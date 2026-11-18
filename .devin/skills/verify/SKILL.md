---
name: verify
description: Run project verification checks without paid API calls
allowed-tools:
  - read
  - grep
  - glob
permissions:
  allow:
    - Exec(uv sync --locked)
    - Exec(uv run pytest -q)
    - Exec(uv run ruff check .)
    - Exec(uv run ruff format --check .)
    - Exec(uv run mypy app)
    - Exec(docker compose config)
triggers:
  - user
  - model
---

Run the project verification checks and report the result:

1. `uv sync --locked`
2. `uv run pytest -q`
3. `uv run ruff check .`
4. `uv run ruff format --check .`
5. `uv run mypy app`
6. `docker compose config`

Rules:

- Never run anything that can call a paid LLM API.
- Do not modify files while verifying; report failures and let the user decide on fixes.
- If a command is unavailable or fails for environment reasons, report the exact command and error.
