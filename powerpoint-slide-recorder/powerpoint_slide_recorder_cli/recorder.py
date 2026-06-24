#!/usr/bin/env python3
import json
import re
import shlex
import subprocess
import sys
import time
import zipfile
import xml.etree.ElementTree as ElementTree
from pathlib import Path


MACOS_DISPLAY_HELPER = r'''
import json
import sys

try:
    import Quartz
except Exception as error:
    raise SystemExit(f"Quartz import failed: {error}")


def payload_for_mode(mode):
    return {
        "width": int(Quartz.CGDisplayModeGetWidth(mode)),
        "height": int(Quartz.CGDisplayModeGetHeight(mode)),
        "pixel_width": int(Quartz.CGDisplayModeGetPixelWidth(mode)),
        "pixel_height": int(Quartz.CGDisplayModeGetPixelHeight(mode)),
    }


def matching_mode(display_id, width, height):
    options = {Quartz.kCGDisplayShowDuplicateLowResolutionModes: True}
    modes = Quartz.CGDisplayCopyAllDisplayModes(display_id, options)
    for mode in modes:
        mode_payload = payload_for_mode(mode)
        if (mode_payload["pixel_width"], mode_payload["pixel_height"]) == (width, height):
            return mode
        if (mode_payload["width"], mode_payload["height"]) == (width, height):
            return mode
    raise SystemExit(f"Display mode {width}x{height} is not available on the main display")


def display_modes(display_id):
    options = {Quartz.kCGDisplayShowDuplicateLowResolutionModes: True}
    return [payload_for_mode(mode) for mode in Quartz.CGDisplayCopyAllDisplayModes(display_id, options)]


def set_display_mode(display_id, mode):
    error, config = Quartz.CGBeginDisplayConfiguration(None)
    if error != Quartz.kCGErrorSuccess:
        raise SystemExit(f"CGBeginDisplayConfiguration failed with code {error}")
    try:
        error = Quartz.CGConfigureDisplayWithDisplayMode(config, display_id, mode, None)
        if error != Quartz.kCGErrorSuccess:
            raise SystemExit(f"CGConfigureDisplayWithDisplayMode failed with code {error}")
        error = Quartz.CGCompleteDisplayConfiguration(config, Quartz.kCGConfigureForSession)
        if error != Quartz.kCGErrorSuccess:
            raise SystemExit(f"CGCompleteDisplayConfiguration failed with code {error}")
    except Exception:
        Quartz.CGCancelDisplayConfiguration(config)
        raise


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Missing display helper action")
    action = sys.argv[1]
    display_id = Quartz.CGMainDisplayID()

    if action == "current":
        print(json.dumps(payload_for_mode(Quartz.CGDisplayCopyDisplayMode(display_id))))
        return

    if action == "modes":
        print(json.dumps(display_modes(display_id)))
        return

    if action == "set":
        if len(sys.argv) != 4:
            raise SystemExit("set requires width and height")
        width = int(sys.argv[2])
        height = int(sys.argv[3])
        set_display_mode(display_id, matching_mode(display_id, width, height))
        return

    raise SystemExit(f"Unsupported display helper action: {action}")


main()
'''
DEFAULT_FRAMERATE = 30
DEFAULT_RESOLUTION = "1920x1080"
DEFAULT_RECORDING_LEAD_SECONDS = 1.0
DEFAULT_SLIDE_PAUSE_SECONDS = 0.75
DEFAULT_SLIDESHOW_START_SECONDS = 2.0
DEFAULT_CUE_MARKER = "||"
# Hard subprocess wall-clock bound on every PowerPoint-targeting osascript. The
# in-AppleScript ``with timeout`` only bounds Apple-event waits once the script is
# executing; it cannot bound the case where osascript never starts running because
# a macOS Automation (AppleEvents) consent prompt or a blocking PowerPoint modal is
# sitting in front of it. Without this subprocess-level timeout the recorder hangs
# forever at the open/automation step with no diagnostic.
OSASCRIPT_TIMEOUT_SECONDS = 30
# Bounded number of open/dismiss/recheck cycles open_deck() runs so a transient
# benign PowerPoint startup dialog cannot block the recording indefinitely.
OPEN_DECK_DISMISS_ATTEMPTS = 8
# The dialog probe is best-effort: re-probe a few times with short sleeps to ride
# out the AX-not-ready race in the first moments after PowerPoint launches before
# concluding "no dialog". Never fatal — a probe that still cannot read dialog
# state just means the auto-dismiss convenience is skipped, not that recording stops.
DIALOG_PROBE_ATTEMPTS = 3
DIALOG_PROBE_RETRY_SECONDS = 0.5
SLIDE_IDENTITY_FIELD = "slide"
SLIDE_LABEL_PREFIX = "Slide"
INTER_SLIDE_ACTIONS = [{
    "key": "space",
    "reason": "next slide",
}]
# Benign PowerPoint startup/first-run dialogs the recorder auto-dismisses (data,
# not control flow). Per Adam's standing rule the agent always auto-dismisses
# demo/recording-related macOS dialogs and never asks, so a recognized startup
# sheet is cleared automatically rather than surfaced as an error. Each entry is
# matched case-insensitively: a dialog matches when any of its ``title_contains``
# substrings appears in the window/sheet title OR any of its ``text_contains``
# substrings appears in the dialog's static text. ``dismiss_button`` lists the
# benign default buttons to click in priority order; when none are present the
# generic_dismisser presses ``escape`` (the safe default). An UNKNOWN blocking
# dialog matches no entry and is never clicked — open_deck() raises instead.
POWERPOINT_STARTUP_DIALOGS = [
    {
        "name": "What's New",
        "title_contains": ["What's New", "Whats New", "What’s New"],
        "text_contains": ["What's New", "What’s New"],
        "dismiss_button": ["Continue", "Get Started", "Close", "OK"],
    },
    {
        "name": "Sign in",
        "title_contains": ["Sign in", "Sign In", "Sign-in"],
        "text_contains": ["Sign in", "sign in to", "Microsoft account", "work or school account"],
        "dismiss_button": ["Sign in later", "Sign In Later", "Not now", "Not Now", "Skip", "Maybe later", "Cancel"],
    },
    {
        "name": "Document Recovery",
        "title_contains": ["Document Recovery", "Recovered"],
        "text_contains": ["Document Recovery", "recovered", "AutoRecover", "wants to recover"],
        "dismiss_button": ["Close", "Don't Save", "Discard", "Cancel"],
    },
    {
        "name": "Update",
        "title_contains": ["Update", "Updates Available", "What's Included"],
        "text_contains": ["update is available", "updates are available", "new update", "Install Update"],
        "dismiss_button": ["Later", "Not now", "Not Now", "Skip", "Close"],
    },
    {
        "name": "First run",
        "title_contains": ["Welcome", "Get started", "Get Started", "We've updated", "What’s Included", "What's Included"],
        "text_contains": ["Welcome to", "Get started with", "We've made some changes", "accept the license", "License Agreement"],
        "dismiss_button": ["Accept", "Continue", "Get Started", "Skip", "Close", "OK", "Done"],
    },
]
PRESENTATIONML_NAMESPACE = "http://schemas.openxmlformats.org/presentationml/2006/main"
PACKAGE_RELATIONSHIPS_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"
SLIDE_LAYOUT_RELATIONSHIP_SUFFIX = "/slideLayout"


def slide_label(item, index):
    if SLIDE_IDENTITY_FIELD not in item:
        raise KeyError(f"{SLIDE_LABEL_PREFIX} item {index} is missing {SLIDE_IDENTITY_FIELD}")
    if not isinstance(item[SLIDE_IDENTITY_FIELD], int):
        raise TypeError(f"{SLIDE_LABEL_PREFIX} item {index} {SLIDE_IDENTITY_FIELD} must be int")
    if item[SLIDE_IDENTITY_FIELD] < 1:
        raise ValueError(f"{SLIDE_LABEL_PREFIX} item {index} {SLIDE_IDENTITY_FIELD} must be greater than zero")
    return f"{SLIDE_LABEL_PREFIX} {item[SLIDE_IDENTITY_FIELD]}"


def log_warning(message):
    print(f"Warning: {message}", file=sys.stderr)


def run(command, timeout=None):
    subprocess.run(command, check=True, timeout=timeout)


def capture(command, timeout=None):
    completed = subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE, timeout=timeout)
    return completed.stdout.strip()


def run_macos_display_helper(*args):
    completed = subprocess.run(
        ["/usr/bin/python3", "-c", MACOS_DISPLAY_HELPER, *[str(arg) for arg in args]],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip()
        if detail == "":
            detail = completed.stdout.strip()
        raise RuntimeError(f"macOS display helper failed: {detail}")
    return completed.stdout.strip()


def parse_display_mode_payload(payload):
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"macOS display helper returned invalid JSON: {payload}") from error

    required_keys = ["width", "height", "pixel_width", "pixel_height"]
    for key in required_keys:
        if key not in parsed:
            raise RuntimeError(f"macOS display helper payload is missing {key}")
        if not isinstance(parsed[key], int):
            raise RuntimeError(f"macOS display helper payload {key} must be int")
    return parsed


def parse_display_modes_payload(payload):
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"macOS display helper returned invalid JSON: {payload}") from error

    if not isinstance(parsed, list):
        raise RuntimeError("macOS display helper modes payload must be a list")
    modes = []
    for index, mode in enumerate(parsed, start=1):
        modes.append(validate_display_mode_payload(mode, f"mode {index}"))
    return modes


def validate_display_mode_payload(parsed, description):
    if not isinstance(parsed, dict):
        raise RuntimeError(f"macOS display helper payload {description} must be object")
    required_keys = ["width", "height", "pixel_width", "pixel_height"]
    for key in required_keys:
        if key not in parsed:
            raise RuntimeError(f"macOS display helper payload {description} is missing {key}")
        if not isinstance(parsed[key], int):
            raise RuntimeError(f"macOS display helper payload {description} {key} must be int")
    return parsed


def current_display_mode():
    return parse_display_mode_payload(run_macos_display_helper("current"))


def available_display_modes():
    return parse_display_modes_payload(run_macos_display_helper("modes"))


def set_display_resolution(width, height):
    run_macos_display_helper("set", width, height)


def parse_resolution(value):
    match = re.fullmatch(r"([1-9][0-9]*)x([1-9][0-9]*)", value)
    if match is None:
        raise ValueError(f"Invalid resolution {value!r}; expected WIDTHxHEIGHT with positive even integers")
    width = int(match.group(1))
    height = int(match.group(2))
    if width % 2 != 0 or height % 2 != 0:
        raise ValueError(f"Invalid resolution {value!r}; expected WIDTHxHEIGHT with positive even integers")
    return width, height


def parse_aspect_ratio(value):
    match = re.fullmatch(r"([1-9][0-9]*)x([1-9][0-9]*)", value)
    if match is None:
        raise ValueError(f"Invalid aspect ratio {value!r}; expected WIDTHxHEIGHT with positive integers")
    return int(match.group(1)), int(match.group(2))


def mode_usable_pixels_for_output(mode, output_width, output_height):
    """Return a display mode's usable (post-centered-crop) pixel size for the output AR.

    PowerPoint always presents the slide centered and letterboxed/pillarboxed to
    fill the screen, so the centered output-aspect-ratio rectangle of a captured
    mode IS the slide. A mode whose own pixel ratio already matches the output AR
    needs no crop and is usable at its full pixel size; any other mode is usable
    only at its centered output-AR crop. Returns a ``(usable_width, usable_height)``
    tuple. Both the output dimensions and the resulting crop are evaluated with the
    same even-rounding the final mux applies, so usability matches what is recorded.
    """
    crop = centered_crop_for_output_aspect(
        mode["pixel_width"], mode["pixel_height"], output_width, output_height
    )
    if crop is None:
        return mode["pixel_width"], mode["pixel_height"]
    return crop[0], crop[1]


def best_display_mode_for_aspect_ratio(modes, aspect_width, aspect_height, output_width, output_height):
    """Pick the highest-area display mode that can deliver the requested output AR.

    A mode qualifies when its centered output-aspect-ratio crop is at least the
    requested output size, so the slide can be captured and scaled to the output
    without upscaling. A mode whose pixel ratio already equals the output AR needs
    no crop; a mode with a different ratio (e.g. a 16:10 panel against 16:9 output)
    qualifies through its centered letterbox crop. The exact-AR case still wins when
    present because it has the largest usable area at a given pixel area and needs no
    crop, so an external true-16:9 source is selected and recorded uncropped exactly
    as before. Raises when no mode's usable region reaches the requested output.
    """
    if aspect_width * output_height != output_width * aspect_height:
        raise ValueError(
            f"Requested aspect ratio {aspect_width}x{aspect_height} does not match "
            f"the output resolution {output_width}x{output_height}"
        )

    qualifying = []
    for mode in modes:
        usable_width, usable_height = mode_usable_pixels_for_output(mode, output_width, output_height)
        if usable_width >= output_width and usable_height >= output_height:
            qualifying.append(mode)
    if len(qualifying) == 0:
        raise RuntimeError(
            f"No display mode can produce a {aspect_width}x{aspect_height} capture of at least "
            f"{output_width}x{output_height} on the main display. The largest centered "
            f"{aspect_width}x{aspect_height} crop of every available mode is smaller than the "
            f"requested output. Use a higher-resolution display or --video-input source."
        )

    def ranking(mode):
        usable_width, usable_height = mode_usable_pixels_for_output(mode, output_width, output_height)
        exact = 1 if mode["pixel_width"] * aspect_height == aspect_width * mode["pixel_height"] else 0
        return (
            usable_width * usable_height,
            exact,
            mode["pixel_width"] * mode["pixel_height"],
            mode["pixel_width"],
            mode["pixel_height"],
        )

    return max(qualifying, key=ranking)


def parse_capture_dimensions(output):
    match = re.search(r"Stream #\d+:\d+.*Video:.*?,\s*(\d+)x(\d+)(?:[,\s])", output)
    if match is None:
        raise ValueError("ffmpeg probe output did not contain capture dimensions")
    return int(match.group(1)), int(match.group(2))


def probe_capture_dimensions(video_input, framerate):
    completed = subprocess.run([
        "ffmpeg",
        "-hide_banner",
        "-f",
        "avfoundation",
        "-framerate",
        str(framerate),
        "-t",
        "0.1",
        "-i",
        str(video_input),
        "-frames:v",
        "1",
        "-f",
        "null",
        "-",
    ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg capture probe exited with code {completed.returncode}: {completed.stderr.strip()}")
    return parse_capture_dimensions(completed.stderr)


def round_to_even(value):
    return int(value) - (int(value) % 2)


def centered_crop_for_output_aspect(capture_width, capture_height, output_width, output_height):
    """Return the centered crop rectangle of the output AR within the capture frame.

    PowerPoint's fullscreen slideshow always presents the 16:9 slide centered and
    letterboxed/pillarboxed to fit the screen, so the centered output-aspect-ratio
    rectangle of the capture IS exactly the slide. Returns ``None`` when the capture
    already matches the output aspect ratio (no crop needed), otherwise a
    ``(crop_width, crop_height, x, y)`` tuple with even dimensions and offsets.
    """
    if capture_width * output_height == output_width * capture_height:
        return None

    if capture_width * output_height < output_width * capture_height:
        # Capture is "taller" than the output AR (e.g. 16:10 vs 16:9): full width,
        # bars top and bottom. Crop full width, shrink height to the output AR.
        crop_width = round_to_even(capture_width)
        crop_height = round_to_even(round(capture_width * output_height / output_width))
        crop_x = 0
        crop_y = round_to_even((capture_height - crop_height) // 2)
    else:
        # Capture is "wider" than the output AR (e.g. 21:9): full height, bars left
        # and right. Crop full height, shrink width to the output AR.
        crop_height = round_to_even(capture_height)
        crop_width = round_to_even(round(capture_height * output_width / output_height))
        crop_y = 0
        crop_x = round_to_even((capture_width - crop_width) // 2)

    return (crop_width, crop_height, crop_x, crop_y)


def capture_crop_plan(source_width, source_height, output_width, output_height, video_input):
    """Validate a capture source and return its centered output-AR crop plan, if any.

    Returns ``None`` when the capture already matches the output aspect ratio, or a
    ``(crop_width, crop_height, x, y)`` tuple when a centered crop is required to
    extract the slide before scaling. Raises when the (post-crop) capture region is
    smaller than the requested output, since that would require upscaling.
    """
    crop = centered_crop_for_output_aspect(source_width, source_height, output_width, output_height)
    effective_width, effective_height = (source_width, source_height) if crop is None else (crop[0], crop[1])
    if effective_width < output_width or effective_height < output_height:
        raise ValueError(
            f"Capture source {video_input} is {source_width}x{source_height} "
            f"(usable {effective_width}x{effective_height} after centered crop), "
            f"which is smaller than requested output {output_width}x{output_height}. "
            "Switch the display mode or --video-input capture source to at least the requested resolution before recording. "
            "Use --force-resolution for an exact display mode when that mode is available."
        )
    return crop


def osascript(*lines, args=None):
    command = ["osascript"]
    for line in lines:
        command.extend(["-e", line])
    if args is not None:
        command.extend(args)
    return command


def osascript_timed_out_error(timeout_seconds):
    return RuntimeError(
        f"osascript controlling Microsoft PowerPoint did not respond within "
        f"{timeout_seconds} seconds and was killed. The most likely cause is a "
        "macOS Automation (AppleEvents) consent prompt for controlling PowerPoint, "
        "or a blocking PowerPoint dialog (first-run / sign-in / 'What's New' / "
        "Document Recovery) sitting in front of the AppleScript. Grant Automation "
        "access (System Settings -> Privacy & Security -> Automation) and dismiss any "
        "open PowerPoint dialog, then retry."
    )


def run_osascript(*lines, args=None):
    try:
        run(osascript(*lines, args=args), timeout=OSASCRIPT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        raise osascript_timed_out_error(OSASCRIPT_TIMEOUT_SECONDS) from error


def capture_osascript(*lines, args=None):
    try:
        return capture(osascript(*lines, args=args), timeout=OSASCRIPT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        raise osascript_timed_out_error(OSASCRIPT_TIMEOUT_SECONDS) from error


def quote_applescript_text(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def render_scoped_process_action(action, inner_lines):
    return [
        'tell application "System Events"',
        f'tell process "{quote_applescript_text(action["process"])}"',
        *inner_lines,
        "end tell",
        "end tell",
    ]


def render_ui_action(action):
    renderers = {
        "activate_app": render_activate_app_action,
        "assert_window": render_assert_window_action,
        "delay": render_delay_action,
        "fullscreen_window": render_fullscreen_window_action,
        "key_code": render_key_code_action,
        "key_stroke": render_key_stroke_action,
        "keystroke_command": render_keystroke_command_action,
        "menu_click": render_menu_click_action,
        "quit_app": render_quit_app_action,
    }
    if action["action"] not in renderers:
        raise ValueError(f"Unsupported UI action: {action['action']}")
    return renderers[action["action"]](action)


def render_ui_actions(actions):
    lines = []
    for action in actions:
        lines.extend(render_ui_action(action))
    return lines


def execute_ui_actions(actions):
    run_osascript(*render_ui_actions(actions))


def render_activate_app_action(action):
    return [f'tell application "{quote_applescript_text(action["app"])}" to activate']


def render_delay_action(action):
    return [f"delay {action['seconds']}"]


def render_menu_click_action(action):
    return render_scoped_process_action(action, [
        f'click menu item "{quote_applescript_text(action["item"])}" of menu "{quote_applescript_text(action["menu"])}" of menu bar 1',
    ])


def render_assert_window_action(action):
    contains = quote_applescript_text(action["contains"])
    return render_scoped_process_action(action, [
        "set foundWindow to false",
        "repeat with currentWindow in windows",
        "set windowName to name of currentWindow as text",
        f'if windowName contains "{contains}" then set foundWindow to true',
        "end repeat",
        f'if foundWindow is false then error "Window containing {contains} not found"',
    ])


def render_key_code_action(action):
    return [f'tell application "System Events" to key code {action["code"]}']


def render_key_stroke_action(action):
    lines = [
        'tell application "System Events"',
        f'keystroke "{quote_applescript_text(action["text"])}"',
    ]
    for key_code in action.get("then_key_codes", []):
        lines.append(f"key code {key_code}")
    lines.append("end tell")
    return lines


def render_keystroke_command_action(action):
    return [
        'tell application "System Events"',
        f'keystroke "{quote_applescript_text(action["text"])}" using command down',
        "end tell",
    ]


def render_quit_app_action(action):
    save_behavior = action["saving"]
    return [f'tell application "{quote_applescript_text(action["app"])}" to quit saving {save_behavior}']


def render_fullscreen_window_action(action):
    contains = quote_applescript_text(action["contains"])
    screen_width = int(action["screen_width"])
    screen_height = int(action["screen_height"])
    coverage_tolerance = int(action.get("coverage_tolerance", 4))
    return render_scoped_process_action(action, [
        "set frontmost to true",
        "repeat 40 times",
        "set targetWindow to missing value",
        "repeat with currentWindow in windows",
        "set windowName to name of currentWindow as text",
        f'if windowName contains "{contains}" then',
        "set targetWindow to currentWindow",
        "exit repeat",
        "end if",
        "end repeat",
        "if targetWindow is not missing value then exit repeat",
        "delay 0.25",
        "end repeat",
        f'if targetWindow is missing value then error "Window containing {contains} not found"',
        'try',
        'perform action "AXRaise" of targetWindow',
        'end try',
        # PowerPoint's "full screen" slideshow uses its own presentation mode rather
        # than macOS-native fullscreen, so AXFullScreen often stays false even though
        # the Slide Show window already covers the whole display. Treat the slideshow
        # as ready when AXFullScreen is true OR the window already covers the screen.
        'try',
        'set value of attribute "AXFullScreen" of targetWindow to true',
        'end try',
        "delay 1",
        "repeat 40 times",
        "set slideshowReady to false",
        "repeat with currentWindow in windows",
        "set windowName to name of currentWindow as text",
        f'if windowName contains "{contains}" then',
        'set isFullscreen to false',
        'try',
        'if (value of attribute "AXFullScreen" of currentWindow) is true then set isFullscreen to true',
        'end try',
        'set coversScreen to false',
        'try',
        "set windowSize to size of currentWindow",
        "set windowPos to position of currentWindow",
        "set windowWidth to item 1 of windowSize",
        "set windowHeight to item 2 of windowSize",
        "set windowX to item 1 of windowPos",
        "set windowY to item 2 of windowPos",
        f"set widthGap to {screen_width} - windowWidth",
        f"set heightGap to {screen_height} - windowHeight",
        "if widthGap < 0 then set widthGap to -widthGap",
        "if heightGap < 0 then set heightGap to -heightGap",
        "set absX to windowX",
        "if absX < 0 then set absX to -absX",
        "set absY to windowY",
        "if absY < 0 then set absY to -absY",
        f"if widthGap <= {coverage_tolerance} and heightGap <= {coverage_tolerance} and absX <= {coverage_tolerance} and absY <= {coverage_tolerance} then set coversScreen to true",
        'end try',
        "if isFullscreen or coversScreen then set slideshowReady to true",
        "end if",
        "end repeat",
        "if slideshowReady is true then return",
        "delay 0.25",
        "end repeat",
        f'error "Window containing {contains} did not enter fullscreen and does not cover the screen"',
    ])


def require_path(path, description):
    resolved_path = Path(path).expanduser().resolve()
    if not resolved_path.is_file():
        raise FileNotFoundError(f"{description} not found: {resolved_path}")
    return resolved_path


def load_items(path):
    items_path = require_path(path, "Items file")
    with items_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if "items" not in payload:
        raise KeyError("Items file must contain an items array")
    if not isinstance(payload["items"], list):
        raise TypeError("Items file key items must be a list")
    if len(payload["items"]) == 0:
        raise ValueError("Items file must contain at least one item")
    return payload["items"]


def read_transcript(item, label):
    if "transcript_path" not in item:
        raise KeyError(f"{label} is missing transcript_path")

    transcript_path = require_path(item["transcript_path"], f"{label} transcript")
    transcript = transcript_path.read_text(encoding="utf-8").strip()
    if transcript == "":
        raise ValueError(f"{label} transcript is empty")
    return transcript


def audio_path(item, label):
    if "audio_path" not in item:
        raise KeyError(f"{label} is missing audio_path")
    return require_path(item["audio_path"], f"{label} audio")


def normalize_item(item, index, cue_marker, expected_cue_count):
    label = slide_label(item, index)
    transcript = read_transcript(item, label)
    segments = split_segments(label, transcript, cue_marker)
    validate_cue_count(segments, label, expected_cue_count)
    return {
        "index": index,
        "label": label,
        "identity": {
            "field": SLIDE_IDENTITY_FIELD,
            "value": item[SLIDE_IDENTITY_FIELD],
        },
        "transcript": transcript,
        "segments": segments,
        "expected_cue_count": expected_cue_count,
        "audio_path": audio_path(item, label),
    }


def word_count(text):
    return len(re.findall(r"[^\W_]+(?:'[^\W_]+)?", text, flags=re.UNICODE))


def split_segments(label, transcript, cue_marker):
    segments = [segment.strip() for segment in transcript.split(cue_marker)]
    for index, segment in enumerate(segments, start=1):
        if segment == "":
            raise ValueError(f"{label} has an empty segment at position {index}")
        if word_count(segment) == 0:
            raise ValueError(f"{label} segment {index} has no countable words")
    return segments


def validate_cue_count(segments, label, expected_cue_count):
    actual_cue_count = len(segments) - 1
    if actual_cue_count != expected_cue_count:
        raise ValueError(
            f"{label.lower()} has {actual_cue_count} cue marker "
            f"but deck has {expected_cue_count} animations"
        )


def audio_duration(path):
    output = capture([
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ])
    return float(output)


def generate_silence(path, duration_seconds):
    run([
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=mono",
        "-t",
        str(duration_seconds),
        str(path),
    ])


def normalize_audio(input_path, output_path):
    run([
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-ar",
        "44100",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ])


def write_concat_file(path, audio_files):
    lines = []
    for audio_file in audio_files:
        lines.append(f"file {shlex.quote(str(audio_file))}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cue_offsets_from_word_ratio(label, segments, duration_seconds):
    total_words = sum(word_count(segment) for segment in segments)
    if total_words == 0:
        raise ValueError(f"{label} has no countable words")

    offsets = []
    consumed_words = 0
    for segment in segments[:-1]:
        consumed_words = consumed_words + word_count(segment)
        offsets.append(duration_seconds * consumed_words / total_words)
    return offsets


def slide_animation_count_from_xml(slide_xml):
    root = ElementTree.fromstring(slide_xml)
    namespace = {"p": PRESENTATIONML_NAMESPACE}
    return len(root.findall(".//p:timing/p:tnLst//p:cTn[@nodeType='clickEffect']", namespace))


def slide_layout_member_for_slide(deck, slide_number):
    """Return the ``ppt/slideLayouts/<name>.xml`` member a slide references, or None.

    Pluralsight-templated decks define their click-build animations on the
    slide's slideLayout rather than on ``slide{N}.xml``. Resolve the layout from
    the slide's relationship part so its animations can be counted too. A missing
    or malformed rels part is treated as "no layout" rather than an error.
    """
    rels_path = f"ppt/slides/_rels/slide{slide_number}.xml.rels"
    try:
        rels_xml = deck.read(rels_path)
    except KeyError:
        return None

    try:
        rels_root = ElementTree.fromstring(rels_xml)
    except ElementTree.ParseError:
        return None

    relationship_tag = f"{{{PACKAGE_RELATIONSHIPS_NAMESPACE}}}Relationship"
    for relationship in rels_root.iter(relationship_tag):
        relationship_type = relationship.get("Type", "")
        target = relationship.get("Target", "")
        if relationship_type.endswith(SLIDE_LAYOUT_RELATIONSHIP_SUFFIX) and target:
            return f"ppt/slideLayouts/{Path(target).name}"
    return None


def slide_layout_animation_count(deck, slide_number):
    layout_member = slide_layout_member_for_slide(deck, slide_number)
    if layout_member is None:
        return 0
    try:
        layout_xml = deck.read(layout_member)
    except KeyError:
        return 0
    return slide_animation_count_from_xml(layout_xml)


def slide_animation_counts(deck_path, slide_numbers):
    counts = {}
    try:
        with zipfile.ZipFile(deck_path) as deck:
            for slide_number in slide_numbers:
                slide_xml_path = f"ppt/slides/slide{slide_number}.xml"
                try:
                    slide_xml = deck.read(slide_xml_path)
                except KeyError as error:
                    raise FileNotFoundError(f"Slide {slide_number} XML not found in deck: {slide_xml_path}") from error
                counts[slide_number] = (
                    slide_animation_count_from_xml(slide_xml)
                    + slide_layout_animation_count(deck, slide_number)
                )
    except zipfile.BadZipFile as error:
        raise ValueError(f"PowerPoint deck is not a readable OOXML presentation: {deck_path}") from error
    return counts


def requested_slide_numbers(items):
    slide_numbers = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise TypeError(f"Item {index} must be an object")
        slide_label(item, index)
        slide_numbers.append(item[SLIDE_IDENTITY_FIELD])
    return slide_numbers


def validate_items(items, cue_marker, animation_counts):
    if cue_marker == "":
        raise ValueError("--cue-marker cannot be empty")

    prepared_items = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise TypeError(f"Item {index} must be an object")

        slide_number = item[SLIDE_IDENTITY_FIELD]
        expected_cue_count = animation_counts[slide_number]
        prepared_items.append(normalize_item(item, index, cue_marker, expected_cue_count))

    for previous, current in zip(prepared_items, prepared_items[1:]):
        expected_identity = previous["identity"]["value"] + 1
        if current["identity"]["value"] != expected_identity:
            raise ValueError(
                f"{SLIDE_LABEL_PREFIX} items must be consecutive; "
                f"expected {SLIDE_IDENTITY_FIELD} {expected_identity}, got {SLIDE_IDENTITY_FIELD} {current['identity']['value']}"
            )

    return prepared_items


def build_config(args):
    deck_path = require_path(args.deck, "PowerPoint deck")
    items = load_items(args.items)
    animation_counts = slide_animation_counts(deck_path, requested_slide_numbers(items))
    prepared_items = validate_items(items, args.cue_marker, animation_counts)
    return {
        "deck_path": str(deck_path),
        "items": prepared_items,
        "output_path": str(Path(args.output).expanduser().resolve()),
        "work_dir": str(Path(args.work_dir).expanduser().resolve()),
        "ffmpeg_video_input": args.video_input,
        "ffmpeg_framerate": args.framerate,
        "output_width": args.output_width,
        "output_height": args.output_height,
        "force_resolution": args.force_resolution,
        "force_aspect_ratio": args.force_aspect_ratio,
        "recording_lead_seconds": args.recording_lead_seconds,
        "slide_pause_seconds": args.slide_pause_seconds,
        "slideshow_start_seconds": args.slideshow_start_seconds,
        "cue_marker": args.cue_marker,
    }


def prepare(config):
    work_dir = Path(config["work_dir"])
    audio_dir = work_dir / "audio"
    plan_path = work_dir / "timing-plan.json"
    narration_path = work_dir / "narration.wav"
    concat_path = work_dir / "concat.txt"
    lead_silence = audio_dir / "silence-lead.wav"
    inter_slide_silence = audio_dir / "silence-slide.wav"

    audio_dir.mkdir(parents=True, exist_ok=True)

    generate_silence(lead_silence, config["recording_lead_seconds"])
    generate_silence(inter_slide_silence, config["slide_pause_seconds"])

    timeline_seconds = config["recording_lead_seconds"]
    audio_files = [lead_silence]
    actions = []
    item_plans = []

    for item_index, item in enumerate(config["items"]):
        normalized_audio_path = audio_dir / f"item-{item['index']:03d}.wav"
        normalize_audio(item["audio_path"], normalized_audio_path)
        duration_seconds = audio_duration(normalized_audio_path)
        item_started_at = timeline_seconds
        cue_offsets = cue_offsets_from_word_ratio(item["label"], item["segments"], duration_seconds)

        audio_files.append(normalized_audio_path)
        for cue_offset in cue_offsets:
            actions.append({
                "at_seconds": round(item_started_at + cue_offset, 3),
                "key": "space",
                "item": item["label"],
                "reason": "action cue",
            })

        timeline_seconds = timeline_seconds + duration_seconds

        if item_index < len(config["items"]) - 1:
            for inter_item_action in INTER_SLIDE_ACTIONS:
                actions.append({
                    "at_seconds": round(timeline_seconds, 3),
                    "key": inter_item_action["key"],
                    "item": item["label"],
                    "reason": inter_item_action["reason"],
                })
            audio_files.append(inter_slide_silence)
            timeline_seconds = timeline_seconds + config["slide_pause_seconds"]

        item_plans.append({
            "label": item["label"],
            "identity": item["identity"],
            "cue_count": len(item["segments"]) - 1,
            "audio": str(item["audio_path"]),
            "duration_seconds": duration_seconds,
            "cue_timing_method": "word-ratio",
        })

    write_concat_file(concat_path, audio_files)
    run([
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-c",
        "copy",
        str(narration_path),
    ])

    plan = {
        "deck_path": config["deck_path"],
        "cue_marker": config["cue_marker"],
        "narration_audio": str(narration_path),
        "duration_seconds": round(audio_duration(narration_path), 3),
        "actions": actions,
        "items": item_plans,
    }
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return plan


def press_space():
    execute_ui_actions([{
        "action": "key_code",
        "code": 49,
    }])


def parse_screen_point_size(output):
    parts = [part.strip() for part in output.split(",")]
    if len(parts) != 4:
        raise ValueError(f"Unexpected desktop bounds response: {output}")
    left, top, right, bottom = (int(part) for part in parts)
    return right - left, bottom - top


def screen_point_size():
    output = capture_osascript('tell application "Finder" to get bounds of window of desktop')
    return parse_screen_point_size(output)


def force_slideshow_fullscreen():
    screen_width, screen_height = screen_point_size()
    execute_ui_actions([
        {
            "action": "activate_app",
            "app": "Microsoft PowerPoint",
        },
        {
            "action": "fullscreen_window",
            "process": "Microsoft PowerPoint",
            "contains": "Slide Show",
            "screen_width": screen_width,
            "screen_height": screen_height,
        },
    ])


def powerpoint_is_running():
    output = capture_osascript('application "Microsoft PowerPoint" is running')
    if output not in ["true", "false"]:
        raise RuntimeError(f"Unexpected PowerPoint running response: {output}")
    return output == "true"


def presentation_is_open(deck_path):
    resolved_deck_path = str(Path(deck_path).expanduser().resolve())
    output = capture_osascript(
        "on run argv",
        "set requestedPath to item 1 of argv",
        'if application "Microsoft PowerPoint" is not running then return "false"',
        'tell application "Microsoft PowerPoint"',
        "with timeout of 10 seconds",
        "repeat with presentationIndex from 1 to count of presentations",
        "try",
        "set currentPath to full name of presentation presentationIndex as text",
        "if currentPath is requestedPath then return \"true\"",
        "end try",
        "end repeat",
        "end timeout",
        "end tell",
        "return \"false\"",
        "end run",
        args=[resolved_deck_path],
    )
    if output not in ["true", "false"]:
        raise RuntimeError(f"Unexpected presentation open response: {output}")
    return output == "true"


def create_powerpoint_state(config):
    deck_path = Path(config["deck_path"])
    powerpoint_was_running = powerpoint_is_running()
    return {
        "powerpoint_was_running": powerpoint_was_running,
        "deck_was_open": powerpoint_was_running and presentation_is_open(deck_path),
    }


DIALOG_FIELD_SEPARATOR = "\x1f"
DIALOG_TEXT_SEPARATOR = "\x1e"


def render_frontmost_powerpoint_dialog():
    """AppleScript that reports the frontmost PowerPoint blocking dialog, if any.

    Emits ``<has-dialog><US><title><US><joined-static-text>`` where has-dialog is
    "true"/"false", the title is the dialog/sheet window name, and the static text
    is every visible static-text value joined by a record separator. A window only
    counts as a blocking dialog when it owns a sheet OR its subrole is an Apple
    dialog/system-dialog subrole, so the live Slide Show / presentation window is
    never misread as a modal. Each query is wrapped in ``try`` so a window that
    refuses an attribute cannot abort the whole probe.
    """
    return [
        'if application "Microsoft PowerPoint" is not running then return "false" & "%s" & "" & "%s" & ""' % (
            DIALOG_FIELD_SEPARATOR,
            DIALOG_FIELD_SEPARATOR,
        ),
        'tell application "System Events"',
        'tell process "Microsoft PowerPoint"',
        "set dialogTitle to \"\"",
        "set dialogText to \"\"",
        "set hasDialog to false",
        "repeat with currentWindow in windows",
        "set isDialog to false",
        "try",
        "if (count of sheets of currentWindow) > 0 then set isDialog to true",
        "end try",
        "try",
        "set windowSubrole to subrole of currentWindow",
        'if windowSubrole is "AXDialog" or windowSubrole is "AXSystemDialog" then set isDialog to true',
        "end try",
        "if isDialog then",
        "set hasDialog to true",
        "try",
        "set dialogTitle to name of currentWindow as text",
        "end try",
        "try",
        "set staticTexts to value of every static text of currentWindow",
        "repeat with staticTextValue in staticTexts",
        "try",
        'set dialogText to dialogText & (staticTextValue as text) & "%s"' % DIALOG_TEXT_SEPARATOR,
        "end try",
        "end repeat",
        "end try",
        "try",
        "set sheetStaticTexts to value of every static text of sheets of currentWindow",
        "repeat with sheetStaticTextValue in sheetStaticTexts",
        "try",
        'set dialogText to dialogText & (sheetStaticTextValue as text) & "%s"' % DIALOG_TEXT_SEPARATOR,
        "end try",
        "end repeat",
        "end try",
        "exit repeat",
        "end if",
        "end repeat",
        "end tell",
        'return (hasDialog as text) & "%s" & dialogTitle & "%s" & dialogText' % (
            DIALOG_FIELD_SEPARATOR,
            DIALOG_FIELD_SEPARATOR,
        ),
        "end tell",
    ]


def parse_frontmost_dialog_payload(output):
    """Parse the dialog probe payload, treating anything ill-formed as "no dialog".

    The dialog probe is best-effort convenience, not a recording step. The
    live-process System Events path can return a bare ``false`` (or an empty /
    AppleScript-error string) instead of the 3-field ``\\x1f``-delimited payload
    when AX is not ready yet or an Automation consent gate intercepts the event.
    Any response that is not a well-formed 3-field payload — bare ``false``,
    empty string, or an AppleScript error string — is read as "no dialog
    detected" and returns ``None`` rather than raising, so a probe that cannot
    read dialog state never crashes the recorder.
    """
    parts = output.split(DIALOG_FIELD_SEPARATOR)
    if len(parts) != 3:
        return None
    has_dialog = parts[0].strip() == "true"
    if not has_dialog:
        return None
    title = parts[1].strip()
    text = " ".join(
        segment.strip()
        for segment in parts[2].split(DIALOG_TEXT_SEPARATOR)
        if segment.strip() != ""
    )
    return {"title": title, "text": text}


def frontmost_powerpoint_dialog():
    """Return the frontmost PowerPoint blocking dialog as ``{title, text}`` or None.

    Best-effort and never fatal. Any failure reading dialog state — a hard
    osascript subprocess timeout, an AppleScript / System Events / AX error, or an
    ill-formed payload — is treated as "no dialog detected" (returns ``None``) and
    the underlying stderr is logged so a genuine Automation consent gate stays
    diagnosable. An AX-not-ready race right after launch is ridden out by
    re-probing a few times with short sleeps before concluding "no dialog".
    """
    last_error = None
    for attempt in range(DIALOG_PROBE_ATTEMPTS):
        try:
            output = capture_osascript(*render_frontmost_powerpoint_dialog())
        # Best-effort by design: ANY failure reading dialog state (osascript
        # timeout, System Events / AX / Automation-consent error, ill-formed
        # output) is non-fatal and read as "no dialog detected".
        except Exception as error:  # noqa: BLE001 - intentional best-effort catch-all
            last_error = error
        else:
            return parse_frontmost_dialog_payload(output)
        if attempt < DIALOG_PROBE_ATTEMPTS - 1:
            time.sleep(DIALOG_PROBE_RETRY_SECONDS)

    if last_error is not None:
        log_warning(
            "PowerPoint dialog probe could not read dialog state; proceeding as "
            f"if no dialog is present. Underlying osascript error: {last_error}"
        )
    return None


def dialog_matches_catalog_entry(entry, title, text):
    title_lower = title.lower()
    text_lower = text.lower()
    for needle in entry["title_contains"]:
        if needle.lower() in title_lower:
            return True
    for needle in entry["text_contains"]:
        if needle.lower() in text_lower:
            return True
    return False


def match_startup_dialog(dialog):
    for entry in POWERPOINT_STARTUP_DIALOGS:
        if dialog_matches_catalog_entry(entry, dialog["title"], dialog["text"]):
            return entry
    return None


def render_dismiss_dialog_button(button_names):
    """AppleScript that clicks the first present benign button, else presses Escape.

    Searches the frontmost PowerPoint window and any sheet it owns for a button
    whose name matches one of ``button_names`` (in priority order) and clicks it.
    When no listed button is present it presses Escape, the safe default for a
    benign startup sheet. Returns the name of the clicked button, or "escape".
    """
    lines = [
        'tell application "Microsoft PowerPoint" to activate',
        'tell application "System Events"',
        'tell process "Microsoft PowerPoint"',
        "set clicked to \"\"",
    ]
    for button_name in button_names:
        quoted = quote_applescript_text(button_name)
        lines.extend([
            'if clicked is "" then',
            "try",
            f'click button "{quoted}" of front window',
            f'set clicked to "{quoted}"',
            "end try",
            "end if",
            'if clicked is "" then',
            "try",
            f'click button "{quoted}" of sheet 1 of front window',
            f'set clicked to "{quoted}"',
            "end try",
            "end if",
        ])
    lines.extend([
        'if clicked is "" then',
        "key code 53",
        'set clicked to "escape"',
        "end if",
        "return clicked",
        "end tell",
        "end tell",
    ])
    return lines


def try_auto_dismiss_startup_dialog():
    """Best-effort auto-dismiss of a benign PowerPoint startup dialog. Never fatal.

    Auto-dismissing benign startup sheets (sign-in, 'What's New', Document
    Recovery, update prompts, first-run) is a CONVENIENCE that smooths recording;
    it must never block or crash the run. Returns the matched catalog entry's name
    when a known benign dialog was dismissed, otherwise ``None`` — no dialog in
    front, an unrecognized dialog (logged and left alone — never blindly clicked),
    or any failure reading/dismissing dialog state. The actual recording steps
    (``open_deck`` and the slideshow drive) remain the fail-fast gates; this probe
    never decides success or failure of the recording.
    """
    dialog = frontmost_powerpoint_dialog()
    if dialog is None:
        return None

    entry = match_startup_dialog(dialog)
    if entry is None:
        log_warning(
            "An unrecognized PowerPoint dialog is in front and was NOT auto-dismissed "
            f"(title={dialog['title']!r}, text={dialog['text']!r}). Proceeding; if the "
            "deck does not open or the slideshow does not start, dismiss it manually "
            "and retry."
        )
        return None

    try:
        capture_osascript(*render_dismiss_dialog_button(entry["dismiss_button"]))
    except Exception as error:  # noqa: BLE001 - dismiss is best-effort, never fatal
        log_warning(
            f"Could not auto-dismiss the benign PowerPoint '{entry['name']}' dialog; "
            f"proceeding. Underlying osascript error: {error}"
        )
        return None
    return entry["name"]


def open_deck_failure_error(deck_path, last_dialog):
    powerpoint_running = powerpoint_is_running()
    if last_dialog is not None:
        cause = (
            f"A PowerPoint dialog is still blocking automation "
            f"(title={last_dialog['title']!r}, text={last_dialog['text']!r}); "
            "dismiss it manually, then retry."
        )
    else:
        cause = (
            "The most likely cause is a blocking PowerPoint modal / first-run dialog "
            "(sign-in, 'What's New', Document Recovery, update prompt) or a pending "
            "macOS Automation (AppleEvents) consent prompt for controlling PowerPoint. "
            "Dismiss any open PowerPoint dialog and grant Automation access (System "
            "Settings -> Privacy & Security -> Automation), then retry."
        )
    return RuntimeError(
        f"PowerPoint deck did not open: {deck_path} "
        f"(PowerPoint running: {powerpoint_running}). {cause}"
    )


def open_deck(config):
    deck_path = Path(config["deck_path"])
    if presentation_is_open(deck_path):
        return

    run(["open", "-a", "Microsoft PowerPoint", str(deck_path)])

    # Bounded open/dismiss/recheck loop: poll for the deck to open, and on each
    # cycle best-effort auto-dismiss a recognized benign startup dialog so a
    # transient first-run / sign-in / recovery / update sheet does not delay the
    # open. The dismiss step is a convenience and never fatal (an unreadable probe
    # or unknown dialog is logged and skipped). Whether the deck actually opened is
    # the fail-fast gate: if it never opens within the budget, raise loudly.
    last_dialog = None
    for _ in range(OPEN_DECK_DISMISS_ATTEMPTS):
        deadline = time.monotonic() + (OSASCRIPT_TIMEOUT_SECONDS / OPEN_DECK_DISMISS_ATTEMPTS)
        while time.monotonic() < deadline:
            if presentation_is_open(deck_path):
                return
            time.sleep(0.5)

        last_dialog = frontmost_powerpoint_dialog()
        if last_dialog is None:
            continue
        try_auto_dismiss_startup_dialog()
        if presentation_is_open(deck_path):
            return

    raise open_deck_failure_error(deck_path, last_dialog)


def render_run_slideshow_range(starting_slide, ending_slide):
    """AppleScript that starts the slideshow on a custom slide range.

    PowerPoint's "Play from Start" always begins on slide 1, and typing a slide
    number to jump is unreliable in the live show: the digit is dropped and the
    show lands on slide 2, which silently desynchronizes every slide from its
    narration and makes the per-cue Space presses fire against the wrong slides
    (so click-build reveals never line up). Starting a custom slide-show range
    begins the show directly on ``starting_slide`` in build-pending state, so the
    click-build animations fire on Space exactly as in a normal linear run from
    slide 1. Advance mode is forced to manual advance so a deck authored with
    automatic slide timings cannot self-advance ahead of the narration.
    """
    return [
        'tell application "Microsoft PowerPoint"',
        "activate",
        "set slideShowSettings to slide show settings of active presentation",
        "set range type of slideShowSettings to slide show range",
        f"set starting slide of slideShowSettings to {int(starting_slide)}",
        f"set ending slide of slideShowSettings to {int(ending_slide)}",
        "set advance mode of slideShowSettings to slide show advance manual advance",
        "run slide show slideShowSettings",
        "end tell",
    ]


def clear_benign_dialogs_before_slideshow():
    """Best-effort clear of benign PowerPoint startup dialogs before the drive. Never fatal.

    PowerPoint can surface a startup/first-run sheet between opening the deck and
    the slideshow drive. Best-effort auto-dismiss recognized benign ones (bounded);
    stop as soon as none is dismissed. This is a CONVENIENCE — it never raises and
    never blocks. A remaining unrecognized/unclearable dialog is logged (via
    ``try_auto_dismiss_startup_dialog``) and left alone; the slideshow drive that
    follows is the fail-fast gate, so a genuine blocker still surfaces loudly there
    rather than being silently waited on here.
    """
    for _ in range(OPEN_DECK_DISMISS_ATTEMPTS):
        if frontmost_powerpoint_dialog() is None:
            return
        if try_auto_dismiss_startup_dialog() is None:
            # Nothing benign was dismissed this cycle (no dialog, an unrecognized
            # one already logged, or an unreadable probe). Stop; do not spin or raise.
            return
        time.sleep(0.5)


def start_slideshow(config):
    open_deck(config)
    clear_benign_dialogs_before_slideshow()
    starting_slide = config["items"][0]["identity"]["value"]
    ending_slide = config["items"][-1]["identity"]["value"]
    run_osascript(*render_run_slideshow_range(starting_slide, ending_slide))
    execute_ui_actions([
        {
            "action": "delay",
            "seconds": 1,
        },
        {
            "action": "assert_window",
            "process": "Microsoft PowerPoint",
            "contains": "Slide Show",
        },
    ])
    force_slideshow_fullscreen()
    time.sleep(config["slideshow_start_seconds"])


def close_slideshow_and_deck(config, state):
    if not state["powerpoint_was_running"]:
        execute_ui_actions([
            {
                "action": "key_code",
                "code": 53,
            },
            {
                "action": "delay",
                "seconds": 0.5,
            },
            {
                "action": "quit_app",
                "app": "Microsoft PowerPoint",
                "saving": "no",
            },
        ])
        return

    if not state["deck_was_open"]:
        execute_ui_actions([
            {
                "action": "key_code",
                "code": 53,
            },
            {
                "action": "delay",
                "seconds": 0.5,
            },
            {
                "action": "activate_app",
                "app": "Microsoft PowerPoint",
            },
            {
                "action": "keystroke_command",
                "text": "w",
            },
        ])
        return

    execute_ui_actions([{
        "action": "key_code",
        "code": 53,
    }])


def stop_audio_process(audio_process):
    if audio_process is None:
        return
    if audio_process.poll() is None:
        audio_process.terminate()
        audio_process.wait(timeout=10)


def stop_ffmpeg_process(ffmpeg_process):
    if ffmpeg_process is None:
        return
    if ffmpeg_process.poll() is not None:
        return
    if ffmpeg_process.stdin is None:
        raise RuntimeError("ffmpeg stdin pipe was not created")
    ffmpeg_process.stdin.write(b"q")
    ffmpeg_process.stdin.flush()
    ffmpeg_process.wait(timeout=10)


def run_cleanup(cleanup_errors, description, cleanup_function):
    try:
        cleanup_function()
    except Exception as error:
        cleanup_errors.append(f"{description}: {error}")


def ensure_process_running(process, description):
    return_code = process.poll()
    if return_code is not None:
        raise RuntimeError(f"{description} exited with code {return_code}")


def sleep_until(target_time, monitored_processes):
    while True:
        for process, description in monitored_processes:
            ensure_process_running(process, description)

        sleep_seconds = target_time - time.monotonic()
        if sleep_seconds <= 0:
            return
        time.sleep(min(sleep_seconds, 0.1))


def wait_for_audio(audio_process, ffmpeg_process):
    while True:
        ensure_process_running(ffmpeg_process, "ffmpeg screen recording")
        audio_return_code = audio_process.poll()
        if audio_return_code is not None:
            return audio_return_code
        time.sleep(0.1)


def record(config):
    display_restore_mode = None
    state = None
    ffmpeg_process = None
    audio_process = None
    primary_error = None
    cleanup_errors = []
    try:
        if config["force_resolution"] and config["force_aspect_ratio"] is not None:
            raise ValueError("--force-resolution and --force-aspect-ratio are mutually exclusive")
        if config["force_aspect_ratio"] is not None:
            display_restore_mode = current_display_mode()
            aspect_width, aspect_height = config["force_aspect_ratio"]
            # Pick the highest-usable-area mode that can yield the output aspect ratio.
            # On a panel with a true matching mode (e.g. an external 16:9 monitor) that
            # exact mode wins and records uncropped. On a panel that only advertises a
            # near ratio (e.g. the built-in 16:10 Liquid Retina XDR), the best 16:10
            # mode is chosen and the centered 16:9 slide region is cropped below, so no
            # external 16:9 display is required.
            forced_mode = best_display_mode_for_aspect_ratio(
                available_display_modes(),
                aspect_width,
                aspect_height,
                config["output_width"],
                config["output_height"],
            )
            set_display_resolution(forced_mode["pixel_width"], forced_mode["pixel_height"])

        source_width, source_height = probe_capture_dimensions(config["ffmpeg_video_input"], config["ffmpeg_framerate"])
        if config["force_resolution"] and (source_width, source_height) != (config["output_width"], config["output_height"]):
            # The user explicitly demanded this exact display mode. Switch to it (when
            # that mode exists) and re-probe so the capture matches the output exactly,
            # rather than relying on the centered-crop fallback.
            display_restore_mode = current_display_mode()
            set_display_resolution(config["output_width"], config["output_height"])
            source_width, source_height = probe_capture_dimensions(config["ffmpeg_video_input"], config["ffmpeg_framerate"])
        crop_plan = capture_crop_plan(
            source_width,
            source_height,
            config["output_width"],
            config["output_height"],
            config["ffmpeg_video_input"],
        )

        plan = prepare(config)
        work_dir = Path(config["work_dir"])
        output_path = Path(config["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        raw_video_path = work_dir / "screen-recording.mov"
        narration_path = Path(plan["narration_audio"])

        state = create_powerpoint_state(config)
        start_slideshow(config)
        ffmpeg_process = subprocess.Popen([
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "avfoundation",
            "-framerate",
            str(config["ffmpeg_framerate"]),
            "-i",
            str(config["ffmpeg_video_input"]),
            "-pix_fmt",
            "yuv420p",
            str(raw_video_path),
        ], stdin=subprocess.PIPE)
        ensure_process_running(ffmpeg_process, "ffmpeg screen recording")

        started_at = time.monotonic()
        audio_process = subprocess.Popen(["afplay", str(narration_path)])
        ensure_process_running(audio_process, "afplay")
        monitored_processes = [
            (ffmpeg_process, "ffmpeg screen recording"),
            (audio_process, "afplay"),
        ]

        for action in plan["actions"]:
            target_time = started_at + action["at_seconds"]
            sleep_until(target_time, monitored_processes)
            for process, description in monitored_processes:
                ensure_process_running(process, description)
            press_space()

        audio_return_code = wait_for_audio(audio_process, ffmpeg_process)
        if audio_return_code != 0:
            raise RuntimeError(f"afplay exited with code {audio_return_code}")

        stop_ffmpeg_process(ffmpeg_process)
        ffmpeg_return_code = ffmpeg_process.returncode
        if ffmpeg_return_code != 0:
            raise RuntimeError(f"ffmpeg screen recording exited with code {ffmpeg_return_code}")

        close_slideshow_and_deck(config, state)
        state = None

        scale_filter = f"scale={config['output_width']}:{config['output_height']}"
        if crop_plan is None:
            video_filter = scale_filter
        else:
            crop_width, crop_height, crop_x, crop_y = crop_plan
            video_filter = f"crop={crop_width}:{crop_height}:{crop_x}:{crop_y},{scale_filter}"
            print(
                f"Capture {source_width}x{source_height} != output AR "
                f"{config['output_width']}x{config['output_height']}; cropping centered "
                f"{crop_width}x{crop_height} -> scaling to "
                f"{config['output_width']}x{config['output_height']}",
                file=sys.stderr,
            )

        run([
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(raw_video_path),
            "-i",
            str(narration_path),
            "-c:v",
            "libx264",
            "-vf",
            video_filter,
            "-c:a",
            "aac",
            "-shortest",
            str(output_path),
        ])
    except Exception as error:
        primary_error = error
    finally:
        run_cleanup(cleanup_errors, "stop audio playback", lambda: stop_audio_process(audio_process))
        run_cleanup(cleanup_errors, "stop screen recording", lambda: stop_ffmpeg_process(ffmpeg_process))
        if state is not None:
            run_cleanup(cleanup_errors, "close PowerPoint slideshow and deck", lambda: close_slideshow_and_deck(config, state))
        if display_restore_mode is not None:
            run_cleanup(cleanup_errors, "restore display resolution", lambda: set_display_resolution(
                display_restore_mode["width"],
                display_restore_mode["height"],
            ))

    if primary_error is not None and cleanup_errors:
        raise RuntimeError(f"{primary_error}; cleanup failed: " + "; ".join(cleanup_errors)) from primary_error

    if primary_error is not None:
        raise primary_error

    if cleanup_errors:
        raise RuntimeError("Cleanup failed: " + "; ".join(cleanup_errors))

    return {
        "output_path": str(output_path),
        "timing_plan_path": str(work_dir / "timing-plan.json"),
        "timing_plan": plan,
    }
