import json
from types import SimpleNamespace

import pyarrow.parquet as pq
import pytest
import yaml

from miner.dataset import DatasetMiner, SCHEMAS
from miner.frontmatter import parse_nodes, split_markdown


class FakeClient:
    def __init__(self, files=None):
        self.files = files if files is not None else {
            ".github/workflows/daily.md": "---\non:\n  schedule:\n    - cron: '0 1 * * *'\nengine: copilot\npermissions: {}\n---\n\n# Hola\n",
            ".github/workflows/daily.lock.yml": "compiled",
        }
        self.calls = []

    def snapshot(self, ref):
        self.calls.append(ref.full_name)
        if ref.full_name == "org/error":
            raise RuntimeError("network failed")
        return object(), "abc123", [SimpleNamespace(path=p, sha=str(i))
                                     for i, p in enumerate(self.files)], "MIT"

    def read_markdown(self, repo, entry, cache_dir):
        value = self.files[entry.path]
        if isinstance(value, Exception):
            raise value
        return value, False


def extract(tmp_path, client, csv="name\nOrg/repo\norg/REPO\n"):
    source = tmp_path / "input.csv"
    source.write_text(csv)
    output = tmp_path / "dataset"
    result = DatasetMiner(client).extract(source, output, workers=3)
    tables = {name: pq.read_table(output / f"{name}.parquet").to_pylist() for name in SCHEMAS}
    return result, tables, output


def test_relations_types_dedup_and_card(tmp_path):
    client = FakeClient()
    result, tables, output = extract(tmp_path, client)
    assert result.errors == 0
    assert result.repositories == result.workflows == result.downloads == 1
    assert len(client.calls) == 1
    repo, = tables["repositories"]
    workflow, = tables["workflows"]
    body, = tables["bodies"]
    assert repo["repository_id"] == workflow["repository_id"]
    assert workflow["workflow_id"] == body["workflow_id"]
    assert body["markdown"] == "\n# Hola\n"
    assert workflow["has_lock"] is True
    nodes = tables["frontmatter_nodes"]
    ids = {node["node_id"] for node in nodes}
    assert len(ids) == len(nodes)
    assert all(n["parent_node_id"] is None or n["parent_node_id"] in ids for n in nodes)
    assert all(n["workflow_id"] == workflow["workflow_id"] for n in nodes)
    cron = next(n for n in nodes if n["pointer"] == "/on/schedule/0/cron")
    assert json.loads(cron["value_json"]) == "0 1 * * *"
    for name, expected in SCHEMAS.items():
        assert pq.read_schema(output / f"{name}.parquet").equals(expected)
    raw, _, _ = split_markdown((output / "README.md").read_text())
    assert {c["config_name"] for c in yaml.safe_load(raw)["configs"]} == set(SCHEMAS)


def test_failed_files_and_repositories_preserve_available_data(tmp_path):
    client = FakeClient({
        ".github/workflows/invalid.md": "---\non: [\n---\nbody\n",
        ".github/workflows/missing.md": "body only\n",
        ".github/workflows/unclosed.md": "---\non: push\nbody",
        ".github/workflows/error.md": RuntimeError("gone"),
    })
    result, tables, _ = extract(tmp_path, client, "name\norg/repo\norg/error\ninvalid\n")
    assert result.errors == 6
    assert result.invalid_rows == 1
    assert len(tables["bodies"]) == 3
    assert tables["frontmatter_nodes"] == []
    assert {w["status"] for w in tables["workflows"]} == {
        "invalid_yaml", "missing_frontmatter", "unclosed_frontmatter", "download_error"}
    assert tables["repositories"][1]["status"] == "error"


def test_empty_dataset_has_typed_tables_and_existing_output_is_preserved(tmp_path):
    result, tables, output = extract(tmp_path, FakeClient({}), "name\n")
    assert result.repositories == 0
    assert all(not rows for rows in tables.values())
    with pytest.raises(ValueError, match="ya existe"):
        DatasetMiner(FakeClient()).extract(tmp_path / "input.csv", output)
    assert (output / "README.md").exists()


@pytest.mark.parametrize("raw", [
    "key: [", "- sequence", "key: 1\nkey: 2", "1: value", "x: !!python/object:os {}",
    "x: &x [*x]", "x: .inf", "x: !!binary SGk=", "x: " + "[" * 70 + "]" * 70,
])
def test_invalid_or_unsafe_yaml(raw):
    with pytest.raises((ValueError, yaml.YAMLError, RecursionError)):
        parse_nodes(raw, "wf")


def test_yaml_types_and_json_pointer_escaping():
    nodes = parse_nodes('on: push\nno: off\nbool: true\nempty: null\nnum: 3\nfloat: 1.5\ndate: 2026-09-06\na/b~c: []\n', "wf")
    indexed = {n["pointer"]: n for n in nodes}
    assert indexed["/on"]["value_json"] == '"push"'
    assert indexed["/no"]["value_json"] == '"off"'
    assert indexed["/bool"]["kind"] == "boolean"
    assert indexed["/empty"]["value_json"] == "null"
    assert indexed["/num"]["kind"] == "integer"
    assert indexed["/float"]["kind"] == "number"
    assert indexed["/date"]["kind"] == "string"
    assert indexed["/a~1b~0c"]["kind"] == "sequence"


def test_bom_crlf_and_body_delimiters_are_preserved():
    raw, body, state = split_markdown('\ufeff---\r\non: push\r\n---\r\n\r\n# Title\r\n---\r\n')
    assert raw == "on: push\r\n"
    assert body == "\r\n# Title\r\n---\r\n"
    assert state == "present"
    assert parse_nodes("", "wf")[0]["kind"] == "mapping"


def test_output_is_deterministic_between_worker_counts(tmp_path):
    source = tmp_path / "input.csv"
    source.write_text("name\norg/a\norg/b\norg/c\n")
    for workers in (1, 4):
        DatasetMiner(FakeClient()).extract(source, tmp_path / str(workers), workers=workers)
    for name in ("workflows", "bodies", "frontmatter_nodes"):
        assert pq.read_table(tmp_path / "1" / f"{name}.parquet").equals(
            pq.read_table(tmp_path / "4" / f"{name}.parquet"))
