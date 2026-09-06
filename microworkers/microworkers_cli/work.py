"""Microworkers IMDb task-work adapter.

Drives the Microworkers "IMDb filmography" worker task flow end to end:

1. **Bitly preview** — recognize the preview/interstitial page and validate its
   single visible ``Continue`` link, which must target the exact Google search
   query for the actor being looked up.
2. **Google SERP** — validate and click the exact IMDb *name* result (an
   ``imdb.com/name/nm...`` page whose link text names the actor), not any
   incidental IMDb link.
3. **IMDb name page** — parse the acting credits (title / year / role).

The page-driving functions operate on a :class:`cli_tools_shared` browser page
(the same ``BrowserHarnessService`` object returned by
``MicroworkersBrowser.get_page``): they only call ``evaluate``, ``url``, and
``wait_for_timeout``, which keeps the flow testable against a fake page.

Selectors for the live Bitly/Google/IMDb DOM are extracted via ``evaluate`` and
validated/parsed in pure Python below, so the deterministic decisions (exactly
one continue link, exactly one IMDb name result, credit normalization) live in
functions that can be unit-tested without a browser.
"""

import json
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from cli_tools_shared.exceptions import ClientError

__all__ = [
    "TaskWorkError",
    "normalize_name",
    "google_search_url",
    "is_bitly_preview",
    "is_continue_link",
    "validate_google_search_destination",
    "is_imdb_name_url",
    "select_exact_imdb_name_result",
    "parse_acting_credits",
    "recognize_bitly_continue",
    "run_imdb_credits_task",
]


class TaskWorkError(ClientError):
    """Raised when the IMDb task-work flow cannot proceed to a valid target."""


GOOGLE_SEARCH_HOSTS = frozenset({"google.com", "www.google.com"})
IMDB_HOSTS = frozenset({"imdb.com", "www.imdb.com", "m.imdb.com"})

# Extracts every visible <a> as {text, href, visible}. Visibility uses the
# bounding box plus offsetParent so hidden/offscreen links are excluded before
# the Python-side "exactly one" validation runs.
ANCHORS_JS = """
() => Array.from(document.querySelectorAll('a')).map(a => {
  const rect = a.getBoundingClientRect();
  const visible = rect.width > 0 && rect.height > 0 && a.offsetParent !== null;
  return { text: (a.innerText || '').trim(), href: a.href || null, visible };
})
"""

# Extracts raw credit entries from an IMDb name page's filmography list. The
# ipc-metadata-list-summary-item markup is the current IMDb name-page list
# item; title/year/role are pulled defensively (missing nodes yield null, and
# parse_acting_credits drops entries without a title).
IMDB_CREDITS_JS = """
() => Array.from(document.querySelectorAll('li.ipc-metadata-list-summary-item')).map(li => {
  const titleEl = li.querySelector('a.ipc-metadata-list-summary-item__t');
  const yearEl = li.querySelector('.ipc-metadata-list-summary-item__li');
  const roleEl = li.querySelector('.ipc-metadata-list-summary-item__tc')
    || li.querySelector('.ipc-metadata-list-summary-item__cc');
  return {
    title: titleEl ? titleEl.innerText.trim() : null,
    href: titleEl ? titleEl.href : null,
    year: yearEl ? yearEl.innerText.trim() : null,
    role: roleEl ? roleEl.innerText.trim() : null,
  };
})
"""


def normalize_name(name: str) -> str:
    """Collapse surrounding/interior whitespace in a person's name."""
    return " ".join((name or "").strip().split())


def _normalize_text(text: Optional[str]) -> str:
    return " ".join((text or "").strip().split())


def google_search_url(name: str) -> str:
    """Canonical Google ``/search`` URL for the exact-phrase ``name`` query."""
    return f"https://www.google.com/search?q={normalize_name(name).replace(' ', '+')}"


def is_bitly_preview(title: str) -> bool:
    """True when a page title identifies a Bitly preview/interstitial page."""
    t = (title or "").strip().lower()
    return "bitly" in t or "bit.ly" in t


def is_continue_link(text: Optional[str]) -> bool:
    """True when link text is the Bitly preview ``Continue`` control."""
    t = _normalize_text(text).lower()
    if not t:
        return False
    return t == "continue" or t.startswith("continue ")


def validate_google_search_destination(href: str, name: str) -> bool:
    """True when ``href`` is a Google ``/search`` query for the exact ``name``.

    Extra query parameters (``sourceid``, ``ie``, ``source``, etc.) are ignored;
    only the host, path, and decoded ``q`` parameter matter.
    """
    if not href:
        return False
    parsed = urlparse(href)
    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.hostname not in GOOGLE_SEARCH_HOSTS:
        return False
    if parsed.path != "/search":
        return False
    query = parse_qs(parsed.query)
    q_values = query.get("q", [])
    if not q_values:
        return False
    expected = normalize_name(name)
    return any(normalize_name(value) == expected for value in q_values)


def is_imdb_name_url(url: Optional[str]) -> bool:
    """True when ``url`` is an IMDb *name* page (``/name/nm...``, not a title)."""
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.hostname not in IMDB_HOSTS:
        return False
    return parsed.path.startswith("/name/nm")


def _is_visible(record: Dict[str, Any]) -> bool:
    # Anchors extracted by ANCHORS_JS always carry a bool `visible`; fixtures
    # without the field are treated as visible.
    return record.get("visible") is not False


def select_exact_imdb_name_result(
    results: List[Dict[str, Any]], name: str
) -> Dict[str, Any]:
    """Return the single visible IMDb name result whose text names ``name``.

    Raises :class:`TaskWorkError` when the result set does not contain exactly
    one visible IMDb *name* link that mentions ``name``.
    """
    expected = normalize_name(name).lower()
    candidates = []
    for record in results or []:
        if not _is_visible(record):
            continue
        text = _normalize_text(record.get("text") or record.get("title")).lower()
        url = record.get("href") or record.get("url")
        if is_imdb_name_url(url) and expected in text:
            candidates.append(record)
    if len(candidates) != 1:
        raise TaskWorkError(
            f"{name} search results did not expose exactly one IMDb name link; "
            f"found {len(candidates)}."
        )
    return candidates[0]


def parse_acting_credits(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize raw IMDb acting-credit entries into ``{title, year, role}``.

    Entries without a title are dropped. ``year`` is parsed to the first
    four-digit year (``None`` when absent, e.g. a TV series without a year).
    """
    credits: List[Dict[str, Any]] = []
    for entry in entries or []:
        title = _normalize_text(entry.get("title"))
        if not title:
            continue
        year_raw = _normalize_text(entry.get("year"))
        year: Optional[int] = None
        if year_raw:
            digits = "".join(ch for ch in year_raw if ch.isdigit())
            if digits:
                year = int(digits[:4])
        credits.append(
            {"title": title, "year": year, "role": _normalize_text(entry.get("role"))}
        )
    return credits


def _click_anchor(page, href: str, text: Optional[str] = None) -> bool:
    """Click the single visible anchor with ``href`` (and exact ``text``).

    Returns True when exactly one visible anchor matched and was clicked.
    """
    condition = f"a.href === {json.dumps(href)}"
    if text is not None:
        condition += f" && (a.innerText || '').trim() === {json.dumps(text)}"
    js = (
        "() => {"
        " const target = Array.from(document.querySelectorAll('a')).filter(a => {"
        "  const r = a.getBoundingClientRect();"
        "  const visible = r.width > 0 && r.height > 0 && a.offsetParent !== null;"
        f"  return visible && {condition};"
        " });"
        " if (target.length !== 1) { return { clicked: false, count: target.length }; }"
        " target[0].click(); return { clicked: true, count: 1 };"
        "}"
    )
    result = page.evaluate(js)
    return bool(result and result.get("clicked"))


def recognize_bitly_continue(page, name: str, log=None) -> Dict[str, Any]:
    """Validate the Bitly preview page and return its single ``Continue`` link.

    Raises :class:`TaskWorkError` when the page is not a Bitly preview, when it
    exposes anything other than exactly one visible ``Continue`` link, or when
    that link's destination is not the exact Google query for ``name``.
    """
    title = page.evaluate("() => document.title") or ""
    if not is_bitly_preview(title):
        raise TaskWorkError(f"Expected a Bitly preview page; got title {title!r}.")

    anchors = page.evaluate(ANCHORS_JS) or []
    continue_links = [
        a
        for a in anchors
        if _is_visible(a) and is_continue_link(a.get("text"))
    ]
    if len(continue_links) != 1:
        raise TaskWorkError(
            f"Bitly preview did not expose exactly one visible Continue link; "
            f"found {len(continue_links)}."
        )

    link = continue_links[0]
    href = link.get("href")
    if not validate_google_search_destination(href, name):
        raise TaskWorkError(
            f"Bitly Continue link does not target the exact Google query for "
            f"{name!r}: {href!r}."
        )
    if log:
        log(f"Validated Bitly Continue link -> {href}")
    return link


def run_imdb_credits_task(
    page, name: str = "Kurt Finney", log=None
) -> List[Dict[str, Any]]:
    """Run the full IMDb task-work flow and return parsed acting credits.

    Order of operations:

    1. Validate the Bitly preview ``Continue`` link and click it.
    2. On the resulting Google SERP, validate and click the exact IMDb name
       result for ``name``.
    3. Parse the acting credits from the IMDb name page.
    """
    continue_link = recognize_bitly_continue(page, name, log=log)
    if not _click_anchor(page, continue_link["href"], continue_link["text"]):
        raise TaskWorkError("Failed to click the Bitly Continue link.")
    page.wait_for_timeout(1500)

    results = page.evaluate(ANCHORS_JS) or []
    imdb_result = select_exact_imdb_name_result(results, name)
    if log:
        log(f"Validated IMDb name result -> {imdb_result['href']}")
    if not _click_anchor(page, imdb_result["href"]):
        raise TaskWorkError("Failed to click the IMDb name result.")
    page.wait_for_timeout(1500)

    entries = page.evaluate(IMDB_CREDITS_JS) or []
    return parse_acting_credits(entries)
