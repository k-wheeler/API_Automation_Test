"""Fetch job postings from a company's career page.

Each fetcher returns a list of normalized postings:

    {"id": str, "title": str, "location": str, "url": str, "description": str}

Reliability, best to worst:
  greenhouse / lever / ashby / bamboohr  -> clean JSON APIs
  rippling                               -> parses the page's embedded Next.js JSON
  html                                   -> best-effort scrape of a career page

The `html` fetcher only sees what's in the server-returned HTML (no JavaScript
runs), so it works when job *links* are present in the markup. When a link's
visible text is generic ("Apply", "View Position") or JS-filled/empty, the title
is derived from the URL slug instead.
"""

from __future__ import annotations

import hashlib
import json
import re
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

TIMEOUT = 25
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122 Safari/537.36"
    )
}


class FetchError(Exception):
    """Raised when a company's postings could not be fetched."""


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    soup = BeautifulSoup(unescape(text), "html.parser")
    return re.sub(r"\s+", " ", soup.get_text(" ")).strip()


def _hash_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _get(url: str, **kwargs: Any) -> requests.Response:
    headers = {**HEADERS, **kwargs.pop("headers", {})}
    resp = requests.get(url, headers=headers, timeout=TIMEOUT, **kwargs)
    resp.raise_for_status()
    return resp


# --- ATS-specific fetchers (clean JSON) --------------------------------------


def fetch_greenhouse(slug: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    data = _get(url).json()
    return [
        {
            "id": str(job.get("id")),
            "title": (job.get("title") or "").strip(),
            "location": (job.get("location") or {}).get("name", "").strip(),
            "url": job.get("absolute_url", ""),
            "description": _strip_html(job.get("content")),
        }
        for job in data.get("jobs", [])
    ]


def fetch_lever(slug: str) -> list[dict]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    data = _get(url).json()
    postings = []
    for job in data:
        cats = job.get("categories") or {}
        postings.append(
            {
                "id": str(job.get("id")),
                "title": (job.get("text") or "").strip(),
                "location": (cats.get("location") or "").strip(),
                "url": job.get("hostedUrl", ""),
                "description": job.get("descriptionPlain") or _strip_html(job.get("description")),
            }
        )
    return postings


def fetch_ashby(slug: str) -> list[dict]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    data = _get(url).json()
    return [
        {
            "id": str(job.get("id")),
            "title": (job.get("title") or "").strip(),
            "location": (job.get("location") or "").strip(),
            "url": job.get("jobUrl") or job.get("applyUrl", ""),
            "description": job.get("descriptionPlain") or _strip_html(job.get("descriptionHtml")),
        }
        for job in data.get("jobs", [])
    ]


def fetch_bamboohr(slug: str) -> list[dict]:
    url = f"https://{slug}.bamboohr.com/careers/list"
    data = _get(url, headers={**HEADERS, "Accept": "application/json"}).json()
    postings = []
    for job in data.get("result", []):
        loc = job.get("location") or {}
        parts = [loc.get("city"), loc.get("state")]
        postings.append(
            {
                "id": str(job.get("id")),
                "title": (job.get("jobOpeningName") or "").strip(),
                "location": ", ".join(p for p in parts if p).strip(),
                "url": f"https://{slug}.bamboohr.com/careers/{job.get('id')}",
                "description": job.get("employmentStatusLabel") or "",
            }
        )
    return postings


def fetch_workable(slug: str) -> list[dict]:
    url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true"
    data = _get(url, headers={"accept": "application/json"}).json()
    postings = []
    for job in data.get("jobs", []):
        loc = job.get("location") or {}
        if isinstance(loc, dict):
            loc = ", ".join(
                x for x in [loc.get("city"), loc.get("region") or loc.get("state"),
                            loc.get("country")] if x
            )
        postings.append(
            {
                "id": str(job.get("shortcode") or job.get("id") or job.get("code") or job.get("url")),
                "title": (job.get("title") or "").strip(),
                "location": loc if isinstance(loc, str) else "",
                "url": job.get("url") or job.get("application_url") or job.get("shortlink")
                or f"https://apply.workable.com/{slug}/",
                "description": _strip_html(job.get("description")),
            }
        )
    return postings


def fetch_pinpoint(slug: str) -> list[dict]:
    url = f"https://{slug}.pinpointhq.com/postings.json"
    data = _get(url, headers={"accept": "application/json"}).json().get("data", [])
    postings = []
    for job in data:
        loc = job.get("location")
        if isinstance(loc, dict):
            loc = loc.get("name") or loc.get("city") or ""
        job_url = job.get("url") or (f"https://{slug}.pinpointhq.com" + (job.get("path") or ""))
        postings.append(
            {
                "id": str(job.get("id")),
                "title": (job.get("title") or "").strip(),
                "location": (loc or "").strip() if isinstance(loc, str) else "",
                "url": job_url,
                "description": _strip_html(job.get("description")),
            }
        )
    return postings


def fetch_rippling(slug: str) -> list[dict]:
    """Rippling ATS boards are Next.js apps; the job list is embedded in the
    __NEXT_DATA__ script tag (react-query dehydrated state)."""
    html = _get(f"https://ats.rippling.com/{slug}/jobs").text
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise FetchError(f"rippling/{slug}: no __NEXT_DATA__ block found")
    data = json.loads(m.group(1))
    queries = data.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
    items = []
    for q in queries:
        d = q.get("state", {}).get("data")
        if isinstance(d, dict) and isinstance(d.get("items"), list) and d["items"]:
            first = d["items"][0]
            if isinstance(first, dict) and "name" in first and "url" in first:
                items = d["items"]
                break
    postings = []
    for job in items:
        locs = job.get("locations") or []
        loc_names = []
        for l in locs:
            if isinstance(l, dict):
                loc_names.append(l.get("name") or l.get("city") or "")
            elif isinstance(l, str):
                loc_names.append(l)
        postings.append(
            {
                "id": str(job.get("id")),
                "title": (job.get("name") or "").strip(),
                "location": ", ".join(x for x in loc_names if x).strip(),
                "url": urljoin(f"https://ats.rippling.com/{slug}/", job.get("url", "")),
                "description": (job.get("department") or {}).get("name", "")
                if isinstance(job.get("department"), dict)
                else str(job.get("department") or ""),
            }
        )
    return postings


# --- Generic HTML fallback ---------------------------------------------------

_GENERIC_TEXT = re.compile(
    r"^(apply( here| now| today)?|view( position| role| job| opening| details)?|"
    r"learn more|read more|see (more|position|role|open(ings?)?|details)|"
    r"open role|details|join( us)?|more info|explore|view)$",
    re.I,
)
_HREF_JOBLIKE = re.compile(r"(job|career|position|opening|posting|apply|req|vacanc|role)", re.I)
_TEXT_JOBLIKE = re.compile(
    r"(scientist|engineer|analyst|manager|researcher|ecologist|specialist|coordinator|"
    r"technician|associate|director|lead|officer|fellow|advisor|intern|consultant|"
    r"developer|designer|head of|vp|president|forester|gis|remote sensing)",
    re.I,
)
_STOP_SLUG = {
    "careers", "career", "jobs", "job", "positions", "openings", "opening",
    "about", "team", "contact", "home", "apply", "index",
}
_UUID = re.compile(r"-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _title_from_slug(url: str) -> str:
    seg = urlsplit(url).path.rstrip("/").split("/")[-1]
    if not seg:
        return ""
    seg = _UUID.sub("", seg)
    seg = re.sub(r"-jr\d+$", "", seg, flags=re.I)      # WRI-style req ids
    seg = re.sub(r"-\d{4}$", "", seg)                    # trailing year
    seg = re.sub(r"-(job-application|application|job)$", "", seg, flags=re.I)
    return seg.replace("_", " ").replace("-", " ").strip()


def _extract_job_links(soup: BeautifulSoup, base: str) -> list[dict]:
    """Emit one posting per job-looking link. Title comes from the link text,
    or the URL slug when the text is generic/empty. Shared by the html and
    browser fetchers."""
    postings = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("mailto:"):
            continue
        text = re.sub(r"\s+", " ", a.get_text(" ")).strip()
        abs_url = urljoin(base, href)
        if not (_HREF_JOBLIKE.search(abs_url) or _TEXT_JOBLIKE.search(text)):
            continue

        if text and len(text) >= 6 and not _GENERIC_TEXT.match(text):
            title = text
        else:
            title = _title_from_slug(abs_url)

        if not title or len(title) < 4 or title.lower() in _STOP_SLUG:
            continue
        if abs_url in seen:
            continue
        seen.add(abs_url)
        postings.append(
            {
                "id": _hash_id(abs_url),
                "title": title[:140],
                "location": "",
                "url": abs_url,
                "description": text,
            }
        )
    return postings


def fetch_html(url: str) -> list[dict]:
    """Best-effort scrape of a career page. Only works on server-rendered markup
    (no JavaScript). For JavaScript-rendered pages, use the browser fetcher."""
    resp = _get(url)
    return _extract_job_links(BeautifulSoup(resp.text, "html.parser"), resp.url)


def _render_page(url: str, wait_selector: str | None = None, timeout_ms: int = 45000) -> str:
    """Render a JavaScript page with headless Chromium and return its HTML."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise FetchError(
            "browser fetcher needs Playwright — `pip install playwright` then "
            "`python -m playwright install chromium`"
        ) from exc
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=HEADERS["User-Agent"])
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            # networkidle is ideal but some SPAs poll forever — don't hang on it.
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=8000)
                except Exception:
                    pass
            page.wait_for_timeout(2500)  # let late XHR-rendered lists settle
            return page.content()
        finally:
            browser.close()


def fetch_browser(url: str, wait_selector: str | None = None) -> list[dict]:
    """Render a JavaScript-heavy career page in headless Chromium, then extract
    job links from the rendered DOM. Use for SPA/JS boards (Paycom, Getro,
    Airtable, custom JS sites) that the html/section fetchers can't read."""
    try:
        html = _render_page(url, wait_selector)
    except FetchError:
        raise
    except Exception as exc:  # Playwright timeouts, crashes, etc.
        raise FetchError(f"browser: {exc}") from exc
    return _extract_job_links(BeautifulSoup(html, "html.parser"), url)


# --- "Open positions" section watcher (Webflow etc.) -------------------------

_SECTION_HEADER = re.compile(
    r"open position|open role|current opening|available position|we.?re hiring|"
    r"join (our|the) team|(current|available|explore) opportunit",
    re.I,
)


def _item_to_posting(item, base: str, page_url: str) -> dict:
    a = item.find("a", href=True)
    href = a["href"].strip() if a else ""
    abs_url = urljoin(base, href) if href else page_url
    heading = item.find(re.compile(r"^h[1-6]$"))
    title = ""
    for cand in (
        heading.get_text(" ", strip=True) if heading else "",
        a.get_text(" ", strip=True) if a else "",
        item.get_text(" ", strip=True),
    ):
        cand = re.sub(r"\s+", " ", cand or "").strip()
        if cand and not _GENERIC_TEXT.match(cand):
            title = cand
            break
    if not title or _GENERIC_TEXT.match(title):
        title = _title_from_slug(abs_url) or title
    return {
        "id": _hash_id(abs_url if href else title),
        "title": title[:140],
        "location": "",
        "url": abs_url,
        "description": re.sub(r"\s+", " ", item.get_text(" ", strip=True))[:400],
    }


def _parse_section(soup: BeautifulSoup, base: str, page_url: str, pat: re.Pattern) -> list[dict]:
    node = soup.find(string=pat)
    if node is None:
        raise FetchError(f"section: no header matching {pat.pattern!r} at {page_url}")
    header_el = node.parent
    # Find the Webflow collection list scoped to the header's container.
    coll = None
    anc = header_el
    for _ in range(8):
        anc = anc.parent
        if anc is None:
            break
        c = anc.find(class_=re.compile(r"w-dyn-list"))
        if c is not None:
            coll = c
            break
    if coll is not None:
        items = coll.find_all(class_=re.compile(r"\bw-dyn-item\b"))
        return [_item_to_posting(it, base, page_url) for it in items]

    # Fallback A (non-Webflow): job-like links appearing after the header.
    postings, seen = [], set()
    for a in header_el.find_all_next("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("mailto:"):
            continue
        text = re.sub(r"\s+", " ", a.get_text(" ")).strip()
        abs_url = urljoin(base, href)
        if not (_HREF_JOBLIKE.search(abs_url) or _TEXT_JOBLIKE.search(text)):
            continue
        title = text if (text and len(text) >= 6 and not _GENERIC_TEXT.match(text)) else _title_from_slug(abs_url)
        if not title or len(title) < 4 or title.lower() in _STOP_SLUG or abs_url in seen:
            continue
        seen.add(abs_url)
        postings.append({"id": _hash_id(abs_url), "title": title[:140],
                         "location": "", "url": abs_url, "description": text})
    if postings:
        return postings

    # Fallback B (plain-text pages, e.g. Squarespace with email-to-apply): watch
    # the page's visible text. Stay silent while it says "no open roles"; when
    # that changes, emit one alert whose id tracks the content (so it fires once
    # per change, not every run). Assumes the page states "no open roles" when empty.
    return _section_text_state(soup, page_url)


_NO_OPENINGS = re.compile(
    r"no (current(ly)? )?open (role|position)|no (current )?opening|"
    r"not have any open|no items found|check back|currently no open|no open roles|"
    r"no positions (are )?(currently )?(open|available)",
    re.I,
)


_SKIP_TAGS = {"script", "style", "noscript", "nav", "footer"}


def _visible_text(soup) -> str:
    parts = []
    for s in soup.find_all(string=True):
        anc = s.parent
        skip = False
        while anc is not None:
            if anc.name in _SKIP_TAGS:
                skip = True
                break
            anc = anc.parent
        if skip:
            continue
        t = s.strip()
        if t:
            parts.append(t)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _section_text_state(soup, page_url: str) -> list[dict]:
    text = _visible_text(soup)
    if not text or _NO_OPENINGS.search(text):
        return []
    return [{
        "id": _hash_id(text[:3000]),
        "title": "Open positions updated — check the page",
        "location": "",
        "url": page_url,
        "description": text[:2000],
    }]


def fetch_section(url: str, header: str | None = None) -> list[dict]:
    """Read job items listed under an 'Open positions' header. Works on
    server-rendered CMS pages (e.g. Webflow): an empty collection yields no
    postings, and a role added later appears as a new item."""
    pat = re.compile(header, re.I) if header else _SECTION_HEADER
    resp = _get(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    return _parse_section(soup, resp.url, resp.url, pat)


# --- Notion public-page database ---------------------------------------------


def _notion_page_id(url: str) -> str:
    m = re.search(r"([0-9a-fA-F]{32})", url)
    if not m:
        raise FetchError(f"notion: could not find a 32-char page id in {url}")
    h = m.group(1).lower()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def _notion_title_id(schema: dict) -> str:
    return next((k for k, v in schema.items() if v.get("type") == "title"), "title")


def _notion_rows(qrm: dict, cid: str, title_id: str, base: str) -> list[dict]:
    """Extract job rows from a queryCollection recordMap."""
    postings, seen = [], set()
    for _bid, b in (qrm.get("block") or {}).items():
        v = b.get("value") or {}
        if v.get("type") != "page" or v.get("parent_id") != cid:
            continue
        props = v.get("properties") or {}
        seg = props.get(title_id) or props.get("title") or []
        title = "".join(s[0] for s in seg if s and isinstance(s[0], str)).strip()
        rid = v.get("id", "")
        if not title or rid in seen:
            continue
        seen.add(rid)
        postings.append(
            {
                "id": rid or _hash_id(title),
                "title": title[:140],
                "location": "",
                "url": f"{base}/{rid.replace('-', '')}",
                "description": title,
            }
        )
    return postings


def fetch_notion(url: str) -> list[dict]:
    """Read job rows from a public Notion page that embeds an inline database.

    Uses Notion's public (unauthenticated) API — the same endpoints the page's
    own JavaScript calls. Pages whose jobs live in a linked/sub-page database
    (not inline) raise FetchError."""
    base = "https://" + urlsplit(url).netloc
    hdr = {**HEADERS, "content-type": "application/json", "accept": "application/json"}
    r1 = requests.post(
        base + "/api/v3/loadCachedPageChunkV2",
        headers=hdr, timeout=TIMEOUT,
        data=json.dumps({"page": {"id": _notion_page_id(url)}, "limit": 200,
                         "cursor": {"stack": []}, "chunkNumber": 0, "verticalColumns": False}),
    )
    r1.raise_for_status()
    rm = r1.json().get("recordMap", {})
    collections = rm.get("collection") or {}
    views = list(rm.get("collection_view") or {})
    if not collections:
        raise FetchError(f"notion: no inline database found on {url} "
                         "(the jobs may be in a linked or sub-page database)")

    postings = []
    for cid, crec in collections.items():
        schema = (crec.get("value") or {}).get("schema", {})
        title_id = _notion_title_id(schema)
        body = {"collection": {"id": cid},
                "loader": {"type": "reducer",
                           "reducers": {"collection_group_results": {"type": "results", "limit": 200}},
                           "searchQuery": "", "userTimeZone": "UTC"}}
        if views:
            body["collectionView"] = {"id": views[0]}
        r2 = requests.post(base + "/api/v3/queryCollection?src=initial_load",
                           headers=hdr, timeout=TIMEOUT, data=json.dumps(body))
        if r2.status_code != 200:
            continue
        qrm = r2.json().get("recordMap", {})
        if not schema:  # schema sometimes only present in the query response
            schema = (qrm.get("collection", {}).get(cid, {}).get("value") or {}).get("schema", {})
            title_id = _notion_title_id(schema)
        postings.extend(_notion_rows(qrm, cid, title_id, base))
    return postings


# --- Dispatch ----------------------------------------------------------------

_FETCHERS = {
    "greenhouse": lambda c: fetch_greenhouse(c["slug"]),
    "lever": lambda c: fetch_lever(c["slug"]),
    "ashby": lambda c: fetch_ashby(c["slug"]),
    "bamboohr": lambda c: fetch_bamboohr(c["slug"]),
    "workable": lambda c: fetch_workable(c["slug"]),
    "pinpoint": lambda c: fetch_pinpoint(c["slug"]),
    "rippling": lambda c: fetch_rippling(c["slug"]),
    "gusto": lambda c: fetch_html(c["url"]),  # Gusto boards are server-rendered
    "section": lambda c: fetch_section(c["url"], c.get("header")),
    "notion": lambda c: fetch_notion(c["url"]),
    "browser": lambda c: fetch_browser(c["url"], c.get("wait")),
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
