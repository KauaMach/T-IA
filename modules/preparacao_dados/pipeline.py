import os
import hashlib
import json
import pandas as pd
from pathlib import Path
import asyncio
from typing import List

try:
    from docling.document_converter import DocumentConverter
    import pytesseract
    from PIL import Image
    import pdf2image
except ImportError:
    pass

class DataPipeline:
    def __init__(self, input_dirs: List[str], output_dir: str):
        self.input_dirs = input_dirs
        self.output_dir = output_dir
        self.text_dir = os.path.join(output_dir, "txt")
        try:
            self.converter = DocumentConverter()
        except Exception:
            self.converter = None
            print("Aviso: DocumentConverter (Docling) não disponível. Usando fallback OCR.")
        
        os.makedirs(self.text_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

    def get_file_id(self, filepath: str) -> str:
        hasher = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()[:16]

    def extract_with_tesseract(self, filepath: str) -> str:
        ext = Path(filepath).suffix.lower()
        text = ""
        try:
            if ext == '.pdf':
                images = pdf2image.convert_from_path(filepath, last_page=3) # Reduzido para 3 pgs para teste
                for img in images:
                    text += pytesseract.image_to_string(img, lang='por+eng') + "\n"
            elif ext in ['.png', '.jpg', '.jpeg', '.tiff']:
                text = pytesseract.image_to_string(Image.open(filepath), lang='por+eng')
        except Exception as e:
            text = f"[OCR Error] {e}"
        return text

    def process_file(self, filepath: str):
        ext = Path(filepath).suffix.lower()
        file_id = self.get_file_id(filepath)
        output_txt = os.path.join(self.text_dir, f"{file_id}.txt")
        
        # Forçamos reprocessamento se o TXT estiver vazio (para corrigir falha anterior)
        if os.path.exists(output_txt) and os.path.getsize(output_txt) > 10:
            return None 

        content = ""
        try:
            if ext in ['.pdf', '.docx', '.pptx', '.xlsx']:
                if self.converter:
                    try:
                        result = self.converter.convert(filepath)
                        content = result.document.export_to_markdown()
                    except:
                        content = ""
                
                if len(content.strip()) < 50 and ext == '.pdf':
                    content = self.extract_with_tesseract(filepath)
            
            elif ext in ['.txt', '.log', '.csv']:
                with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
            
            elif ext in ['.rtf', '.odt', '.png', '.jpg', '.jpeg']:
                content = self.extract_with_tesseract(filepath)
                
        except Exception as e:
            content = f"[Error] {e}"

        if not content: content = "[Nenhum texto extraído]"

        with open(output_txt, 'w', encoding='utf-8') as f:
            f.write(content)
            
        return {
            "id": file_id,
            "filename": os.path.basename(filepath),
            "path": filepath,
            "format": ext,
            "text_content": content,
            "char_count": len(content)
        }

    def run(self):
        all_records = []
        # Para o teste, vamos processar apenas uma amostra se for muito grande
        # mas aqui processaremos tudo, focando nos que falharam (vazios)
        for input_dir in self.input_dirs:
            if not os.path.exists(input_dir): continue
            for root, _, files in os.walk(input_dir):
                for file in files:
                    if file == "docentes_arquivos.csv": continue
                    filepath = os.path.join(root, file)
                    record = self.process_file(filepath)
                    if record:
                        all_records.append(record)

        if all_records:
            df = pd.DataFrame(all_records)
            parquet_file = os.path.join(self.output_dir, "dataset_consolidado.parquet")
            
            if os.path.exists(parquet_file):
                old_df = pd.read_parquet(parquet_file)
                # Atualiza os registros existentes com os novos (que agora têm conteúdo)
                df = pd.concat([df, old_df], ignore_index=True).drop_duplicates(subset=['id'], keep='first')
            
            df.to_parquet(parquet_file, index=False)
            print(f"Pipeline atualizado. {len(all_records)} registros processados/corrigidos.")

if __name__ == "__main__":
    inputs = ["data/raw/docentes", "data/raw/diario_oficial"]
    output = "data/processed"
    pipeline = DataPipeline(inputs, output)
    pipeline.run()
