"""Regla para identificar GitHub Agentic Workflows."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePosixPath


LOCK_SUFFIX = ".lock.yml"


def _normalized_path(path: str) -> str:
    """Normaliza separadores conservando el directorio de cada archivo."""

    return str(PurePosixPath(str(path).replace("\\", "/")))


def has_agentic_workflow(files: Iterable[str]) -> bool:
    """Devuelve si ``files`` contiene un par ``name.md``/``name.lock.yml``.

    El iterable representa los archivos encontrados dentro de
    `.github/workflows/`; se aceptan tanto nombres simples como rutas completas
    devueltas por la API de GitHub.
    """

    markdown_bases: set[str] = set()
    lock_bases: set[str] = set()

    for path in files:
        name = _normalized_path(path)
        if name.endswith(".md"):
            base = name[: -len(".md")]
            if base:
                markdown_bases.add(base)
        elif name.endswith(LOCK_SUFFIX):
            base = name[: -len(LOCK_SUFFIX)]
            if base:
                lock_bases.add(base)

    return bool(markdown_bases & lock_bases)


# Nombre alternativo explícito para usar la función desde otras integraciones.
uses_ghaw = has_agentic_workflow
