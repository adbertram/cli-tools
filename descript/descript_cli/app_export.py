"""Descript app automation for composition export via CDP and AppleScript.

Exports full compositions (with slides, edits, etc.) by automating the
Descript desktop app. Requires Descript to be running with CDP on port 9222.
"""
import http.client
import json
import subprocess
import time
from pathlib import Path
from typing import Optional

import websocket

from .client import ClientError
from cli_tools_shared.output import print_info, print_error

CDP_PORT = 9222
DESCRIPT_BASE_URL = "https://web.descript.com"


def _get_cdp_targets() -> list[dict]:
    """Get CDP targets from Descript app."""
    try:
        conn = http.client.HTTPConnection("127.0.0.1", CDP_PORT, timeout=5)
        conn.request("GET", "/json")
        response = conn.getresponse()
        targets = json.loads(response.read().decode())
        conn.close()
        return targets
    except Exception:
        raise ClientError(
            "Cannot connect to Descript CDP.\n"
            "Ensure Descript is running with --remote-debugging-port=9222"
        )


def _get_project_page_ws(project_id: str) -> str:
    """Get WebSocket URL for the project page target."""
    targets = _get_cdp_targets()
    for t in targets:
        if t.get("type") == "page" and project_id[:5] in t.get("url", ""):
            ws_url = t.get("webSocketDebuggerUrl")
            if ws_url:
                return ws_url
    return ""


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
    ws.send(json.dumps({"id": msg_id, "method": "DOM.enable"}))
    json.loads(ws.recv())
    ws.send(json.dumps({
        "id": msg_id + 1,
        "method": "DOM.getDocument",
        "params": {"depth": -1}
    }))
    result = json.loads(ws.recv())
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


def navigate_to_composition(project_id: str, composition_id: str) -> None:
    """Navigate Descript to a specific composition.

    Opens the composition URL in the Descript app via CDP navigation.
    Waits for the page to fully load before returning.
    """
    url = f"{DESCRIPT_BASE_URL}/{project_id}/{composition_id[:5]}?editorVariant=default"

    ws_url = _get_project_page_ws(project_id)
    if not ws_url:
        raise ClientError(
            f"Project {project_id} is not open in Descript.\n"
            "Open the project in Descript first, then retry."
        )

    # Navigate via CDP
    ws = websocket.create_connection(ws_url, timeout=15)
    try:
        ws.send(json.dumps({
            "id": 1,
            "method": "Page.navigate",
            "params": {"url": url}
        }))
        json.loads(ws.recv())
    finally:
        ws.close()

    # Wait for page to load by polling for the export trigger button in the DOM
    for attempt in range(20):
        time.sleep(1)
        try:
            new_ws_url = _get_project_page_ws(project_id)
            if not new_ws_url:
                continue
            ws = websocket.create_connection(new_ws_url, timeout=10)
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

    ws = websocket.create_connection(ws_url, timeout=15)
    try:
        # Runtime.evaluate .click() works but return values are unreliable
        # in this Electron context. So: click once, wait, click export.
        msg_id = int(time.time() * 1000) % 100000

        # Step 1: Open export panel (click trigger once)
        print_info("Opening export panel...")
        ws.send(json.dumps({
            "id": msg_id,
            "method": "Runtime.evaluate",
            "params": {
                "expression": '(function(){ var el = document.querySelector(\'[data-testid="export-popover-trigger"]\'); if(el) el.click(); })()',
            }
        }))
        json.loads(ws.recv())
        time.sleep(3)

        # Step 2: Set destination to Local export
        # Click the destination dropdown, then select Local export
        print_info("Setting Local export destination...")
        ws.send(json.dumps({
            "id": msg_id + 1,
            "method": "Runtime.evaluate",
            "params": {
                "expression": """(function(){
                    var dest = document.querySelector('[data-testid="export-destination-select"]');
                    if (dest && dest.textContent.indexOf('Local export') === -1) {
                        var btn = dest.querySelector('button');
                        if (btn) btn.click();
                    }
                })()""",
            }
        }))
        json.loads(ws.recv())
        time.sleep(1)

        ws.send(json.dumps({
            "id": msg_id + 2,
            "method": "Runtime.evaluate",
            "params": {
                "expression": '(function(){ var el = document.querySelector(\'[data-testid="export-destination-select-option-Local export"]\'); if(el) el.click(); })()',
            }
        }))
        json.loads(ws.recv())
        time.sleep(1)

        # Step 3: Click the Export button with full mouse event simulation
        print_info("Clicking Export button...")
        ws.send(json.dumps({
            "id": msg_id + 3,
            "method": "Runtime.evaluate",
            "params": {
                "expression": """(function(){
                    var el = document.querySelector('[data-testid="export-button"]');
                    if (!el) return;
                    var rect = el.getBoundingClientRect();
                    var x = rect.x + rect.width / 2;
                    var y = rect.y + rect.height / 2;
                    ['mousedown', 'mouseup', 'click'].forEach(function(type) {
                        el.dispatchEvent(new MouseEvent(type, {
                            bubbles: true, cancelable: true, view: window,
                            clientX: x, clientY: y, button: 0
                        }));
                    });
                })()""",
            }
        }))
        json.loads(ws.recv())
    finally:
        ws.close()


def _handle_save_dialog(output_path: Path, window_title: str) -> None:
    """Handle the native macOS save dialog via AppleScript.

    Sets the filename and navigates to the output directory.
    """
    output_dir = str(output_path.parent)
    filename = output_path.name

    # Activate Descript to ensure save dialog is visible
    _run_applescript('tell application "Descript" to activate')

    # Wait for the save sheet to appear
    for _ in range(20):
        try:
            count = _run_applescript(f'''
                tell application "System Events"
                    tell process "Descript"
                        return count of sheets of window "{window_title}"
                    end tell
                end tell
            ''')
            if int(count) > 0:
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        raise ClientError("Save dialog did not appear within 10 seconds")

    # Set the filename
    _run_applescript(f'''
        tell application "System Events"
            tell process "Descript"
                set s to sheet 1 of window "{window_title}"
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
                set s to sheet 1 of window "{window_title}"
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
                    set s to sheet 1 of window "{window_title}"
                    set innerSheet to sheet 1 of s
                    click button "Replace" of innerSheet
                    return "replaced"
                end tell
            end tell
        ''')
    except ClientError:
        pass  # No replace dialog — file didn't exist


def _wait_for_export_complete(output_path: Path, window_title: str, timeout: int = 300) -> None:
    """Wait for the Descript export to complete.

    Monitors the save dialog sheet — export is done when the sheet closes.
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            count = _run_applescript(f'''
                tell application "System Events"
                    tell process "Descript"
                        return count of sheets of window "{window_title}"
                    end tell
                end tell
            ''')
            if int(count) == 0:
                # Sheet closed — export complete
                if output_path.exists():
                    return
        except Exception:
            pass
        time.sleep(2)

    raise ClientError(f"Export timed out after {timeout} seconds")


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
    print_info(f"Navigating to composition '{composition_name}'...")
    navigate_to_composition(project_id, composition_id)

    # Connect to the page
    ws_url = _get_project_page_ws(project_id)
    if not ws_url:
        raise ClientError("Lost connection to Descript after navigation")

    ws = websocket.create_connection(ws_url, timeout=15)
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
        if t.get("type") == "page" and project_id[:5] in t.get("url", ""):
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

    size_mb = output_path.stat().st_size / (1024 * 1024)
    return output_path
