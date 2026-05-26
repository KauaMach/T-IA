from io import BytesIO

import pytesseract
from PIL import Image


def extract_text_from_image_bytes(
    image_bytes: bytes,
    lang: str = "por+eng",
) -> str:
    """
    Recebe bytes de uma imagem, executa OCR com Tesseract e retorna o texto extraído.

    Args:
        image_bytes: Bytes brutos da imagem.
        lang: Idioma(s) do Tesseract (ex.: "por", "eng", "por+eng").

    Returns:
        Texto extraído da imagem como string.
    """
    print("Iniciando OCR com Tesseract...")
    pil_image = Image.open(BytesIO(image_bytes)).convert("RGB")
    text = pytesseract.image_to_string(pil_image, lang=lang)
    print(
        f"OCR concluído. Texto extraído: {text[:100]}..."
    )  # Exibe os primeiros 100 caracteres do texto extraído
    return text.strip()
