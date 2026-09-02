import pytest

from miner.detector import has_agentic_workflow


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        (["report.md", "report.lock.yml"], True),
        (["report.md"], False),
        (["report.lock.yml"], False),
        (["report.md", "other.lock.yml"], False),
        ([".github/workflows/daily-report.md", ".github/workflows/daily-report.lock.yml"], True),
        (["report.md", "report.lock.yaml"], False),
        ([], False),
    ],
)
def test_has_agentic_workflow(files, expected):
    assert has_agentic_workflow(files) is expected
