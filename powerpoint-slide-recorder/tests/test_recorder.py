import contextlib
import io
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from powerpoint_slide_recorder_cli.client import PowerPointSlideRecorderClient
from powerpoint_slide_recorder_cli.main import app
from powerpoint_slide_recorder_cli import recorder as record
from typer.testing import CliRunner


TEST_PRESENTATIONML_NAMESPACE = "http://schemas.openxmlformats.org/presentationml/2006/main"


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
            "cue_count": 1,
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
        "coursecraft_repo_root": None,
    }
    config.update(overrides)
    return config


class DemoEnvironmentPrepTests(unittest.TestCase):
    def test_demo_environment_manifest_resolves_from_coursecraft_projection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = root / record.DEMO_ENVIRONMENT_AUTOMATION_MODULE_RELATIVE_PATH
            manifest.parent.mkdir(parents=True)
            manifest.write_text("@{}", encoding="utf-8")
            (root / "course-pipeline.json").write_text("{}", encoding="utf-8")

            with mock.patch.object(record.Path, "cwd", return_value=root / "nested"):
                self.assertEqual(record.resolve_demo_environment_automation_module_path(), manifest.resolve())

    def test_demo_environment_manifest_requires_coursecraft_projection_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(record.Path, "cwd", return_value=Path(temp_dir)):
                with self.assertRaisesRegex(FileNotFoundError, "CourseCraft repo root not found"):
                    record.resolve_demo_environment_automation_module_path()

    def test_demo_environment_manifest_resolves_from_explicit_repo_root_outside_cwd(self):
        # The recorder is otherwise fully path-explicit; --coursecraft-repo-root must let a
        # caller record from any working directory without the cwd walk finding anything.
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as unrelated_cwd:
            root = Path(temp_dir)
            manifest = root / record.DEMO_ENVIRONMENT_AUTOMATION_MODULE_RELATIVE_PATH
            manifest.parent.mkdir(parents=True)
            manifest.write_text("@{}", encoding="utf-8")
            (root / "course-pipeline.json").write_text("{}", encoding="utf-8")

            with mock.patch.object(record.Path, "cwd", return_value=Path(unrelated_cwd)):
                resolved = record.resolve_demo_environment_automation_module_path(root)

            self.assertEqual(resolved, manifest.resolve())

    def test_coursecraft_repo_root_failure_names_the_explicit_option(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(record.Path, "cwd", return_value=Path(temp_dir)):
                with self.assertRaisesRegex(FileNotFoundError, "--coursecraft-repo-root"):
                    record.resolve_coursecraft_repo_root()

    def test_demo_environment_prep_passes_explicit_repo_root_to_the_manifest_lookup(self):
        root = Path("/tmp/course")
        module_path = root / record.DEMO_ENVIRONMENT_AUTOMATION_MODULE_RELATIVE_PATH

        with mock.patch.object(
            record, "resolve_demo_environment_automation_module_path", return_value=module_path
        ) as resolve_manifest, \
                mock.patch.object(record, "require_path", side_effect=lambda path, description: Path(path)), \
                mock.patch.object(record, "run"):
            record.run_demo_environment_recording_prep(root)

        self.assertEqual(resolve_manifest.call_args.args[0], root)

    def test_demo_environment_prep_runs_existing_focus_and_notification_helpers(self):
        module_path = Path("/tmp/course/.agents/skills/demo-environment-automation/tools/DemoEnvironmentAutomation/DemoEnvironmentAutomation.psd1")

        with mock.patch.object(record, "resolve_demo_environment_automation_module_path", return_value=module_path), \
                mock.patch.object(record, "require_path", side_effect=lambda path, description: Path(path)), \
                mock.patch.object(record, "run") as run_command:
            record.run_demo_environment_recording_prep()

        command = run_command.call_args.args[0]
        script = command[-1]
        self.assertEqual(command[:3], [str(record.DEMO_ENVIRONMENT_PWSH_PATH), "-NoProfile", "-NonInteractive"])
        self.assertEqual(command[3], "-Command")
        self.assertIn("Import-Module -DisableNameChecking", script)
        self.assertIn(str(module_path), script)
        self.assertLess(script.index("Set-MacOSDoNotDisturb -SoftPass"), script.index("Remove-MacOSNotifications"))
        self.assertEqual(
            run_command.call_args.kwargs["timeout"],
            record.DEMO_ENVIRONMENT_RECORDING_PREP_TIMEOUT_SECONDS,
        )

    def test_demo_environment_prep_failure_is_clear(self):
        module_path = Path("/tmp/course/.agents/skills/demo-environment-automation/tools/DemoEnvironmentAutomation/DemoEnvironmentAutomation.psd1")

        with mock.patch.object(record, "resolve_demo_environment_automation_module_path", return_value=module_path), \
                mock.patch.object(record, "require_path", side_effect=lambda path, description: Path(path)), \
                mock.patch.object(record, "run", side_effect=subprocess.CalledProcessError(7, ["pwsh"])):
            with self.assertRaisesRegex(RuntimeError, "Demo environment prep failed before recording \\(exit 7\\)"):
                record.run_demo_environment_recording_prep()


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.demo_prep_patcher = mock.patch.object(record, "run_demo_environment_recording_prep")
        self.demo_environment_prep = self.demo_prep_patcher.start()
        self.capture_overlay_settle_original = record.settle_capture_overlay
        self.capture_overlay_settle_patcher = mock.patch.object(record, "settle_capture_overlay")
        self.capture_overlay_settle = self.capture_overlay_settle_patcher.start()
        # The live click-step probe drives PowerPoint; every record() test stubs it and
        # asserts on what the drive does with the measurement, not on the probe's IO.
        self.click_step_probe_patcher = mock.patch.object(
            record, "measure_slide_click_steps", return_value={1: 1, 2: 1}
        )
        self.click_step_probe = self.click_step_probe_patcher.start()
        self.cue_count_check_patcher = mock.patch.object(record, "assert_cue_counts_match_click_steps")
        self.cue_count_check = self.cue_count_check_patcher.start()
        # audio_peak_dbfs shells out to ffmpeg through subprocess.run, which these tests
        # reach with subprocess.Popen patched to a FakeProcess. Stub the measurement so the
        # narration gain stays a real computation over a known peak.
        self.audio_peak_patcher = mock.patch.object(record, "audio_peak_dbfs", return_value=-1.4)
        self.audio_peak = self.audio_peak_patcher.start()

    def tearDown(self):
        self.audio_peak_patcher.stop()
        self.cue_count_check_patcher.stop()
        self.click_step_probe_patcher.stop()
        self.capture_overlay_settle_patcher.stop()
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

    def test_macos_display_helper_moves_cursor_with_quartz(self):
        quartz = SimpleNamespace(
            CGMainDisplayID=mock.Mock(return_value=1),
            CGPointMake=mock.Mock(return_value=(1919, 540)),
            CGEventCreateMouseEvent=mock.Mock(return_value="mouse-event"),
            CGEventPost=mock.Mock(),
            kCGEventMouseMoved=5,
            kCGMouseButtonLeft=0,
            kCGHIDEventTap=0,
        )

        with mock.patch.dict(record.sys.modules, {"Quartz": quartz}), \
                mock.patch.object(record.sys, "argv", ["helper", "move_cursor", "1919", "540"]):
            exec(record.MACOS_DISPLAY_HELPER, {})

        quartz.CGPointMake.assert_called_once_with(1919, 540)
        quartz.CGEventCreateMouseEvent.assert_called_once_with(None, 5, (1919, 540), 0)
        quartz.CGEventPost.assert_called_once_with(0, "mouse-event")

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
                }], "||")

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
            }], "||")

        self.assertEqual(items[0]["identity"], {
            "field": "slide",
            "value": 3,
        })
        self.assertNotIn("slide", items[0])
        self.assertNotIn("name", items[0])

    def test_click_steps_from_walk_counts_presses_that_do_not_change_the_slide(self):
        # Slide 1 builds twice then advances; slide 2 builds once then ends the show.
        counts = record.click_steps_from_slide_index_walk([1, 2], [1, 1, 2, 2, None])

        self.assertEqual(counts, {1: 2, 2: 1})

    def test_click_steps_from_walk_counts_slides_with_no_animations_as_zero(self):
        counts = record.click_steps_from_slide_index_walk([4, 5, 6], [5, 6, None])

        self.assertEqual(counts, {4: 0, 5: 0, 6: 0})

    def test_click_steps_from_walk_measures_more_steps_than_the_deck_xml_authored(self):
        # The shipped defect: slide 16 of the m1 deck authors 4 clickEffect nodes in its
        # layout but the running show consumes 8 click steps, because PowerPoint expands
        # the layout's paragraph-build template against the slide's own content. The walk
        # reports what the show consumed, which is the number the drive must plan.
        observed = [16] * 8 + [None]

        counts = record.click_steps_from_slide_index_walk([16], observed)

        self.assertEqual(counts, {16: 8})

    def test_click_steps_from_walk_rejects_a_jump_past_the_next_slide(self):
        with self.assertRaisesRegex(RuntimeError, "jumped from slide 1 to slide 3 at press 2"):
            record.click_steps_from_slide_index_walk([1, 2, 3], [1, 3, None])

    def test_click_steps_from_walk_rejects_a_show_that_ends_early(self):
        with self.assertRaisesRegex(RuntimeError, "ended on slide 1 at press 1 before reaching"):
            record.click_steps_from_slide_index_walk([1, 2], [None])

    def test_click_steps_from_walk_rejects_a_walk_that_never_finishes(self):
        with self.assertRaisesRegex(RuntimeError, "did not finish within 3 presses"):
            record.click_steps_from_slide_index_walk([1, 2], [1, 1, 1])

    def test_live_slideshow_slide_index_reads_the_running_show(self):
        with mock.patch.object(record, "capture_osascript", return_value="7"):
            self.assertEqual(record.live_slideshow_slide_index(), 7)

    def test_live_slideshow_slide_index_reports_none_once_the_show_ends(self):
        with mock.patch.object(record, "capture_osascript", return_value="ended"):
            self.assertIsNone(record.live_slideshow_slide_index())

    def test_live_slideshow_slide_index_rejects_an_unexpected_response(self):
        with mock.patch.object(record, "capture_osascript", return_value="missing value"):
            with self.assertRaisesRegex(RuntimeError, "Unexpected slideshow slide index response"):
                record.live_slideshow_slide_index()

    def test_position_watcher_passes_when_the_show_is_on_the_planned_slide(self):
        watcher = record.SlideshowPositionWatcher(5)

        with mock.patch.object(record, "live_slideshow_slide_index", return_value=5):
            watcher.check()

    def test_position_watcher_aborts_when_the_deck_runs_ahead_of_the_narration(self):
        # The shipped defect's signature: extra presses spilled into the next slide, so
        # the show sits on slide 4 while the plan is still driving slide 3.
        watcher = record.SlideshowPositionWatcher(3)

        with mock.patch.object(record, "live_slideshow_slide_index", return_value=4):
            with self.assertRaisesRegex(RuntimeError, "on slide 4 but the timing plan is driving slide 3"):
                watcher.check()

    def test_position_watcher_aborts_when_the_show_ended_early(self):
        watcher = record.SlideshowPositionWatcher(2)

        with mock.patch.object(record, "live_slideshow_slide_index", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "ended while slide 2 was still being driven"):
                watcher.check()

    def test_position_watcher_accepts_the_previous_slide_while_an_advance_lands(self):
        # An advance press does not land instantly, so the bounded transition must not
        # abort on the very next poll while PowerPoint is still rendering it.
        watcher = record.SlideshowPositionWatcher(2)
        watcher.expect_slide(3)

        with mock.patch.object(record, "live_slideshow_slide_index", return_value=2):
            watcher.check()

        self.assertEqual(watcher.expected_slide, 2)

    def test_position_watcher_commits_the_advance_once_the_new_slide_is_observed(self):
        watcher = record.SlideshowPositionWatcher(2)
        watcher.expect_slide(3)

        with mock.patch.object(record, "live_slideshow_slide_index", return_value=3):
            watcher.check()

        self.assertEqual(watcher.expected_slide, 3)

    def test_position_watcher_aborts_when_an_advance_press_is_eaten_by_an_animation(self):
        # The other half of the shipped defect: the deck needed more click steps than
        # were planned, so the "next slide" press built an animation instead of advancing.
        # Once the bounded transition window expires, staying put is a hard failure.
        watcher = record.SlideshowPositionWatcher(10)
        watcher.expect_slide(11)

        with mock.patch.object(record, "live_slideshow_slide_index", return_value=10), \
                mock.patch.object(record.time, "monotonic", return_value=1e9):
            with self.assertRaisesRegex(RuntimeError, "did not advance from slide 10 to slide 11"):
                watcher.check()

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
                    plan = record.prepare(config, {1: 1, 2: 0})

            self.assertEqual(generated_silence, ["silence-lead.wav", "silence-slide.wav"])
            self.assertEqual(plan["actions"], [{
                "at_seconds": 2.0,
                "key": "space",
                "item": "Slide 1",
                "slide": 1,
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

    def test_sleep_until_never_runs_the_presence_check_itself(self):
        process = FakeProcess([None], 0)
        presence_check = mock.Mock()
        watcher = record.SlideshowPresenceWatcher(presence_check, 2.0)

        record.sleep_until(0, [(process, "ffmpeg")], watcher)

        presence_check.assert_not_called()

    def test_sleep_until_raises_the_watchers_recorded_absence(self):
        process = FakeProcess([None], 0)

        class FailedWatcher:
            def raise_if_failed(self):
                raise RuntimeError("PowerPoint slideshow was not present during capture: gone")

        with self.assertRaisesRegex(RuntimeError, "slideshow was not present during capture"):
            record.sleep_until(0, [(process, "ffmpeg")], FailedWatcher())

    def test_presence_watcher_records_a_genuinely_absent_slideshow(self):
        presence_check = mock.Mock(side_effect=RuntimeError("Window containing Slide Show not found"))

        with record.SlideshowPresenceWatcher(presence_check, 0.01) as watcher:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    watcher.raise_if_failed()
                except RuntimeError as error:
                    self.assertIn("Window containing Slide Show not found", str(error))
                    return
                time.sleep(0.01)

        self.fail("presence watcher never recorded the absent slideshow")

    def test_action_on_schedule_allows_ordinary_jitter(self):
        action = {"at_seconds": 10.0, "key": "space", "item": "Slide 1", "reason": "action cue"}

        record.assert_action_on_schedule(0, action, 0.0, 10.0 + record.MAX_ACTION_DRIFT_SECONDS)

    def test_action_on_schedule_aborts_a_desynced_advance(self):
        action = {"at_seconds": 10.0, "key": "space", "item": "Slide 9", "reason": "next slide"}

        with self.assertRaisesRegex(RuntimeError, "Slide advance 3 of Slide 9 \\(next slide\\)"):
            record.assert_action_on_schedule(2, action, 0.0, 34.0)

    def test_record_runs_demo_environment_prep_before_capture_starts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = slide_config(Path(temp_dir), work_dir="/tmp/work")
        ffmpeg_process = FakeProcess([None, None, None], 0)
        audio_process = FakeProcess([None, 0], 0)
        events = []

        def fake_prepare(config, click_steps):
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

        self.demo_environment_prep.side_effect = lambda coursecraft_repo_root: events.append("demo_prep")

        with mock.patch.object(record, "probe_capture_dimensions", return_value=(1920, 1080)), \
                mock.patch.object(record, "prepare", side_effect=fake_prepare), \
                mock.patch.object(record, "create_powerpoint_state", side_effect=fake_state), \
                mock.patch.object(record, "start_slideshow", side_effect=fake_start_slideshow), \
                mock.patch.object(record, "close_slideshow_and_deck"), \
                mock.patch.object(record, "live_slideshow_slide_index", return_value=1), \
                mock.patch.object(record, "run"), \
                mock.patch.object(subprocess, "Popen", side_effect=fake_popen):
            record.record(config)

        # PowerPoint state is captured before the live click-step probe opens the deck,
        # so the same cleanup path closes whatever the probe left behind.
        self.assertEqual(events[:4], ["demo_prep", "state", "prepare", "slideshow"])
        self.assertEqual(events[4], "ffmpeg")

    def test_record_forwards_configured_coursecraft_repo_root_to_demo_environment_prep(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = slide_config(
                Path(temp_dir),
                work_dir="/tmp/work",
                coursecraft_repo_root="/tmp/coursecraft",
            )
        ffmpeg_process = FakeProcess([None, None, None], 0)
        audio_process = FakeProcess([None, 0], 0)

        def fake_popen(command, **kwargs):
            if command[0] == "ffmpeg":
                return ffmpeg_process
            if command[0] == "afplay":
                return audio_process
            raise AssertionError(command)

        with mock.patch.object(record, "probe_capture_dimensions", return_value=(1920, 1080)), \
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
                mock.patch.object(record, "live_slideshow_slide_index", return_value=1), \
                mock.patch.object(record, "run"), \
                mock.patch.object(subprocess, "Popen", side_effect=fake_popen):
            record.record(config)

        self.assertEqual(self.demo_environment_prep.call_args.args[0], "/tmp/coursecraft")

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
                mock.patch.object(record, "live_slideshow_slide_index", return_value=1), \
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
                mock.patch.object(record, "live_slideshow_slide_index", return_value=1), \
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
                mock.patch.object(record, "live_slideshow_slide_index", return_value=1), \
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
                mock.patch.object(record, "create_powerpoint_state", return_value={
                    "powerpoint_was_running": False,
                    "deck_was_open": False,
                }), \
                mock.patch.object(record, "close_slideshow_and_deck") as close_slideshow_and_deck, \
                mock.patch.object(record, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "prepare failed"):
                record.record(config)

        self.assertEqual(events, ["set_resolution", "restore_resolution"])
        # The click-step probe already opened the deck by this point, so the failure path
        # must close PowerPoint rather than leaving a probe-opened deck behind.
        close_slideshow_and_deck.assert_called_once()
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

        self.capture_overlay_settle.side_effect = lambda: events.extend([
            "park_after_capture",
            ("settle_overlay", record.CAPTURE_OVERLAY_SETTLE_SECONDS),
        ])

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
                mock.patch.object(record, "live_slideshow_slide_index", return_value=1), \
                mock.patch.object(record, "run", side_effect=fake_run), \
                mock.patch.object(subprocess, "Popen", side_effect=[ffmpeg_process, audio_process]):
            record.record(config)

        self.assertEqual(events, [
            "park_after_capture",
            ("settle_overlay", record.CAPTURE_OVERLAY_SETTLE_SECONDS),
            "close_powerpoint",
            "mux",
        ])

    def test_advance_expectation_opens_before_the_press_is_sent(self):
        # PowerPoint can land an advance while press_space() is still returning, and the
        # position check runs on the watcher thread. Registering the expectation after the
        # press left a window where a poll saw the new slide while the plan still expected
        # the old one, and a correctly driven 24-slide recording aborted on slide 10 with
        # "on slide 11 but the timing plan is driving slide 10".
        with tempfile.TemporaryDirectory() as temp_dir:
            config = slide_config(Path(temp_dir), work_dir="/tmp/work")
        # The watcher starts out expecting this item's slide, which is also what the
        # mocked live show reports, so only the advance transition is under test.
        config["items"][0]["identity"]["value"] = 10
        ffmpeg_process = FakeProcess([None] * 10, 0)
        audio_process = FakeProcess([None] * 6 + [0], 0)
        events = []

        original_expect_slide = record.SlideshowPositionWatcher.expect_slide

        def tracking_expect_slide(self, slide_number):
            events.append(("expect_slide", slide_number))
            original_expect_slide(self, slide_number)

        with mock.patch.object(record, "prepare", return_value={
            "narration_audio": "/tmp/narration.wav",
            "actions": [{
                "at_seconds": 0.0,
                "slide": 10,
                "item": "Slide 10",
                "reason": record.SLIDE_ADVANCE_REASON,
            }],
        }), \
                mock.patch.object(record, "probe_capture_dimensions", return_value=(1920, 1080)), \
                mock.patch.object(record, "create_powerpoint_state", return_value={
                    "powerpoint_was_running": False,
                    "deck_was_open": False,
                }), \
                mock.patch.object(record, "start_slideshow"), \
                mock.patch.object(record, "close_slideshow_and_deck"), \
                mock.patch.object(record, "live_slideshow_slide_index", return_value=10), \
                mock.patch.object(record, "press_space", side_effect=lambda: events.append("press")), \
                mock.patch.object(record.SlideshowPositionWatcher, "expect_slide", tracking_expect_slide), \
                mock.patch.object(record, "run"), \
                mock.patch.object(subprocess, "Popen", side_effect=[ffmpeg_process, audio_process]):
            record.record(config)

        self.assertEqual(events, [("expect_slide", 11), "press"])

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
                mock.patch.object(record, "live_slideshow_slide_index", return_value=1), \
                mock.patch.object(record, "run", side_effect=fake_run), \
                mock.patch.object(subprocess, "Popen", side_effect=[ffmpeg_process, audio_process]):
            record.record(config)

        mux_command = commands[0]
        self.assertEqual(
            mux_command[mux_command.index("-ss") + 1],
            str(record.CAPTURE_OVERLAY_SETTLE_SECONDS),
        )
        self.assertLess(mux_command.index("-ss"), mux_command.index("-i"))
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
                mock.patch.object(record, "live_slideshow_slide_index", return_value=1), \
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

    def test_save_dialog_matches_exact_title_without_matching_save_as(self):
        save_entry = record.match_startup_dialog({"title": "Save", "text": "Save"})

        self.assertEqual(save_entry["name"], "Save")
        self.assertEqual(save_entry["dismiss_button"], ["Don't Save", "Discard", "Cancel"])
        self.assertIsNone(record.match_startup_dialog({"title": "Save As", "text": ""}))

    def test_auto_dismiss_save_dialog_uses_safe_discard_buttons(self):
        dialog = {"title": "Save", "text": "Save"}
        with mock.patch.object(record, "frontmost_powerpoint_dialog", return_value=dialog), \
                mock.patch.object(record, "capture_osascript") as capture_osascript:
            self.assertEqual(record.try_auto_dismiss_startup_dialog(), "Save")

        rendered = "\n".join(capture_osascript.call_args.args)
        self.assertLess(rendered.index('button "Don\'t Save"'), rendered.index('button "Discard"'))
        self.assertLess(rendered.index('button "Discard"'), rendered.index('button "Cancel"'))

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

    def test_park_slideshow_cursor_uses_right_edge_midpoint(self):
        with mock.patch.object(record, "screen_point_size", return_value=(1920, 1080)), \
                mock.patch.object(record, "run_macos_display_helper") as helper:
            record.park_slideshow_cursor()

        helper.assert_called_once_with("move_cursor", 1856, 540)

    def test_settle_capture_overlay_reparks_then_waits(self):
        with mock.patch.object(record, "park_slideshow_cursor") as park, \
                mock.patch.object(record.time, "sleep") as sleep:
            self.capture_overlay_settle_original()

        park.assert_called_once_with()
        sleep.assert_called_once_with(record.CAPTURE_OVERLAY_SETTLE_SECONDS)

    def test_during_capture_watchdog_is_read_only(self):
        # The during-capture check must never run a mutating UI action (an earlier
        # regression re-ran the fullscreen action and surfaced the navigation toolbar).
        watcher = record.SlideshowPositionWatcher(1)

        with mock.patch.object(record, "execute_ui_actions") as execute, \
                mock.patch.object(record, "capture_osascript", return_value="1"):
            watcher.check()

        execute.assert_not_called()

    def test_set_slideshow_pointer_automatic_uses_powerpoint_command_u_shortcut(self):
        with mock.patch.object(record, "execute_ui_actions") as execute:
            record.set_slideshow_pointer_automatic()

        execute.assert_called_once_with([{
            "action": "keystroke_command",
            "text": "u",
        }])

    def test_start_slideshow_sets_pointer_automatic_then_parks_before_settle_delay(self):
        config = {
            "items": [{"identity": {"value": 3}}, {"identity": {"value": 5}}],
            "slideshow_start_seconds": 2.0,
        }
        events = []
        with mock.patch.object(record, "open_deck"), \
                mock.patch.object(record, "frontmost_powerpoint_dialog", return_value=None), \
                mock.patch.object(record, "run_osascript"), \
                mock.patch.object(record, "execute_ui_actions"), \
                mock.patch.object(record, "force_slideshow_fullscreen",
                                  side_effect=lambda: events.append("fullscreen")), \
                mock.patch.object(record, "set_slideshow_pointer_automatic",
                                  side_effect=lambda: events.append("pointer_automatic")), \
                mock.patch.object(record, "park_slideshow_cursor",
                                  side_effect=lambda: events.append("park_cursor")), \
                mock.patch.object(record.time, "sleep",
                                  side_effect=lambda seconds: events.append(("settle_delay", seconds))):
            record.start_slideshow(config)

        self.assertEqual(
            events,
            ["fullscreen", "pointer_automatic", "park_cursor", ("settle_delay", 2.0)],
        )

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
                    coursecraft_repo_root=root,
                )

        self.assertEqual(result.output_path, str(output))
        self.assertEqual(result.duration_seconds, 3.0)
        self.assertEqual(build_config.call_args.args[0].deck, deck)
        self.assertEqual(build_config.call_args.args[0].output_width, 1920)
        self.assertEqual(build_config.call_args.args[0].output_height, 1080)
        self.assertIs(build_config.call_args.args[0].force_resolution, True)
        self.assertEqual(build_config.call_args.args[0].force_aspect_ratio, (16, 9))
        self.assertEqual(build_config.call_args.args[0].coursecraft_repo_root, root)

    def test_public_cli_forwards_coursecraft_repo_root(self):
        runner = CliRunner()

        with mock.patch("powerpoint_slide_recorder_cli.commands.get_client") as get_client, \
                mock.patch("powerpoint_slide_recorder_cli.commands.print_json"):
            get_client.return_value.record.return_value = mock.Mock()
            result = runner.invoke(app, [
                "record",
                "--deck", "/tmp/deck.pptx",
                "--items", "/tmp/items.json",
                "--output", "/tmp/out.mp4",
                "--work-dir", "/tmp/work",
                "--video-input", "3",
                "--coursecraft-repo-root", "/tmp/coursecraft",
            ])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(
            get_client.return_value.record.call_args.kwargs["coursecraft_repo_root"],
            Path("/tmp/coursecraft"),
        )

    def test_public_cli_defaults_coursecraft_repo_root_to_cwd_discovery(self):
        runner = CliRunner()

        with mock.patch("powerpoint_slide_recorder_cli.commands.get_client") as get_client, \
                mock.patch("powerpoint_slide_recorder_cli.commands.print_json"):
            get_client.return_value.record.return_value = mock.Mock()
            result = runner.invoke(app, [
                "record",
                "--deck", "/tmp/deck.pptx",
                "--items", "/tmp/items.json",
                "--output", "/tmp/out.mp4",
                "--work-dir", "/tmp/work",
                "--video-input", "3",
            ])

        self.assertEqual(result.exit_code, 0)
        self.assertIsNone(get_client.return_value.record.call_args.kwargs["coursecraft_repo_root"])


    def test_build_config_prepares_items_without_touching_powerpoint(self):
        # build_config stays offline: cue counts are checked against the live probe
        # inside record(), so building a config never needs PowerPoint running.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "transcript.txt"
            audio = root / "audio.wav"
            deck = root / "deck.pptx"
            items_path = root / "items.json"
            transcript.write_text("first || second || third", encoding="utf-8")
            audio.write_bytes(b"audio")
            deck.write_bytes(b"deck")
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
                coursecraft_repo_root=root / "coursecraft",
            )
            config = record.build_config(args)
            resolved_repo_root = str((root / "coursecraft").resolve())

        self.assertEqual(config["items"][0]["cue_count"], 2)
        self.assertEqual(config["output_width"], 1920)
        self.assertEqual(config["output_height"], 1080)
        self.assertEqual(config["coursecraft_repo_root"], resolved_repo_root)

    def test_build_config_leaves_coursecraft_repo_root_unset_for_cwd_discovery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "transcript.txt"
            audio = root / "audio.wav"
            deck = root / "deck.pptx"
            items_path = root / "items.json"
            transcript.write_text("first", encoding="utf-8")
            audio.write_bytes(b"audio")
            deck.write_bytes(b"deck")
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
                coursecraft_repo_root=None,
            )
            config = record.build_config(args)

        self.assertIsNone(config["coursecraft_repo_root"])


class LiveClickStepProbeTests(unittest.TestCase):
    """Probe and cue-count checks, unstubbed (RecordTests stubs both for its drive tests)."""

    def test_measure_slide_click_steps_walks_the_live_show_and_exits_it(self):
        config = {"deck_path": "/tmp/deck.pptx", "slideshow_start_seconds": 0}
        # Start on slide 3, one build, advance to 4, one build, then the show ends.
        indexes = [3, 3, 4, 4, None]

        with mock.patch.object(record, "open_deck"), \
                mock.patch.object(record, "clear_benign_dialogs_before_slideshow"), \
                mock.patch.object(record, "run_osascript"), \
                mock.patch.object(record, "press_space") as press_space, \
                mock.patch.object(record, "exit_slideshow_if_running") as exit_slideshow, \
                mock.patch.object(record, "live_slideshow_slide_index", side_effect=indexes), \
                mock.patch.object(record, "terminal_next_click_after_effect_step", return_value=0), \
                mock.patch.object(record.time, "sleep"):
            counts = record.measure_slide_click_steps(config, [3, 4])

        self.assertEqual(counts, {3: 1, 4: 1})
        self.assertEqual(press_space.call_count, 4)
        exit_slideshow.assert_called_once()

    def test_measure_slide_click_steps_excludes_one_terminal_after_effect(self):
        config = {"deck_path": "/tmp/deck.pptx", "slideshow_start_seconds": 0}
        indexes = [26, 26, 26, 26, 26, 26, 26, None]

        with mock.patch.object(record, "open_deck"), \
                mock.patch.object(record, "clear_benign_dialogs_before_slideshow"), \
                mock.patch.object(record, "run_osascript"), \
                mock.patch.object(record, "press_space"), \
                mock.patch.object(record, "exit_slideshow_if_running"), \
                mock.patch.object(record, "live_slideshow_slide_index", side_effect=indexes), \
                mock.patch.object(record, "terminal_next_click_after_effect_step", return_value=1), \
                mock.patch.object(record.time, "sleep"):
            counts = record.measure_slide_click_steps(config, [26])

        self.assertEqual(counts, {26: 5})

    def test_terminal_next_click_after_effect_in_xml_checks_only_the_final_click_effect(self):
        nonterminal_only = f'''<p:sld xmlns:p="{TEST_PRESENTATIONML_NAMESPACE}">
          <p:cTn nodeType="clickEffect"><p:cTn masterRel="nextClick" afterEffect="1"/></p:cTn>
          <p:cTn nodeType="clickEffect"/>
        </p:sld>'''.encode()
        terminal = f'''<p:sld xmlns:p="{TEST_PRESENTATIONML_NAMESPACE}">
          <p:cTn nodeType="clickEffect"><p:cTn masterRel="nextClick" afterEffect="1"/></p:cTn>
          <p:cTn nodeType="clickEffect"><p:cTn masterRel="nextClick" afterEffect="1"/></p:cTn>
        </p:sld>'''.encode()

        self.assertFalse(record.terminal_next_click_after_effect_in_xml(nonterminal_only))
        self.assertTrue(record.terminal_next_click_after_effect_in_xml(terminal))

    def test_slide_layout_member_resolves_the_relationship_target(self):
        relationships = b'''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
          <Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout"
                        Target="../slideLayouts/custom/slideLayout53.xml"/>
        </Relationships>'''
        deck = SimpleNamespace(read=mock.Mock(return_value=relationships))

        member = record.slide_layout_member_for_slide(deck, 26)

        self.assertEqual(member, "ppt/slideLayouts/custom/slideLayout53.xml")

    def test_measure_slide_click_steps_rejects_a_show_that_starts_on_the_wrong_slide(self):
        config = {"deck_path": "/tmp/deck.pptx", "slideshow_start_seconds": 0}

        with mock.patch.object(record, "open_deck"), \
                mock.patch.object(record, "clear_benign_dialogs_before_slideshow"), \
                mock.patch.object(record, "run_osascript"), \
                mock.patch.object(record, "press_space"), \
                mock.patch.object(record, "live_slideshow_slide_index", return_value=1), \
                mock.patch.object(record, "terminal_next_click_after_effect_step", return_value=0), \
                mock.patch.object(record.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "started on slide 1, expected slide 3"):
                record.measure_slide_click_steps(config, [3, 4])

    def test_assert_cue_counts_match_click_steps_accepts_matching_counts(self):
        items = [{"label": "Slide 1", "identity": {"field": "slide", "value": 1}, "cue_count": 2}]

        record.assert_cue_counts_match_click_steps(items, {1: 2})

    def test_assert_cue_counts_match_click_steps_rejects_a_mismatch(self):
        items = [{"label": "Slide 16", "identity": {"field": "slide", "value": 16}, "cue_count": 4}]

        with self.assertRaisesRegex(ValueError, "slide 16 has 4 cue marker but the live slide show consumes 8 click steps"):
            record.assert_cue_counts_match_click_steps(items, {16: 8})


if __name__ == "__main__":
    unittest.main()
