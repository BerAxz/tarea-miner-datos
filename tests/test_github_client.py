import base64
import hashlib
from types import SimpleNamespace
from unittest.mock import Mock

from github.GithubException import GithubException
import pytest

from miner.github_client import GitHubRepositoryClient
from miner.models import RepositoryReference


def test_verified_cache_avoids_network_and_repairs_corruption(tmp_path):
    data = b"---\non: push\n---\n# Hello\n"
    sha = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    repo = Mock()
    repo.get_git_blob.return_value = SimpleNamespace(encoding="base64", content=base64.b64encode(data))
    entry = SimpleNamespace(sha=sha)
    assert GitHubRepositoryClient.read_markdown(repo, entry, tmp_path) == (data.decode(), False)
    assert GitHubRepositoryClient.read_markdown(repo, entry, tmp_path) == (data.decode(), True)
    repo.get_git_blob.assert_called_once_with(sha)
    (tmp_path / sha[:2] / sha).write_bytes(b"corrupt")
    assert GitHubRepositoryClient.read_markdown(repo, entry, tmp_path) == (data.decode(), False)
    assert repo.get_git_blob.call_count == 2


def test_snapshot_pins_every_directory_read_and_records_license():
    repo = Mock(default_branch="main", raw_data={"license": {"spdx_id": "MIT"}})
    repo.get_branch.return_value.commit.sha = "commit"
    repo.get_contents.side_effect = [
        [SimpleNamespace(type="dir", path=".github/workflows/nested")],
        [SimpleNamespace(type="file", path=".github/workflows/nested/a.md")],
    ]
    api = Mock()
    api.get_repo.return_value = repo
    client = GitHubRepositoryClient("test", github_api=api)
    _, commit, entries, license_id = client.snapshot(RepositoryReference(full_name="org/repo"))
    assert commit == "commit"
    assert license_id == "MIT"
    assert len(entries) == 1
    assert all(call.kwargs["ref"] == "commit" for call in repo.get_contents.call_args_list)


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_api_errors_are_not_treated_as_empty_directories(status):
    repo = Mock()
    repo.get_contents.side_effect = GithubException(status, {"message": "failure"})
    with pytest.raises(GithubException):
        GitHubRepositoryClient._get_contents(repo, ".github/workflows", "commit")


def test_absent_workflows_is_empty():
    repo = Mock()
    repo.get_contents.side_effect = GithubException(404, {})
    assert GitHubRepositoryClient._get_contents(repo, ".github/workflows", "commit") == ()
