import os
import hashlib
import json
import pandas as pd
from pathlib import Path

def get_file_hash(filepath):
    """Calcula o hash SHA256 de um arquivo para identificação única."""
    hasher = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
    except Exception as e:
        return None
    return hasher.hexdigest()

def deduplicate_raw(base_paths):
    """
    Remove duplicatas exatas nos diretórios de entrada (data/raw).
    Lida com o padrão de IDs dos docentes (12345-Arquivo.pdf).
    """
    print("--- Iniciando Deduplicação Pré-Processamento (RAW) ---")
    seen_hashes = {}
    count_removed = 0

    for base_path in base_paths:
        if not os.path.exists(base_path):
            continue
            
        for root, _, files in os.walk(base_path):
            for file in files:
                if file.endswith('.csv') or file.endswith('.md'): continue
                
                filepath = os.path.join(root, file)
                f_hash = get_file_hash(filepath)
                
                if f_hash in seen_hashes:
                    print(f"[RAW] Removendo duplicata: {filepath} (Original: {seen_hashes[f_hash]})")
                    os.remove(filepath)
                    count_removed += 1
                else:
                    seen_hashes[f_hash] = filepath
                    
    print(f"Total de arquivos RAW removidos: {count_removed}")

def deduplicate_processed(processed_path):
    """
    Limpa o conteúdo extraído no data/processed se houver duplicatas de conteúdo.
    """
    print("--- Iniciando Deduplicação Pós-Processamento (PROCESSED) ---")
    parquet_path = os.path.join(processed_path, "dataset_consolidado.parquet")
    
    if not os.path.exists(parquet_path):
        print("Nenhum arquivo Parquet consolidado encontrado para deduplicação pós.")
        return

    df = pd.read_parquet(parquet_path)
    initial_len = len(df)
    
    # Remove duplicatas baseadas no hash do conteúdo extraído (text_content)
    df_clean = df.drop_duplicates(subset=['text_content'])
    
    if len(df_clean) < initial_len:
        df_clean.to_parquet(parquet_path, index=False)
        print(f"Registros duplicados removidos no Parquet: {initial_len - len(df_clean)}")
    else:
        print("Nenhuma duplicata de conteúdo encontrada no Parquet.")

if __name__ == "__main__":
    raw_dirs = ["data/raw/docentes", "data/raw/diario_oficial"]
    processed_dir = "data/processed"
    
    deduplicate_raw(raw_dirs)
    deduplicate_processed(processed_dir)
