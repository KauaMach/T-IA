import os
import hashlib
import pandas as pd
from pathlib import Path
import logging
from typing import List, Dict, Optional

# Integração com o novo deduplicador
try:
    from modules.preparacao_dados.deduplicator import deduplicate_raw, deduplicate_dataset
except ImportError:
    import sys
    sys.path.append(os.getcwd())
    try:
        from modules.preparacao_dados.deduplicator import deduplicate_raw, deduplicate_dataset
    except ImportError:
        def deduplicate_raw(x): pass
        def deduplicate_dataset(x): pass

# Bibliotecas de Extração
try:
    from docling.document_converter import DocumentConverter
    import pytesseract
    from PIL import Image
    import pdf2image
    HAS_DOCLING = True
except ImportError:
    HAS_DOCLING = False

# Configuração de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class UnifiedDataPipeline:
    def __init__(self, input_dirs: List[str], output_dir: str):
        self.input_dirs = input_dirs
        self.output_dir = output_dir
        self.text_dir = os.path.join(output_dir, "txt")
        self.parquet_path = os.path.join(output_dir, "dataset_consolidado.parquet")
        
        os.makedirs(self.text_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        
        if HAS_DOCLING:
            try:
                self.converter = DocumentConverter()
                logger.info("Docling inicializado com sucesso.")
            except Exception as e:
                self.converter = None
                logger.warning(f"Falha ao inicializar Docling: {e}. Usando fallbacks.")
        else:
            self.converter = None
            logger.warning("Docling ou dependências de OCR não instaladas. Fallbacks limitados.")

    def get_file_id(self, filepath: str) -> str:
        """ID único baseado em hash do conteúdo."""
        hasher = hashlib.sha256()
        try:
            with open(filepath, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hasher.update(chunk)
        except Exception as e:
            logger.error(f"Erro ao ler {filepath}: {e}")
            return "error_" + os.path.basename(filepath)
        return hasher.hexdigest()[:16]

    def extract_with_ocr(self, filepath: str) -> str:
        """Fallback de OCR usando Tesseract."""
        if not HAS_DOCLING: return "[OCR Indisponível]"
        ext = Path(filepath).suffix.lower()
        text = ""
        try:
            if ext == '.pdf':
                images = pdf2image.convert_from_path(filepath, last_page=5)
                for img in images:
                    text += pytesseract.image_to_string(img, lang='por+eng') + "\n"
            elif ext in ['.png', '.jpg', '.jpeg', '.tiff']:
                text = pytesseract.image_to_string(Image.open(filepath), lang='por+eng')
        except Exception as e:
            text = f"[OCR Error] {e}"
        return text

    def process_file(self, filepath: str) -> Optional[Dict]:
        ext = Path(filepath).suffix.lower()
        file_id = self.get_file_id(filepath)
        output_txt = os.path.join(self.text_dir, f"{file_id}.txt")
        
        if os.path.exists(output_txt) and os.path.getsize(output_txt) > 20:
            return None 

        content = ""
        try:
            if self.converter and ext in ['.pdf', '.docx', '.pptx', '.xlsx']:
                try:
                    result = self.converter.convert(filepath)
                    content = result.document.export_to_markdown()
                except Exception:
                    content = ""
            
            if (not content or len(content.strip()) < 100) and ext in ['.pdf', '.png', '.jpg', '.jpeg']:
                content = self.extract_with_ocr(filepath)
            
            elif ext in ['.txt', '.log', '.csv']:
                with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
            
            elif not content and ext in ['.rtf', '.odt']:
                 content = self.extract_with_ocr(filepath)
                
        except Exception as e:
            logger.error(f"Erro ao processar {filepath}: {e}")
            content = f"[Error] {e}"

        if not content.strip():
            content = "[Nenhum texto extraído]"

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

    def run(self, batch_size: int = 50):
        deduplicate_raw(self.input_dirs)
        
        all_files = []
        for d in self.input_dirs:
            if not os.path.exists(d): continue
            for root, _, files in os.walk(d):
                for f in files:
                    if f.endswith(('.csv', '.md')) or f.startswith('.'): continue
                    all_files.append(os.path.join(root, f))
        
        # Priorizar diários: coloca arquivos que contenham 'diario' no path no início da lista
        all_files.sort(key=lambda x: 0 if "diario" in x.lower() else 1)
        
        logger.info(f"Iniciando processamento de {len(all_files)} arquivos.")
        
        new_records = []
        for i in range(0, len(all_files), batch_size):
            batch = all_files[i : i + batch_size]
            for filepath in batch:
                record = self.process_file(filepath)
                if record:
                    new_records.append(record)
            
            if new_records:
                self._update_parquet(new_records)
                new_records = []
                logger.info(f"Progresso: {min(i + batch_size, len(all_files))}/{len(all_files)} arquivos analisados.")

        deduplicate_dataset(self.parquet_path)
        self._print_stats()

    def _update_parquet(self, records: List[Dict]):
        df_new = pd.DataFrame(records)
        if os.path.exists(self.parquet_path):
            try:
                df_old = pd.read_parquet(self.parquet_path)
                df_final = pd.concat([df_old, df_new], ignore_index=True).drop_duplicates(subset=['id'], keep='last')
            except Exception:
                df_final = df_new
        else:
            df_final = df_new
        df_final.to_parquet(self.parquet_path, index=False)

    def _print_stats(self):
        if not os.path.exists(self.parquet_path): return
        try:
            df = pd.read_parquet(self.parquet_path)
            logger.info("=== Estatísticas do Dataset Consolidado ===")
            logger.info(f"Total de documentos: {len(df)}")
            logger.info(f"Distribuição de formatos:\n{df['format'].value_counts()}")
            logger.info("===========================================")
        except Exception as e:
            logger.error(f"Erro ao gerar estatísticas: {e}")

if __name__ == "__main__":
    inputs = ["data/raw/diario_oficial", "data/raw/docentes"]
    output = "data/processed"
    pipeline = UnifiedDataPipeline(inputs, output)
    pipeline.run()
