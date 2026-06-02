"""CJ filter-map configuration.

CJ's advertiser-lookup endpoint accepts a handful of server-side
narrowing parameters (``keywords``, ``advertiser-name``, ``category``,
``advertiser-ids``).  Anything outside that set is applied client-side
by the shared filter machinery.
"""

from typing import Any, Dict

from cli_tools_shared import FilterMap


def _translate_keywords(op: str, val: str) -> Dict[str, Any]:
    """``description:contains:foo`` -> server-side ``keywords=foo``.

    Other operators fall through to client-side filtering.
    """
    if op in ("contains", "eq"):
        return {"keywords": val}
    return {}


def _translate_name(op: str, val: str) -> Dict[str, Any]:
    """``advertiser_name:eq:Foo`` -> server-side ``advertiser-name=Foo``."""
    if op == "eq":
        return {"advertiser-name": val}
    return {}


def _translate_category(op: str, val: str) -> Dict[str, Any]:
    """``primary_category:eq:Software`` -> server-side ``category=Software``."""
    if op == "eq":
        return {"category": val}
    return {}


def _translate_relationship(op: str, val: str) -> Dict[str, Any]:
    """``relationship_status:eq:joined`` -> server-side ``advertiser-ids=joined``."""
    if op == "eq" and val in {"joined", "notjoined"}:
        return {"advertiser-ids": val}
    return {}


cj_filter_map = (
    FilterMap()
    .add_argument_mapping("keywords")
    .add_argument_mapping("advertiser_name")
    .add_argument_mapping("primary_category")
    .add_argument_mapping("relationship_status")
    .register_api_translator("keywords", _translate_keywords)
    .register_api_translator("advertiser_name", _translate_name)
    .register_api_translator("primary_category", _translate_category)
    .register_api_translator("relationship_status", _translate_relationship)
)


# Re-export the base class so command modules can satisfy the
# compliance suite by importing ``FilterMap`` from here.
__all__ = ["FilterMap", "cj_filter_map"]
