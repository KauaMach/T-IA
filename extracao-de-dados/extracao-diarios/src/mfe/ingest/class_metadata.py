import json
import re
from pathlib import Path

_DATE_PATTERN = re.compile(r"^\d{4}$")  # segmento de 4 dígitos = ano


def _find_date_dir_index(parts: tuple) -> int | None:
    """Retorna o índice do segmento YYYY que inicia o padrão YYYY/MM/DD no path."""
    for i in range(len(parts) - 2):
        if (
            _DATE_PATTERN.match(parts[i])
            and parts[i + 1].isdigit()
            and parts[i + 2].isdigit()
        ):
            return i
    return None


def build_metadata_lookup(metadata_json_path: str) -> dict:
    """Constrói um dicionário de lookup de metadados de turmas a partir do JSON do MongoDB.

    A chave do lookup é "YYYY/MM/DD/nome_arquivo", construída a partir de
    path_local e nome_arquivo de cada arquivo nos planos de aula.

    Args:
        metadata_json_path: caminho para o JSON exportado do MongoDB.

    Returns:
        Dicionário com chave "YYYY/MM/DD/nome_arquivo" e valor contendo
        turma, plano_aula e arquivo.
    """
    with open(metadata_json_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    lookup = {}
    for professor in metadata:
        for turma in professor.get("turmas", []):
            turma_info = {k: v for k, v in turma.items() if k != "planos_aula"}
            for plano in turma.get("planos_aula", []):
                plano_info = {k: v for k, v in plano.items() if k != "arquivos"}
                for arquivo in plano.get("arquivos", []):
                    path_local = arquivo.get("path_local", "")
                    nome_arquivo = arquivo.get("nome_arquivo", "")
                    if path_local and nome_arquivo:
                        date_dir = str(Path(path_local.replace("files/", "", 1)).parent)
                        key = f"{date_dir}/{nome_arquivo}"
                        lookup[key] = {
                            "turma": turma_info,
                            "plano_aula": plano_info,
                            "arquivo": arquivo,
                        }

    return lookup


def get_class_metadata(filepath: str, lookup: dict) -> dict | None:
    """Retorna os metadados de turma para um filepath, ou None se não encontrado.

    Localiza o padrão YYYY/MM/DD no path e usa YYYY/MM/DD/nome_arquivo como
    chave, independente de quantos subdiretórios existam após a data.

    Args:
        filepath: caminho do arquivo (ex: data/input/.../2026/02/20/comp/arquivo.java).
        lookup: dicionário construído por build_metadata_lookup.

    Returns:
        Dicionário com turma, plano_aula e arquivo, ou None.
    """
    parts = Path(filepath).parts
    date_idx = _find_date_dir_index(parts)
    if date_idx is None:
        return None

    # Monta YYYY/MM/DD e tenta cada segmento após a data como nome do arquivo
    # Útil para arquivos em subdiretórios ou extraídos de zips
    date_prefix = "/".join(parts[date_idx : date_idx + 3])
    for segment in parts[date_idx + 3 :]:
        key = f"{date_prefix}/{segment}"
        result = lookup.get(key)
        if result is not None:
            return result

    return None
