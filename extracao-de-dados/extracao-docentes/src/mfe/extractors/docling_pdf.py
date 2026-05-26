import gc
import logging
import os
import time
import torch
from pathlib import Path
from typing import List

from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.datamodel.pipeline_options import (
    AcceleratorDevice,
    AcceleratorOptions,
    PdfPipelineOptions,
)
from docling.document_converter import (
    DocumentConverter,
    PdfFormatOption,
)
from docling_core.types.doc import ImageRefMode, PictureItem

from src.mfe.config.logging import create_logger
from src.mfe.converters.pdf import reduce_pdf_to_n_pages
from src.mfe.converters.soffice import convert_office_to_pdf
from src.mfe.extractors.enums.ocr_type import OCRModel
from src.mfe.extractors.ocr import ocr_image

logger, error_logger = create_logger("docling_pdf_extraction", logging.INFO)
memory_logger, error_memory_logger = create_logger("memory_logger")

office_extensions = [".docx", ".doc", "xlsx", ".xls", ".pptx"]


def instantiate_document_converter(
    generate_picture_images: bool = True,
    generate_full_page_image: bool = False,
    do_docling_ocr: bool = False,
    do_table_structure: bool = True,
    do_cell_matching: bool = True,
    do_formula_enhancement: bool = False,
    force_cpu: bool = False,
):
    pipeline_options = PdfPipelineOptions()
    pipeline_options.generate_picture_images = generate_picture_images
    pipeline_options.generate_page_images = generate_full_page_image
    pipeline_options.do_ocr = do_docling_ocr
    pipeline_options.do_formula_enrichment = do_formula_enhancement
    pipeline_options.do_table_structure = do_table_structure
    pipeline_options.table_structure_options.do_cell_matching = do_cell_matching
    pipeline_options.images_scale = 1.0
    
    # Força o uso do Tesseract para evitar downloads do RapidOCR e economizar VRAM
    from docling.datamodel.pipeline_options import TesseractOcrOptions
    pipeline_options.ocr_options = TesseractOcrOptions()
    pipeline_options.ocr_options.lang = ["por", "eng"]

    if force_cpu:
        acc_device = AcceleratorDevice.CPU
    else:
        acc_device = AcceleratorDevice.CUDA if torch.cuda.is_available() else AcceleratorDevice.CPU
        
    accelerator_options = AcceleratorOptions(
        num_threads=4, # Reduzido para economizar memória
        device=acc_device,
    )

    pipeline_options.accelerator_options = accelerator_options

    doc_converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
            ),
        }
    )

    return doc_converter


def single_extraction(
    doc_path: str,
    output_folder: str,
    page_numbers: List[int] | None = None,
    do_ocr_on_full_pages: bool = False,
    generate_picture_images: bool = True,
    ocr_provider: OCRModel = OCRModel.TESSERACT,
    save_image_on_bucket: bool = False,
    base_image_path: str = "",
    bucket_name: str = "",
    images_output_dir: str | None = None,
    doc_converter: DocumentConverter | None = None,
):
    if doc_converter is None:
        doc_converter = instantiate_document_converter(
            generate_picture_images=generate_picture_images,
            generate_full_page_image=True,
        )

    if save_image_on_bucket and bucket_name == "":
        raise ValueError("bucket_name must be provided if save_image_on_bucket is True")

    # Conversão de arquivos do Office para PDF, se necessário
    base, ext = os.path.splitext(doc_path)
    if ext.lower() in office_extensions:
        converted_file_path = f"{base}-converted_to_pdf.pdf"
        convert_office_to_pdf(doc_path, converted_file_path)
        doc_path = converted_file_path

    # Redução do PDF para um número específico de páginas para testes
    if page_numbers:
        output_pdf = f"{base}_reduced{ext}"
        reduce_pdf_to_n_pages(doc_path, output_pdf, page_numbers)
        doc_path = output_pdf

    start_time = time.time()

    logger.info(f"Start document conversion: {doc_path}")
    conv_result = None
    try:
        conv_result = doc_converter.convert(
            doc_path,
            raises_on_error=True,
        )
    except (torch.cuda.OutOfMemoryError, RuntimeError) as e:
        if "CUDA out of memory" in str(e) or isinstance(e, torch.cuda.OutOfMemoryError):
            logger.warning(f"CUDA Out of Memory para {doc_path}. Tentando via CPU...")
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()
            
            # Re-instancia o conversor forçando CPU
            try:
                doc_converter_cpu = instantiate_document_converter(
                    generate_picture_images=generate_picture_images,
                    generate_full_page_image=True,
                    force_cpu=True
                )
                conv_result = doc_converter_cpu.convert(doc_path, raises_on_error=False)
            except Exception as cpu_e:
                error_logger.error(f"Erro na conversão via CPU de {doc_path}: {cpu_e}")
                return None, None
        else:
            error_logger.error(f"Erro na conversão de {doc_path}: {e}")
            return None, None
    except Exception as e:
        error_logger.error(f"Erro na conversão de {doc_path}: {e}")
        return None, None
        
    if conv_result is None:
        return None, None

    logger.info(f"Document conversion completed: {doc_path}")

    end_document_conversion_time = time.time() - start_time
    logger.info(f"Document conversion time: {end_document_conversion_time:.2f} seconds")

    os.makedirs(output_folder, exist_ok=True)

    doc_filename = conv_result.input.file.stem
    final_output_path = os.path.join(output_folder, f"{doc_filename}.md")
    page_count = None

    if conv_result.status == ConversionStatus.SUCCESS or conv_result.status == ConversionStatus.PARTIAL_SUCCESS:
        if conv_result.status == ConversionStatus.PARTIAL_SUCCESS:
            logger.warning(f"Documento {doc_path} convertido parcialmente.")
        
        page_count = len(conv_result.document.pages)
        logger.info(f"Document with {page_count} pages extracted")

        # Salvamento das imagens (Pictures) das páginas
        picture_counter = 0
        artifacts_output = (
            Path(images_output_dir)
            if images_output_dir
            else Path(f"{output_folder}/{doc_filename}_artifacts")
        )
        artifacts_output.mkdir(parents=True, exist_ok=True)

        for element, _level in conv_result.document.iterate_items():
            if isinstance(element, PictureItem):
                element_image_filename = (
                    artifacts_output
                    / f"picture-{picture_counter}-pg_{element.prov[0].page_no}.png"
                )

                # Correção para AttributeError: 'NoneType' object has no attribute 'save'
                img = element.get_image(conv_result.document)
                if img is not None:
                    picture_counter += 1
                    with element_image_filename.open("wb") as fp:
                        img.save(fp, "PNG")
                        element.image.uri = element_image_filename

        # Salvamento do markdown com referência às imagens (Pictures)
        markdown_final_content = ""
        for page_no in range(1, len(conv_result.document.pages) + 1):
            text = conv_result.document.export_to_markdown(
                page_no=page_no,
                image_mode=ImageRefMode.REFERENCED,
            )

            markdown_final_content += f"{text}\n\n"

        print(f"Artifacts output path: {artifacts_output}")
        if os.path.exists(artifacts_output):
            for image in os.listdir(artifacts_output):
                print(f"Processing OCR for image: {image}")
                ocr_image_path = artifacts_output / image

                try:
                    image_bytes = ocr_image_path.read_bytes()
                    ocr_text = ocr_image(
                        image_bytes,
                        ocr_model=ocr_provider,
                    )

                    text_to_be_replaced = f"![Image]({ocr_image_path})"
                    replacement = f'{text_to_be_replaced}\n<ImageContent image_path="{ocr_image_path}">{ocr_text}</ImageContent>'
                    markdown_final_content = markdown_final_content.replace(
                        text_to_be_replaced,
                        replacement,
                    )
                except Exception as e:
                    print(f"Aviso: Falha no OCR da imagem {image}: {e}")

        # Salvamento da imagem completa da página, se necessário
        if do_ocr_on_full_pages:
            page_image_filename_base_path = (
                Path(output_folder) / f"{doc_filename}_full_pages"
            )
            page_image_filename_base_path.mkdir(parents=True, exist_ok=True)
            for page_no, page in conv_result.document.pages.items():
                page_no = page.page_no
                page_image_filename = (
                    page_image_filename_base_path
                    / f"{doc_filename}-{page_no}_complete.png"
                )
                if page.image and page.image.pil_image:
                    with page_image_filename.open("wb") as fp:
                        page.image.pil_image.save(fp, format="PNG")

        with open(final_output_path, "w", encoding="utf-8") as f_out:
            f_out.write(markdown_final_content)

        logger.info(f"Document {conv_result.input.file} converted successfully.")

    elif conv_result.status == ConversionStatus.PARTIAL_SUCCESS:
        error_logger.error(
            f"Document {conv_result.input.file} was partially converted."
        )
    else:
        error_logger.error(f"Document {conv_result.input.file} failed to convert.")

    del conv_result
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()

    end_time = time.time() - start_time
    logger.info(f"Total processing time: {end_time:.2f} seconds")

    return final_output_path, page_count
