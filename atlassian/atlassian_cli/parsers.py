"""Parse the FlexOffers Atlassian affiliate page into CLI records."""
from html import unescape
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse


def extract_items_from_snapshot(page_text: str) -> List[Dict]:
    """Extract the Atlassian affiliate program record from page HTML."""
    title = _meta_content(page_text, "og:title") or _title(page_text)
    url = _meta_content(page_text, "og:url") or _canonical(page_text)
    description = _meta_content(page_text, "description")

    if not title:
        raise ValueError("Atlassian page did not contain a title.")
    if not url:
        raise ValueError("Atlassian page did not contain a canonical URL.")

    return [
        {
            "id": _slug_from_url(url),
            "name": _clean(title),
            "status": "active",
            "description": _clean(description) if description else None,
        }
    ]


def _meta_content(page_text: str, name: str) -> Optional[str]:
    pattern = (
        rf'<meta\s+(?:name|property)=["\']{re.escape(name)}["\']\s+'
        rf'content=["\']([^"\']+)["\']'
    )
    match = re.search(pattern, page_text, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def _title(page_text: str) -> Optional[str]:
    match = re.search(r"<title>(.*?)</title>", page_text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1)
    return None


def _canonical(page_text: str) -> Optional[str]:
    match = re.search(
        r'<link\s+rel=["\']canonical["\']\s+href=["\']([^"\']+)["\']',
        page_text,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1)
    return None


def _slug_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if not path:
        raise ValueError(f"Atlassian canonical URL has no path: {url}")
    return path.split("/")[-1]


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()
