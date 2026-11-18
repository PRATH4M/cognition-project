# Agent instructions

## Project
A FastAPI app that takes a GitHub repository (URL or `owner/repo`) and shows its metadata, contributors, commit activity and commit-frequency metrics from the GitHub REST API, plus an optional AI brief based only on data the app fetched. Public repos work without a token; private repos work with a token the user enters for that request.
Requirements and acceptance criteria: `docs/requirements.md`. Read it before planning.

## Stack
Python 3.13 + uv, FastAPI, Jinja2 + HTMX, Chart.js (vendored), httpx (async), Pydantic v2, pydantic-settings, OpenRouter (OpenAI-compatible API via httpx). Tests: pytest, pytest-asyncio, respx. Quality: ruff, mypy (strict). Docker Compose.

## Commands
- Sync: `uv sync`
- Test: `uv run pytest -q`
- Lint and format: `uv run ruff check . --fix` and `uv run ruff format .`
- Types: `uv run mypy app`
- Run the app: `uv run uvicorn app.main:app --reload`

## Approval required (ask every time)
- Git: only `git status`, `git diff` and `git log` without asking. Never add, commit, push, pull, merge, rebase, reset, checkout or switch unless the user explicitly asks in the current message.
- Paid API calls: never run anything that can call a paid API (OpenRouter or any other LLM key) without explicit consent in the current message. This includes scripts, tests, and clicking "Generate AI brief" or calling `/brief` or `/api/brief` in a running app. Never put keys in commands or code.
- Free runs need no approval: mocked tests, lint, type checks, running the app or Docker, and GitHub API calls.
- Dependencies: ask before `uv add` or `uv remove`. Never use pip.
- Tests: before writing or changing tests, use `/test-plan` and wait for approval.

## Decisions
- Ask before any decision that changes requirements, scope, dependencies, endpoints or architecture.
- Record each approved decision in `docs/decisions.md` (date | decision | reason).
- Implementation details that follow these rules need no approval.

## Architecture
- `main.py`: routes and error handlers only.
- `service.py`: analysis store → repo-name cache → GitHub → analyzer.
- `github_client.py`: the only module that calls GitHub.
- `llm.py`: the only module that calls the LLM.
- `analyzer.py`: pure functions, no I/O; `now` is passed in.
- `config.py`: all settings from env; no `os.getenv` elsewhere.
- `models.py`: Pydantic schemas and `RepoRef.parse`.
- `errors.py`: typed exceptions.
- `cache.py`: in-memory analysis store and repo-name cache.

## Data and security
- Code computes every number; the LLM only describes them and names the fields it used.
- Every page works with no GitHub token and no LLM key, and says what is unavailable.
- Tokens are never logged, stored, cached, put in URLs or shown in errors.
- Private repo results are never cached by repo name, written to disk, logged or listed as recent, and go to the LLM only when `LLM_ZDR_ENABLED=true`.
- Never read, print or edit `.env`. Never commit secrets. Never hardcode secrets or API keys.

## Code quality and efficiency
- Each GitHub resource is fetched at most once per analysis (contributor pages count as one resource); independent calls run concurrently; the cache is checked first.
- Compute each metric in a single pass; no repeated work, no API calls inside loops.
- Small typed functions, early returns, no recursion, no `except Exception` outside the single global error handler.
- Async I/O in request paths; no blocking calls.
- No dead code, unused parameters, or abstractions with a single use.
- Comments only where the code cannot explain itself. No TODOs, development notes, decision logs or commented-out code in source files. Explain decisions in chat.
- Public functions and classes get a short Google-style docstring describing behaviour.
- Templates: autoescape on, never `|safe` on external data, chart data via `|tojson`.

## Done means
`/verify` passes, the approved tests are written and passing, and the change and any decisions are summarised in chat.
