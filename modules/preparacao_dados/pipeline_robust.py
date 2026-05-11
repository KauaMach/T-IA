import os
import hashlib
import pandas as pd
from pathlib import Path
from docling.document_converter import DocumentConverter
import pytesseract
from PIL import Image
import pdf2image

def get_file_id(filepath):
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()[:16]

def extract_content(path, converter):
    ext = Path(path).suffix.lower()
    content = ""
    try:
        if ext in ['.pdf', '.docx', '.pptx', '.xlsx']:
            res = converter.convert(path)
            content = res.document.export_to_markdown()
        elif ext in ['.txt', '.log', '.csv']:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
    except Exception as e:
        print(f"Erro em {path}: {e}")
    return content

def run_pipeline():
    input_dirs = ["data/raw/docentes", "data/raw/diario_oficial"]
    output_dir = "data/processed"
    txt_dir = os.path.join(output_dir, "txt")
    os.makedirs(txt_dir, exist_ok=True)
    
    converter = DocumentConverter()
    
    all_files = []
    for d in input_dirs:
        if not os.path.exists(d): continue
        for root, _, files in os.walk(d):
            for f in files:
                if f == "docentes_arquivos.csv": continue
                all_files.append(os.path.join(root, f))
    
    print(f"Total de arquivos encontrados: {len(all_files)}")
    
    records = []
    parquet_file = os.path.join(output_dir, "dataset_consolidado.parquet")
    
    # Processar em batches de 100 para persistência frequente
    batch_size = 100
    for i in range(0, len(all_files), batch_size):
        batch = all_files[i : i + batch_size]
        batch_records = []
        
        for path in batch:
            file_id = get_file_id(path)
            txt_path = os.path.join(txt_dir, f"{file_id}.txt")
            
            # Se já existe e não está vazio, skip
            if os.path.exists(txt_path) and os.path.getsize(txt_path) > 10:
                continue
                
            content = extract_content(path, converter)
            if not content.strip():
                content = "[Extração vazia]"
            
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(content)
                
            batch_records.append({
                "id": file_id,
                "filename": os.path.basename(path),
                "format": Path(path).suffix.lower(),
                "text_content": content,
                "char_count": len(content)
            })
        
        if batch_records:
            df_batch = pd.DataFrame(batch_records)
            if os.path.exists(parquet_file):
                df_old = pd.read_parquet(parquet_file)
                df_final = pd.concat([df_old, df_batch], ignore_index=True).drop_duplicates(subset=['id'], keep='last')
            else:
                df_final = df_batch
            
            df_final.to_parquet(parquet_file, index=False)
            print(f"Processados {min(i + batch_size, len(all_files))}/{len(all_files)}...")

if __name__ == "__main__":
    run_pipeline()
