"""Concurrent extraction into four related, explicitly typed Parquet tables."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import time
from urllib.parse import quote

import pyarrow as pa
import pyarrow.parquet as pq

from .concurrency import bounded_map
from .csv_io import read_candidates
from .frontmatter import parse_nodes, split_markdown
from .models import repository_from_row


def schema(*columns):
    return pa.schema([pa.field(name, kind, nullable=nullable)
                      for name, kind, nullable in columns])


S = pa.string()
SCHEMAS = {
    "repositories": schema(
        ("repository_id", S, False), ("full_name", S, False),
        ("html_url", S, False), ("commit_sha", S, True),
        ("license_spdx", S, True), ("extracted_at", pa.timestamp("us", tz="UTC"), False),
        ("status", S, False), ("error", S, True)),
    "workflows": schema(
        ("workflow_id", S, False), ("repository_id", S, False),
        ("path", S, False), ("blob_sha", S, False), ("source_url", S, False),
        ("has_lock", pa.bool_(), False), ("frontmatter_yaml", S, True),
        ("status", S, False), ("error", S, True)),
    "bodies": schema(("workflow_id", S, False), ("markdown", S, False)),
    "frontmatter_nodes": schema(
        ("node_id", S, False), ("workflow_id", S, False),
        ("parent_node_id", S, True), ("pointer", S, False),
        ("key", S, True), ("position", pa.int32(), False),
        ("kind", S, False), ("value_json", S, True)),
}


def stable_id(*parts):
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


@dataclass
class ExtractionSummary:
    repositories: int = 0
    workflows: int = 0
    errors: int = 0
    cache_hits: int = 0
    downloads: int = 0
    invalid_rows: int = 0
    elapsed_seconds: float = 0


def dataset_card(counts):
    configs = "\n".join(
        f"  - config_name: {name}\n    data_files:\n      - split: train\n        path: {name}.parquet"
        for name in SCHEMAS
    )
    return f"""---
language:
  - en
  - es
tags:
  - github
  - agentic-workflows
  - code
configs:
{configs}
---
# GitHub Agentic Workflows — Miner

Snapshot de los Markdown bajo `.github/workflows/` de los repositorios de entrada
de la Tarea 2. Incluye archivos auxiliares; `has_lock` indica si existe el
compañero `.lock.yml` en el mismo directorio. No se ejecutan workflows.

## Tablas

| Tabla | Filas | Contenido |
| --- | ---: | --- |
| repositories | {counts['repositories']} | Repositorio, commit, licencia declarada, fecha y estado de consulta. |
| workflows | {counts['workflows']} | Ruta, blob SHA, URL fijada al commit, YAML original y estado. |
| bodies | {counts['bodies']} | Body Markdown sin normalizar espacios ni saltos de línea. |
| frontmatter_nodes | {counts['frontmatter_nodes']} | Árbol YAML: mappings, secuencias y escalares tipados. |

`repository_id` es PK de repositories y FK en workflows. `workflow_id` es PK de
workflows y de bodies (también FK), y FK en frontmatter_nodes. `node_id` es PK;
`parent_node_id` referencia otro nodo del mismo archivo. La raíz usa pointer vacío;
los descendientes usan JSON Pointer. `position` conserva el orden desde cero.
`kind` distingue mapping, sequence, null, string, boolean, integer y number;
`value_json` conserva el escalar en JSON (NULL en contenedores).

Cada tabla es una configuración separada del visor de Hugging Face:

```python
from datasets import load_dataset
# Reemplazar usuario/dataset por el identificador publicado.
workflows = load_dataset("usuario/dataset", "workflows", split="train")
```

## Recolección y limitaciones

Miner 0.2 fija cada repositorio al commit de su rama predeterminada al consultarlo.
Los IDs son SHA-256 del nombre normalizado y de la ruta; identifican entidades
estables entre ejecuciones, mientras commit_sha y blob_sha identifican versiones.
La selección depende del CSV de entrada y no representa todo GitHub.
Los errores se conservan en status/error; una descarga fallida no tiene body.
Un frontmatter ausente, inválido o sin cierre no genera nodos. Si no tiene cierre,
el body conserva el archivo completo para no inventar una separación.
Los valores on/off/yes/no y las fechas quedan como texto; true/false son booleanos.
Se rechazan claves duplicadas/no textuales, tipos YAML especiales, valores
no finitos, ciclos y árboles de más de 64 niveles o 100000 nodos por archivo.

Los archivos fuente conservan las licencias y condiciones de sus repositorios.
`license_spdx` registra la licencia declarada por GitHub cuando existe; no se
atribuye una licencia única al contenido recolectado. Consultar source_url
para atribución y contexto. run.json informa métricas y errores de la extracción.
"""


class DatasetMiner:
    def __init__(self, client):
        self.client = client

    def extract(self, input_csv, output, workers=8, cache_dir=Path(".miner-cache")):
        started = time.perf_counter()
        output = Path(output)
        # A new directory prevents mixed snapshots or destructive replacement.
        if output.exists():
            raise ValueError(f"la salida ya existe; elige un directorio nuevo: {output}")
        candidates = read_candidates(input_csv)
        repositories = {}
        summary = ExtractionSummary()
        invalid = []
        for position, row in enumerate(candidates.to_dict("records"), start=2):
            try:
                ref = repository_from_row(row)
                repositories.setdefault(ref.full_name.lower(), ref)
            except ValueError as exc:
                summary.invalid_rows += 1
                invalid.append({"row": position, "error": str(exc)})
        summary.errors = summary.invalid_rows
        output.parent.mkdir(parents=True, exist_ok=True)
        counts = dict.fromkeys(SCHEMAS, 0)
        extracted_at = datetime.now(timezone.utc)

        def process(ref):
            tables = {name: [] for name in SCHEMAS}
            name = ref.full_name.lower()
            repository_id = stable_id(name)
            repo_row = dict(repository_id=repository_id, full_name=name,
                            html_url=f"https://github.com/{name}", commit_sha=None,
                            license_spdx=None, extracted_at=extracted_at, status="ok", error=None)
            tables["repositories"].append(repo_row)
            stats = {"errors": 0, "cache_hits": 0, "downloads": 0}
            try:
                repo, commit, entries, license_spdx = self.client.snapshot(ref)
                repo_row.update(commit_sha=commit, license_spdx=license_spdx)
            except Exception as exc:
                repo_row.update(status="error", error=str(exc))
                stats["errors"] += 1
                return tables, stats
            paths = {entry.path for entry in entries}
            for entry in entries:
                if not entry.path.endswith(".md"):
                    continue
                workflow_id = stable_id(name, entry.path)
                row = dict(workflow_id=workflow_id, repository_id=repository_id,
                           path=entry.path, blob_sha=entry.sha,
                           source_url=f"https://github.com/{name}/blob/{commit}/{quote(entry.path)}",
                           has_lock=entry.path[:-3] + ".lock.yml" in paths,
                           frontmatter_yaml=None, status="ok", error=None)
                tables["workflows"].append(row)
                try:
                    text, cached = self.client.read_markdown(repo, entry, cache_dir)
                    stats["cache_hits" if cached else "downloads"] += 1
                except Exception as exc:
                    row.update(status="download_error", error=str(exc))
                    stats["errors"] += 1
                    continue
                raw, body, state = split_markdown(text)
                row["frontmatter_yaml"] = raw
                tables["bodies"].append(dict(workflow_id=workflow_id, markdown=body))
                if state != "present":
                    row.update(status=f"{state}_frontmatter", error=f"frontmatter {state}")
                    stats["errors"] += 1
                    continue
                try:
                    tables["frontmatter_nodes"].extend(parse_nodes(raw, workflow_id))
                except Exception as exc:
                    row.update(status="invalid_yaml", error=str(exc))
                    stats["errors"] += 1
            return tables, stats

        # Write incrementally by repository; publish the directory only on completion.
        with tempfile.TemporaryDirectory(prefix=".miner-", dir=output.parent) as staging:
            stage = Path(staging)
            writers = {}
            try:
                for name, table_schema in SCHEMAS.items():
                    writers[name] = pq.ParquetWriter(stage / f"{name}.parquet", table_schema, compression="zstd")
                for tables, stats in bounded_map(process, repositories.values(), workers):
                    for name, rows in tables.items():
                        if rows:
                            writers[name].write_table(pa.Table.from_pylist(rows, schema=SCHEMAS[name]))
                        counts[name] += len(rows)
                    for key, value in stats.items():
                        setattr(summary, key, getattr(summary, key) + value)
            finally:
                for writer in writers.values():
                    writer.close()
            summary.repositories = counts["repositories"]
            summary.workflows = counts["workflows"]
            summary.elapsed_seconds = round(time.perf_counter() - started, 3)
            (stage / "README.md").write_text(dataset_card(counts), encoding="utf-8")
            (stage / "run.json").write_text(json.dumps({
                "miner_version": "0.2.0", "input_sha256": hashlib.sha256(Path(input_csv).read_bytes()).hexdigest(),
                "workers": workers, "counts": counts, "summary": vars(summary),
                "invalid_rows": invalid,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            stage.rename(output)
        return summary
