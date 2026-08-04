"""Parsers for Vinted catalog records and item pages.

The catalog API returns JSON, so `normalize_listing` only reshapes it.

The item page is a React Server Component page. Its data arrives as JSON string
chunks passed to `self.__next_f.push`, and one chunk can end in the middle of an
object, so the chunks are joined before anything is read out of them. That
payload is the single source for item detail.

An earlier version read the `application/ld+json` Product block instead. Vinted
omits that block on a hidden listing, so `vinted listings get` failed with a
hard error on a page that answered HTTP 200 with a full body. Listing
9573431534 is one such page. The payload carries the same data on every page
sampled, hidden or not, so the ld+json block is no longer read.
"""

import json
from datetime import datetime, timezone
from typing import List, Optional

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.http_session import iter_json_values_at_marker

RSC_PUSH_MARKER = "self.__next_f.push("
RSC_CHUNK_INDEX = 1

# The page renders each section as a named plugin, and every plugin has the
# shape {"name":"<n>","type":"<n>","section":"...","data":{...}}.
PLUGIN_MARKER = '{{"name":"{name}","type":"{name}"'

# The buyer facing shipping summary. Vinted also renders a lower level shipping
# object twice with two different undiscounted prices, so the CLI reads this
# summary instead. It is the same in every render.
SHIPPING_KEY = "shippingDetails"

# The seller's asking price, and that price plus the buyer protection fee.
PRICE_KEY = "originalAskingAmount"
TOTAL_PRICE_KEY = "totalAmount"

# Vinted attribute codes mapped to the field names the CLI reports.
ATTRIBUTE_FIELDS = {"size": "size", "status": "condition", "color": "color"}

# The last breadcrumb repeats the category with the brand in front, and its URL
# names the brand. It is not part of the category path.
BRAND_BREADCRUMB = "/brand/"
CATEGORY_SEPARATOR = " / "

# Fields the item status plugin reports about a listing's availability.
STATUS_FIELDS = ("is_reserved", "is_hidden", "is_closed")


def _rsc_payload(html: str) -> str:
    """Join the React Server Component data chunks of an item page."""
    decoder = json.JSONDecoder()
    chunks = []
    index = 0
    while True:
        start = html.find(RSC_PUSH_MARKER, index)
        if start < 0:
            return "".join(chunks)
        try:
            value, index = decoder.raw_decode(html, start + len(RSC_PUSH_MARKER))
        except ValueError:
            # Not a data push. Step past this marker and keep looking.
            index = start + len(RSC_PUSH_MARKER)
            continue
        if isinstance(value, list) and len(value) > RSC_CHUNK_INDEX:
            chunk = value[RSC_CHUNK_INDEX]
            if isinstance(chunk, str):
                chunks.append(chunk)


def _decode_at(payload: str, marker: str) -> Optional[object]:
    """Return the JSON value that starts at `marker`, or None if it is absent."""
    return next(iter_json_values_at_marker(payload, marker), None)


def _decode_after_key(payload: str, key: str) -> Optional[object]:
    """Return the JSON value that follows `"key":`, or None if it is absent.

    The key marker does not start a value, so this locates the key and then
    decodes at the position after the colon.
    """
    marker = f'"{key}":'
    start = payload.find(marker)
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(payload, start + len(marker))
    except ValueError as exc:
        raise ClientError(
            f"The item page carried an unreadable value for {key}. Vinted "
            "changed the item page structure."
        ) from exc
    return value


def _plugin_data(payload: str, name: str) -> dict:
    """Return the data object of one named item page plugin."""
    plugin = _decode_at(payload, PLUGIN_MARKER.format(name=name))
    if not isinstance(plugin, dict):
        return {}
    data = plugin.get("data")
    return data if isinstance(data, dict) else {}


def _object(raw: dict, key: str) -> dict:
    """Return a nested object field, or an empty one if Vinted changed its type.

    A plain `raw.get(key) or {}` keeps a wrong-typed value, such as a string
    price, and the next `.get()` raises AttributeError.
    """
    value = raw.get(key)
    return value if isinstance(value, dict) else {}


def _list(raw: dict, key: str) -> List:
    """Return a nested list field, or an empty one if Vinted changed its type."""
    value = raw.get(key)
    return value if isinstance(value, list) else []


def _amount(value: object) -> Optional[str]:
    """Return the amount of a Vinted money object."""
    return value.get("amount") if isinstance(value, dict) else None


def _currency(value: object) -> Optional[str]:
    """Return the currency code of a Vinted money object."""
    return value.get("currencyCode") if isinstance(value, dict) else None


def _shipping(payload: str) -> Optional[dict]:
    """Return the shipping figures from an item page payload.

    `price` is what Vinted shows a buyer with no address, so it is an estimate
    and not a checkout quote. Vinted resolves the exact cost at checkout, where
    it knows the delivery method and the address.

    A listing with no shipping summary returns None.
    """
    details = _decode_after_key(payload, SHIPPING_KEY)
    if not isinstance(details, dict):
        return None
    price = details.get("price")
    return {
        "price": _amount(price),
        "currency": _currency(price),
        "discount": _amount(details.get("discount")),
        "free": details.get("isFreeShipping"),
        "pickup_only": details.get("isPickupOnly"),
        "multiple_options": details.get("areMultipleShippingOptionsAvailable"),
    }


def parse_shipping(html: str) -> Optional[dict]:
    """Return the shipping figures an item page carries."""
    return _shipping(_rsc_payload(html))


def _attributes(payload: str) -> dict:
    """Return the item detail attributes, keyed by the CLI field name."""
    fields = {field: None for field in ATTRIBUTE_FIELDS.values()}
    for attribute in _list(_plugin_data(payload, "attributes"), "attributes"):
        if not isinstance(attribute, dict):
            continue
        field = ATTRIBUTE_FIELDS.get(attribute.get("code"))
        if field is not None:
            fields[field] = _object(attribute, "data").get("value")
    return fields


def _category(payload: str) -> Optional[str]:
    """Return the category path, for example `Kids / Toys / Blocks`."""
    titles = [
        crumb["title"]
        for crumb in _list(_plugin_data(payload, "breadcrumbs"), "breadcrumbs")
        if isinstance(crumb, dict)
        and isinstance(crumb.get("title"), str)
        and BRAND_BREADCRUMB not in str(crumb.get("url", ""))
    ]
    return CATEGORY_SEPARATOR.join(titles) if titles else None


def _photo_url(payload: str) -> Optional[str]:
    """Return the main photo URL from the gallery plugin."""
    for photo in _list(_plugin_data(payload, "gallery"), "photos"):
        if isinstance(photo, dict) and isinstance(photo.get("url"), str):
            return photo["url"]
    return None


def _listed_at(photo: dict) -> Optional[str]:
    """Return the listing time as an ISO 8601 UTC string.

    The catalog record carries no created_at. Vinted's `newest_first` order
    follows `photo.high_resolution.timestamp`, a Unix time, so that field is the
    recency signal the CLI reports.
    """
    timestamp = (photo.get("high_resolution") or {}).get("timestamp")
    if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool):
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def normalize_listing(raw: dict) -> dict:
    """Map one catalog API item to the public CLI listing record."""
    if "id" not in raw:
        raise ClientError(
            "Vinted returned a catalog listing with no id. The catalog response "
            "shape changed."
        )
    price = _object(raw, "price")
    total_price = _object(raw, "total_item_price")
    user = _object(raw, "user")
    photo = _object(raw, "photo")
    return {
        "id": raw["id"],
        "title": raw.get("title"),
        "url": raw.get("url"),
        "listed_at": _listed_at(photo),
        "price": price.get("amount"),
        "currency": price.get("currency_code"),
        "total_price": total_price.get("amount"),
        "brand": raw.get("brand_title"),
        "size": raw.get("size_title"),
        "condition": raw.get("status"),
        "favourite_count": raw.get("favourite_count"),
        "view_count": raw.get("view_count"),
        "is_visible": raw.get("is_visible"),
        "promoted": raw.get("promoted"),
        "seller_id": user.get("id"),
        "seller_login": user.get("login"),
        "seller_url": user.get("profile_url"),
        "photo_url": photo.get("url"),
    }


def parse_item_page(html: str, item_id: str, url: str) -> dict:
    """Build the public CLI listing detail record from an item page.

    `item_id` is digits only, because `resolve_item_id` validates it before the
    request, so it is safe inside the marker below.
    """
    payload = _rsc_payload(html)
    item = _decode_at(payload, f'{{"id":{item_id},"title":')
    if not isinstance(item, dict):
        raise ClientError(
            f"Item page for {item_id} carried no item data. Vinted changed the "
            "item page structure."
        )

    price = _decode_after_key(payload, PRICE_KEY)
    status = _plugin_data(payload, "item_status")
    record = {
        "id": item_id,
        "title": item.get("title"),
        "url": url,
        "description": _plugin_data(payload, "description").get("description"),
        "price": _amount(price),
        "currency": _currency(price) or item.get("currency"),
        "total_price": _amount(_decode_after_key(payload, TOTAL_PRICE_KEY)),
        "brand": _object(item, "brand_dto").get("title"),
        "category": _category(payload),
        "catalog_id": item.get("catalog_id"),
        "seller_id": item.get("seller_id"),
    }
    record.update(_attributes(payload))
    record.update({field: status.get(field) for field in STATUS_FIELDS})
    record["shipping"] = _shipping(payload)
    record["photo_url"] = _photo_url(payload)
    return record
