"""Physical reader for DeepSeek Harness session logs.

dsh writes one append-only JSONL log per session at
`<sessions root>/<projectKey(cwd)>/<sessionId>/session.jsonl[.zstd]`.

Two physical encodings exist and both must be read:

- `session.jsonl.zstd` — a container of independently decodable Zstandard
  frames, appended one batch at a time. `compression.zstd` (stdlib, Python
  3.14+) decodes a concatenated-frame stream, so no third-party package is
  needed.
- `session.jsonl` — the same JSONL in plaintext, written when the harness is
  configured for the uncompressed encoding.

The first line of either encoding is the session header (`type: "session"`).

Truncation is a real state, not corruption: dsh appends whole frames, so a
process killed mid-append leaves a trailing partial frame. dsh itself performs
truncation repair on read. This reader does the same and reports it — the
returned `truncated` flag is surfaced on `SessionSummary.truncated` so a caller
never mistakes a clipped log for a complete one.

A single event line can also be corrupt in the middle of an otherwise intact
file: dsh writes one Zstandard frame per append batch, and a batch can be
flushed with an incomplete JSON payload (e.g. a tool result whose content was
still being assembled when the writer was interrupted) while the frame itself
remains a structurally valid, fully-decodable Zstandard frame. That is
invisible to the trailing-frame truncation check above, since it can occur
anywhere in the file, not just at the tail. Such a line is skipped rather than
aborting the whole file — one bad row must never hide every other session
event, or every other session, from a caller. Skipped line numbers are
reported on `SessionLog.skipped_lines` so callers can warn about them.
"""
import json
from compression import zstd
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG_BASENAMES = (
    "session.v3.jsonl",
    "session.jsonl",
)
ZSTD_SUFFIX = ".zstd"
READ_CHUNK_BYTES = 1024 * 1024


class SessionLogError(Exception):
    """Raised when a session log cannot be read as a dsh session log."""


@dataclass
class SessionLog:
    """A decoded session log: its header plus every event row."""

    path: Path
    header: Dict[str, Any]
    events: List[Dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    skipped_lines: List[int] = field(default_factory=list)

    @property
    def session_id(self) -> str:
        return self.header["id"]

    @property
    def cwd(self) -> Optional[str]:
        return self.header.get("cwd")


def find_log_path(session_dir: Path) -> Optional[Path]:
    """Return the session log inside a session directory, or None.

    Prefers the current v3 Zstandard artifact, then the legacy Zstandard
    artifact, then the corresponding plaintext encodings. Both layouts are
    valid dsh encodings; the fallback never masks a missing file.
    """
    for basename in LOG_BASENAMES:
        compressed = session_dir / f"{basename}{ZSTD_SUFFIX}"
        if compressed.is_file():
            return compressed
    for basename in LOG_BASENAMES:
        plain = session_dir / basename
        if plain.is_file():
            return plain
    return None


def _open_log_stream(path: Path):
    """Open a compressed or plaintext log as a binary stream."""
    if path.suffix == ZSTD_SUFFIX:
        return zstd.open(path, "rb")
    return path.open("rb")


def _read_text(path: Path) -> tuple[str, bool]:
    """Return the log's decoded text and whether a partial tail was dropped.

    `read1()` returns decoded bytes already available before a damaged tail
    raises. That keeps every complete frame and drops only the unfinished one,
    unlike a single `read()` that can raise before returning earlier bytes.
    """
    if path.suffix != ZSTD_SUFFIX:
        return path.read_text(encoding="utf-8", errors="replace"), False

    parts: List[bytes] = []
    truncated = False
    try:
        with _open_log_stream(path) as stream:
            read = getattr(stream, "read1", stream.read)
            while chunk := read(READ_CHUNK_BYTES):
                parts.append(chunk)
    except (EOFError, zstd.ZstdError):
        # A final frame was still being written. Keep every complete line from
        # the frames that decoded successfully.
        truncated = True

    text = b"".join(parts).decode("utf-8", errors="replace")
    if truncated:
        # The dropped frame almost certainly cut a line in half; keep only whole
        # JSONL records.
        cut = text.rfind("\n")
        text = text[: cut + 1] if cut >= 0 else ""
    return text, truncated


def read_log_text(path: Path) -> str:
    """Return the raw decoded JSONL text of a log, for keyword pre-filtering."""
    text, _ = _read_text(path)
    return text


def _parse_header(line: str, path: Path) -> Dict[str, Any]:
    """Parse and validate one session-header line."""
    if not line.strip():
        raise SessionLogError(f"empty session log: {path}")

    try:
        header = json.loads(line)
    except json.JSONDecodeError as exc:
        raise SessionLogError(f"session log header is not valid JSON: {path}") from exc

    if not isinstance(header, dict) or header.get("type") != "session":
        raise SessionLogError(f"first line is not a session header: {path}")
    if not isinstance(header.get("id"), str):
        raise SessionLogError(f"session header has no id: {path}")
    return header


def load_log_header(path: Path) -> Dict[str, Any]:
    """Read only the validated first record of a session log.

    Project discovery needs the session identity, cwd, and origin but not the
    transcript. Reading one line avoids decoding and parsing every event in
    every log just to render the project list.
    """
    try:
        with _open_log_stream(path) as stream:
            raw_line = stream.readline()
    except (OSError, EOFError, zstd.ZstdError) as exc:
        raise SessionLogError(f"session log header cannot be decoded: {path}") from exc

    if not raw_line:
        raise SessionLogError(f"empty session log: {path}")
    line = raw_line.decode("utf-8", errors="replace")
    return _parse_header(line, path)


def load_log_title(path: Path) -> Optional[str]:
    """Read only the final session-title event from a log.

    Discovery can resolve a title without materializing every message, tool
    result, and usage record. A truncated tail is ignored because the latest
    complete title event is still authoritative.
    """
    title: Optional[str] = None
    try:
        with _open_log_stream(path) as stream:
            header_line = stream.readline()
            if not header_line:
                raise SessionLogError(f"empty session log: {path}")
            _parse_header(header_line.decode("utf-8", errors="replace"), path)

            for raw_line in stream:
                try:
                    record = json.loads(raw_line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                if record.get("type") != "session/title":
                    continue
                data = record.get("data") or {}
                if isinstance(data, dict):
                    title = data.get("title")
    except (EOFError, zstd.ZstdError):
        pass
    return title


def load_log(path: Path) -> SessionLog:
    """Decode a session log into its header and event rows.

    A line that is not valid JSON is skipped rather than aborting the whole
    file: its number is recorded on the returned `SessionLog.skipped_lines` so
    the caller can warn about it, and every other event still decodes.

    Raises:
        SessionLogError: the file is empty, or its first line is not a valid
            session header. The header must decode; there is no per-file
            identity to recover it from otherwise.
    """
    text, truncated = _read_text(path)
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise SessionLogError(f"empty session log: {path}")

    header = _parse_header(lines[0], path)

    events: List[Dict[str, Any]] = []
    skipped_lines: List[int] = []
    for number, line in enumerate(lines[1:], start=2):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            skipped_lines.append(number)
            continue
        if isinstance(record, dict):
            events.append(record)

    return SessionLog(
        path=path,
        header=header,
        events=events,
        truncated=truncated,
        skipped_lines=skipped_lines,
    )
