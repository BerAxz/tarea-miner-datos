"""Cliente de GitHub utilizado por Miner."""

from __future__ import annotations

from collections.abc import Iterable
import base64
import hashlib
import os
from pathlib import Path
import tempfile
import threading
from typing import Any

from github import Auth, Github
from github.GithubException import GithubException

from .models import RepositoryReference


WORKFLOWS_PATH = ".github/workflows"


class GitHubRepositoryClient:
    """Consulta recursivamente los archivos de workflows de un repositorio."""

    def __init__(self, token: str, github_api: Any | None = None) -> None:
        if not token or not token.strip():
            raise ValueError("se requiere un token de GitHub")
        self._token = token
        self._injected_api = github_api
        self._local = threading.local()
        self._clients = []
        self._clients_lock = threading.Lock()

    @property
    def _github(self):
        if self._injected_api is not None:
            return self._injected_api
        if not hasattr(self._local, "api"):
            self._local.api = Github(auth=Auth.Token(self._token), timeout=30)
            with self._clients_lock:
                self._clients.append(self._local.api)
        return self._local.api

    def snapshot(self, repository):
        """Pin reads to one commit and list only the workflows subtree."""
        repo = self._github.get_repo(repository.full_name)
        commit = repo.get_branch(repo.default_branch).commit.sha
        pending = list(self._get_contents(repo, WORKFLOWS_PATH, commit))
        files = []
        while pending:
            entry = pending.pop()
            if entry.type == "dir":
                # Unlike the optional root, a vanished child is an error.
                pending.extend(repo.get_contents(entry.path, ref=commit))
            elif entry.type == "file":
                files.append(entry)
        license_info = repo.raw_data.get("license") or {}
        return repo, commit, sorted(files, key=lambda entry: entry.path), license_info.get("spdx_id")

    @staticmethod
    def read_markdown(repo, entry, cache_dir):
        """Fetch immutable blobs; validate cached bytes against Git's blob SHA."""
        cache_path = Path(cache_dir) / entry.sha[:2] / entry.sha

        def valid(data):
            header = f"blob {len(data)}\0".encode("ascii")
            return hashlib.sha1(header + data).hexdigest() == entry.sha

        if cache_path.is_file():
            data = cache_path.read_bytes()
            if valid(data):
                return data.decode("utf-8"), True
        blob = repo.get_git_blob(entry.sha)
        if blob.encoding != "base64":
            raise ValueError("encoding de blob no soportado")
        data = base64.b64decode(blob.content)
        if not valid(data):
            raise ValueError("SHA del contenido no coincide con GitHub")
        text = data.decode("utf-8")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cache_path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
        try:
            os.replace(temporary, cache_path)
        finally:
            temporary.unlink(missing_ok=True)
        return text, False

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

        clients = [self._injected_api] if self._injected_api is not None else self._clients
        for client in clients:
            close = getattr(client, "close", None)
            if close is not None:
                close()
        self._clients.clear()
