"""Normalize order records returned by trainee.digital's JSON API.

trainee.digital serves the worker order feed as JSON, not server-rendered DOM:
the /orders page (and the signed-in worker surface) is painted from
`GET /api/orders`, and `GET /api/orders/<id>` returns one order's detail.
`client.py` reproduces those same calls from inside the authenticated page,
and the raw JSON lands here.

Endpoints and field names were captured live 2026-09-03 from an authenticated
session (see tests/fixtures/ for the exact payloads):

  GET /api/orders          -> [ {id, title, category, pay, unit, volume,
                                 deadline, posted}, ... ]
  GET /api/orders/<id>     -> the list fields plus {totalPay, dataset, scope,
                                 guidelines[], createdAt} (fields the API does
                                 not fill for an order are JSON null).

`url`: every order renders on the /orders listing (the route "Explore orders"
links to on the worker dashboard), so every record points there rather than at
an invented per-order URL.

Anything the API does not return stays ``None`` / absent, exactly as captured.
"""

from typing import Any, Dict, List, Optional

ORDERS_LIST_URL = "https://trainee.digital/orders"


def normalize_order(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one record from ``GET /api/orders`` (or its detail variant).

    All fields the API returned are preserved verbatim; ``url`` is added as
    the one derived field (the page every order is listed on). No field is
    dropped and no value is invented for a missing one.
    """
    if not isinstance(raw, dict):
        raise TypeError(f"Expected an order record dict, got {type(raw).__name__}")
    order = dict(raw)
    order["url"] = ORDERS_LIST_URL
    return order


def normalize_orders(records: Any) -> List[Dict[str, Any]]:
    """Normalize a ``GET /api/orders`` response list, rejecting anything else."""
    if records is None:
        return []
    if not isinstance(records, list):
        raise TypeError(
            f"Expected a list of order records, got {type(records).__name__}"
        )
    return [normalize_order(record) for record in records]


def normalize_order_detail(raw: Any, order_id: Optional[str] = None) -> Dict[str, Any]:
    """Normalize one ``GET /api/orders/<id>`` response body.

    The detail response carries the same ``id`` as the request (captured live
    for med-seg and legal-ner), so ``order_id`` is only a fallback when the
    body does not echo it.
    """
    order = normalize_order(raw)
    if order.get("id") is None and order_id is not None:
        order["id"] = order_id
    return order
