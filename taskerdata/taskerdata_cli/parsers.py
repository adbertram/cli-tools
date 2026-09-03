"""Parse DOM data extracted from TaskerData worker pages.

With BrowserAutomation (cli_tools_shared) backed by browser-harness, the
preferred extraction pattern is to run JavaScript via the browser page
(``page.evaluate(...)``) and return structured data directly, rather than
parsing accessibility-tree snapshots.

STATUS: The task board / task detail DOM has NOT been captured yet — the
saved LastPass credentials for the TaskerData worker account are being
rejected by the live site (`/api/login/signin` returns
`{"success": false, "errors": [{"field": "wrong_credentials", ...}]}`), so no
authenticated page has been reached. Per the cli-tool skill's mandatory
"Browser Parser Validation" principle, these normalizers stay unimplemented
until a real authenticated DOM snapshot can be captured and inspected — no
selector or field name below is guessed.
"""
from typing import Any, Dict, List, Optional


def normalize_tasks(raw_tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize raw task dicts returned from page.evaluate() on the worker
    task board into the public `tasks list` record shape.

    TODO(live-DOM-pending): implement against a real captured DOM snapshot of
    the authenticated worker task board once TaskerData auth is unblocked.
    """
    raise NotImplementedError(
        "normalize_tasks: pending live-DOM capture of the authenticated "
        "worker task board (blocked on TaskerData credential rejection)"
    )


def normalize_task_detail(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a raw task-detail dict into the public `tasks get` record shape.

    TODO(live-DOM-pending): implement against a real captured DOM snapshot of
    the authenticated task detail page once TaskerData auth is unblocked.
    """
    raise NotImplementedError(
        "normalize_task_detail: pending live-DOM capture of the authenticated "
        "task detail page (blocked on TaskerData credential rejection)"
    )
