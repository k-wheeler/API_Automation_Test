# Job Posting Watcher

Created with Claude Code to test its capabilities. This watcher checks a private list of company career pages on a schedule, finds **new** postings
since the last run, filters them to ones matching keywords relevant to my skillset
(ecology / geospatial / remote sensing), and emails me a digest.

- **Free.** Runs on GitHub Actions; filtering is keyword-based (no AI API, no billing).
- **Private watchlist on a public repo.** The company list and run-state never touch the
  repo — the list is a GitHub Actions secret, the state lives in the Actions cache.

## How it works

```
COMPANIES_YAML secret ─▶ companies.yaml (ephemeral, git-ignored)
   restore seen.json ◀── Actions cache
        └─▶ fetch listings ─▶ diff vs seen ─▶ keyword filter ─▶ email digest (Gmail SMTP)
                                                                     └─▶ save seen.json ─▶ cache
```

| File | Purpose |
|------|---------|
| `watcher/fetchers.py` | Pull postings from Greenhouse / Lever / Ashby / BambooHR JSON APIs, Rippling (embedded JSON), Gusto boards, or scrape an HTML page. |
| `watcher/store.py` | Load/save `seen.json`; compute which postings are new. |
| `watcher/filter.py` | Keyword relevance matching (`keywords.yaml`). |
| `watcher/notify.py` | Build + send the email digest. |
| `watcher/main.py` | Orchestrates the pipeline. |
| `keywords.yaml` | Include/exclude relevance terms (public). |
| `companies.example.yaml` | Dummy format sample (the real list is a secret). |

## Notes

- **Supported platforms:** `greenhouse`, `lever`, `ashby`, `bamboohr`, `rippling`, `pinpoint`,
  `workable`, `gusto`, `notion` (public Notion page with an inline jobs database),
  `section` (reads items under an "Open positions" header on Webflow-style CMS pages),
  `browser` (renders JavaScript-only pages with headless Chromium, then scrapes), and
  `html` (best-effort scrape). See `companies.example.yaml` for the format of each.
- **The `browser` type needs Chromium**, installed in CI by the workflow
  (`playwright install --with-deps chromium`). Locally: `python -m playwright install chromium`.
- **HTML fallback is best-effort.** It only sees server-rendered markup (no JavaScript
  runs). Titles come from link text, or the URL slug when the text is generic
  ("Apply"/"View Position"). Fully JavaScript-rendered pages (e.g. Notion) won't yield jobs.
- **Workday** isn't supported in v1.
- **Cache eviction:** state lives in the Actions cache, which can evict after ~7 days of
  no runs. The daily schedule keeps it warm; if it ever evicts, one digest may repeat.
- **To upgrade filtering to AI later:** `watcher/filter.py` exposes a single
  `is_relevant(posting, keywords)` — swap its body for a model call without changing the
  rest of the pipeline.
