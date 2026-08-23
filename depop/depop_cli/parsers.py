"""Normalize Depop search API responses into public command records.

Field shapes here are validated against real captured responses from the
live `GET www.depop.com/presentation/api/v1/search/products/` endpoint (see
client.py module docstring for the discovery record). We return the raw
object verbatim (no upstream field is dropped, per the "return everything
the API provides" contract) and add convenience top-level fields (`url`,
`price`, `currency`, `condition`, `gender`, `category`) so common table
columns and `--filter` targets do not require reaching into nested
`pricing`/`attributes` objects. None of the original fields are overwritten.
"""

from typing import Any, Dict, List

PRODUCT_URL_TEMPLATE = "https://www.depop.com/products/{slug}/"


def _with_conveniences(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Return the raw search object plus flat convenience fields (non-destructive)."""
    if not isinstance(raw, dict):
        return raw
    item = dict(raw)

    slug = raw.get("slug")
    if slug:
        item.setdefault("url", PRODUCT_URL_TEMPLATE.format(slug=slug))

    pricing = raw.get("pricing") or {}
    current_price = pricing.get("current_price") or {}
    if "total_price" in current_price:
        item.setdefault("price", current_price["total_price"])
    if "currency" in pricing:
        item.setdefault("currency", pricing["currency"])

    attributes = raw.get("attributes") or {}
    if "condition" in attributes:
        item.setdefault("condition", attributes["condition"])
    if "gender" in attributes:
        item.setdefault("gender", attributes["gender"])
    if "group" in attributes:
        item.setdefault("category", attributes["group"])

    return item


def normalize_items(raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize search result objects, preserving every upstream field."""
    return [_with_conveniences(item) for item in raw_items]
