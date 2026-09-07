"""Orquestación del flujo completo de Miner."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from .csv_io import read_candidates, write_candidates
from .concurrency import bounded_map
from .detector import has_agentic_workflow
from .models import (
    MiningSummary,
    RepositoryReference,
    RepositoryReferenceError,
    repository_from_row,
)

logger = logging.getLogger(__name__)


class WorkflowRepositoryClient(Protocol):
    """Interfaz mínima que necesita el servicio para consultar GitHub."""

    def list_workflow_files(self, repository: RepositoryReference) -> Sequence[str]:
        ...


class Miner:
    """Procesa candidatos y conserva solo los repositorios con GH-AW."""

    def __init__(self, github_client: WorkflowRepositoryClient) -> None:
        self.github_client = github_client

    def run(self, input_csv: str | Path, output_csv: str | Path, workers: int = 1) -> MiningSummary:
        candidates = read_candidates(input_csv)
        matched_positions: list[int] = []
        invalid_rows = 0
        repositories = {}
        positions = []

        for position, row in enumerate(candidates.to_dict("records")):
            try:
                repository = repository_from_row(row)
            except (RepositoryReferenceError, ValueError) as exc:
                invalid_rows += 1
                logger.warning("Se ignora la fila %d: %s", position + 2, exc)
                continue

            key = repository.full_name.lower()
            repositories.setdefault(key, repository)
            positions.append((position, key))

        def detect(repository):
            return has_agentic_workflow(self.github_client.list_workflow_files(repository))

        cache = dict(zip(repositories, bounded_map(detect, repositories.values(), workers)))
        for position, key in positions:
            if cache[key]:
                matched_positions.append(position)

        filtered = candidates.iloc[matched_positions].copy()
        write_candidates(filtered, output_csv)

        return MiningSummary(
            input_rows=len(candidates),
            matched_rows=len(filtered),
            invalid_rows=invalid_rows,
            repositories_consulted=len(repositories),
        )


def mine(
    input_csv: str | Path,
    output_csv: str | Path,
    github_client: WorkflowRepositoryClient,
) -> MiningSummary:
    """Función de conveniencia para ejecutar Miner desde otras aplicaciones."""

    return Miner(github_client).run(input_csv, output_csv)
