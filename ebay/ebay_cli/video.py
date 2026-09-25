"""Video preparation helpers for eBay Media API uploads.

eBay accepts listing videos as H.264 inside an MP4/MOV container. Anything else
(notably the HEVC/H.265 files current iPhones produce) is transcoded to a
temporary H.264 MP4 so the uploaded bytes match what eBay will accept. The
caller's source file is never modified.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Extensions treated as listing videos (never as listing images). This is the
# suffix filter for --video-folder; it is deliberately distinct from the ffprobe
# container names in _SUPPORTED_CONTAINERS below.
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v"}

# eBay Media API hard limit: 150 MB.
MAX_VIDEO_MB = 150
MAX_VIDEO_BYTES = MAX_VIDEO_MB * 1024 * 1024

# Codec and container eBay requires for a video that needs no transcoding.
TARGET_CODEC = "h264"
TARGET_ENCODER = "libx264"
_SUPPORTED_CONTAINERS = {"mov", "mp4"}

MAX_TITLE_LENGTH = 80

_REQUIRED_TOOLS = ("ffprobe", "ffmpeg")

_FFPROBE_ARGS = (
    "ffprobe",
    "-v",
    "error",
    "-select_streams",
    "v:0",
    "-show_entries",
    "stream=codec_name",
    "-show_entries",
    "format=format_name",
    "-of",
    "json",
)

_FFMPEG_ARGS = (
    "ffmpeg",
    "-hide_banner",
    "-loglevel",
    "error",
    "-y",
    "-i",
)

# Even-numbered dimensions are required by yuv420p; this is a no-op for
# already-even sources.
_EVEN_DIMENSIONS_FILTER = "scale=trunc(iw/2)*2:trunc(ih/2)*2"


class VideoError(RuntimeError):
    """Raised when a video cannot be prepared for upload."""


@dataclass
class PreparedVideo:
    """The exact file and byte count to hand to the Media API."""

    path: str
    size: int
    source_codec: str
    output_codec: str
    transcoded: bool
    temp_dir: Optional[str] = field(default=None)

    def cleanup(self) -> None:
        """Remove any temporary transcode output. Never touches the source file."""
        if self.temp_dir:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            self.temp_dir = None


def default_title_for(path: str) -> str:
    """Derive a text-only Media API title from a file name."""
    stem = Path(path).stem
    title = re.sub(r"[_\-\.]+", " ", stem)
    title = re.sub(r"[<>&]", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    return (title or "eBay listing video")[:MAX_TITLE_LENGTH]


def video_prep_message(prepared: PreparedVideo) -> str:
    """Describe what will be uploaded, for stderr logging."""
    if prepared.transcoded:
        return (
            f"Transcoded video {prepared.source_codec} -> {prepared.output_codec} "
            f"MP4 ({prepared.size} bytes)"
        )
    return (
        f"Video is already {prepared.source_codec} in a supported container "
        f"({prepared.size} bytes)"
    )


def upload_prepared_video(
    client: Any,
    prepared: PreparedVideo,
    *,
    title: str,
    description: Optional[str] = None,
) -> str:
    """Create a Media API video resource and upload exactly the prepared bytes.

    ``create_video`` is told ``prepared.size`` and ``upload_video`` sends that
    same file, so the declared and uploaded byte counts can never disagree.
    """
    video_id = client.create_video(
        title=title,
        size=prepared.size,
        description=description,
    )
    client.upload_video(video_id, prepared.path)
    return video_id


def _require_tools() -> None:
    missing = [name for name in _REQUIRED_TOOLS if shutil.which(name) is None]
    if missing:
        raise VideoError(
            f"Missing required tool(s): {', '.join(missing)}. "
            "Install ffmpeg (which provides ffmpeg and ffprobe) before uploading videos."
        )


def probe_video(path: str) -> tuple[str, str]:
    """Return (video_codec_name, container_format_name) for a local file."""
    result = subprocess.run(
        [*_FFPROBE_ARGS, path],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise VideoError(f"ffprobe could not read '{path}': {detail}")

    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise VideoError(f"ffprobe returned unreadable output for '{path}': {exc}")

    streams = data.get("streams") or []
    if not streams:
        raise VideoError(f"No video stream found in '{path}'")

    codec = (streams[0].get("codec_name") or "").lower()
    format_name = ((data.get("format") or {}).get("format_name") or "").lower()
    return codec, format_name


def _is_upload_compatible(codec: str, format_name: str) -> bool:
    containers = {part.strip() for part in format_name.split(",")}
    return codec == TARGET_CODEC and bool(containers & _SUPPORTED_CONTAINERS)


def prepare_video_for_upload(path: str) -> PreparedVideo:
    """Return the file to upload, transcoding to H.264 MP4 when required.

    Raises:
        VideoError: when the file is missing, ffmpeg/ffprobe are unavailable,
            the source is unreadable, transcoding fails, or the result exceeds
            eBay's 150 MB limit.
    """
    source = Path(path)
    if not source.is_file():
        raise VideoError(f"Video file not found: {path}")

    _require_tools()

    source_codec, format_name = probe_video(str(source))

    if _is_upload_compatible(source_codec, format_name):
        prepared = PreparedVideo(
            path=str(source),
            size=source.stat().st_size,
            source_codec=source_codec,
            output_codec=source_codec,
            transcoded=False,
        )
    else:
        prepared = _transcode_to_h264_mp4(source, source_codec)

    if prepared.size > MAX_VIDEO_BYTES:
        prepared.cleanup()
        raise VideoError(
            f"Video is {prepared.size} bytes, over eBay's {MAX_VIDEO_BYTES}-byte "
            f"({MAX_VIDEO_MB} MB) limit: {path}"
        )

    return prepared


def _transcode_to_h264_mp4(source: Path, source_codec: str) -> PreparedVideo:
    temp_dir = tempfile.mkdtemp(prefix="ebay_video_")
    output = Path(temp_dir) / f"{source.stem}.mp4"

    command = [
        *_FFMPEG_ARGS,
        str(source),
        "-vf",
        _EVEN_DIMENSIONS_FILTER,
        "-c:v",
        TARGET_ENCODER,
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output),
    ]

    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise VideoError(f"Transcoding timed out for '{source}'")

    if result.returncode != 0 or not output.is_file():
        detail = (result.stderr or result.stdout).strip()
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise VideoError(f"Transcoding failed for '{source}': {detail}")

    output_codec, _ = probe_video(str(output))
    if output_codec != TARGET_CODEC:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise VideoError(
            f"Transcoding produced '{output_codec}' instead of {TARGET_CODEC} for '{source}'"
        )

    return PreparedVideo(
        path=str(output),
        size=output.stat().st_size,
        source_codec=source_codec,
        output_codec=output_codec,
        transcoded=True,
        temp_dir=temp_dir,
    )
