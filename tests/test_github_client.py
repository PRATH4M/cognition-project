"""GitHub client tests using respx mocks only."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.errors import (
    AccessDeniedError,
    GitHubUnavailableError,
    InvalidTokenError,
    RateLimitError,
    RepoNotFoundError,
    SectionUnavailableError,
)
from app.models import RepoRef

BASE = "https://api.github.com"
OWNER = "octo"
NAME = "repo"


def api(path: str) -> str:
    """Return an absolute GitHub API URL."""
    return f"{BASE}{path}"


def repo_api(suffix: str = "") -> str:
    """Return the repository endpoint URL."""
    return api(f"/repos/{OWNER}/{NAME}{suffix}")


def repo_payload(full_name: str = "octo/repo") -> dict[str, Any]:
    """Return a minimal valid repository payload."""
    return {
        "name": full_name.split("/")[-1],
        "full_name": full_name,
        "html_url": f"https://github.com/{full_name}",
        "description": "demo",
        "stargazers_count": 10,
        "forks_count": 2,
        "watchers_count": 3,
        "open_issues_count": 4,
        "language": "Python",
        "license": {"spdx_id": "MIT", "name": "MIT"},
        "topics": ["demo"],
        "created_at": "2024-01-01T00:00:00Z",
        "pushed_at": "2024-01-02T00:00:00Z",
        "archived": False,
        "private": False,
    }


def contributor(login: str, contributions: int = 1) -> dict[str, Any]:
    """Return a minimal valid contributor payload."""
    return {
        "login": login,
        "id": 1,
        "avatar_url": "https://example.com/a.png",
        "html_url": f"https://github.com/{login}",
        "contributions": contributions,
        "type": "User",
    }


def reset_epoch(delta: timedelta = timedelta(hours=1)) -> int:
    """Return a reset timestamp relative to now."""
    return int((datetime.now(UTC) + delta).timestamp())


@respx.mock
async def test_get_repo_sends_headers_and_parses(
    repo_ref: RepoRef, user_token: SecretStr, client_factory: Any
) -> None:
    """Repo requests send required headers and parse metadata/rate limits."""
    client = client_factory()
    route = respx.get(repo_api()).respond(
        200,
        json=repo_payload(),
        headers={"x-ratelimit-remaining": "4999", "x-ratelimit-reset": str(reset_epoch())},
    )
    result = await client.get_repo(repo_ref, user_token=user_token)
    assert result.data.full_name == "octo/repo"
    assert result.rate_limit.remaining == 4999
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer user-token"
    assert request.headers["x-github-api-version"] == "2026-03-10"
    assert request.headers["accept"] == "application/vnd.github+json"


@respx.mock
async def test_get_repo_follows_redirect(repo_ref: RepoRef, client_factory: Any) -> None:
    """A renamed repo redirect is followed to the new canonical repo."""
    client = client_factory()
    old_url = repo_api()
    new_url = api("/repos/newowner/newrepo")
    first = respx.get(old_url).respond(301, headers={"Location": new_url})
    second = respx.get(new_url).respond(200, json=repo_payload("newowner/newrepo"))
    result = await client.get_repo(repo_ref)
    assert result.data.full_name == "newowner/newrepo"
    assert first.called and second.called


@respx.mock
async def test_contributors_without_token_fetches_page1_only(
    repo_ref: RepoRef, client_factory: Any
) -> None:
    """Anonymous contributor access loads page 1 and asks for a token."""
    client = client_factory()
    link = (
        f'<{repo_api("/contributors")}?per_page=100&page=2>; rel="next", '
        f'<{repo_api("/contributors")}?per_page=100&page=3>; rel="last"'
    )
    route = respx.get(repo_api("/contributors")).respond(
        200, json=[contributor("a")], headers={"Link": link}
    )
    result = await client.get_contributors(repo_ref)
    assert len(route.calls) == 1
    assert result.data.needs_token is True
    assert result.data.total_pages == 3
    assert result.data.pages_fetched == 1


@respx.mock
async def test_contributors_with_token_fetches_remaining_pages(
    repo_ref: RepoRef, user_token: SecretStr, client_factory: Any
) -> None:
    """Token-authenticated contributor access fetches pages through rel=last."""
    client = client_factory()
    link = f'<{repo_api("/contributors")}?per_page=100&page=3>; rel="last"'
    respx.get(repo_api("/contributors")).mock(
        side_effect=lambda request: httpx.Response(
            200,
            json=[contributor(f"u{request.url.params['page']}")],
            headers={"Link": link},
        )
    )
    result = await client.get_contributors(repo_ref, user_token=user_token)
    assert result.data.pages_fetched == 3
    assert result.data.total_pages == 3
    assert result.data.truncated is False
    assert {item.login for item in result.data.contributors} == {"u1", "u2", "u3"}


@respx.mock
async def test_contributors_with_token_caps_at_five_pages(
    repo_ref: RepoRef, user_token: SecretStr, client_factory: Any
) -> None:
    """Contributor pagination never exceeds five pages."""
    client = client_factory()
    link = f'<{repo_api("/contributors")}?per_page=100&page=8>; rel="last"'
    route = respx.get(repo_api("/contributors")).mock(
        side_effect=lambda request: httpx.Response(
            200,
            json=[contributor(f"u{request.url.params['page']}")],
            headers={"Link": link},
        )
    )
    result = await client.get_contributors(repo_ref, user_token=user_token)
    assert len(route.calls) == 5
    assert result.data.pages_fetched == 5
    assert result.data.total_pages == 8
    assert result.data.truncated is True


@respx.mock
async def test_contributors_with_server_token_fetches_remaining_pages(
    repo_ref: RepoRef, client_factory: Any
) -> None:
    """A server token paginates contributors even without a user token."""
    client = client_factory(server_token=SecretStr("server-token"))
    link = f'<{repo_api("/contributors")}?per_page=100&page=3>; rel="last"'
    route = respx.get(repo_api("/contributors")).mock(
        side_effect=lambda request: httpx.Response(
            200,
            json=[contributor(f"s{request.url.params['page']}")],
            headers={"Link": link},
        )
    )
    result = await client.get_contributors(repo_ref)
    assert len(route.calls) == 3
    assert result.data.pages_fetched == 3
    assert result.data.total_pages == 3
    assert result.data.truncated is False
    assert {item.login for item in result.data.contributors} == {"s1", "s2", "s3"}


@respx.mock
async def test_server_token_sends_authorization_and_uses_shared_gate(
    repo_ref: RepoRef, client_factory: Any
) -> None:
    """Server-token calls send Authorization and still use the shared gate."""
    client = client_factory(server_token=SecretStr("server-token"))
    repo = respx.get(repo_api()).respond(
        200,
        json=repo_payload(),
        headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset_epoch())},
    )
    languages = respx.get(repo_api("/languages")).respond(200, json={})
    await client.get_repo(repo_ref)
    assert repo.calls.last.request.headers["authorization"] == "Bearer server-token"
    with pytest.raises(RateLimitError):
        await client.get_languages(repo_ref)
    assert len(languages.calls) == 0


@respx.mock
async def test_contributors_too_large_403_is_section_unavailable(
    repo_ref: RepoRef, client_factory: Any
) -> None:
    """GitHub's too-large contributor list degrades only that section."""
    client = client_factory()
    respx.get(repo_api("/contributors")).respond(
        403,
        json={
            "message": "The list of contributors is too large to list; "
            "use the Git tree API instead."
        },
    )
    with pytest.raises(SectionUnavailableError) as exc_info:
        await client.get_contributors(repo_ref)
    assert exc_info.value.section == "contributors"


@respx.mock
async def test_contributors_204_is_empty_section(repo_ref: RepoRef, client_factory: Any) -> None:
    """A 204 contributor response is an empty section, not an error."""
    client = client_factory()
    respx.get(repo_api("/contributors")).respond(204)
    result = await client.get_contributors(repo_ref)
    assert result.data.contributors == []
    assert result.data.needs_token is False


@respx.mock
async def test_commit_activity_retries_202_with_fake_sleep(
    repo_ref: RepoRef, client_factory: Any
) -> None:
    """Stats 202 responses retry with 1s/2s/4s delays and no real waiting."""
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    client = client_factory(sleep=fake_sleep)
    route = respx.get(repo_api("/stats/commit_activity")).mock(
        side_effect=[
            httpx.Response(202),
            httpx.Response(202),
            httpx.Response(202),
            httpx.Response(
                200,
                json=[{"week": 1704067200, "total": 3, "days": [0, 0, 1, 1, 1, 0, 0]}],
            ),
        ]
    )
    result = await client.get_commit_activity(repo_ref)
    assert sleeps == [1.0, 2.0, 4.0]
    assert len(route.calls) == 4
    assert result.stats_pending is False
    assert result.data is not None and result.data[0].total == 3


@respx.mock
async def test_commit_activity_pending_after_retries(
    repo_ref: RepoRef, client_factory: Any
) -> None:
    """Stats still computing after retries returns a pending result."""
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    client = client_factory(sleep=fake_sleep)
    route = respx.get(repo_api("/stats/commit_activity")).respond(202)
    result = await client.get_commit_activity(repo_ref)
    assert sleeps == [1.0, 2.0, 4.0]
    assert len(route.calls) == 4
    assert result.stats_pending is True
    assert result.data is None


@respx.mock
async def test_punch_card_204_is_empty(repo_ref: RepoRef, client_factory: Any) -> None:
    """A 204 punch-card response is an empty section."""
    client = client_factory()
    respx.get(repo_api("/stats/punch_card")).respond(204)
    result = await client.get_punch_card(repo_ref)
    assert result.data == []
    assert result.stats_pending is False


@respx.mock
async def test_stats_rate_limit_fails_instead_of_section(
    repo_ref: RepoRef, client_factory: Any
) -> None:
    """Rate limits on stats endpoints fail the analysis, not just the section."""
    client = client_factory()
    respx.get(repo_api("/stats/commit_activity")).respond(429, headers={"retry-after": "30"})
    with pytest.raises(RateLimitError) as exc_info:
        await client.get_commit_activity(repo_ref)
    assert exc_info.value.rate_limit is not None
    assert exc_info.value.rate_limit.retry_after_seconds == 30


@respx.mock
async def test_shared_gate_blocks_until_reset(repo_ref: RepoRef, client_factory: Any) -> None:
    """The shared gate stops calls while remaining is 0 and reset is future."""
    client = client_factory()
    respx.get(repo_api()).respond(
        200,
        json=repo_payload(),
        headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset_epoch())},
    )
    languages = respx.get(repo_api("/languages")).respond(200, json={})
    await client.get_repo(repo_ref)
    with pytest.raises(RateLimitError):
        await client.get_languages(repo_ref)
    assert len(languages.calls) == 0


@respx.mock
async def test_shared_gate_allows_after_reset(repo_ref: RepoRef, client_factory: Any) -> None:
    """Once reset has passed, the shared gate lets calls through again."""
    client = client_factory()
    respx.get(repo_api()).respond(
        200,
        json=repo_payload(),
        headers={
            "x-ratelimit-remaining": "0",
            "x-ratelimit-reset": str(reset_epoch(-timedelta(hours=1))),
        },
    )
    languages = respx.get(repo_api("/languages")).respond(200, json={"Python": 10})
    await client.get_repo(repo_ref)
    result = await client.get_languages(repo_ref)
    assert result.data == {"Python": 10}
    assert len(languages.calls) == 1


@respx.mock
async def test_user_token_skips_shared_gate_and_returns_own_rate_limit(
    repo_ref: RepoRef, user_token: SecretStr, client_factory: Any
) -> None:
    """User-token requests bypass shared state but still expose their rate limit."""
    client = client_factory()
    respx.get(repo_api()).respond(
        200,
        json=repo_payload(),
        headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset_epoch())},
    )
    languages = respx.get(repo_api("/languages")).respond(
        200, json={}, headers={"x-ratelimit-remaining": "4999"}
    )
    repo = await client.get_repo(repo_ref, user_token=user_token)
    languages_result = await client.get_languages(repo_ref)
    assert repo.rate_limit.remaining == 0
    assert languages_result.rate_limit.remaining == 4999
    assert len(languages.calls) == 1


@respx.mock
async def test_repo_404_is_not_found(repo_ref: RepoRef, client_factory: Any) -> None:
    """Repo 404 maps to not found/private."""
    client = client_factory()
    respx.get(repo_api()).respond(404, json={"message": "Not Found"})
    with pytest.raises(RepoNotFoundError):
        await client.get_repo(repo_ref)


@respx.mock
async def test_repo_401_is_invalid_token(
    repo_ref: RepoRef, user_token: SecretStr, client_factory: Any
) -> None:
    """Repo 401 maps to invalid token without exposing the token."""
    client = client_factory()
    respx.get(repo_api()).respond(401, json={"message": "Bad credentials"})
    with pytest.raises(InvalidTokenError) as exc_info:
        await client.get_repo(repo_ref, user_token=user_token)
    assert "user-token" not in str(exc_info.value)


@respx.mock
async def test_repo_403_permissions_is_access_denied(
    repo_ref: RepoRef, client_factory: Any
) -> None:
    """A permissions 403 with requests left is access denied, not rate limited."""
    client = client_factory()
    respx.get(repo_api()).respond(
        403,
        json={"message": "Forbidden"},
        headers={"x-ratelimit-remaining": "100"},
    )
    with pytest.raises(AccessDeniedError):
        await client.get_repo(repo_ref)


@respx.mock
async def test_rate_limit_remaining_zero_reset(repo_ref: RepoRef, client_factory: Any) -> None:
    """Remaining 0 exposes the reset time on the rate-limit error."""
    client = client_factory()
    respx.get(repo_api()).respond(
        403,
        json={"message": "API rate limit exceeded"},
        headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset_epoch())},
    )
    with pytest.raises(RateLimitError) as exc_info:
        await client.get_repo(repo_ref)
    assert exc_info.value.rate_limit is not None
    assert exc_info.value.rate_limit.reset_at is not None


@respx.mock
async def test_rate_limit_retry_after(repo_ref: RepoRef, client_factory: Any) -> None:
    """Retry-After supplies the wait for rate-limit errors."""
    client = client_factory()
    respx.get(repo_api()).respond(429, headers={"retry-after": "45"})
    with pytest.raises(RateLimitError) as exc_info:
        await client.get_repo(repo_ref)
    assert exc_info.value.rate_limit is not None
    assert exc_info.value.rate_limit.retry_after_seconds == 45


@respx.mock
async def test_rate_limit_message_only_defaults_60(repo_ref: RepoRef, client_factory: Any) -> None:
    """A rate-limit message without headers defaults the wait to 60 seconds."""
    client = client_factory()
    respx.get(repo_api()).respond(403, json={"message": "API rate limit exceeded"})
    with pytest.raises(RateLimitError) as exc_info:
        await client.get_repo(repo_ref)
    assert exc_info.value.rate_limit is not None
    assert exc_info.value.rate_limit.retry_after_seconds == 60


@respx.mock
async def test_contributors_rate_limit_fails_whole(repo_ref: RepoRef, client_factory: Any) -> None:
    """Rate limits on contributors fail the analysis rather than degrade."""
    client = client_factory()
    respx.get(repo_api("/contributors")).respond(429, headers={"retry-after": "10"})
    with pytest.raises(RateLimitError):
        await client.get_contributors(repo_ref)


@respx.mock
async def test_repo_500_is_github_unavailable(repo_ref: RepoRef, client_factory: Any) -> None:
    """Repo 5xx maps to GitHub unavailable."""
    client = client_factory()
    respx.get(repo_api()).respond(500, json={"message": "boom"})
    with pytest.raises(GitHubUnavailableError):
        await client.get_repo(repo_ref)


@respx.mock
async def test_repo_network_error_is_github_unavailable(
    repo_ref: RepoRef, client_factory: Any
) -> None:
    """Network failures map to GitHub unavailable."""
    client = client_factory()
    respx.get(repo_api()).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(GitHubUnavailableError):
        await client.get_repo(repo_ref)


@respx.mock
async def test_non_repo_500_is_section_unavailable(repo_ref: RepoRef, client_factory: Any) -> None:
    """Non-repo endpoint failures degrade only that section."""
    client = client_factory()
    respx.get(repo_api("/languages")).respond(500, json={"message": "boom"})
    with pytest.raises(SectionUnavailableError) as exc_info:
        await client.get_languages(repo_ref)
    assert exc_info.value.section == "languages"


@respx.mock
async def test_readme_200_returns_decoded_text(repo_ref: RepoRef, client_factory: Any) -> None:
    """README raw responses return text."""
    client = client_factory()
    route = respx.get(repo_api("/readme")).respond(200, text="# Hello")
    result = await client.get_readme(repo_ref)
    assert result.data == "# Hello"
    assert route.calls.last.request.headers["accept"] == "application/vnd.github.raw"


@respx.mock
async def test_readme_404_returns_none(repo_ref: RepoRef, client_factory: Any) -> None:
    """Missing README is not an error."""
    client = client_factory()
    respx.get(repo_api("/readme")).respond(404, json={"message": "Not Found"})
    result = await client.get_readme(repo_ref)
    assert result.data is None


@respx.mock
async def test_languages_returns_byte_dict(repo_ref: RepoRef, client_factory: Any) -> None:
    """Languages endpoint returns a byte-count mapping."""
    client = client_factory()
    respx.get(repo_api("/languages")).respond(200, json={"Python": 1000, "Shell": 50})
    result = await client.get_languages(repo_ref)
    assert result.data == {"Python": 1000, "Shell": 50}


@respx.mock
async def test_max_six_concurrent_requests(repo_ref: RepoRef, client_factory: Any) -> None:
    """The client never has more than six GitHub requests in flight."""
    active = 0
    max_active = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(200, json={})

    respx.get(repo_api("/languages")).mock(side_effect=handler)
    client = client_factory()
    await asyncio.gather(*(client.get_languages(repo_ref) for _ in range(10)))
    assert max_active <= 6
