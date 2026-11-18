"""Coordinates caching, GitHub fetches, and analysis."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import SecretStr

from app import analyzer
from app.cache import AnalysisStore, RepoAnalysisCache
from app.errors import AnalysisNotFoundError, SectionUnavailableError
from app.github_client import GitHubClient
from app.llm import MAX_README_CHARS, BriefGenerator
from app.models import (
    AnalysisReport,
    ContributorResult,
    GeneratedBrief,
    GitHubRepo,
    GitHubResponse,
    RateLimitInfo,
    RepoRef,
)

T = TypeVar("T")

NO_KEY_REASON = "No LLM key configured"
PRIVATE_REASON = "Private repos need zero-data-retention enabled"


@dataclass(frozen=True)
class AnalysisOutcome:
    """Result of an analysis request."""

    report: AnalysisReport
    analysis_id: str
    rate_limit: RateLimitInfo | None
    cached: bool
    is_private: bool
    brief_available: bool
    brief_blocked_reason: str | None


@dataclass(frozen=True)
class BriefResult:
    """Result of a brief request: a brief or the reason none is available."""

    brief: GeneratedBrief | None
    reason: str | None


class AnalysisService:
    """Runs analyses through the cache, GitHub client, and analyzer."""

    def __init__(
        self,
        client: GitHubClient,
        store: AnalysisStore,
        repo_cache: RepoAnalysisCache,
        *,
        brief_generator: BriefGenerator | None = None,
        zdr_enabled: bool = False,
    ) -> None:
        """Create a service with the given client, caches, and brief options."""
        self._client = client
        self._store = store
        self._repo_cache = repo_cache
        self._brief_generator = brief_generator
        self._zdr_enabled = zdr_enabled

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
        want_readme = self._brief_available(repo.private)
        calls: list[Coroutine[Any, Any, Any]] = [
            self._client.get_contributors(ref, user_token=user_token),
            self._client.get_commit_activity(ref, user_token=user_token),
            self._client.get_punch_card(ref, user_token=user_token),
            self._client.get_languages(ref, user_token=user_token),
            self._client.get_commit_count(ref, user_token=user_token),
        ]
        if want_readme:
            calls.append(self._readme(ref, user_token))
        results: list[Any] = await asyncio.gather(*calls, return_exceptions=True)
        sections = results[:5]
        readme_result = results[5] if want_readme else None
        if isinstance(readme_result, BaseException):
            raise readme_result
        readme_resp = readme_result if isinstance(readme_result, GitHubResponse) else None
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
        readme = (
            readme_resp.data[:MAX_README_CHARS]
            if readme_resp is not None and readme_resp.data
            else None
        )
        analysis_id = self._store.put(report, readme=readme, private=repo.private)
        if user_token is None and not repo.private and not unavailable and not pending:
            self._repo_cache.put(repo.full_name, analysis_id)
        return AnalysisOutcome(
            report=report,
            analysis_id=analysis_id,
            rate_limit=self._latest_rate_limit(repo_response, *results),
            cached=False,
            is_private=repo.private,
            brief_available=want_readme,
            brief_blocked_reason=None if want_readme else self._brief_blocked_reason(),
        )

    async def generate_brief(self, analysis_id: str) -> BriefResult:
        """Return the stored or newly generated brief for an analysis."""
        stored = self._store.get_stored(analysis_id)
        if stored is None:
            raise AnalysisNotFoundError("Analysis not found or expired")
        if stored.brief is not None:
            return BriefResult(brief=stored.brief, reason=None)
        if self._brief_generator is None or (stored.private and not self._zdr_enabled):
            return BriefResult(brief=None, reason=self._brief_blocked_reason())
        brief = await self._brief_generator.generate(
            stored.report, stored.readme, is_private=stored.private
        )
        self._store.set_brief(analysis_id, brief)
        return BriefResult(brief=brief, reason=None)

    def _brief_available(self, is_private: bool) -> bool:
        return self._brief_generator is not None and (not is_private or self._zdr_enabled)

    def _brief_blocked_reason(self) -> str:
        if self._brief_generator is None:
            return NO_KEY_REASON
        return PRIVATE_REASON

    async def _readme(
        self, ref: RepoRef, user_token: SecretStr | None
    ) -> GitHubResponse[str | None] | None:
        try:
            return await self._client.get_readme(ref, user_token=user_token)
        except SectionUnavailableError:
            return None

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
        available = self._brief_generator is not None
        return AnalysisOutcome(
            report=report,
            analysis_id=analysis_id,
            rate_limit=None,
            cached=True,
            is_private=False,
            brief_available=available,
            brief_blocked_reason=None if available else NO_KEY_REASON,
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
        *sections: object,
    ) -> RateLimitInfo:
        rate_limit = repo_response.rate_limit
        for section in sections:
            if isinstance(section, GitHubResponse):
                rate_limit = section.rate_limit
        return rate_limit
