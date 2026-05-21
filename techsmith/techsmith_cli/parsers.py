"""Parse the TechSmith affiliate page into CLI records."""
from html import unescape
from html.parser import HTMLParser
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse


class _TechSmithPageParser(HTMLParser):
    """Collect metadata from the TechSmith affiliate page."""

    def __init__(self):
        super().__init__()
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.casefold() != "meta":
            return

        attr_map = {name.casefold(): value for name, value in attrs if value is not None}
        key = attr_map.get("property") or attr_map.get("name")
        content = attr_map.get("content")
        if key is not None and content is not None:
            self.meta[key] = content


def extract_items_from_snapshot(page_text: str) -> List[Dict]:
    """Extract the TechSmith affiliate program record from page HTML."""
    parser = _TechSmithPageParser()
    parser.feed(page_text)

    title = parser.meta.get("og:title")
    url = parser.meta.get("og:url")
    description = parser.meta.get("description")

    if not title:
        raise ValueError("TechSmith page did not contain og:title metadata.")
    if not url:
        raise ValueError("TechSmith page did not contain og:url metadata.")
    if not description:
        raise ValueError("TechSmith page did not contain description metadata.")

    return [
        {
            "id": _slug_from_url(url),
            "name": _clean(title),
            "status": "active",
            "description": _clean(description),
        }
    ]


def _slug_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if not path:
        raise ValueError(f"TechSmith canonical URL has no path: {url}")
    return path.split("/")[-1]


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()
