import pytest
from pydantic import ValidationError

from miner.models import RepositoryReference, repository_from_row


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("octo/example", "octo/example"),
        ("https://github.com/octo/example", "octo/example"),
        ("https://api.github.com/repos/octo/example", "octo/example"),
        ("git@github.com:octo/example.git", "octo/example"),
    ],
)
def test_repository_reference_normalizes_common_formats(value, expected):
    assert RepositoryReference(full_name=value).full_name == expected


def test_repository_from_row_uses_name_column():
    repository = repository_from_row({"name": "octo/example", "language": "Python"})

    assert repository.full_name == "octo/example"


def test_repository_from_row_falls_back_to_github_url():
    repository = repository_from_row({"name": "Example", "html_url": "https://github.com/octo/example"})

    assert repository.full_name == "octo/example"


def test_invalid_repository_reference_is_rejected():
    with pytest.raises((ValidationError, ValueError)):
        RepositoryReference(full_name="not-a-full-name")
