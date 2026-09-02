"""Toloka client using BrowserAutomation from cli_tools_shared."""

from pathlib import Path
from typing import List, Optional

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .browser import TolokaBrowser
from .config import get_config

# https://www.toloka.site was completely unreachable during this CLI's
# development (Cloudflare Tunnel error 1033 / HTTP 530 on every request,
# including /login) -- confirmed by repeated live checks, not assumed. No
# real DOM was ever observable, so list_tasks/get_task cannot be implemented
# without guessing selectors, which the cli-tool skill's "Browser Parser
# Validation" principle forbids. Fail loudly and explain why instead of
# fabricating task data.
_LIVE_DOM_BLOCKER = (
    "Task data parsing is not implemented: https://www.toloka.site was "
    "unreachable (Cloudflare Tunnel error 1033 / HTTP 530) during CLI "
    "development, so no real dashboard/task-list page could be captured to "
    "validate a parser against. Retry once the site recovers; if it works, "
    "implement TolokaClient.list_tasks/get_task in client.py using a real "
    "page.evaluate() capture, per the cli-tool skill's Browser Parser "
    "Validation principle."
)


class TolokaClient:
    """Client that uses BrowserAutomation to drive Toloka."""

    def __init__(self):
        self.config = get_config()
        self._browser: Optional[TolokaBrowser] = None

    def _get_browser(self) -> TolokaBrowser:
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    @cached
    def list_tasks(self, limit: int = 100) -> List[dict]:
        """List open/available tasks for the logged-in worker.

        TODO: capture the real dashboard/task-list DOM via
        ``self._get_browser().get_page(...)`` + ``page.evaluate(...)`` once
        https://www.toloka.site is reachable, then normalize it with
        ``normalize_tasks`` from parsers.py.
        """
        raise ClientError(_LIVE_DOM_BLOCKER)

    @cached
    def get_task(self, task_id: str) -> dict:
        """Get full detail for a specific task.

        TODO: capture the real task-detail page DOM once
        https://www.toloka.site is reachable, then normalize it with
        ``normalize_task`` from parsers.py.
        """
        raise ClientError(_LIVE_DOM_BLOCKER)

    def apply_task(
        self,
        task_id: str,
        confirm: bool = False,
        debug_dir: Optional[Path] = None,
        log=None,
    ) -> dict:
        """Apply to a task. DRY-RUN by default: never submits without --confirm.

        The dry-run branch reports intent only and never opens a browser or
        touches the live site, so it works (and is safe to run) even while
        the site itself is down. The confirm branch is intentionally
        unimplemented: the real submit-flow DOM (form fields, confirmation
        dialog, success state) could not be captured or validated because
        toloka.site was unreachable during development -- guessing that flow
        would risk an unverified live mutation, which is forbidden.
        """
        if not confirm:
            return {
                "task_id": task_id,
                "confirm": False,
                "would_submit": True,
                "submitted": False,
                "message": (
                    f"DRY RUN: would submit an application for task {task_id} "
                    "using the saved browser session. No request was sent to "
                    "toloka.site. Pass --confirm to actually apply."
                ),
            }
        raise ClientError(
            "Live task application submission is not implemented: the real "
            "submit-flow DOM for toloka.site could not be captured or "
            "validated because the site was unreachable (Cloudflare Tunnel "
            "error 1033 / HTTP 530) during CLI development. Capture and "
            "validate the real flow once the site recovers, then implement "
            "it in TolokaClient.apply_task -- do not guess selectors."
        )


_client: Optional[TolokaClient] = None


def get_client() -> TolokaClient:
    """Get or create the global Toloka client instance."""
    global _client
    if _client is None:
        _client = TolokaClient()
    return _client
