from pathlib import Path

import pandas as pd

from miner.models import RepositoryReference
from miner.service import Miner


class FakeGitHubClient:
    def __init__(self, files_by_repository):
        self.files_by_repository = files_by_repository
        self.calls = []

    def list_workflow_files(self, repository: RepositoryReference):
        self.calls.append(repository.full_name)
        return self.files_by_repository.get(repository.full_name, [])


def test_miner_writes_only_repositories_with_agentic_workflows(tmp_path: Path):
    input_csv = tmp_path / "candidates.csv"
    output_csv = tmp_path / "result.csv"
    input_csv.write_text(
        "name,language\n"
        "octo/with-ghaw,Python\n"
        "octo/without-ghaw,Go\n"
        "octo/with-ghaw,Python\n",
        encoding="utf-8",
    )
    client = FakeGitHubClient(
        {
            "octo/with-ghaw": ["daily.md", "daily.lock.yml"],
            "octo/without-ghaw": ["daily.md"],
        }
    )

    summary = Miner(client).run(input_csv, output_csv)

    result = pd.read_csv(output_csv, dtype=str)
    assert result["name"].tolist() == ["octo/with-ghaw", "octo/with-ghaw"]
    assert result["language"].tolist() == ["Python", "Python"]
    assert summary.input_rows == 3
    assert summary.matched_rows == 2
    assert summary.invalid_rows == 0
    assert summary.repositories_consulted == 2
    assert client.calls == ["octo/with-ghaw", "octo/without-ghaw"]
