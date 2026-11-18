"""Tests for the AI brief flow; all LLM calls are faked."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from helpers import FakeBriefGenerator, FakeGitHubClient, make_repo

from app.errors import AnalysisNotFoundError, BriefGenerationError
from app.models import GitHubResponse, RateLimitInfo
from app.service import AnalysisService


async def test_analyze_fetches_readme_when_brief_possible(
    service_factory: Any, fake_client: FakeGitHubClient, brief_generator: FakeBriefGenerator
) -> None:
    """A configured generator triggers a README fetch during analysis."""
    service = service_factory(brief_generator=brief_generator)
    outcome = await service.analyze("octo/repo")
    assert "readme:octo/repo" in fake_client.calls
    assert outcome.brief_available is True
    assert outcome.brief_blocked_reason is None


async def test_analyze_skips_readme_without_generator(
    service: AnalysisService, fake_client: FakeGitHubClient
) -> None:
    """No generator means no README call and the brief is unavailable."""
    outcome = await service.analyze("octo/repo")
    assert "readme:octo/repo" not in fake_client.calls
    assert outcome.brief_available is False
    assert outcome.brief_blocked_reason == "No LLM key configured"


async def test_analyze_private_without_zdr_skips_readme(
    service_factory: Any,
    fake_client: FakeGitHubClient,
    brief_generator: FakeBriefGenerator,
) -> None:
    """Private repos skip the README unless ZDR is enabled."""
    fake_client.repo_response = GitHubResponse(
        data=make_repo(private=True, full_name="octo/secret"),
        rate_limit=RateLimitInfo(remaining=59),
    )
    service = service_factory(brief_generator=brief_generator, zdr_enabled=False)
    outcome = await service.analyze("octo/secret")
    assert "readme:octo/secret" not in fake_client.calls
    assert outcome.brief_available is False
    assert outcome.brief_blocked_reason == "Private repos need zero-data-retention enabled"


async def test_analyze_private_with_zdr_fetches_readme(
    service_factory: Any,
    fake_client: FakeGitHubClient,
    brief_generator: FakeBriefGenerator,
) -> None:
    """ZDR-enabled private repos fetch the README for briefs."""
    fake_client.repo_response = GitHubResponse(
        data=make_repo(private=True, full_name="octo/secret"),
        rate_limit=RateLimitInfo(remaining=59),
    )
    service = service_factory(brief_generator=brief_generator, zdr_enabled=True)
    outcome = await service.analyze("octo/secret")
    assert "readme:octo/secret" in fake_client.calls
    assert outcome.brief_available is True


async def test_analyze_readme_failure_still_analyzes(
    service_factory: Any,
    fake_client: FakeGitHubClient,
    brief_generator: FakeBriefGenerator,
) -> None:
    """A failed README fetch degrades silently to no readme."""
    from app.errors import SectionUnavailableError

    service = service_factory(brief_generator=brief_generator)
    fake_client.errors["readme"] = SectionUnavailableError("readme", "boom")
    outcome = await service.analyze("octo/repo")
    assert outcome.report.metadata.full_name == "octo/repo"


async def test_generate_brief_unknown_id(
    service_factory: Any, brief_generator: FakeBriefGenerator
) -> None:
    """Unknown analysis IDs raise a not-found error."""
    service = service_factory(brief_generator=brief_generator)
    with pytest.raises(AnalysisNotFoundError):
        await service.generate_brief("nope")


async def test_generate_brief_success_and_cached(
    service_factory: Any,
    fake_client: FakeGitHubClient,
    brief_generator: FakeBriefGenerator,
) -> None:
    """The first brief call hits the generator; repeats return the stored brief."""
    service = service_factory(brief_generator=brief_generator)
    outcome = await service.analyze("octo/repo")
    result = await service.generate_brief(outcome.analysis_id)
    assert result.brief is not None
    assert result.reason is None
    assert len(brief_generator.calls) == 1
    assert brief_generator.calls[0][1] == "# Demo\n\nA demo repository."
    again = await service.generate_brief(outcome.analysis_id)
    assert again.brief == result.brief
    assert len(brief_generator.calls) == 1


async def test_generate_brief_unavailable_without_generator(service: AnalysisService) -> None:
    """Without a generator the result carries a reason and no brief."""
    outcome = await service.analyze("octo/repo")
    result = await service.generate_brief(outcome.analysis_id)
    assert result.brief is None
    assert result.reason == "No LLM key configured"


async def test_generate_brief_private_without_zdr(
    service_factory: Any,
    fake_client: FakeGitHubClient,
    brief_generator: FakeBriefGenerator,
) -> None:
    """Private analyses without ZDR cannot generate briefs."""
    fake_client.repo_response = GitHubResponse(
        data=make_repo(private=True, full_name="octo/secret"),
        rate_limit=RateLimitInfo(remaining=59),
    )
    service = service_factory(brief_generator=brief_generator, zdr_enabled=False)
    outcome = await service.analyze("octo/secret")
    result = await service.generate_brief(outcome.analysis_id)
    assert result.brief is None
    assert result.reason == "Private repos need zero-data-retention enabled"
    assert len(brief_generator.calls) == 0


async def test_generate_brief_failure_not_stored(
    service_factory: Any, brief_generator: FakeBriefGenerator
) -> None:
    """LLM failures propagate and are not cached, so retry works."""
    brief_generator.error = BriefGenerationError("boom")
    service = service_factory(brief_generator=brief_generator)
    outcome = await service.analyze("octo/repo")
    with pytest.raises(BriefGenerationError):
        await service.generate_brief(outcome.analysis_id)
    brief_generator.error = None
    result = await service.generate_brief(outcome.analysis_id)
    assert result.brief is not None
    assert len(brief_generator.calls) == 2


def _analyze_id(client: TestClient) -> str:
    """Analyze a repo through the API and return its analysis ID."""
    response = client.post("/api/analyze", json={"repo": "octo/repo"})
    assert response.status_code == 200
    return response.json()["analysis_id"]


def test_api_brief_success(brief_client: TestClient, brief_generator: FakeBriefGenerator) -> None:
    """The API returns the generated brief."""
    analysis_id = _analyze_id(brief_client)
    response = brief_client.post("/api/brief", json={"analysis_id": analysis_id})
    assert response.status_code == 200
    body = response.json()
    assert body["brief"]["summary"] == "A demo repo."
    assert body["reason"] is None
    brief_client.post("/api/brief", json={"analysis_id": analysis_id})
    assert len(brief_generator.calls) == 1


def test_api_brief_unavailable(client: TestClient) -> None:
    """No generator returns 200 with a null brief and a reason."""
    analysis_id = _analyze_id(client)
    response = client.post("/api/brief", json={"analysis_id": analysis_id})
    assert response.status_code == 200
    body = response.json()
    assert body["brief"] is None
    assert body["reason"] == "No LLM key configured"


def test_api_brief_unknown_id(client: TestClient) -> None:
    """Unknown analysis IDs return 404."""
    response = client.post("/api/brief", json={"analysis_id": "missing"})
    assert response.status_code == 404
    assert "detail" in response.json()


def test_api_brief_llm_failure_is_502(
    service_factory: Any, fake_client: FakeGitHubClient, test_settings: Any
) -> None:
    """LLM failures map to 502."""
    generator = FakeBriefGenerator(error=BriefGenerationError("boom"))
    service = service_factory(brief_generator=generator)
    from app.main import create_app

    client = TestClient(create_app(test_settings, service=service), raise_server_exceptions=False)
    analysis_id = _analyze_id(client)
    response = client.post("/api/brief", json={"analysis_id": analysis_id})
    assert response.status_code == 502
    assert "detail" in response.json()


def test_brief_form_renders_partial(brief_client: TestClient) -> None:
    """The HTML brief route returns the brief partial for HTMX."""
    analysis_id = _analyze_id(brief_client)
    response = brief_client.post(
        "/brief",
        data={"analysis_id": analysis_id},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "A demo repo." in response.text
    assert "<html" not in response.text


def test_brief_form_full_page(brief_client: TestClient) -> None:
    """A normal form post returns a full page."""
    analysis_id = _analyze_id(brief_client)
    response = brief_client.post("/brief", data={"analysis_id": analysis_id})
    assert response.status_code == 200
    assert "<html" in response.text
    assert "A demo repo." in response.text


def test_brief_form_unknown_id(client: TestClient) -> None:
    """Unknown IDs render the error page."""
    response = client.post("/brief", data={"analysis_id": "missing"})
    assert response.status_code == 404
