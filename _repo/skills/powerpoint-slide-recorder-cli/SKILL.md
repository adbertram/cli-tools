---
name: powerpoint-slide-recorder-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute powerpoint-slide-recorder operations using the `powerpoint-slide-recorder` CLI tool.
  Record narrated PowerPoint slides. For CourseCraft slide recording, first use the project screen-recording skill; this skill is only the PowerPoint command adapter.
  Triggers: powerpoint-slide-recorder, powerpoint-slide-recorder cli, PowerPoint slide recorder, screencast recorder, PowerPoint screencast, record PowerPoint screencast, screen recording slides, record slides, slide recording, cue marker recording
---

<objective>
Execute powerpoint-slide-recorder operations using the `powerpoint-slide-recorder` CLI. All powerpoint-slide-recorder interactions should use this CLI.
</objective>

<coursecraft_boundary>
For CourseCraft slide recording, this skill is not the recording workflow source
of truth. Load and follow the project-local `screen-recording` skill first when
that skill is available. That `screen-recording` skill owns the general recording guidance,
storage contract, verification rules, and troubleshooting path for both slide
and demo recordings. Use this `powerpoint-slide-recorder-cli` skill only when
the `screen-recording` slide workflow needs live `powerpoint-slide-recorder`
command syntax or execution.
</coursecraft_boundary>

<quick_start>
The `powerpoint-slide-recorder` CLI follows this pattern:
```bash
powerpoint-slide-recorder <command> [options]
```

| Command | Purpose |
| --- | --- |
| `powerpoint-slide-recorder --help` | Show available commands and global options. |
| `powerpoint-slide-recorder --version` | Show the installed CLI version. |
| `powerpoint-slide-recorder record --help` | Show the full recording contract. |
| `powerpoint-slide-recorder record ...` | Record one or more consecutive slide items. |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `powerpoint-slide-recorder` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `powerpoint-slide-recorder --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="PowerPoint Launch Permission">
**MANDATORY: Ask the user for explicit permission before launching, activating, or controlling Microsoft PowerPoint.**
This includes `powerpoint-slide-recorder record`, AppleScript/System Events automation, starting Slide Show mode, or any action that can steal focus or take over the screen. Help, version, file inspection, manifest generation, and other non-UI preflight commands do not require permission. If permission is not granted, stop before the PowerPoint action and report the exact command or step that is ready to run.
</principle>

<principle name="AI Instruction Results">
After every `powerpoint-slide-recorder` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- `record` — Record narrated PowerPoint slides. Requires a PowerPoint deck, item manifest, output path, work directory, and ffmpeg AVFoundation video input.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions when present.
**`powerpoint-slide-recorder --help` and subcommand `--help`** — Live installed command tree and option list.
**`README.md`** — Supplemental examples and workflow notes.
</reference_index>

## Known Issues

### 1. PowerPoint Recording Takes Over The Screen
**Symptom:** Running `powerpoint-slide-recorder record` or equivalent PowerPoint automation activates Microsoft PowerPoint, starts Slide Show mode, steals focus, and can take over the user's screen.
**Cause:** The recorder drives the real PowerPoint UI through AppleScript/System Events and screen capture, so the workflow is inherently interactive even though the CLI is launched from a shell.
**Fix:** Before any command or automation that launches, activates, or controls PowerPoint, ask the user for explicit permission. Perform non-UI preparation first, then pause before `powerpoint-slide-recorder record` or Slide Show automation until permission is granted.
**Verification:** Inspect this skill before recording work and confirm the permission gate appears under `PowerPoint Launch Permission`; execute only non-UI commands until the user approves the PowerPoint action.
**Recurrence Prevention:** Treat `powerpoint-slide-recorder record` as a focus-stealing UI operation, not a background command. Never start it silently.

### 2. PowerPoint Must Close Before Final Muxing
**Symptom:** After narration and slide automation completed, Microsoft PowerPoint and the deck stayed open while `ffmpeg` muxed `screen-recording.mov` and `narration.wav` into the final MP4.
**Cause:** `powerpoint_slide_recorder_cli.recorder.record()` closed PowerPoint in the `finally` block after the final mux command, so the UI remained open during long encoding work.
**Fix:** Close the slideshow and deck immediately after screen capture stops and before running the final mux command. Keep this lifecycle covered by `tests/test_recorder.py::RecordTests::test_record_closes_powerpoint_before_final_mux`.
**Verification:** Run `python3 -m unittest tests.test_recorder.RecordTests.test_record_closes_powerpoint_before_final_mux -v`, `python3 -m unittest discover -s tests -v`, `powerpoint-slide-recorder --help`, and `powerpoint-slide-recorder record --help`.
**Recurrence Prevention:** Treat screen capture completion as the boundary where PowerPoint must be released. Do not defer PowerPoint cleanup until final encoding or result formatting.

### 3. Output MP4 Has Black Bars From Aspect Ratio Mismatch
**Symptom:** A recorded slide MP4 has black bars above and below the slide content.
**Cause:** The recorder captured the selected AVFoundation source without validating its aspect ratio against the intended course output size, then muxed the raw recording without forcing a final output resolution.
**Fix:** Use `powerpoint-slide-recorder record --resolution WIDTHxHEIGHT` to define the final MP4 size. The default is `1920x1080`, and both dimensions must be positive even integers because the MP4 is encoded with `libx264`. The recorder probes `--video-input` before PowerPoint launches, fails when the capture source aspect ratio differs or is smaller than the requested output, and muxes with `-vf scale=<width>:<height>` without padding or cropping. If the source does not match because the display is in the wrong mode, use `--force-resolution` to temporarily switch the main display to `--resolution`, re-probe the capture source, record, and restore the previous display mode during cleanup. For standard 1080p course output, prefer `--force-aspect-ratio 16x9`; this switches to the highest available 16:9 source mode and scales the final MP4 down to the default 1920x1080 output.
**Verification:** Run `python3 -m unittest discover -s tests -v`, `powerpoint-slide-recorder --help`, and `powerpoint-slide-recorder record --help`; confirm the help output shows `--resolution` with default `1920x1080`, `--force-resolution`, and `--force-aspect-ratio`.
**Recurrence Prevention:** Treat `--resolution` as part of the normal recording contract. Do not bypass the preflight probe or add pad/crop filters to make mismatched capture sources fit. Do not add an external display-resolution dependency; the recorder owns display switching through its embedded macOS CoreGraphics helper.

### 4. Slideshow Starts On The Wrong Slide So Reveals Never Line Up
**Symptom:** A multi-slide clip records with every slide desynchronized from its narration: the first slide is clicked away immediately, narration ends up on the second slide, and the click-build reveals never appear at the right time (they look like they fire on the wrong slides or not at all).
**Cause:** The recorder started the show with "Play from Start" (always slide 1) and then jumped to the clip's first deck slide by typing the slide number followed by Return. In a live PowerPoint slide show the typed digit is DROPPED — only the Return registers, as a single advance — so the show lands on slide 2 instead of the requested slide. The per-cue Space schedule built for the clip's real slides then fires against the wrong slides. The click-build animations themselves are fine; this is purely a navigation bug, not an animation bug.
**Fix:** Start the show on the clip's first slide through a custom slide-show range instead of "Play from Start" + a number jump. `powerpoint_slide_recorder_cli.recorder.render_run_slideshow_range(start, end)` sets `range type` to `slide show range`, sets `starting slide`/`ending slide`, forces `advance mode` to `slide show advance manual advance`, then runs `run slide show`. The show opens directly on the starting slide in build-pending state, so Space presses fire click-builds exactly like a normal linear run. `jump_to_slide` is removed.
**Verification:** Run `python3 -m pytest tests/test_recorder.py -q` (see `test_run_slideshow_range_starts_on_clip_first_slide_via_custom_range`). For a live check, start a custom-range show at slide N and confirm `current show position` HOLDS across that slide's build-count Space presses before advancing (the builds consume the presses) instead of incrementing on every press.
**Recurrence Prevention:** Never navigate a running slide show by typing a slide number. Start on the intended slide with a custom slide-show range; the typed-number jump is unreliable.

## Domain Knowledge

### Navigating A Running PowerPoint Slide Show (AppleScript)
**Context:** Use this when the recorder (or any automation) must start or move a live PowerPoint slide show to a specific slide on macOS.
**Key Facts:** Start at a specific slide by setting a custom range on `slide show settings of active presentation` — `range type` = `slide show range` (the bare enum literal; raw code `0x00d60002`), plus integer `starting slide` and `ending slide` — then `run slide show <settings>`. With a custom range, `current show position` is RANGE-relative (1 = the starting slide), which is fine for blind, cue-driven advancing. Force `advance mode` to `slide show advance manual advance` so a deck authored with automatic slide timings cannot self-advance ahead of narration. The slide-show window is named like `PowerPoint Slide Show - [<deck>]` (it contains "Slide Show", which window-matching can key on).
**Gotchas:** Typing a slide number + Return to jump in a live show DROPS the digit and lands on slide 2 — never navigate that way. `current show position` is READ-ONLY, so you cannot set it to jump. `go to slide (slide show view ...) number N` throws a runtime "Parameter error" on current PowerPoint for Mac. `set show with animation ... to true` errors (`-10006`); it is not settable, but animations play by default. The `sdef` CLI returns empty for PowerPoint (sandboxed) — read the dictionary from `/Applications/Microsoft PowerPoint.app/Contents/Resources/PowerPoint.sdef` instead. Pluralsight-templated decks define their click-build animations on the slide LAYOUT, not on `slideN.xml`, yet they still fire on a normal/linear or custom-range run; count them as slide + layout `clickEffect` nodes under `p:timing`.

### Forced Resolution Uses Embedded macOS CoreGraphics
**Context:** Use this when a recording source fails the resolution guard and the user wants the CLI to fix the display mode automatically.
**Key Facts:** `--force-resolution` uses an embedded helper run with `/usr/bin/python3` and macOS Quartz/CoreGraphics APIs. It targets the main display, switches to the requested `--resolution`, re-runs the AVFoundation probe, performs the normal recording, and restores the previous display mode in cleanup.
**Gotchas:** The requested mode must be available on the main display. If macOS does not advertise that mode, the command fails before PowerPoint launches instead of installing or shelling out to another display tool. On macOS, `CGDisplaySetDisplayMode` can return success without changing the active mode; use a CoreGraphics configuration transaction with `CGBeginDisplayConfiguration`, `CGConfigureDisplayWithDisplayMode`, and `CGCompleteDisplayConfiguration`.

### Standard Course Recordings Use Forced 16:9 Source
**Context:** Use this when recording CourseCraft slide videos intended for final 1920x1080 delivery.
**Key Facts:** Run `powerpoint-slide-recorder record` with `--force-aspect-ratio 16x9` for standard course recordings. Do not add `--resolution 1920x1080`; the default output resolution already applies. The recorder enumerates main-display modes, selects the highest pixel-area mode whose pixel dimensions exactly match 16:9, switches to that mode, records, restores the previous display mode, and scales the final MP4 to 1920x1080.
**Gotchas:** `--force-aspect-ratio` and `--force-resolution` are mutually exclusive. If the main display does not advertise any 16:9 mode, the command fails before PowerPoint launches; use a display or AVFoundation input that exposes a 16:9 mode. Do not add crop or pad filters to hide this failure.

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
