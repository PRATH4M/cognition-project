"""Async GitHub REST API client used by the analyzer."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import httpx
from pydantic import SecretStr, TypeAdapter, ValidationError

from app.errors import (
    AccessDeniedError,
    GitHubStatusError,
    GitHubUnavailableError,
    InvalidTokenError,
    RateLimitError,
    RepoNotFoundError,
    SectionUnavailableError,
)
from app.models import (
    ContributorResult,
    GitHubCommitActivityWeek,
    GitHubContributor,
    GitHubRepo,
    GitHubResponse,
    PunchCardPoint,
    RateLimitInfo,
    RepoRef,
)

GITHUB_API_BASE = "https://api.github.com"
API_VERSION = "2026-03-10"
DEFAULT_TIMEOUT = 10.0
MAX_CONCURRENCY = 6
MAX_CONTRIBUTOR_PAGES = 5
STATS_RETRY_DELAYS = (1.0, 2.0, 4.0)
MESSAGE_ONLY_RATE_LIMIT_SECONDS = 60.0

_CONTRIBUTORS = TypeAdapter(list[GitHubContributor])
_COMMIT_ACTIVITY = TypeAdapter(list[GitHubCommitActivityWeek])
_LANGUAGES = TypeAdapter(dict[str, int])
_PUNCH_CARD = TypeAdapter(list[tuple[int, int, int]])


class GitHubClient:
    """Typed async client for the GitHub endpoints used by the app."""

    def __init__(
        self,
        server_token: SecretStr | None = None,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Create a client with the server token used for shared-budget calls."""
        self._client = httpx.AsyncClient(
            base_url=GITHUB_API_BASE,
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
            },
        )
        self._server_token = server_token
        self._sleep = sleep
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        self._shared_rate_limit: RateLimitInfo | None = None

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def get_repo(
        self, ref: RepoRef, *, user_token: SecretStr | None = None
    ) -> GitHubResponse[GitHubRepo]:
        """Fetch repository metadata."""
        try:
            response, rate_limit = await self._request(
                "GET", self._repo_path(ref), user_token=user_token
            )
            repo = GitHubRepo.model_validate(self._json(response))
        except GitHubStatusError as exc:
            if exc.status_code == 404:
                raise RepoNotFoundError(exc.message, rate_limit=exc.rate_limit) from exc
            if exc.status_code == 403:
                raise AccessDeniedError(exc.message, rate_limit=exc.rate_limit) from exc
            raise GitHubUnavailableError(exc.message, rate_limit=exc.rate_limit) from exc
        except ValidationError as exc:
            raise GitHubUnavailableError("GitHub returned invalid repo data") from exc
        return GitHubResponse(data=repo, rate_limit=rate_limit)

    async def get_contributors(
        self, ref: RepoRef, *, user_token: SecretStr | None = None
    ) -> GitHubResponse[ContributorResult]:
        """Fetch contributor pages according to token and pagination rules."""
        try:
            contributors, rate_limit, response = await self._contributors_page(
                ref, 1, user_token=user_token
            )
        except (GitHubStatusError, GitHubUnavailableError, ValidationError) as exc:
            raise SectionUnavailableError("contributors", str(exc)) from exc

        last_page = self._link_page(response, "last")
        next_page = self._link_page(response, "next")
        has_more = next_page is not None or (last_page is not None and last_page > 1)
        if user_token is None and self._server_token is None:
            return GitHubResponse(
                data=ContributorResult(
                    contributors=contributors,
                    pages_fetched=1,
                    total_pages=last_page,
                    needs_token=has_more,
                ),
                rate_limit=rate_limit,
            )
        return await self._remaining_contributor_pages(
            ref,
            contributors,
            rate_limit,
            last_page=last_page,
            has_more=has_more,
            user_token=user_token,
        )

    async def get_commit_activity(
        self, ref: RepoRef, *, user_token: SecretStr | None = None
    ) -> GitHubResponse[list[GitHubCommitActivityWeek] | None]:
        """Fetch weekly commit activity, retrying while GitHub computes it."""
        payload = await self._stats_payload(
            f"{self._repo_path(ref)}/stats/commit_activity",
            "commit_activity",
            user_token=user_token,
        )
        if payload.data is None:
            return GitHubResponse(data=None, rate_limit=payload.rate_limit, stats_pending=True)
        try:
            weeks = _COMMIT_ACTIVITY.validate_python(payload.data)
        except ValidationError as exc:
            raise SectionUnavailableError("commit_activity", "invalid payload") from exc
        return GitHubResponse(data=weeks, rate_limit=payload.rate_limit)

    async def get_punch_card(
        self, ref: RepoRef, *, user_token: SecretStr | None = None
    ) -> GitHubResponse[list[PunchCardPoint] | None]:
        """Fetch punch-card commit counts, retrying while GitHub computes them."""
        payload = await self._stats_payload(
            f"{self._repo_path(ref)}/stats/punch_card",
            "punch_card",
            user_token=user_token,
        )
        if payload.data is None:
            return GitHubResponse(data=None, rate_limit=payload.rate_limit, stats_pending=True)
        try:
            rows = _PUNCH_CARD.validate_python(payload.data)
        except ValidationError as exc:
            raise SectionUnavailableError("punch_card", "invalid payload") from exc
        points = [PunchCardPoint(day=day, hour=hour, commits=count) for day, hour, count in rows]
        return GitHubResponse(data=points, rate_limit=payload.rate_limit)

    async def get_languages(
        self, ref: RepoRef, *, user_token: SecretStr | None = None
    ) -> GitHubResponse[dict[str, int]]:
        """Fetch language byte counts for a repository."""
        try:
            response, rate_limit = await self._request(
                "GET", f"{self._repo_path(ref)}/languages", user_token=user_token
            )
            languages = (
                {}
                if response.status_code == 204
                else _LANGUAGES.validate_python(self._json(response))
            )
        except (GitHubStatusError, GitHubUnavailableError, ValidationError) as exc:
            raise SectionUnavailableError("languages", str(exc)) from exc
        return GitHubResponse(data=languages, rate_limit=rate_limit)

    async def get_readme(
        self, ref: RepoRef, *, user_token: SecretStr | None = None
    ) -> GitHubResponse[str | None]:
        """Fetch raw README text, returning ``None`` when absent."""
        try:
            response, rate_limit = await self._request(
                "GET",
                f"{self._repo_path(ref)}/readme",
                user_token=user_token,
                accept="application/vnd.github.raw",
            )
        except GitHubStatusError as exc:
            if exc.status_code == 404:
                return GitHubResponse(data=None, rate_limit=exc.rate_limit)
            raise SectionUnavailableError("readme", exc.message) from exc
        except GitHubUnavailableError as exc:
            raise SectionUnavailableError("readme", exc.message) from exc
        return GitHubResponse(data=response.text, rate_limit=rate_limit)

    async def _remaining_contributor_pages(
        self,
        ref: RepoRef,
        contributors: list[GitHubContributor],
        rate_limit: RateLimitInfo,
        *,
        last_page: int | None,
        has_more: bool,
        user_token: SecretStr | None,
    ) -> GitHubResponse[ContributorResult]:
        end_page = (
            min(last_page, MAX_CONTRIBUTOR_PAGES)
            if last_page is not None
            else MAX_CONTRIBUTOR_PAGES
        )
        if not has_more or end_page <= 1:
            return GitHubResponse(
                data=ContributorResult(
                    contributors=contributors,
                    pages_fetched=1,
                    total_pages=last_page,
                ),
                rate_limit=rate_limit,
            )
        try:
            results = await asyncio.gather(
                *(
                    self._contributors_page(ref, page, user_token=user_token)
                    for page in range(2, end_page + 1)
                )
            )
        except (GitHubStatusError, GitHubUnavailableError, ValidationError) as exc:
            raise SectionUnavailableError("contributors", str(exc)) from exc
        for page_contributors, page_rate_limit, _response in results:
            contributors.extend(page_contributors)
            rate_limit = page_rate_limit
        return GitHubResponse(
            data=ContributorResult(
                contributors=contributors,
                pages_fetched=end_page,
                total_pages=last_page,
                truncated=has_more and (last_page is None or last_page > MAX_CONTRIBUTOR_PAGES),
            ),
            rate_limit=rate_limit,
        )

    async def _stats_payload(
        self,
        path: str,
        section: str,
        *,
        user_token: SecretStr | None,
    ) -> GitHubResponse[object | None]:
        attempt = 0
        while True:
            try:
                response, rate_limit = await self._request("GET", path, user_token=user_token)
            except (GitHubStatusError, GitHubUnavailableError) as exc:
                raise SectionUnavailableError(section, str(exc)) from exc
            if response.status_code == 202:
                if attempt == len(STATS_RETRY_DELAYS):
                    return GitHubResponse(data=None, rate_limit=rate_limit, stats_pending=True)
                await self._sleep(STATS_RETRY_DELAYS[attempt])
                attempt += 1
                continue
            if response.status_code == 204:
                return GitHubResponse(data=[], rate_limit=rate_limit)
            try:
                payload = self._json(response)
            except GitHubUnavailableError as exc:
                raise SectionUnavailableError(section, exc.message) from exc
            return GitHubResponse(data=payload, rate_limit=rate_limit)

    async def _contributors_page(
        self,
        ref: RepoRef,
        page: int,
        *,
        user_token: SecretStr | None,
    ) -> tuple[list[GitHubContributor], RateLimitInfo, httpx.Response]:
        response, rate_limit = await self._request(
            "GET",
            f"{self._repo_path(ref)}/contributors",
            user_token=user_token,
            params={"per_page": 100, "page": page},
        )
        if response.status_code == 204:
            return [], rate_limit, response
        contributors = _CONTRIBUTORS.validate_python(self._json(response))
        return contributors, rate_limit, response

    async def _request(
        self,
        method: str,
        path: str,
        *,
        user_token: SecretStr | None,
        params: dict[str, int | str] | None = None,
        accept: str | None = None,
    ) -> tuple[httpx.Response, RateLimitInfo]:
        shared_budget = user_token is None
        if shared_budget:
            self._check_shared_gate()
        token = user_token if user_token is not None else self._server_token
        async with self._semaphore:
            try:
                response = await self._client.request(
                    method,
                    path,
                    headers=self._headers(token, accept),
                    params=params,
                )
            except httpx.HTTPError as exc:
                raise GitHubUnavailableError("GitHub request failed") from exc
        rate_limit = self._parse_rate_limit(response)
        if shared_budget:
            self._shared_rate_limit = rate_limit
        if response.status_code == 401:
            raise InvalidTokenError("GitHub token was rejected", rate_limit=rate_limit)
        if self._is_rate_limit_status(response, rate_limit):
            raise self._rate_limit_error(rate_limit)
        if response.status_code >= 400:
            raise GitHubStatusError(
                response.status_code, self._error_message(response), rate_limit=rate_limit
            )
        return response, rate_limit

    def _check_shared_gate(self) -> None:
        info = self._shared_rate_limit
        if info is None or info.remaining != 0 or info.reset_at is None:
            return
        if info.reset_at > datetime.now(UTC):
            raise RateLimitError("GitHub rate limit exceeded", rate_limit=info)

    @staticmethod
    def _headers(token: SecretStr | None, accept: str | None) -> dict[str, str]:
        headers = {}
        if accept is not None:
            headers["Accept"] = accept
        if token is not None:
            headers["Authorization"] = f"Bearer {token.get_secret_value()}"
        return headers

    @staticmethod
    def _repo_path(ref: RepoRef) -> str:
        return f"/repos/{ref.owner}/{ref.name}"

    @staticmethod
    def _link_page(response: httpx.Response, rel: str) -> int | None:
        link = response.links.get(rel)
        if link is None:
            return None
        url = link.get("url") if isinstance(link, dict) else None
        if url is None:
            return None
        page = parse_qs(urlparse(url).query).get("page", [None])[0]
        return int(page) if page is not None and page.isdigit() else None

    @staticmethod
    def _parse_rate_limit(response: httpx.Response) -> RateLimitInfo:
        remaining = GitHubClient._header_int(response, "x-ratelimit-remaining")
        reset = GitHubClient._header_int(response, "x-ratelimit-reset")
        return RateLimitInfo(
            remaining=remaining,
            reset_at=datetime.fromtimestamp(reset, UTC) if reset is not None else None,
            retry_after_seconds=GitHubClient._header_float(response, "retry-after"),
        )

    @staticmethod
    def _header_int(response: httpx.Response, name: str) -> int | None:
        value = response.headers.get(name)
        return int(value) if value is not None and value.isdigit() else None

    @staticmethod
    def _header_float(response: httpx.Response, name: str) -> float | None:
        value = response.headers.get(name)
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    @staticmethod
    def _is_rate_limit_status(response: httpx.Response, rate_limit: RateLimitInfo) -> bool:
        if response.status_code == 429:
            return True
        return response.status_code == 403 and GitHubClient._is_rate_limit_response(
            response, rate_limit
        )

    @staticmethod
    def _is_rate_limit_response(response: httpx.Response, rate_limit: RateLimitInfo) -> bool:
        if rate_limit.remaining == 0 or response.headers.get("retry-after") is not None:
            return True
        lowered = response.text[:2000].lower()
        return "rate limit" in lowered or "abuse" in lowered or "secondary rate" in lowered

    @staticmethod
    def _rate_limit_error(rate_limit: RateLimitInfo) -> RateLimitError:
        info = rate_limit
        if info.retry_after_seconds is None and info.reset_at is None:
            info = info.model_copy(update={"retry_after_seconds": MESSAGE_ONLY_RATE_LIMIT_SECONDS})
        return RateLimitError("GitHub rate limit exceeded", rate_limit=info)

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except json.JSONDecodeError:
            return response.text[:200]
        if isinstance(payload, dict):
            message = payload.get("message")
            if isinstance(message, str):
                return message
        return response.text[:200]

    @staticmethod
    def _json(response: httpx.Response) -> object:
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise GitHubUnavailableError("GitHub returned invalid JSON") from exc
