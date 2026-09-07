from unittest.mock import Mock

from typer.testing import CliRunner

from miner.cli import app
from miner.dataset import DatasetMiner
from miner.publication import publish_dataset
from test_dataset import FakeClient

runner = CliRunner()


def test_old_cli_and_explicit_detect_are_compatible(tmp_path, monkeypatch):
    source = tmp_path / "repos.csv"
    source.write_text("name\norg/repo\n")
    client = Mock()
    client.list_workflow_files.return_value = ["x.md", "x.lock.yml"]
    monkeypatch.setenv("GITHUB_TOKEN", "test")
    monkeypatch.setattr("miner.cli.GitHubRepositoryClient", lambda token: client)
    for arguments in (
        [str(source), "-o", str(tmp_path / "out.csv")],
        ["detect", str(source), "-o", str(tmp_path / "out.csv")],
        ["-o", str(tmp_path / "out.csv"), str(source)],
    ):
        result = runner.invoke(app, [*arguments, "--api", "rest"])
        assert result.exit_code == 0, result.output
    assert "org/repo" in (tmp_path / "out.csv").read_text()


def test_extract_cli_and_partial_exit_code(tmp_path, monkeypatch):
    source = tmp_path / "repos.csv"
    source.write_text("name\norg/repo\n")
    client = FakeClient({".github/workflows/x.md": "body"})
    client.close = Mock()
    monkeypatch.setenv("GITHUB_TOKEN", "test")
    monkeypatch.setattr("miner.cli.GitHubRepositoryClient", lambda token: client)
    result = runner.invoke(app, ["extract", str(source), "-o", str(tmp_path / "out")])
    assert result.exit_code == 2, result.output
    assert (tmp_path / "out" / "bodies.parquet").exists()
    client.close.assert_called_once()


def test_publish_uses_only_dataset_files(tmp_path):
    source = tmp_path / "repos.csv"
    source.write_text("name\norg/repo\n")
    output = tmp_path / "out"
    DatasetMiner(FakeClient()).extract(source, output)
    (output / ".env").write_text("not for upload")
    api = Mock()
    assert publish_dataset(output, "user/dataset", api=api) == "https://huggingface.co/datasets/user/dataset"
    assert ".env" not in api.upload_folder.call_args.kwargs["allow_patterns"]
    assert api.create_repo.call_args.kwargs["repo_type"] == "dataset"


def test_missing_token_fails_before_network(tmp_path, monkeypatch):
    source = tmp_path / "repos.csv"
    source.write_text("name\norg/repo\n")
    monkeypatch.setattr("miner.cli.load_dotenv", lambda: None)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    result = runner.invoke(app, ["extract", str(source)])
    assert result.exit_code == 1
    assert "GITHUB_TOKEN" in result.output
