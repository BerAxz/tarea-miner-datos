"""Lectura y escritura de los archivos CSV de Miner."""

from __future__ import annotations

from os import PathLike
from pathlib import Path

import pandas as pd


def read_candidates(path: str | PathLike[str]) -> pd.DataFrame:
    """Lee el CSV de candidatos conservando los valores como texto."""

    csv_path = Path(path)
    try:
        return pd.read_csv(
            csv_path,
            dtype=str,
            keep_default_na=False,
        )
    except pd.errors.EmptyDataError as exc:
        raise ValueError(f"el archivo CSV está vacío: {csv_path}") from exc


def write_candidates(
    candidates: pd.DataFrame,
    path: str | PathLike[str],
) -> None:
    """Escribe las filas filtradas sin agregar una columna índice."""

    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    candidates.to_csv(csv_path, index=False)
