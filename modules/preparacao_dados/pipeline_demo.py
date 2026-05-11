import os
import hashlib
import pandas as pd
from pathlib import Path
from docling.document_converter import DocumentConverter

def get_file_id(filepath):
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()[:16]

def run_demo():
    input_dirs = ["data/raw/docentes"]
    output_dir = "data/processed"
    converter = DocumentConverter()
    records = []
    
    count = 0
    for d in input_dirs:
        for root, _, files in os.walk(d):
            for f in files:
                if count > 20: break
                path = os.path.join(root, f)
                if not f.endswith('.pdf'): continue
                print(f"Demo: {f}")
                try:
                    res = converter.convert(path)
                    text = res.document.export_to_markdown()
                    records.append({
                        "id": get_file_id(path),
                        "filename": f,
                        "text_content": text,
                        "char_count": len(text)
                    })
                    count += 1
                except: pass
    
    if records:
        df = pd.DataFrame(records)
        df.to_parquet(os.path.join(output_dir, "dataset_consolidado.parquet"), index=False)
        print("Demo concluída. Parquet atualizado.")

if __name__ == "__main__":
    run_demo()
