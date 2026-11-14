"""Client facade for recording PowerPoint slides."""
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Optional, Tuple

from . import recorder
from .models import RecordingResult


class ClientError(Exception):
    """Raised when powerpoint-slide-recorder cannot complete a request."""


def require_executables(executables):
    """Raise ClientError for the first executable missing from PATH."""
    for executable in executables:
        if shutil.which(executable) is None:
            raise ClientError(f"Required executable not found in PATH: {executable}")


class PowerPointSlideRecorderClient:
    """Runs the deterministic local PowerPoint slide recorder."""

    def __init__(self):
        """Validate required command-line dependencies."""
        require_executables(["ffmpeg", "ffprobe", "osascript", "afplay", "open"])

    def record(
        self,
        deck: Path,
        items: Path,
        output: Path,
        work_dir: Path,
        video_input: str,
        cue_marker: str,
        framerate: int,
        recording_lead_seconds: float,
        slide_pause_seconds: float,
        slideshow_start_seconds: float,
        output_width: int,
        output_height: int,
        force_resolution: bool,
        force_aspect_ratio: Optional[Tuple[int, int]],
        ronin_home: Optional[Path],
    ) -> RecordingResult:
        """Record a narrated slide recording."""
        args = SimpleNamespace(
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
            force_aspect_ratio=force_aspect_ratio,
            ronin_home=ronin_home,
        )
        config = recorder.build_config(args)
        result = recorder.record(config)
        timing_plan = result["timing_plan"]
        return RecordingResult(
            output_path=result["output_path"],
            timing_plan_path=result["timing_plan_path"],
            duration_seconds=timing_plan["duration_seconds"],
            timing_plan=timing_plan,
        )


def plan_slides(
    deck: Path,
    items: Path,
    work_dir: Path,
    click_steps: str,
    cue_marker: str,
    recording_lead_seconds: float,
    slide_pause_seconds: float,
) -> dict:
    """Build the narration track and press schedule ``record`` would use, without PowerPoint or a screen.

    Needs only ffmpeg and ffprobe, so it deliberately does not construct the recording client.
    """
    require_executables(["ffmpeg", "ffprobe"])
    if recording_lead_seconds < 0:
        raise ValueError("--recording-lead-seconds cannot be negative")
    if slide_pause_seconds < 0:
        raise ValueError("--slide-pause-seconds cannot be negative")
    args = SimpleNamespace(
        deck=deck,
        items=items,
        work_dir=work_dir,
        cue_marker=cue_marker,
        recording_lead_seconds=recording_lead_seconds,
        slide_pause_seconds=slide_pause_seconds,
    )
    config = recorder.build_plan_config(args)
    plan = recorder.plan_slides(
        config,
        recorder.parse_click_steps(click_steps, recorder.prepared_slide_numbers(config["items"])),
    )
    return {**plan, "timing_plan_path": str(Path(config["work_dir"]) / "timing-plan.json")}


_client: Optional[PowerPointSlideRecorderClient] = None


def get_client() -> PowerPointSlideRecorderClient:
    """Get or create the global PowerPointSlideRecorder client instance."""
    global _client
    if _client is None:
        _client = PowerPointSlideRecorderClient()
    return _client
