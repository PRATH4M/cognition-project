---
description: GitHub API integration rules for github_client.py
trigger: glob
globs: "app/github_client.py"
---

- `github_client.py` is the only module that calls GitHub.
- One shared `httpx.AsyncClient`: 10-second timeout, `follow_redirects=True`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2026-03-10`, and the effective token only in `Authorization`.
- Fetch each GitHub resource at most once per analysis; independent calls run concurrently under the 6-request cap.
- Contributor page 1 runs with the core calls; with any token, read `rel="last"` and fetch remaining pages concurrently up to 5 total pages; without a token, fetch page 1 only.
- Record `x-ratelimit-limit`, `-remaining` and `-reset` from every response for the badge.
- Shared rate-limit gate (no user token only): if the last shared response showed `remaining=0` and the reset time has not passed, raise `RateLimited` without calling GitHub. User-token requests skip the gate and do not update shared state.
- A 403/429 is a rate limit only when `x-ratelimit-remaining` is `0` (→ `RateLimited(reset_at)`), `retry-after` is present (→ `RateLimited(retry_after)`), or the message mentions a rate limit (→ `RateLimited(retry_after=60)`). Every response carries rate-limit headers, so their presence alone means nothing.
- Repo metadata: 401 → `InvalidToken`, 404 → `RepoNotFound`, other 403 → `AccessDenied`, 5xx/timeout/connection error → `UpstreamError`. These and `RateLimited` fail the whole analysis.
- Other endpoints: 204 → empty section; README 404 → no README; contributor-list 403 "too large" or any other failure → that section unavailable.
- Stats endpoints: retry `202 Accepted` with 1 s/2 s/4 s delays, then mark the section pending. No other retries, and never retry while rate limited.
- Tests use respx mocks only and never access the network.
