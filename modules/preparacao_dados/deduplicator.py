import os
import hashlib
import pandas as pd
from pathlib import Path
import logging

# Configuração de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_file_hash(filepath: str) -> str:
    """Calcula o hash SHA256 de um arquivo para identificação única."""
    hasher = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
    except Exception as e:
        logger.error(f"Erro ao calcular hash de {filepath}: {e}")
        return None
    return hasher.hexdigest()

def deduplicate_raw(base_paths: list):
    """
    Remove duplicatas exatas nos diretórios de entrada (data/raw).
    Lida com redundâncias de conteúdo independentemente do nome do arquivo.
    """
    logger.info("--- Iniciando Deduplicação de Arquivos RAW ---")
    seen_hashes = {}
    count_removed = 0

    for base_path in base_paths:
        if not os.path.exists(base_path):
            logger.warning(f"Caminho não encontrado: {base_path}")
            continue
            
        for root, _, files in os.walk(base_path):
            for file in files:
                # Ignorar arquivos de controle ou metadados
                if file.endswith('.csv') or file.endswith('.md') or file.startswith('.'):
                    continue
                
                filepath = os.path.join(root, file)
                f_hash = get_file_hash(filepath)
                
                if not f_hash:
                    continue

                if f_hash in seen_hashes:
                    logger.info(f"Removendo duplicata: {filepath} (Original: {seen_hashes[f_hash]})")
                    try:
                        os.remove(filepath)
                        count_removed += 1
                    except Exception as e:
                        logger.error(f"Erro ao remover {filepath}: {e}")
                else:
                    seen_hashes[f_hash] = filepath
                    
    logger.info(f"Total de arquivos RAW duplicados removidos: {count_removed}")
    return count_removed

def deduplicate_dataset(parquet_path: str):
    """
    Remove duplicatas no dataset consolidado baseado no conteúdo extraído.
    """
    if not os.path.exists(parquet_path):
        return

    logger.info(f"--- Iniciando Deduplicação no Dataset: {parquet_path} ---")
    try:
        df = pd.read_parquet(parquet_path)
        initial_len = len(df)
        
        # Remove duplicatas baseadas no ID (hash do arquivo) e no conteúdo de texto
        df_clean = df.drop_duplicates(subset=['id'])
        df_clean = df_clean.drop_duplicates(subset=['text_content'])
        
        if len(df_clean) < initial_len:
            df_clean.to_parquet(parquet_path, index=False)
            logger.info(f"Registros duplicados removidos no Parquet: {initial_len - len(df_clean)}")
        else:
            logger.info("Nenhuma duplicata encontrada no dataset.")
    except Exception as e:
        logger.error(f"Erro ao deduplicar dataset: {e}")

if __name__ == "__main__":
    raw_dirs = ["data/raw/diario_oficial", "data/raw/docentes"]
    processed_parquet = "data/processed/dataset_consolidado.parquet"
    
    deduplicate_raw(raw_dirs)
    deduplicate_dataset(processed_parquet)
