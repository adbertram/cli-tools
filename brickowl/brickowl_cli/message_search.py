"""Pure helpers for `brickowl messages search` (live, fully paged message lookup).

Brick Owl list rows carry an epoch-seconds sort key (UTC) in the date cell, so
exact times come from ``timestamp`` rather than the display string.
"""

import re
from datetime import date, datetime, time, timezone
from typing import Iterable, List, Optional

URL_RE = re.compile(r"""(?:https?://|www\.|(?<![\w@/])[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|co|me|ly|app)/)[^\s<>"')\]]+""", re.I)


def parse_bound(value: Optional[str], end: bool = False) -> Optional[datetime]:
    """Parse --since/--until. Date-only covers the whole day; naive = local time."""
    if not value:
        return None
    v = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        dt = datetime.combine(date.fromisoformat(v), time.max if end else time.min)
    else:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    return dt.astimezone() if dt.tzinfo is None else dt


def from_timestamp(ts: Optional[int]) -> Optional[datetime]:
    return datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None


def parse_display_utc(value: Optional[str]) -> Optional[datetime]:
    """Fallback for 'Oct 28, 2026, 16:09' (Brick Owl displays UTC)."""
    try:
        return datetime.strptime((value or "").strip(), "%b %d, %Y, %H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def in_window(dt: Optional[datetime], since: Optional[datetime], until: Optional[datetime]) -> bool:
    if dt is None:
        return True
    return not ((since and dt < since) or (until and dt > until))


def user_matches(row: dict, users: Optional[List[str]]) -> bool:
    if not users:
        return True
    names = {(row.get("from") or "").strip().lower(), (row.get("to") or "").strip().lower()}
    return any(u.strip().lower() in names for u in users)


def extract_links(*texts: Optional[str], hrefs: Iterable[str] = ()) -> List[str]:
    seen, out = set(), []
    cands = [m.group(0).rstrip(".,;:!?") for t in texts if t for m in URL_RE.finditer(t)]
    cands.extend(h for h in hrefs if h)
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out
