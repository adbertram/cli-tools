"""Bounded local media rendering. Model strings never enter executable filters.

Captions come from measured Whisper segments, not the proposed post caption.
Quality receipts bind the rendered bytes, timed captions and sentence boundaries.
"""
from __future__ import annotations

import hashlib
import fcntl
import os
import signal
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .safety import SafetyError, canonical, digest, keys, number, strict_json, string, validate_proposal, write_allowance, PHYSICAL_DISK_RESERVE_BYTES


# Coordinates and typography are trusted constants, never model filter text.
STYLES = {
    "centered": ("(iw-ow)/2", 1.0, 20),
    "tight": ("(iw-ow)/2", 1.2, 22),
    "left": ("0", 1.0, 20),
    "right": ("iw-ow", 1.0, 20),
}
BOUNDARY_TOLERANCE = 0.25


def sha256(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def timed_segments(raw, duration, maximum=1048576):
    """Validate measured segments without repairing or inventing timestamps."""
    if isinstance(raw, (str, bytes)):
        raw = strict_json(raw, maximum)
    if not isinstance(raw, dict) or not isinstance(raw.get("segments"), list) or not raw["segments"]:
        raise SafetyError("timed_transcript_required")
    result = []
    previous_end = 0
    for segment in raw["segments"]:
        keys(segment, {"start", "end", "text"})
        start = number(segment["start"], previous_end, duration)
        end = number(segment["end"], start, duration)
        if end <= start:
            raise SafetyError("empty_caption_interval")
        text = string(segment["text"], 500).strip()
        if any(c in text for c in ("{", "}", "\\", "<", ">", "\n", "\r")):
            raise SafetyError("caption_markup_forbidden")
        result.append({"start": start, "end": end, "text": text})
        previous_end = end
    if len(canonical({"segments": result}).encode()) > maximum:
        raise SafetyError("payload_too_large")
    return result


def clip_segments(segments, proposal):
    """Require a complete sentence start and end, then shift measured captions."""
    start, end = proposal["start_seconds"], proposal["end_seconds"]
    selected = [s for s in segments if s["end"] > start and s["start"] < end]
    if not selected:
        raise SafetyError("no_caption_in_clip")
    first = segments.index(selected[0])
    if abs(selected[0]["start"] - start) > BOUNDARY_TOLERANCE or abs(selected[-1]["end"] - end) > BOUNDARY_TOLERANCE:
        raise SafetyError("clip_splits_spoken_segment")
    sentence_ends = lambda text: text.rstrip().rstrip('"\u201d\u2019\')]').endswith((".", "?", "!"))
    if first and not sentence_ends(segments[first - 1]["text"]):
        raise SafetyError("clip_starts_mid_sentence")
    if not sentence_ends(selected[-1]["text"]):
        raise SafetyError("clip_ends_mid_sentence")
    # Only trim sub-frame tolerance at source boundaries; never stretch a cue.
    return [{"start": max(0, s["start"] - start), "end": min(end - start, s["end"] - start), "text": s["text"]} for s in selected]


def srt_time(value):
    milliseconds = round(value * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


class MediaRenderer:
    """Trusted adapter component; each operation shares one hard deadline."""

    def __init__(self, config, *, ffmpeg="ffmpeg", ffprobe="ffprobe"):
        self.config = config
        self.workspace = Path(config["workspace"])
        if not self.workspace.is_absolute() or self.workspace.is_symlink():
            raise SafetyError("absolute_nonsymlink_workspace_required")
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.workspace = self.workspace.resolve()
        self.root = self.workspace / "media"
        self.root.mkdir(exist_ok=True)
        self._path(self.root, directory=True)
        self.ffmpeg, self.ffprobe = ffmpeg, ffprobe

    def _path(self, path, *, directory=False):
        path = Path(path)
        if not path.is_absolute() or path.is_symlink() or not path.resolve().is_relative_to(self.workspace):
            raise SafetyError("media_path_outside_workspace")
        if directory and not path.is_dir() or not directory and not path.is_file():
            raise SafetyError("media_path_missing")
        # Symlinks in any parent are disallowed even if their targets stay inside.
        current = path
        while current != self.workspace:
            if current.is_symlink():
                raise SafetyError("media_symlink_forbidden")
            current = current.parent
        return path.resolve()

    def _deadline(self):
        return time.monotonic() + self.config["limits"]["work_timeout_seconds"]

    @contextmanager
    def _lock(self, deadline):
        path = self.root / ".lock"
        if path.is_symlink():
            raise SafetyError("media_symlink_forbidden")
        with path.open("a") as stream:
            while True:
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("media_lock_timeout")
                    time.sleep(0.05)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def prune_cache(self):
        """Reclaim only source caches; durable clips and coordinator files stay owned by the caller."""
        with self._lock(self._deadline()):
            return self._prune_cache()

    def _prune_cache(self, exclude=None, reserve=0):
        caches = []
        for path in self.root.iterdir():
            if len(path.name) != 64 or any(c not in "0123456789abcdef" for c in path.name) or not path.is_dir() or path.is_symlink():
                continue
            if not (path / "source.json").is_file() or not (path / "source.mp4").is_file():
                continue
            self._path(path, directory=True)
            files = list(path.rglob("*"))
            if any(p.is_symlink() for p in files):
                raise SafetyError("media_symlink_forbidden")
            if {p.name for p in files} != {"source.json", "source.mp4"} or any(not p.is_file() for p in files):
                raise SafetyError("unexpected_source_cache_files")
            caches.append((path.stat().st_mtime, path, sum(p.stat().st_size for p in files if p.is_file())))
        ceiling = self.config["limits"]["max_disk_bytes"] // 2
        total = sum(row[2] for row in caches)
        freed = 0
        for _, path, size in sorted(caches):
            if total + reserve <= ceiling and shutil.disk_usage(self.workspace).free > PHYSICAL_DISK_RESERVE_BYTES:
                break
            if path == exclude:
                continue
            shutil.rmtree(path)
            total -= size
            freed += size
        if total + reserve > ceiling:
            raise SafetyError("source_cache_budget_exhausted")
        # Logical cache deletion can reclaim no physical blocks on APFS.
        if shutil.disk_usage(self.workspace).free <= PHYSICAL_DISK_RESERVE_BYTES:
            raise SafetyError("disk_budget_exhausted")
        return {"cache_bytes": total, "removed_bytes": freed, "cache_limit_bytes": ceiling}

    def _disk(self, unlinked_bytes=0):
        return write_allowance(self.workspace, self.config["limits"]["max_disk_bytes"], unlinked_bytes=unlinked_bytes)

    def _run(self, command, deadline, *, cwd=None, output_limit=None):
        """Kill the whole CLI process tree on timeout or resource exhaustion."""
        output_limit = output_limit or self.config["limits"]["max_payload_bytes"]
        if time.monotonic() >= deadline:
            raise TimeoutError("media_work_timeout")
        self._disk()
        with tempfile.TemporaryDirectory(prefix="process-", dir=self.root) as process_temp, tempfile.TemporaryFile(dir=process_temp) as out, tempfile.TemporaryFile(dir=process_temp) as err:
            environment = os.environ.copy()
            # Whisper temporary WAVs belong inside the measured workspace too.
            environment["TMPDIR"] = process_temp
            try:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                    cwd=cwd, env=environment, start_new_session=True)
            except FileNotFoundError as exc:
                raise SafetyError("media_executable_missing: " + command[0]) from exc
            try:
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("media_work_timeout")
                    self._disk(os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size)
                    if os.fstat(out.fileno()).st_size > output_limit or os.fstat(err.fileno()).st_size > 1048576:
                        raise SafetyError("media_process_output_limit")
                    time.sleep(min(0.1, max(0, deadline - time.monotonic())))
            except BaseException:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
                raise
            self._disk(os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size)
            if os.fstat(out.fileno()).st_size > output_limit or os.fstat(err.fileno()).st_size > 1048576:
                raise SafetyError("media_process_output_limit")
            out.seek(0)
            err.seek(0)
            stdout, stderr = out.read(output_limit + 1), err.read(1048576)
            if process.returncode:
                raise SafetyError("media_process_failed: " + Path(command[0]).name + ": " + stderr.decode(errors="replace")[-300:])
            return stdout

    def probe(self, path, deadline=None):
        path = self._path(path)
        raw = self._run([self.ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe", "-show_entries",
            "stream=codec_type,width,height:format=duration", "-of", "json", str(path)], deadline or self._deadline())
        data = strict_json(raw, self.config["limits"]["max_payload_bytes"])
        if not isinstance(data, dict) or not isinstance(data.get("streams"), list) or not isinstance(data.get("format"), dict):
            raise SafetyError("invalid_media_probe")
        videos = [s for s in data["streams"] if s.get("codec_type") == "video"]
        if len(videos) != 1:
            raise SafetyError("single_video_stream_required")
        try:
            duration = float(data["format"]["duration"])
        except (ValueError, KeyError, TypeError) as exc:
            raise SafetyError("invalid_media_duration") from exc
        width = number(videos[0].get("width"), 1, 8192, integer=True)
        height = number(videos[0].get("height"), 1, 8192, integer=True)
        if width * height > 3840 * 2160:
            raise SafetyError("media_pixel_budget_exhausted")
        return {"width": width, "height": height,
            "duration_seconds": number(duration, 0.001, 86400),
            "audio_present": any(s.get("codec_type") == "audio" for s in data["streams"])}

    def _source(self, record):
        source = next((s for s in self.config["sources"] if s["id"] == record["source_id"]), None)
        parsed = urlparse(string(record["media_url"]))
        if source is None or parsed.scheme != "https" or parsed.hostname not in source["allowed_hosts"] or parsed.username or parsed.password:
            raise SafetyError("media_host_not_allowlisted")
        # Supported contract is a single YouTube video, never playlists/channels.
        if parsed.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            identifiers = parse_qs(parsed.query).get("v", [])
            identifier = identifiers[0] if len(identifiers) == 1 and parsed.path == "/watch" else ""
        elif parsed.hostname == "youtu.be":
            identifier = parsed.path[1:]
        else:
            raise SafetyError("media_source_capability_missing")
        if len(identifier) != 11 or not all(c.isascii() and (c.isalnum() or c in "_-") for c in identifier):
            raise SafetyError("single_youtube_video_required")
        return "https://www.youtube.com/watch?v=" + identifier

    def prepare(self, record, *, deadline=None):
        """Download and transcribe once, returning measured model-input fields."""
        deadline = deadline or self._deadline()
        with self._lock(deadline):
            return self._prepare(record, deadline)

    def _prepare(self, record, deadline):
        url = self._source(record)
        target = self.root / digest({"url": url})
        self._prune_cache(exclude=target)
        if target.exists():
            self._path(target, directory=True)
            receipt = self._path(target / "source.json")
            data = strict_json(receipt.read_bytes(), self.config["limits"]["max_payload_bytes"])
            media = self._path(target / "source.mp4")
            if data["sha256"] != sha256(media):
                raise SafetyError("cached_source_digest_mismatch")
            self._prepared_segments(data)
            os.utime(target, None)
            return {key: data[key] for key in ("duration_seconds", "transcript", "transcript_segments", "provenance")}
        with tempfile.TemporaryDirectory(prefix="source-", dir=self.root) as temp:
            temp = Path(temp)
            self._run(["youtube", "videos", "download", url, "--output-dir", str(temp), "--format", "mp4",
                "--quality", "bestvideo[height<=1080]+bestaudio/best[height<=1080]"], deadline)
            candidates = [p for p in temp.rglob("*.mp4") if p.is_file() and not p.is_symlink()]
            if len(candidates) != 1:
                raise SafetyError("single_downloaded_media_required")
            media = self._path(candidates[0])
            measured = self.probe(media, deadline)
            if not measured["audio_present"]:
                raise SafetyError("source_audio_missing")
            raw = self._run(["whisper", "transcripts", "create", str(media), "--timeout",
                str(max(1, int(deadline - time.monotonic())))], deadline)
            segments = timed_segments(raw, measured["duration_seconds"], self.config["limits"]["max_payload_bytes"])
            media.rename(temp / "source.mp4")
            data = {"duration_seconds": measured["duration_seconds"], "transcript": " ".join(s["text"] for s in segments),
                "transcript_segments": [{"start_seconds": s["start"], "end_seconds": s["end"], "text": s["text"]} for s in segments],
                "sha256": sha256(temp / "source.mp4"), "provenance": "youtube CLI download; ffprobe; whisper CLI timed speech: " + url}
            encoded = canonical(data).encode()
            if len(encoded) > self.config["limits"]["max_payload_bytes"]:
                raise SafetyError("payload_too_large")
            (temp / "source.json").write_bytes(encoded)
            for path in temp.iterdir():
                if path.name not in {"source.mp4", "source.json"}:
                    if path.is_dir() and not path.is_symlink():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
            self._prune_cache(reserve=sum(p.stat().st_size for p in temp.rglob("*") if p.is_file()))
            self._disk()
            # Source cache install is atomic; temporary remnants clean on failure.
            temp.rename(target)
        return {key: data[key] for key in ("duration_seconds", "transcript", "transcript_segments", "provenance")}

    def _prepared_segments(self, data):
        raw = data.get("transcript_segments")
        if not isinstance(raw, list):
            raise SafetyError("timed_transcript_required")
        segments = []
        for segment in raw:
            keys(segment, {"start_seconds", "end_seconds", "text"})
            segments.append({"start": segment["start_seconds"], "end": segment["end_seconds"], "text": segment["text"]})
        return timed_segments({"segments": segments}, data["duration_seconds"], self.config["limits"]["max_payload_bytes"])

    def render(self, job, proposal):
        record = job["input"]
        deadline = self._deadline()
        with self._lock(deadline):
            prepared = self._prepare(record, deadline)
            validate_proposal("clip", proposal, {**record, **prepared}, self.config)
            source_path = self.root / digest({"url": self._source(record)}) / "source.mp4"
            segments = self._prepared_segments(prepared)
            return self.render_local(source_path, segments, proposal, prepared["provenance"], deadline=deadline)

    def render_local(self, source_path, segments, proposal, provenance, *, deadline=None):
        """Render an already approved workspace file; also used by local smoke tests."""
        deadline = deadline or self._deadline()
        source_path = self._path(source_path)
        measured = self.probe(source_path, deadline)
        validate_proposal("clip", proposal, {"duration_seconds": measured["duration_seconds"]}, self.config)
        if proposal["style"] not in STYLES:
            raise SafetyError("render_style_not_supported")
        if not measured["audio_present"]:
            raise SafetyError("source_audio_missing")
        captions = clip_segments(timed_segments({"segments": segments}, measured["duration_seconds"], self.config["limits"]["max_payload_bytes"]), proposal)
        string(provenance)
        filters = self._run([self.ffmpeg, "-hide_banner", "-filters"], deadline, output_limit=262144)
        if b" subtitles " not in filters:
            raise SafetyError("ffmpeg_subtitles_filter_required")
        x, zoom, font_size = STYLES[proposal["style"]]
        duration = proposal["end_seconds"] - proposal["start_seconds"]
        name = digest({"source": sha256(source_path), "proposal": proposal, "captions": captions})
        destination = self.root / (name + ".mp4")
        receipt_path = self.root / (name + ".json")
        with tempfile.TemporaryDirectory(prefix="render-", dir=self.root) as temp:
            temp = Path(temp)
            srt = "\n\n".join(f"{i}\n{srt_time(s['start'])} --> {srt_time(s['end'])}\n{s['text']}" for i, s in enumerate(captions, 1)) + "\n"
            (temp / "captions.srt").write_text(srt, encoding="utf-8")
            # Relative fixed subtitle filename avoids all filter path escaping.
            crop = f"crop=w='min(iw,ih*9/16)/{zoom}':h='min(ih,iw*16/9)/{zoom}':x='{x}':y='(ih-oh)/2'"
            video_filter = crop + ",scale=720:1280,setsar=1,subtitles=filename=captions.srt:force_style='FontName=Arial,FontSize=" + str(font_size) + ",Outline=2,MarginV=60'"
            self._run([self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-protocol_whitelist", "file,pipe", "-ss",
                str(proposal["start_seconds"]), "-i", str(source_path), "-t", str(duration), "-map", "0:v:0", "-map", "0:a:0",
                "-vf", video_filter, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                "-threads", "2", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-b:a", "128k", "-movflags", "+faststart",
                "-map_metadata", "-1", "-fs", str(self._disk()), str(temp / "clip.mp4")], deadline, cwd=temp)
            output = temp / "clip.mp4"
            report = self.probe(output, deadline)
            if not report["audio_present"] or not self.config["limits"]["min_clip_seconds"] <= report["duration_seconds"] <= self.config["limits"]["max_clip_seconds"] or abs(report["duration_seconds"] - duration) > 1:
                raise SafetyError("render_duration_or_audio_invalid")
            self._decode(output, deadline)
            asset = {"path": str(destination), "sha256": sha256(output), "bytes": output.stat().st_size,
                "provenance": "ffmpeg portrait crop; loudnorm; timed Whisper caption burn-in; " + provenance}
            receipt = {"asset": asset, "proposal": proposal, "captions": captions, "source_sha256": sha256(source_path), "measured": report}
            raw = canonical(receipt).encode()
            if len(raw) > self.config["limits"]["max_payload_bytes"]:
                raise SafetyError("payload_too_large")
            (temp / "receipt.json").write_bytes(raw)
            self._disk()
            output.replace(destination)
            (temp / "receipt.json").replace(receipt_path)
        return asset

    def _decode(self, path, deadline):
        self._run([self.ffmpeg, "-hide_banner", "-loglevel", "error", "-xerror", "-nostdin", "-protocol_whitelist", "file,pipe",
            "-i", str(path), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"], deadline)

    def quality(self, job, proposal, asset):
        keys(asset, {"path", "sha256", "bytes", "provenance"})
        deadline = self._deadline()
        path = self._path(asset["path"])
        if path.stat().st_size != asset["bytes"] or sha256(path) != asset["sha256"]:
            raise SafetyError("asset_digest_or_size_mismatch")
        receipt_path = self._path(path.with_suffix(".json"))
        receipt = strict_json(receipt_path.read_bytes(), self.config["limits"]["max_payload_bytes"])
        keys(receipt, {"asset", "proposal", "captions", "source_sha256", "measured"})
        if receipt["asset"] != asset or receipt["proposal"] != proposal:
            raise SafetyError("render_receipt_mismatch")
        duration = proposal["end_seconds"] - proposal["start_seconds"]
        captions = timed_segments({"segments": receipt["captions"]}, duration, self.config["limits"]["max_payload_bytes"])
        report = self.probe(path, deadline)
        self._decode(path, deadline)
        passed = (report["audio_present"] and 0.5 <= report["width"] / report["height"] <= 0.65
            and self.config["limits"]["min_clip_seconds"] <= report["duration_seconds"] <= self.config["limits"]["max_clip_seconds"]
            and abs(report["duration_seconds"] - duration) <= 1)
        return {"passed": bool(passed), **report, "captions_present": bool(captions), "coherent_boundaries": True,
            "provenance": "ffprobe and full decode; SHA-256-bound caption burn-in receipt; complete timed sentence boundaries"}
