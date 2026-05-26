from io import BytesIO
from typing import Optional

from PIL.Image import Image

from src.mfe.extractors.deepseek_ocr import (
    extract_text_from_image_bytes as deepseek_image_ocr,
)
from src.mfe.extractors.deepseek_ocr import (
    extract_text_from_pdf_with_deepseek,
)
from src.mfe.extractors.enums.ocr_type import OCRModel
from src.mfe.extractors.tesseract_ocr import (
    extract_text_from_image_bytes as tesseract_image_ocr,
)


def pil_image_to_bytes(pil_image: Image, format: str = "PNG") -> bytes:
    buffer = BytesIO()
    pil_image.save(buffer, format=format)
    return buffer.getvalue()


def ocr_image(image_bytes: bytes, ocr_model: OCRModel) -> str:
    if ocr_model == OCRModel.TESSERACT:
        extracted_text = tesseract_image_ocr(
            image_bytes=image_bytes,
        )
    elif ocr_model == OCRModel.DEEPSEEK:
        extracted_text = deepseek_image_ocr(
            image_bytes=image_bytes,
        )
    else:
        raise ValueError(f"OCR model {ocr_model} not supported.")

    return extracted_text


async def ocr_pdf(
    pdf_path: str,
    ocr_model: OCRModel,
    local_limit_quantity: int = 5,
    local_base_directory: str = "temp_images",
    bucket_base_directory: Optional[str] = None,
    upload_s3_enabled: bool = True,
) -> tuple[str, int]:
    if ocr_model == OCRModel.DEEPSEEK:
        markdown_text, pages_count = await extract_text_from_pdf_with_deepseek(
            pdf_path=pdf_path,
            local_limit_quantity=local_limit_quantity,
            local_base_directory=local_base_directory,
            bucket_base_directory=bucket_base_directory,
            upload_s3_enabled=upload_s3_enabled,
        )
    else:
        raise ValueError(f"OCR model {ocr_model} not supported.")

    return markdown_text, pages_count
