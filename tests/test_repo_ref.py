"""Tests for RepoRef.parse input normalization."""

from __future__ import annotations

import pytest

from app.errors import InvalidRepoInputError
from app.models import RepoRef

VALID_CASES = [
    ("octo/repo", "octo", "repo"),
    ("  octo/repo  ", "octo", "repo"),
    ("https://github.com/octo/repo", "octo", "repo"),
    ("http://github.com/octo/repo", "octo", "repo"),
    ("github.com/octo/repo", "octo", "repo"),
    ("www.github.com/octo/repo", "octo", "repo"),
    ("https://github.com/octo/repo.git", "octo", "repo"),
    ("https://github.com/octo/repo/", "octo", "repo"),
    ("github.com/octo/repo/tree/main/src", "octo", "repo"),
    ("https://github.com/octo/repo?tab=readme-ov-file", "octo", "repo"),
    ("octo/repo#readme", "octo", "repo"),
    ("Octo/Repo", "Octo", "Repo"),
    ("owner/re.po_under-score", "owner", "re.po_under-score"),
    ("a/b", "a", "b"),
]

INVALID_CASES = [
    "",
    "   ",
    "hello",
    "owner",
    "github.com/owner",
    "https://gitlab.com/a/b",
    "https://example.com/a/b",
    "git@github.com:a/b",
    "ftp://github.com/a/b",
    "owner/re po",
    "ow ner/repo",
    "-owner/repo",
    "owner/-repo",
    "owner/..",
    "owner/.",
]


@pytest.mark.parametrize(("raw", "owner", "name"), VALID_CASES)
def test_parse_valid(raw: str, owner: str, name: str) -> None:
    """Valid inputs normalize to owner/repo."""
    ref = RepoRef.parse(raw)
    assert ref.owner == owner
    assert ref.name == name
    assert ref.full_name == f"{owner}/{name}"


@pytest.mark.parametrize("raw", INVALID_CASES)
def test_parse_rejects(raw: str) -> None:
    """Invalid inputs raise InvalidRepoInputError with the FR1 message."""
    with pytest.raises(InvalidRepoInputError, match="owner/name"):
        RepoRef.parse(raw)
