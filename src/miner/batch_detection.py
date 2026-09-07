"""GraphQL batches and resumable SQLite checkpoints for large candidate CSVs."""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time

import httpx
import pandas as pd

from .concurrency import bounded_unordered_map
from .detector import has_agentic_workflow
from .models import MiningSummary, repository_from_row

logger = logging.getLogger(__name__)


class GraphQLDetector:
    def __init__(self, token, rest_client, http=None, workers=4):
        self.http = http or httpx.Client(
            headers={"Authorization": f"Bearer {token}"}, timeout=90,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=8))
        self.rest = rest_client
        self._condition = threading.Condition()
        self._active = 0
        self._concurrency = workers
        self._resume_at = 0.0

    def close(self):
        self.http.close()

    def _post(self, query):
        with self._condition:
            while True:
                delay = self._resume_at - time.monotonic()
                if delay <= 0 and self._active < self._concurrency:
                    self._active += 1
                    break
                self._condition.wait(timeout=delay if delay > 0 else None)
        try:
            return self.http.post("https://api.github.com/graphql", json={"query": query})
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    def _cooldown(self, seconds, secondary=False):
        """Pause all workers together and reduce pressure after secondary limits."""
        with self._condition:
            now = time.monotonic()
            if secondary and now >= self._resume_at:
                self._concurrency = max(1, self._concurrency // 2)
                logger.warning("Concurrencia GraphQL reducida a %d", self._concurrency)
            self._resume_at = max(self._resume_at, now + max(1, seconds))
            self._condition.notify_all()

    def detect_batch(self, references):
        results = [[ref.full_name.lower(), False, "ok"] for ref in references]
        pending = [(index, ref, "HEAD:.github/workflows") for index, ref in enumerate(references)]
        while pending:
            batch, pending = pending[:100], pending[100:]
            data = self._query([(ref, expression) for _, ref, expression in batch])
            for alias_index, (index, ref, expression) in enumerate(batch):
                alias = f"r{alias_index}"
                if alias not in data:
                    raise RuntimeError(f"respuesta incompleta para {ref.full_name}")
                repo = data[alias]
                if repo is None:
                    results[index][2] = "unavailable"
                    continue
                tree = repo.get("object")
                if tree is None:
                    if expression != "HEAD:.github/workflows":
                        raise RuntimeError(f"árbol desaparecido: {ref.full_name}/{expression}")
                    continue
                entries = tree["entries"]
                if has_agentic_workflow(e["name"] for e in entries if e["type"] == "blob"):
                    results[index][1] = True
                if not results[index][1]:
                    pending.extend((index, ref, entry["oid"]) for entry in entries if entry["type"] == "tree")
            pending = [item for item in pending if not results[item[0]][1]]
        return [tuple(row) for row in results]

    def _query(self, objects):
        fields = []
        for index, (ref, expression) in enumerate(objects):
            owner, name = ref.full_name.split("/")
            fields.append(f"r{index}: repository(owner:{json.dumps(owner)}, name:{json.dumps(name)}) "
                          f'{{ object(expression:{json.dumps(expression)}) {{ ... on Tree {{ entries {{ name type oid }} }} }} }}')
        query = "query { " + " ".join(fields) + " rateLimit { cost remaining resetAt } }"
        for attempt in range(5):
            try:
                response = self._post(query)
                if response.status_code == 429 or (response.status_code == 403 and
                        ("retry-after" in response.headers or response.headers.get("x-ratelimit-remaining") == "0")):
                    # Respect primary and secondary rate limits, with bounded retries.
                    delay = float(response.headers.get("retry-after", 60))
                    if response.headers.get("x-ratelimit-remaining") == "0":
                        delay = max(delay, float(response.headers.get("x-ratelimit-reset", 0)) - time.time() + 1)
                    if attempt < 4:
                        logger.warning("GitHub limita las consultas; reintento en %.0f s", delay)
                        self._cooldown(delay, secondary=response.headers.get("x-ratelimit-remaining") != "0")
                        continue
                if response.status_code in {502, 504} and len(objects) > 1:
                    return self._split_query(objects)
                if response.status_code >= 500 and attempt < 4:
                    time.sleep(2 ** attempt)
                    continue
                response.raise_for_status()
                payload = response.json()
                errors = payload.get("errors", [])
                if any(error.get("type") == "RATE_LIMITED" for error in errors) and attempt < 4:
                    delay = max(60, float(response.headers.get("x-ratelimit-reset", 0)) - time.time() + 1)
                    logger.warning("Cuota GraphQL agotada; reintento en %.0f s", delay)
                    self._cooldown(delay)
                    continue
                if len(objects) > 1 and any(
                    error.get("type") in {"RESOURCE_LIMITS", "MAX_NODE_LIMIT_EXCEEDED", "INTERNAL"}
                    or "timeout" in error.get("message", "").lower()
                    or "something went wrong" in error.get("message", "").lower()
                    for error in errors
                ):
                    return self._split_query(objects)
                break
            except httpx.TransportError:
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
        errors = payload.get("errors", [])
        # Never turn an interrupted/unauthorized query into negative results.
        if any(error.get("type") != "NOT_FOUND" for error in errors):
            raise RuntimeError("GraphQL: " + "; ".join(e.get("message", "error") for e in errors))
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("GraphQL no devolvió datos")
        return data

    def _split_query(self, objects):
        """Large/expensive queries are retried as smaller batches without lost aliases."""
        middle = len(objects) // 2
        logger.warning("GitHub no pudo resolver un lote de %d; dividiendo en dos", len(objects))
        left = self._query(objects[:middle])
        right = self._query(objects[middle:])
        return {**{key: value for key, value in left.items() if key != "rateLimit"},
                **{f"r{int(key[1:]) + middle}": value for key, value in right.items() if key != "rateLimit"}}


def detect_large_csv(input_csv, output_csv, detector, checkpoint, workers=4, batch_size=100, progress=None):
    """Stream original columns; commit completed batches before reporting progress."""
    if not 1 <= batch_size <= 100:
        raise ValueError("batch-size debe estar entre 1 y 100")
    source, output, checkpoint = Path(input_csv), Path(output_csv), Path(checkpoint)
    if source.resolve() == output.resolve():
        raise ValueError("entrada y salida deben ser diferentes")
    output.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    totals = dict(input_rows=0, matched_rows=0, invalid_rows=0, repositories_consulted=0)
    unavailable = set()
    with sqlite3.connect(checkpoint) as db:
        db.execute("CREATE TABLE IF NOT EXISTS detection (repository TEXT PRIMARY KEY, matched INTEGER NOT NULL, status TEXT NOT NULL, checked_at TEXT NOT NULL)")
        with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".csv", delete=False) as handle:
            temporary = Path(handle.name)
        first = True
        try:
            for frame in pd.read_csv(source, dtype=str, keep_default_na=False, chunksize=5000):
                references, rows = {}, []
                # Validate only relevant rows; avoid materializing the whole input CSV.
                for position, row in enumerate(frame.to_dict("records")):
                    try:
                        ref = repository_from_row(row)
                    except ValueError:
                        totals["invalid_rows"] += 1
                        continue
                    key = ref.full_name.lower()
                    references.setdefault(key, ref)
                    rows.append((position, key))
                cached = {}
                keys = list(references)
                for offset in range(0, len(keys), 500):
                    subset = keys[offset:offset + 500]
                    placeholders = ",".join("?" for _ in subset)
                    for key, matched, status in db.execute(f"SELECT repository, matched, status FROM detection WHERE repository IN ({placeholders})", subset):
                        cached[key] = matched
                        if status == "unavailable":
                            unavailable.add(key)
                pending = [ref for key, ref in references.items() if key not in cached]
                batches = (pending[offset:offset + batch_size] for offset in range(0, len(pending), batch_size))
                for results in bounded_unordered_map(detector.detect_batch, batches, workers):
                    checked_at = datetime.now(timezone.utc).isoformat()
                    db.executemany("INSERT OR REPLACE INTO detection VALUES (?, ?, ?, ?)",
                                   [(key, int(matched), status, checked_at) for key, matched, status in results])
                    db.commit()
                    cached.update((key, matched) for key, matched, _ in results)
                    unavailable.update(key for key, _, status in results if status == "unavailable")
                    totals["repositories_consulted"] += len(results)
                    if progress:
                        progress(totals["input_rows"] + len(cached), totals["matched_rows"] + sum(cached.values()))
                selected = [position for position, key in rows if cached[key]]
                frame.iloc[selected].to_csv(temporary, index=False, mode="w" if first else "a", header=first)
                first = False
                totals["input_rows"] += len(frame)
                totals["matched_rows"] += len(selected)
                if progress:
                    progress(totals["input_rows"], totals["matched_rows"])
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
    totals["unavailable_repositories"] = len(unavailable)
    output.with_suffix(".report.json").write_text(json.dumps({
        "summary": totals, "checkpoint": str(checkpoint),
        "unavailable_repositories": sorted(unavailable),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return MiningSummary(**totals)
