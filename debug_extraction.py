import sys
from docling.document_converter import DocumentConverter
from pathlib import Path
import os

def test_single_file(path):
    print(f"Testando: {path}")
    converter = DocumentConverter()
    try:
        result = converter.convert(path)
        markdown = result.document.export_to_markdown()
        print(f"Markdown extraído ({len(markdown)} chars):")
        print(markdown[:500])
    except Exception as e:
        print(f"Erro no Docling: {e}")

if __name__ == "__main__":
    # Prioriza diários oficiais, depois docentes
    search_dirs = ["data/raw/diario_oficial", "data/raw/docentes"]
    
    found = False
    for base_dir in search_dirs:
        if not os.path.exists(base_dir):
            continue
        for root, dirs, files in os.walk(base_dir):
            for f in files:
                if f.endswith(".pdf"):
                    test_single_file(os.path.join(root, f))
                    found = True
                    break
            if found: break
        if found: break
    
    if not found:
        print("Nenhum arquivo PDF encontrado para teste.")
