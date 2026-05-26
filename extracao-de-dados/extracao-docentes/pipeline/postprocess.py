import os
from pathlib import Path

from huggingface_hub import CommitOperationAdd, HfApi


def upload_to_hf(
    output_jsonl_final_dir: str,
    pipeline_name: str,
    dataset_version: str,
    logger,
) -> None:

    HF_TOKEN = os.getenv("HF_TOKEN")
    HF_USERNAME = os.getenv("HF_USERNAME")
    DATASET_NAME = "ia-course"

    if pipeline_name == "deepseek":
        extraction_model = "deepseek-ocr-2"
        branch_name = None  # main
    else:
        extraction_model = "docling-1"
        branch_name = "docling"

    repo_id = f"{HF_USERNAME}/{DATASET_NAME}"

    dataset_card = f"""\
---
license: other
tags:
  - ocr
  - pdf
  - text-extraction
  - {extraction_model}
version: "{dataset_version}"
configs:
  - config_name: default
    data_files:
      - split: train
        path: "data/*.jsonl"
---

# {DATASET_NAME}

Extracted text dataset processed with {extraction_model}, merged with MongoDB metadata.

## Extraction details

| Field | Value |
|---|---|
| Extraction model | `{extraction_model}` |
| Dataset version | `{dataset_version}` |
| Pipeline | {pipeline_name.capitalize()} |
"""

    api = HfApi(token=HF_TOKEN)
    api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True, private=True)
    logger.info(f"Repositório pronto: https://huggingface.co/datasets/{repo_id}")

    if branch_name:
        try:
            api.create_branch(repo_id=repo_id, repo_type="dataset", branch=branch_name)
            logger.info(f"Branch '{branch_name}' criada.")
        except Exception:
            logger.info(f"Branch '{branch_name}' já existe, reutilizando.")

    jsonl_final_dir = Path(output_jsonl_final_dir)
    operations = [
        CommitOperationAdd(
            path_in_repo=f"data/{f.name}",
            path_or_fileobj=str(f),
        )
        for f in sorted(jsonl_final_dir.glob("*.jsonl"))
    ]
    operations.append(
        CommitOperationAdd(
            path_in_repo="README.md",
            path_or_fileobj=dataset_card.encode("utf-8"),
        )
    )

    logger.info(f"Fazendo upload de {len(operations) - 1} arquivos JSONL + README...")

    commit_kwargs = dict(
        repo_id=repo_id,
        repo_type="dataset",
        operations=operations,
        commit_message=f"feat: add extraction v{dataset_version} using {extraction_model}",
    )
    if branch_name:
        commit_kwargs["revision"] = branch_name

    commit_info = api.create_commit(**commit_kwargs)
    logger.info(f"Commit: {commit_info.commit_url}")

    tag = f"v{dataset_version}" + (f"-{branch_name}" if branch_name else "")
    api.create_tag(
        repo_id=repo_id,
        repo_type="dataset",
        tag=tag,
        tag_message=f"Extraction using {extraction_model}",
        revision=commit_info.oid,
    )
    logger.info(f"Tag {tag} criada.")
