"""Pydantic schemas shared by the analyzer."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RepoRef(BaseModel):
    """A normalized GitHub repository reference."""

    model_config = ConfigDict(frozen=True)

    owner: str
    name: str

    @property
    def full_name(self) -> str:
        """Return the canonical ``owner/name`` identifier."""
        return f"{self.owner}/{self.name}"


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
