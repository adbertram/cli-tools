"""Parse DOM data extracted from Poshmark pages.

The Poshmark search results page renders listing tiles with stable
``data-et-prop-listing_id`` attributes. The client extracts raw records via
``page.evaluate(...)`` and this module normalizes them into the public command
output shape and deduplicates by listing id.
"""
import re
from typing import Any, Dict, List
from urllib.parse import urljoin

from cli_tools_shared.exceptions import ClientError


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


def _required_text(data: Dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ClientError(f"Poshmark listing detail is missing required field: {field}.")
    return value.strip()


def normalize_item_detail(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one live Poshmark product page into a detail record."""
    product = raw.get("product")
    if not isinstance(product, dict) or product.get("@type") != "Product":
        raise ClientError("Poshmark listing detail did not include Product data.")
    offers = product.get("offers")
    if not isinstance(offers, dict) or offers.get("@type") != "Offer":
        raise ClientError("Poshmark listing detail did not include Offer data.")

    images_raw = product.get("image")
    if isinstance(images_raw, str) and images_raw.strip():
        image_urls = [images_raw.strip()]
    elif isinstance(images_raw, list) and all(isinstance(value, str) and value.strip() for value in images_raw):
        image_urls = [value.strip() for value in images_raw]
    else:
        raise ClientError("Poshmark listing detail is missing required field: image.")

    shipping_text = _required_text(raw, "shipping_text")
    if shipping_text.lower() == "free shipping":
        shipping_estimate = 0.0
    else:
        shipping_match = re.fullmatch(r"\$([\d,]+(?:\.\d{1,2})?) Shipping", shipping_text)
        if shipping_match is None:
            raise ClientError(f"Unexpected Poshmark shipping value: {shipping_text!r}.")
        shipping_estimate = float(shipping_match.group(1).replace(",", ""))

    availability = _required_text(offers, "availability").rsplit("/", 1)[-1]
    available = availability == "InStock"
    condition = _required_text(offers, "itemCondition").rsplit("/", 1)[-1]
    brand = product.get("brand")
    brand_name = brand.get("name") if isinstance(brand, dict) else None

    return {
        "id": _required_text(product, "productID"),
        "title": _required_text(product, "name"),
        "description": _required_text(product, "description"),
        "price": float(_required_text(offers, "price")),
        "price_currency": _required_text(offers, "priceCurrency"),
        "availability": availability,
        "available": available,
        "available_fulfillment": ["shipping"] if available else [],
        "condition": condition,
        "seller_name": _required_text(raw, "seller_name"),
        "shipping": shipping_text,
        "shipping_estimate": shipping_estimate,
        "size": raw.get("size"),
        "brand": brand_name,
        "category": product.get("category"),
        "image": image_urls[0],
        "image_urls": image_urls,
        "url": _required_text(offers, "url"),
    }
