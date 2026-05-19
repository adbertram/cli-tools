"""Confirmation-code error types and legacy pending-flag cleanup helpers."""
import json
from pathlib import Path

from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.auth import BrowserAutomationError

activity = get_activity_logger("bricklink")


class ConfirmationRequiredError(BrowserAutomationError):
    """Raised when Bricklink requires email confirmation for an operation."""

    def __init__(self, operation: str, order_id: str = None):
        self.operation = operation
        self.order_id = order_id
        if operation == "this operation":
            msg = "BrickLink requires an email confirmation code. Check your email and retry."
        else:
            msg = (
                f"BrickLink requires an email confirmation code for {operation}. "
                "Check your email and retry."
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
