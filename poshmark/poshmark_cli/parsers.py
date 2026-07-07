"""Parse DOM data extracted from Poshmark pages.

The Poshmark search results page renders listing tiles with stable
``data-et-prop-listing_id`` attributes. The client extracts raw records via
``page.evaluate(...)`` and this module normalizes them into the public command
output shape and deduplicates by listing id.
"""
from typing import Any, Dict, List
from urllib.parse import urljoin


_BASE_URL = "https://poshmark.com"


def normalize_item(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a single raw listing tile into the public record shape."""
    item_id = (raw.get("id") or "").strip()
    href = (raw.get("href") or "").strip()
    return {
        "id": item_id,
        "lister_id": (raw.get("lister_id") or "").strip(),
        "title": (raw.get("title") or "").strip(),
        "price": (raw.get("price") or "").strip(),
        "size": (raw.get("size") or "").strip(),
        "image": (raw.get("image") or "").strip(),
        "url": urljoin(_BASE_URL, href) if href else "",
    }


def normalize_items(raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize raw listing tiles and deduplicate by listing id."""
    seen: set = set()
    results: List[Dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        item_id = (raw.get("id") or "").strip()
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        results.append(normalize_item(raw))
    return results
