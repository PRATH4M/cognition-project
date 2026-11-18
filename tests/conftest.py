"""Shared pytest fixtures."""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from pydantic import SecretStr

from app.config import Settings
from app.github_client import GitHubClient
from app.models import RepoRef

FAKE_GITHUB_VALUE = "test-github-token"
FAKE_OPENROUTER_VALUE = "test-openrouter-key"


@pytest.fixture(autouse=True)
def fake_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tests never use real API keys."""
    monkeypatch.setenv("GITHUB_TOKEN", FAKE_GITHUB_VALUE)
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_OPENROUTER_VALUE)
    monkeypatch.setenv("LLM_MODEL", "test/model")
    monkeypatch.setenv("LLM_ZDR_ENABLED", "false")
    monkeypatch.setenv("CACHE_TTL_SECONDS", "60")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")


@pytest.fixture
def repo_ref() -> RepoRef:
    """Return a normalized repository reference."""
    return RepoRef(owner="octo", name="repo")


@pytest.fixture
def settings() -> Settings:
    """Return settings built without reading ``.env``."""
    return Settings(_env_file=None)


@pytest_asyncio.fixture
async def client_factory() -> Any:
    """Return a factory for GitHub clients that are closed after the test."""
    clients: list[GitHubClient] = []

    def make(**kwargs: Any) -> GitHubClient:
        client = GitHubClient(**kwargs)
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.aclose()


@pytest.fixture
def user_token() -> SecretStr:
    """Return a fake per-request user token."""
    return SecretStr("user-token")
