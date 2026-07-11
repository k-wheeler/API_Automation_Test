"""Fetch job postings from a company's career page.

Each fetcher returns a list of normalized postings:

    {"id": str, "title": str, "location": str, "url": str, "description": str}

The ATS-specific fetchers (Greenhouse, Lever, Ashby) hit clean JSON APIs and are
reliable. The `html` fetcher is a best-effort fallback for custom career pages and
only sees link text, not full descriptions — prefer a real ATS type when possible.
"""

from __future__ import annotations

import hashlib
import re
from html import unescape
from typing import Any

import requests
from bs4 import BeautifulSoup

TIMEOUT = 20
HEADERS = {"User-Agent": "job-watcher/1.0 (+https://github.com/k-wheeler/API_Automation_Test)"}


class FetchError(Exception):
    """Raised when a company's postings could not be fetched."""


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    # ATS "content" fields are often HTML (sometimes entity-escaped twice).
    soup = BeautifulSoup(unescape(text), "html.parser")
    return re.sub(r"\s+", " ", soup.get_text(" ")).strip()


def _hash_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _get(url: str, **kwargs: Any) -> requests.Response:
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, **kwargs)
    resp.raise_for_status()
    return resp


# --- ATS-specific fetchers ---------------------------------------------------


def fetch_greenhouse(slug: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    data = _get(url).json()
    postings = []
    for job in data.get("jobs", []):
        postings.append(
            {
                "id": str(job.get("id")),
                "title": job.get("title", "").strip(),
                "location": (job.get("location") or {}).get("name", "").strip(),
                "url": job.get("absolute_url", ""),
                "description": _strip_html(job.get("content")),
            }
        )
    return postings


def fetch_lever(slug: str) -> list[dict]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    data = _get(url).json()
    postings = []
    for job in data:
        cats = job.get("categories") or {}
        postings.append(
            {
                "id": str(job.get("id")),
                "title": job.get("text", "").strip(),
                "location": (cats.get("location") or "").strip(),
                "url": job.get("hostedUrl", ""),
                "description": job.get("descriptionPlain")
                or _strip_html(job.get("description")),
            }
        )
    return postings


def fetch_ashby(slug: str) -> list[dict]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    data = _get(url).json()
    postings = []
    for job in data.get("jobs", []):
        postings.append(
            {
                "id": str(job.get("id")),
                "title": job.get("title", "").strip(),
                "location": (job.get("location") or "").strip(),
                "url": job.get("jobUrl") or job.get("applyUrl", ""),
                "description": job.get("descriptionPlain")
                or _strip_html(job.get("descriptionHtml")),
            }
        )
    return postings


def fetch_html(url: str) -> list[dict]:
    """Best-effort scrape of a custom career page.

    Emits one posting per anchor that looks like a job link. Only the link text is
    available as title/description, so keyword matching runs against titles here.
    """
    resp = _get(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    base = resp.url
    postings = []
    seen_hrefs = set()
    for a in soup.find_all("a", href=True):
        text = re.sub(r"\s+", " ", a.get_text(" ")).strip()
        href = a["href"].strip()
        if not text or len(text) < 4:
            continue
        # Heuristic: keep links that look job-related by href or by text.
        if not re.search(r"(job|career|position|opening|posting|apply|req)", href, re.I) and \
           not re.search(r"(scientist|engineer|analyst|manager|researcher|ecologist|specialist|coordinator|technician|associate|director|lead|intern)", text, re.I):
            continue
        abs_url = requests.compat.urljoin(base, href)
        if abs_url in seen_hrefs:
            continue
        seen_hrefs.add(abs_url)
        postings.append(
            {
                "id": _hash_id(abs_url, text),
                "title": text,
                "location": "",
                "url": abs_url,
                "description": text,
            }
        )
    return postings


_FETCHERS = {
    "greenhouse": lambda c: fetch_greenhouse(c["slug"]),
    "lever": lambda c: fetch_lever(c["slug"]),
    "ashby": lambda c: fetch_ashby(c["slug"]),
    "html": lambda c: fetch_html(c["url"]),
}


def fetch_company(company: dict) -> list[dict]:
    """Dispatch on `type`. Raises FetchError on any failure (caller should catch)."""
    ctype = company.get("type", "").lower()
    fetcher = _FETCHERS.get(ctype)
    if fetcher is None:
        if ctype == "workday":
            raise FetchError(
                f"{company.get('name')}: Workday is not supported in v1 — "
                "use the company's Greenhouse/Lever/Ashby board if it has one, "
                "or type: html against the careers URL."
            )
        raise FetchError(f"{company.get('name')}: unknown type {ctype!r}")
    try:
        return fetcher(company)
    except (requests.RequestException, ValueError, KeyError) as exc:
        raise FetchError(f"{company.get('name')}: {exc}") from exc
