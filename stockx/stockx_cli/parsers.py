"""Normalize StockX GraphQL records into the documented command output.

StockX's own field set is returned verbatim — nothing is dropped, so the CLI
stays useful as the schema grows. The additions are the ``url`` convenience
key, plus the identity promotion described below.

Browse returns two node types
-----------------------------
``browse.results.edges[].node`` is a union. Most nodes are ``Product``, but
StockX also returns ``Variant`` nodes — one specific size of a product, with
its own ``market`` and ``sizeChart`` (verified live: a `lego` search returned
40 ``Product`` nodes and 4 ``Variant`` nodes on one page). A ``Variant`` carries
no top-level ``urlKey``, ``title``, or ``brand``; those live on its nested
``product``.

So that one result set has one shape, a ``Variant`` row promotes its nested
product's catalog fields to the top level and keeps its own variant id under
``variantId``. Its ``market``, ``sizeChart``, and the full nested ``product``
are preserved, so no size-level data is lost. ``__typename`` stays on every row,
so a caller can still tell the two apart.
"""

from typing import Callable, Dict, List

# Catalog fields a Variant row borrows from its nested product, so every browse
# row exposes the same primary columns.
_IDENTITY_FIELDS = (
    "id",
    "urlKey",
    "title",
    "name",
    "brand",
    "gender",
    "model",
    "condition",
    "description",
    "productCategory",
    "browseVerticals",
    "listingType",
    "media",
    "traits",
)


def _with_url(record: Dict, product_url: Callable[[str], str]) -> Dict:
    """Return ``record`` plus the canonical stockx.com ``url``."""
    url_key = record.get("urlKey")
    if not url_key:
        raise ValueError(f"StockX record is missing urlKey: {sorted(record)}")
    normalized = dict(record)
    normalized["url"] = product_url(url_key)
    return normalized


def _normalize_node(node: Dict, product_url: Callable[[str], str]) -> Dict:
    """Normalize one ``browse`` union node into a single row shape."""
    typename = node.get("__typename")
    if typename == "Product":
        return _with_url(node, product_url)
    if typename == "Variant":
        product = node.get("product")
        if not product:
            raise ValueError(
                f"StockX Variant node has no nested product: {sorted(node)}"
            )
        row = dict(node)
        row["variantId"] = node.get("id")
        for field in _IDENTITY_FIELDS:
            if field in product:
                row[field] = product[field]
        return _with_url(row, product_url)
    raise ValueError(
        f"Unsupported StockX browse node type {typename!r}: {sorted(node)}"
    )


def normalize_products(
    products: List[Dict], product_url: Callable[[str], str]
) -> List[Dict]:
    """Normalize browse nodes for `products search` / `products list`."""
    return [_normalize_node(node, product_url) for node in products]


def normalize_product(product: Dict, product_url: Callable[[str], str]) -> Dict:
    """Normalize one catalog record for `products get`."""
    return _with_url(product, product_url)


def normalize_market(product: Dict, product_url: Callable[[str], str]) -> Dict:
    """Normalize one market-data record for `products market`."""
    return _with_url(product, product_url)
