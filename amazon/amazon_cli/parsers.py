"""Parse DOM data extracted from Amazon pages.

With BrowserAutomation (cli_tools_shared) backed by browser-harness, the
preferred extraction pattern is to run JavaScript via the browser page
(``page.evaluate(...)``) and return structured data directly, rather than
parsing accessibility-tree snapshots.

This module provides helpers to normalize raw data into dict records that
match the documented command output.
"""
from typing import Any, Dict, List, Optional


def normalize_items(raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize raw item dicts returned from page.evaluate().

    TODO: Map raw DOM fields into the public command record shape.
    """
    return raw_items


def normalize_item_detail(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a raw item-detail dict into the public command record shape."""
    return raw
