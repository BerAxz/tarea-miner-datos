"""Validate and upload only the generated dataset artifacts."""

import json
from pathlib import Path

import pyarrow.parquet as pq

from .dataset import SCHEMAS


def publish_dataset(dataset_dir, repo_id, private=False, api=None):
    directory = Path(dataset_dir)
    if len(repo_id.split("/")) != 2 or any(not part.strip() for part in repo_id.split("/")):
        raise ValueError("repo-id debe tener formato usuario/dataset")
    required = [*(f"{name}.parquet" for name in SCHEMAS), "README.md", "run.json"]
    for filename in required:
        if not (directory / filename).is_file():
            raise ValueError(f"falta {filename}")
    for name, expected in SCHEMAS.items():
        if not pq.read_schema(directory / f"{name}.parquet").equals(expected):
            raise ValueError(f"esquema inválido: {name}")
    manifest = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    if manifest["counts"]["workflows"] == 0:
        raise ValueError("el dataset no contiene Markdown; no se publicará vacío")
    if api is None:
        try:
            from huggingface_hub import HfApi
        except ImportError as exc:
            raise ValueError('instala el soporte con pip install -e ".[publish]"') from exc
        api = HfApi()
    api.create_repo(repo_id=repo_id, repo_type="dataset", private=private, exist_ok=True)
    api.upload_folder(repo_id=repo_id, repo_type="dataset", folder_path=directory,
                      allow_patterns=required, commit_message="Publish Miner GH-AW dataset")
    return f"https://huggingface.co/datasets/{repo_id}"
