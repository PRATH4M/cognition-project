"""Pure analysis functions; no I/O."""

from __future__ import annotations

from datetime import datetime

from app.models import (
    ActivityAnalysis,
    AnalysisReport,
    ContributorAnalysis,
    ContributorEntry,
    ContributorResult,
    GitHubCommitActivityWeek,
    GitHubRepo,
    LanguageShare,
    MaintenanceStatus,
    PunchCardMetrics,
    PunchCardPoint,
    RepoMetadata,
    RepoMetrics,
    WeekPoint,
)

RECENT_WINDOW_WEEKS = 12
COMPARISON_WINDOW_WEEKS = 12
DORMANT_WINDOW_WEEKS = 26


def analyze(
    repo: GitHubRepo,
    contributors: ContributorResult,
    activity_weeks: list[GitHubCommitActivityWeek] | None,
    *,
    activity_pending: bool = False,
    punch_card: list[PunchCardPoint] | None = None,
    languages: dict[str, int] | None = None,
    unavailable_sections: list[str] | None = None,
    pending_sections: list[str] | None = None,
    commit_count: int | None = None,
    now: datetime,
) -> AnalysisReport:
    """Build a complete analysis report from fetched GitHub data."""
    activity = build_activity(activity_weeks, pending=activity_pending)
    contributor_analysis = build_contributors(contributors)
    return AnalysisReport(
        metadata=build_metadata(repo),
        contributors=contributor_analysis,
        activity=activity,
        punch_card=build_punch_metrics(punch_card),
        metrics=build_metrics(
            repo,
            activity.weeks if activity_weeks is not None else None,
            contributor_analysis,
            languages or {},
            commit_count=commit_count,
        ),
        unavailable_sections=unavailable_sections or [],
        pending_sections=pending_sections or [],
        generated_at=now,
    )


def build_metadata(repo: GitHubRepo) -> RepoMetadata:
    """Map a GitHub repo payload to display metadata."""
    license_name = None
    if repo.license is not None:
        license_name = repo.license.spdx_id or repo.license.name
    return RepoMetadata(
        name=repo.name,
        full_name=repo.full_name,
        url=repo.html_url,
        description=repo.description,
        stars=repo.stargazers_count,
        forks=repo.forks_count,
        watchers=repo.subscribers_count,
        open_issues=repo.open_issues_count,
        language=repo.language,
        license=license_name,
        topics=repo.topics,
        created_at=repo.created_at,
        pushed_at=repo.pushed_at,
        archived=repo.archived,
    )


def build_contributors(result: ContributorResult) -> ContributorAnalysis:
    """Sort contributors by commits and flag bots."""
    ordered = sorted(result.contributors, key=lambda c: c.contributions, reverse=True)
    return ContributorAnalysis(
        contributors=[
            ContributorEntry(
                login=c.login,
                avatar_url=c.avatar_url,
                url=c.html_url,
                commits=c.contributions,
                is_bot=c.type == "Bot",
            )
            for c in ordered
        ],
        needs_token=result.needs_token,
        truncated=result.truncated,
        total_pages=result.total_pages,
    )


def build_activity(
    weeks: list[GitHubCommitActivityWeek] | None, *, pending: bool
) -> ActivityAnalysis:
    """Normalize weekly commit activity to newest-first week totals."""
    if weeks is None:
        return ActivityAnalysis(weeks=[], pending=pending)
    ordered = sorted(weeks, key=lambda w: w.week, reverse=True)
    return ActivityAnalysis(
        weeks=[WeekPoint(week=w.week, total=w.total) for w in ordered],
        pending=pending,
    )


def build_punch_metrics(points: list[PunchCardPoint] | None) -> PunchCardMetrics:
    """Find the busiest weekday (0 = Sunday) and hour from punch-card data."""
    if not points:
        return PunchCardMetrics()
    point = min(points, key=lambda p: (-p.commits, p.day, p.hour))
    if point.commits == 0:
        return PunchCardMetrics()
    return PunchCardMetrics(busiest_weekday=point.day, busiest_hour=point.hour)


def build_metrics(
    repo: GitHubRepo,
    weeks: list[WeekPoint] | None,
    contributors: ContributorAnalysis,
    languages: dict[str, int],
    commit_count: int | None = None,
) -> RepoMetrics:
    """Compute commit-frequency metrics from normalized analyzer inputs."""
    humans = [c for c in contributors.contributors if not c.is_bot]
    total_human_commits = sum(c.commits for c in humans)
    top1 = top3 = None
    if total_human_commits > 0:
        top1 = round(humans[0].commits / total_human_commits * 100, 1)
        top3 = round(sum(c.commits for c in humans[:3]) / total_human_commits * 100, 1)

    recent = previous = active_pct = None
    maintenance: MaintenanceStatus = "unknown"
    if repo.archived:
        maintenance = "archived"
    elif weeks is not None:
        totals = [w.total for w in weeks]
        recent = sum(totals[:RECENT_WINDOW_WEEKS])
        previous = sum(totals[RECENT_WINDOW_WEEKS : RECENT_WINDOW_WEEKS + COMPARISON_WINDOW_WEEKS])
        active_pct = (
            round(sum(1 for t in totals if t > 0) / len(totals) * 100, 1) if totals else 0.0
        )
        maintenance = _maintenance_status(totals, recent, previous)

    return RepoMetrics(
        total_commits=commit_count,
        recent_12_weeks_commits=recent,
        previous_12_weeks_commits=previous,
        active_week_percentage=active_pct,
        languages=_language_shares(languages),
        bus_factor_top1=top1,
        bus_factor_top3=top3,
        maintenance=maintenance,
    )


def _maintenance_status(totals: list[int], recent: int, previous: int) -> MaintenanceStatus:
    if sum(totals[:DORMANT_WINDOW_WEEKS]) == 0:
        return "dormant"
    if recent < previous / 2:
        return "slowing"
    return "active"


def _language_shares(languages: dict[str, int]) -> list[LanguageShare]:
    total_bytes = sum(languages.values())
    if total_bytes <= 0:
        return []
    ordered = sorted(languages.items(), key=lambda kv: (-kv[1], kv[0]))
    return [
        LanguageShare(name=name, percentage=round(count / total_bytes * 100, 1))
        for name, count in ordered
    ]
