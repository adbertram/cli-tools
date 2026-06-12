"""Descript app automation for composition export via CDP and AppleScript.

Exports full compositions (with slides, edits, etc.) by automating the
Descript desktop app. Requires Descript to be running with CDP on port 9222.
"""
import http.client
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

import websocket

from .client import ClientError
from cli_tools_shared.output import print_info, print_error

CDP_PORT = 9222
DESCRIPT_BASE_URL = "https://web.descript.com"
PROJECT_OPEN_TIMEOUT_SECONDS = 60
SAVE_DIALOG_TIMEOUT_SECONDS = 300
EXPORT_COMPLETE_TIMEOUT_SECONDS = 1800
EXPORT_STABLE_TIMEOUT_SECONDS = 300
MIN_EXPORT_BYTES = 1024


def _cdp_preflight_instructions() -> str:
    """Return the deterministic Descript CDP preflight commands."""
    return (
        "Run this preflight before composition export:\n"
        "  osascript -e 'tell application \"Descript\" to quit'\n"
        "  while pgrep -x Descript >/dev/null; do sleep 1; done\n"
        "  open -na \"Descript\" --args --remote-debugging-port=9222\n"
        "  python3 - <<'PY'\n"
        "import http.client, time\n"
        "deadline = time.time() + 30\n"
        "while time.time() < deadline:\n"
        "    try:\n"
        "        conn = http.client.HTTPConnection('127.0.0.1', 9222, timeout=2)\n"
        "        conn.request('GET', '/json/version')\n"
        "        response = conn.getresponse()\n"
        "        body = response.read().decode()\n"
        "        conn.close()\n"
        "        if response.status == 200:\n"
        "            print(body)\n"
        "            raise SystemExit(0)\n"
        "    except OSError:\n"
        "        pass\n"
        "    time.sleep(1)\n"
        "raise SystemExit('Descript CDP did not respond on 127.0.0.1:9222')\n"
        "PY\n"
        "Then rerun the export; the CLI auto-opens the target project via its descript:// deep link."
    )


def _get_cdp_targets() -> list[dict]:
    """Get CDP targets from Descript app."""
    try:
        conn = http.client.HTTPConnection("127.0.0.1", CDP_PORT, timeout=5)
        conn.request("GET", "/json")
        response = conn.getresponse()
        targets = json.loads(response.read().decode())
        conn.close()
        return targets
    except Exception as exc:
        raise ClientError(
            "Cannot connect to Descript CDP at http://127.0.0.1:9222/json/version.\n"
            f"{_cdp_preflight_instructions()}"
        ) from exc


def _get_project_page_ws(project_id: str) -> str:
    """Get WebSocket URL for the project page target."""
    targets = _get_cdp_targets()
    for t in targets:
        if t.get("type") == "page" and project_id in t.get("url", ""):
            ws_url = t.get("webSocketDebuggerUrl")
            if ws_url:
                return ws_url
    return ""


def _connect_cdp(ws_url: str, timeout: int):
    """Connect to a CDP websocket without sending an Origin header."""
    return websocket.create_connection(
        ws_url,
        timeout=timeout,
        suppress_origin=True,
    )


def _send_cdp_message(ws, msg_id: int, method: str, params: Optional[dict] = None) -> dict:
    """Send a CDP message and return the decoded response."""
    message = {"id": msg_id, "method": method}
    if params is not None:
        message["params"] = params
    ws.send(json.dumps(message))
    return json.loads(ws.recv())


def get_visible_compositions() -> list[dict]:
    """Return Descript composition pages currently visible through CDP."""
    records = []
    pattern = re.compile(r"web\.descript\.com/([0-9a-f-]{36})/([0-9a-f]{5})")
    for target in _get_cdp_targets():
        if target.get("type") != "page":
            continue
        url = target.get("url", "")
        match = pattern.search(url)
        if not match:
            continue
        ws_url = target.get("webSocketDebuggerUrl")
        if not ws_url:
            continue
        ws = _connect_cdp(ws_url, timeout=15)
        try:
            result = _send_cdp_message(ws, 1, "Runtime.evaluate", {
                "expression": """
(function(){
  const el = document.querySelector('[data-testid="composition-popover-trigger"]');
  return {
    visible_name: el ? (el.innerText || el.textContent || '').trim() : '',
    title: document.title,
    url: location.href
  };
})()
""",
                "returnByValue": True,
            })
            value = result.get("result", {}).get("result", {}).get("value") or {}
            value["project_id"] = match.group(1)
            value["composition_prefix"] = match.group(2)
            records.append(value)
        finally:
            ws.close()
    return records


def _find_dom_node(root: dict, testid: str) -> Optional[dict]:
    """Recursively find a DOM node by data-testid."""
    attrs = root.get("attributes", [])
    for i in range(0, len(attrs), 2):
        if attrs[i] == "data-testid" and attrs[i + 1] == testid:
            return root
    for child in root.get("children", []):
        result = _find_dom_node(child, testid)
        if result:
            return result
    return None



def _cdp_get_dom(ws) -> dict:
    """Get full DOM document."""
    msg_id = int(time.time() * 1000) % 100000
    _send_cdp_message(ws, msg_id, "DOM.enable")
    result = _send_cdp_message(ws, msg_id + 1, "DOM.getDocument", {"depth": -1})
    return result.get("result", {}).get("root", {})


def _run_applescript(script: str) -> str:
    """Run AppleScript and return output."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise ClientError(f"AppleScript error: {result.stderr.strip()}")
    return result.stdout.strip()


# AppleScript source for save-dialog diagnostics. Must contain no
# backslash-escaped quotes: intermediate quoting layers (shells, SSH) can
# strip the backslashes and turn the script into a -2741 syntax error.
# Use the AppleScript `quote` constant for embedded quotes instead.
_DIALOG_STATE_SCRIPT = '''
        on joinList(theList, delimiter)
            set AppleScript's text item delimiters to delimiter
            set joinedText to theList as text
            set AppleScript's text item delimiters to ""
            return joinedText
        end joinList

        tell application "System Events"
            if not (exists process "Descript") then
                return "Descript process not found"
            end if
            tell process "Descript"
                set windowSummaries to {}
                repeat with windowIndex from 1 to count of windows
                    set candidateWindow to window windowIndex
                    set sheetCount to count of sheets of candidateWindow
                    if sheetCount > 0 then
                        set sheetSummaries to {}
                        repeat with sheetIndex from 1 to sheetCount
                            set candidateSheet to sheet sheetIndex of candidateWindow
                            set textFieldNames to {}
                            repeat with candidateField in text fields of candidateSheet
                                try
                                    set fieldName to name of candidateField as text
                                on error
                                    set fieldName to "missing value"
                                end try
                                if fieldName is "" then set fieldName to "missing value"
                                set end of textFieldNames to fieldName
                            end repeat
                            set buttonNames to {}
                            repeat with candidateButton in buttons of candidateSheet
                                try
                                    set buttonName to name of candidateButton as text
                                on error
                                    set buttonName to "missing value"
                                end try
                                if buttonName is "" then set buttonName to "missing value"
                                set end of buttonNames to buttonName
                            end repeat
                            set end of sheetSummaries to "sheet " & sheetIndex & " text fields [" & my joinList(textFieldNames, ", ") & "] buttons [" & my joinList(buttonNames, ", ") & "]"
                        end repeat
                        set windowName to name of candidateWindow as text
                        set end of windowSummaries to "window " & windowIndex & " " & quote & windowName & quote & ": " & my joinList(sheetSummaries, "; ")
                    end if
                end repeat
                if (count of windowSummaries) = 0 then
                    return "no Descript sheets found across " & (count of windows as text) & " windows"
                end if
                return my joinList(windowSummaries, " | ")
            end tell
        end tell
    '''


def _describe_descript_dialog_state() -> str:
    """Describe native Descript sheets for timeout diagnostics."""
    return _run_applescript(_DIALOG_STATE_SCRIPT)


def _assert_assistive_access() -> None:
    """Fail fast when the calling process lacks macOS assistive access.

    Counting windows of the Descript process is a UI-element query that
    System Events rejects with -25211 when the responsible host app has no
    Accessibility grant. Run this only after Descript is proven running
    (CDP reachable), so a probe failure means missing assistive access,
    not a missing process. This prevents triggering an export that would
    otherwise spin for the full save-dialog timeout before failing.
    """
    try:
        _run_applescript(
            'tell application "System Events" to count windows of process "Descript"'
        )
    except ClientError as exc:
        raise ClientError(
            "The process running this CLI lacks macOS assistive (Accessibility) access, "
            "which composition export needs to drive Descript's native save dialog.\n"
            "Grant access in System Settings > Privacy & Security > Accessibility to the "
            "responsible host app — TCC attributes the grant to the app that launched this "
            "process (e.g. /Applications/Claude.app when run from Claude, or Terminal/iTerm "
            "for shells) — then retry the export.\n"
            f"Probe error: {exc}"
        ) from exc


def _find_save_dialog_window_index(timeout: int = SAVE_DIALOG_TIMEOUT_SECONDS) -> int:
    """Find the Descript window with the native save sheet attached."""
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            window_index = _run_applescript('''
                tell application "System Events"
                    tell process "Descript"
                        repeat with windowIndex from 1 to count of windows
                            set candidateWindow to window windowIndex
                            if (count of sheets of candidateWindow) > 0 then
                                set candidateSheet to sheet 1 of candidateWindow
                                if exists text field "Save As:" of candidateSheet then
                                    return windowIndex as text
                                end if
                            end if
                        end repeat
                    end tell
                end tell
                return ""
            ''')
            if window_index:
                return int(window_index)
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.5)

    details = ""
    try:
        details = _describe_descript_dialog_state()
    except Exception as exc:
        details = f"could not inspect Descript dialog state: {exc}"

    message = f"Save dialog did not appear within {timeout} seconds.\n{details}"
    if last_error:
        message = f"{message}\nLast AppleScript probe error: {last_error}"
    raise ClientError(message)


def _count_descript_sheets() -> int:
    """Count native sheets attached to Descript windows."""
    count = _run_applescript('''
        tell application "System Events"
            tell process "Descript"
                set sheetCount to 0
                repeat with windowIndex from 1 to count of windows
                    set sheetCount to sheetCount + (count of sheets of window windowIndex)
                end repeat
                return sheetCount as text
            end tell
        end tell
    ''')
    return int(count)


def _ensure_project_open(project_id: str, timeout: int = PROJECT_OPEN_TIMEOUT_SECONDS) -> str:
    """Return the project page WebSocket URL, auto-opening the project if needed.

    If the project page is not visible through CDP, opens the project via the
    Descript desktop app's `descript://project/<id>` deep link, then polls CDP
    until the project page appears. Raises ClientError if it never appears.
    """
    ws_url = _get_project_page_ws(project_id)
    if ws_url:
        return ws_url

    deep_link = f"descript://project/{project_id}"
    print_info(f"Project {project_id} is not open in Descript. Opening {deep_link}...")
    result = subprocess.run(
        ["open", deep_link],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise ClientError(
            f"Failed to open Descript deep link {deep_link}: {result.stderr.strip()}"
        )

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(2)
        ws_url = _get_project_page_ws(project_id)
        if ws_url:
            return ws_url

    raise ClientError(
        f"Project {project_id} did not appear in Descript within {timeout} seconds "
        f"after opening {deep_link}. Open the project in Descript manually, then retry."
    )


def navigate_to_composition(project_id: str, composition_id: str) -> None:
    """Navigate Descript to a specific composition.

    Auto-opens the project via its descript:// deep link if it is not already
    open, then opens the composition URL in the Descript app via CDP navigation.
    Waits for the page to fully load before returning.
    """
    url = f"{DESCRIPT_BASE_URL}/{project_id}/{composition_id[:5]}?editorVariant=default"

    ws_url = _ensure_project_open(project_id)

    # Navigate via CDP
    ws = _connect_cdp(ws_url, timeout=15)
    try:
        _send_cdp_message(ws, 1, "Page.navigate", {"url": url})
    finally:
        ws.close()

    # Wait for page to load by polling for the export trigger button in the DOM
    for attempt in range(20):
        time.sleep(1)
        try:
            new_ws_url = _get_project_page_ws(project_id)
            if not new_ws_url:
                continue
            ws = _connect_cdp(new_ws_url, timeout=10)
            try:
                root = _cdp_get_dom(ws)
                if _find_dom_node(root, "export-popover-trigger"):
                    return  # Page fully loaded
            finally:
                ws.close()
        except Exception:
            continue

    raise ClientError("Page did not load after navigation (20s timeout)")


def _trigger_local_export(project_id: str) -> None:
    """Trigger local export via AppleScript menu + CDP button click.

    1. Activates Descript
    2. File > Export (Local) to open panel
    3. CDP click on the Export button
    """
    ws_url = _get_project_page_ws(project_id)
    if not ws_url:
        raise ClientError("Lost connection to Descript")

    ws = _connect_cdp(ws_url, timeout=15)
    try:
        # Runtime.evaluate .click() works but return values are unreliable
        # in this Electron context. So: click once, wait, click export.
        msg_id = int(time.time() * 1000) % 100000

        # Step 1: Open export panel (click trigger once)
        print_info("Opening export panel...")
        _send_cdp_message(ws, msg_id, "Runtime.evaluate", {
            "expression": '(function(){ var el = document.querySelector(\'[data-testid="export-popover-trigger"]\'); if(el) el.click(); })()',
        })
        time.sleep(3)

        # Step 2: Set destination to Local export
        # Click the destination dropdown, then select Local export
        print_info("Setting Local export destination...")
        _send_cdp_message(ws, msg_id + 1, "Runtime.evaluate", {
            "expression": """(function(){
                    var dest = document.querySelector('[data-testid="export-destination-select"]');
                    if (dest && dest.textContent.indexOf('Local export') === -1) {
                        var btn = dest.querySelector('button');
                        if (btn) btn.click();
                    }
                })()""",
        })
        time.sleep(1)

        _send_cdp_message(ws, msg_id + 2, "Runtime.evaluate", {
            "expression": '(function(){ var el = document.querySelector(\'[data-testid="export-destination-select-option-Local export"]\'); if(el) el.click(); })()',
        })
        time.sleep(1)

        # Step 3: Click the Export button with full mouse event simulation
        print_info("Clicking Export button...")
        result = _send_cdp_message(ws, msg_id + 3, "Runtime.evaluate", {
            "expression": """
(function(){
  const el = document.querySelector('[data-testid="export-button"]');
  if (!el) return null;
  const rect = el.getBoundingClientRect();
  return {
    x: rect.x + rect.width / 2,
    y: rect.y + rect.height / 2,
    disabled: !!el.disabled,
    text: el.innerText
  };
})()
""",
            "returnByValue": True,
        })
        button = result.get("result", {}).get("result", {}).get("value")
        if not button:
            raise ClientError("Export button was not found")
        if button.get("disabled"):
            raise ClientError("Export button was disabled")
        for offset, event_type in enumerate(["mouseMoved", "mousePressed", "mouseReleased"], start=4):
            params = {
                "type": event_type,
                "x": button["x"],
                "y": button["y"],
                "button": "left",
                "clickCount": 1,
            }
            if event_type == "mousePressed":
                params["buttons"] = 1
            _send_cdp_message(ws, msg_id + offset, "Input.dispatchMouseEvent", params)
    finally:
        ws.close()


def _handle_save_dialog(output_path: Path, _window_title: str) -> None:
    """Handle the native macOS save dialog via AppleScript.

    Sets the filename and navigates to the output directory.
    """
    output_dir = str(output_path.parent)
    filename = output_path.name

    # Activate Descript to ensure save dialog is visible
    _run_applescript('tell application "Descript" to activate')

    window_index = _find_save_dialog_window_index()

    # Set the filename
    _run_applescript(f'''
        tell application "System Events"
            tell process "Descript"
                set s to sheet 1 of window {window_index}
                set value of text field "Save As:" of s to "{filename}"
            end tell
        end tell
    ''')

    time.sleep(0.3)

    # Navigate to the output directory via Cmd+Shift+G
    _run_applescript('''
        tell application "System Events"
            tell process "Descript"
                keystroke "g" using {command down, shift down}
            end tell
        end tell
    ''')
    time.sleep(0.5)

    _run_applescript(f'''
        tell application "System Events"
            tell process "Descript"
                keystroke "{output_dir}"
                delay 0.3
                keystroke return
            end tell
        end tell
    ''')
    time.sleep(1)

    # Click Save
    _run_applescript(f'''
        tell application "System Events"
            tell process "Descript"
                set s to sheet 1 of window {window_index}
                click button "Save" of s
            end tell
        end tell
    ''')
    time.sleep(0.5)

    # Handle "Replace" dialog if file exists
    try:
        result = _run_applescript(f'''
            tell application "System Events"
                tell process "Descript"
                    set s to sheet 1 of window {window_index}
                    set innerSheet to sheet 1 of s
                    click button "Replace" of innerSheet
                    return "replaced"
                end tell
            end tell
        ''')
    except ClientError:
        pass  # No replace dialog — file didn't exist


def _wait_for_export_complete(
    output_path: Path,
    _window_title: str,
    timeout: int = EXPORT_COMPLETE_TIMEOUT_SECONDS,
) -> None:
    """Wait for the Descript export to complete.

    Monitors Descript native sheets — export is done when all sheets close.
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            if _count_descript_sheets() == 0:
                # Sheet closed — export complete
                if output_path.exists():
                    return
        except Exception:
            pass
        time.sleep(2)

    raise ClientError(f"Export timed out after {timeout} seconds")


def _wait_for_stable_export_file(
    output_path: Path,
    timeout: int = EXPORT_STABLE_TIMEOUT_SECONDS,
) -> None:
    """Wait until the exported MP4 is present, nontrivial, and stable."""
    deadline = time.time() + timeout
    last_size = -1
    stable_count = 0
    while time.time() < deadline:
        if output_path.exists():
            size = output_path.stat().st_size
            if size >= MIN_EXPORT_BYTES and size == last_size:
                stable_count += 1
                if stable_count >= 2:
                    return
            else:
                stable_count = 0
            last_size = size
        time.sleep(1)

    if output_path.exists():
        size = output_path.stat().st_size
        raise ClientError(
            f"Export file did not become stable and at least {MIN_EXPORT_BYTES} bytes "
            f"within {timeout} seconds: {output_path} ({size} bytes)"
        )
    raise ClientError(f"Export file was not created within {timeout} seconds: {output_path}")


def export_composition_local(
    project_id: str,
    composition_id: str,
    composition_name: str,
    output_path: Path,
) -> Path:
    """Export a composition via Descript app local export.

    Automates the Descript desktop app to export a full composition
    (including slides, edits, effects) as an MP4 file.

    Requires Descript to be running with the project open.

    Args:
        project_id: Descript project UUID
        composition_id: Composition UUID
        composition_name: Composition name (for logging)
        output_path: Where to save the exported MP4

    Returns:
        Path to the exported file
    """
    output_path = output_path.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    print_info(f"Navigating to composition '{composition_name}'...")
    navigate_to_composition(project_id, composition_id)

    print_info("Verifying macOS assistive access...")
    _assert_assistive_access()

    # Connect to the page
    ws_url = _get_project_page_ws(project_id)
    if not ws_url:
        raise ClientError("Lost connection to Descript after navigation")

    ws = _connect_cdp(ws_url, timeout=15)
    try:
        # Get the window title for AppleScript
        msg_id = 1
        ws.send(json.dumps({
            "id": msg_id,
            "method": "Runtime.evaluate",
            "params": {"expression": "document.title", "returnByValue": True}
        }))
        result = json.loads(ws.recv())
        # Title might not be returned via Runtime.evaluate in Electron
        # Fall back to getting it from CDP target info
    finally:
        ws.close()

    # Get window title from targets
    targets = _get_cdp_targets()
    window_title = ""
    for t in targets:
        if t.get("type") == "page" and project_id in t.get("url", ""):
            window_title = t.get("title", "")
            break

    if not window_title:
        raise ClientError("Cannot determine Descript window title")

    print_info(f"Window: {window_title}")
    print_info("Triggering local export...")
    _trigger_local_export(project_id)
    time.sleep(3)

    print_info("Handling save dialog...")
    _handle_save_dialog(output_path, window_title)

    print_info(f"Exporting to {output_path}...")
    print_info("Waiting for export to complete (this may take a few minutes)...")
    _wait_for_export_complete(output_path, window_title)
    _wait_for_stable_export_file(output_path)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    return output_path
