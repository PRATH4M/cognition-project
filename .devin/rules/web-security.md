---
description: Security rules for routes, templates, GitHub access, and LLM calls
trigger: glob
globs: "app/**"
---

- Never log, store, cache, put in URLs, or show tokens or secrets in errors.
- Private repo results are never keyed by repo name, written to disk, logged, or listed as recent; they go to the LLM only when `LLM_ZDR_ENABLED=true`.
- Templates must keep autoescape enabled, never use `|safe` on external data, and render chart data with `|tojson`.
- GitHub tokens belong only in the `Authorization` header for the current request.
- The LLM receives only computed metrics and at most the first 8,000 README characters; never log prompts or responses.
- Never read, print, or edit `.env`; never hardcode secrets or API keys.
