import os
import json
import sys
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# Adiciona o diretório atual ao path para que as importações locais funcionem
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

# Carrega configurações do .env localizado na mesma pasta do script
load_dotenv(os.path.join(current_dir, ".env"))

try:
    import pandas as pd
except ImportError:
    pd = None

# Importações da lógica do projeto (ajustadas para o contexto de extracao-diarios)
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

# Configuração de Logs
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(current_dir, "pipeline.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ExtracaoDiarios")

DOCLING_EXTENSIONS = {".pdf", ".docx", ".doc", ".pptx", ".xlsx", ".xls", ".ppt"}

def extract_diario_metadata(filepath, input_dir):
    """Extrai metadados baseados na estrutura de pastas de diários"""
    try:
        # A pasta de entrada geralmente é: dados/diarios-oficiais/Dados-Tabuleiros do Alto Parnaíba-002
        rel_path = os.path.relpath(filepath, input_dir)
        
        # Tenta pegar o nome do município da pasta
        folder_name = os.path.basename(input_dir)
        # Ex: "Dados-Tabuleiros do Alto Parnaíba-002" -> "Tabuleiros do Alto Parnaíba"
        municipio = folder_name.replace("Dados-", "")
        if "-" in municipio:
            # Remove o sufixo numérico se houver
            parts = municipio.split("-")
            if parts[-1].isdigit():
                municipio = "-".join(parts[:-1])
        
        metadata = {
            "municipio": municipio.strip(),
            "pasta_origem": folder_name,
            "nome_arquivo": os.path.basename(filepath),
            "caminho_relativo": rel_path
        }
        return metadata
    except Exception:
        return {}

def process_diarios():
    input_folder = os.getenv("INPUT_FOLDER_PATH")
    output_filename = os.getenv("OUTPUT_FILENAME", "extracao_diarios")
    
    # Resolve o caminho de entrada relativo à raiz do projeto se necessário
    if input_folder and not os.path.isabs(input_folder):
        root_dir = os.path.abspath(os.path.join(current_dir, ".."))
        input_folder = os.path.join(root_dir, input_folder)

    if not input_folder or not os.path.exists(input_folder):
        logger.error(f"INPUT_FOLDER_PATH inválida ou não encontrada: {input_folder}")
        return

    output_base = current_dir
    output_markdown_dir = os.path.join(output_base, "markdown")
    output_images_dir = os.path.join(output_base, "images")
    os.makedirs(output_markdown_dir, exist_ok=True)
    os.makedirs(output_images_dir, exist_ok=True)

    # Coleta arquivos. Diários costumam estar em uma subpasta 'pdfs'
    pdf_dir = os.path.join(input_folder, "pdfs")
    if os.path.exists(pdf_dir):
        all_files = collect_all_files(pdf_dir)
    else:
        all_files = collect_all_files(input_folder)

    jsonl_path = os.path.join(output_base, f"{output_filename}.jsonl")
    
    # Carregar IDs já processados (Resume Logic)
    processed_ids = set()
    if os.path.exists(jsonl_path):
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    processed_ids.add(json.loads(line)["id"])
                except: continue
        logger.info(f"Retomando extração: {len(processed_ids)} arquivos já processados.")

    logger.info(f"Iniciando extração de {len(all_files)} arquivos de {input_folder}...")

    # Instancia o conversor
    doc_converter = instantiate_document_converter(
        generate_picture_images=True,
        generate_full_page_image=False
    )

    count = 0
    total_files = len(all_files)
    
    for filepath in all_files:
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in DOCLING_EXTENSIONS and ext not in HTML_EXTENSIONS and ext not in XML_EXTENSIONS:
            continue

        # ID único baseado no conteúdo e caminho relativo
        # Usa input_folder como referência para o caminho relativo
        record_id = generate_record_id(filepath, os.path.relpath(filepath, input_folder))
        
        if record_id in processed_ids:
            continue

        logger.info(f"[{len(processed_ids) + 1}/{total_files}] Processando: {os.path.basename(filepath)}")
        diario_meta = extract_diario_metadata(filepath, input_folder)
        
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
            
            elif ext in HTML_EXTENSIONS:
                content = extract_text_from_html(filepath)
                status = "EXTRACTED"
                
            elif ext in XML_EXTENSIONS:
                content = convert_xml_to_json(filepath)
                status = "EXTRACTED"

            tokens_count = count_tokens(content) if content else 0
            
            record = {
                "id": record_id,
                **diario_meta,
                "file_format": ext,
                "text_content": content,
                "tokens_count": tokens_count,
                "page_count": page_count,
                "status": status,
                "extraction_timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            # Salva incrementalmente
            with open(jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            
            processed_ids.add(record_id)
            count += 1

        except Exception as e:
            logger.error(f"Erro ao processar {filepath}: {e}")
            error_record = {
                "id": record_id,
                **diario_meta,
                "status": "FAILED",
                "error": str(e),
                "extraction_timestamp": datetime.now(timezone.utc).isoformat()
            }
            with open(jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(error_record, ensure_ascii=False) + "\n")

    logger.info(f"Extração concluída. Total processado nesta rodada: {count}")

    # Exportar Parquet ao final
    if pd and os.path.exists(jsonl_path):
        logger.info("Gerando arquivo Parquet consolidado...")
        try:
            records = []
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    clean_line = line.strip()
                    if not clean_line:
                        continue
                    try:
                        # Remove possíveis aspas simples extras no início/fim (comum em corrupções de log)
                        if clean_line.startswith("'"):
                            clean_line = clean_line.lstrip("'").strip()
                        if clean_line.endswith("'"):
                            clean_line = clean_line.rstrip("'").strip()
                            
                        records.append(json.loads(clean_line))
                    except json.JSONDecodeError as e:
                        logger.warning(f"Linha {i} do JSONL está malformada e será pulada: {e}")
                        continue

            if not records:
                logger.warning("Nenhum registro válido encontrado no JSONL para exportar Parquet.")
                return
            
            df = pd.DataFrame(records)
            parquet_path = os.path.join(output_base, f"{output_filename}.parquet")
            df.to_parquet(parquet_path, index=False)
            logger.info(f"Exportado Parquet: {parquet_path}")
        except Exception as e:
            logger.error(f"Erro ao salvar Parquet: {e}")

if __name__ == "__main__":
    # Otimização de memória
    os.environ["PYTORCH_ALLOC_CONF"] = "expandable_segments:True"
    
    try:
        process_diarios()
    except KeyboardInterrupt:
        logger.info("Processo interrompido pelo usuário.")
    except Exception as e:
        logger.critical(f"Erro fatal na pipeline: {e}")
        traceback.print_exc()
