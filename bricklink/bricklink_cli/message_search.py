"""Pure helpers for `bricklink messages search` (live, fully paged message lookup).

BrickLink renders message timestamps in US Eastern time with no zone marker
("Oct 24, 2026 21:04"); list rows carry only the date ("Oct 24, 2026"). These
helpers turn those strings into timezone-aware datetimes, decide when paging
can stop, and pull links out of message bodies, so the browser layer only has
to fetch pages.
"""

import os
import re
from datetime import date, datetime, time, timedelta
from typing import Callable, Iterable, List, Optional
from zoneinfo import ZoneInfo

DISPLAY_TZ_ENV = "BRICKLINK_DISPLAY_TZ"
DEFAULT_DISPLAY_TZ = "America/New_York"

URL_RE = re.compile(r"""(?:https?://|www\.|(?<![\w@/])[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|co|me|ly|app)/)[^\s<>"')\]]+""", re.I)


def display_tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get(DISPLAY_TZ_ENV, DEFAULT_DISPLAY_TZ))


def parse_list_date(value: str) -> Optional[date]:
    """Parse a list-row date like 'Oct 24, 2026'."""
    try:
        return datetime.strptime((value or "").strip(), "%b %d, %Y").date()
    except ValueError:
        return None


def parse_sent(value: str, tz: Optional[ZoneInfo] = None) -> Optional[datetime]:
    """Parse a detail-page 'Sent:' value ('Oct 24, 2026 21:04') as an aware datetime."""
    s = re.sub(r"\s+", " ", (value or "").replace("\xa0", " ")).strip()
    for fmt in ("%b %d, %Y %H:%M:%S", "%b %d, %Y %H:%M", "%b %d, %Y %I:%M %p", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=tz or display_tz())
        except ValueError:
            continue
    return None


def parse_bound(value: Optional[str], end: bool = False) -> Optional[datetime]:
    """Parse a --since/--until value. Date-only values cover the whole day.

    Naive values are interpreted in the machine's local timezone.
    """
    if not value:
        return None
    v = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        d = date.fromisoformat(v)
        dt = datetime.combine(d, time.max if end else time.min)
    else:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt


def extract_links(*texts: Optional[str], hrefs: Iterable[str] = ()) -> List[str]:
    """Return unique links found in text plus explicit hrefs, in first-seen order."""
    seen, out = set(), []
    candidates = []
    for t in texts:
        if t:
            candidates.extend(m.group(0).rstrip(".,;:!?") for m in URL_RE.finditer(t))
    candidates.extend(h for h in hrefs if h)
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def normalize_body(body: Optional[str]) -> Optional[str]:
    """Undo BrickLink's <br>-doubling: empty lines are artifacts, space-only lines are paragraphs."""
    if body is None:
        return None
    lines = [ln for ln in body.replace("\r", "").split("\n") if ln != ""]
    return "\n".join(ln.rstrip() for ln in lines).strip()


def user_matches(username: Optional[str], users: Optional[List[str]]) -> bool:
    if not users:
        return True
    u = (username or "").strip().lower()
    return any(u == x.strip().lower() for x in users)


def iter_live_rows(fetch_page: Callable[[int], list], since_day: Optional[date] = None,
                   max_pages: int = 200) -> Iterable[dict]:
    """Yield list rows page by page (newest first) until the window is exhausted.

    Stops when a page is empty, repeats the previous page (past the last page),
    or its oldest row is older than ``since_day``. Raises when ``max_pages`` is
    hit before reaching ``since_day`` so a truncated scan is never silent.
    """
    prev_ids = None
    for pg in range(1, max_pages + 1):
        rows = fetch_page(pg) or []
        ids = [r.get("message_id") for r in rows]
        if not rows or ids == prev_ids:
            return
        prev_ids = ids
        for r in rows:
            yield r
        oldest = min((d for d in (parse_list_date(r.get("date", "")) for r in rows) if d), default=None)
        if since_day and oldest and oldest < since_day:
            return
    if since_day is not None:
        raise RuntimeError(
            f"Scanned {max_pages} pages without reaching {since_day}; raise --max-pages."
        )


def in_window(dt: Optional[datetime], since: Optional[datetime], until: Optional[datetime]) -> bool:
    if dt is None:
        return True
    if since and dt < since:
        return False
    if until and dt > until:
        return False
    return True


def day_in_window(d: Optional[date], since: Optional[datetime], until: Optional[datetime],
                  tz: Optional[ZoneInfo] = None) -> bool:
    """Coarse date-only filter for list rows (widened by a day for zone skew)."""
    if d is None:
        return True
    if since and d < (since.astimezone(tz or display_tz()).date() - timedelta(days=1)):
        return False
    if until and d > (until.astimezone(tz or display_tz()).date() + timedelta(days=1)):
        return False
    return True
