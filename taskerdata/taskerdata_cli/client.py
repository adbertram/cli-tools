"""TaskerData client using BrowserAutomation from cli_tools_shared."""

from typing import List, Optional

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .browser import TaskerdataBrowser
from .config import get_config
from .parsers import normalize_task_detail, normalize_tasks

# Candidate worker task-board URL. Not yet validated against a real
# authenticated DOM snapshot — see parsers.py.
TASK_BOARD_URL = "https://worker.taskerdata.com/"


class TaskerdataClient:
    """Client that uses BrowserAutomation to drive TaskerData."""

    def __init__(self):
        self.config = get_config()
        self._browser: Optional[TaskerdataBrowser] = None

    def _get_browser(self) -> TaskerdataBrowser:
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

        TODO(live-DOM-pending): navigate to TASK_BOARD_URL and extract the
        task-board DOM once TaskerData auth is unblocked — see parsers.py.
        """
        return normalize_tasks([])[:limit]

    @cached
    def get_task(self, task_id: str) -> dict:
        """Get full detail for a specific task."""
        for task in self.list_tasks(limit=1000):
            if str(task.get("id")) == str(task_id):
                return task
        raise ClientError(f"Task not found: {task_id}")

    def apply_task(self, task_id: str, confirm: bool = False) -> dict:
        """Apply to / pick up a task. Default is dry-run (no submission).

        Phase 1 (always): resolve the task via get_task() and build a preview
        of what would be submitted.
        Phase 2 (only when confirm=True): drive the actual browser
        submission flow — NOT YET IMPLEMENTED pending live DOM capture.
        """
        task = self.get_task(task_id)
        result = {
            "task_id": task_id,
            "confirm": confirm,
            "submitted": False,
            "preview": task,
        }
        if not confirm:
            return result

        raise NotImplementedError(
            "apply_task confirm=True: the live task-submission flow has not "
            "been implemented or validated against a real authenticated DOM "
            "snapshot yet (blocked on TaskerData credential rejection). "
            "Re-run without --confirm for a dry-run preview."
        )


_client: Optional[TaskerdataClient] = None


def get_client() -> TaskerdataClient:
    """Get or create the global TaskerData client instance."""
    global _client
    if _client is None:
        _client = TaskerdataClient()
    return _client
