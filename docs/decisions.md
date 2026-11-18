# Decisions

| Date | Decision | Reason |
|---|---|---|
| 2026-11-18 | Use OpenRouter's OpenAI-compatible chat API through `httpx` for the optional AI brief. | Approved provider; no new SDK dependency is required. |
| 2026-11-18 | Use `stats/punch_card` for busiest weekday/hour metrics and drop the `/commits` endpoint. | Covers the needed time distribution in one stats call with the same 202 retry policy. |
| 2026-11-18 | Store every analysis result in memory under a random `analysis_id` for `CACHE_TTL_SECONDS`; `/brief` and `/api/brief` accept only `analysis_id`. | Lets brief generation reuse fetched data without asking for tokens again while keeping private results unlisted and unkeyed by repo name. |
| 2026-11-18 | Fetch README during analysis only when a brief is possible. | Avoids an extra GitHub call when no LLM key/model is configured or private ZDR is disabled. |
| 2026-11-18 | Cache by repo name only for complete public analyses made without a per-request user token; `GITHUB_TOKEN` analyses may cache. | Prevents private, token-specific, or partial results from being reused as public recent analyses. |
| 2026-11-18 | Fetch contributor page 1 concurrently; with any token, read `rel="last"` and fetch remaining pages concurrently up to 5 total pages; without a token, show page 1 plus a token notice. | Balances GitHub rate limits with useful contributor coverage and bus-factor accuracy. |
| 2026-11-18 | Apply the shared rate-limit gate only to requests without a user token; user-token requests skip the gate and do not update shared state. | User tokens have separate GitHub rate-limit budgets and must not affect anonymous/shared throttling. |
| 2026-11-18 | Cap `AnalysisStore` at 500 entries with oldest-first eviction in addition to TTL expiry. | Bounds memory use while preserving recent analysis IDs for briefs. |
| 2026-11-18 | Vendor htmx `2.0.11` and Chart.js `4.6.1` from official npm package tarballs; record version, source URL, and SHA-256 when vendored. | Keeps the app self-contained without CDN dependencies or floating frontend versions. |
| 2026-11-19 | Defer `/brief` and `/api/brief` to the LLM step; no stub routes. | Brief endpoints cannot work before `llm.py` exists, so they ship together in step 5. |
| 2026-11-19 | Key the repo-name cache by the lowercased GitHub `full_name`; lookups lowercase the input. | GitHub names are case-insensitive, so `Octo/Repo` and `octo/repo` must share one cache entry. |
| 2026-11-19 | Results with pending stats sections are not repo-name cached. | Only complete analyses may be reused as recent/public results. |
| 2026-11-19 | `RepoRef.parse` trims input, requires a github.com host when a host is present, and validates owner/repo character sets; deeper paths are ignored. | FR1 normalization must reject non-GitHub hosts and invalid names while accepting common URL forms. |
