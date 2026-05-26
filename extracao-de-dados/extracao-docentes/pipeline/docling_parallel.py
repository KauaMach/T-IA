import asyncio
import functools
import logging
import os
import shutil
import tempfile
import traceback
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from src.mfe.artifacts.token_count import count_tokens
from src.mfe.constants import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS
from src.mfe.extractors.docling_pdf import single_extraction
from src.mfe.extractors.video import extract_audio_content, extract_video_content
from src.mfe.ingest.class_metadata import get_class_metadata
from src.mfe.ingest.unzip import extract_file, is_compressed

from .utils import (
    BATCH_SIZE,
    HTML_EXTENSIONS,
    XML_EXTENSIONS,
    collect_all_files,
    convert_xml_to_json,
    extract_text_from_html,
    generate_record_id,
    make_save_batch_final,
)

DOCLING_EXTENSIONS = {".pdf", ".docx", ".doc", ".pptx", ".xlsx", ".xls", ".ppt"}

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")


def _process_file_worker(
    filepath: str,
    relative_filepath: str,
    db_url: str,
    pipeline_name: str,
    output_text_dir: str,
    output_images_dir: str,
    output_markdown_dir: str,
    file_metadata_lookup: dict,
    logger_name: str,
    error_logger_name: str,
) -> dict | None:
    """
    Executada em um processo separado do pool. Cada processo cria sua própria
    engine e sessão SQLAlchemy para evitar conflitos entre processos.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.mfe.db.db_metadata import should_process_file, upsert_record

    logger = logging.getLogger(logger_name)
    error_logger = logging.getLogger(error_logger_name)

    engine = create_engine(db_url)
    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()
    try:
        logger.info(f"\nProcessando: {filepath}")
        ext = Path(filepath).suffix.lower()

        record_id = generate_record_id(filepath, relative_filepath)

        if not should_process_file(session, record_id, pipeline_name):
            logger.info(f"[SKIP] Já extraído: {relative_filepath}")
            return None

        text_output_path = os.path.join(output_text_dir, f"{record_id}.txt")
        images_output_path = os.path.join(output_images_dir, record_id)

        text_file_s3_uri = f"output/docling/text_file/{record_id}.txt"
        images_s3_uri = f"output/docling/images/{record_id}/"

        start_dt = datetime.now(timezone.utc)
        status = "FAILED"
        tokens_count = 0
        page_count = None
        error_log = None

        upsert_record(
            session,
            {
                "id": record_id,
                "filepath": relative_filepath,
                "file_format": ext,
                "status": "IN_PROGRESS",
                "extraction_started": start_dt.isoformat(),
            },
            pipeline_name,
        )

        try:
            if ext in HTML_EXTENSIONS:
                content = extract_text_from_html(filepath)

                with open(text_output_path, "w", encoding="utf-8") as f:
                    f.write(content)
                tokens_count = count_tokens(content)

                status = "EXTRACTED"
            elif ext in XML_EXTENSIONS:
                content = convert_xml_to_json(filepath)

                with open(text_output_path, "w", encoding="utf-8") as f:
                    f.write(content)
                tokens_count = count_tokens(content)

                status = "EXTRACTED"
            elif ext in DOCLING_EXTENSIONS:
                markdown_path, page_count = single_extraction(
                    doc_path=filepath,
                    output_folder=output_markdown_dir,
                    images_output_dir=images_output_path,
                )

                with open(markdown_path, "r", encoding="utf-8") as f:
                    content = f.read()
                with open(text_output_path, "w", encoding="utf-8") as f:
                    f.write(content)

                tokens_count = count_tokens(content)
                status = "EXTRACTED"
            elif ext in AUDIO_EXTENSIONS:
                content = asyncio.run(
                    extract_audio_content(
                        audio_path=filepath,
                        groq_api_key=GROQ_API_KEY,
                    )
                )

                with open(text_output_path, "w", encoding="utf-8") as f:
                    f.write(content)
                tokens_count = count_tokens(content)

                status = "EXTRACTED"
            elif ext in VIDEO_EXTENSIONS:
                content = asyncio.run(
                    extract_video_content(
                        video_path=filepath,
                        groq_api_key=GROQ_API_KEY,
                        local_base_directory=images_output_path,
                        use_frame_ocr=True,
                    )
                )

                with open(text_output_path, "w", encoding="utf-8") as f:
                    f.write(content)
                tokens_count = count_tokens(content)

                status = "EXTRACTED"
            else:
                logger.info(
                    f"[EXTRACTED] Extensão sem necessidade de extração: {ext} → {relative_filepath}"
                )

                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                with open(text_output_path, "w", encoding="utf-8") as f:
                    f.write(content)
                tokens_count = 0

                try:
                    tokens_count = count_tokens(content)
                except Exception as e:
                    error_logger.error(
                        f"[ERROR] Falha ao contar tokens em {relative_filepath}: {e}"
                    )
                    traceback.print_exc()

                status = "EXTRACTED"

        except Exception as e:
            error_log = traceback.format_exc()
            error_logger.error(f"[ERROR] {relative_filepath}: {e}")
            traceback.print_exc()

        end_dt = datetime.now(timezone.utc)

        record = {
            "id": record_id,
            "filepath": relative_filepath,
            "file_format": ext,
            "status": status,
            "tokens_count": tokens_count,
            "page_count": page_count,
            "text_file_s3_uri": text_file_s3_uri,
            "images_s3_uri": images_s3_uri,
            "extraction_started": start_dt.isoformat(),
            "extraction_finished": end_dt.isoformat(),
            "extraction_duration_in_seconds": (end_dt - start_dt).total_seconds(),
            "class_metadata": get_class_metadata(
                relative_filepath, file_metadata_lookup
            ),
            "error_log": error_log,
        }

        upsert_record(session, record, pipeline_name)
        return record

    finally:
        session.close()
        engine.dispose()


async def run_docling_pipeline_parallel(
    root_dir: str,
    files_to_rename_dir: str,
    output_base: str,
    logger,
    error_logger,
    engine,
    pipeline_name: str,
    file_metadata_lookup: dict,
    max_workers: int = 4,
) -> tuple:
    """
    Versão paralela da pipeline Docling usando ProcessPoolExecutor.

    Docling é CPU/GPU intensivo, portanto usa processos para paralelismo real,
    contornando o GIL do Python. Cada processo cria sua própria engine e sessão
    SQLAlchemy de forma isolada.

    Args:
        engine:      SQLAlchemy Engine (usado apenas para extrair a URL de conexão).
        max_workers: número máximo de processos simultâneos. Controla uso de RAM/GPU.
                     Reduza se houver estouro de memória.
    """
    from sqlalchemy.orm import sessionmaker

    from src.mfe.db.db_metadata import (
        check_sequence_exists,
        get_next_batch_index,
    )

    SessionFactory = sessionmaker(bind=engine)

    _check_session = SessionFactory()
    try:
        if not check_sequence_exists(_check_session):
            error_logger.error(
                "A sequence 'jsonl_batch_seq' não foi encontrada no banco de dados. "
                "Execute o seguinte comando no banco correspondente para criá-la:\n"
                "  CREATE SEQUENCE jsonl_batch_seq START WITH 0 MINVALUE 0 INCREMENT BY 1;"
            )
            raise RuntimeError(
                "Sequence 'jsonl_batch_seq' não existe. Crie-a antes de executar a pipeline. Execute CREATE SEQUENCE jsonl_batch_seq START WITH 0 MINVALUE 0 INCREMENT BY 1;"
            )
    finally:
        _check_session.close()

    output_jsonl_final_dir = os.path.join(output_base, "jsonl_final")
    output_text_dir = os.path.join(output_base, "text_files")
    output_images_dir = os.path.join(output_base, "images")
    output_markdown_dir = os.path.join(output_base, "markdown")

    for d in [
        output_jsonl_final_dir,
        output_text_dir,
        output_images_dir,
        output_markdown_dir,
    ]:
        os.makedirs(d, exist_ok=True)

    save_batch = make_save_batch_final(output_jsonl_final_dir, output_text_dir, logger)

    # Fase 1: coleta todos os pares (filepath, relative_filepath),
    # expandindo arquivos comprimidos de forma síncrona.
    all_files = collect_all_files(files_to_rename_dir)
    logger.info(f"Arquivos encontrados: {len(all_files)} | Workers: {max_workers}")

    file_pairs: list[tuple[str, str]] = []
    temp_dirs: list[str] = []

    for filepath in all_files:
        if is_compressed(filepath):
            logger.info(f"\n[COMPRESSED] Extraindo: {filepath}")
            zip_relative = os.path.relpath(filepath, root_dir)
            try:
                tmpdir = tempfile.mkdtemp()
                temp_dirs.append(tmpdir)
                extract_file(filepath, tmpdir)
                for extracted_path in collect_all_files(tmpdir):
                    internal_path = os.path.relpath(extracted_path, tmpdir)
                    file_pairs.append(
                        (extracted_path, f"{zip_relative}/{internal_path}")
                    )
            except Exception as e:
                error_logger.error(f"[ERROR] Falha ao extrair {filepath}: {e}")
        else:
            file_pairs.append((filepath, os.path.relpath(filepath, root_dir)))

    logger.info(f"Total de arquivos a processar (após extração): {len(file_pairs)}")

    # Fase 2: processa em paralelo usando ProcessPoolExecutor.
    # max_workers controla diretamente quantos documentos são processados
    # ao mesmo tempo — reduza para limitar uso de RAM/GPU.
    # Salva em batches progressivamente conforme cada tarefa termina.

    db_url = engine.url.render_as_string(hide_password=False)
    worker = functools.partial(
        _process_file_worker,
        db_url=db_url,
        pipeline_name=pipeline_name,
        output_text_dir=output_text_dir,
        output_images_dir=output_images_dir,
        output_markdown_dir=output_markdown_dir,
        file_metadata_lookup=file_metadata_lookup,
        logger_name=logger.name,
        error_logger_name=error_logger.name,
    )

    pipeline_start = datetime.now(timezone.utc)
    loop = asyncio.get_running_loop()
    records = []

    try:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                loop.run_in_executor(executor, worker, fp, rel)
                for fp, rel in file_pairs
            ]
            for future in asyncio.as_completed(futures):
                try:
                    result = await future
                    if result is None:
                        continue
                    records.append(result)
                    if len(records) >= BATCH_SIZE:
                        session = SessionFactory()
                        try:
                            batch_idx = get_next_batch_index(session)
                        finally:
                            session.close()
                        save_batch(records, batch_idx)
                        records = []
                except Exception as e:
                    error_logger.error(f"[ERROR] Tarefa falhou: {e}")
    finally:
        for tmpdir in temp_dirs:
            shutil.rmtree(tmpdir, ignore_errors=True)

    if records:
        session = SessionFactory()
        try:
            batch_idx = get_next_batch_index(session)
        finally:
            session.close()
        save_batch(records, batch_idx)

    total_seconds = (datetime.now(timezone.utc) - pipeline_start).total_seconds()
    logger.info(
        f"\nPipeline Docling (paralela) concluída! {len(file_pairs)} arquivos processados. "
        f"Tempo total: {total_seconds:.1f}s"
    )

    return output_jsonl_final_dir, output_text_dir
