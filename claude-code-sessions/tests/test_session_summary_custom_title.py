import json

from claude_code_sessions_cli.parsers import parse_session_summary


def _write_lines(path, entries):
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )


def test_summary_captures_custom_title(tmp_path):
    session_path = tmp_path / "session-123.jsonl"
    _write_lines(
        session_path,
        [
            {
                "type": "custom-title",
                "customTitle": "Course: OpenAI Codex Advanced Features Module 2",
                "sessionId": "session-123",
            },
            {
                "type": "user",
                "uuid": "user-1",
                "timestamp": "2026-06-25T12:00:00.000Z",
                "message": {"content": "Build the module"},
            },
            {
                "type": "assistant",
                "uuid": "assistant-1",
                "timestamp": "2026-06-25T12:00:01.000Z",
                "message": {
                    "content": [{"type": "text", "text": "Done"}],
                    "usage": {"input_tokens": 10, "output_tokens": 2},
                },
            },
        ],
    )

    summary = parse_session_summary(session_path, "TestProject")

    assert summary is not None
    assert summary.custom_title == "Course: OpenAI Codex Advanced Features Module 2"


def test_summary_uses_last_custom_title_when_retitled(tmp_path):
    session_path = tmp_path / "session-123.jsonl"
    _write_lines(
        session_path,
        [
            {
                "type": "custom-title",
                "customTitle": "Original Title",
                "sessionId": "session-123",
            },
            {
                "type": "user",
                "uuid": "user-1",
                "timestamp": "2026-06-25T12:00:00.000Z",
                "message": {"content": "Rename me"},
            },
            {
                "type": "assistant",
                "uuid": "assistant-1",
                "timestamp": "2026-06-25T12:00:01.000Z",
                "message": {
                    "content": [{"type": "text", "text": "ok"}],
                    "usage": {"input_tokens": 5, "output_tokens": 1},
                },
            },
            {
                "type": "custom-title",
                "customTitle": "Final Title",
                "sessionId": "session-123",
            },
        ],
    )

    summary = parse_session_summary(session_path, "TestProject")

    assert summary is not None
    assert summary.custom_title == "Final Title"


def test_summary_custom_title_is_none_when_absent(tmp_path):
    session_path = tmp_path / "session-123.jsonl"
    _write_lines(
        session_path,
        [
            {
                "type": "user",
                "uuid": "user-1",
                "timestamp": "2026-06-25T12:00:00.000Z",
                "message": {"content": "No title here"},
            },
            {
                "type": "assistant",
                "uuid": "assistant-1",
                "timestamp": "2026-06-25T12:00:01.000Z",
                "message": {
                    "content": [{"type": "text", "text": "ok"}],
                    "usage": {"input_tokens": 5, "output_tokens": 1},
                },
            },
        ],
    )

    summary = parse_session_summary(session_path, "TestProject")

    assert summary is not None
    assert summary.custom_title is None
    # Field still serializes (CLIModel shows None values) under the json key.
    assert summary.model_dump()["custom_title"] is None
