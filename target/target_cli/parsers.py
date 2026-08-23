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
        # Pre-launch ("coming soon") listings carry a future release date here even
        # though the PDP itself is already live; genuinely optional -- most items
        # have no street date at all. Verified live for TCIN 94962117 (LoveShackFancy
        # x Target x Yoobi, street_date "2026-07-05").
        "street_date": _dig(item, "mmbv_content", "street_date"),
    }


# Fulfillment channel values observed live from product_fulfillment_v1 that mean
# "a guest can actually order this right now." Verified against two real TCINs:
# an in-stock item (87450164, Bounty paper towels) returned "IN_STOCK" for both
# pickup.order_pickup.availability_status and shipping.availability_status; a
# pre-launch item (94962117, street_date 2026-07-05) returned "UNAVAILABLE" for
# pickup and "OUT_OF_STOCK" for shipping. Treated as an allowlist (not a denylist)
# so an unrecognized future status defaults to "not orderable" rather than being
# silently treated as purchasable.
_ORDERABLE_STATUSES = {"IN_STOCK"}


def is_orderable(fulfillment: Dict[str, Any]) -> bool:
    """True when at least one fulfillment channel (shipping or any pickup store)
    is in an orderable status, per ``_ORDERABLE_STATUSES``."""
    if fulfillment.get("shipping") in _ORDERABLE_STATUSES:
        return True
    return any(p.get("pickup") in _ORDERABLE_STATUSES for p in fulfillment.get("pickup") or [])


def _pre_order_quantity(store_options: List[Dict[str, Any]]) -> Optional[float]:
    """Return the pre-order-to-promise signal across stores, or None if absent.

    ``pre_order_location_available_to_promise_quantity`` is a per-store field
    (sibling of the existing ``location_available_to_promise_quantity`` used for
    ``quantity``) that only appears on pre-launch items. Taken as the max across
    stores -- like ``is_orderable``'s any-store-counts semantics -- so a single
    store with allocated pre-order stock surfaces the signal even when other
    stores report zero. Absent on every store (a normal in-stock item) normalizes
    to None rather than 0, since 0 is itself meaningful (allocated but depleted).
    """
    values = [
        opt.get("pre_order_location_available_to_promise_quantity")
        for opt in store_options
        if opt.get("pre_order_location_available_to_promise_quantity") is not None
    ]
    return max(values) if values else None


def normalize_fulfillment(raw: Dict[str, Any], tcin: str) -> Dict[str, Any]:
    """Return stock/pickup/shipping summary from a product_fulfillment_v1 body."""
    ful = _dig(raw, "data", "product", "fulfillment") or {}
    store_options = ful.get("store_options") or []
    pickup = []
    for opt in store_options:
        pickup.append(
            {
                "store_id": opt.get("location_id"),
                "store": opt.get("location_name") or _dig(opt, "store", "location_name"),
                "pickup": _dig(opt, "order_pickup", "availability_status"),
                "quantity": opt.get("location_available_to_promise_quantity"),
            }
        )
    shipping = ful.get("shipping_options") or {}
    record = {
        "id": tcin,
        "sold_out": ful.get("sold_out"),
        "out_of_stock_all_stores": ful.get("is_out_of_stock_in_all_store_locations"),
        "shipping": shipping.get("availability_status"),
        "shipping_quantity": shipping.get("available_to_promise_quantity"),
        "pickup": pickup,
        # Pre-launch ("coming soon") signals. ``notify_me_eligible`` is a SIBLING
        # of ``fulfillment`` under data.product, not inside it. ``future_selling_intent``
        # is present only for future/pre-launch items -- a normal in-stock item has
        # neither key at all, so both dates normalize to None via _dig rather than
        # raising. Verified live for TCIN 94962117 (LoveShackFancy x Target x Yoobi,
        # street-dated 2026-07-05): notify_me_eligible=true, both dates populated.
        "notify_me_eligible": _dig(raw, "data", "product", "notify_me_eligible"),
        "available_online_date": _dig(ful, "future_selling_intent", "event_online_date_and_time"),
        "available_instore_date": _dig(ful, "future_selling_intent", "event_in_store_date_and_time"),
        "pre_order_quantity": _pre_order_quantity(store_options),
    }
    record["orderable"] = is_orderable(record)
    return record


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


def normalize_favorites(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return favorite item records from a favorites/v1/list_items body.

    The favorites API stores only membership (TCIN + timestamps + note); it
    carries no product title or price, so each record here is the raw favorite
    reference. ``client.list_favorites`` hydrates ``tcin`` into title/price via
    redsky. ``tcin`` is read directly so a contract break fails loudly; the
    per-item ``item_note`` is genuinely optional (Target omits it or returns the
    literal string ``"None"``) and normalizes to ``None``.

    ``list_item_id`` is the per-item membership id (a UUID) that Target's remove
    endpoint (``DELETE /favorites/v1/list_items/{list_item_id}``) requires, so
    ``client.remove_favorite`` resolves a TCIN to it. It is an internal key: the
    `list`/`get` command output does not render it, but it is carried on the
    normalized record so remove can look it up.
    """
    rows: List[Dict[str, Any]] = []
    for item in raw.get("list_items") or []:
        note = item.get("item_note")
        if note == "None":
            note = None
        rows.append(
            {
                "tcin": item["tcin"],
                "list_item_id": item.get("list_item_id"),
                "added": item.get("added_ts"),
                "note": note,
            }
        )
    return rows


def normalize_store(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Return a single store record from a store_location_v1 body."""
    store = _dig(raw, "data", "store") or {}
    if not store.get("store_id"):
        return {}
    return _store_row(store)
