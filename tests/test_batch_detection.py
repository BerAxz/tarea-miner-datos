from unittest.mock import Mock

import httpx
import pandas as pd
import pytest

from miner.batch_detection import GraphQLDetector, detect_large_csv
from miner.models import RepositoryReference


def test_graphql_batch_checks_pairs_and_does_not_confuse_directories():
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"data": {
        "r0": {"object": {"entries": [{"name": "x.md", "type": "blob"}, {"name": "x.lock.yml", "type": "blob"}]}},
        "r1": {"object": None}, "r2": None,
    }, "errors": [{"type": "NOT_FOUND", "message": "Could not resolve repository"}]}
    http = Mock()
    http.post.return_value = response
    detector = GraphQLDetector("test", Mock(), http=http)
    result = detector.detect_batch([RepositoryReference(full_name=f"org/r{i}") for i in range(3)])
    assert result == [("org/r0", True, "ok"), ("org/r1", False, "ok"), ("org/r2", False, "unavailable")]
    query = http.post.call_args.kwargs["json"]["query"]
    assert "r0: repository" in query and "r2: repository" in query


@pytest.mark.parametrize("payload", [
    {"errors": [{"type": "RATE_LIMITED", "message": "rate limited"}]},
    {"data": {}},
    {"errors": [{"type": "FORBIDDEN", "message": "denied"}], "data": {"r0": None}},
])
def test_graphql_incomplete_results_never_become_negative_matches(payload, monkeypatch):
    http = Mock()
    http.post.return_value.json.return_value = payload
    http.post.return_value.status_code = 200
    http.post.return_value.headers = {}
    monkeypatch.setattr("miner.batch_detection.time.sleep", lambda seconds: None)
    monkeypatch.setattr(GraphQLDetector, "_cooldown", lambda self, *args, **kwargs: None)
    with pytest.raises(RuntimeError):
        GraphQLDetector("test", Mock(), http=http).detect_batch([RepositoryReference(full_name="org/repo")])


class FakeDetector:
    def __init__(self):
        self.calls = []

    def detect_batch(self, references):
        self.calls.extend(r.full_name for r in references)
        return [(r.full_name.lower(), r.full_name.lower() == "org/yes", "ok") for r in references]


def test_streaming_detection_preserves_columns_duplicates_and_resumes(tmp_path):
    source = tmp_path / "input.csv.gz"
    pd.DataFrame({"name": ["org/yes", "org/no", "ORG/YES", "invalid"], "metric": ["001", "2", "003", "4"]}).to_csv(source, index=False)
    detector = FakeDetector()
    checkpoint = tmp_path / "checkpoint.sqlite"
    for i in range(2):
        summary = detect_large_csv(source, tmp_path / f"out{i}.csv", detector, checkpoint, batch_size=1)
        assert summary.input_rows == 4
        assert summary.matched_rows == 2
        assert summary.invalid_rows == 1
        assert summary.repositories_consulted == (2 if i == 0 else 0)
    assert len(detector.calls) == 2
    result = pd.read_csv(tmp_path / "out1.csv", dtype=str)
    assert result.to_dict("list") == {"name": ["org/yes", "ORG/YES"], "metric": ["001", "003"]}


def test_failure_keeps_checkpoint_and_previous_output(tmp_path):
    source = tmp_path / "input.csv"
    source.write_text("name\norg/yes\norg/no\n")
    output = tmp_path / "out.csv"
    output.write_text("previous")
    detector = FakeDetector()
    original = detector.detect_batch

    def fail_second(refs):
        if refs[0].full_name == "org/no":
            raise RuntimeError("interrupted")
        return original(refs)

    detector.detect_batch = fail_second
    checkpoint = tmp_path / "checkpoint.sqlite"
    with pytest.raises(RuntimeError):
        detect_large_csv(source, output, detector, checkpoint, workers=1, batch_size=1)
    assert output.read_text() == "previous"
    detector.detect_batch = original
    result = detect_large_csv(source, output, detector, checkpoint, workers=1, batch_size=1)
    assert result.repositories_consulted == 1
    assert detector.calls == ["org/yes", "org/no"]


def test_timeout_splits_queries_and_remaps_aliases():
    http = Mock()
    request = httpx.Request("POST", "https://api.github.com/graphql")
    http.post.side_effect = [
        httpx.Response(502, request=request),
        httpx.Response(200, json={"data": {"r0": {"object": None}}}, request=request),
        httpx.Response(200, json={"data": {"r0": {"object": {"entries": [
            {"name": "x.md", "type": "blob"}, {"name": "x.lock.yml", "type": "blob"}]}}}}, request=request),
    ]
    detector = GraphQLDetector("test", Mock(), http=http)
    assert detector.detect_batch([RepositoryReference(full_name=f"org/r{i}") for i in range(2)]) == [
        ("org/r0", False, "ok"), ("org/r1", True, "ok")]


def test_nested_directories_are_queried_by_immutable_tree_sha():
    http = Mock()
    request = httpx.Request("POST", "https://api.github.com/graphql")
    http.post.side_effect = [
        httpx.Response(200, json={"data": {"r0": {"object": {"entries": [
            {"name": "sub", "type": "tree", "oid": "tree-sha"}]}}}}, request=request),
        httpx.Response(200, json={"data": {"r0": {"object": {"entries": [
            {"name": "x.md", "type": "blob"}, {"name": "x.lock.yml", "type": "blob"}]}}}}, request=request),
    ]
    detector = GraphQLDetector("test", Mock(), http=http)
    assert detector.detect_batch([RepositoryReference(full_name="org/r")]) == [("org/r", True, "ok")]
    assert 'expression:"tree-sha"' in http.post.call_args.kwargs["json"]["query"]


def test_secondary_limit_reduces_concurrency_once_per_cooldown():
    detector = GraphQLDetector("test", Mock(), http=Mock(), workers=8)
    detector._cooldown(60, secondary=True)
    assert detector._concurrency == 4
    detector._cooldown(60, secondary=True)
    assert detector._concurrency == 4
