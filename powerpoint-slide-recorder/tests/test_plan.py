"""Tests for the offline `plan` command: the same planning `record` runs, with no PowerPoint, screen or audio device."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from typer.testing import CliRunner

from powerpoint_slide_recorder_cli import client
from powerpoint_slide_recorder_cli import recorder as record
from powerpoint_slide_recorder_cli.main import app

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PLAN_KEYS = {"deck_path", "cue_marker", "narration_audio", "duration_seconds", "actions", "items", "timing_plan_path"}

# Slide 2 plays two click builds (1.5 s and 0.5 s) and its last click effect owns a next-click after-effect.
SLIDE_TWO_TIMING = (
    f'<p:sld xmlns:p="{P_NS}"><p:timing><p:tnLst><p:par><p:cTn nodeType="mainSeq"><p:childTnLst>'
    '<p:par><p:cTn><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst><p:childTnLst>'
    '<p:par><p:cTn nodeType="clickEffect" dur="1500"/></p:par></p:childTnLst></p:cTn></p:par>'
    '<p:par><p:cTn><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst><p:childTnLst>'
    '<p:par><p:cTn nodeType="clickEffect"><p:childTnLst>'
    '<p:par><p:cTn nodeType="afterEffect" masterRel="nextClick" afterEffect="1" dur="500"/></p:par>'
    '</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>'
    '</p:childTnLst></p:cTn></p:par></p:tnLst></p:timing></p:sld>'
)
EMPTY_SLIDE = f'<p:sld xmlns:p="{P_NS}"/>'


def write_wav(path, seconds):
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(22050)
        handle.writeframes(b"\x00\x08" * int(22050 * seconds))


def write_deck(path):
    ids = "".join(f'<p:sldId id="{256 + n}" r:id="rId{n}"/>' for n in (1, 2, 3))
    relationships = "".join(
        f'<Relationship Id="rId{n}" Target="slides/slide{n}.xml"/>' for n in (1, 2, 3)
    )
    layout_rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" '
        'Target="../slideLayouts/slideLayout1.xml"/></Relationships>'
    )
    with zipfile.ZipFile(path, "w") as deck:
        deck.writestr(
            "ppt/presentation.xml",
            f'<p:presentation xmlns:p="{P_NS}" xmlns:r="{R_NS}"><p:sldIdLst>{ids}</p:sldIdLst></p:presentation>',
        )
        deck.writestr(
            "ppt/_rels/presentation.xml.rels",
            f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{relationships}</Relationships>',
        )
        deck.writestr("ppt/slideLayouts/slideLayout1.xml", EMPTY_SLIDE)
        for number in (1, 2, 3):
            deck.writestr(f"ppt/slides/slide{number}.xml", SLIDE_TWO_TIMING if number == 2 else EMPTY_SLIDE)
            deck.writestr(f"ppt/slides/_rels/slide{number}.xml.rels", layout_rels)


class PlanFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.deck = self.root / "deck.pptx"
        write_deck(self.deck)
        specs = [
            # slide, transcript, seconds, extra item fields
            (1, "alpha || beta", 2.0, {"cue_offsets_seconds": [0.5]}),
            (2, "one two || three four || five six", 3.0, {}),
            (3, "closing words", 2.5, {"media_start": "on_click"}),
        ]
        items = []
        for slide, transcript, seconds, extra in specs:
            transcript_path = self.root / f"{slide}.txt"
            audio_path = self.root / f"{slide}.wav"
            transcript_path.write_text(transcript, encoding="utf-8")
            write_wav(audio_path, seconds)
            items.append({"slide": slide, "transcript_path": str(transcript_path), "audio_path": str(audio_path), **extra})
        self.items = self.root / "items.json"
        self.items.write_text(json.dumps({"items": items}), encoding="utf-8")
        self.click_steps = {1: 1, 2: 2, 3: 1}

    def plan_args(self, work_dir, **overrides):
        values = {
            "--deck": self.deck,
            "--items": self.items,
            "--work-dir": work_dir,
            "--click-steps": "1,2,1",
            "--recording-lead-seconds": "1.5",
            "--slide-pause-seconds": "0.4",
        }
        values.update(overrides)
        return ["plan", *[part for pair in values.items() for part in pair]]

    def invoke(self, args):
        return CliRunner().invoke(app, [str(arg) for arg in args])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg and ffprobe")
class PlanMatchesRecordPlanningTests(PlanFixture):
    def test_plan_output_equals_what_prepare_gives_record_for_the_same_inputs(self):
        work = self.root / "work"
        # What record does: build_config, read the XML-derived inputs, hand prepare() the measured clicks.
        config = record.build_config(SimpleNamespace(
            deck=self.deck, items=self.items, output=self.root / "out.mp4", work_dir=work, video_input="3",
            cue_marker="||", framerate=30, recording_lead_seconds=1.5, slide_pause_seconds=0.4,
            slideshow_start_seconds=2.0, output_width=1920, output_height=1080, force_resolution=False,
            force_aspect_ratio=None, ronin_home=None,
        ))
        terminal, settle = record.deck_xml_click_timing(config["deck_path"], record.prepared_slide_numbers(config["items"]))
        expected = record.prepare(config, self.click_steps, terminal, settle)

        result = self.invoke(self.plan_args(work))

        self.assertEqual(result.exit_code, 0, result.output)
        output = json.loads(result.stdout)
        self.assertEqual(set(output), PLAN_KEYS)
        self.assertEqual(output.pop("timing_plan_path"), str(work.resolve() / "timing-plan.json"))
        self.assertEqual(output, expected)
        self.assertEqual(json.loads((work / "timing-plan.json").read_text()), expected)
        # The deck's XML was read: slide 2's last click effect has a terminal after-effect and a 1.5 s build.
        self.assertEqual([item["terminal_after_effect_steps"] for item in output["items"]], [0, 1, 0])
        self.assertEqual([item["click_settle_seconds"] for item in output["items"]], [0.7, 1.7, 0.7])
        self.assertEqual([item["measured_click_steps"] for item in output["items"]], [1, 2, 1])
        self.assertEqual([item["cue_timing_method"] for item in output["items"]], ["explicit", "word-ratio", "word-ratio"])
        self.assertEqual(
            [action["reason"] for action in output["actions"]].count("terminal after effect"), 1
        )
        self.assertTrue(Path(output["narration_audio"]).is_file())

    def test_plan_calls_the_same_prepare_record_calls(self):
        work = self.root / "work"
        with mock.patch.object(record, "prepare", wraps=record.prepare) as prepare:
            result = self.invoke(self.plan_args(work))

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(prepare.call_count, 1)
        config, click_steps, terminal, settle = prepare.call_args.args
        self.assertEqual(click_steps, self.click_steps)
        self.assertEqual(terminal, {1: 0, 2: 1, 3: 0})
        self.assertEqual(settle, {1: 0.7, 2: 1.7, 3: 0.7})
        self.assertEqual(config["recording_lead_seconds"], 1.5)
        self.assertEqual(config["slide_pause_seconds"], 0.4)

    def test_plan_never_builds_the_recording_client_or_touches_powerpoint(self):
        launched = []
        real_run = subprocess.run

        def watching_run(command, *args, **kwargs):
            launched.append(Path(command[0]).name)
            return real_run(command, *args, **kwargs)

        real_which = shutil.which

        def which_without_ui_tools(name, *args, **kwargs):
            return None if name in ("osascript", "afplay", "open") else real_which(name, *args, **kwargs)

        with mock.patch.object(client, "get_client", side_effect=AssertionError("plan must not build the client")), \
                mock.patch("powerpoint_slide_recorder_cli.commands.get_client", side_effect=AssertionError("no client")), \
                mock.patch.object(client.shutil, "which", side_effect=which_without_ui_tools), \
                mock.patch.object(record, "run_osascript", side_effect=AssertionError("osascript")), \
                mock.patch.object(record, "capture_osascript", side_effect=AssertionError("osascript")), \
                mock.patch.object(record, "press_space", side_effect=AssertionError("keypress")), \
                mock.patch.object(record.subprocess, "run", side_effect=watching_run):
            result = self.invoke(self.plan_args(self.root / "work"))

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(launched)
        self.assertLessEqual(set(launched), {"ffmpeg", "ffprobe"})

    def test_installed_style_launch_runs_with_osascript_afplay_and_open_off_the_path(self):
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        for tool in ("ffmpeg", "ffprobe"):
            (bin_dir / tool).symlink_to(shutil.which(tool))
        env = {"PATH": str(bin_dir), "HOME": str(self.root), "XDG_DATA_HOME": str(self.root / "xdg")}
        arguments = [str(arg) for arg in self.plan_args(self.root / "work")]

        completed = subprocess.run(
            [sys.executable, "-m", "powerpoint_slide_recorder_cli.main", *arguments],
            env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(set(json.loads(completed.stdout)), PLAN_KEYS)
        for tool in ("osascript", "afplay", "open"):
            self.assertIsNone(shutil.which(tool, path=str(bin_dir)))

    def test_plan_defaults_match_record_defaults(self):
        work = self.root / "work"
        arguments = self.plan_args(work)
        for option in ("--recording-lead-seconds", "--slide-pause-seconds"):
            index = arguments.index(option)
            del arguments[index:index + 2]

        result = self.invoke(arguments)

        self.assertEqual(result.exit_code, 0, result.output)
        output = json.loads(result.stdout)
        self.assertEqual(output["items"][0]["audio_start_seconds"], record.DEFAULT_RECORDING_LEAD_SECONDS)
        self.assertEqual(output["cue_marker"], record.DEFAULT_CUE_MARKER)

    def test_plan_help_lists_every_option(self):
        result = self.invoke(["plan", "--help"])

        self.assertEqual(result.exit_code, 0)
        for option in ("--deck", "--items", "--work-dir", "--click-steps", "--cue-marker",
                       "--recording-lead-seconds", "--slide-pause-seconds"):
            self.assertIn(option, result.output)
        for record_only in ("--output", "--video-input", "--force-resolution"):
            self.assertNotIn(record_only, result.output)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg and ffprobe")
class PlanBadInputTests(PlanFixture):
    def assert_fails(self, args, message):
        result = self.invoke(args)

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertEqual(result.stdout, "")
        self.assertIn(message, result.stderr)

    def test_missing_deck(self):
        self.assert_fails(self.plan_args(self.root / "work", **{"--deck": self.root / "none.pptx"}), "PowerPoint deck not found")

    def test_missing_items_file(self):
        self.assert_fails(self.plan_args(self.root / "work", **{"--items": self.root / "none.json"}), "Items file not found")

    def test_deck_that_is_not_a_presentation(self):
        bad = self.root / "bad.pptx"
        bad.write_bytes(b"not a zip")
        self.assert_fails(self.plan_args(self.root / "work", **{"--deck": bad}), "not a readable OOXML presentation")

    def test_item_slide_beyond_the_deck(self):
        payload = json.loads(self.items.read_text())
        payload["items"] = payload["items"][2:] + [{**payload["items"][2], "slide": 4}]
        self.items.write_text(json.dumps(payload))
        self.assert_fails(self.plan_args(self.root / "work", **{"--click-steps": "1,1"}), "slide index 4 is outside the 3 slides")

    def test_click_steps_that_disagree_with_the_cue_markers(self):
        self.assert_fails(
            self.plan_args(self.root / "work", **{"--click-steps": "1,3,1"}),
            "slide 2 has 2 cue marker but the live slide show consumes 3 click steps",
        )

    def test_click_steps_missing_the_media_start_click(self):
        self.assert_fails(
            self.plan_args(self.root / "work", **{"--click-steps": "1,2,0"}),
            "slide 3 has 0 cue marker and 1 media-start click but the live slide show consumes 0 click steps",
        )

    def test_wrong_number_of_click_steps(self):
        self.assert_fails(self.plan_args(self.root / "work", **{"--click-steps": "1,2"}), "--click-steps has 2 counts but the items file has 3 items")

    def test_click_steps_must_be_whole_numbers(self):
        for value in ("1,x,1", "1,-2,1", "1,,1", "", "1,2.5,1"):
            with self.subTest(value=value):
                self.assert_fails(self.plan_args(self.root / "work", **{"--click-steps": value}), "--click-steps entries must be whole numbers")

    def test_click_steps_is_required(self):
        arguments = self.plan_args(self.root / "work")
        index = arguments.index("--click-steps")
        del arguments[index:index + 2]

        result = self.invoke(arguments)

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--click-steps", result.output)

    def test_empty_cue_marker(self):
        self.assert_fails(self.plan_args(self.root / "work", **{"--cue-marker": ""}), "--cue-marker cannot be empty")

    def test_negative_lead_and_pause(self):
        self.assert_fails(self.plan_args(self.root / "work", **{"--recording-lead-seconds": "-1"}), "--recording-lead-seconds cannot be negative")
        self.assert_fails(self.plan_args(self.root / "work", **{"--slide-pause-seconds": "-1"}), "--slide-pause-seconds cannot be negative")

    def test_missing_ffmpeg_is_named(self):
        with mock.patch.object(client.shutil, "which", return_value=None):
            self.assert_fails(self.plan_args(self.root / "work"), "Required executable not found in PATH: ffmpeg")

    def test_bad_input_writes_nothing_to_the_work_folder(self):
        work = self.root / "work"

        self.invoke(self.plan_args(work, **{"--click-steps": "1,3,1"}))

        self.assertFalse(work.exists())


class RecordKeepsItsConfigTests(PlanFixture):
    def test_build_config_is_the_plan_config_plus_the_recording_settings(self):
        args = SimpleNamespace(
            deck=self.deck, items=self.items, output=self.root / "out.mp4", work_dir=self.root / "work", video_input="3",
            cue_marker="||", framerate=30, recording_lead_seconds=1.0, slide_pause_seconds=0.25,
            slideshow_start_seconds=2.0, output_width=1920, output_height=1080, force_resolution=False,
            force_aspect_ratio=None, ronin_home=None,
        )

        config = record.build_config(args)

        self.assertEqual(set(config), {
            "deck_path", "items", "output_path", "work_dir", "ffmpeg_video_input", "ffmpeg_framerate", "output_width",
            "output_height", "force_resolution", "force_aspect_ratio", "recording_lead_seconds", "slide_pause_seconds",
            "slideshow_start_seconds", "cue_marker", "ronin_home",
        })
        plan_config = record.build_plan_config(args)
        for key, value in plan_config.items():
            self.assertEqual(config[key], value)


if __name__ == "__main__":
    unittest.main()
