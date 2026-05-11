import sys
from docling.document_converter import DocumentConverter
from pathlib import Path

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
    # Pega o primeiro PDF que encontrar em data/raw/docentes
    import os
    for root, dirs, files in os.walk("data/raw/docentes"):
        for f in files:
            if f.endswith(".pdf"):
                test_single_file(os.path.join(root, f))
                sys.exit(0)
