"""AppleScript utilities for iMessage CLI."""
import subprocess
from typing import Optional


AUTOMATION_PROBE_TIMEOUT = 3


class AppleScriptError(Exception):
    """Error executing AppleScript."""
    pass


class AutomationPermissionError(AppleScriptError):
    """macOS Automation (Apple Events) consent for the target app is not granted.

    Raised when a bounded Apple Events probe against an application either hangs
    until timeout or is denied outright (error -1743, "Not authorized to send
    Apple events"). This is the TCC "Automation" gate under System Settings →
    Privacy & Security → Automation, not Full Disk Access. In a headless /
    launchd / cron context there is no consent UI, so the gated event would
    otherwise block until the osascript timeout.
    """
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


def ensure_app_running(app_name: str, timeout: int = 30) -> None:
    """Ensure a macOS application is running before scripting it.

    Uses the AppleScript `launch` verb, which starts the application in the
    background without activating it or stealing focus (unlike `activate`).
    A `tell application "<app_name>"` block issued while the app isn't running
    fails with "Application isn't running. (-600)"; calling this first avoids
    that failure whether or not the app was already open.

    Args:
        app_name: Name of the application to launch (e.g. "Contacts")
        timeout: Command timeout in seconds

    Raises:
        AppleScriptError: If the launch command itself fails
    """
    escaped_name = escape_applescript_string(app_name)
    run_applescript(f'tell application "{escaped_name}" to launch', timeout=timeout)


def launch_app(app_name: str, timeout: int = 15) -> None:
    """Start a macOS application via LaunchServices, without Apple Events.

    Uses ``open -g -a <app>`` rather than an AppleScript ``tell ... to launch``.
    A LaunchServices launch does NOT depend on Apple Events / Automation (TCC)
    consent, so it cannot hang on the Automation gate the way a ``tell`` event
    can; ``-g`` launches in the background so it does not steal focus. Call this
    before ``probe_automation`` so a cold-start delay isn't misread as a
    permission block.

    Args:
        app_name: Name of the application to launch (e.g. "Messages")
        timeout: Command timeout in seconds

    Raises:
        AppleScriptError: If ``open`` times out, is unavailable, or fails.
    """
    try:
        result = subprocess.run(
            ["open", "-g", "-a", app_name],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise AppleScriptError(f"Launching {app_name} timed out after {timeout}s")
    except FileNotFoundError:
        raise AppleScriptError("open not found - not running on macOS?")
    if result.returncode != 0:
        raise AppleScriptError(result.stderr.strip() or f"Failed to launch {app_name}")


def probe_automation(app_name: str, timeout: int = AUTOMATION_PROBE_TIMEOUT) -> None:
    """Bounded probe of the Automation (Apple Events) gate for an application.

    Sends a cheap ``tell application "<app>" to get name`` Apple Event with a
    short timeout. If Automation consent is missing the event either hangs (and
    ``run_applescript`` raises the timeout ``AppleScriptError``) or is denied
    with -1743; either way this re-raises an ``AutomationPermissionError``.

    Assumes the app is already running (call ``launch_app`` first) so a cold
    launch isn't misread as a block. TCC Automation is per-target-app and
    all-or-nothing, so a passing ``get name`` guarantees the target's other
    Apple Events (e.g. the send's account/service events) are permitted too.

    Args:
        app_name: Name of the application to probe (e.g. "Messages")
        timeout: Probe timeout in seconds

    Raises:
        AutomationPermissionError: If the probe hangs or is denied, meaning
            Automation consent for the app is not granted.
    """
    escaped_name = escape_applescript_string(app_name)
    try:
        run_applescript(f'tell application "{escaped_name}" to get name', timeout=timeout)
    except AppleScriptError as exc:
        raise AutomationPermissionError(
            f"Automation (Apple Events) permission for {app_name} is not granted "
            "(probe timed out or was denied)."
        ) from exc
