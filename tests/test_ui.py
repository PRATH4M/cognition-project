"""Tests for the rendered UI."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from helpers import FakeGitHubClient, make_contributor, make_repo

from app.errors import RateLimitError, SectionUnavailableError
from app.models import (
    ContributorResult,
    GitHubCommitActivityWeek,
    GitHubResponse,
    PunchCardPoint,
    RateLimitInfo,
)


def test_index_has_htmx_form_and_assets(client: TestClient) -> None:
    """The index page wires HTMX, indicators, and vendored assets."""
    response = client.get("/")
    assert response.status_code == 200
    assert 'hx-post="/analyze"' in response.text
    assert 'hx-indicator="#analyzing"' in response.text
    assert "Analyzing..." in response.text
    assert "htmx.min.js" in response.text
    assert "chart.umd.min.js" in response.text
    assert "app.js" in response.text
    assert "app.css" in response.text


def test_report_shows_all_sections(client: TestClient) -> None:
    """The report page shows metadata, metrics, contributors, and badges."""
    response = client.post("/analyze", data={"repo": "octo/repo", "token": ""})
    assert response.status_code == 200
    for text in (
        "octo/repo",
        "Stars",
        "Forks",
        "Watchers",
        "Open issues",
        "PRs",
        "MIT",
        "Python",
        "Commit activity",
        "Commit frequency",
        "Contributors",
        "Maintenance",
        "All time",
        "Bus factor",
        "requests remaining",
        "Analysis ID",
    ):
        assert text in response.text


def test_report_numbers_with_commas(client: TestClient, fake_client: FakeGitHubClient) -> None:
    """Large counts render with thousands separators."""
    fake_client.repo_response = GitHubResponse(
        data=make_repo(stargazers_count=12345), rate_limit=RateLimitInfo(remaining=59)
    )
    response = client.post("/analyze", data={"repo": "octo/repo", "token": ""})
    assert "12,345" in response.text


def test_report_chart_data_oldest_first(client: TestClient, fake_client: FakeGitHubClient) -> None:
    """Chart JSON lists weeks oldest to newest for left-to-right display."""
    weeks = [GitHubCommitActivityWeek(week=1000 + i, total=i, days=[0] * 7) for i in range(52)]
    fake_client.activity_response = GitHubResponse(
        data=weeks, rate_limit=RateLimitInfo(remaining=59)
    )
    response = client.post("/analyze", data={"repo": "octo/repo", "token": ""})
    data = response.text.split('id="activity-data"', 1)[1]
    assert data.index('"week": 1000') < data.index('"week": 1051')


def test_report_top10_contributors_expandable(
    client: TestClient, fake_client: FakeGitHubClient
) -> None:
    """Only the top 10 contributors show by default; the rest are expandable."""
    contributors = [make_contributor(f"alice-{i:02d}", 100 - i) for i in range(15)]
    fake_client.contributors_response = GitHubResponse(
        data=ContributorResult(contributors=contributors, pages_fetched=1),
        rate_limit=RateLimitInfo(remaining=59),
    )
    response = client.post("/analyze", data={"repo": "octo/repo", "token": ""})
    assert "Show all 15 contributors" in response.text
    details_at = response.text.index("<details>")
    assert response.text.index("alice-09") < details_at
    assert response.text.index("alice-10") > details_at


def test_report_pending_shows_retry(client: TestClient, fake_client: FakeGitHubClient) -> None:
    """Pending stats show a notice and a retry that resubmits the form."""
    fake_client.activity_response = GitHubResponse(
        data=None, rate_limit=RateLimitInfo(remaining=59), stats_pending=True
    )
    response = client.post("/analyze", data={"repo": "octo/repo", "token": ""})
    assert "Still computing" in response.text
    assert "Commit activity" in response.text
    assert 'form="repo-form"' in response.text
    assert "Retry" in response.text


def test_report_unavailable_section_notice(
    client: TestClient, fake_client: FakeGitHubClient
) -> None:
    """A failed section is named with a readable label."""
    fake_client.errors["contributors"] = SectionUnavailableError("contributors", "boom")
    response = client.post("/analyze", data={"repo": "octo/repo", "token": ""})
    assert "Unavailable: Contributors" in response.text


def test_report_cached_badge(client: TestClient) -> None:
    """A cache hit shows the cached badge."""
    client.post("/analyze", data={"repo": "octo/repo", "token": ""})
    response = client.post("/analyze", data={"repo": "octo/repo", "token": ""})
    assert ">cached<" in response.text


def test_report_private_badge_not_recent(client: TestClient, fake_client: FakeGitHubClient) -> None:
    """Private results show a badge and never appear in recent."""
    fake_client.repo_response = GitHubResponse(
        data=make_repo(private=True, full_name="octo/secret"),
        rate_limit=RateLimitInfo(remaining=59),
    )
    response = client.post("/analyze", data={"repo": "octo/secret", "token": ""})
    assert "private" in response.text
    index = client.get("/")
    assert "octo/secret" not in index.text


def test_htmx_error_partial_still_returned(client: TestClient) -> None:
    """HTMX error responses still carry the error partial body."""
    response = client.post(
        "/analyze",
        data={"repo": "bogus!!", "token": ""},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 400
    assert "owner/name" in response.text
    assert "<html" not in response.text


def test_recent_list_on_index(client: TestClient) -> None:
    """Analyzed public repos appear in the recent list."""
    client.post("/analyze", data={"repo": "octo/repo", "token": ""})
    response = client.get("/")
    assert "octo/repo" in response.text


def test_static_assets_served(client: TestClient) -> None:
    """Vendored and app assets are served."""
    for path in (
        "/static/js/app.js",
        "/static/css/app.css",
        "/static/vendor/htmx.min.js",
        "/static/vendor/chart.umd.min.js",
    ):
        assert client.get(path).status_code == 200


def test_needs_token_notice(client: TestClient, fake_client: FakeGitHubClient) -> None:
    """More contributor pages without a token show the token notice."""
    fake_client.contributors_response = GitHubResponse(
        data=ContributorResult(
            contributors=[make_contributor()],
            pages_fetched=1,
            total_pages=3,
            needs_token=True,
        ),
        rate_limit=RateLimitInfo(remaining=59),
    )
    response = client.post("/analyze", data={"repo": "octo/repo", "token": ""})
    assert "Add a GitHub token to load all contributors" in response.text


def test_truncated_notice(client: TestClient, fake_client: FakeGitHubClient) -> None:
    """Contributor lists cut at the page cap show a truncation notice."""
    fake_client.contributors_response = GitHubResponse(
        data=ContributorResult(
            contributors=[make_contributor()],
            pages_fetched=5,
            total_pages=9,
            truncated=True,
        ),
        rate_limit=RateLimitInfo(remaining=59),
    )
    response = client.post("/analyze", data={"repo": "octo/repo", "token": ""})
    assert "truncated at 5 pages" in response.text


def test_punch_card_sunday(client: TestClient, fake_client: FakeGitHubClient) -> None:
    """Punch-card day 0 renders as Sunday."""
    fake_client.punch_response = GitHubResponse(
        data=[PunchCardPoint(day=0, hour=9, commits=10)],
        rate_limit=RateLimitInfo(remaining=59),
    )
    response = client.post("/analyze", data={"repo": "octo/repo", "token": ""})
    assert "Sundays at 09:00" in response.text
    assert "committers' local time" in response.text


def test_rate_limit_error_shows_reset(client: TestClient, fake_client: FakeGitHubClient) -> None:
    """A rate-limit error shows the reset time."""
    fake_client.errors["repo"] = RateLimitError(
        "slow down",
        rate_limit=RateLimitInfo(remaining=0, reset_at=datetime(2026, 11, 20, 3, 0, tzinfo=UTC)),
    )
    response = client.post("/analyze", data={"repo": "octo/repo", "token": ""})
    assert response.status_code == 429
    assert "resets 2026-11-20 03:00 UTC" in response.text


def test_rate_limit_badge_shows_reset(client: TestClient, fake_client: FakeGitHubClient) -> None:
    """The rate-limit badge shows remaining requests and reset time."""
    reset = RateLimitInfo(remaining=42, reset_at=datetime(2026, 11, 20, 3, 0, tzinfo=UTC))
    for name in (
        "repo_response",
        "contributors_response",
        "activity_response",
        "punch_response",
        "languages_response",
        "commit_count_response",
    ):
        getattr(fake_client, name).rate_limit = reset
    response = client.post("/analyze", data={"repo": "octo/repo", "token": ""})
    assert "42 requests remaining" in response.text
    assert "resets 2026-11-20 03:00 UTC" in response.text
