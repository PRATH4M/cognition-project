---
name: security-review
description: Review changes for secret leakage, private-data caching, XSS, and prompt minimization
allowed-tools:
  - read
  - grep
  - glob
permissions:
  allow:
    - Exec(git status)
    - Exec(git diff)
    - Exec(git log)
triggers:
  - user
  - model
---

Review the current changes for security and privacy issues:

1. Run `git status` and `git diff` (and `git log` if needed) to inspect the change set.
2. Check for:
   - tokens, secrets, or `.env` contents in code, logs, URLs, errors, or committed files
   - private repo results cached by repo name, written to disk, logged, or listed as recent
   - template injection/XSS risks, including missing autoescape or unsafe `|safe` usage
   - chart data not rendered through `|tojson`
   - LLM prompts containing more than computed metrics and at most 8,000 README characters
   - logged prompts, responses, tokens, or private payloads
   - paid API calls in tests or tooling
3. Report findings by severity with file and line references. Do not modify files during the review.
