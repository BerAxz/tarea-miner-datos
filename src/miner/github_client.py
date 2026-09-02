"""Cliente de GitHub utilizado por Miner."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from github import Github
from github.GithubException import GithubException

from .models import RepositoryReference


WORKFLOWS_PATH = ".github/workflows"


class GitHubRepositoryClient:
    """Consulta recursivamente los archivos de workflows de un repositorio."""

    def __init__(self, token: str, github_api: Any | None = None) -> None:
        if not token or not token.strip():
            raise ValueError("se requiere un token de GitHub")
        self._github = github_api if github_api is not None else Github(token)

    def list_workflow_files(self, repository: RepositoryReference) -> tuple[str, ...]:
        """Devuelve las rutas de archivos bajo `.github/workflows/`.

        Un 404 en este directorio significa que el repositorio no tiene
        workflows y se interpreta como una lista vacía. Otros errores de la API
        se propagan para no ocultar problemas de autenticación, red o límites.
        """

        repo = self._github.get_repo(repository.full_name)
        ref = getattr(repo, "default_branch", None)
        pending = list(self._get_contents(repo, WORKFLOWS_PATH, ref))
        files: list[str] = []

        while pending:
            content = pending.pop()
            path = getattr(content, "path", None)
            content_type = getattr(content, "type", None)
            if not path:
                continue
            if content_type == "dir":
                pending.extend(self._get_contents(repo, path, ref))
            elif content_type == "file":
                files.append(path)

        return tuple(files)

    @staticmethod
    def _get_contents(repo: Any, path: str, ref: str | None) -> Iterable[Any]:
        try:
            contents = repo.get_contents(path, ref=ref) if ref else repo.get_contents(path)
        except GithubException as exc:
            if getattr(exc, "status", None) == 404:
                return ()
            raise

        if isinstance(contents, list):
            return contents
        return (contents,)

    def close(self) -> None:
        """Libera la conexión HTTP si la versión de PyGithub lo permite."""

        close = getattr(self._github, "close", None)
        if close is not None:
            close()
