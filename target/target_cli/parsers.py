"""Normalize redsky JSON into the Target CLI's documented command records.

These map the live redsky response shapes (captured and verified against
target.com) into flat dict records. Required identity fields (``tcin``) are read
directly so a contract break fails loudly; genuinely-optional fields (rating,
price range, image) normalize to ``None`` when the product omits them.
"""

import html
import re
from typing import Any, Dict, List, Optional

_TAG_RE = re.compile(r"<[^>]+>")


def _dig(node: Any, *keys: str) -> Any:
    """Walk nested dicts, returning None if any level is missing/not a dict."""
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _clean(text: Any, *, strip_tags: bool = False) -> Any:
    """Decode HTML entities (and optionally strip tags) in redsky text fields."""
    if not isinstance(text, str):
        return text
    if strip_tags:
        text = _TAG_RE.sub("", text)
    return html.unescape(text).strip()


def _price_range(price: Dict[str, Any]) -> Optional[str]:
    lo, hi = price.get("current_retail_min"), price.get("current_retail_max")
    if lo is not None and hi is not None and lo != hi:
        return f"${lo:.2f} - ${hi:.2f}"
    return None


def normalize_search_products(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Return {'total': int, 'products': [row, ...]} from a plp_search_v2 body."""
    search = _dig(raw, "data", "search") or {}
    total = _dig(search, "search_response", "metadata", "total_results")
    rows: List[Dict[str, Any]] = []
    for product in search.get("products") or []:
        item = product.get("item") or {}
        price = product.get("price") or {}
        rows.append(
            {
                "id": product["tcin"],
                "title": _clean(_dig(item, "product_description", "title")),
                "price": price.get("formatted_current_price"),
                "price_range": _price_range(price),
                "brand": _clean(_dig(item, "primary_brand", "name")),
                "rating": _dig(item, "ratings_and_reviews", "statistics", "rating", "average"),
                "rating_count": _dig(item, "ratings_and_reviews", "statistics", "rating", "count"),
                "url": _dig(item, "enrichment", "buy_url"),
                "image": _dig(item, "enrichment", "image_info", "primary_image", "url"),
            }
        )
    return {"total": total, "products": rows}


def normalize_product_detail(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Return a single product record from a pdp_client_v1 body."""
    product = _dig(raw, "data", "product") or {}
    item = product.get("item") or {}
    price = product.get("price") or {}
    bullets = _dig(item, "product_description", "bullet_descriptions") or []
    children = product.get("children") or []
    return {
        "id": product.get("tcin"),
        "title": _clean(_dig(item, "product_description", "title")),
        "price": price.get("formatted_current_price"),
        "brand": _clean(_dig(item, "primary_brand", "name")),
        "rating": _dig(product, "ratings_and_reviews", "statistics", "rating", "average"),
        "rating_count": _dig(product, "ratings_and_reviews", "statistics", "rating", "count"),
        "bullets": [_clean(b, strip_tags=True) for b in bullets],
        "url": _dig(item, "enrichment", "buy_url"),
        "variant_count": len(children),
        "variant_tcins": [c.get("tcin") for c in children if c.get("tcin")],
    }


def normalize_fulfillment(raw: Dict[str, Any], tcin: str) -> Dict[str, Any]:
    """Return stock/pickup/shipping summary from a product_fulfillment_v1 body."""
    ful = _dig(raw, "data", "product", "fulfillment") or {}
    pickup = []
    for opt in ful.get("store_options") or []:
        pickup.append(
            {
                "store_id": opt.get("location_id"),
                "store": opt.get("location_name") or _dig(opt, "store", "location_name"),
                "pickup": _dig(opt, "order_pickup", "availability_status"),
                "quantity": opt.get("location_available_to_promise_quantity"),
            }
        )
    shipping = ful.get("shipping_options") or {}
    return {
        "id": tcin,
        "sold_out": ful.get("sold_out"),
        "out_of_stock_all_stores": ful.get("is_out_of_stock_in_all_store_locations"),
        "shipping": shipping.get("availability_status"),
        "shipping_quantity": shipping.get("available_to_promise_quantity"),
        "pickup": pickup,
    }


def _store_row(store: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": store.get("store_id"),
        "name": store.get("location_name"),
        "distance": store.get("distance"),
        "status": store.get("status"),
        "address": _dig(store, "mailing_address", "address_line1"),
        "city": _dig(store, "mailing_address", "city"),
    }


def normalize_stores(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return a list of store records from a nearby_stores_v1 body."""
    stores = _dig(raw, "data", "nearby_stores", "stores") or []
    return [_store_row(store) for store in stores]


def normalize_store(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Return a single store record from a store_location_v1 body."""
    store = _dig(raw, "data", "store") or {}
    if not store.get("store_id"):
        return {}
    return _store_row(store)
