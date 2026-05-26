import asyncio
import base64
import json
import os
import re
import sys
import traceback
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple

import pymupdf
from openai import AsyncOpenAI
from PIL import Image

root_dir = os.path.abspath(os.path.join(os.getcwd(), "..", "..", ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from src.mfe.cloud.s3 import upload_s3_async
from src.mfe.config.logging import create_logger

DEFAULT_BASE_URL = "http://localhost:5999/v1"
DESCRIBE_IMAGES = False

_async_ocr_client: Optional[AsyncOpenAI] = None


def init_ocr_client(base_url: Optional[str] = None) -> AsyncOpenAI:
    """
    Inicializa (ou reinicializa) o cliente OCR com a base_url fornecida.
    Se base_url não for informada, usa DEFAULT_BASE_URL (localhost).
    Retorna o cliente criado.
    """
    global _async_ocr_client
    _async_ocr_client = AsyncOpenAI(base_url=base_url or DEFAULT_BASE_URL, api_key="a")
    return _async_ocr_client


def get_ocr_client() -> AsyncOpenAI:
    """Retorna o cliente OCR singleton, inicializando com o padrão se necessário."""
    if _async_ocr_client is None:
        return init_ocr_client()
    return _async_ocr_client


async def describe_image_with_deepseek(crop_b64: str) -> str:
    """
    Envia um recorte de imagem (base64 PNG) para o DeepSeek-OCR-2 e retorna
    uma descrição textual do conteúdo da imagem.
    """
    response = await get_ocr_client().chat.completions.create(
        model="deepseek-ai/DeepSeek-OCR-2",
        messages=[
            {
                "role": "system",
                "content": (
                    "Descreva esta imagem em detalhes. Responda somente em português do Brasil."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{crop_b64}"},
                    },
                    {
                        "type": "text",
                        "text": "Descreva esta imagem em detalhes. Responda somente em português do Brasil.",
                    },
                ],
            },
        ],
        max_tokens=512,
        temperature=0.0,
    )
    content = response.choices[0].message.content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content)


IMAGE_REF_PATTERN = re.compile(
    r"<\|ref\|>image<\|/ref\|><\|det\|>(?P<bbox>\[\[[^\]]+\]\])<\|/det\|>",
    re.DOTALL,
)
REF_TAG_PATTERN = re.compile(r"<\|ref\|>.*?<\|/ref\|>", re.DOTALL)
DET_TAG_PATTERN = re.compile(r"<\|det\|>.*?<\|/det\|>", re.DOTALL)
CENTER_TAG_PATTERN = re.compile(r"</?center>", re.IGNORECASE)

logger, error_logger = create_logger("re_extract_simplified")


def deepseek_to_markdown(text: str) -> str:
    """
    Remove tokens especiais (<|ref|>, <|det|>, etc.) e deixa o texto
    em um formato de markdown mais limpo.
    Também remove linhas do tipo '# Página 1'.
    """
    if not text:
        return ""

    cleaned = text

    # Remove tags HTML simples usadas em captions (ex.: <center>...</center>)
    cleaned = CENTER_TAG_PATTERN.sub("", cleaned)

    # Remove apenas os tokens especiais, mantendo o texto logo depois deles
    cleaned = REF_TAG_PATTERN.sub("", cleaned)
    cleaned = DET_TAG_PATTERN.sub("", cleaned)

    # Quebras de linha excessivas
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    # Remover linhas "# Página N"
    lines = cleaned.splitlines()
    filtered_lines = []
    for line in lines:
        if re.match(r"^#\s*Página\s+\d+\s*$", line.strip(), re.IGNORECASE):
            # pula essa linha
            continue
        filtered_lines.append(line.rstrip())

    cleaned = "\n".join(filtered_lines)
    return cleaned.strip()


async def postprocess_deepseek_output(
    page_text: str,
    page_num: int,
    page_image: Image.Image,
    pdf_path: str,
    local_base_directory: str,
    bucket_base_directory: Optional[str] = None,
    upload_s3_enabled: bool = True,
) -> str:
    """
    - Lida com blocos de imagem usando os tokens <|ref|>image ... <|det|>[[...]]<|/det|>:
      recorta, salva e insere markdown com referência + descrição.
    - Remove os demais tokens especiais e devolve markdown limpo.
    - Formato de saída de imagem:
        ![Image](caminho/da/imagem.png)
        <ImageContent image_path="caminho/da/imagem.png">Descrição...</ImageContent>
    """
    if not page_text:
        return ""

    processed_text = page_text

    # 1) Encontrar todas as ocorrências de imagem nesta página
    image_matches = list(IMAGE_REF_PATTERN.finditer(processed_text))

    # 2) Se não houver imagem, apenas limpar tokens
    if not image_matches:
        return deepseek_to_markdown(processed_text)

    # 3) Obter dimensões da página para normalização
    width, height = page_image.size

    # 4) Substituir as tags de imagem de trás pra frente para não quebrar os índices
    counter = 0
    image_dir = pdf_path.replace(".pdf", "")
    os.makedirs(os.path.join(local_base_directory, image_dir), exist_ok=True)

    for match in reversed(image_matches):
        counter += 1
        bbox_json = match.group("bbox")

        try:
            boxes = json.loads(bbox_json)
            if not isinstance(boxes, list) or not boxes:
                continue
            x0, y0, x1, y1 = boxes[0]
        except Exception as e:
            error_logger.error(f"Erro ao parsear bbox na página {page_num}: {e}")
            continue

        crop = None
        image_rel_path = None

        # Normalizar coordenadas (0-1000) para coordenadas de pixel
        # DeepSeek usa 0-1000 como coordenadas relativas
        abs_x0 = x0 / 1000 * width
        abs_y0 = y0 / 1000 * height
        abs_x1 = x1 / 1000 * width
        abs_y1 = y1 / 1000 * height

        # Recortar e salvar imagem
        if page_image is not None:
            try:
                crop = page_image.crop((abs_x0, abs_y0, abs_x1, abs_y1))
                filename = f"page_{page_num:04d}_img_{counter:02d}.png"
                file_path = os.path.join(local_base_directory, image_dir, filename)

                # salva o recorte
                crop.save(file_path, "PNG")
                # Caminho em formato POSIX pra markdown (evita \ em Windows)
                image_rel_path = Path(file_path).as_posix()

                if bucket_base_directory and upload_s3_enabled:
                    s3_key = os.path.join(bucket_base_directory, image_dir, filename)
                    await upload_s3_async(file_path, s3_key)
                    image_rel_path = f"s3://{s3_key}"
                    os.remove(file_path)

            except Exception as e:
                error_logger.error(
                    f"Erro ao salvar recorte de imagem da página {page_num}: {e}"
                )

        # Descrever imagem com o modelo (opcional)
        desc = ""
        if DESCRIBE_IMAGES and crop is not None:
            try:
                buf = BytesIO()
                crop.save(buf, format="PNG")
                crop_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                desc = await describe_image_with_deepseek(crop_b64)
            except Exception as e:
                error_logger.error(
                    f"Erro ao descrever recorte de imagem da página {page_num}: {e}"
                )

        parts = []
        if image_rel_path:
            # Linha 1: markdown da imagem
            parts.append(f"![Image]({image_rel_path})")

            # Linha 2: componente ImageContent com o caminho e descrição
            if desc:
                parts.append(
                    f'<ImageContent image_path="{image_rel_path}">{desc}</ImageContent>'
                )
            else:
                # Se por algum motivo não tiver descrição, ainda assim gera o wrapper
                parts.append(
                    f'<ImageContent image_path="{image_rel_path}"></ImageContent>'
                )

        replacement = "\n".join(parts) if parts else ""

        # Substituir exatamente o trecho do token por esse markdown/custom tag
        processed_text = (
            processed_text[: match.start()]
            + replacement
            + processed_text[match.end() :]
        )

    processed_text = deepseek_to_markdown(processed_text)
    return processed_text


async def process_page_with_deepseek(
    page_num: int,
    base64_image: str,
    page_image: Image.Image,
    max_tokens: int = 2048,
    pdf_path: str = "",
    local_base_directory: Optional[str] = None,
    bucket_base_directory: Optional[str] = None,
    upload_s3_enabled: bool = True,
) -> Tuple[int, str]:
    """
    Processa uma única página com DeepSeek-OCR de forma assíncrona.
    Retorna (page_num, extracted_text_em_markdown).
    """
    try:
        response = await get_ocr_client().chat.completions.create(
            model="deepseek-ai/DeepSeek-OCR-2",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}"
                            },
                        },
                        {
                            "type": "text",
                            "text": "\n<|grounding|>Convert the document to markdown.",
                        },
                    ],
                }
            ],
            max_tokens=max_tokens,
            temperature=0.0,
            extra_body={
                # Mantemos os tokens especiais para conseguir usar as bboxes
                "skip_special_tokens": False,
                "vllm_xargs": {
                    "ngram_size": 30,
                    "window_size": 90,
                    "whitelist_token_ids": [128821, 128822],
                },
                "repetition_penalty": 1.05,
            },
        )

        raw_content = response.choices[0].message.content

        # vLLM pode devolver string ou lista de partes
        if isinstance(raw_content, list):
            page_text = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in raw_content
            )
        else:
            page_text = str(raw_content)

        # Pós-processar: limpar tokens especiais e lidar com imagens
        page_text = await postprocess_deepseek_output(
            page_text,
            page_num=page_num,
            page_image=page_image,
            pdf_path=pdf_path,
            local_base_directory=local_base_directory,
            bucket_base_directory=bucket_base_directory,
            upload_s3_enabled=upload_s3_enabled,
        )

        return (page_num, page_text)

    except Exception as e:
        error_logger.error(f"Erro ao processar página {page_num}: {e}")
        error_logger.error(traceback.format_exc())
        return (page_num, "")


async def extract_text_from_image_bytes(
    image_bytes: bytes,
    max_tokens: int = 4096,
    page_num: int = 1,
    local_base_directory: Optional[str] = None,
    bucket_base_directory: Optional[str] = None,
    upload_s3_enabled: bool = False,
) -> str:
    """
    Recebe bytes de uma imagem, chama o DeepSeek OCR e retorna o texto pós-processado em markdown.
    Imagens embutidas são salvas em local_base_directory (usa diretório temporário por padrão).
    """
    import tempfile

    pil_image = Image.open(BytesIO(image_bytes)).convert("RGB")
    base64_image = base64.b64encode(image_bytes).decode("utf-8")

    if local_base_directory is None:
        local_base_directory = tempfile.gettempdir()

    _, text = await process_page_with_deepseek(
        page_num=page_num,
        base64_image=base64_image,
        page_image=pil_image,
        max_tokens=max_tokens,
        pdf_path="image.pdf",
        local_base_directory=local_base_directory,
        bucket_base_directory=bucket_base_directory,
        upload_s3_enabled=upload_s3_enabled,
    )

    return text


def _render_pdf_chunk(
    doc: pymupdf.Document, dpi: int, page_start: int, page_end: int
) -> List[Tuple[int, str, Image.Image]]:
    """
    Renderiza um intervalo de páginas [page_start, page_end) de um documento
    já aberto. Executado em thread pool para não bloquear o event loop.
    """
    pages_data: List[Tuple[int, str, Image.Image]] = []
    for page_num in range(page_start, page_end):
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        img_bytes = pix.tobytes("jpeg")
        pil_image = Image.open(BytesIO(img_bytes)).convert("RGB")
        base64_image = base64.b64encode(img_bytes).decode("utf-8")
        pages_data.append((page_num + 1, base64_image, pil_image))
    return pages_data


async def extract_text_from_pdf_with_deepseek(
    pdf_path: str,
    max_tokens: int = 4096,
    local_limit_quantity: int = 5,
    local_base_directory: Optional[str] = None,
    bucket_base_directory: Optional[str] = None,
    upload_s3_enabled: bool = True,
) -> Optional[Tuple[str, int]]:
    """
    Extrai texto de um PDF usando DeepSeek-OCR com processamento paralelo de páginas.

    Processa local_limit_quantity páginas por vez (um chunk), liberando a RAM
    das imagens antes de carregar o próximo chunk. Isso evita OOM em PDFs grandes.
    O documento é aberto uma única vez e mantido aberto durante toda a extração.
    """
    try:
        logger.info(
            f"[DeepSeek] - Iniciando extração: {os.path.basename(pdf_path)}"
        )

        dpi = 200
        doc = pymupdf.open(pdf_path)
        total_pages = len(doc)
        logger.info(f"Total de páginas: {total_pages}")

        all_results: List[Tuple[int, str]] = []

        try:
            for chunk_start in range(0, total_pages, local_limit_quantity):
                chunk_end = min(chunk_start + local_limit_quantity, total_pages)

                pages_data = await asyncio.to_thread(
                    _render_pdf_chunk, doc, dpi, chunk_start, chunk_end
                )

                logger.info(
                    f"[DeepSeek] - Processando páginas {chunk_start + 1}–{chunk_end}/{total_pages}"
                )

                tasks = [
                    process_page_with_deepseek(
                        page_num=page_num,
                        base64_image=base64_image,
                        page_image=page_image,
                        max_tokens=max_tokens,
                        pdf_path=os.path.basename(pdf_path),
                        local_base_directory=local_base_directory,
                        bucket_base_directory=bucket_base_directory,
                        upload_s3_enabled=upload_s3_enabled,
                    )
                    for page_num, base64_image, page_image in pages_data
                ]

                chunk_results = await asyncio.gather(*tasks)
                all_results.extend(chunk_results)
                del pages_data
        finally:
            doc.close()

        results_sorted = sorted(all_results, key=lambda x: x[0])
        full_text = "\n\n".join(
            text.strip() for _, text in results_sorted if text and text.strip()
        )
        logger.info(f"Extração concluída: {total_pages} páginas processadas")

        return (full_text, total_pages)

    except Exception as e:
        error_logger.error(f"Erro ao extrair texto do PDF {pdf_path}: {e}")
        error_logger.error(traceback.format_exc())
        return None
