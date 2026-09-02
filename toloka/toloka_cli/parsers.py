"""Parse DOM data extracted from Toloka pages.

With BrowserAutomation (cli_tools_shared) backed by browser-harness, the
preferred extraction pattern is to run JavaScript via the browser page
(``page.evaluate(...)``) and return structured data directly, rather than
parsing accessibility-tree snapshots.

This module provides helpers to normalize raw data into dict records that
match the documented `tasks list` / `tasks get` command output.

STATUS (2026-09-02): https://www.toloka.site was unreachable (Cloudflare
Tunnel error 1033 / HTTP 530) throughout this CLI's development, so no real
task-list or task-detail DOM was ever observed. These functions are
pass-through placeholders -- do not fill in field mappings from guesswork.
Capture a real page.evaluate() snapshot once the site recovers, inspect the
actual field names, and only then implement the mapping below.
"""
from typing import Any, Dict, List


def normalize_tasks(raw_tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize raw task dicts returned from page.evaluate() into the
    public `tasks list` record shape.

    TODO: Map raw DOM fields into the documented shape (id, title, payout,
    status, ...) once a real dashboard/task-list capture is available.
    """
    return raw_tasks


def normalize_task(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a raw task-detail dict into the public `tasks get` record
    shape.

    TODO: Map raw DOM fields once a real task-detail page capture is
    available.
    """
    return raw
