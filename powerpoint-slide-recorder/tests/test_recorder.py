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


def write_layout_animation_deck(root, slide_layout_animation_counts):
    """Build a deck whose slide XML has no timing but whose layout defines the clicks.

    Mirrors Pluralsight-templated decks: each ``slide{N}.xml`` carries no
    ``<p:timing>`` at all, and the click-build animations live on the referenced
    slideLayout. Each slide gets its own layout part so per-slide counts differ.
    """
    deck = root / "layout-deck.pptx"
    presentation_namespace = "http://schemas.openxmlformats.org/presentationml/2006/main"
    relationships_namespace = "http://schemas.openxmlformats.org/package/2006/relationships"

    with zipfile.ZipFile(deck, "w") as archive:
        for slide_number, animation_count in slide_layout_animation_counts.items():
            slide_xml = f'<p:sld xmlns:p="{presentation_namespace}"><p:cSld/></p:sld>'
            archive.writestr(f"ppt/slides/slide{slide_number}.xml", slide_xml)

            layout_name = f"slideLayout{slide_number}.xml"
            rels_xml = (
                f'<Relationships xmlns="{relationships_namespace}">'
                f'<Relationship Id="rId1" '
                f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" '
                f'Target="../slideLayouts/{layout_name}"/>'
                "</Relationships>"
            )
            archive.writestr(f"ppt/slides/_rels/slide{slide_number}.xml.rels", rels_xml)

            click_effects = "".join(
                f'<p:par><p:cTn id="{index + 2}" nodeType="clickEffect"/></p:par>'
                for index in range(animation_count)
            )
            layout_xml = (
                f'<p:sldLayout xmlns:p="{presentation_namespace}">'
                "<p:cSld/>"
                "<p:timing><p:tnLst><p:par><p:cTn id=\"1\">"
                f"<p:childTnLst>{click_effects}</p:childTnLst>"
                "</p:cTn></p:par></p:tnLst></p:timing>"
                "</p:sldLayout>"
            )
            archive.writestr(f"ppt/slideLayouts/{layout_name}", layout_xml)

    return deck


class DemoEnvironmentPrepTests(unittest.TestCase):
    def test_demo_environment_prep_runs_existing_focus_and_notification_helpers(self):
        with mock.patch.object(record, "require_path", side_effect=lambda path, description: Path(path)), \
                mock.patch.object(record, "run") as run_command:
            record.run_demo_environment_recording_prep()

        command = run_command.call_args.args[0]
        script = command[-1]
        self.assertEqual(command[:3], [str(record.DEMO_ENVIRONMENT_PWSH_PATH), "-NoProfile", "-NonInteractive"])
        self.assertEqual(command[3], "-Command")
        self.assertIn("Import-Module -DisableNameChecking", script)
        self.assertIn(str(record.DEMO_ENVIRONMENT_AUTOMATION_MODULE_PATH), script)
        self.assertLess(script.index("Set-MacOSDoNotDisturb -SoftPass"), script.index("Remove-MacOSNotifications"))
        self.assertEqual(
            run_command.call_args.kwargs["timeout"],
            record.DEMO_ENVIRONMENT_RECORDING_PREP_TIMEOUT_SECONDS,
        )

    def test_demo_environment_prep_failure_is_clear(self):
        with mock.patch.object(record, "require_path", side_effect=lambda path, description: Path(path)), \
                mock.patch.object(record, "run", side_effect=subprocess.CalledProcessError(7, ["pwsh"])):
            with self.assertRaisesRegex(RuntimeError, "Demo environment prep failed before recording \\(exit 7\\)"):
                record.run_demo_environment_recording_prep()


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.demo_prep_patcher = mock.patch.object(record, "run_demo_environment_recording_prep")
        self.demo_environment_prep = self.demo_prep_patcher.start()

    def tearDown(self):
        self.demo_prep_patcher.stop()

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

    def test_capture_crop_plan_accepts_exact_size_without_crop(self):
        self.assertIsNone(record.capture_crop_plan(1920, 1080, 1920, 1080, "3"))

    def test_capture_crop_plan_accepts_larger_same_ratio_source_without_crop(self):
        self.assertIsNone(record.capture_crop_plan(3840, 2160, 1920, 1080, "3"))

    def test_centered_crop_returns_none_for_equal_aspect_ratio(self):
        self.assertIsNone(record.centered_crop_for_output_aspect(3840, 2160, 1920, 1080))

    def test_centered_crop_letterboxes_taller_capture(self):
        # 16:10 capture, 16:9 output -> full width, bars top/bottom.
        self.assertEqual(
            record.centered_crop_for_output_aspect(4112, 2658, 1920, 1080),
            (4112, 2312, 0, 172),
        )

    def test_centered_crop_pillarboxes_wider_capture(self):
        # 21:9 capture, 16:9 output -> full height, bars left/right.
        self.assertEqual(
            record.centered_crop_for_output_aspect(5040, 2160, 1920, 1080),
            (3840, 2160, 600, 0),
        )

    def test_capture_crop_plan_crops_mismatched_ratio_source(self):
        self.assertEqual(
            record.capture_crop_plan(4112, 2658, 1920, 1080, "3"),
            (4112, 2312, 0, 172),
        )

    def test_capture_crop_plan_rejects_smaller_source(self):
        with self.assertRaisesRegex(
            ValueError,
            "Capture source 3 is 1280x720 .*which is smaller than requested output 1920x1080",
        ):
            record.capture_crop_plan(1280, 720, 1920, 1080, "3")

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

    def test_best_display_mode_for_aspect_ratio_returns_highest_exact_area_match(self):
        # Two exact 16:9 modes plus a smaller exact one: the largest exact 16:9 mode
        # wins (it records uncropped), preserving the external-16:9 source behavior.
        modes = [
            {"width": 960, "height": 540, "pixel_width": 1920, "pixel_height": 1080},
            {"width": 1728, "height": 972, "pixel_width": 3456, "pixel_height": 1944},
            {"width": 2560, "height": 1440, "pixel_width": 5120, "pixel_height": 2880},
        ]

        self.assertEqual(record.best_display_mode_for_aspect_ratio(modes, 16, 9, 1920, 1080), {
            "width": 2560,
            "height": 1440,
            "pixel_width": 5120,
            "pixel_height": 2880,
        })

    def test_best_display_mode_for_aspect_ratio_prefers_exact_over_larger_croppable(self):
        # A 16:10 mode of higher pixel area sits next to an exact 16:9 mode whose
        # usable (uncropped) area is larger. The exact 16:9 mode wins because its
        # full pixel area is usable while the 16:10 mode loses height to the crop.
        modes = [
            {"width": 1728, "height": 1080, "pixel_width": 3456, "pixel_height": 2160},  # 16:10, usable 3456x1944
            {"width": 1920, "height": 1080, "pixel_width": 3840, "pixel_height": 2160},  # exact 16:9, usable 3840x2160
        ]

        self.assertEqual(record.best_display_mode_for_aspect_ratio(modes, 16, 9, 1920, 1080), {
            "width": 1920,
            "height": 1080,
            "pixel_width": 3840,
            "pixel_height": 2160,
        })

    def test_best_display_mode_for_aspect_ratio_uses_centered_crop_on_sixteen_ten_only_panel(self):
        # The real built-in Liquid Retina XDR panel: every mode is 16:10 or 1.547,
        # none is exact 16:9. A mode is chosen via its centered 16:9 crop so no
        # external 16:9 display is required. When two modes share the largest usable
        # 16:9 area, the larger raw pixel mode wins (its extra height is cropped away,
        # so the recorded result is identical) -- here the 4112x2658 native mode.
        modes = [
            {"width": 2056, "height": 1329, "pixel_width": 4112, "pixel_height": 2658},  # 1.547, usable 4112x2312
            {"width": 2056, "height": 1285, "pixel_width": 4112, "pixel_height": 2570},  # 16:10, usable 4112x2312
            {"width": 1728, "height": 1117, "pixel_width": 3456, "pixel_height": 2234},  # 1.547, usable 3456x1944
            {"width": 1728, "height": 1080, "pixel_width": 3456, "pixel_height": 2160},  # 16:10, usable 3456x1944
            {"width": 960, "height": 600, "pixel_width": 1920, "pixel_height": 1200},    # 16:10, usable 1920x1080
        ]

        chosen = record.best_display_mode_for_aspect_ratio(modes, 16, 9, 1920, 1080)

        # 4112x2658 and 4112x2570 tie on usable area (4112x2312); the larger raw mode wins.
        self.assertEqual(chosen, {
            "width": 2056,
            "height": 1329,
            "pixel_width": 4112,
            "pixel_height": 2658,
        })

    def test_best_display_mode_for_aspect_ratio_rejects_when_no_mode_reaches_output(self):
        # Only small modes whose centered 16:9 crop is below 1920x1080.
        modes = [
            {"width": 640, "height": 400, "pixel_width": 1280, "pixel_height": 800},
        ]

        with self.assertRaisesRegex(
            RuntimeError,
            "No display mode can produce a 16x9 capture of at least 1920x1080 on the main display",
        ):
            record.best_display_mode_for_aspect_ratio(modes, 16, 9, 1920, 1080)

    def test_best_display_mode_for_aspect_ratio_rejects_ratio_output_mismatch(self):
        modes = [
            {"width": 960, "height": 540, "pixel_width": 1920, "pixel_height": 1080},
        ]

        with self.assertRaisesRegex(
            ValueError,
            "Requested aspect ratio 16x9 does not match the output resolution 1920x1200",
        ):
            record.best_display_mode_for_aspect_ratio(modes, 16, 9, 1920, 1200)

    def test_parse_display_mode_payload_rejects_invalid_payload(self):
        with self.assertRaisesRegex(RuntimeError, "macOS display helper returned invalid JSON"):
            record.parse_display_mode_payload("not-json")

    def test_run_macos_display_helper_raises_with_stderr(self):
        completed = subprocess.CompletedProcess(
            args=[record.sys.executable],
            returncode=1,
            stdout="",
            stderr="mode not available",
        )

        with mock.patch.object(subprocess, "run", return_value=completed) as run:
            with self.assertRaisesRegex(RuntimeError, "macOS display helper failed: mode not available"):
                record.run_macos_display_helper("set", "1920", "1080")
        self.assertEqual(run.call_args.args[0][0], record.sys.executable)

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

    def test_slide_animation_counts_read_click_effects_from_slide_layout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            deck = write_layout_animation_deck(root, {1: 0, 2: 4, 8: 6})

            counts = record.slide_animation_counts(deck, [1, 2, 8])

        self.assertEqual(counts, {
            1: 0,
            2: 4,
            8: 6,
        })

    def test_slide_animation_counts_sum_slide_and_layout_click_effects(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            deck = root / "mixed-deck.pptx"
            presentation_namespace = "http://schemas.openxmlformats.org/presentationml/2006/main"
            relationships_namespace = "http://schemas.openxmlformats.org/package/2006/relationships"

            with zipfile.ZipFile(deck, "w") as archive:
                slide_xml = (
                    f'<p:sld xmlns:p="{presentation_namespace}">'
                    "<p:cSld/>"
                    "<p:timing><p:tnLst><p:par><p:cTn id=\"1\">"
                    "<p:childTnLst>"
                    "<p:par><p:cTn id=\"2\" nodeType=\"clickEffect\"/></p:par>"
                    "</p:childTnLst>"
                    "</p:cTn></p:par></p:tnLst></p:timing>"
                    "</p:sld>"
                )
                archive.writestr("ppt/slides/slide1.xml", slide_xml)

                rels_xml = (
                    f'<Relationships xmlns="{relationships_namespace}">'
                    '<Relationship Id="rId1" '
                    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" '
                    'Target="../slideLayouts/slideLayout1.xml"/>'
                    "</Relationships>"
                )
                archive.writestr("ppt/slides/_rels/slide1.xml.rels", rels_xml)

                layout_xml = (
                    f'<p:sldLayout xmlns:p="{presentation_namespace}">'
                    "<p:cSld/>"
                    "<p:timing><p:tnLst><p:par><p:cTn id=\"1\">"
                    "<p:childTnLst>"
                    "<p:par><p:cTn id=\"2\" nodeType=\"clickEffect\"/></p:par>"
                    "<p:par><p:cTn id=\"3\" nodeType=\"clickEffect\"/></p:par>"
                    "</p:childTnLst>"
                    "</p:cTn></p:par></p:tnLst></p:timing>"
                    "</p:sldLayout>"
                )
                archive.writestr("ppt/slideLayouts/slideLayout1.xml", layout_xml)

            counts = record.slide_animation_counts(deck, [1])

        self.assertEqual(counts, {1: 3})

    def test_slide_animation_counts_treat_missing_layout_rels_as_zero(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            deck = write_deck(root, {1: 2})

            counts = record.slide_animation_counts(deck, [1])

        self.assertEqual(counts, {1: 2})

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

    def test_run_slideshow_range_starts_on_clip_first_slide_via_custom_range(self):
        # The slideshow must begin on the clip's first deck slide through a custom
        # slide-show range, not "Play from Start" (always slide 1) followed by a
        # number-typed jump. Typing the slide number in the live show drops the
        # digit and lands on slide 2, which desynchronizes every slide from its
        # narration and fires the per-cue Space presses against the wrong slides
        # so the click-build reveals never line up.
        lines = record.render_run_slideshow_range(7, 10)

        self.assertEqual(lines, [
            'tell application "Microsoft PowerPoint"',
            "activate",
            "set slideShowSettings to slide show settings of active presentation",
            "set range type of slideShowSettings to slide show range",
            "set starting slide of slideShowSettings to 7",
            "set ending slide of slideShowSettings to 10",
            "set advance mode of slideShowSettings to slide show advance manual advance",
            "run slide show slideShowSettings",
            "end tell",
        ])
        script = "\n".join(lines)
        # Manual advance keeps an auto-timed deck from self-advancing ahead of audio.
        self.assertIn("slide show advance manual advance", script)
        # No legacy "Play from Start" + number jump.
        self.assertNotIn("Play from Start", script)
        self.assertNotIn("key code 36", script)

    def test_parse_screen_point_size_reads_desktop_bounds(self):
        self.assertEqual(record.parse_screen_point_size("0, 0, 2056, 1329"), (2056, 1329))

    def test_parse_screen_point_size_rejects_unexpected_bounds(self):
        with self.assertRaisesRegex(ValueError, "Unexpected desktop bounds response"):
            record.parse_screen_point_size("0, 0, 2056")

    def test_fullscreen_action_treats_screen_coverage_as_ready(self):
        lines = record.render_fullscreen_window_action({
            "process": "Microsoft PowerPoint",
            "contains": "Slide Show",
            "screen_width": 2056,
            "screen_height": 1329,
        })
        script = "\n".join(lines)

        # Readiness is satisfied by full coverage, not only AXFullScreen=true.
        self.assertIn("set coversScreen to false", script)
        self.assertIn("set widthGap to 2056 - windowWidth", script)
        self.assertIn("set heightGap to 1329 - windowHeight", script)
        self.assertIn(
            "if widthGap <= 4 and heightGap <= 4 and absX <= 4 and absY <= 4 then set coversScreen to true",
            script,
        )
        self.assertIn("if isFullscreen or coversScreen then set slideshowReady to true", script)
        # AXFullScreen reads/writes must not hard-fail when PowerPoint refuses them.
        self.assertIn('try', script)
        self.assertIn(
            'error "Window containing Slide Show did not enter fullscreen and does not cover the screen"',
            script,
        )

    def test_fullscreen_action_honors_custom_coverage_tolerance(self):
        lines = record.render_fullscreen_window_action({
            "process": "Microsoft PowerPoint",
            "contains": "Slide Show",
            "screen_width": 1920,
            "screen_height": 1080,
            "coverage_tolerance": 10,
        })
        script = "\n".join(lines)

        self.assertIn(
            "if widthGap <= 10 and heightGap <= 10 and absX <= 10 and absY <= 10 then set coversScreen to true",
            script,
        )

    def test_press_space_targets_powerpoint_process(self):
        with mock.patch.object(record, "execute_ui_actions") as execute_ui_actions:
            record.press_space()

        execute_ui_actions.assert_called_once_with([{
            "action": "scoped_key_code",
            "process": "Microsoft PowerPoint",
            "code": 49,
        }])

    def test_sleep_until_checks_slideshow_before_action(self):
        process = FakeProcess([None], 0)
        presence_check = mock.Mock()

        record.sleep_until(0, [(process, "ffmpeg")], presence_check)

        presence_check.assert_called_once()

    def test_record_runs_demo_environment_prep_before_capture_starts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = slide_config(Path(temp_dir), work_dir="/tmp/work")
        ffmpeg_process = FakeProcess([None, None, None], 0)
        audio_process = FakeProcess([None, 0], 0)
        events = []

        def fake_prepare(config):
            events.append("prepare")
            return {
                "narration_audio": "/tmp/narration.wav",
                "actions": [],
            }

        def fake_state(config):
            events.append("state")
            return {
                "powerpoint_was_running": False,
                "deck_was_open": False,
            }

        def fake_start_slideshow(config):
            events.append("slideshow")

        def fake_popen(command, **kwargs):
            events.append(command[0])
            if command[0] == "ffmpeg":
                return ffmpeg_process
            if command[0] == "afplay":
                return audio_process
            raise AssertionError(command)

        self.demo_environment_prep.side_effect = lambda: events.append("demo_prep")

        with mock.patch.object(record, "probe_capture_dimensions", return_value=(1920, 1080)), \
                mock.patch.object(record, "prepare", side_effect=fake_prepare), \
                mock.patch.object(record, "create_powerpoint_state", side_effect=fake_state), \
                mock.patch.object(record, "start_slideshow", side_effect=fake_start_slideshow), \
                mock.patch.object(record, "close_slideshow_and_deck"), \
                mock.patch.object(record, "assert_slideshow_present"), \
                mock.patch.object(record, "run"), \
                mock.patch.object(subprocess, "Popen", side_effect=fake_popen):
            record.record(config)

        self.assertEqual(events[:4], ["demo_prep", "prepare", "state", "slideshow"])
        self.assertEqual(events[4], "ffmpeg")

    def test_record_aborts_clearly_when_demo_environment_prep_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = slide_config(Path(temp_dir), work_dir="/tmp/work")

        self.demo_environment_prep.side_effect = RuntimeError("Demo environment prep failed before recording (exit 7)")

        with mock.patch.object(record, "probe_capture_dimensions", return_value=(1920, 1080)), \
                mock.patch.object(record, "prepare") as prepare, \
                mock.patch.object(record, "create_powerpoint_state") as create_powerpoint_state, \
                mock.patch.object(record, "start_slideshow") as start_slideshow, \
                mock.patch.object(subprocess, "Popen") as popen:
            with self.assertRaisesRegex(RuntimeError, "Demo environment prep failed before recording"):
                record.record(config)

        prepare.assert_not_called()
        create_powerpoint_state.assert_not_called()
        start_slideshow.assert_not_called()
        popen.assert_not_called()

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

    def test_record_aborts_before_powerpoint_when_capture_too_small(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = slide_config(Path(temp_dir), work_dir="/tmp/work")

        with mock.patch.object(record, "probe_capture_dimensions", return_value=(1280, 720)), \
                mock.patch.object(record, "prepare") as prepare, \
                mock.patch.object(record, "create_powerpoint_state") as create_powerpoint_state, \
                mock.patch.object(record, "start_slideshow") as start_slideshow, \
                mock.patch.object(subprocess, "Popen") as popen:
            with self.assertRaisesRegex(ValueError, "which is smaller than requested output"):
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
                mock.patch.object(record, "assert_slideshow_present"), \
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
                mock.patch.object(record, "assert_slideshow_present"), \
                mock.patch.object(record, "run", side_effect=fake_run), \
                mock.patch.object(subprocess, "Popen", side_effect=[ffmpeg_process, audio_process]):
            record.record(config)

        self.assertEqual(events, ["set_aspect_ratio", "close_powerpoint", "mux", "restore_resolution"])

    def test_force_aspect_ratio_crops_centered_region_on_sixteen_ten_only_panel(self):
        # The real failure case: the built-in Liquid Retina XDR panel advertises only
        # 16:10 / 1.547 modes and no exact 16:9 mode. --force-aspect-ratio 16x9 must
        # switch to the best 16:10 mode, record, and crop the centered 16:9 slide
        # region before scaling to 1920x1080 -- no external 16:9 display required.
        with tempfile.TemporaryDirectory() as temp_dir:
            config = slide_config(Path(temp_dir), work_dir="/tmp/work", force_aspect_ratio=(16, 9))
        ffmpeg_process = FakeProcess([None, None, None], 0)
        audio_process = FakeProcess([None, 0], 0)
        events = []
        commands = []
        original_mode = {
            "width": 2056,
            "height": 1329,
            "pixel_width": 4112,
            "pixel_height": 2658,
        }
        # 16:10-only panel modes -- none is exact 16:9.
        modes = [
            {"width": 2056, "height": 1285, "pixel_width": 4112, "pixel_height": 2570},
            {"width": 1728, "height": 1080, "pixel_width": 3456, "pixel_height": 2160},
        ]

        def fake_set_display_resolution(width, height):
            if (width, height) == (4112, 2570):
                events.append("set_aspect_ratio")
                return
            if (width, height) == (2056, 1329):
                events.append("restore_resolution")
                return
            raise AssertionError((width, height))

        def fake_run(command):
            if command[0] == "ffmpeg":
                commands.append(command)
                events.append("mux")
                return
            raise AssertionError(command)

        def fake_probe(video_input, framerate):
            if "set_aspect_ratio" in events:
                return (4112, 2570)
            return (4112, 2658)

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
                mock.patch.object(record, "close_slideshow_and_deck"), \
                mock.patch.object(record, "assert_slideshow_present"), \
                mock.patch.object(record, "run", side_effect=fake_run), \
                mock.patch.object(subprocess, "Popen", side_effect=[ffmpeg_process, audio_process]):
            with contextlib.redirect_stderr(io.StringIO()):
                record.record(config)

        # Best 16:10 mode chosen, then the centered 16:9 region cropped and scaled.
        self.assertIn("set_aspect_ratio", events)
        mux_command = commands[0]
        self.assertIn("-vf", mux_command)
        # 4112x2570 (16:10) -> centered crop to 16:9 (4112x2312, y=129->even 128), then scale.
        self.assertEqual(
            mux_command[mux_command.index("-vf") + 1],
            "crop=4112:2312:0:128,scale=1920:1080",
        )

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

    def test_cleanup_force_kills_recorder_launched_powerpoint_on_connection_error(self):
        state = {"powerpoint_was_running": False, "deck_was_open": False}

        with mock.patch.object(record, "close_slideshow_and_deck",
                               side_effect=RuntimeError("Microsoft PowerPoint got an error: Connection is invalid. (-609)")), \
                mock.patch.object(record, "force_kill_powerpoint") as force_kill:
            record.cleanup_powerpoint({}, state)

        force_kill.assert_called_once_with()

    def test_cleanup_does_not_force_kill_preexisting_powerpoint(self):
        state = {"powerpoint_was_running": True, "deck_was_open": False}

        with mock.patch.object(record, "close_slideshow_and_deck",
                               side_effect=RuntimeError("Microsoft PowerPoint got an error: Connection is invalid. (-609)")), \
                mock.patch.object(record, "force_kill_powerpoint") as force_kill:
            with self.assertRaisesRegex(RuntimeError, "Connection is invalid"):
                record.cleanup_powerpoint({}, state)

        force_kill.assert_not_called()

    def test_force_kill_powerpoint_uses_sigkill_and_verifies_exit(self):
        with mock.patch.object(subprocess, "run", side_effect=[
            subprocess.CompletedProcess(["pkill"], 0, stdout="", stderr=""),
            subprocess.CompletedProcess(["pgrep"], 1, stdout="", stderr=""),
        ]) as run:
            record.force_kill_powerpoint()

        self.assertEqual(run.call_args_list[0].args[0], ["pkill", "-9", "-x", "Microsoft PowerPoint"])
        self.assertEqual(run.call_args_list[1].args[0], ["pgrep", "-x", "Microsoft PowerPoint"])

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
                mock.patch.object(record, "assert_slideshow_present"), \
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
                mock.patch.object(record, "assert_slideshow_present"), \
                mock.patch.object(record, "run", side_effect=fake_run), \
                mock.patch.object(subprocess, "Popen", side_effect=[ffmpeg_process, audio_process]):
            record.record(config)

        mux_command = commands[0]
        self.assertIn("-vf", mux_command)
        self.assertEqual(mux_command[mux_command.index("-vf") + 1], "scale=1920:1080")
        self.assertNotIn("pad", mux_command)
        self.assertNotIn("crop", mux_command)

    def test_final_mux_crops_centered_output_aspect_before_scaling(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = slide_config(Path(temp_dir), work_dir="/tmp/work", output_width=1920, output_height=1080)
        ffmpeg_process = FakeProcess([None, None, None], 0)
        audio_process = FakeProcess([None, 0], 0)
        commands = []

        def fake_run(command):
            commands.append(command)

        with mock.patch.object(record, "probe_capture_dimensions", return_value=(3000, 2000)), \
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
                mock.patch.object(record, "assert_slideshow_present"), \
                mock.patch.object(record, "run", side_effect=fake_run), \
                mock.patch.object(subprocess, "Popen", side_effect=[ffmpeg_process, audio_process]):
            record.record(config)

        mux_command = commands[0]
        self.assertIn("-vf", mux_command)
        # 3000x2000 (3:2) -> centered crop to 16:9 (3000x1688, y=156), then scale.
        self.assertEqual(
            mux_command[mux_command.index("-vf") + 1],
            "crop=3000:1688:0:156,scale=1920:1080",
        )

    def test_presentation_open_check_uses_full_deck_path(self):
        deck_path = "/tmp/course-a/m1.pptx"

        with mock.patch.object(record, "capture", return_value="false") as capture:
            result = record.presentation_is_open(deck_path)

        self.assertFalse(result)
        self.assertEqual(capture.call_args.args[0][-1], str(Path(deck_path).expanduser().resolve()))

    def test_open_poll_treats_applescript_timeout_as_not_open_yet(self):
        error = subprocess.CalledProcessError(
            1,
            ["osascript"],
            stderr="Microsoft PowerPoint got an error: AppleEvent timed out. (-1712)",
        )

        with mock.patch.object(record, "presentation_is_open", side_effect=error), \
                mock.patch.object(record, "log_warning") as log_warning:
            self.assertFalse(record.presentation_is_open_during_open("/tmp/deck.pptx"))

        log_warning.assert_called_once()

    def test_open_poll_treats_connection_invalid_as_not_open_yet(self):
        error = subprocess.CalledProcessError(
            1,
            ["osascript"],
            stderr="Microsoft PowerPoint got an error: Connection is invalid. (-609)",
        )

        with mock.patch.object(record, "presentation_is_open", side_effect=error), \
                mock.patch.object(record, "log_warning") as log_warning:
            self.assertFalse(record.presentation_is_open_during_open("/tmp/deck.pptx"))

        log_warning.assert_called_once()

    def test_initial_state_tolerates_applescript_timeout_when_powerpoint_is_running(self):
        with mock.patch.object(record, "powerpoint_is_running", return_value=True), \
                mock.patch.object(record, "presentation_is_open_during_open", return_value=False) as is_open:
            state = record.create_powerpoint_state({"deck_path": "/tmp/deck.pptx"})

        self.assertEqual(state, {"powerpoint_was_running": True, "deck_was_open": False})
        is_open.assert_called_once_with(Path("/tmp/deck.pptx"))

    def test_open_poll_keeps_non_timeout_presentation_failures_loud(self):
        error = subprocess.CalledProcessError(1, ["osascript"], stderr="syntax error")

        with mock.patch.object(record, "presentation_is_open", side_effect=error):
            with self.assertRaises(subprocess.CalledProcessError):
                record.presentation_is_open_during_open("/tmp/deck.pptx")

    def test_parse_dialog_payload_treats_malformed_responses_as_no_dialog(self):
        # Regression: the live-process System Events probe can return a bare
        # ``false`` (or an empty / AppleScript-error string) instead of the
        # 3-field payload when AX is not ready or an Automation consent gate
        # intercepts the event. Any non-3-field response must be read as
        # "no dialog detected" and return None, never raise -- raising here used
        # to crash the whole recorder with
        # "Unexpected PowerPoint dialog probe response: 'false'".
        for malformed in ["false", "", "true", "execution error: Not authorized to send Apple events", "weird\toutput"]:
            with self.subTest(response=malformed):
                self.assertIsNone(record.parse_frontmost_dialog_payload(malformed))

    def test_parse_dialog_payload_reads_wellformed_payload(self):
        sep = record.DIALOG_FIELD_SEPARATOR
        text_sep = record.DIALOG_TEXT_SEPARATOR
        self.assertIsNone(record.parse_frontmost_dialog_payload(f"false{sep}{sep}"))
        self.assertEqual(
            record.parse_frontmost_dialog_payload(f"true{sep}Sign in{sep}Use your account{text_sep}"),
            {"title": "Sign in", "text": "Use your account"},
        )

    def test_frontmost_dialog_probe_is_non_fatal_on_bare_false(self):
        # The bare ``false`` from the failing live run must yield None (no raise).
        with mock.patch.object(record, "capture", return_value="false"), \
                mock.patch.object(record.time, "sleep"):
            self.assertIsNone(record.frontmost_powerpoint_dialog())

    def test_frontmost_dialog_probe_is_non_fatal_on_osascript_failure(self):
        # An osascript subprocess failure (e.g. a consent gate / AX error) must be
        # caught and read as "no dialog", after retrying, never propagated.
        def boom(command, timeout=None):
            raise subprocess.CalledProcessError(1, command, stderr="Not authorized to send Apple events")

        with mock.patch.object(record, "capture", side_effect=boom) as capture, \
                mock.patch.object(record.time, "sleep"):
            self.assertIsNone(record.frontmost_powerpoint_dialog())
        self.assertEqual(capture.call_count, record.DIALOG_PROBE_ATTEMPTS)

    def test_frontmost_dialog_probe_is_non_fatal_on_timeout(self):
        # A hard osascript subprocess timeout (converted to RuntimeError by
        # capture_osascript) must also be non-fatal for the best-effort probe.
        with mock.patch.object(record, "capture", side_effect=subprocess.TimeoutExpired("osascript", 30)), \
                mock.patch.object(record.time, "sleep"):
            self.assertIsNone(record.frontmost_powerpoint_dialog())

    def test_auto_dismiss_does_not_raise_on_unknown_dialog(self):
        # An unrecognized dialog is logged and left alone (never blindly clicked),
        # and auto-dismiss returns None instead of raising.
        with mock.patch.object(record, "frontmost_powerpoint_dialog",
                               return_value={"title": "Delete slide?", "text": "cannot undo"}), \
                mock.patch.object(record, "capture_osascript") as capture_osascript:
            self.assertIsNone(record.try_auto_dismiss_startup_dialog())
        capture_osascript.assert_not_called()

    def test_open_deck_proceeds_when_already_open_despite_unreadable_probe(self):
        # When the deck is already open, the recorder must proceed even if the
        # dialog probe cannot read dialog state.
        with mock.patch.object(record, "presentation_is_open", return_value=True), \
                mock.patch.object(record, "frontmost_powerpoint_dialog", return_value=None) as probe, \
                mock.patch.object(record, "run") as run_command:
            record.open_deck({"deck_path": "/tmp/deck.pptx"})
        run_command.assert_not_called()
        probe.assert_not_called()

    def test_start_slideshow_proceeds_when_open_but_probe_reads_no_dialog(self):
        # presentation_is_open true + probe returns "no dialog" -> the slideshow is
        # driven (open/record path proceeds), the probe never blocks it.
        config = {"items": [{"identity": {"value": 3}}, {"identity": {"value": 5}}]}
        with mock.patch.object(record, "open_deck") as open_deck, \
                mock.patch.object(record, "frontmost_powerpoint_dialog", return_value=None), \
                mock.patch.object(record, "run_osascript") as run_osascript, \
                mock.patch.object(record, "execute_ui_actions"), \
                mock.patch.object(record, "force_slideshow_fullscreen"), \
                mock.patch.object(record.time, "sleep"):
            config["slideshow_start_seconds"] = 0
            record.start_slideshow(config)
        open_deck.assert_called_once()
        # The slideshow-range AppleScript was driven for slides 3..5.
        rendered = "\n".join(run_osascript.call_args.args)
        self.assertIn("set starting slide of slideShowSettings to 3", rendered)
        self.assertIn("set ending slide of slideShowSettings to 5", rendered)

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
