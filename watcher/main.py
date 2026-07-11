"""Orchestrate the pipeline: fetch -> diff -> filter -> email -> save state.

Usage:
    python -m watcher.main                 # normal run: email new relevant postings
    python -m watcher.main --dry-run       # print instead of emailing; don't save state
    python -m watcher.main --seed          # mark everything seen, don't email (first run)

Files (paths overridable via flags):
    companies.yaml   the watchlist (from the COMPANIES_YAML secret at runtime)
    keywords.yaml    include/exclude relevance terms
    seen.json        run state (restored from / saved to the Actions cache)
"""

from __future__ import annotations

import argparse
import sys

import yaml

from watcher import fetchers, notify, store
from watcher.filter import is_relevant, load_keywords


def load_companies(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    companies = data.get("companies") or []
    if not companies:
        raise SystemExit(f"No companies found in {path}.")
    return companies


def run(args: argparse.Namespace) -> int:
    companies = load_companies(args.companies)
    keywords = load_keywords(args.keywords)
    seen = store.load_seen(args.seen)

    matches: list[dict] = []
    errors: list[str] = []

    for company in companies:
        name = company.get("name", "?")
        try:
            fetched = fetchers.fetch_company(company)
        except fetchers.FetchError as exc:
            errors.append(str(exc))
            print(f"  ! {exc}", file=sys.stderr)
            continue

        fresh = store.new_postings(name, fetched, seen)
        print(f"  {name}: {len(fetched)} postings, {len(fresh)} new")

        if not args.seed:
            for posting in fresh:
                relevant, reasons = is_relevant(posting, keywords)
                if relevant:
                    matches.append({**posting, "company": name, "reasons": reasons})

        # Mark every posting we saw as seen, so nothing is re-emailed next run.
        store.mark_seen(name, (p["id"] for p in fetched), seen)

    if args.seed:
        print("Seed run: state primed, no email sent.")
    else:
        notify.send_digest(matches, dry_run=args.dry_run)

    if args.dry_run:
        print("Dry run: state not saved.")
    else:
        store.save_seen(args.seen, seen)

    if errors:
        print(f"\nCompleted with {len(errors)} fetch error(s).", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Watch career pages for new relevant jobs.")
    parser.add_argument("--companies", default="companies.yaml")
    parser.add_argument("--keywords", default="keywords.yaml")
    parser.add_argument("--seen", default="seen.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the digest instead of emailing; don't save state.")
    parser.add_argument("--seed", action="store_true",
                        help="Mark all current postings as seen without emailing (first run).")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
