# powerpoint-slide-recorder

## DESCRIPTION

The `powerpoint-slide-recorder` CLI lets you record narrated PowerPoint slides.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Requirements

- macOS
- Microsoft PowerPoint
- `ffmpeg` and `ffprobe`
- `osascript`, `afplay`, and `open`

List AVFoundation devices:

```bash
ffmpeg -f avfoundation -list_devices true -i ""
```

## Command

```bash
powerpoint-slide-recorder record \
  --deck /path/to/slides.pptx \
  --items /path/to/items.json \
  --output /path/to/output.mp4 \
  --work-dir /path/to/work \
  --video-input AVFOUNDATION_DEVICE \
  --force-aspect-ratio 16x9
```

Required options:

- `--deck PATH`
- `--items PATH`
- `--output PATH`
- `--work-dir PATH`
- `--video-input AVFOUNDATION_DEVICE`

Optional options:

- `--cue-marker MARKER`, default `||`
- `--framerate 30`
- `--resolution WIDTHxHEIGHT`, default `1920x1080`; width and height must be positive even integers
- `--force-resolution`; temporarily switches the main display to `--resolution` before recording and restores the previous display mode afterward
- `--force-aspect-ratio WIDTHxHEIGHT`; temporarily switches the main display to the highest available mode with that aspect ratio before recording and restores the previous display mode afterward; mutually exclusive with `--force-resolution`
- `--recording-lead-seconds 1.0`
- `--slide-pause-seconds 0.75`
- `--slideshow-start-seconds 2.0`
- `--table`

## Resolution Guard

The recorder probes the selected AVFoundation `--video-input` before launching PowerPoint. The capture source must have the same aspect ratio as the final MP4 resolution and must be at least as large as the requested output size. Matching larger sources are scaled down during the final mux. Mismatched or smaller sources fail before recording so the final MP4 is not letterboxed, cropped, or upscaled.

The default `--resolution` is `1920x1080`. A high-resolution non-16:9 source such as `4112x2658` is still rejected because scaling it directly to 1920x1080 would keep or distort the bars from the full-screen PowerPoint capture. The source has to be 16:9, such as `1920x1080`, `2560x1440`, or `3840x2160`.

If the current capture source is smaller than the requested output, add `--force-resolution` to have the recorder temporarily switch the main display to `--resolution`, re-probe the AVFoundation source, perform the recording, and restore the original display mode during cleanup. This uses an embedded macOS CoreGraphics helper through `/usr/bin/python3`; there is no external display resolution tool to install.

For standard 1080p course output, use `--force-aspect-ratio 16x9` without also passing `--resolution 1920x1080`. The recorder chooses the highest-usable-area main-display mode for 16:9 — an exact 16:9 mode when one exists (captured uncropped), otherwise the best near-ratio mode whose centered 16:9 crop still covers 1920x1080 — captures at that source size, and scales the final MP4 to the default output resolution, 1920x1080.

A 16:10-only display, such as the built-in MacBook Pro Liquid Retina XDR panel, advertises no true 16:9 mode but still works: PowerPoint presents the 16:9 slide centered and letterboxed inside the 16:10 screen, so the recorder switches to the best 16:10 mode, crops the centered 16:9 slide region from the captured frame, and scales it to 1920x1080 — no external 16:9 monitor required. The command fails before PowerPoint launches only when no available mode's centered 16:9 crop reaches 1920x1080 (every mode is too small); use a higher-resolution display or AVFoundation input. Do not add crop or pad filters to hide a real too-small-source failure.

## Item Manifest

Every item requires `slide`, `transcript_path`, and `audio_path`. Slide numbers must be positive integers and items must be consecutive.

Each transcript is required. Each cue marker sends Space at the estimated cue boundary. The recorder reads each slide's click-triggered animation count from the deck and fails before recording when the transcript cue marker count does not match the slide animation count.

```json
{
  "items": [
    {
      "slide": 1,
      "transcript_path": "/path/to/transcripts/001.txt",
      "audio_path": "/path/to/audio/001.mp3"
    },
    {
      "slide": 2,
      "transcript_path": "/path/to/transcripts/002.txt",
      "audio_path": "/path/to/audio/002.mp3"
    }
  ]
}
```

## Output

Successful commands emit JSON on stdout:

```json
{
  "output_path": "/path/to/output.mp4",
  "timing_plan_path": "/path/to/work/timing-plan.json",
  "duration_seconds": 42.1,
  "timing_plan": {
    "deck_path": "/path/to/slides.pptx",
    "cue_marker": "||",
    "narration_audio": "/path/to/work/narration.wav",
    "duration_seconds": 42.1,
    "actions": [],
    "items": []
  }
}
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```
