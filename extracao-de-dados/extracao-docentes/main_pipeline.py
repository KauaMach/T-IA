import os
import json
import sys
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path

# Adiciona o diretório atual ao path para que 'import src' funcione
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

try:
    import pandas as pd
except ImportError:
    pd = None

# Importações da lógica migrada (ajustadas para usar src.)
from src.mfe.extractors.docling_pdf import single_extraction, instantiate_document_converter
from src.mfe.artifacts.token_count import count_tokens
from pipeline.utils import (
    collect_all_files,
    generate_record_id,
    HTML_EXTENSIONS,
    XML_EXTENSIONS,
    extract_text_from_html,
    convert_xml_to_json,
)

# Configuração de Logs básica (como no curso)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ExtracaoDocentes")

DOCLING_EXTENSIONS = {".pdf", ".docx", ".doc", ".pptx", ".xlsx", ".xls", ".ppt"}

def extract_docente_metadata(filepath, root_dir):
    """Extrai metadados baseados na estrutura de pastas específica de dados/docentes"""
    try:
        rel_path = os.path.relpath(filepath, root_dir)
        parts = rel_path.split(os.sep)
        
        # Estrutura esperada: {Docente}/{Ano}/{Mes}/{Dia}/{Arquivo}
        metadata = {
            "docente": parts[0] if len(parts) > 0 else "Desconhecido",
            "ano": parts[1] if len(parts) > 1 else None,
            "mes": parts[2] if len(parts) > 2 else None,
            "dia": parts[3] if len(parts) > 3 else None,
            "nome_arquivo": os.path.basename(filepath),
            "caminho_relativo": rel_path
        }
        return metadata
    except Exception:
        return {}

def process_docentes(input_dir, output_base):
    output_markdown_dir = os.path.join(output_base, "markdown")
    output_images_dir = os.path.join(output_base, "images")
    os.makedirs(output_markdown_dir, exist_ok=True)
    os.makedirs(output_images_dir, exist_ok=True)

    all_files = collect_all_files(input_dir)
    records = []

    logger.info(f"Iniciando extração de {len(all_files)} arquivos...")

    # Instancia o conversor uma única vez para reaproveitamento
    doc_converter = instantiate_document_converter(
        generate_picture_images=True,
        generate_full_page_image=True
    )

    for filepath in all_files:
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in DOCLING_EXTENSIONS and ext not in HTML_EXTENSIONS and ext not in XML_EXTENSIONS:
            continue

        record_id = generate_record_id(filepath, os.path.relpath(filepath, input_dir))
        
        # Pular arquivos já processados (Resume Logic)
        if record_id in processed_ids:
            logger.info(f"Pulando (já extraído): {filepath}")
            continue

        logger.info(f"Processando: {filepath}")
        docente_meta = extract_docente_metadata(filepath, input_dir)
        
        start_dt = datetime.now(timezone.utc)
        content = ""
        page_count = None
        status = "FAILED"

        try:
            if ext in DOCLING_EXTENSIONS:
                images_path = os.path.join(output_images_dir, record_id)
                md_path, page_count = single_extraction(
                    doc_path=filepath,
                    output_folder=output_markdown_dir,
                    images_output_dir=images_path,
                    doc_converter=doc_converter
                )
                if md_path and os.path.exists(md_path):
                    with open(md_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    status = "EXTRACTED"
                else:
                    logger.error(f"Falha na extração de {filepath}: Arquivo markdown não gerado.")
                    status = "FAILED"
            
            elif ext in HTML_EXTENSIONS:
                content = extract_text_from_html(filepath)
                status = "EXTRACTED"
                
            elif ext in XML_EXTENSIONS:
                content = convert_xml_to_json(filepath)
                status = "EXTRACTED"

            tokens_count = count_tokens(content) if content else 0
            
            record = {
                "id": record_id,
                **docente_meta,
                "file_format": ext,
                "text_content": content,
                "tokens_count": tokens_count,
                "page_count": page_count,
                "status": status,
                "extraction_timestamp": datetime.now(timezone.utc).isoformat()
            }
            records.append(record)

        except Exception as e:
            logger.error(f"Erro em {filepath}: {e}")
            traceback.print_exc()

    # Salvamento Final
    if not records:
        logger.warning("Nenhum registro extraído.")
        return

    # Exportar JSONL
    jsonl_path = os.path.join(output_base, "docentes_completo.jsonl")
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    logger.info(f"Exportado JSONL: {jsonl_path}")

    # Exportar Parquet
    if pd:
        df = pd.DataFrame(records)
        parquet_path = os.path.join(output_base, "docentes_completo.parquet")
        try:
            df.to_parquet(parquet_path, index=False)
            logger.info(f"Exportado Parquet: {parquet_path}")
        except Exception as e:
            logger.error(f"Erro ao salvar Parquet: {e}")
    else:
        logger.warning("Pandas não instalado. Parquet não gerado.")

if __name__ == "__main__":
    # Otimização de memória para máquinas com 6GB de VRAM ou menos
    os.environ["PYTORCH_ALLOC_CONF"] = "expandable_segments:True"
    
    # Define caminhos relativos ao diretório raiz do projeto
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    INPUT = os.path.join(BASE_DIR, "dados", "docentes")
    OUTPUT = os.path.join(BASE_DIR, "extracao-docentes")
    
    # Carregar IDs já processados para permitir "Resume"
    processed_ids = set()
    jsonl_path = os.path.join(OUTPUT, "docentes_completo.jsonl")
    if os.path.exists(jsonl_path):
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    processed_ids.add(json.loads(line)["id"])
                except: continue
        logger.info(f"Retomando extração: {len(processed_ids)} arquivos já processados.")

    # Verifica se a pasta de entrada existe
    if not os.path.exists(INPUT):
        logger.error(f"Pasta de entrada não encontrada: {INPUT}")
        sys.exit(1)
        
    process_docentes(INPUT, OUTPUT)
