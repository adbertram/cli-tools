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
"""
import json
from compression import zstd
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG_BASENAME = "session.jsonl"
ZSTD_SUFFIX = ".zstd"


class SessionLogError(Exception):
    """Raised when a session log cannot be read as a dsh session log."""


@dataclass
class SessionLog:
    """A decoded session log: its header plus every event row."""

    path: Path
    header: Dict[str, Any]
    events: List[Dict[str, Any]] = field(default_factory=list)
    truncated: bool = False

    @property
    def session_id(self) -> str:
        return self.header["id"]

    @property
    def cwd(self) -> Optional[str]:
        return self.header.get("cwd")


def find_log_path(session_dir: Path) -> Optional[Path]:
    """Return the session log inside a session directory, or None.

    Prefers the Zstandard artifact; falls back to the plaintext artifact only
    because both are valid dsh encodings, never to mask a missing file.
    """
    compressed = session_dir / f"{LOG_BASENAME}{ZSTD_SUFFIX}"
    if compressed.is_file():
        return compressed
    plain = session_dir / LOG_BASENAME
    if plain.is_file():
        return plain
    return None


def _read_text(path: Path) -> tuple[str, bool]:
    """Return the log's decoded text and whether a partial tail was dropped.

    Decoding proceeds one frame at a time rather than through a whole-stream
    reader. A whole-stream read raises on the incomplete final frame *before*
    handing back the frames it already decoded, which would discard an entire
    truncated log. Per-frame decoding keeps every complete frame and drops only
    the unfinished one.
    """
    if path.suffix != ZSTD_SUFFIX:
        return path.read_text(encoding="utf-8", errors="replace"), False

    raw = path.read_bytes()
    parts: List[bytes] = []
    truncated = False
    remaining = raw

    while remaining:
        decompressor = zstd.ZstdDecompressor()
        try:
            parts.append(decompressor.decompress(remaining))
        except zstd.ZstdError:
            # The tail is not a decodable frame at all.
            truncated = True
            break
        if not decompressor.eof:
            # Input ended inside this frame: it was still being written.
            truncated = True
            break
        remaining = decompressor.unused_data

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
    if path.suffix == ZSTD_SUFFIX:
        try:
            decompressor = zstd.ZstdDecompressor()
            first_frame = decompressor.decompress(path.read_bytes())
            line = first_frame.decode("utf-8", errors="replace").splitlines()[0]
        except (OSError, zstd.ZstdError) as exc:
            raise SessionLogError(f"session log header cannot be decoded: {path}") from exc
        except IndexError as exc:
            raise SessionLogError(f"empty session log: {path}") from exc
    else:
        with path.open(encoding="utf-8", errors="replace") as stream:
            line = stream.readline()
    return _parse_header(line, path)


def load_log(path: Path) -> SessionLog:
    """Decode a session log into its header and event rows.

    Raises:
        SessionLogError: the file is empty, its first line is not a session
            header, or a line is not valid JSON.
    """
    text, truncated = _read_text(path)
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise SessionLogError(f"empty session log: {path}")

    header = _parse_header(lines[0], path)

    events: List[Dict[str, Any]] = []
    for number, line in enumerate(lines[1:], start=2):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SessionLogError(
                f"session log line {number} is not valid JSON: {path}"
            ) from exc
        if isinstance(record, dict):
            events.append(record)

    return SessionLog(path=path, header=header, events=events, truncated=truncated)
