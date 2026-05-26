from typing import List

from pypdf import PdfReader, PdfWriter


def reduce_pdf_to_n_pages(input_pdf: str, output_pdf: str, page_numbers: List[int]) -> None:
    reader = PdfReader(input_pdf)
    writer = PdfWriter()
    for page_num in page_numbers:
        writer.add_page(reader.pages[page_num])
    with open(output_pdf, "wb") as f:
        writer.write(f)
