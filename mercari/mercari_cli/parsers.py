"""Normalize Mercari GraphQL responses into public command records.

Field shapes here are validated against real captured responses from the live
authenticated session:
  - `list`  -> data.userItems.items[] from the `userItemsQuery` operation
  - `get`   -> data.item from the `productQuery` operation

The captured item-detail shape (productQuery) uses `itemId`, `name`, `price`,
`status`, `created`, `updated`, `numLikes`, `photos[]`, `seller{}`, etc. We
return the full response object verbatim (no field is dropped) and add two
convenience fields (`id`, `url`) so the CLI's id/url conventions work without
discarding any upstream data.
"""
from typing import Any, Dict, List

ITEM_URL_TEMPLATE = "https://www.mercari.com/us/item/{item_id}/"


def _item_id_of(raw: Dict[str, Any]) -> Any:
    """Return the item id from whichever id field the payload carries.

    Validated: productQuery items use `itemId`; other item payloads may use
    `id`. We read the real key present rather than assuming one.
    """
    for key in ("itemId", "id"):
        if key in raw and raw[key]:
            return raw[key]
    return None


def _with_conveniences(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Return the raw item plus `id`/`url` conveniences (non-destructive)."""
    if not isinstance(raw, dict):
        return raw
    item = dict(raw)
    item_id = _item_id_of(raw)
    if item_id is not None:
        item.setdefault("id", item_id)
        if isinstance(item_id, str) and item_id.startswith("m"):
            item.setdefault("url", ITEM_URL_TEMPLATE.format(item_id=item_id))
    return item


def normalize_items(raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize the userItems.items[] list, preserving every upstream field."""
    return [_with_conveniences(item) for item in raw_items]


def normalize_item_detail(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize item detail and expose exact buyer-cost values in cents."""
    item = _with_conveniences(raw)
    price = item.get("price")
    price_summary = item.get("priceSummary")
    if not isinstance(price, int):
        raise ValueError("Mercari item detail has no integer price in cents")
    if not isinstance(price_summary, dict) or not isinstance(
        price_summary.get("totalPrice"), int
    ):
        raise ValueError(
            "Mercari item detail has no integer priceSummary.totalPrice in cents"
        )

    shipping_fee = 0
    shipping_payer = item.get("shippingPayer")
    if isinstance(shipping_payer, dict) and shipping_payer.get("code") == "buyer":
        shipping_class = item.get("shippingClass")
        if not isinstance(shipping_class, dict) or not isinstance(
            shipping_class.get("fee"), int
        ):
            raise ValueError(
                "Mercari buyer-paid shipping has no integer shippingClass.fee in cents"
            )
        shipping_fee = shipping_class["fee"]

    landed_total = price_summary["totalPrice"]
    buyer_protection_fee = landed_total - price - shipping_fee
    if buyer_protection_fee < 0:
        raise ValueError(
            "Mercari priceSummary.totalPrice is less than price plus buyer shipping"
        )
    item["buyer_protection_fee_cents"] = buyer_protection_fee
    item["landed_total_cents"] = landed_total
    return item
