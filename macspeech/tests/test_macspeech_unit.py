"""Unit tests for macspeech transform + plumbing logic.

These tests exercise the load-bearing pieces WITHOUT launching MacSpeech.app, so
they never touch Speech Recognition and never trigger the TCC dialog:
  * transcript -> text output mapping (uniform with the whisper CLIs)
  * contextual-strings parsing (semicolon-separated)
  * language -> locale mapping (en -> en-US, others pass through)
  * helper argument assembly for contextualStrings + addsPunctuation
  * fail-fast behavior when the helper reports an error / empty output
"""

import json
from pathlib import Path

import pytest

from cli_tools_shared.exceptions import ClientError

from macspeech_cli.client import (
    AUTHORIZATION_STATUS_LABELS,
    _SUBPROCESS_TIMEOUT_GRACE,
    MacspeechClient,
    build_transcript,
)
from macspeech_cli.config import DEFAULT_TIMEOUT, language_to_locale, parse_contextual_strings


def test_build_transcript_maps_transcript_to_text():
    raw = {
        "transcript": "permanent worktree handoff",
        "words": [
            {"text": "permanent", "start": 0.0, "end": 0.5, "confidence": 0.9},
            {"text": "worktree", "start": 0.5, "end": 1.0, "confidence": 0.8},
        ],
    }
    out = build_transcript(raw, "en")
    assert out["text"] == "permanent worktree handoff"
    assert out["language"] == "en"
    assert out["words"][1]["text"] == "worktree"
    # Uniform top-level keys with the whisper tools.
    assert set(out.keys()) == {"text", "language", "words"}


def test_build_transcript_defaults_missing_words_to_empty():
    out = build_transcript({"transcript": "hi"}, "en")
    assert out["words"] == []


def test_parse_contextual_strings_splits_and_trims():
    assert parse_contextual_strings("worktree; subagent ;detached HEAD") == [
        "worktree",
        "subagent",
        "detached HEAD",
    ]


def test_parse_contextual_strings_empty_inputs():
    assert parse_contextual_strings(None) == []
    assert parse_contextual_strings("") == []
    assert parse_contextual_strings("  ;  ; ") == []


def test_language_to_locale_en_maps_to_en_us():
    assert language_to_locale("en") == "en-US"


def test_language_to_locale_passthrough():
    assert language_to_locale("es") == "es"
    assert language_to_locale("fr-FR") == "fr-FR"


def test_authorization_status_labels_cover_known_values():
    assert AUTHORIZATION_STATUS_LABELS[0] == "notDetermined"
    assert AUTHORIZATION_STATUS_LABELS[3] == "authorized"


def test_transcribe_missing_file_fails_fast():
    client = MacspeechClient()
    with pytest.raises(ClientError, match="Audio file not found"):
        client.transcribe("/does/not/exist.wav")


def test_read_helper_output_raises_on_error_key(tmp_path):
    out = tmp_path / "result.json"
    out.write_text(json.dumps({"error": "boom"}), encoding="utf-8")
    client = MacspeechClient()
    with pytest.raises(ClientError, match="boom"):
        client._read_helper_output(out)


def test_read_helper_output_raises_on_missing_file(tmp_path):
    client = MacspeechClient()
    with pytest.raises(ClientError, match="no output file"):
        client._read_helper_output(tmp_path / "absent.json")


def test_read_helper_output_raises_on_empty_file(tmp_path):
    out = tmp_path / "empty.json"
    out.write_text("   ", encoding="utf-8")
    client = MacspeechClient()
    with pytest.raises(ClientError, match="empty output file"):
        client._read_helper_output(out)


def test_transcribe_assembles_helper_args_with_context_and_punctuation(tmp_path, monkeypatch):
    """transcribe() should pass locale, a contextual-strings file, and --punctuation
    to the helper, then map the helper JSON to the uniform shape — all without
    launching the real .app."""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"\x00\x00")

    client = MacspeechClient()
    # Pretend the .app is installed so _ensure_installed passes.
    monkeypatch.setattr(client.config, "is_app_installed", lambda: True)

    captured = {}

    def fake_run_app(args, timeout):
        captured["args"] = args
        captured["timeout"] = timeout
        # Read the contextual-strings file WHILE the temp dir still exists
        # (transcribe() tears it down on return).
        if "--contextual-strings-file" in args:
            ctx_file = Path(args[args.index("--contextual-strings-file") + 1])
            captured["ctx_lines"] = ctx_file.read_text(encoding="utf-8").splitlines()
        # The output path is the 3rd positional helper arg; write a valid result.
        out_path = Path(args[2])
        out_path.write_text(
            json.dumps({"transcript": "biased text", "words": []}), encoding="utf-8"
        )

    monkeypatch.setattr(client, "_run_app", fake_run_app)

    result = client.transcribe(
        str(audio),
        language="en",
        contextual_strings=["worktree", "subagent"],
        punctuation=False,
        timeout=42,
    )

    args = captured["args"]
    # Positional contract: <audio> <locale> <out.json>
    assert Path(args[0]) == audio.resolve()
    assert args[1] == "en-US"
    assert args[2].endswith(".json")
    # Contextual strings file is passed and contains the phrases, one per line.
    assert "--contextual-strings-file" in args
    assert captured["ctx_lines"] == ["worktree", "subagent"]
    # Punctuation off -> "0".
    assert "--punctuation" in args
    punc_idx = args.index("--punctuation")
    assert args[punc_idx + 1] == "0"
    # Caller's timeout is passed to the helper's watchdog verbatim...
    assert "--timeout" in args
    assert args[args.index("--timeout") + 1] == "42"
    # ...while the subprocess wrapper gets a grace margin over it.
    assert captured["timeout"] == 42 + _SUBPROCESS_TIMEOUT_GRACE
    # Output mapped to uniform shape.
    assert result == {"text": "biased text", "language": "en", "words": []}


def test_transcribe_omits_context_file_when_no_phrases(tmp_path, monkeypatch):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"\x00\x00")

    client = MacspeechClient()
    monkeypatch.setattr(client.config, "is_app_installed", lambda: True)

    captured = {}

    def fake_run_app(args, timeout):
        captured["args"] = args
        Path(args[2]).write_text(json.dumps({"transcript": "x", "words": []}), encoding="utf-8")

    monkeypatch.setattr(client, "_run_app", fake_run_app)
    client.transcribe(str(audio), language="en", contextual_strings=[], punctuation=True)

    args = captured["args"]
    assert "--contextual-strings-file" not in args
    # Punctuation on -> "1".
    punc_idx = args.index("--punctuation")
    assert args[punc_idx + 1] == "1"


def test_transcribe_default_timeout_uses_constant(tmp_path, monkeypatch):
    """The transcribe() default timeout flows from the single DEFAULT_TIMEOUT constant."""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"\x00\x00")

    client = MacspeechClient()
    monkeypatch.setattr(client.config, "is_app_installed", lambda: True)

    captured = {}

    def fake_run_app(args, timeout):
        captured["args"] = args
        Path(args[2]).write_text(json.dumps({"transcript": "x", "words": []}), encoding="utf-8")

    monkeypatch.setattr(client, "_run_app", fake_run_app)
    client.transcribe(str(audio), language="en", contextual_strings=[])

    args = captured["args"]
    assert args[args.index("--timeout") + 1] == str(DEFAULT_TIMEOUT)
