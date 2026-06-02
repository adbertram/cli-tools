"""AppleScript utilities for iMessage CLI."""
import subprocess
from typing import Optional


class AppleScriptError(Exception):
    """Error executing AppleScript."""
    pass


def run_applescript(script: str, timeout: int = 30) -> str:
    """Execute an AppleScript and return the output.

    Args:
        script: AppleScript code to execute
        timeout: Command timeout in seconds

    Returns:
        Script output (stdout)

    Raises:
        AppleScriptError: If script execution fails
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


def escape_applescript_string(text: str) -> str:
    """Escape a string for safe use in AppleScript.

    Args:
        text: String to escape

    Returns:
        Escaped string safe for AppleScript
    """
    return text.replace("\\", "\\\\").replace('"', '\\"')
