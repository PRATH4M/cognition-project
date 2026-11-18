"""Tests for the pure analyzer functions."""

from __future__ import annotations

from datetime import UTC, datetime

from app.analyzer import (
    analyze,
    build_activity,
    build_contributors,
    build_metrics,
    build_punch_metrics,
)
from app.models import (
    ContributorResult,
    GitHubCommitActivityWeek,
    GitHubContributor,
    GitHubLicense,
    GitHubRepo,
    PunchCardPoint,
    WeekPoint,
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


# --- metadata ---


def test_metadata_maps_all_fields() -> None:
    meta = analyze(make_repo(), make_contributors_result([]), [], now=NOW).metadata
    assert meta.name == "repo"
    assert meta.full_name == "octo/repo"
    assert meta.url == "https://github.com/octo/repo"
    assert meta.description == "A test repo"
    assert meta.stars == 10
    assert meta.forks == 3
    assert meta.watchers == 7
    assert meta.open_issues == 4
    assert meta.language == "Python"
    assert meta.license == "MIT"
    assert meta.topics == ["api", "cli"]
    assert meta.created_at == datetime(2024, 1, 1, tzinfo=UTC)
    assert meta.pushed_at == datetime(2026, 11, 1, tzinfo=UTC)
    assert meta.archived is False


def test_metadata_watchers_none_when_subscribers_missing() -> None:
    repo = make_repo(watchers_count=99, subscribers_count=None)
    meta = analyze(repo, make_contributors_result([]), [], now=NOW).metadata
    assert meta.watchers is None


def test_metadata_missing_optionals() -> None:
    repo = make_repo(
        description=None,
        language=None,
        license=None,
        topics=[],
        pushed_at=None,
        subscribers_count=None,
    )
    meta = analyze(repo, make_contributors_result([]), [], now=NOW).metadata
    assert meta.description is None
    assert meta.language is None
    assert meta.license is None
    assert meta.topics == []
    assert meta.pushed_at is None
    assert meta.watchers is None


# --- contributors ---


def test_contributors_sorted_by_commits_desc() -> None:
    result = make_contributors_result(
        [make_contributor("low", 1), make_contributor("high", 50), make_contributor("mid", 10)]
    )
    analysis = build_contributors(result)
    assert [c.login for c in analysis.contributors] == ["high", "mid", "low"]
    assert [c.commits for c in analysis.contributors] == [50, 10, 1]


def test_contributors_bots_marked() -> None:
    result = make_contributors_result(
        [make_contributor("dependabot", 5, type="Bot"), make_contributor("alice", 5)]
    )
    analysis = build_contributors(result)
    by_login = {c.login: c for c in analysis.contributors}
    assert by_login["dependabot"].is_bot is True
    assert by_login["alice"].is_bot is False


def test_contributors_anonymous_login() -> None:
    result = make_contributors_result([make_contributor(None, 3)])
    analysis = build_contributors(result)
    assert analysis.contributors[0].login is None
    assert analysis.contributors[0].is_bot is False


def test_contributors_carries_pagination_flags() -> None:
    result = make_contributors_result(
        [make_contributor()], needs_token=True, truncated=True, total_pages=7
    )
    analysis = build_contributors(result)
    assert analysis.needs_token is True
    assert analysis.truncated is True
    assert analysis.total_pages == 7


def test_contributors_empty() -> None:
    analysis = build_contributors(make_contributors_result([]))
    assert analysis.contributors == []
    assert analysis.needs_token is False


# --- weekly activity ---


def test_activity_normalizes_newest_first() -> None:
    weeks = [make_week(100, 5), make_week(300, 9), make_week(200, 7)]
    activity = build_activity(weeks, pending=False)
    assert activity.pending is False
    assert [(w.week, w.total) for w in activity.weeks] == [(300, 9), (200, 7), (100, 5)]


def test_activity_pending() -> None:
    activity = build_activity(None, pending=True)
    assert activity.weeks == []
    assert activity.pending is True


def test_activity_empty_repo() -> None:
    activity = build_activity([make_week(1, 0), make_week(2, 0)], pending=False)
    assert [w.total for w in activity.weeks] == [0, 0]


# --- punch card ---


def test_punch_card_busiest_weekday_is_sunday() -> None:
    points = [
        PunchCardPoint(day=0, hour=9, commits=10),
        PunchCardPoint(day=3, hour=9, commits=4),
        PunchCardPoint(day=0, hour=14, commits=2),
    ]
    metrics = build_punch_metrics(points)
    assert metrics.busiest_weekday == 0
    assert metrics.busiest_hour == 9


def test_punch_card_tie_breaks_lowest_day_then_hour() -> None:
    points = [
        PunchCardPoint(day=5, hour=10, commits=8),
        PunchCardPoint(day=2, hour=15, commits=8),
        PunchCardPoint(day=2, hour=9, commits=8),
    ]
    metrics = build_punch_metrics(points)
    assert metrics.busiest_weekday == 2
    assert metrics.busiest_hour == 9


def test_punch_card_no_commits() -> None:
    points = [PunchCardPoint(day=1, hour=5, commits=0)]
    metrics = build_punch_metrics(points)
    assert metrics.busiest_weekday is None
    assert metrics.busiest_hour is None
    assert build_punch_metrics([]).busiest_weekday is None
    assert build_punch_metrics(None).busiest_weekday is None


# --- derived metrics ---


def make_weeks(totals: list[int]) -> list[GitHubCommitActivityWeek]:
    """Build weeks oldest-first like GitHub returns them."""
    return [make_week(i + 1, total) for i, total in enumerate(totals)]


def test_recent_vs_previous_12_weeks() -> None:
    totals = [4] * 12 + [2] * 12
    report = analyze(make_repo(), make_contributors_result([]), make_weeks(totals), now=NOW)
    assert report.metrics.recent_12_weeks_commits == 24
    assert report.metrics.previous_12_weeks_commits == 48


def test_active_week_percentage() -> None:
    totals = [1, 0, 2, 0] + [0] * 20
    report = analyze(make_repo(), make_contributors_result([]), make_weeks(totals), now=NOW)
    assert report.metrics.active_week_percentage == 8.3


def test_language_percentages() -> None:
    report = analyze(
        make_repo(),
        make_contributors_result([]),
        [],
        languages={"Python": 7500, "JavaScript": 2500},
        now=NOW,
    )
    shares = {s.name: s.percentage for s in report.metrics.languages}
    assert shares["Python"] == 75.0
    assert shares["JavaScript"] == 25.0


def test_language_percentages_empty() -> None:
    report = analyze(make_repo(), make_contributors_result([]), [], languages={}, now=NOW)
    assert report.metrics.languages == []


def test_bus_factor_excludes_bots() -> None:
    result = make_contributors_result(
        [
            make_contributor("bot", 100, type="Bot"),
            make_contributor("alice", 50),
            make_contributor("bob", 30),
            make_contributor("carol", 20),
        ]
    )
    report = analyze(make_repo(), result, [], now=NOW)
    assert report.metrics.bus_factor_top1 == 50.0
    assert report.metrics.bus_factor_top3 == 100.0


def test_bus_factor_fewer_than_three_humans() -> None:
    result = make_contributors_result([make_contributor("alice", 70), make_contributor("bob", 30)])
    report = analyze(make_repo(), result, [], now=NOW)
    assert report.metrics.bus_factor_top1 == 70.0
    assert report.metrics.bus_factor_top3 == 100.0


def test_bus_factor_zero_human_commits() -> None:
    result = make_contributors_result(
        [make_contributor("alice", 0), make_contributor("bot", 99, type="Bot")]
    )
    report = analyze(make_repo(), result, [], now=NOW)
    assert report.metrics.bus_factor_top1 is None
    assert report.metrics.bus_factor_top3 is None


def test_maintenance_archived() -> None:
    repo = make_repo(archived=True)
    report = analyze(repo, make_contributors_result([]), make_weeks([5] * 52), now=NOW)
    assert report.metrics.maintenance == "archived"


def test_maintenance_dormant() -> None:
    totals = [3] * 26 + [0] * 26
    report = analyze(make_repo(), make_contributors_result([]), make_weeks(totals), now=NOW)
    assert report.metrics.maintenance == "dormant"


def test_maintenance_dormant_boundary() -> None:
    commit_27_weeks_back = [0] * 25 + [1] + [0] * 26
    report = analyze(
        make_repo(), make_contributors_result([]), make_weeks(commit_27_weeks_back), now=NOW
    )
    assert report.metrics.maintenance == "dormant"

    commit_26_weeks_back = [0] * 26 + [1] + [0] * 25
    report = analyze(
        make_repo(), make_contributors_result([]), make_weeks(commit_26_weeks_back), now=NOW
    )
    assert report.metrics.maintenance == "active"


def test_maintenance_slowing() -> None:
    totals = [3] * 28 + [10] * 12 + [4] * 12
    report = analyze(make_repo(), make_contributors_result([]), make_weeks(totals), now=NOW)
    assert report.metrics.maintenance == "slowing"


def test_maintenance_slowing_boundary() -> None:
    totals = [3] * 28 + [10] * 12 + [5] * 12
    report = analyze(make_repo(), make_contributors_result([]), make_weeks(totals), now=NOW)
    assert report.metrics.maintenance == "active"


def test_maintenance_unknown_when_activity_unavailable() -> None:
    report = analyze(make_repo(), make_contributors_result([]), None, now=NOW)
    assert report.metrics.maintenance == "unknown"
    assert report.metrics.recent_12_weeks_commits is None
    assert report.metrics.active_week_percentage is None


def test_maintenance_active() -> None:
    totals = [3] * 52
    report = analyze(make_repo(), make_contributors_result([]), make_weeks(totals), now=NOW)
    assert report.metrics.maintenance == "active"


# --- full report ---


def test_analyze_returns_full_report() -> None:
    repo = make_repo()
    contributors = make_contributors_result(
        [make_contributor("alice", 40), make_contributor("bot", 60, type="Bot")],
        needs_token=True,
    )
    weeks = make_weeks([2] * 52)
    punch = [PunchCardPoint(day=2, hour=14, commits=30)]
    report = analyze(
        repo,
        contributors,
        weeks,
        punch_card=punch,
        languages={"Python": 100},
        now=NOW,
    )
    assert report.generated_at == NOW
    assert report.metadata.full_name == "octo/repo"
    assert report.contributors.needs_token is True
    assert report.activity.weeks[0].week == 52
    assert report.punch_card.busiest_weekday == 2
    assert report.metrics.recent_12_weeks_commits == 24
    assert report.metrics.bus_factor_top1 == 100.0
    assert report.metrics.maintenance == "active"


def test_build_metrics_directly() -> None:
    weeks = [WeekPoint(week=i, total=1) for i in range(26)]
    metrics = build_metrics(
        make_repo(), weeks, build_contributors(make_contributors_result([])), {}
    )
    assert metrics.maintenance == "active"
    assert metrics.recent_12_weeks_commits == 12
