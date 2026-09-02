"""Orquestación del flujo completo de Miner."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from .csv_io import read_candidates, write_candidates
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

    def run(self, input_csv: str | Path, output_csv: str | Path) -> MiningSummary:
        candidates = read_candidates(input_csv)
        matched_positions: list[int] = []
        invalid_rows = 0
        repositories_consulted = 0
        cache: dict[str, bool] = {}

        for position, (_, row) in enumerate(candidates.iterrows()):
            try:
                repository = repository_from_row(row.to_dict())
            except (RepositoryReferenceError, ValueError) as exc:
                invalid_rows += 1
                logger.warning("Se ignora la fila %d: %s", position + 2, exc)
                continue

            if repository.full_name not in cache:
                files = self.github_client.list_workflow_files(repository)
                cache[repository.full_name] = has_agentic_workflow(files)
                repositories_consulted += 1

            if cache[repository.full_name]:
                matched_positions.append(position)

        filtered = candidates.iloc[matched_positions].copy()
        write_candidates(filtered, output_csv)

        return MiningSummary(
            input_rows=len(candidates),
            matched_rows=len(filtered),
            invalid_rows=invalid_rows,
            repositories_consulted=repositories_consulted,
        )


def mine(
    input_csv: str | Path,
    output_csv: str | Path,
    github_client: WorkflowRepositoryClient,
) -> MiningSummary:
    """Función de conveniencia para ejecutar Miner desde otras aplicaciones."""

    return Miner(github_client).run(input_csv, output_csv)
