"""Shared test data builders."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import SecretStr

from app.analyzer import analyze
from app.models import (
    AnalysisReport,
    ContributorResult,
    GitHubCommitActivityWeek,
    GitHubContributor,
    GitHubLicense,
    GitHubRepo,
    GitHubResponse,
    PunchCardPoint,
    RateLimitInfo,
    RepoRef,
)

NOW = datetime(2026, 11, 19, tzinfo=UTC)


def make_repo(**overrides: object) -> GitHubRepo:
    """Build a repo payload with sensible defaults."""
    data: dict[str, object] = {
        "name": "repo",
        "full_name": "octo/repo",
        "html_url": "https://github.com/octo/repo",
        "description": "A test repo",
        "stargazers_count": 10,
        "forks_count": 3,
        "watchers_count": 10,
        "subscribers_count": 7,
        "open_issues_count": 4,
        "language": "Python",
        "license": GitHubLicense(spdx_id="MIT", name="MIT License"),
        "topics": ["api", "cli"],
        "created_at": datetime(2024, 1, 1, tzinfo=UTC),
        "pushed_at": datetime(2026, 11, 1, tzinfo=UTC),
        "archived": False,
        "private": False,
    }
    data.update(overrides)
    return GitHubRepo.model_validate(data)


def make_contributor(
    login: str | None = "alice",
    commits: int = 10,
    type: str = "User",
) -> GitHubContributor:
    """Build a contributor payload."""
    return GitHubContributor(
        login=login,
        avatar_url="https://avatars.example.com/a",
        html_url=f"https://github.com/{login}" if login else None,
        contributions=commits,
        type=type,
    )


def make_week(week: int, total: int) -> GitHubCommitActivityWeek:
    """Build a commit-activity week."""
    return GitHubCommitActivityWeek(week=week, total=total, days=[0] * 7)


def make_weeks(totals: list[int]) -> list[GitHubCommitActivityWeek]:
    """Build weeks oldest-first like GitHub returns them."""
    return [make_week(i + 1, total) for i, total in enumerate(totals)]


def make_contributors_result(
    contributors: list[GitHubContributor], **overrides: object
) -> ContributorResult:
    """Build a contributor result."""
    data: dict[str, object] = {
        "contributors": contributors,
        "pages_fetched": 1,
        "total_pages": 1,
    }
    data.update(overrides)
    return ContributorResult.model_validate(data)


def make_report(
    repo: GitHubRepo | None = None,
    contributors: ContributorResult | None = None,
    activity_weeks: list[GitHubCommitActivityWeek] | None = None,
) -> AnalysisReport:
    """Build an analysis report from test data."""
    return analyze(
        repo if repo is not None else make_repo(),
        contributors if contributors is not None else make_contributors_result([]),
        activity_weeks if activity_weeks is not None else [],
        now=NOW,
    )


class FakeGitHubClient:
    """GitHubClient stand-in returning canned responses and recording calls."""

    def __init__(self) -> None:
        """Set up default successful responses for every endpoint."""
        self.calls: list[str] = []
        self.user_tokens: list[str | None] = []
        self.errors: dict[str, Exception] = {}
        self.rate_limit = RateLimitInfo(remaining=59)
        self.repo_response = GitHubResponse(data=make_repo(), rate_limit=self.rate_limit)
        self.contributors_response = GitHubResponse(
            data=make_contributors_result([make_contributor("alice", 5)]),
            rate_limit=self.rate_limit,
        )
        self.activity_response = GitHubResponse(
            data=make_weeks([1] * 52), rate_limit=self.rate_limit
        )
        self.punch_response = GitHubResponse(
            data=[PunchCardPoint(day=2, hour=10, commits=5)],
            rate_limit=self.rate_limit,
        )
        self.languages_response = GitHubResponse(data={"Python": 100}, rate_limit=self.rate_limit)
        self.commit_count_response = GitHubResponse(data=1234, rate_limit=self.rate_limit)

    def _record(self, name: str, ref: RepoRef, user_token: SecretStr | None) -> None:
        self.calls.append(f"{name}:{ref.full_name}")
        self.user_tokens.append(user_token.get_secret_value() if user_token else None)
        if name in self.errors:
            raise self.errors[name]

    async def get_repo(
        self, ref: RepoRef, *, user_token: SecretStr | None = None
    ) -> GitHubResponse[Any]:
        """Return the canned repo response."""
        self._record("repo", ref, user_token)
        return self.repo_response

    async def get_contributors(
        self, ref: RepoRef, *, user_token: SecretStr | None = None
    ) -> GitHubResponse[Any]:
        """Return the canned contributors response."""
        self._record("contributors", ref, user_token)
        return self.contributors_response

    async def get_commit_activity(
        self, ref: RepoRef, *, user_token: SecretStr | None = None
    ) -> GitHubResponse[Any]:
        """Return the canned commit activity response."""
        self._record("commit_activity", ref, user_token)
        return self.activity_response

    async def get_punch_card(
        self, ref: RepoRef, *, user_token: SecretStr | None = None
    ) -> GitHubResponse[Any]:
        """Return the canned punch card response."""
        self._record("punch_card", ref, user_token)
        return self.punch_response

    async def get_languages(
        self, ref: RepoRef, *, user_token: SecretStr | None = None
    ) -> GitHubResponse[Any]:
        """Return the canned languages response."""
        self._record("languages", ref, user_token)
        return self.languages_response

    async def get_commit_count(
        self, ref: RepoRef, *, user_token: SecretStr | None = None
    ) -> GitHubResponse[Any]:
        """Return the canned commit count response."""
        self._record("commit_count", ref, user_token)
        return self.commit_count_response

    async def get_readme(
        self, ref: RepoRef, *, user_token: SecretStr | None = None
    ) -> GitHubResponse[Any]:
        """Return an empty README response."""
        self._record("readme", ref, user_token)
        return GitHubResponse(data=None, rate_limit=self.rate_limit)
