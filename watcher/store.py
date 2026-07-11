"""Run-state persistence: which postings we've already seen.

The state is a JSON object mapping a company name to the list of posting ids seen
for it. In GitHub Actions this file is restored from / saved to the Actions cache
(it is never committed, since it reveals the private watchlist).
"""

from __future__ import annotations

import json
import os
from typing import Iterable


def load_seen(path: str) -> dict[str, list[str]]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        # Corrupt/empty state: start fresh rather than crash the run.
        return {}


def save_seen(path: str, seen: dict[str, list[str]]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(seen, fh, indent=2, sort_keys=True)


def new_postings(company_name: str, fetched: list[dict], seen: dict[str, list[str]]) -> list[dict]:
    """Return postings whose id has not been recorded for this company."""
    known = set(seen.get(company_name, []))
    return [p for p in fetched if p["id"] not in known]


def mark_seen(company_name: str, ids: Iterable[str], seen: dict[str, list[str]]) -> None:
    """Record ids as seen for a company (idempotent, order-preserving-ish)."""
    known = set(seen.get(company_name, []))
    known.update(ids)
    seen[company_name] = sorted(known)
