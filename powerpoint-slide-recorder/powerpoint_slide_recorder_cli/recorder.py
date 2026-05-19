#!/usr/bin/env python3
import json
import re
import shlex
import subprocess
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
SLIDE_IDENTITY_FIELD = "slide"
SLIDE_LABEL_PREFIX = "Slide"
INTER_SLIDE_ACTIONS = [{
    "key": "space",
    "reason": "next slide",
}]
PRESENTATIONML_NAMESPACE = "http://schemas.openxmlformats.org/presentationml/2006/main"


def slide_label(item, index):
    if SLIDE_IDENTITY_FIELD not in item:
        raise KeyError(f"{SLIDE_LABEL_PREFIX} item {index} is missing {SLIDE_IDENTITY_FIELD}")
    if not isinstance(item[SLIDE_IDENTITY_FIELD], int):
        raise TypeError(f"{SLIDE_LABEL_PREFIX} item {index} {SLIDE_IDENTITY_FIELD} must be int")
    if item[SLIDE_IDENTITY_FIELD] < 1:
        raise ValueError(f"{SLIDE_LABEL_PREFIX} item {index} {SLIDE_IDENTITY_FIELD} must be greater than zero")
    return f"{SLIDE_LABEL_PREFIX} {item[SLIDE_IDENTITY_FIELD]}"


def run(command):
    subprocess.run(command, check=True)


def capture(command):
    completed = subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE)
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


def best_display_mode_for_aspect_ratio(modes, aspect_width, aspect_height):
    matches = []
    for mode in modes:
        if mode["pixel_width"] * aspect_height == aspect_width * mode["pixel_height"]:
            matches.append(mode)
    if len(matches) == 0:
        raise RuntimeError(
            f"No display mode with aspect ratio {aspect_width}x{aspect_height} is available on the main display"
        )
    return max(matches, key=lambda mode: (
        mode["pixel_width"] * mode["pixel_height"],
        mode["pixel_width"],
        mode["pixel_height"],
    ))


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


def validate_capture_resolution(source_width, source_height, output_width, output_height, video_input):
    if source_width * output_height != output_width * source_height:
        raise ValueError(
            f"Capture source {video_input} is {source_width}x{source_height}, "
            f"which does not match requested output aspect ratio {output_width}x{output_height}. "
            "Switch the display mode or --video-input capture source to the same aspect ratio before recording. "
            "Use --force-aspect-ratio for automatic display switching when a matching display mode is available."
        )
    if source_width < output_width or source_height < output_height:
        raise ValueError(
            f"Capture source {video_input} is {source_width}x{source_height}, "
            f"which is smaller than requested output {output_width}x{output_height}. "
            "Switch the display mode or --video-input capture source to at least the requested resolution before recording. "
            "Use --force-resolution for an exact display mode when that mode is available."
        )


def osascript(*lines, args=None):
    command = ["osascript"]
    for line in lines:
        command.extend(["-e", line])
    if args is not None:
        command.extend(args)
    return command


def run_osascript(*lines, args=None):
    run(osascript(*lines, args=args))


def capture_osascript(*lines, args=None):
    return capture(osascript(*lines, args=args))


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
        'perform action "AXRaise" of targetWindow',
        'set value of attribute "AXFullScreen" of targetWindow to true',
        "delay 1",
        "repeat 40 times",
        "set fullscreenReached to false",
        "repeat with currentWindow in windows",
        "set windowName to name of currentWindow as text",
        f'if windowName contains "{contains}" then',
        'if (value of attribute "AXFullScreen" of currentWindow) is true then set fullscreenReached to true',
        "end if",
        "end repeat",
        "if fullscreenReached is true then return",
        "delay 0.25",
        "end repeat",
        f'error "Window containing {contains} did not enter fullscreen"',
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
                counts[slide_number] = slide_animation_count_from_xml(slide_xml)
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


def force_slideshow_fullscreen():
    execute_ui_actions([
        {
            "action": "activate_app",
            "app": "Microsoft PowerPoint",
        },
        {
            "action": "fullscreen_window",
            "process": "Microsoft PowerPoint",
            "contains": "Slide Show",
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


def open_deck(config):
    deck_path = Path(config["deck_path"])
    if presentation_is_open(deck_path):
        return

    run(["open", "-a", "Microsoft PowerPoint", str(deck_path)])
    for _ in range(60):
        if presentation_is_open(deck_path):
            return
        time.sleep(0.5)

    raise RuntimeError(f"PowerPoint deck did not open: {deck_path}")


def start_slideshow(config):
    open_deck(config)
    execute_ui_actions([
        {
            "action": "activate_app",
            "app": "Microsoft PowerPoint",
        },
        {
            "action": "delay",
            "seconds": 0.5,
        },
        {
            "action": "menu_click",
            "process": "Microsoft PowerPoint",
            "menu": "Slide Show",
            "item": "Play from Start",
        },
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
    jump_to_slide(config["items"][0]["identity"]["value"])
    time.sleep(config["slideshow_start_seconds"])


def jump_to_slide(slide_number):
    if slide_number == 1:
        return
    execute_ui_actions([{
        "action": "key_stroke",
        "text": str(slide_number),
        "then_key_codes": [36],
    }])

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
            forced_mode = best_display_mode_for_aspect_ratio(available_display_modes(), aspect_width, aspect_height)
            set_display_resolution(forced_mode["pixel_width"], forced_mode["pixel_height"])

        source_width, source_height = probe_capture_dimensions(config["ffmpeg_video_input"], config["ffmpeg_framerate"])
        try:
            validate_capture_resolution(
                source_width,
                source_height,
                config["output_width"],
                config["output_height"],
                config["ffmpeg_video_input"],
            )
        except ValueError:
            if not config["force_resolution"]:
                raise
            display_restore_mode = current_display_mode()
            set_display_resolution(config["output_width"], config["output_height"])
            source_width, source_height = probe_capture_dimensions(config["ffmpeg_video_input"], config["ffmpeg_framerate"])
            validate_capture_resolution(
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
            f"scale={config['output_width']}:{config['output_height']}",
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
