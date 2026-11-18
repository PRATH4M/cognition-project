# GitHub Repo Analyzer Implementation Plan

Build the full GitHub repo analyzer with FastAPI, typed GitHub/OpenRouter clients, contributor pagination, analysis-id memory storage, public repo-name caching, Docker support, vendored frontend assets, and gated Devin rules/skills—pausing after skeleton/prereqs and after each implementation step.

## Summary

Implement the GitHub repository analyzer as a FastAPI + Jinja2/HTMX app under a flat `app/` package, with typed GitHub API access, pure analysis functions, in-memory analysis storage, public repo-name caching, graceful typed errors, optional OpenRouter-powered AI briefs, request-only private-repo tokens, JSON endpoints, Docker support, vendored frontend assets, and Devin rules/skills.

Re-read after the user's update: `AGENTS.md` and `docs/requirements.md` now reflect OpenRouter, vendored Chart.js, `RepoRef.parse`, analysis-store → repo-cache → GitHub → analyzer, contributor pagination limits, and `docs/decisions.md`. `.devin/config.json` and the `[tool.*]` sections in `pyproject.toml` already exist and must not be modified.

Approved decisions from the user:
- Include the full requirements, including AI brief and private-repo token support.
- Target OpenRouter for the LLM; do not edit `AGENTS.md` or `docs/requirements.md`.
- Use `GET /repos/{owner}/{repo}/stats/punch_card` for busiest weekday/hour instead of `/commits`; drop commit-sample partial metrics.
- Store every analysis result in memory under a random `analysis_id` for `CACHE_TTL_SECONDS`; never key it by repo name and never write it to disk.
- `/brief` and `/api/brief` take `analysis_id`, so users never resend tokens.
- Fetch README during analysis only when a brief is possible.
- Cache by repo name only when the user did not supply a request token; results fetched with the app's own `GITHUB_TOKEN` may still be cached.
- Only complete public analyses go into the repo-name cache; partial results get an `analysis_id` but are never repo-name cached.
- Use glob-triggered Devin rules and only three skills.
- Log decisions in `docs/decisions.md` as a table (`date | decision | reason`).
- Contributor pagination: page 1 runs with the core calls; with any token, read `rel="last"` and fetch remaining pages concurrently up to 5 total contributor pages; without a token, page 1 only plus a token notice.
- Rate-limit gate applies only to the shared no-user-token budget; user-token requests skip the gate and do not update shared state.
- `AnalysisStore` has TTL plus a 500-entry oldest-first eviction limit.
- Phase 1 proceeds one gated step at a time with `/test-plan` → approval → implement → `/verify` → stop for review.
- Vendor htmx `2.0.11` and Chart.js `4.6.1` from official npm packages and record version, source URL, and SHA-256 in `docs/decisions.md`.
- GitHub client timeout is 10 seconds; `GitHubClient` owns one configured `httpx.AsyncClient`.
- `GitHubClient` takes an optional server token in the constructor; methods take an optional user token. User-token calls skip shared state; server/anonymous calls use the shared gate.
- Contributor pagination uses `response.links`; `GitHubResponse` carries only `data`, `rate_limit`, and `stats_pending`.
- Contributor “too large” and all other non-repo endpoint failures use the same `SectionUnavailableError` path; `ContributorResult` has no unavailable flags.
- Punch-card parsing uses a `TypeAdapter`; no `RootModel` payload class.

## Architecture and data flow

1. `app/main.py` owns routes and exception handlers only:
   - `GET /` renders the input form and recent public analyses.
   - `POST /analyze` accepts `repo` plus optional password `token`; returns a partial for HTMX and a full page for normal form posts.
   - `POST /api/analyze` accepts JSON `{repo, token?}` and returns analysis JSON or `{"detail": ...}`.
   - `POST /brief` and `POST /api/brief` accept `analysis_id` and generate the AI brief from the stored analysis.
   - `GET /healthz` supports Docker/Compose checks.
2. `app/models.py` contains Pydantic schemas and `RepoRef.parse` for normalizing GitHub repo references.
3. `app/service.py` coordinates analysis store → repo-name cache → GitHub → analyzer:
   - Every successful or partial analysis gets a random `analysis_id` and is stored in memory for `CACHE_TTL_SECONDS`, max 500 entries.
   - Repo-name cache is checked only for public analyses where the user did not provide a per-request token. Complete results fetched with the configured `GITHUB_TOKEN` may use this cache.
   - Only complete public analyses with no pending or unavailable sections are stored by repo name and listed as recent.
   - Private results are never keyed by repo name, written to disk, logged, or listed as recent.
   - Only repo-metadata failure, rate limiting, or invalid-token failure fails the whole analysis; other endpoint failures mark only that section unavailable.
4. `app/github_client.py` is the only GitHub caller:
   - Owns one `httpx.AsyncClient` configured with `base_url`, 10s timeout, `follow_redirects=True`, default `Accept`, and `X-GitHub-Api-Version: 2026-03-10`.
   - Constructor accepts optional server token; methods accept optional `user_token`. User token wins and skips shared gate/state; otherwise server token or anonymous uses the shared budget and still returns per-response rate-limit info.
   - Core resources per analysis: repo metadata, contributors, `stats/commit_activity`, `stats/punch_card`, and languages.
   - Contributor page 1 uses `/contributors?per_page=100` without `anon=true` and runs concurrently with the other core calls.
   - With a server `GITHUB_TOKEN` or user token, the client reads `rel="last"` via `response.links` and fetches remaining pages concurrently, capped at 5 contributor pages total. Without a token, only page 1 is fetched and the UI shows "Add a GitHub token to load all contributors".
   - Contributor-list 403 “too large” and other non-repo endpoint failures raise `SectionUnavailableError`; only repo metadata failure, rate limiting, or invalid token fails the whole analysis.
   - Bus factor uses all fetched contributors with bots excluded.
   - README is fetched during analysis only when a brief is possible: `OPENROUTER_API_KEY` and `LLM_MODEL` are set, and the repo is public or `LLM_ZDR_ENABLED=true`.
   - Enforces at most 6 concurrent GitHub requests.
   - Retries only stats endpoints on `202 Accepted` with 1s/2s/4s delays, then marks that stats section pending.
5. `app/analyzer.py` contains pure functions only; `now` is passed in:
   - Metadata mapping.
   - Contributor sorting and bot marking.
   - Weekly commit activity normalization.
   - Busiest weekday/hour from punch-card data.
   - Last-12-weeks vs previous-12-weeks commits, active-week percentage, language percentages, bus factor, and maintenance status.
   - No `/commits` call and no commit-sample partial flags.
6. `app/llm.py` is the only LLM caller:
   - Calls OpenRouter chat completions through existing `httpx`; no new dependency.
   - Sends only computed metrics plus the first 8,000 README characters.
   - Uses `response_format` with `json_schema`, `provider.require_parameters=true`, and `provider.zdr=true` only for private repos.
   - System prompt states the README is untrusted data, not instructions.
   - Validates the reply with Pydantic, drops points citing unknown metric fields, and returns the dropped count.
   - Never logs prompts or responses.
7. `app/cache.py` contains:
   - `AnalysisStore`: random `analysis_id` → stored analysis/brief payload, TTL expiry, 500-entry oldest-first eviction, memory only.
   - `RepoAnalysisCache`: normalized public repo name → cached analysis reference for repeat eligible analyses, plus recent-list support.

## Planned directory structure

```text
.
├── .devin/
│   ├── config.json                    # existing; do not modify
│   ├── rules/
│   │   ├── app-python.md              # glob: **/*.py
│   │   ├── web-security.md            # glob: app/**
│   │   ├── github.md                  # glob: app/github_client.py
│   │   └── llm.md                     # glob: app/llm.py
│   └── skills/
│       ├── test-plan/SKILL.md
│       ├── verify/SKILL.md
│       └── security-review/SKILL.md
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── errors.py
│   ├── models.py
│   ├── cache.py
│   ├── analyzer.py
│   ├── github_client.py
│   ├── llm.py
│   ├── service.py
│   ├── templates/
│   │   ├── base.html
│   │   ├── index.html
│   │   └── partials/
│   │       ├── report.html
│   │       ├── brief.html
│   │       ├── error.html
│   │       └── recent.html
│   └── static/
│       ├── css/app.css
│       ├── js/app.js
│       └── vendor/
│           ├── htmx.min.js
│           └── chart.umd.min.js
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   └── test_*.py
├── docs/
│   ├── requirements.md               # updated by user; do not modify
│   ├── decisions.md
│   └── plan.md
├── .env.example
├── .gitignore
├── .dockerignore
├── .devinignore
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml                    # [tool.*] exists; do not modify
└── uv.lock
```

## Implementation steps

### Phase 0 — skeleton and prerequisite files, then pause

After plan approval, first create only the directory skeleton and prerequisite files, then stop for user review before feature development:

1. Create directories for `app`, templates/partials, static/css/js/vendor, tests/fixtures, `.devin/rules`, and the three `.devin/skills` directories. Do not create `tests/__init__.py`.
2. Create package/config prerequisites:
   - `app/__init__.py`
   - `.gitignore`
   - updated `.devinignore`
   - `.env.example` with exactly `GITHUB_TOKEN`, `OPENROUTER_API_KEY`, `LLM_MODEL`, `LLM_ZDR_ENABLED`, `CACHE_TTL_SECONDS`, and `LOG_LEVEL`
   - `Dockerfile`, `.dockerignore`, and `docker-compose.yml`
   - `docs/decisions.md` with the required table header and approved decisions, including contributor pagination
   - `.devin/rules/*.md` and `.devin/skills/*/SKILL.md`
3. Do not modify `.devin/config.json`, `pyproject.toml` `[tool.*]` sections, `AGENTS.md`, or `docs/requirements.md`.
4. Run the Phase 0 checks and pause:
   - `uv run ruff check .`
   - `uv run ruff format --check .`
   - `uv run mypy app`
   - `docker compose config`
5. Wait for the user to start Phase 1.

### Phase 1 — gated implementation steps

For each step below: run `/test-plan`, wait for approval, implement only that step, run `/verify`, then stop for user review. No step starts without the user's go-ahead.

1. **GitHub client foundation** — **Status: done**
   - Implemented `config.py`, `errors.py`, GitHub payload models in `models.py`, and `github_client.py`.
   - Covered redirects, API version header, auth header, 10s timeout, owned `httpx.AsyncClient`, 6-request concurrency cap, shared rate-limit gate for no-user-token requests, stats `202` retries, contributor pagination via `response.links`, and per-section error mapping.
   - Tests use respx only and were updated for the final client API.

2. **Analyzer**
   - Add pure analysis functions and output schemas needed for metadata, contributors, weekly activity, punch-card metrics, bus factor, language breakdown, and maintenance status.
   - Tests cover analyzer edge cases with fixtures; no network.
   - Watchers come from `subscribers_count`; GitHub's `watchers_count` is just the star count.

3. **Cache, service, and routes**
   - Add `cache.py`, complete `service.py`, `main.py`, health endpoint, `/analyze`, `/api/analyze`, `/brief`, and `/api/brief`.
   - Implement `analysis_id` storage, repo-name caching rules, recent list, section degradation, and JSON/HTML error handling.
   - Tests cover cache/privacy/API behavior with mocked GitHub client responses.

4. **Templates and frontend**
   - Add autoescaped Jinja templates and static assets.
   - Vendor htmx `2.0.11` and Chart.js `4.6.1` from official npm package tarballs; record version, source URL, and SHA-256 in `docs/decisions.md`.
   - Use `|tojson` for chart data, password inputs for tokens, top-10 contributors with expandable remainder, and no CDN dependencies.

5. **LLM brief flow**
   - Add `llm.py` OpenRouter integration and brief schemas/validation.
   - Use `response_format` `json_schema`, `provider.require_parameters=true`, private-only `provider.zdr=true`, fixed timeout, untrusted-README system prompt, and no prompt/response logging.
   - Tests use mocked OpenRouter responses only; no paid calls.

6. **Docker verification**
   - Ensure the existing `Dockerfile`/`docker-compose.yml` satisfy the required image/runtime shape and `/healthz` check.
   - Run `docker compose config` and, if approved, `docker compose up --build` smoke check on port 8000 with no keys.
   - Add a README: what the app does, how to run it (local and Docker), the env settings, and known limitations.

## Files to modify/create

- Modify: `.devinignore`
- Create: `.gitignore`, `.env.example`, `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `docs/decisions.md`, `docs/plan.md`
- Create app modules/templates/static files listed above
- Create `.devin/rules/*.md` and `.devin/skills/*/SKILL.md`
- Create pytest suite under `tests/`
- Do not modify: `.devin/config.json`, `pyproject.toml` `[tool.*]` sections, `AGENTS.md`, `docs/requirements.md`

## Verification

- [x] Phase 0 skeleton/prerequisite files created, Phase 0 checks pass, then pause for user before Phase 1
- [x] Phase 1 step 1 — GitHub client foundation implemented, tests added, `/verify` passed, paused for review
- [ ] Each remaining Phase 1 step has an approved `/test-plan`, implementation, `/verify`, and user review before the next step
- [x] `uv sync --locked`
- [x] `uv run pytest -q` for Phase 1 step 1 (30 passed)
- [x] `uv run ruff check .` for Phase 1 step 1
- [x] `uv run ruff format --check .` for Phase 1 step 1
- [x] `uv run mypy app` for Phase 1 step 1
- [x] `docker compose config` for Phase 1 step 1
- [ ] Optional approved `docker compose up --build` smoke check on port 8000 with no keys
- [ ] `/security-review` before completion
- [ ] `/verify` before completion

## Risks and considerations

- Contributor pagination is capped at 5 pages even with a token; very large repos will show a truncation notice and bus factor will reflect fetched contributors only.
- Stats retries can exceed the nominal call count for stats endpoints, but they are limited to the specified 202 retry policy and do not add new endpoint types.
- Private-repo briefs rely on the in-memory `analysis_id`; if the TTL expires, the entry is evicted, or the process restarts, the user must analyze again.
- Repo-name caching is skipped for per-request user tokens and for partial results to avoid caching private, token-specific, or incomplete analyses under a repo name.
- OpenRouter model names are deployment-specific, so `LLM_MODEL` is required rather than guessing a default model.
- Vendored frontend files must come from official npm package tarballs and have version/source/SHA-256 recorded in `docs/decisions.md`.
