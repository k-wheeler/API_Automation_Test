"""Keyword relevance filtering (free, no AI).

A posting is relevant when its title or description matches at least one `include`
keyword and none of the `exclude` keywords. Matching is case-insensitive and
word-boundary aware, so short terms like "GIS" don't match "logistics".

The single entry point is `is_relevant(posting, keywords) -> (bool, reasons)`.
Swapping this for an AI scorer later means changing only this function.
"""

from __future__ import annotations

import re

import yaml


def load_keywords(path: str) -> dict[str, list[str]]:
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return {
        "include": [str(k) for k in (data.get("include") or [])],
        "exclude": [str(k) for k in (data.get("exclude") or [])],
    }


def _matches(text: str, term: str) -> bool:
    # \b around the whole (possibly multi-word) term; escape regex metacharacters.
    pattern = r"\b" + re.escape(term) + r"\b"
    return re.search(pattern, text, re.IGNORECASE) is not None


def is_relevant(posting: dict, keywords: dict[str, list[str]]) -> tuple[bool, list[str]]:
    """Return (relevant, matched_include_terms)."""
    haystack = f"{posting.get('title', '')}\n{posting.get('description', '')}"

    for term in keywords.get("exclude", []):
        if _matches(haystack, term):
            return False, []

    hits = [term for term in keywords.get("include", []) if _matches(haystack, term)]
    return (bool(hits), hits)
