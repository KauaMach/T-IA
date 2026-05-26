import asyncio
import os
import shutil
import tempfile
import traceback
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image

from src.mfe.artifacts.token_count import count_tokens
from src.mfe.constants import (
    AUDIO_EXTENSIONS,
    IMAGE_EXTENSIONS,
    OFFICE_EXTENSIONS,
    RAW_FILE_EXTENSIONS,
    VIDEO_EXTENSIONS,
)
from src.mfe.converters.soffice import convert_office_to_pdf
from src.mfe.db.db_metadata import (
    async_check_sequence_exists,
    async_get_next_batch_index,
    async_should_process_file,
    async_upsert_record,
)
from src.mfe.extractors.deepseek_ocr import extract_text_from_image_bytes
from src.mfe.extractors.enums.ocr_type import OCRModel
from src.mfe.extractors.ocr import ocr_pdf
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

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")


async def run_deepseek_pipeline_parallel(
    root_dir: str,
    files_to_rename_dir: str,
    output_base: str,
    logger,
    error_logger,
    async_session_factory,
    pipeline_name: str,
    file_metadata_lookup: dict,
    concurrency: int = 2,
    page_concurrency: int = 4,
) -> tuple:
    """
    Versão paralela da pipeline DeepSeek.

    Usa asyncio.Semaphore para limitar quantos arquivos são processados
    simultaneamente, evitando estouro de memória GPU ou limites de API.

    Args:
        concurrency:      máximo de arquivos processados simultaneamente.
        page_concurrency: máximo de páginas de um PDF enviadas ao vLLM ao mesmo tempo.
                          Deve satisfazer: concurrency × page_concurrency ≤ --max-num-seqs do vLLM.
    """
    async with async_session_factory() as session:
        if not await async_check_sequence_exists(session):
            error_logger.error(
                "[ERROR] A sequence 'jsonl_batch_seq' não foi encontrada no banco de dados. "
                "Execute o seguinte comando no banco correspondente para criá-la:\n"
                "  CREATE SEQUENCE jsonl_batch_seq START WITH 0 MINVALUE 0 INCREMENT BY 1;"
            )
            raise RuntimeError("Sequence 'jsonl_batch_seq' não existe. Crie-a antes de executar a pipeline.")

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
    semaphore = asyncio.Semaphore(concurrency)

    def image_to_png_bytes(file_path: str) -> bytes:
        img = Image.open(file_path).convert("RGB")
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    async def process_file(filepath: str, relative_filepath: str) -> dict | None:
        async with semaphore:
            logger.info(f"\nProcessando: {filepath}")
            ext = Path(filepath).suffix.lower()

            record_id = await asyncio.to_thread(
                generate_record_id, filepath, relative_filepath
            )

            async with async_session_factory() as session:
                if not await async_should_process_file(
                    session, record_id, pipeline_name
                ):
                    logger.info(f"[SKIP] Já extraído: {relative_filepath}")
                    return None
            text_output_path = os.path.join(output_text_dir, f"{record_id}.txt")
            images_output_path = os.path.join(output_images_dir, record_id)

            text_file_s3_uri = f"output/deep_seek_2/text_file/{record_id}.txt"
            images_s3_uri = f"output/deep_seek_2/images/{record_id}/"

            start_dt = datetime.now(timezone.utc)
            status = "FAILED"
            tokens_count = 0
            page_count = None
            error_log = None

            async with async_session_factory() as session:
                await async_upsert_record(
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
                    content = await asyncio.to_thread(extract_text_from_html, filepath)

                    with open(text_output_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    tokens_count = await asyncio.to_thread(count_tokens, content)

                    status = "EXTRACTED"
                elif ext in XML_EXTENSIONS:
                    content = await asyncio.to_thread(convert_xml_to_json, filepath)

                    with open(text_output_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    tokens_count = await asyncio.to_thread(count_tokens, content)

                    status = "EXTRACTED"
                elif ext in IMAGE_EXTENSIONS:
                    image_bytes = await asyncio.to_thread(image_to_png_bytes, filepath)
                    content = await extract_text_from_image_bytes(
                        image_bytes=image_bytes,
                        local_base_directory=images_output_path,
                        upload_s3_enabled=False,
                    )

                    with open(text_output_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    tokens_count = await asyncio.to_thread(count_tokens, content)

                    status = "EXTRACTED"
                elif ext in OFFICE_EXTENSIONS or ext in RAW_FILE_EXTENSIONS:
                    pdf_path = filepath
                    tmp_pdf = None

                    if ext in OFFICE_EXTENSIONS:
                        tmp_fd, tmp_pdf = tempfile.mkstemp(suffix=".pdf")
                        os.close(tmp_fd)
                        await asyncio.to_thread(
                            convert_office_to_pdf, filepath, tmp_pdf
                        )
                        pdf_path = tmp_pdf

                    try:
                        text, page_count = await ocr_pdf(
                            pdf_path=pdf_path,
                            ocr_model=OCRModel.DEEPSEEK,
                            local_base_directory=images_output_path,
                            local_limit_quantity=page_concurrency,
                            upload_s3_enabled=False,
                        )
                    finally:
                        if tmp_pdf and os.path.exists(tmp_pdf):
                            os.remove(tmp_pdf)

                    with open(text_output_path, "w", encoding="utf-8") as f:
                        f.write(text)

                    tokens_count = await asyncio.to_thread(count_tokens, text)
                    status = "EXTRACTED"
                elif ext in AUDIO_EXTENSIONS:
                    content = await extract_audio_content(
                        audio_path=filepath,
                        groq_api_key=GROQ_API_KEY,
                    )

                    with open(text_output_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    tokens_count = await asyncio.to_thread(count_tokens, content)

                    status = "EXTRACTED"
                elif ext in VIDEO_EXTENSIONS:
                    content = await extract_video_content(
                        video_path=filepath,
                        groq_api_key=GROQ_API_KEY,
                        local_base_directory=images_output_path,
                        use_frame_ocr=True,
                    )

                    with open(text_output_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    tokens_count = await asyncio.to_thread(count_tokens, content)

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
                        tokens_count = await asyncio.to_thread(count_tokens, content)
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

            async with async_session_factory() as session:
                await async_upsert_record(session, record, pipeline_name)
            return record

    # Fase 1: coleta todos os pares (filepath, relative_filepath),
    # expandindo arquivos comprimidos de forma síncrona.
    all_files = collect_all_files(files_to_rename_dir)
    logger.info(f"Arquivos encontrados: {len(all_files)} | Concorrência: {concurrency}")

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

    # Fase 2: processa todos em paralelo, limitado pelo semáforo.
    pipeline_start = datetime.now(timezone.utc)
    records = []
    try:
        tasks = [process_file(fp, rel) for fp, rel in file_pairs]
        for coro in asyncio.as_completed(tasks):
            try:
                result = await coro
                if result is None:
                    continue
                records.append(result)
                if len(records) >= BATCH_SIZE:
                    async with async_session_factory() as session:
                        batch_idx = await async_get_next_batch_index(session)
                    save_batch(records, batch_idx)
                    records = []
            except Exception as e:
                error_logger.error(f"[ERROR] Tarefa falhou: {e}")
    finally:
        for tmpdir in temp_dirs:
            shutil.rmtree(tmpdir, ignore_errors=True)

    if records:
        async with async_session_factory() as session:
            batch_idx = await async_get_next_batch_index(session)
        save_batch(records, batch_idx)

    total_seconds = (datetime.now(timezone.utc) - pipeline_start).total_seconds()
    logger.info(
        f"\nPipeline DeepSeek (paralela) concluída! {len(file_pairs)} arquivos processados. "
        f"Tempo total: {total_seconds:.1f}s"
    )

    return output_jsonl_final_dir, output_text_dir
