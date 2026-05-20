import contextlib
import io
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from powerpoint_slide_recorder_cli.client import PowerPointSlideRecorderClient
from powerpoint_slide_recorder_cli.main import app
from powerpoint_slide_recorder_cli import recorder as record
from typer.testing import CliRunner


class FakeProcess:
    def __init__(self, poll_values, returncode):
        self.poll_values = list(poll_values)
        self.returncode = returncode
        self.stdin = mock.Mock()
        self.terminated = False

    def poll(self):
        if len(self.poll_values) == 0:
            return self.returncode
        return self.poll_values.pop(0)

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.terminated = True


def slide_config(root, **overrides):
    audio = root / "audio.wav"
    audio.write_bytes(b"audio")
    config = {
        "deck_path": "/tmp/deck.pptx",
        "items": [{
            "index": 1,
            "label": "Slide 1",
            "identity": {
                "field": "slide",
                "value": 1,
            },
            "segments": ["first", "second"],
            "audio_path": audio,
        }],
        "output_path": "/tmp/out.mp4",
        "work_dir": str(root / "work"),
        "ffmpeg_video_input": "3",
        "ffmpeg_framerate": 30,
        "output_width": 1920,
        "output_height": 1080,
        "force_resolution": False,
        "force_aspect_ratio": None,
        "recording_lead_seconds": 1.0,
        "slide_pause_seconds": 0.75,
        "cue_marker": "||",
    }
    config.update(overrides)
    return config


def write_deck(root, slide_animation_counts):
    deck = root / "deck.pptx"
    namespace = "http://schemas.openxmlformats.org/presentationml/2006/main"

    with zipfile.ZipFile(deck, "w") as archive:
        for slide_number, animation_count in slide_animation_counts.items():
            click_effects = "".join(
                f'<p:par><p:cTn id="{index + 2}" nodeType="clickEffect"/></p:par>'
                for index in range(animation_count)
            )
            slide_xml = (
                f'<p:sld xmlns:p="{namespace}">'
                "<p:cSld/>"
                "<p:timing><p:tnLst><p:par><p:cTn id=\"1\">"
                f"<p:childTnLst>{click_effects}</p:childTnLst>"
                "</p:cTn></p:par></p:tnLst></p:timing>"
                "</p:sld>"
            )
            archive.writestr(f"ppt/slides/slide{slide_number}.xml", slide_xml)

    return deck


class RecordTests(unittest.TestCase):
    def test_public_cli_uses_default_resolution(self):
        runner = CliRunner()
        fake_result = mock.Mock()

        with mock.patch("powerpoint_slide_recorder_cli.commands.get_client") as get_client, \
                mock.patch("powerpoint_slide_recorder_cli.commands.print_json"):
            get_client.return_value.record.return_value = fake_result
            result = runner.invoke(app, [
                "record",
                "--deck", "/tmp/deck.pptx",
                "--items", "/tmp/items.json",
                "--output", "/tmp/out.mp4",
                "--work-dir", "/tmp/work",
                "--video-input", "3",
            ])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(get_client.return_value.record.call_args.kwargs["output_width"], 1920)
        self.assertEqual(get_client.return_value.record.call_args.kwargs["output_height"], 1080)

    def test_public_cli_forwards_custom_resolution(self):
        runner = CliRunner()
        fake_result = mock.Mock()

        with mock.patch("powerpoint_slide_recorder_cli.commands.get_client") as get_client, \
                mock.patch("powerpoint_slide_recorder_cli.commands.print_json"):
            get_client.return_value.record.return_value = fake_result
            result = runner.invoke(app, [
                "record",
                "--deck", "/tmp/deck.pptx",
                "--items", "/tmp/items.json",
                "--output", "/tmp/out.mp4",
                "--work-dir", "/tmp/work",
                "--video-input", "3",
                "--resolution", "2560x1440",
            ])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(get_client.return_value.record.call_args.kwargs["output_width"], 2560)
        self.assertEqual(get_client.return_value.record.call_args.kwargs["output_height"], 1440)

    def test_public_cli_forwards_force_resolution(self):
        runner = CliRunner()
        fake_result = mock.Mock()

        with mock.patch("powerpoint_slide_recorder_cli.commands.get_client") as get_client, \
                mock.patch("powerpoint_slide_recorder_cli.commands.print_json"):
            get_client.return_value.record.return_value = fake_result
            result = runner.invoke(app, [
                "record",
                "--deck", "/tmp/deck.pptx",
                "--items", "/tmp/items.json",
                "--output", "/tmp/out.mp4",
                "--work-dir", "/tmp/work",
                "--video-input", "3",
                "--force-resolution",
            ])

        self.assertEqual(result.exit_code, 0)
        self.assertIs(get_client.return_value.record.call_args.kwargs["force_resolution"], True)
        self.assertIsNone(get_client.return_value.record.call_args.kwargs["force_aspect_ratio"])

    def test_public_cli_forwards_force_aspect_ratio(self):
        runner = CliRunner()
        fake_result = mock.Mock()

        with mock.patch("powerpoint_slide_recorder_cli.commands.get_client") as get_client, \
                mock.patch("powerpoint_slide_recorder_cli.commands.print_json"):
            get_client.return_value.record.return_value = fake_result
            result = runner.invoke(app, [
                "record",
                "--deck", "/tmp/deck.pptx",
                "--items", "/tmp/items.json",
                "--output", "/tmp/out.mp4",
                "--work-dir", "/tmp/work",
                "--video-input", "3",
                "--force-aspect-ratio", "16x9",
            ])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(get_client.return_value.record.call_args.kwargs["force_aspect_ratio"], (16, 9))
        self.assertIs(get_client.return_value.record.call_args.kwargs["force_resolution"], False)

    def test_public_cli_rejects_force_resolution_with_force_aspect_ratio(self):
        runner = CliRunner()

        result = runner.invoke(app, [
            "record",
            "--deck", "/tmp/deck.pptx",
            "--items", "/tmp/items.json",
            "--output", "/tmp/out.mp4",
            "--work-dir", "/tmp/work",
            "--video-input", "3",
            "--force-resolution",
            "--force-aspect-ratio", "16x9",
        ])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--force-resolution and --force-aspect-ratio are mutually exclusive", result.output)

    def test_public_cli_does_not_accept_prepare_only(self):
        runner = CliRunner()

        result = runner.invoke(app, [
            "record",
            "--deck", "/tmp/deck.pptx",
            "--items", "/tmp/items.json",
            "--output", "/tmp/out.mp4",
            "--work-dir", "/tmp/work",
            "--video-input", "3",
            "--prepare-only",
        ])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("No such option: --prepare-only", result.output)

    def test_public_cli_does_not_accept_type(self):
        runner = CliRunner()

        result = runner.invoke(app, [
            "record",
            "--deck", "/tmp/deck.pptx",
            "--items", "/tmp/items.json",
            "--output", "/tmp/out.mp4",
            "--work-dir", "/tmp/work",
            "--video-input", "3",
            "--type", "slide",
        ])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("No such option: --type", result.output)

    def test_parse_resolution_accepts_width_by_height(self):
        self.assertEqual(record.parse_resolution("1920x1080"), (1920, 1080))

    def test_parse_resolution_rejects_invalid_values(self):
        cases = [
            "1920",
            "x1080",
            "1920x",
            "widex1080",
            "1920xtall",
            "0x1080",
            "1920x0",
            "-1920x1080",
            "1920x-1080",
            "1921x1080",
            "2056x1329",
        ]

        for value in cases:
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, f"Invalid resolution {value!r}; expected WIDTHxHEIGHT with positive even integers"):
                    record.parse_resolution(value)

    def test_parse_aspect_ratio_accepts_width_by_height(self):
        self.assertEqual(record.parse_aspect_ratio("16x9"), (16, 9))

    def test_parse_aspect_ratio_rejects_invalid_values(self):
        cases = [
            "16",
            "x9",
            "16x",
            "widex9",
            "16xtall",
            "0x9",
            "16x0",
            "-16x9",
            "16x-9",
        ]

        for value in cases:
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, f"Invalid aspect ratio {value!r}; expected WIDTHxHEIGHT with positive integers"):
                    record.parse_aspect_ratio(value)

    def test_parse_capture_dimensions_reads_ffmpeg_stream_size(self):
        output = """
Input #0, avfoundation, from '3':
  Stream #0:0: Video: rawvideo (UYVY / 0x59565955), uyvy422, 4112x2658, 1000k tbr, 1000k tbn
"""

        self.assertEqual(record.parse_capture_dimensions(output), (4112, 2658))

    def test_parse_capture_dimensions_rejects_unparseable_output(self):
        with self.assertRaisesRegex(ValueError, "ffmpeg probe output did not contain capture dimensions"):
            record.parse_capture_dimensions("no stream dimensions here")

    def test_probe_capture_dimensions_raises_on_ffmpeg_failure(self):
        completed = subprocess.CompletedProcess(
            args=["ffmpeg"],
            returncode=1,
            stderr="probe failed",
        )

        with mock.patch.object(subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "ffmpeg capture probe exited with code 1: probe failed"):
                record.probe_capture_dimensions("3", 30)

    def test_validate_capture_resolution_accepts_exact_size(self):
        record.validate_capture_resolution(1920, 1080, 1920, 1080, "3")

    def test_validate_capture_resolution_accepts_larger_same_ratio_source(self):
        record.validate_capture_resolution(3840, 2160, 1920, 1080, "3")

    def test_validate_capture_resolution_rejects_mismatched_ratio_source(self):
        with self.assertRaisesRegex(
            ValueError,
            "Capture source 3 is 4112x2658, which does not match requested output aspect ratio 1920x1080. "
            "Switch the display mode or --video-input capture source to the same aspect ratio before recording. "
            "Use --force-aspect-ratio for automatic display switching when a matching display mode is available.",
        ):
            record.validate_capture_resolution(4112, 2658, 1920, 1080, "3")

    def test_validate_capture_resolution_rejects_smaller_source(self):
        with self.assertRaisesRegex(
            ValueError,
            "Capture source 3 is 1280x720, which is smaller than requested output 1920x1080. "
            "Switch the display mode or --video-input capture source to at least the requested resolution before recording. "
            "Use --force-resolution for an exact display mode when that mode is available.",
        ):
            record.validate_capture_resolution(1280, 720, 1920, 1080, "3")

    def test_parse_display_mode_payload_returns_pixel_dimensions(self):
        payload = '{"width": 2056, "height": 1329, "pixel_width": 4112, "pixel_height": 2658}'

        self.assertEqual(record.parse_display_mode_payload(payload), {
            "width": 2056,
            "height": 1329,
            "pixel_width": 4112,
            "pixel_height": 2658,
        })

    def test_parse_display_modes_payload_returns_mode_list(self):
        payload = '[{"width": 1728, "height": 972, "pixel_width": 3456, "pixel_height": 1944}]'

        self.assertEqual(record.parse_display_modes_payload(payload), [{
            "width": 1728,
            "height": 972,
            "pixel_width": 3456,
            "pixel_height": 1944,
        }])

    def test_best_display_mode_for_aspect_ratio_returns_highest_pixel_area_match(self):
        modes = [
            {"width": 960, "height": 540, "pixel_width": 1920, "pixel_height": 1080},
            {"width": 1728, "height": 972, "pixel_width": 3456, "pixel_height": 1944},
            {"width": 1728, "height": 1080, "pixel_width": 3456, "pixel_height": 2160},
        ]

        self.assertEqual(record.best_display_mode_for_aspect_ratio(modes, 16, 9), {
            "width": 1728,
            "height": 972,
            "pixel_width": 3456,
            "pixel_height": 1944,
        })

    def test_best_display_mode_for_aspect_ratio_rejects_missing_match(self):
        modes = [
            {"width": 1728, "height": 1080, "pixel_width": 3456, "pixel_height": 2160},
        ]

        with self.assertRaisesRegex(RuntimeError, "No display mode with aspect ratio 16x9 is available on the main display"):
            record.best_display_mode_for_aspect_ratio(modes, 16, 9)

    def test_parse_display_mode_payload_rejects_invalid_payload(self):
        with self.assertRaisesRegex(RuntimeError, "macOS display helper returned invalid JSON"):
            record.parse_display_mode_payload("not-json")

    def test_run_macos_display_helper_raises_with_stderr(self):
        completed = subprocess.CompletedProcess(
            args=["/usr/bin/python3"],
            returncode=1,
            stdout="",
            stderr="mode not available",
        )

        with mock.patch.object(subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "macOS display helper failed: mode not available"):
                record.run_macos_display_helper("set", "1920", "1080")

    def test_macos_display_helper_uses_configuration_transaction(self):
        self.assertIn("CGBeginDisplayConfiguration", record.MACOS_DISPLAY_HELPER)
        self.assertIn("CGConfigureDisplayWithDisplayMode", record.MACOS_DISPLAY_HELPER)
        self.assertIn("CGCompleteDisplayConfiguration", record.MACOS_DISPLAY_HELPER)
        self.assertNotIn("CGDisplaySetDisplayMode", record.MACOS_DISPLAY_HELPER)

    def test_word_count_supports_unicode_transcripts(self):
        offsets = record.cue_offsets_from_word_ratio("Slide unicode", ["你好", "世界"], 2.0)

        self.assertEqual(offsets, [1.0])

    def test_validate_items_rejects_zero_token_segments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "transcript.txt"
            audio = root / "audio.wav"
            transcript.write_text("... || words here", encoding="utf-8")
            audio.write_bytes(b"audio")

            with self.assertRaisesRegex(ValueError, "segment 1 has no countable words"):
                record.validate_items([{
                    "slide": 1,
                    "transcript_path": str(transcript),
                    "audio_path": str(audio),
                }], "||", {1: 1})

    def test_validate_items_normalizes_identity_without_type_parallel_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "transcript.txt"
            audio = root / "audio.wav"
            transcript.write_text("first segment", encoding="utf-8")
            audio.write_bytes(b"audio")

            items = record.validate_items([{
                "slide": 3,
                "transcript_path": str(transcript),
                "audio_path": str(audio),
            }], "||", {3: 0})

        self.assertEqual(items[0]["identity"], {
            "field": "slide",
            "value": 3,
        })
        self.assertNotIn("slide", items[0])
        self.assertNotIn("name", items[0])

    def test_slide_animation_counts_read_click_effects_from_pptx(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            deck = write_deck(root, {1: 2, 2: 0})

            counts = record.slide_animation_counts(deck, [1, 2])

        self.assertEqual(counts, {
            1: 2,
            2: 0,
        })

    def test_slide_animation_count_ignores_build_list_templates(self):
        namespace = "http://schemas.openxmlformats.org/presentationml/2006/main"
        slide_xml = (
            f'<p:sld xmlns:p="{namespace}">'
            "<p:timing>"
            "<p:tnLst><p:par><p:cTn nodeType=\"tmRoot\">"
            "<p:childTnLst><p:par><p:cTn nodeType=\"clickEffect\"/></p:par></p:childTnLst>"
            "</p:cTn></p:par></p:tnLst>"
            "<p:bldLst><p:bldP><p:tmplLst><p:tmpl><p:tnLst>"
            "<p:par><p:cTn nodeType=\"clickEffect\"/></p:par>"
            "</p:tnLst></p:tmpl></p:tmplLst></p:bldP></p:bldLst>"
            "</p:timing>"
            "</p:sld>"
        )

        self.assertEqual(record.slide_animation_count_from_xml(slide_xml), 1)

    def test_validate_items_uses_deck_animation_count_without_manifest_cue_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "transcript.txt"
            audio = root / "audio.wav"
            transcript.write_text("first || second || third", encoding="utf-8")
            audio.write_bytes(b"audio")

            items = record.validate_items([{
                "slide": 1,
                "transcript_path": str(transcript),
                "audio_path": str(audio),
            }], "||", {1: 2})

        self.assertEqual(items[0]["expected_cue_count"], 2)

    def test_validate_items_rejects_cue_count_that_does_not_match_deck_animations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "transcript.txt"
            audio = root / "audio.wav"
            transcript.write_text("first || second", encoding="utf-8")
            audio.write_bytes(b"audio")

            with self.assertRaisesRegex(ValueError, "slide 1 has 1 cue marker but deck has 2 animations"):
                record.validate_items([{
                    "slide": 1,
                    "transcript_path": str(transcript),
                    "audio_path": str(audio),
                }], "||", {1: 2})

    def test_build_config_infers_cue_count_from_deck_animations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "transcript.txt"
            audio = root / "audio.wav"
            deck = write_deck(root, {1: 2})
            items_path = root / "items.json"
            transcript.write_text("first || second || third", encoding="utf-8")
            audio.write_bytes(b"audio")
            items_path.write_text(json.dumps({
                "items": [{
                    "slide": 1,
                    "transcript_path": str(transcript),
                    "audio_path": str(audio),
                }],
            }), encoding="utf-8")

            args = SimpleNamespace(
                deck=deck,
                items=items_path,
                output=root / "out.mp4",
                work_dir=root / "work",
                video_input="3",
                cue_marker="||",
                framerate=30,
                recording_lead_seconds=1.0,
                slide_pause_seconds=0.75,
                slideshow_start_seconds=2.0,
                output_width=1920,
                output_height=1080,
                force_resolution=False,
                force_aspect_ratio=None,
            )
            config = record.build_config(args)

        self.assertEqual(config["items"][0]["expected_cue_count"], 2)
        self.assertEqual(config["output_width"], 1920)
        self.assertEqual(config["output_height"], 1080)

    def test_prepare_generates_between_slide_silence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = slide_config(root)
            generated_silence = []

            def fake_generate_silence(path, duration_seconds):
                generated_silence.append(Path(path).name)
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_bytes(b"silence")

            def fake_normalize_audio(input_path, output_path):
                Path(output_path).write_bytes(b"normalized")

            def fake_run(command):
                Path(command[-1]).write_bytes(b"narration")

            with mock.patch.object(record, "generate_silence", side_effect=fake_generate_silence), \
                    mock.patch.object(record, "normalize_audio", side_effect=fake_normalize_audio), \
                    mock.patch.object(record, "audio_duration", side_effect=[2.0, 3.0]), \
                    mock.patch.object(record, "run", side_effect=fake_run):
                with contextlib.redirect_stdout(io.StringIO()):
                    plan = record.prepare(config)

            self.assertEqual(generated_silence, ["silence-lead.wav", "silence-slide.wav"])
            self.assertEqual(plan["actions"], [{
                "at_seconds": 2.0,
                "key": "space",
                "item": "Slide 1",
                "reason": "action cue",
            }])
            self.assertEqual(plan["items"][0]["identity"], {
                "field": "slide",
                "value": 1,
            })
            self.assertNotIn("slide", plan["items"][0])

    def test_ui_action_renderer_builds_applescript_from_data(self):
        lines = record.render_ui_actions([
            {"action": "activate_app", "app": "Microsoft PowerPoint"},
            {"action": "delay", "seconds": 0.5},
            {"action": "menu_click", "process": "Microsoft PowerPoint", "menu": "Slide Show", "item": "Play from Start"},
            {"action": "assert_window", "process": "Microsoft PowerPoint", "contains": "Slide Show"},
            {"action": "key_code", "code": 53},
        ])

        self.assertEqual(lines, [
            'tell application "Microsoft PowerPoint" to activate',
            "delay 0.5",
            'tell application "System Events"',
            'tell process "Microsoft PowerPoint"',
            'click menu item "Play from Start" of menu "Slide Show" of menu bar 1',
            "end tell",
            "end tell",
            'tell application "System Events"',
            'tell process "Microsoft PowerPoint"',
            "set foundWindow to false",
            "repeat with currentWindow in windows",
            "set windowName to name of currentWindow as text",
            'if windowName contains "Slide Show" then set foundWindow to true',
            "end repeat",
            'if foundWindow is false then error "Window containing Slide Show not found"',
            "end tell",
            "end tell",
            'tell application "System Events" to key code 53',
        ])

    def test_record_aborts_before_actions_when_ffmpeg_exits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = slide_config(Path(temp_dir), items=[], work_dir="/tmp/work")
        ffmpeg_process = FakeProcess([1], 1)
        audio_process = FakeProcess([None, None], 0)

        with mock.patch.object(record, "prepare", return_value={
            "narration_audio": "/tmp/narration.wav",
            "actions": [{"at_seconds": 0, "key": "space", "item": "Slide 1", "reason": "action cue"}],
        }), \
                mock.patch.object(record, "probe_capture_dimensions", return_value=(1920, 1080)), \
                mock.patch.object(record, "create_powerpoint_state", return_value={
                    "powerpoint_was_running": True,
                    "deck_was_open": True,
                }), \
                mock.patch.object(record, "start_slideshow"), \
                mock.patch.object(record, "close_slideshow_and_deck"), \
                mock.patch.object(record, "press_space") as press_space, \
                mock.patch.object(subprocess, "Popen", side_effect=[ffmpeg_process, audio_process]):
            with self.assertRaisesRegex(RuntimeError, "ffmpeg screen recording exited with code 1"):
                record.record(config)

        press_space.assert_not_called()

    def test_record_aborts_before_powerpoint_when_probe_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = slide_config(Path(temp_dir), work_dir="/tmp/work")

        with mock.patch.object(record, "probe_capture_dimensions", return_value=(1366, 768)), \
                mock.patch.object(record, "prepare") as prepare, \
                mock.patch.object(record, "create_powerpoint_state") as create_powerpoint_state, \
                mock.patch.object(record, "start_slideshow") as start_slideshow, \
                mock.patch.object(subprocess, "Popen") as popen:
            with self.assertRaisesRegex(ValueError, "does not match requested output aspect ratio"):
                record.record(config)

        prepare.assert_not_called()
        create_powerpoint_state.assert_not_called()
        start_slideshow.assert_not_called()
        popen.assert_not_called()

    def test_force_resolution_switches_before_recording_and_restores_after_mux(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = slide_config(Path(temp_dir), work_dir="/tmp/work", force_resolution=True)
        ffmpeg_process = FakeProcess([None, None, None], 0)
        audio_process = FakeProcess([None, 0], 0)
        events = []
        original_mode = {
            "width": 2056,
            "height": 1329,
            "pixel_width": 4112,
            "pixel_height": 2658,
        }

        def fake_set_display_resolution(width, height):
            if (width, height) == (1920, 1080):
                events.append("set_resolution")
                return
            if (width, height) == (2056, 1329):
                events.append("restore_resolution")
                return
            raise AssertionError((width, height))

        def fake_run(command):
            if command[0] == "ffmpeg":
                events.append("mux")
                return
            raise AssertionError(command)

        def fake_probe(video_input, framerate):
            if "set_resolution" in events:
                return (1920, 1080)
            return (4112, 2658)

        def fake_close_slideshow_and_deck(config, state):
            events.append("close_powerpoint")

        with mock.patch.object(record, "current_display_mode", return_value=original_mode), \
                mock.patch.object(record, "set_display_resolution", side_effect=fake_set_display_resolution), \
                mock.patch.object(record, "probe_capture_dimensions", side_effect=fake_probe), \
                mock.patch.object(record, "prepare", return_value={
                    "narration_audio": "/tmp/narration.wav",
                    "actions": [],
                }), \
                mock.patch.object(record, "create_powerpoint_state", return_value={
                    "powerpoint_was_running": False,
                    "deck_was_open": False,
                }), \
                mock.patch.object(record, "start_slideshow"), \
                mock.patch.object(record, "close_slideshow_and_deck", side_effect=fake_close_slideshow_and_deck), \
                mock.patch.object(record, "run", side_effect=fake_run), \
                mock.patch.object(subprocess, "Popen", side_effect=[ffmpeg_process, audio_process]):
            record.record(config)

        self.assertEqual(events, ["set_resolution", "close_powerpoint", "mux", "restore_resolution"])

    def test_force_aspect_ratio_sets_highest_ratio_mode_before_recording_and_restores_after_mux(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = slide_config(Path(temp_dir), work_dir="/tmp/work", force_aspect_ratio=(16, 9))
        ffmpeg_process = FakeProcess([None, None, None], 0)
        audio_process = FakeProcess([None, 0], 0)
        events = []
        original_mode = {
            "width": 2056,
            "height": 1329,
            "pixel_width": 4112,
            "pixel_height": 2658,
        }
        modes = [
            {"width": 960, "height": 540, "pixel_width": 1920, "pixel_height": 1080},
            {"width": 1728, "height": 972, "pixel_width": 3456, "pixel_height": 1944},
        ]

        def fake_set_display_resolution(width, height):
            if (width, height) == (3456, 1944):
                events.append("set_aspect_ratio")
                return
            if (width, height) == (2056, 1329):
                events.append("restore_resolution")
                return
            raise AssertionError((width, height))

        def fake_run(command):
            if command[0] == "ffmpeg":
                events.append("mux")
                return
            raise AssertionError(command)

        def fake_probe(video_input, framerate):
            if "set_aspect_ratio" in events:
                return (3456, 1944)
            return (4112, 2658)

        def fake_close_slideshow_and_deck(config, state):
            events.append("close_powerpoint")

        with mock.patch.object(record, "current_display_mode", return_value=original_mode), \
                mock.patch.object(record, "available_display_modes", return_value=modes), \
                mock.patch.object(record, "set_display_resolution", side_effect=fake_set_display_resolution), \
                mock.patch.object(record, "probe_capture_dimensions", side_effect=fake_probe), \
                mock.patch.object(record, "prepare", return_value={
                    "narration_audio": "/tmp/narration.wav",
                    "actions": [],
                }), \
                mock.patch.object(record, "create_powerpoint_state", return_value={
                    "powerpoint_was_running": False,
                    "deck_was_open": False,
                }), \
                mock.patch.object(record, "start_slideshow"), \
                mock.patch.object(record, "close_slideshow_and_deck", side_effect=fake_close_slideshow_and_deck), \
                mock.patch.object(record, "run", side_effect=fake_run), \
                mock.patch.object(subprocess, "Popen", side_effect=[ffmpeg_process, audio_process]):
            record.record(config)

        self.assertEqual(events, ["set_aspect_ratio", "close_powerpoint", "mux", "restore_resolution"])

    def test_force_resolution_restores_after_recording_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = slide_config(Path(temp_dir), work_dir="/tmp/work", force_resolution=True)
        events = []
        original_mode = {
            "width": 2056,
            "height": 1329,
            "pixel_width": 4112,
            "pixel_height": 2658,
        }

        def fake_set_display_resolution(width, height):
            if (width, height) == (1920, 1080):
                events.append("set_resolution")
                return
            if (width, height) == (2056, 1329):
                events.append("restore_resolution")
                return
            raise AssertionError((width, height))

        with mock.patch.object(record, "current_display_mode", return_value=original_mode), \
                mock.patch.object(record, "set_display_resolution", side_effect=fake_set_display_resolution), \
                mock.patch.object(record, "probe_capture_dimensions", side_effect=[(4112, 2658), (1920, 1080)]), \
                mock.patch.object(record, "prepare", side_effect=RuntimeError("prepare failed")), \
                mock.patch.object(record, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "prepare failed"):
                record.record(config)

        self.assertEqual(events, ["set_resolution", "restore_resolution"])
        run.assert_not_called()

    def test_record_runs_process_cleanup_when_state_creation_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = slide_config(Path(temp_dir), work_dir="/tmp/work")

        with mock.patch.object(record, "prepare", return_value={
            "narration_audio": "/tmp/narration.wav",
            "actions": [],
        }), \
                mock.patch.object(record, "probe_capture_dimensions", return_value=(1920, 1080)), \
                mock.patch.object(record, "create_powerpoint_state", side_effect=RuntimeError("state failed")), \
                mock.patch.object(record, "stop_audio_process") as stop_audio_process, \
                mock.patch.object(record, "stop_ffmpeg_process") as stop_ffmpeg_process, \
                mock.patch.object(record, "close_slideshow_and_deck") as close_slideshow_and_deck:
            with self.assertRaisesRegex(RuntimeError, "state failed"):
                record.record(config)

        stop_audio_process.assert_called_once_with(None)
        stop_ffmpeg_process.assert_called_once_with(None)
        close_slideshow_and_deck.assert_not_called()

    def test_record_reports_cleanup_errors_after_primary_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = slide_config(Path(temp_dir), work_dir="/tmp/work")

        with mock.patch.object(record, "prepare", return_value={
            "narration_audio": "/tmp/narration.wav",
            "actions": [],
        }), \
                mock.patch.object(record, "probe_capture_dimensions", return_value=(1920, 1080)), \
                mock.patch.object(record, "create_powerpoint_state", return_value={
                    "powerpoint_was_running": True,
                    "deck_was_open": True,
                }), \
                mock.patch.object(record, "start_slideshow", side_effect=RuntimeError("slideshow failed")), \
                mock.patch.object(record, "stop_audio_process"), \
                mock.patch.object(record, "stop_ffmpeg_process"), \
                mock.patch.object(record, "close_slideshow_and_deck", side_effect=RuntimeError("close failed")):
            with self.assertRaisesRegex(RuntimeError, "slideshow failed; cleanup failed: close PowerPoint slideshow and deck: close failed") as context:
                record.record(config)

        self.assertIsInstance(context.exception.__cause__, RuntimeError)
        self.assertEqual(str(context.exception.__cause__), "slideshow failed")

    def test_record_closes_powerpoint_before_final_mux(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = slide_config(Path(temp_dir), work_dir="/tmp/work")
        ffmpeg_process = FakeProcess([None, None, None], 0)
        audio_process = FakeProcess([None, 0], 0)
        events = []

        def fake_run(command):
            self.assertEqual(command[0], "ffmpeg")
            events.append("mux")

        def fake_close_slideshow_and_deck(config, state):
            events.append("close_powerpoint")

        with mock.patch.object(record, "prepare", return_value={
            "narration_audio": "/tmp/narration.wav",
            "actions": [],
        }), \
                mock.patch.object(record, "probe_capture_dimensions", return_value=(1920, 1080)), \
                mock.patch.object(record, "create_powerpoint_state", return_value={
                    "powerpoint_was_running": False,
                    "deck_was_open": False,
                }), \
                mock.patch.object(record, "start_slideshow"), \
                mock.patch.object(record, "close_slideshow_and_deck", side_effect=fake_close_slideshow_and_deck), \
                mock.patch.object(record, "run", side_effect=fake_run), \
                mock.patch.object(subprocess, "Popen", side_effect=[ffmpeg_process, audio_process]):
            record.record(config)

        self.assertEqual(events, ["close_powerpoint", "mux"])

    def test_final_mux_scales_to_requested_resolution_without_padding_or_crop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = slide_config(Path(temp_dir), work_dir="/tmp/work", output_width=1920, output_height=1080)
        ffmpeg_process = FakeProcess([None, None, None], 0)
        audio_process = FakeProcess([None, 0], 0)
        commands = []

        def fake_run(command):
            commands.append(command)

        with mock.patch.object(record, "probe_capture_dimensions", return_value=(3840, 2160)), \
                mock.patch.object(record, "prepare", return_value={
                    "narration_audio": "/tmp/narration.wav",
                    "actions": [],
                }), \
                mock.patch.object(record, "create_powerpoint_state", return_value={
                    "powerpoint_was_running": False,
                    "deck_was_open": False,
                }), \
                mock.patch.object(record, "start_slideshow"), \
                mock.patch.object(record, "close_slideshow_and_deck"), \
                mock.patch.object(record, "run", side_effect=fake_run), \
                mock.patch.object(subprocess, "Popen", side_effect=[ffmpeg_process, audio_process]):
            record.record(config)

        mux_command = commands[0]
        self.assertIn("-vf", mux_command)
        self.assertEqual(mux_command[mux_command.index("-vf") + 1], "scale=1920:1080")
        self.assertNotIn("pad", mux_command)
        self.assertNotIn("crop", mux_command)

    def test_presentation_open_check_uses_full_deck_path(self):
        deck_path = "/tmp/course-a/m1.pptx"

        with mock.patch.object(record, "capture", return_value="false") as capture:
            result = record.presentation_is_open(deck_path)

        self.assertFalse(result)
        self.assertEqual(capture.call_args.args[0][-1], str(Path(deck_path).expanduser().resolve()))

    def test_client_returns_recording_result_model(self):
        client = PowerPointSlideRecorderClient.__new__(PowerPointSlideRecorderClient)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            deck = root / "deck.pptx"
            items = root / "items.json"
            output = root / "out.mp4"
            work_dir = root / "work"

            with mock.patch.object(record, "build_config", return_value={"deck_path": str(deck)}) as build_config, \
                    mock.patch.object(record, "record", return_value={
                        "output_path": str(output),
                        "timing_plan_path": str(work_dir / "timing-plan.json"),
                        "timing_plan": {
                            "deck_path": str(deck),
                            "cue_marker": "||",
                            "narration_audio": str(work_dir / "narration.wav"),
                            "duration_seconds": 3.0,
                            "actions": [],
                            "items": [],
                        },
                    }):
                result = client.record(
                    deck=deck,
                    items=items,
                    output=output,
                    work_dir=work_dir,
                    video_input="3",
                    cue_marker="||",
                    framerate=30,
                    recording_lead_seconds=1.0,
                    slide_pause_seconds=0.75,
                    slideshow_start_seconds=2.0,
                    output_width=1920,
                    output_height=1080,
                    force_resolution=True,
                    force_aspect_ratio=(16, 9),
                )

        self.assertEqual(result.output_path, str(output))
        self.assertEqual(result.duration_seconds, 3.0)
        self.assertEqual(build_config.call_args.args[0].deck, deck)
        self.assertEqual(build_config.call_args.args[0].output_width, 1920)
        self.assertEqual(build_config.call_args.args[0].output_height, 1080)
        self.assertIs(build_config.call_args.args[0].force_resolution, True)
        self.assertEqual(build_config.call_args.args[0].force_aspect_ratio, (16, 9))


if __name__ == "__main__":
    unittest.main()
