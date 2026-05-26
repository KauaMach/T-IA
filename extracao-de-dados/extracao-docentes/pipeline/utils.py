import hashlib
import json
import os
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

# fmt: off
HTML_EXTENSIONS = {".html", ".htm"}
XML_EXTENSIONS = {".xml"}
BATCH_SIZE = 200
# fmt: on


def extract_text_from_html(filepath: str) -> str:
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        html = f.read()
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def _xml_element_to_dict(element):
    result = {}
    if element.attrib:
        result["@attributes"] = element.attrib
    children = list(element)
    if children:
        child_dict = {}
        for child in children:
            child_data = _xml_element_to_dict(child)
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag in child_dict:
                if not isinstance(child_dict[tag], list):
                    child_dict[tag] = [child_dict[tag]]
                child_dict[tag].append(child_data)
            else:
                child_dict[tag] = child_data
        result.update(child_dict)
    text = (element.text or "").strip()
    if text:
        result["#text"] = text if result else text
        if not result or result == {"#text": text}:
            return text
    return result or text or {}


def convert_xml_to_json(filepath: str) -> str:
    tree = ET.parse(filepath)
    root = tree.getroot()
    tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    data = {tag: _xml_element_to_dict(root)}
    return json.dumps(data, ensure_ascii=False, indent=2)


def generate_record_id(file_path: str, relative_path: str) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    sha256.update(relative_path.encode("utf-8"))
    return sha256.hexdigest()


def collect_all_files(base_dir: str) -> list:
    all_files = []
    for root, _dirs, files in os.walk(base_dir):
        for filename in files:
            all_files.append(os.path.join(root, filename))
    return sorted(all_files)


def make_save_batch_final(output_jsonl_final_dir: str, output_text_dir: str, logger):
    EXCLUDED_FIELDS = {
        "text_file_s3_uri",
        "extraction_started",
        "extraction_finished",
        "extraction_duration_in_seconds",
        "status",
        "filepath",
    }

    def save_batch(records: list, batch_index: int):
        batch_path = os.path.join(
            output_jsonl_final_dir, f"batch_{batch_index:04d}.jsonl"
        )
        with open(batch_path, "w", encoding="utf-8") as f:
            for record in records:
                text_path = os.path.join(output_text_dir, f"{record['id']}.txt")
                try:
                    with open(text_path, "r", encoding="utf-8", errors="replace") as tf:
                        text_content = tf.read()
                except FileNotFoundError:
                    text_content = None

                new_record = {
                    k: v for k, v in record.items() if k not in EXCLUDED_FIELDS
                }
                new_record["text_content"] = text_content
                f.write(json.dumps(new_record, ensure_ascii=False) + "\n")

        logger.info(
            f"Batch {batch_index} salvo ({len(records)} registros) → {batch_path}"
        )

    return save_batch
