"""Confirmation-code helpers and legacy pending-flag cleanup."""
import json
import re
from pathlib import Path

from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.auth import BrowserAutomationError

activity = get_activity_logger("bricklink")

CONFIRMATION_CODE_URL_PATTERN = re.compile(
    r"/v3(?:/user)?/confirmation_code_required\.page",
    re.IGNORECASE,
)


def is_confirmation_code_page_url(url: str) -> bool:
    """Return True when a BrickLink URL is the email confirmation-code page."""
    if not url:
        return False
    return bool(CONFIRMATION_CODE_URL_PATTERN.search(url))


class ConfirmationRequiredError(BrowserAutomationError):
    """Raised when Bricklink requires email confirmation for an operation."""

    def __init__(self, operation: str, order_id: str = None):
        self.operation = operation
        self.order_id = order_id
        if operation == "this operation":
            msg = (
                "The BrickLink confirmation code page has come up. "
                "Please check your email for the confirmation code and provide it."
            )
        else:
            msg = (
                f"The BrickLink confirmation code page has come up for {operation}. "
                "Please check your email for the confirmation code and provide it."
            )
        super().__init__(msg)


class ConfirmationState:
    """Reads and clears the legacy pending-confirmation flag file.

    Current browser commands fail immediately when BrickLink redirects to
    ``confirmation_code_required``. Older builds wrote a local flag file and
    exposed ``bricklink auth confirm`` as a cleanup step. That command remains
    for backward compatibility, so this helper only needs read/clear behavior.
    """

    def __init__(self, browser_data_dir: Path):
        self._flag_path = Path(browser_data_dir) / "pending_confirmation.json"

    def is_pending(self) -> bool:
        """Check if a confirmation is pending."""
        return self._flag_path.exists()

    def get(self) -> dict | None:
        """Get pending confirmation details, or None if not pending."""
        if not self._flag_path.exists():
            return None
        return json.loads(self._flag_path.read_text())

    def clear(self) -> None:
        """Clear the pending confirmation flag."""
        if self._flag_path.exists():
            activity.info("Confirmation flag cleared")
            self._flag_path.unlink()
