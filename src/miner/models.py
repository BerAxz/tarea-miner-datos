"""Modelos y validaciones de los datos que usa Miner."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RepositoryReferenceError(ValueError):
    """Indica que una fila no contiene una referencia válida a GitHub."""


def normalize_full_name(value: Any) -> str:
    """Convierte un nombre o URL de GitHub a ``owner/repository``.

    Se aceptan nombres completos, URLs web/API y URLs SSH para que el lector
    pueda trabajar con distintos CSV sin acoplarse a un único formato.
    """

    if value is None or (isinstance(value, float) and math.isnan(value)):
        raise RepositoryReferenceError("la referencia del repositorio está vacía")

    raw = str(value).strip()
    if not raw:
        raise RepositoryReferenceError("la referencia del repositorio está vacía")

    if raw.startswith("git@github.com:"):
        raw = raw.removeprefix("git@github.com:")
    elif raw.startswith("github.com/"):
        raw = raw.removeprefix("github.com/")

    parsed = urlparse(raw if "://" in raw else "")
    if parsed.scheme and parsed.netloc:
        host = (parsed.hostname or "").lower()
        if host not in {"github.com", "www.github.com", "api.github.com"}:
            raise RepositoryReferenceError(
                f"la URL no pertenece a GitHub: {value!r}"
            )
        raw = parsed.path
        if host == "api.github.com" and raw.startswith("/repos/"):
            raw = raw.removeprefix("/repos/")

    raw = raw.strip().strip("/")
    if raw.endswith(".git"):
        raw = raw[:-4].rstrip("/")

    parts = raw.split("/")
    if len(parts) != 2 or any(not part or any(char.isspace() for char in part) for part in parts):
        raise RepositoryReferenceError(
            f"se esperaba un repositorio con formato owner/repo, recibido: {value!r}"
        )

    return f"{parts[0]}/{parts[1]}"


class RepositoryReference(BaseModel):
    """Referencia validada a un repositorio de GitHub."""

    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(..., description="Repositorio en formato owner/repo")

    @field_validator("full_name", mode="before")
    @classmethod
    def validate_full_name(cls, value: Any) -> str:
        return normalize_full_name(value)


# Alias corto y cómodo para consumidores de la biblioteca.
RepositoryRef = RepositoryReference


_REPOSITORY_FIELDS = (
    "full_name",
    "fullName",
    "repository",
    "repository_name",
    "repo",
    "repo_name",
    "name",
    "html_url",
    "repository_url",
    "repo_url",
    "github_url",
    "url",
)


def repository_from_row(row: Mapping[str, Any]) -> RepositoryReference:
    """Extrae y valida una referencia de repositorio desde una fila CSV.

    Se prueban varias columnas conocidas. Esto permite usar directamente el
    archivo de la Tarea 1 (`name`) y también exportaciones que traen una URL.
    Si existen columnas separadas `owner` y `repo`, se combinan como último
    recurso.
    """

    columns = {str(column).strip().lower(): column for column in row}
    errors: list[str] = []

    for field in _REPOSITORY_FIELDS:
        key = columns.get(field.lower())
        if key is None:
            continue
        value = row[key]
        try:
            return RepositoryReference(full_name=value)
        except (RepositoryReferenceError, ValueError) as exc:
            errors.append(str(exc))

    owner_key = columns.get("owner")
    repo_key = columns.get("repo") or columns.get("repository_name")
    if owner_key is not None and repo_key is not None:
        try:
            return RepositoryReference(
                full_name=f"{row[owner_key]}/{row[repo_key]}"
            )
        except (RepositoryReferenceError, ValueError) as exc:
            errors.append(str(exc))

    if errors:
        detail = errors[-1]
    else:
        detail = "no se encontró una columna de repositorio reconocida"
    raise RepositoryReferenceError(detail)


class MiningSummary(BaseModel):
    """Resultado validado del procesamiento de un archivo."""

    input_rows: int = Field(ge=0)
    matched_rows: int = Field(ge=0)
    invalid_rows: int = Field(ge=0)
    repositories_consulted: int = Field(ge=0)
