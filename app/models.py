"""Pydantic schemas shared by the analyzer."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.errors import InvalidRepoInputError

_INVALID_REPO_MESSAGE = "Enter a repo like owner/name or a github.com link"
_GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})
_OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
_REPO_RE = re.compile(r"[A-Za-z0-9._](?:[A-Za-z0-9._-]{0,99})")


class RepoRef(BaseModel):
    """A normalized GitHub repository reference."""

    model_config = ConfigDict(frozen=True)

    owner: str
    name: str

    @property
    def full_name(self) -> str:
        """Return the canonical ``owner/name`` identifier."""
        return f"{self.owner}/{self.name}"

    @classmethod
    def parse(cls, raw: str) -> RepoRef:
        """Normalize user input to ``owner/repo`` or raise ``InvalidRepoInputError``."""
        text = raw.strip()
        if not text:
            raise InvalidRepoInputError(_INVALID_REPO_MESSAGE)
        if "://" in text:
            scheme, _, rest = text.partition("://")
            if scheme.lower() not in {"http", "https"}:
                raise InvalidRepoInputError(_INVALID_REPO_MESSAGE)
            text = rest
        text = re.split(r"[?#]", text, maxsplit=1)[0]
        segments = [seg for seg in text.split("/") if seg]
        if segments and ("." in segments[0] or segments[0].lower() in _GITHUB_HOSTS):
            if segments[0].lower() not in _GITHUB_HOSTS:
                raise InvalidRepoInputError(_INVALID_REPO_MESSAGE)
            segments = segments[1:]
        if len(segments) < 2:
            raise InvalidRepoInputError(_INVALID_REPO_MESSAGE)
        owner, repo = segments[0], segments[1]
        if repo.endswith(".git"):
            repo = repo[: -len(".git")]
        if (
            _OWNER_RE.fullmatch(owner) is None
            or _REPO_RE.fullmatch(repo) is None
            or repo in {".", ".."}
        ):
            raise InvalidRepoInputError(_INVALID_REPO_MESSAGE)
        return cls(owner=owner, name=repo)


class RateLimitInfo(BaseModel):
    """Rate-limit details parsed from GitHub response headers."""

    model_config = ConfigDict(frozen=True)

    remaining: int | None = None
    reset_at: datetime | None = None
    retry_after_seconds: float | None = None


class GitHubResponse[T](BaseModel):
    """A typed GitHub payload plus response metadata."""

    data: T
    rate_limit: RateLimitInfo
    stats_pending: bool = False


class GitHubLicense(BaseModel):
    """License metadata returned by GitHub."""

    model_config = ConfigDict(extra="ignore")

    spdx_id: str | None = None
    name: str | None = None


class GitHubRepo(BaseModel):
    """Repository metadata returned by GitHub."""

    model_config = ConfigDict(extra="ignore")

    name: str
    full_name: str
    html_url: str
    description: str | None = None
    stargazers_count: int = 0
    forks_count: int = 0
    watchers_count: int = 0
    subscribers_count: int | None = None
    open_issues_count: int = 0
    language: str | None = None
    license: GitHubLicense | None = None
    topics: list[str] = Field(default_factory=list)
    created_at: datetime
    pushed_at: datetime | None = None
    archived: bool = False
    private: bool = False
    default_branch: str | None = None


class GitHubContributor(BaseModel):
    """A contributor returned by GitHub."""

    model_config = ConfigDict(extra="ignore")

    login: str | None = None
    id: int | None = None
    avatar_url: str | None = None
    html_url: str | None = None
    contributions: int = 0
    type: str | None = None


class ContributorResult(BaseModel):
    """Contributor page results and pagination state."""

    model_config = ConfigDict(frozen=True)

    contributors: list[GitHubContributor]
    pages_fetched: int = 0
    total_pages: int | None = None
    needs_token: bool = False
    truncated: bool = False


class GitHubCommitActivityWeek(BaseModel):
    """One week of commit activity returned by GitHub."""

    model_config = ConfigDict(extra="ignore")

    week: int
    total: int = 0
    days: list[int] = Field(default_factory=list)


class PunchCardPoint(BaseModel):
    """Commit count for one weekday/hour bucket."""

    model_config = ConfigDict(frozen=True)

    day: int = Field(ge=0, le=6)
    hour: int = Field(ge=0, le=23)
    commits: int = Field(ge=0)


MaintenanceStatus = Literal["active", "slowing", "dormant", "archived", "unknown"]


class RepoMetadata(BaseModel):
    """Repository metadata prepared for display."""

    name: str
    full_name: str
    url: str
    description: str | None = None
    stars: int = 0
    forks: int = 0
    watchers: int | None = None
    open_issues: int = 0
    language: str | None = None
    license: str | None = None
    topics: list[str] = Field(default_factory=list)
    created_at: datetime
    pushed_at: datetime | None = None
    archived: bool = False


class ContributorEntry(BaseModel):
    """One contributor prepared for display."""

    login: str | None = None
    avatar_url: str | None = None
    url: str | None = None
    commits: int = 0
    is_bot: bool = False


class ContributorAnalysis(BaseModel):
    """Sorted contributor list plus pagination state."""

    contributors: list[ContributorEntry] = Field(default_factory=list)
    needs_token: bool = False
    truncated: bool = False
    total_pages: int | None = None


class WeekPoint(BaseModel):
    """Total commits for one week, newest first."""

    week: int
    total: int = 0


class ActivityAnalysis(BaseModel):
    """Weekly commit activity normalized for charting."""

    weeks: list[WeekPoint] = Field(default_factory=list)
    pending: bool = False


class PunchCardMetrics(BaseModel):
    """Busiest commit times from punch-card data; day 0 is Sunday."""

    busiest_weekday: int | None = None
    busiest_hour: int | None = None


class LanguageShare(BaseModel):
    """One language's share of repository bytes."""

    name: str
    percentage: float


class RepoMetrics(BaseModel):
    """Computed commit-frequency metrics for a repository."""

    total_commits: int | None = None
    recent_12_weeks_commits: int | None = None
    previous_12_weeks_commits: int | None = None
    active_week_percentage: float | None = None
    languages: list[LanguageShare] = Field(default_factory=list)
    bus_factor_top1: float | None = None
    bus_factor_top3: float | None = None
    maintenance: MaintenanceStatus = "unknown"


class AnalysisReport(BaseModel):
    """Complete analysis result for one repository."""

    metadata: RepoMetadata
    contributors: ContributorAnalysis
    activity: ActivityAnalysis
    punch_card: PunchCardMetrics
    metrics: RepoMetrics
    unavailable_sections: list[str] = Field(default_factory=list)
    pending_sections: list[str] = Field(default_factory=list)
    generated_at: datetime


class BriefPoint(BaseModel):
    """A single brief bullet with the metric fields it cites."""

    model_config = ConfigDict(extra="forbid")

    text: str
    fields: list[str]


class Brief(BaseModel):
    """Raw brief structure returned by the LLM."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    strengths: list[BriefPoint]
    risks: list[BriefPoint]
    getting_started: list[BriefPoint]


class GeneratedBrief(BaseModel):
    """Validated brief with grounded points and a dropped-point count."""

    summary: str
    strengths: list[BriefPoint]
    risks: list[BriefPoint]
    getting_started: list[BriefPoint]
    dropped_points: int = 0
