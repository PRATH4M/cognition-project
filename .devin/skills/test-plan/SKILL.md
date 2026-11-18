---
name: test-plan
description: Create an approval-ready pytest plan before writing or changing tests
argument-hint: "[feature or change]"
allowed-tools:
  - read
  - grep
  - glob
triggers:
  - user
  - model
---

Before any test file is created or modified:

1. Read `docs/requirements.md`, `AGENTS.md`, and the relevant implementation files.
2. Produce an approval-ready test plan that maps each behavior or requirement to:
   - test file and test case name
   - mocked GitHub/OpenRouter inputs via respx or fixtures
   - expected result or error status
3. State explicitly that tests will use pytest + pytest-asyncio + respx only, with no network access and no paid LLM calls.
4. Include `tests/conftest.py` with an autouse fixture that sets `GITHUB_TOKEN` and `OPENROUTER_API_KEY` to empty strings, and build settings in tests with `Settings(_env_file=None, ...)` so `.env` is never read. Mock all GitHub and OpenRouter traffic with respx.
5. Stop and wait for explicit user approval. Do not write or change tests until approved.
6. Once approved tests are implemented, run `uv run pytest -q` and report the results.
