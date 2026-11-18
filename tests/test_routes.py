"""Tests for the HTTP routes."""

from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import FakeGitHubClient

from app.errors import RateLimitError, RepoNotFoundError
from app.models import RateLimitInfo


def test_healthz(client: TestClient) -> None:
    """The health endpoint returns ok."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_renders(client: TestClient) -> None:
    """The index page shows the repo input form."""
    response = client.get("/")
    assert response.status_code == 200
    assert 'name="repo"' in response.text
    assert 'type="password"' in response.text


def test_api_analyze_success(client: TestClient) -> None:
    """The JSON endpoint returns the analysis payload."""
    response = client.post("/api/analyze", json={"repo": "octo/repo"})
    assert response.status_code == 200
    body = response.json()
    assert body["analysis_id"]
    assert body["cached"] is False
    assert body["report"]["metadata"]["full_name"] == "octo/repo"
    assert body["rate_limit"]["remaining"] == 59


def test_api_analyze_invalid_repo(client: TestClient) -> None:
    """Invalid input returns 400 with a detail message."""
    response = client.post("/api/analyze", json={"repo": "not a repo"})
    assert response.status_code == 400
    assert "owner/name" in response.json()["detail"]


def test_api_analyze_not_found(client: TestClient, fake_client: FakeGitHubClient) -> None:
    """A missing repo returns 404."""
    fake_client.errors["repo"] = RepoNotFoundError("not found")
    response = client.post("/api/analyze", json={"repo": "octo/missing"})
    assert response.status_code == 404
    assert response.json()["detail"] == "not found"


def test_api_analyze_rate_limited(client: TestClient, fake_client: FakeGitHubClient) -> None:
    """Rate limiting returns 429."""
    fake_client.errors["repo"] = RateLimitError("slow down", rate_limit=RateLimitInfo(remaining=0))
    response = client.post("/api/analyze", json={"repo": "octo/repo"})
    assert response.status_code == 429


def test_analyze_form_post_full_page(client: TestClient) -> None:
    """A normal form post renders the full report page."""
    response = client.post("/analyze", data={"repo": "octo/repo", "token": ""})
    assert response.status_code == 200
    assert "octo/repo" in response.text
    assert "<html" in response.text


def test_analyze_form_post_htmx_partial(client: TestClient) -> None:
    """An HTMX post renders only the report partial."""
    response = client.post(
        "/analyze",
        data={"repo": "octo/repo", "token": ""},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "octo/repo" in response.text
    assert "<html" not in response.text


def test_analyze_form_bad_repo_shows_error(client: TestClient) -> None:
    """A bad repo in the form shows the error message."""
    response = client.post("/analyze", data={"repo": "bogus!!", "token": ""})
    assert response.status_code == 400
    assert "owner/name" in response.text


def test_unexpected_error_returns_plain_500(
    client: TestClient, fake_client: FakeGitHubClient
) -> None:
    """Unexpected errors produce a plain 500 with no stack trace."""
    fake_client.errors["repo"] = RuntimeError("boom-details")
    response = client.post("/api/analyze", json={"repo": "octo/repo"})
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "boom-details" not in response.text

    response = client.post("/analyze", data={"repo": "octo/other", "token": ""})
    assert response.status_code == 500
    assert "boom-details" not in response.text


def test_validation_error_never_echoes_token(client: TestClient) -> None:
    """A body missing repo returns 400 without echoing the token."""
    value = "super-secret-token"
    response = client.post("/api/analyze", json={"token": value})
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid request"
    assert value not in response.text


def test_token_never_in_response(client: TestClient) -> None:
    """The supplied token is not echoed in any response."""
    value = "super-secret-token"
    api_response = client.post("/api/analyze", json={"repo": "octo/repo", "token": value})
    assert api_response.status_code == 200
    assert value not in api_response.text

    form_response = client.post("/analyze", data={"repo": "octo/repo", "token": value})
    assert form_response.status_code == 200
    assert value not in form_response.text
