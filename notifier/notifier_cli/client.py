"""Notifier wrapper client using subprocess to call terminal-notifier."""
import shutil
import subprocess
import sys
from typing import List, Optional

from .config import get_config
from .models import AuthStatus, SendResult


class ClientError(Exception):
    """Custom exception for Notifier wrapper errors."""

    pass


class NotifierClient:
    """Wrapper client for terminal-notifier CLI.

    Calls terminal-notifier via subprocess and returns Pydantic models.
    """

    def __init__(self):
        """Initialize Notifier wrapper client."""
        self.config = get_config()
        # Lazy check - don't error on init, let commands fail naturally

    def _run_command(
        self,
        args: List[str],
        input_text: Optional[str] = None,
        timeout: int = 60,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        """Run a command on terminal-notifier.

        Args:
            args: Command arguments (without the CLI command itself)
            input_text: Optional text to pass to stdin
            timeout: Command timeout in seconds
            check: If True, raise ClientError on non-zero exit

        Returns:
            CompletedProcess with stdout, stderr, and returncode

        Raises:
            ClientError: If command fails and check=True
        """
        cmd = [self.config.get_cli_executable()] + args

        try:
            result = subprocess.run(
                cmd,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if check and result.returncode != 0:
                error_msg = (
                    result.stderr.strip() or result.stdout.strip() or "Command failed"
                )
                raise ClientError(f"terminal-notifier error: {error_msg}")

            return result

        except subprocess.TimeoutExpired:
            raise ClientError(f"Command timed out after {timeout} seconds")
        except FileNotFoundError:
            raise ClientError(
                "terminal-notifier not found. Install with: brew install terminal-notifier"
            )
        except Exception as e:
            if isinstance(e, ClientError):
                raise
            raise ClientError(f"Failed to run command: {e}")

    # ==================== Auth Methods ====================

    def auth_login(self, force: bool = False) -> AuthStatus:
        """No-op login - terminal-notifier doesn't require authentication.

        Args:
            force: Ignored, kept for API compatibility

        Returns:
            AuthStatus model
        """
        status = self.auth_status()
        if status.authenticated:
            return AuthStatus(
                authenticated=True,
                terminal_notifier_path=status.terminal_notifier_path,
                version=status.version,
                message="terminal-notifier is ready (no authentication required)",
            )
        return status

    def auth_status(self) -> AuthStatus:
        """Check if terminal-notifier is installed and available.

        Returns:
            AuthStatus model with installation details
        """
        # Check if terminal-notifier is in PATH
        path = shutil.which("terminal-notifier")

        if not path:
            return AuthStatus(
                authenticated=False,
                terminal_notifier_path=None,
                version=None,
                message="terminal-notifier not found. Install with: brew install terminal-notifier",
            )

        # Get version
        version = self.config.get_cli_version()

        return AuthStatus(
            authenticated=True,
            terminal_notifier_path=path,
            version=version,
            message="terminal-notifier is installed and ready",
        )

    # ==================== Notification Methods ====================

    def send_notification(
        self,
        message: Optional[str] = None,
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        sound: Optional[str] = None,
        ignore_dnd: bool = False,
    ) -> SendResult:
        """Send a desktop notification.

        Args:
            message: Notification message (can also come from stdin)
            title: Notification title
            subtitle: Notification subtitle
            sound: Sound name to play (e.g., 'default', 'Basso', 'Blow')
            ignore_dnd: Send even if Do Not Disturb is enabled

        Returns:
            SendResult model
        """
        args = []

        # Check for stdin input if no message provided
        stdin_input = None
        if message:
            args.extend(["-message", message])
        elif not sys.stdin.isatty():
            # Read from stdin
            stdin_input = sys.stdin.read().strip()
            if not stdin_input:
                raise ClientError("No message provided and stdin is empty")
        else:
            raise ClientError(
                "Message is required. Use --message or pipe content to stdin."
            )

        if title:
            args.extend(["-title", title])
        if subtitle:
            args.extend(["-subtitle", subtitle])
        if sound:
            args.extend(["-sound", sound])
        if ignore_dnd:
            args.append("-ignoreDnD")

        try:
            self._run_command(args, input_text=stdin_input)
            return SendResult(
                success=True,
                message="Notification sent",
            )
        except ClientError as e:
            return SendResult(
                success=False,
                message=str(e),
            )


# Module-level client instance - singleton pattern
_client: Optional[NotifierClient] = None


def get_client() -> NotifierClient:
    """Get or create the global Notifier client instance."""
    global _client
    if _client is None:
        _client = NotifierClient()
    return _client
