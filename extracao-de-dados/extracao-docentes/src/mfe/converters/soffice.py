import logging
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
scripts_dir = os.path.dirname(os.path.abspath(__file__))
for d in [root_dir, scripts_dir]:
    if d not in sys.path:
        sys.path.insert(0, d)

from src.mfe.ingest.unzip import is_compressed
from src.mfe.config.logging import create_logger

logger, error_logger = create_logger("soffice_converter", logging.INFO)


PRESENTATION_EXTENSIONS = {".ppt", ".pptx", ".odp"}
SPREADSHEET_EXTENSIONS = {".xls", ".xlsx", ".ods", ".csv"}


def _pdf_filter(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    if ext in PRESENTATION_EXTENSIONS:
        return "pdf:impress_pdf_Export"
    if ext in SPREADSHEET_EXTENSIONS:
        return "pdf:calc_pdf_Export"
    return "pdf:writer_pdf_Export"


def convert_office_to_pdf(file_path: str, output_path: str) -> None:
    file_path = str(Path(file_path).resolve())

    if not Path(file_path).exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {file_path}")

    logging.info(f"[PID {os.getpid()}] Converting doc to PDF: {file_path}")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            user_install_dir = tmpdir / f"lo_profile_{uuid.uuid4().hex}"
            user_install_dir.mkdir(parents=True, exist_ok=True)
            user_install_uri = f"file://{user_install_dir.as_posix()}"

            command = [
                "soffice",
                "--headless",
                f"-env:UserInstallation={user_install_uri}",
                "--convert-to",
                _pdf_filter(file_path),
                "--outdir",
                str(tmpdir),
                file_path,
            ]

            try:
                result = subprocess.run(
                    command,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                logger.info(f"soffice stdout: {result.stdout}")
                logger.info(f"soffice stderr: {result.stderr}")
            except subprocess.CalledProcessError as e:
                error_message = (
                    f"Failed to convert doc to PDF.\n"
                    f"Command: {' '.join(command)}\n"
                    f"Exit code: {e.returncode}\n"
                    f"STDOUT:\n{e.stdout}\n"
                    f"STDERR:\n{e.stderr}"
                )
                error_logger.error(error_message)
                raise RuntimeError(error_message) from e
            except Exception as e:
                raise RuntimeError(f"Erro inesperado ao executar o comando: {e}") from e

            tmpdir_contents = list(tmpdir.iterdir())
            logger.info(f"tmpdir contents: {tmpdir_contents}")

            generated_pdf = tmpdir / f"{Path(file_path).stem}.pdf"
            if not generated_pdf.exists():
                raise RuntimeError(
                    f"PDF não foi criado após a conversão. "
                    f"Arquivos no tmpdir: {tmpdir_contents}"
                )

            with open(generated_pdf, "rb") as f:
                pdf_content = f.read()
                with open(output_path, "wb") as f_out:
                    f_out.write(pdf_content)

    except Exception as e:
        error_logger.error(f"Failed to convert doc to .pdf: {e}")
        raise RuntimeError(f"Failed to convert doc to .pdf: {e}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Convert Office document to PDF")
    parser.add_argument("input_file", help="Path to the input Office document")
    parser.add_argument("output_file", help="Path to save the converted PDF")
    args = parser.parse_args()

    print(
        f"É um arquivo comprimido ? {is_compressed(args.input_file)}"
    )

    logging.basicConfig(level=logging.INFO)
    convert_office_to_pdf(args.input_file, args.output_file)
