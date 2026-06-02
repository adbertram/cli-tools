"""AppleScript utilities for macOS Accessibility permission detection.

Provides functions to check if cliclick has the required Accessibility
permissions in macOS System Settings.
"""
import subprocess
from typing import Optional


class AppleScriptError(Exception):
    """Error executing AppleScript."""

    pass


def run_applescript(script: str, timeout: int = 30) -> str:
    """Execute an AppleScript and return the output.

    Args:
        script: AppleScript code to execute
        timeout: Maximum execution time in seconds

    Returns:
        stdout from the script execution

    Raises:
        AppleScriptError: If script fails to execute
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            error_msg = result.stderr.strip() or "Unknown AppleScript error"
            raise AppleScriptError(error_msg)
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise AppleScriptError(f"AppleScript timed out after {timeout}s")
    except FileNotFoundError:
        raise AppleScriptError("osascript not found - not running on macOS?")


def check_accessibility_permissions() -> bool:
    """Check if current process has Accessibility permissions.

    Uses AppleScript to query System Events, which requires Accessibility
    permissions. If the query succeeds, permissions are granted.

    Returns:
        True if Accessibility permissions are granted, False otherwise
    """
    # This script tries to interact with System Events
    # If permissions are not granted, it will fail
    script = '''
        tell application "System Events"
            try
                set processCount to count of processes
                return "true"
            on error
                return "false"
            end try
        end tell
    '''
    try:
        result = run_applescript(script)
        return result.lower() == "true"
    except AppleScriptError:
        return False


def get_accessibility_instructions() -> str:
    """Get instructions for enabling Accessibility permissions.

    Returns:
        Human-readable instructions for granting permissions
    """
    return (
        "Accessibility permissions required.\n"
        "Grant permission in: System Settings > Privacy & Security > Accessibility\n"
        "Add your terminal application (Terminal, iTerm, etc.) to the allowed list."
    )


def test_cliclick_permissions(cliclick_path: str = "cliclick") -> bool:
    """Test if cliclick can execute by running a benign command.

    Args:
        cliclick_path: Path to cliclick executable

    Returns:
        True if cliclick executed successfully, False otherwise
    """
    try:
        # Use 'p' command which just prints mouse position
        # This is a read-only operation that requires accessibility
        result = subprocess.run(
            [cliclick_path, "p"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # If we get output and no error, permissions are working
        return result.returncode == 0 and result.stdout.strip() != ""
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def get_terminal_app_name() -> Optional[str]:
    """Get the name of the current terminal application.

    Returns:
        Name of terminal app (e.g., "Terminal", "iTerm2") or None
    """
    script = '''
        tell application "System Events"
            set frontApp to name of first process whose frontmost is true
            return frontApp
        end tell
    '''
    try:
        return run_applescript(script)
    except AppleScriptError:
        return None
