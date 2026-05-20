"""Recording command."""
from pathlib import Path
from typing import Optional

import typer

from cli_tools_shared.output import handle_error, print_json, print_table

from .client import get_client
from .recorder import (
    DEFAULT_CUE_MARKER,
    DEFAULT_FRAMERATE,
    DEFAULT_RESOLUTION,
    DEFAULT_RECORDING_LEAD_SECONDS,
    DEFAULT_SLIDE_PAUSE_SECONDS,
    DEFAULT_SLIDESHOW_START_SECONDS,
    parse_aspect_ratio,
    parse_resolution,
)


def record(
    deck: Path = typer.Option(..., "--deck", help="PowerPoint slide deck path"),
    items: Path = typer.Option(..., "--items", help="JSON item manifest path"),
    output: Path = typer.Option(..., "--output", help="MP4 output file path"),
    work_dir: Path = typer.Option(..., "--work-dir", help="Working directory for generated timing and audio files"),
    video_input: str = typer.Option(..., "--video-input", help="ffmpeg AVFoundation video input"),
    resolution: str = typer.Option(DEFAULT_RESOLUTION, "--resolution", help="Final MP4 resolution as WIDTHxHEIGHT with even dimensions"),
    force_resolution: bool = typer.Option(False, "--force-resolution", help="Temporarily switch the main display to --resolution before recording, then restore it"),
    force_aspect_ratio: Optional[str] = typer.Option(None, "--force-aspect-ratio", help="Temporarily switch the main display to the highest available mode with this aspect ratio, then restore it"),
    cue_marker: str = typer.Option(DEFAULT_CUE_MARKER, "--cue-marker", help="Transcript marker that triggers a Space keypress"),
    framerate: int = typer.Option(DEFAULT_FRAMERATE, "--framerate", help="Screen recording framerate"),
    recording_lead_seconds: float = typer.Option(DEFAULT_RECORDING_LEAD_SECONDS, "--recording-lead-seconds", help="Silence before narration starts"),
    slide_pause_seconds: float = typer.Option(DEFAULT_SLIDE_PAUSE_SECONDS, "--slide-pause-seconds", help="Pause inserted between slide items"),
    slideshow_start_seconds: float = typer.Option(DEFAULT_SLIDESHOW_START_SECONDS, "--slideshow-start-seconds", help="Delay after slideshow starts before recording begins"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result summary as a table"),
):
    """Record narrated PowerPoint slides."""
    try:
        if force_resolution and force_aspect_ratio is not None:
            raise ValueError("--force-resolution and --force-aspect-ratio are mutually exclusive")
        output_width, output_height = parse_resolution(resolution)
        parsed_force_aspect_ratio = None
        if force_aspect_ratio is not None:
            parsed_force_aspect_ratio = parse_aspect_ratio(force_aspect_ratio)
        result = get_client().record(
            deck=deck,
            items=items,
            output=output,
            work_dir=work_dir,
            video_input=video_input,
            cue_marker=cue_marker,
            framerate=framerate,
            recording_lead_seconds=recording_lead_seconds,
            slide_pause_seconds=slide_pause_seconds,
            slideshow_start_seconds=slideshow_start_seconds,
            output_width=output_width,
            output_height=output_height,
            force_resolution=force_resolution,
            force_aspect_ratio=parsed_force_aspect_ratio,
        )
        if table:
            print_table(
                [result],
                ["output_path", "timing_plan_path", "duration_seconds"],
                ["Output", "Timing Plan", "Duration"],
            )
            return
        print_json(result)
    except Exception as error:
        raise typer.Exit(handle_error(error))
