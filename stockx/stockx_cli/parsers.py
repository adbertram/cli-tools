"""Normalize StockX GraphQL records into the documented command output.

StockX's own field set is returned verbatim — nothing is dropped, so the CLI
stays useful as the schema grows. The only addition is the ``url`` convenience
key: every browse, product, and market record carries ``urlKey``, but StockX
never returns the canonical product URL built from it.
"""

from typing import Callable, Dict, List


def _with_url(record: Dict, product_url: Callable[[str], str]) -> Dict:
    """Return ``record`` plus the canonical stockx.com ``url``."""
    url_key = record.get("urlKey")
    if not url_key:
        raise ValueError(f"StockX record is missing urlKey: {sorted(record)}")
    normalized = dict(record)
    normalized["url"] = product_url(url_key)
    return normalized


def normalize_products(
    products: List[Dict], product_url: Callable[[str], str]
) -> List[Dict]:
    """Normalize browse product nodes for `products search` / `products list`."""
    return [_with_url(product, product_url) for product in products]


def normalize_product(product: Dict, product_url: Callable[[str], str]) -> Dict:
    """Normalize one catalog record for `products get`."""
    return _with_url(product, product_url)


def normalize_market(product: Dict, product_url: Callable[[str], str]) -> Dict:
    """Normalize one market-data record for `products market`."""
    return _with_url(product, product_url)
