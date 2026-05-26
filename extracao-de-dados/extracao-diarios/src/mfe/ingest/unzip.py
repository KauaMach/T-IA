import subprocess
import tarfile
import zipfile
from pathlib import Path

from src.mfe.constants import OFFICE_EXTENSIONS


def is_compressed(filepath: str | Path) -> bool:
    """Detecta se um arquivo é comprimido verificando os magic bytes.

    Suporta: .zip, .rar, .tar.gz, .tgz, .tar.bz2, .tar.xz
    """
    filepath = Path(filepath)
    if not filepath.is_file():
        return False
    if filepath.suffix.lower() in OFFICE_EXTENSIONS:
        return False
    try:
        if zipfile.is_zipfile(filepath):
            print(f"{filepath} é um arquivo ZIP válido.")
            return True
        if tarfile.is_tarfile(filepath):
            print(f"{filepath} é um arquivo TAR válido.")
            return True
        with open(filepath, "rb") as f:
            print(f"Verificando magic bytes de {filepath}...")
            return f.read(6) == b"Rar!\x1a\x07"
    except Exception:
        return False


def _extract_tar(filepath: Path, destination: Path) -> None:
    with tarfile.open(filepath) as tar:
        tar.extractall(path=destination)


def _extract_zip(filepath: Path, destination: Path) -> None:
    with zipfile.ZipFile(filepath) as zf:
        zf.extractall(path=destination)


def _extract_rar(filepath: Path, destination: Path) -> None:
    result = subprocess.run(
        ["7z", "x", str(filepath), f"-o{destination}", "-y"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Falha ao extrair {filepath.name}: {result.stderr}")


def extract_file(filepath: str | Path, output_dir: str | Path | None = None) -> bool:
    """Extrai um único arquivo comprimido.

    Suporta: .zip, .rar, .tar.gz, .tgz, .tar.bz2, .tar.xz

    Args:
        filepath: caminho do arquivo comprimido
        output_dir: diretório de saída. Se None, extrai no mesmo diretório do arquivo.

    Returns:
        True se extraído com sucesso.
    """
    filepath = Path(filepath)
    destination = Path(output_dir) if output_dir else filepath.parent
    destination.mkdir(parents=True, exist_ok=True)

    if tarfile.is_tarfile(filepath):
        _extract_tar(filepath, destination)
    elif zipfile.is_zipfile(filepath):
        _extract_zip(filepath, destination)
    else:
        with open(filepath, "rb") as f:
            if f.read(6) == b"Rar!\x1a\x07":
                _extract_rar(filepath, destination)
            else:
                raise ValueError(f"Formato não suportado: {filepath.name}")

    return True


if __name__ == "__main__":
    extract_file(
        "data/input/raw/files_to_rename/files_to_rename/2016/09/26/aula_NLTK.rar",
        "extracted_rar",
    )

    extract_file(
        "data/input/raw/files_to_rename/files_to_rename/2016/11/04/portugol parcial2.zip",
        "extracted_zip",
    )

    extract_file(
        "data/input/raw/files_to_rename/files_to_rename/2018/08/29/brasileirao.tar.gz",
        "extracted_tar",
    )
