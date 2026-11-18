---
description: Python implementation rules for the analyzer app
trigger: glob
globs: "**/*.py"
---

- Follow `AGENTS.md` module boundaries: routes in `main.py`, orchestration in `service.py`, GitHub calls only in `github_client.py`, LLM calls only in `llm.py`, pure analysis in `analyzer.py`, env settings only in `config.py`, schemas in `models.py`, typed exceptions in `errors.py`, and memory caches in `cache.py`.
- Keep `analyzer.py` pure: no I/O, no environment reads, and pass `now` explicitly.
- Use async I/O in request paths, small typed functions, early returns, Google-style docstrings on public functions, and no `except Exception` outside the global error handler.
- Keep Ruff complexity at or below 10 and satisfy mypy strict.
- Do not use `print`, TODOs, commented-out code, or development notes in source files.
