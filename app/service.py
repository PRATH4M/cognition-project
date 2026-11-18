"""Coordinates caching, GitHub fetches, and analysis."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeVar

from pydantic import SecretStr

from app import analyzer
from app.cache import AnalysisStore, RepoAnalysisCache
from app.errors import SectionUnavailableError
from app.github_client import GitHubClient
from app.models import (
    AnalysisReport,
    ContributorResult,
    GitHubRepo,
    GitHubResponse,
    RateLimitInfo,
    RepoRef,
)

T = TypeVar("T")


@dataclass(frozen=True)
class AnalysisOutcome:
    """Result of an analysis request."""

    report: AnalysisReport
    analysis_id: str
    rate_limit: RateLimitInfo | None
    cached: bool
    is_private: bool


class AnalysisService:
    """Runs analyses through the cache, GitHub client, and analyzer."""

    def __init__(
        self,
        client: GitHubClient,
        store: AnalysisStore,
        repo_cache: RepoAnalysisCache,
    ) -> None:
        """Create a service with the given client and caches."""
        self._client = client
        self._store = store
        self._repo_cache = repo_cache

    async def analyze(
        self, raw_input: str, *, user_token: SecretStr | None = None
    ) -> AnalysisOutcome:
        """Analyze a repo, using the repo-name cache when eligible."""
        ref = RepoRef.parse(raw_input)
        if user_token is None:
            cached = self._cached_outcome(ref)
            if cached is not None:
                return cached

        repo_response = await self._client.get_repo(ref, user_token=user_token)
        repo = repo_response.data
        sections = await asyncio.gather(
            self._client.get_contributors(ref, user_token=user_token),
            self._client.get_commit_activity(ref, user_token=user_token),
            self._client.get_punch_card(ref, user_token=user_token),
            self._client.get_languages(ref, user_token=user_token),
            self._client.get_commit_count(ref, user_token=user_token),
            return_exceptions=True,
        )
        unavailable: list[str] = []
        pending: list[str] = []
        contributors_resp = self._section(sections[0], "contributors", unavailable)
        activity_resp = self._section(sections[1], "commit_activity", unavailable)
        punch_resp = self._section(sections[2], "punch_card", unavailable)
        languages_resp = self._section(sections[3], "languages", unavailable)
        count_resp = self._section(sections[4], "commit_count", unavailable)

        activity_pending = bool(activity_resp and activity_resp.stats_pending)
        punch_pending = bool(punch_resp and punch_resp.stats_pending)
        if activity_pending:
            pending.append("commit_activity")
        if punch_pending:
            pending.append("punch_card")

        report = analyzer.analyze(
            repo,
            contributors_resp.data if contributors_resp else ContributorResult(contributors=[]),
            activity_resp.data if activity_resp else None,
            activity_pending=activity_pending,
            punch_card=punch_resp.data if punch_resp else None,
            languages=languages_resp.data if languages_resp else {},
            unavailable_sections=unavailable,
            pending_sections=pending,
            commit_count=count_resp.data if count_resp else None,
            now=datetime.now(UTC),
        )
        analysis_id = self._store.put(report)
        if user_token is None and not repo.private and not unavailable and not pending:
            self._repo_cache.put(repo.full_name, analysis_id)
        return AnalysisOutcome(
            report=report,
            analysis_id=analysis_id,
            rate_limit=self._latest_rate_limit(repo_response, sections),
            cached=False,
            is_private=repo.private,
        )

    def recent(self) -> list[str]:
        """Return recently analyzed public repo names."""
        return self._repo_cache.recent()

    def _cached_outcome(self, ref: RepoRef) -> AnalysisOutcome | None:
        analysis_id = self._repo_cache.get(ref.full_name)
        if analysis_id is None:
            return None
        report = self._store.get(analysis_id)
        if report is None:
            return None
        return AnalysisOutcome(
            report=report,
            analysis_id=analysis_id,
            rate_limit=None,
            cached=True,
            is_private=False,
        )

    @staticmethod
    def _section(
        result: GitHubResponse[T] | BaseException,
        name: str,
        unavailable: list[str],
    ) -> GitHubResponse[T] | None:
        if isinstance(result, GitHubResponse):
            return result
        if isinstance(result, SectionUnavailableError):
            unavailable.append(name)
            return None
        raise result

    @staticmethod
    def _latest_rate_limit(
        repo_response: GitHubResponse[GitHubRepo],
        sections: tuple[object, ...],
    ) -> RateLimitInfo:
        rate_limit = repo_response.rate_limit
        for section in sections:
            if isinstance(section, GitHubResponse):
                rate_limit = section.rate_limit
        return rate_limit
