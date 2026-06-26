"""Descript app automation for composition export via CDP and AppleScript.

Exports full compositions (with slides, edits, etc.) by automating the
Descript desktop app. Requires Descript to be running with CDP on port 9222.
"""
import http.client
import json
import re
import shutil
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
FFMPEG_BINARY = "ffmpeg"
AUDIO_EXTRACT_TIMEOUT_SECONDS = 600


def extract_audio_wav(source_video: Path, output_wav: Path) -> Path:
    """Extract a video file's audio track to a 16-bit PCM WAV via ffmpeg.

    Args:
        source_video: An existing video file (e.g. an exported MP4).
        output_wav: Destination WAV path.

    Returns:
        The output WAV path.

    Raises:
        ClientError: If ffmpeg is unavailable, the source is missing, the
            ffmpeg run fails, or the produced WAV is empty.
    """
    source_video = source_video.expanduser()
    output_wav = output_wav.expanduser()

    if not source_video.exists():
        raise ClientError(
            f"Cannot extract audio: source video does not exist: {source_video}"
        )

    ffmpeg = shutil.which(FFMPEG_BINARY)
    if not ffmpeg:
        raise ClientError(
            "ffmpeg is required to extract WAV audio from the exported video, "
            "but it was not found on PATH. Install it (e.g. 'brew install ffmpeg') "
            "and retry."
        )

    output_wav.parent.mkdir(parents=True, exist_ok=True)

    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source_video),
        "-vn",
        "-acodec",
        "pcm_s16le",
        str(output_wav),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=AUDIO_EXTRACT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ClientError(
            f"ffmpeg failed to extract audio from {source_video}: {detail}"
        )

    if not output_wav.exists() or output_wav.stat().st_size < MIN_EXPORT_BYTES:
        size = output_wav.stat().st_size if output_wav.exists() else 0
        raise ClientError(
            f"ffmpeg produced an empty or undersized WAV ({size} bytes): {output_wav}"
        )

    return output_wav


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
            "process. When run from Claude desktop that is the embedded Claude Code runtime "
            "bundle (~/Library/Application Support/Claude/claude-code/<version>/claude.app), "
            "shown as lowercase 'claude' in the Accessibility list — distinct from the "
            "capital-C 'Claude' desktop app entry. For shells it is Terminal/iTerm. "
            "Then retry the export.\n"
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
    """Trigger local export via CDP automation.

    1. Activates Descript first — the CDP Input.dispatchMouseEvent click on
       the Export button only produces the native save sheet when Descript
       is the frontmost app.
    2. Opens the export panel (idempotent: skipped when already open)
    3. Sets Local export destination
    4. CDP click on the Export button
    """
    print_info("Activating Descript...")
    _run_applescript('tell application "Descript" to activate')
    time.sleep(1)

    ws_url = _get_project_page_ws(project_id)
    if not ws_url:
        raise ClientError("Lost connection to Descript")

    ws = _connect_cdp(ws_url, timeout=15)
    try:
        # Runtime.evaluate .click() works but return values are unreliable
        # in this Electron context. So: click once, wait, click export.
        msg_id = int(time.time() * 1000) % 100000

        # Step 1: Open export panel. Idempotent — clicking the trigger while
        # the panel is already open from a previous attempt would toggle it
        # closed, so only click when the Export button is not present.
        print_info("Opening export panel...")
        _send_cdp_message(ws, msg_id, "Runtime.evaluate", {
            "expression": """(function(){
                    if (document.querySelector('[data-testid="export-button"]')) return 'already-open';
                    var el = document.querySelector('[data-testid="export-popover-trigger"]');
                    if (el) el.click();
                    return 'clicked';
                })()""",
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


SIDEBAR_TIMEOUT_SECONDS = 15
MENU_TIMEOUT_SECONDS = 10
DELETE_CONFIRM_WAIT_SECONDS = 3
RENAME_COMMIT_WAIT_SECONDS = 3

# Backwards-compatible aliases (the delete path referenced these names).
DELETE_SIDEBAR_TIMEOUT_SECONDS = SIDEBAR_TIMEOUT_SECONDS
DELETE_MENU_TIMEOUT_SECONDS = MENU_TIMEOUT_SECONDS


def _cdp_eval_value(ws, msg_id: int, expression: str):
    """Runtime.evaluate, returning the JS expression's value by value."""
    result = _send_cdp_message(ws, msg_id, "Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True,
    })
    return result.get("result", {}).get("result", {}).get("value")


def _cdp_click_point(ws, msg_id: int, x: float, y: float) -> None:
    """Dispatch a real left-click (move/press/release) at page coords via CDP.

    Radix menus and Electron buttons ignore synthetic element.click(); they
    require dispatched mouse input, matching _trigger_local_export.
    """
    for offset, event_type in enumerate(["mouseMoved", "mousePressed", "mouseReleased"]):
        params = {
            "type": event_type,
            "x": x,
            "y": y,
            "button": "left",
            "clickCount": 1,
        }
        if event_type == "mousePressed":
            params["buttons"] = 1
        _send_cdp_message(ws, msg_id + offset, "Input.dispatchMouseEvent", params)
        time.sleep(0.05)


def _cdp_press_key(
    ws,
    msg_id: int,
    key: str,
    code: str,
    *,
    command: bool = False,
) -> None:
    """Dispatch a real keyDown/keyUp for a single key via CDP.

    Synthetic keyboard events are ignored by Radix/contenteditable rename
    fields, so renaming drives Input.dispatchKeyEvent the same way clicks use
    Input.dispatchMouseEvent. Pass command=True for a Cmd-modified chord
    (e.g. Cmd+A select-all on macOS).
    """
    modifiers = 4 if command else 0  # CDP bit 3 (value 4) == Meta/Command.
    for offset, event_type in enumerate(["keyDown", "keyUp"]):
        _send_cdp_message(ws, msg_id + offset, "Input.dispatchKeyEvent", {
            "type": event_type,
            "key": key,
            "code": code,
            "modifiers": modifiers,
        })
        time.sleep(0.05)


def _cdp_type_text(ws, msg_id: int, text: str) -> None:
    """Insert literal text into the focused field via CDP Input.insertText.

    insertText commits the whole string as one composed input event, which
    contenteditable/Radix rename fields accept, avoiding per-character key
    synthesis. Caller must ensure the rename field is focused first.
    """
    _send_cdp_message(ws, msg_id, "Input.insertText", {"text": text})
    time.sleep(0.1)


def _open_composition_context_menu(
    ws,
    composition_id: str,
    composition_name: str,
    probe: int,
) -> int:
    """Open the id-scoped composition's sidebar context menu via CDP.

    Shared by delete and rename. Opens the composition popover if needed,
    locates the `composition-sidebar-item` whose id is the composition UUID,
    hovers it, and clicks its `composition-context-menu-button` so the Radix
    context menu is open. Returns the next free CDP message id to continue
    with. Raises ClientError if the item or its menu button is not found.
    """
    # 1. Open the composition popover. The composition list rows
    #    (composition-sidebar-item, each whose id IS the composition UUID,
    #    carrying a composition-context-menu-button) render ONLY inside the
    #    composition-popover-content popover — they are absent from the
    #    default editor DOM, so querying for them first returns ids: [].
    #    Click the composition-popover-trigger to open it. The popover is
    #    transient (closes on focus loss), so the locate loop below re-opens
    #    it whenever composition-popover-content is not present.
    trigger_expr = (
        "(function(){"
        "var open=!!document.querySelector('[data-testid=\"composition-popover-content\"]');"
        "var t=document.querySelector('[data-testid=\"composition-popover-trigger\"]');"
        "if(!t) return {trigger:false, open:open};"
        "var r=t.getBoundingClientRect();"
        "return {trigger:true, open:open, x:r.x+r.width/2, y:r.y+r.height/2};"
        "})()"
    )

    # 2. Locate the id-scoped sidebar item and its context-menu button
    #    inside the open popover.
    locate_expr = (
        "(function(){"
        "var item=document.querySelector('[data-testid=\"composition-sidebar-item\"][id=\"%s\"]');"
        "if(!item){var all=Array.from(document.querySelectorAll('[data-testid=\"composition-sidebar-item\"]'));"
        "return {found:false, ids: all.map(function(e){return e.id;})};}"
        "item.scrollIntoView({block:'center'});"
        "var ir=item.getBoundingClientRect();"
        "var btn=item.querySelector('[data-testid=\"composition-context-menu-button\"]');"
        "if(!btn) return {found:true, button:false};"
        "var r=btn.getBoundingClientRect();"
        "return {found:true, button:true, x:r.x+r.width/2, y:r.y+r.height/2, ix:ir.x+ir.width/2, iy:ir.y+ir.height/2};"
        "})()"
    ) % composition_id
    loc = None
    deadline = time.time() + SIDEBAR_TIMEOUT_SECONDS
    while time.time() < deadline:
        trig = _cdp_eval_value(ws, probe, trigger_expr)
        probe += 1
        if trig and trig.get("trigger") and not trig.get("open"):
            print_info("Opening composition list...")
            _cdp_click_point(ws, probe, trig["x"], trig["y"])
            probe += 3
            time.sleep(0.6)
        loc = _cdp_eval_value(ws, probe, locate_expr)
        probe += 1
        if loc and loc.get("found") and loc.get("button"):
            break
        time.sleep(0.4)
    if not loc or not loc.get("found"):
        raise ClientError(
            f"Composition {composition_id} not found in the Descript composition list. "
            f"Available composition ids: {loc.get('ids') if loc else None}"
        )
    if not loc.get("button"):
        raise ClientError(
            f"Composition {composition_id} has no context-menu button in the sidebar DOM."
        )

    # Hover the item (the options button can be hover-gated), then click it.
    _send_cdp_message(ws, probe, "Input.dispatchMouseEvent", {
        "type": "mouseMoved", "x": loc["ix"], "y": loc["iy"],
    })
    probe += 1
    time.sleep(0.3)
    print_info(f"Opening context menu for '{composition_name}'...")
    _cdp_click_point(ws, probe, loc["x"], loc["y"])
    probe += 3  # _cdp_click_point uses 3 consecutive IDs (move/press/release)
    time.sleep(0.6)
    return probe


def _click_context_menu_item(
    ws,
    probe: int,
    labels: tuple,
    action: str,
    timeout: int = MENU_TIMEOUT_SECONDS,
) -> int:
    """Find and click a Radix menuitem by visible text via CDP.

    `labels` is a tuple of acceptable lowercase menu-item texts (e.g.
    ('delete', 'delete composition')). Returns the next free CDP message id.
    Raises ClientError listing the menu items seen if no label matches.
    """
    labels_js = ",".join("'%s'" % label for label in labels)
    item_expr = (
        "(function(){"
        "var labels=[%s];"
        "var els=Array.from(document.querySelectorAll('[role=\"menuitem\"]'));"
        "var hit=els.find(function(e){var t=(e.textContent||'').trim().toLowerCase(); return labels.indexOf(t)!==-1;});"
        "if(!hit) return {found:false, items: els.map(function(e){return (e.textContent||'').trim();})};"
        "var r=hit.getBoundingClientRect();"
        "return {found:true, x:r.x+r.width/2, y:r.y+r.height/2, text:hit.textContent.trim()};"
        "})()"
    ) % labels_js
    deadline = time.time() + timeout
    item = None
    while time.time() < deadline:
        item = _cdp_eval_value(ws, probe, item_expr)
        probe += 1
        if item and item.get("found"):
            break
        time.sleep(0.3)
    if not item or not item.get("found"):
        raise ClientError(
            f"{action} item did not appear in the composition context menu. "
            f"Menu items seen: {item.get('items') if item else None}"
        )
    print_info(f"Clicking {item['text']}...")
    _cdp_click_point(ws, probe + 1, item["x"], item["y"])
    probe += 4  # one eval id consumed above + 3 for the click
    time.sleep(0.8)
    return probe


def delete_composition_local(
    project_id: str,
    composition_id: str,
    composition_name: str,
) -> None:
    """Delete a composition by driving the Descript desktop app's own UI.

    Descript exposes no delete API — deleting a composition is a proprietary
    collaborative-document (OT) commit the app computes internally. So this
    drives the id-scoped sidebar context menu -> Delete via CDP, letting the
    app produce the correct document delta. Requires Descript running with CDP
    on port 9222; the project auto-opens via its descript:// deep link.
    """
    _ensure_project_open(project_id)

    print_info("Activating Descript...")
    _run_applescript('tell application "Descript" to activate')
    time.sleep(1)

    ws_url = _get_project_page_ws(project_id)
    if not ws_url:
        raise ClientError("Lost connection to Descript")

    ws = _connect_cdp(ws_url, timeout=15)
    try:
        probe = int(time.time() * 1000) % 100000

        # 1. Open the id-scoped composition's sidebar context menu.
        probe = _open_composition_context_menu(
            ws, composition_id, composition_name, probe,
        )

        # 2. Find and click the Delete item (Radix menuitem).
        probe = _click_context_menu_item(
            ws, probe, ("delete", "delete composition"), "Delete",
        )

        # 3. Confirm dialog, if Descript shows one (Radix AlertDialog).
        confirm_expr = (
            "(function(){"
            "var dlg=document.querySelector('[role=\"alertdialog\"],[role=\"dialog\"]');"
            "if(!dlg) return {dialog:false};"
            "var btns=Array.from(dlg.querySelectorAll('button,[role=\"button\"]'));"
            "var del=btns.find(function(b){var t=(b.textContent||'').trim().toLowerCase(); return t==='delete'||t==='delete composition'||t==='confirm'||t==='ok'||t==='move to trash';});"
            "if(!del) return {dialog:true, button:false, buttons: btns.map(function(b){return (b.textContent||'').trim();})};"
            "var r=del.getBoundingClientRect();"
            "return {dialog:true, button:true, x:r.x+r.width/2, y:r.y+r.height/2, text:del.textContent.trim()};"
            "})()"
        )
        # Many Descript builds delete immediately on the menu click; some may
        # show a confirmation dialog. Best-effort: if a confirm dialog WITH a
        # matching confirm button appears, click it. Otherwise proceed — the
        # caller verifies the deletion via the compositions list, which is the
        # source of truth. A non-matching role="dialog" (the app's own panels)
        # is ignored, never treated as a failure.
        deadline = time.time() + DELETE_CONFIRM_WAIT_SECONDS
        probe2 = probe + 20
        while time.time() < deadline:
            conf = _cdp_eval_value(ws, probe2, confirm_expr)
            probe2 += 1
            if conf and conf.get("dialog") and conf.get("button"):
                print_info("Confirming deletion...")
                _cdp_click_point(ws, probe2 + 1, conf["x"], conf["y"])
                time.sleep(0.8)
                break
            time.sleep(0.3)
    finally:
        ws.close()


def _enter_rename_mode_via_double_click(ws, composition_id: str, probe: int) -> int:
    """Fallback rename trigger: double-click the composition title.

    Used only when the context menu exposes no Rename item. Locates the
    id-scoped sidebar item's title element and dispatches a double-click
    (clickCount 2) via CDP, which Descript treats as an inline-rename gesture.
    Returns the next free CDP message id. Raises ClientError if the title
    element cannot be located.
    """
    title_expr = (
        "(function(){"
        "var item=document.querySelector('[data-testid=\"composition-sidebar-item\"][id=\"%s\"]');"
        "if(!item) return {found:false};"
        "var t=item.querySelector('[data-testid=\"composition-name\"]') "
        "|| item.querySelector('[contenteditable]') || item;"
        "var r=t.getBoundingClientRect();"
        "return {found:true, x:r.x+r.width/2, y:r.y+r.height/2};"
        "})()"
    ) % composition_id
    loc = _cdp_eval_value(ws, probe, title_expr)
    probe += 1
    if not loc or not loc.get("found"):
        raise ClientError(
            f"Composition {composition_id} title element not found to enter rename mode."
        )
    print_info("Double-clicking the composition title to rename...")
    for click_count in (1, 2):
        for event_type in ("mousePressed", "mouseReleased"):
            params = {
                "type": event_type,
                "x": loc["x"],
                "y": loc["y"],
                "button": "left",
                "clickCount": click_count,
            }
            if event_type == "mousePressed":
                params["buttons"] = 1
            _send_cdp_message(ws, probe, "Input.dispatchMouseEvent", params)
            probe += 1
            time.sleep(0.05)
    time.sleep(0.6)
    return probe


def rename_composition_local(
    project_id: str,
    composition_id: str,
    composition_name: str,
    new_name: str,
) -> None:
    """Rename a composition by driving the Descript desktop app's own UI.

    Descript exposes no rename API — a composition name is an internal
    collaborative-document (OT) edit the app computes internally, exactly like
    delete. So this drives the id-scoped sidebar context menu -> Rename via CDP
    (falling back to double-clicking the title if no Rename item exists),
    select-all + type the new name + Enter, letting the app produce the correct
    document delta. Requires Descript running with CDP on port 9222; the project
    auto-opens via its descript:// deep link. The caller verifies the new name
    via the compositions list and fails loudly if it did not take.
    """
    _ensure_project_open(project_id)

    print_info("Activating Descript...")
    _run_applescript('tell application "Descript" to activate')
    time.sleep(1)

    ws_url = _get_project_page_ws(project_id)
    if not ws_url:
        raise ClientError("Lost connection to Descript")

    ws = _connect_cdp(ws_url, timeout=15)
    try:
        probe = int(time.time() * 1000) % 100000

        # 1. Open the id-scoped composition's sidebar context menu.
        probe = _open_composition_context_menu(
            ws, composition_id, composition_name, probe,
        )

        # 2. Click the Rename item (Radix menuitem). If the menu has no Rename
        #    item, fall back to the app's double-click-title rename affordance.
        try:
            probe = _click_context_menu_item(
                ws, probe, ("rename", "rename composition"), "Rename",
            )
        except ClientError:
            print_info("No Rename menu item; falling back to double-click rename...")
            probe = _enter_rename_mode_via_double_click(ws, composition_id, probe)

        # 3. Replace the text: select-all, type the new name, commit with Enter.
        #    The rename field is a contenteditable/Radix input that ignores
        #    synthetic events, so these go through real CDP key/text dispatch.
        print_info(f"Renaming to '{new_name}'...")
        _cdp_press_key(ws, probe, "a", "KeyA", command=True)  # Cmd+A select-all
        probe += 2
        _cdp_type_text(ws, probe, new_name)
        probe += 1
        _cdp_press_key(ws, probe, "Enter", "Enter")  # commit
        probe += 2
        time.sleep(RENAME_COMMIT_WAIT_SECONDS)
    finally:
        ws.close()
