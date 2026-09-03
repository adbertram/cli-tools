"""Tests for the physical session-log reader."""
import json
from compression import zstd
from pathlib import Path

import pytest

from deepseek_sessions_cli.logfile import (
    SessionLogError,
    find_log_path,
    load_log,
    load_log_header,
    read_log_text,
)

from conftest import PROJECT_CWD, PROJECT_KEY, header, write_log


def test_reads_concatenated_zstd_frames(simple_log: Path):
    """Each dsh write appends its own frame; all frames must decode."""
    log = load_log(simple_log)
    assert log.session_id == "session-11111111-1111-4111-8111-111111111111"
    assert log.cwd == PROJECT_CWD
    assert log.truncated is False
    # 15 event rows follow the header.
    assert len(log.events) == 15


def test_load_log_header_does_not_decode_later_frames(simple_log: Path):
    """Metadata discovery must not pay the cost of decoding the transcript."""
    raw = simple_log.read_bytes()
    decompressor = zstd.ZstdDecompressor()
    decompressor.decompress(raw)
    first_frame_end = len(raw) - len(decompressor.unused_data)
    simple_log.write_bytes(raw[:first_frame_end] + b"not-zstd")

    header_row = load_log_header(simple_log)

    assert header_row["id"] == "session-11111111-1111-4111-8111-111111111111"
    assert header_row["cwd"] == PROJECT_CWD


def test_reads_plaintext_encoding(sessions_root: Path):
    """dsh also writes an uncompressed `session.jsonl`; both must be read."""
    session_id = "session-99999999-9999-4999-8999-999999999999"
    records = [
        header(session_id, PROJECT_CWD),
        {"type": "turn/start", "seq": 1, "time": 1, "data": {"turn": 1}},
    ]
    path = write_log(
        sessions_root / PROJECT_KEY / session_id, records, compressed=False
    )
    assert path.name == "session.jsonl"

    log = load_log(path)
    assert log.session_id == session_id
    assert len(log.events) == 1
    assert load_log_header(path)["id"] == session_id


def test_find_log_path_prefers_compressed(sessions_root: Path):
    session_dir = sessions_root / PROJECT_KEY / "session-abc"
    session_dir.mkdir(parents=True)
    (session_dir / "session.jsonl").write_text("{}")
    assert find_log_path(session_dir).name == "session.jsonl"

    (session_dir / "session.jsonl.zstd").write_bytes(b"")
    assert find_log_path(session_dir).name == "session.jsonl.zstd"


def test_find_log_path_returns_none_when_absent(sessions_root: Path):
    session_dir = sessions_root / PROJECT_KEY / "empty"
    session_dir.mkdir(parents=True)
    assert find_log_path(session_dir) is None


def test_truncated_tail_is_repaired_and_reported(simple_log: Path):
    """A partial trailing frame is dropped and flagged, never silently kept."""
    raw = simple_log.read_bytes()
    simple_log.write_bytes(raw[:-40])

    log = load_log(simple_log)
    assert log.truncated is True
    # The header plus every whole frame before the clipped one survived.
    assert log.session_id == "session-11111111-1111-4111-8111-111111111111"
    assert 0 < len(log.events) < 15


def test_empty_log_raises(sessions_root: Path):
    session_dir = sessions_root / PROJECT_KEY / "session-empty"
    session_dir.mkdir(parents=True)
    (session_dir / "session.jsonl").write_text("")

    with pytest.raises(SessionLogError, match="empty session log"):
        load_log(session_dir / "session.jsonl")


def test_missing_header_raises(sessions_root: Path):
    session_dir = sessions_root / PROJECT_KEY / "session-bad"
    session_dir.mkdir(parents=True)
    (session_dir / "session.jsonl").write_text(
        json.dumps({"type": "turn/start", "data": {}}) + "\n"
    )

    with pytest.raises(SessionLogError, match="not a session header"):
        load_log(session_dir / "session.jsonl")


def test_invalid_json_line_is_skipped_not_raised(sessions_root: Path):
    """One corrupt line must not hide every other event in the same file.

    dsh can flush a structurally valid Zstandard frame that carries an
    incomplete JSON payload (e.g. a tool result cut short mid-write). That one
    line is unreadable, but every other line in the file is still good data
    and must survive the read.
    """
    session_dir = sessions_root / PROJECT_KEY / "session-torn"
    session_dir.mkdir(parents=True)
    (session_dir / "session.jsonl").write_text(
        json.dumps(header("session-torn", PROJECT_CWD))
        + "\nnot json\n"
        + json.dumps({"type": "turn/start", "seq": 1, "time": 1, "data": {"turn": 1}})
        + "\n"
    )

    log = load_log(session_dir / "session.jsonl")

    assert log.session_id == "session-torn"
    assert log.skipped_lines == [2]
    # The good line after the corrupt one still decodes.
    assert len(log.events) == 1
    assert log.events[0]["type"] == "turn/start"


def test_read_log_text_returns_raw_jsonl(simple_log: Path):
    text = read_log_text(simple_log)
    assert '"type":"session"' in text.replace(" ", "")
    assert "do the thing" in text
