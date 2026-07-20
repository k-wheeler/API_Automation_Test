# Job Posting Watcher

Checks a private list of company career pages on a schedule, finds **new** postings
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

## One-time setup

1. **Gmail app password** — create one at
   https://support.google.com/accounts/answer/185833 (needed to send the digest).
2. **Add two repo secrets** (Settings → Secrets and variables → Actions):
   - `GMAIL_APP_PASSWORD` — the app password from step 1.
   - `COMPANIES_YAML` — paste your real watchlist YAML (same shape as
     `companies.example.yaml`). Find each company's `type`/`slug` from its career URL:
     `boards.greenhouse.io/<slug>`, `jobs.lever.co/<slug>`, `jobs.ashbyhq.com/<slug>`;
     anything else → `type: html` with the full careers `url`.
3. **Seed the state** so the first run doesn't email a giant backlog:
   Actions → job-watcher → *Run workflow* → set **seed = true**.
4. Done — the daily weekday cron takes over. Trigger *Run workflow* (seed = false) any
   time to check immediately.

## Run locally (for testing / tuning)

```bash
pip install -r requirements.txt

# Make a LOCAL companies.yaml (git-ignored) with a couple of real companies, then:
python -m watcher.main --dry-run       # prints the digest; sends nothing; saves nothing
```

- `--dry-run` — print instead of emailing, don't touch state.
- `--seed` — mark everything seen without emailing.

## Notes

- **Supported platforms:** `greenhouse`, `lever`, `ashby`, `bamboohr`, `rippling`, `gusto`,
  `section` (reads items under an "Open positions" header on Webflow-style CMS pages), and
  `html` (best-effort scrape). See `companies.example.yaml` for the format of each.
- **HTML fallback is best-effort.** It only sees server-rendered markup (no JavaScript
  runs). Titles come from link text, or the URL slug when the text is generic
  ("Apply"/"View Position"). Fully JavaScript-rendered pages (e.g. Notion) won't yield jobs.
- **Workday** isn't supported in v1.
- **Cache eviction:** state lives in the Actions cache, which can evict after ~7 days of
  no runs. The daily schedule keeps it warm; if it ever evicts, one digest may repeat.
- **To upgrade filtering to AI later:** `watcher/filter.py` exposes a single
  `is_relevant(posting, keywords)` — swap its body for a model call without changing the
  rest of the pipeline.
