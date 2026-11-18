"""Tests for the analysis service with a mocked GitHub client."""

from __future__ import annotations

import pytest
from helpers import FakeGitHubClient, make_repo
from pydantic import SecretStr

from app.errors import (
    InvalidRepoInputError,
    RateLimitError,
    RepoNotFoundError,
    SectionUnavailableError,
)
from app.models import GitHubResponse, RateLimitInfo
from app.service import AnalysisService


async def test_analyze_public_repo_happy_path(service: AnalysisService) -> None:
    """A public repo produces a full report and is cached."""
    outcome = await service.analyze("octo/repo")
    assert outcome.report.metadata.full_name == "octo/repo"
    assert outcome.analysis_id
    assert outcome.cached is False
    assert outcome.is_private is False
    assert outcome.rate_limit is not None
    assert outcome.report.unavailable_sections == []
    assert outcome.report.pending_sections == []


async def test_analyze_repeat_uses_repo_cache(
    service: AnalysisService, fake_client: FakeGitHubClient
) -> None:
    """A repeat analysis makes zero GitHub calls."""
    first = await service.analyze("octo/repo")
    second = await service.analyze("octo/repo")
    assert second.cached is True
    assert second.analysis_id == first.analysis_id
    assert len(fake_client.calls) == 5


async def test_analyze_cache_key_is_github_full_name_lowercased(
    service: AnalysisService, fake_client: FakeGitHubClient
) -> None:
    """Octo/Repo from GitHub caches lookups for any input casing."""
    fake_client.repo_response = GitHubResponse(
        data=make_repo(full_name="Octo/Repo"), rate_limit=RateLimitInfo(remaining=59)
    )
    await service.analyze("octo/repo")
    calls_after_first = len(fake_client.calls)
    outcome = await service.analyze("OCTO/REPO")
    assert outcome.cached is True
    assert len(fake_client.calls) == calls_after_first


async def test_analyze_private_repo_not_cached(
    service: AnalysisService, fake_client: FakeGitHubClient
) -> None:
    """Private results get an analysis_id but are never repo-cached."""
    fake_client.repo_response = GitHubResponse(
        data=make_repo(private=True, full_name="octo/secret"),
        rate_limit=RateLimitInfo(remaining=59),
    )
    outcome = await service.analyze("octo/secret")
    assert outcome.is_private is True
    assert outcome.analysis_id
    assert service.recent() == []
    await service.analyze("octo/secret")
    assert len(fake_client.calls) == 10


async def test_analyze_user_token_skips_repo_cache(
    service: AnalysisService, fake_client: FakeGitHubClient
) -> None:
    """Analyses with a per-request token are not repo-cached."""
    await service.analyze("octo/repo", user_token=SecretStr("user-token"))
    assert service.recent() == []
    assert "user-token" in fake_client.user_tokens


async def test_analyze_partial_result_not_repo_cached(
    service: AnalysisService, fake_client: FakeGitHubClient
) -> None:
    """A section failure yields a degraded report that is not cached."""
    fake_client.errors["contributors"] = SectionUnavailableError("contributors", "boom")
    outcome = await service.analyze("octo/repo")
    assert outcome.report.unavailable_sections == ["contributors"]
    assert outcome.report.contributors.contributors == []
    assert service.recent() == []
    await service.analyze("octo/repo")
    assert len(fake_client.calls) == 10


async def test_analyze_stats_pending_not_repo_cached(
    service: AnalysisService, fake_client: FakeGitHubClient
) -> None:
    """Stats still computing is not cached and surfaces as pending."""
    fake_client.activity_response = GitHubResponse(
        data=None, rate_limit=RateLimitInfo(remaining=59), stats_pending=True
    )
    outcome = await service.analyze("octo/repo")
    assert outcome.report.pending_sections == ["commit_activity"]
    assert outcome.report.activity.pending is True
    assert service.recent() == []
    await service.analyze("octo/repo")
    assert len(fake_client.calls) == 10


async def test_analyze_repo_not_found(
    service: AnalysisService, fake_client: FakeGitHubClient
) -> None:
    """Repo metadata failure propagates."""
    fake_client.errors["repo"] = RepoNotFoundError("not found")
    with pytest.raises(RepoNotFoundError):
        await service.analyze("octo/missing")


async def test_analyze_invalid_input(service: AnalysisService) -> None:
    """Unparseable input fails before any GitHub call."""
    with pytest.raises(InvalidRepoInputError):
        await service.analyze("not a repo")


async def test_analyze_rate_limited(
    service: AnalysisService, fake_client: FakeGitHubClient
) -> None:
    """Rate limiting propagates."""
    fake_client.errors["repo"] = RateLimitError("slow down", rate_limit=RateLimitInfo(remaining=0))
    with pytest.raises(RateLimitError):
        await service.analyze("octo/repo")
