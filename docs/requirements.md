# Requirements

## Brief
Build a tool that takes a public GitHub repo URL and presents insights using the GitHub API.
- Input field for a GitHub repo link
- Fetch and display repo metadata (name, stars, forks, etc.)
- Display contributor and commit activity data
- Handle rate limiting and failed API calls gracefully
- Optional: more metrics, such as commit frequency

## Functional requirements
| ID | Requirement | Acceptance criteria |
|---|---|---|
| FR1 | Repo input | Accepts `https://github.com/owner/repo`, `github.com/owner/repo`, `owner/repo`, a `.git` suffix, a trailing slash and deeper paths (`/tree/...`), normalised to `owner/repo`. Anything else shows "Enter a repo like owner/name or a github.com link". |
| FR2 | Metadata | Name, description, stars, forks, watchers, open issues and PRs (GitHub counts both together), primary language, license, topics, created and last-pushed dates, archived flag. Total commits on the default branch (all time). |
| FR3 | Contributors | All contributors with GitHub accounts, sorted by commits, with avatar, login and commit count; bots marked; top 10 shown, the rest in an expandable list. Without a token, only the first 100 load, with a notice to add a token. If GitHub refuses the list (very large repos), the section says so. |
| FR4 | Commit activity | Line chart of weekly commits for the last 52 weeks. |
| FR5 | Commit-frequency metrics | Busiest weekday and hour (from GitHub's punch card); last 12 weeks vs previous 12; % of weeks with commits; language breakdown; bus factor (share of commits by the top 1 and top 3, bots excluded); maintenance status. |
| FR6 | Error handling | A clear message for invalid input, repo not found or private, invalid token, access denied, rate limited (with reset time or wait), stats still computing (rest of the report shown, plus Retry), and GitHub or network failure. No stack traces shown. |
| FR7 | Rate-limit badge | Remaining requests and reset time from the latest GitHub response. |
| FR8 | Cache and recent list | Complete public analyses made without a user token are cached in memory for `CACHE_TTL_SECONDS` (default 1 hour); a repeat analysis makes 0 GitHub calls; "Recent analyses" lists public repos only. |
| FR9 | AI brief (optional) | Generated only when the user clicks "Generate AI brief": a summary, 3 strengths, 3 risks and where to start. Each point names the metric fields it uses; points citing unknown fields are dropped and the count is shown. With no key, the panel says the brief is unavailable. |
| FR10 | Private repos (optional) | A password field for a token, used for that request only. Private results are never cached by repo name, saved, logged or listed. AI brief only when `LLM_ZDR_ENABLED=true`. |
| FR11 | JSON endpoints | `POST /api/analyze` returns the analysis as JSON; `POST /api/brief` takes an `analysis_id` and returns the brief. Errors are `{"detail": ...}` with status 400, 403, 404, 429 or 502. |
| FR12 | Docker | `docker compose up --build` from a fresh clone serves the app on port 8000 and works with no keys. |

### Maintenance status
- Archived: GitHub's `archived` flag is true.
- Dormant: no commits in the last 26 weeks.
- Slowing: commits in the last 12 weeks are under half of the previous 12.
- Active: everything else.

## Non-functional requirements
- **Rate limits:** works with no token (60 requests/hour per IP) and with a token (5,000/hour). Per analysis: 5 core calls, the README only when a brief is possible, and up to 4 extra contributor pages only when a token is used, so at most 6 calls without a token and 10 with one. No retries while rate limited. When stats are still being computed: 3 retries (1, 2, 4 s), then a partial report.
- **Efficiency:** each resource is fetched once per analysis, calls run concurrently, and metrics are computed in one pass.
- **Security:** tokens are never logged, stored, cached or put in URLs; `.env` is never committed; templates escape all external content.
- **Privacy:** prompts and responses are never logged; private data is never written to disk; the LLM receives only computed metrics and the first 8,000 README characters.
- **Cost:** paid LLM calls happen only on an explicit user click; tests and tooling never make paid calls.
- **Quality:** ruff passes (complexity ≤ 10; no `print`, TODOs or commented-out code), mypy strict passes, and the approved tests pass without network access.

## Out of scope
Cloning or reading source code, user accounts, comparing repos, chat or Q&A about a repo, history that survives restarts, GitHub Enterprise.
