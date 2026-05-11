import os
import hashlib
from pathlib import Path

def get_file_hash(filepath):
    """Calcula o hash SHA256 de um arquivo."""
    hasher = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
    except Exception as e:
        print(f"Erro ao ler {filepath}: {e}")
        return None
    return hasher.hexdigest()

def deduplicate_docentes(base_path):
    """
    Deduplica arquivos de docentes baseados no nome (pós-prefixo) e conteúdo.
    """
    print(f"Analisando docentes em: {base_path}")
    if not os.path.exists(base_path):
        print("Diretório não encontrado.")
        return

    files_map = {}
    for root, dirs, files in os.walk(base_path):
        for file in files:
            if file == "docentes_arquivos.csv":
                continue
            filepath = os.path.join(root, file)
            if '-' in file:
                clean_name = file.split('-', 1)[1]
            else:
                clean_name = file
            file_hash = get_file_hash(filepath)
            if not file_hash:
                continue
            if clean_name not in files_map:
                files_map[clean_name] = {}
            if file_hash not in files_map[clean_name]:
                files_map[clean_name][file_hash] = []
            files_map[clean_name][file_hash].append(filepath)

    count_removed = 0
    for clean_name, hashes in files_map.items():
        for f_hash, paths in hashes.items():
            if len(paths) > 1:
                # Mantém o primeiro, remove os outros
                for path_to_remove in paths[1:]:
                    print(f"[DEDUPLICATE] Removendo duplicata: {path_to_remove}")
                    try:
                        os.remove(path_to_remove)
                        count_removed += 1
                    except Exception as e:
                        print(f"Erro ao remover {path_to_remove}: {e}")
    print(f"Total de arquivos removidos em docentes: {count_removed}")

def deduplicate_diario(base_path):
    """
    Deduplica arquivos do Diário Oficial baseados em hash de conteúdo.
    """
    print(f"Analisando diário oficial em: {base_path}")
    if not os.path.exists(base_path):
        print("Diretório não encontrado.")
        return

    hashes = {}
    count_removed = 0
    for root, dirs, files in os.walk(base_path):
        for file in files:
            if not file.lower().endswith('.pdf'):
                continue
            filepath = os.path.join(root, file)
            file_hash = get_file_hash(filepath)
            if not file_hash:
                continue
            if file_hash in hashes:
                print(f"[DEDUPLICATE] Removendo PDF duplicado: {filepath}")
                try:
                    os.remove(filepath)
                    count_removed += 1
                except Exception as e:
                    print(f"Erro ao remover {filepath}: {e}")
            else:
                hashes[file_hash] = filepath
    print(f"Total de arquivos removidos em Diário Oficial: {count_removed}")

if __name__ == "__main__":
    deduplicate_docentes("data/raw/docentes")
    deduplicate_diario("data/raw/diario_oficial")
