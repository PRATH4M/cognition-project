"""Shared pytest fixtures."""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from helpers import FakeBriefGenerator, FakeGitHubClient
from pydantic import SecretStr

from app.cache import AnalysisStore, RepoAnalysisCache
from app.config import Settings
from app.github_client import GitHubClient
from app.main import create_app
from app.models import RepoRef
from app.service import AnalysisService

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


@pytest.fixture
def fake_client() -> FakeGitHubClient:
    """Return a fake GitHub client."""
    return FakeGitHubClient()


@pytest.fixture
def service(fake_client: FakeGitHubClient) -> AnalysisService:
    """Return an analysis service backed by the fake client."""
    return AnalysisService(
        fake_client,  # type: ignore[arg-type]
        AnalysisStore(3600),
        RepoAnalysisCache(3600),
    )


@pytest.fixture
def service_factory(fake_client: FakeGitHubClient) -> Any:
    """Return a factory for services with brief options."""

    def make(*, zdr_enabled: bool = False, brief_generator: Any = None) -> AnalysisService:
        return AnalysisService(
            fake_client,  # type: ignore[arg-type]
            AnalysisStore(3600),
            RepoAnalysisCache(3600),
            brief_generator=brief_generator,
            zdr_enabled=zdr_enabled,
        )

    return make


@pytest.fixture
def test_settings() -> Settings:
    """Return settings with all keys disabled, ignoring ``.env`` and env vars."""
    return Settings(
        _env_file=None,
        github_token=None,
        openrouter_api_key=None,
        llm_model=None,
    )


@pytest.fixture
def client(service: AnalysisService, test_settings: Settings) -> TestClient:
    """Return a test client for the app with the fake service."""
    return TestClient(create_app(test_settings, service=service), raise_server_exceptions=False)


@pytest.fixture
def brief_generator() -> FakeBriefGenerator:
    """Return a fake brief generator."""
    return FakeBriefGenerator()


@pytest.fixture
def brief_service(service_factory: Any, brief_generator: FakeBriefGenerator) -> AnalysisService:
    """Return a service with a fake brief generator and ZDR off."""
    return service_factory(brief_generator=brief_generator)


@pytest.fixture
def brief_client(brief_service: AnalysisService, test_settings: Settings) -> TestClient:
    """Return a test client whose service can generate briefs."""
    return TestClient(
        create_app(test_settings, service=brief_service), raise_server_exceptions=False
    )
