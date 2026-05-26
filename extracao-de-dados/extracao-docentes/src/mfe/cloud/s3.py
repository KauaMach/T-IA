import asyncio
import os
import sys
import traceback

import boto3
from botocore.exceptions import NoCredentialsError
from dotenv import load_dotenv

root_dir = os.path.abspath(os.path.join(os.getcwd(), "..", "..", "..", ".."))

# Garantir que sempre pegue o root do projeto
# Procura pelo diretório que contém .git ou .env
current_dir = os.path.dirname(os.path.abspath(__file__))
while current_dir != os.path.dirname(
    current_dir
):  # Enquanto não chegar na raiz do sistema
    if (
        os.path.exists(os.path.join(current_dir, ".git"))
        or os.path.exists(os.path.join(current_dir, ".env"))
        or os.path.exists(os.path.join(current_dir, "pyproject.toml"))
    ):
        root_dir = current_dir
        break
    current_dir = os.path.dirname(current_dir)
else:
    # Fallback para o método original se não encontrar
    root_dir = os.path.abspath(os.path.join(os.getcwd(), "..", "..", "..", ".."))

if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from src.mfe.config.logging import create_logger

load_dotenv(os.path.join(root_dir, ".env"))

logger, error_logger = create_logger("s3_upload")

AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")
REGION = os.getenv("REGION")
BUCKET_NAME = os.getenv("BUCKET_NAME")

s3 = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=REGION,
)


def upload_s3(
    local_path: str,
    s3_object_name: str,
    bucket_name: str = BUCKET_NAME,
    delete_after=False,
    log_infos=True,
):
    try:
        if log_infos:
            logger.info(
                f"Uploading {local_path} to s3://{bucket_name}/{s3_object_name}"
            )

        s3.upload_file(local_path, bucket_name, s3_object_name)

        if log_infos:
            logger.info(
                f"Upload feito com sucesso: s3://{bucket_name}/{s3_object_name}"
            )

        if delete_after:
            os.remove(local_path)
    except FileNotFoundError:
        error_logger.error(f"Arquivo local {local_path} não encontrado.")
    except NoCredentialsError:
        error_logger.error("Credenciais inválidas ou ausentes.")
    except Exception as e:
        error_logger.error(f"Erro durante o upload: {e}")
        error_logger.error(traceback.format_exc())


_S3_UPLOAD_SEMAPHORE = asyncio.Semaphore(9)


async def upload_s3_limited(*, local_path: str, bucket_name: str, s3_object_name: str):
    """
    Envolve upload_s3_async com um semáforo global para limitar
    o número total de uploads simultâneos ao S3.
    """
    async with _S3_UPLOAD_SEMAPHORE:
        return await upload_s3_async(
            local_path=local_path,
            bucket_name=bucket_name,
            s3_object_name=s3_object_name,
        )


async def upload_s3_async(
    local_path: str,
    s3_object_name: str,
    bucket_name: str = BUCKET_NAME,
):
    """
    Uploads a file to S3 asynchronously.
    """
    try:
        logger.info(f"Uploading {local_path} to s3://{bucket_name}/{s3_object_name}")
        await asyncio.to_thread(s3.upload_file, local_path, bucket_name, s3_object_name)
        logger.info(f"Upload feito com sucesso: s3://{bucket_name}/{s3_object_name}")
    except FileNotFoundError:
        error_logger.error(f"Arquivo local {local_path} não encontrado.")
    except NoCredentialsError:
        error_logger.error("Credenciais inválidas ou ausentes.")
    except Exception as e:
        error_logger.error(f"Erro durante o upload: {e}")
        error_logger.error(traceback.format_exc())


def fetch_root_folders(delimiter: str = "/", bucket_name: str = BUCKET_NAME):
    """
    Fetches the root folders in the S3 bucket.
    """
    try:
        response = s3.list_objects_v2(Bucket=bucket_name, Delimiter=delimiter)
        return [prefix["Prefix"] for prefix in response.get("CommonPrefixes", [])]
    except Exception as e:
        error_logger.error(f"Erro ao listar pastas: {e}")
        return []


def get_object(
    s3_object_name: str,
    bucket_name: str = BUCKET_NAME,
):
    """
    Fetches an image from the S3 bucket.
    """
    try:
        response = s3.get_object(Bucket=bucket_name, Key=s3_object_name)
        return response["Body"].read()
    except Exception as e:
        error_logger.error(f"Erro ao obter imagem: {e}")
        return None


def delete_all_object_in_directory(
    directory: str,
    bucket_name: str = BUCKET_NAME,
):
    try:
        response = s3.list_objects_v2(Bucket=bucket_name, Prefix=directory)
        if "Contents" in response:
            for obj in response["Contents"]:
                s3.delete_object(Bucket=bucket_name, Key=obj["Key"])
            logger.info(f"Todos os objetos em {directory} foram deletados.")
        else:
            logger.info(f"Nenhum objeto encontrado em {directory}.")
    except Exception as e:
        error_logger.error(f"Erro ao deletar objetos: {e}")
        error_logger.error(traceback.format_exc())


def list_folders_in_directory(
    directory: str,
    bucket_name: str = BUCKET_NAME,
):
    folders = []
    response = s3.list_objects_v2(
        Bucket=bucket_name,
        Prefix=directory,
        Delimiter="/",
    )

    if "CommonPrefixes" in response:
        for prefix in response["CommonPrefixes"]:
            folders.append(prefix["Prefix"])
    return folders


def list_all_objects_in_directory(
    directory: str,
    bucket_name: str = BUCKET_NAME,
    paginate: bool = False,
):
    try:
        if paginate:
            paginator = s3.get_paginator("list_objects_v2")
            page_iterator = paginator.paginate(Bucket=bucket_name, Prefix=directory)
            all_keys = []
            for page in page_iterator:
                if "Contents" in page:
                    all_keys.extend([obj["Key"] for obj in page["Contents"]])
            return all_keys

        response = s3.list_objects_v2(Bucket=bucket_name, Prefix=directory)
        if "Contents" in response:
            return [obj["Key"] for obj in response["Contents"]]
        else:
            return []
    except Exception as e:
        error_logger.error(f"Erro ao listar objetos: {e}")
        return []


def get_len_objects_in_directory(
    directory: str,
    bucket_name: str = BUCKET_NAME,
):
    paginator = s3.get_paginator("list_objects_v2")
    page_iterator = paginator.paginate(Bucket=bucket_name, Prefix=directory)
    fileCount = sum(KeyCount for KeyCount in page_iterator.search("KeyCount"))

    return fileCount
