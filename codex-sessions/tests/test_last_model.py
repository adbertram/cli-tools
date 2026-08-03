"""Regression tests for the last-model-used field on Codex sessions,
conversations, and search results.

Codex rollout transcripts record the active model on `payload.model` of each
`turn_context` record (one per turn). A session or conversation can span
multiple models (mid-session model switches via /model or a subagent handoff),
so the correct "last model used" for a session is the model from the LAST
turn_context record in file order, not the first and not blank/None when a
later turn_context does carry a model.

Unlike Claude Code's JSONL format, Codex has no sidechain interleaving within
a single rollout file (subagent turns are written to their own rollout file
under a different session_id, linked via session_meta.source.subagent) and,
per investigation of real ~/.codex session data, no sentinel/placeholder
model value analogous to Claude Code's "<synthetic>" rate-limit marker -- every
turn_context.model value observed across live transcripts was a real model
identifier.
"""
import json
import tempfile
import unittest
from pathlib import Path

from codex_sessions_cli.client import CodexSessionsClient
from codex_sessions_cli.parsers import RolloutRecord, extract_turn_model, last_turn_model


def _turn_context(line_number, timestamp, model):
    payload = {"turn_id": f"turn-{line_number}", "cwd": "/tmp", "model": model}
    return RolloutRecord(
        path=Path("/tmp/fake.jsonl"),
        line_number=line_number,
        timestamp=timestamp,
        record_type="turn_context",
        payload=payload,
        raw={"timestamp": timestamp, "type": "turn_context", "payload": payload},
    )


def _other_record(line_number, timestamp, record_type="response_item"):
    payload = {"type": "message", "role": "assistant", "content": []}
    return RolloutRecord(
        path=Path("/tmp/fake.jsonl"),
        line_number=line_number,
        timestamp=timestamp,
        record_type=record_type,
        payload=payload,
        raw={"timestamp": timestamp, "type": record_type, "payload": payload},
    )


class ExtractTurnModelTests(unittest.TestCase):
    def test_returns_model_from_turn_context_payload(self):
        record = _turn_context(1, "2026-06-25T12:00:00.000Z", "gpt-5.5")
        self.assertEqual(extract_turn_model(record), "gpt-5.5")

    def test_returns_none_for_non_turn_context_record(self):
        record = _other_record(1, "2026-06-25T12:00:00.000Z")
        self.assertIsNone(extract_turn_model(record))

    def test_returns_none_when_turn_context_has_no_model(self):
        payload = {"turn_id": "turn-1", "cwd": "/tmp"}
        record = RolloutRecord(
            path=Path("/tmp/fake.jsonl"),
            line_number=1,
            timestamp="2026-06-25T12:00:00.000Z",
            record_type="turn_context",
            payload=payload,
            raw={"timestamp": "2026-06-25T12:00:00.000Z", "type": "turn_context", "payload": payload},
        )
        self.assertIsNone(extract_turn_model(record))


class LastTurnModelTests(unittest.TestCase):
    def test_returns_none_for_empty_records(self):
        self.assertIsNone(last_turn_model([]))

    def test_returns_none_when_no_turn_context_present(self):
        records = [_other_record(1, "2026-06-25T12:00:00.000Z")]
        self.assertIsNone(last_turn_model(records))

    def test_reports_model_from_last_turn_context_after_mid_session_switch(self):
        # Mirrors observed real-world data: a session can bounce between
        # models across turns; the LAST turn_context wins, even if an
        # earlier turn used a different (or the same) model again later.
        records = [
            _turn_context(1, "2026-06-25T12:00:00.000Z", "gpt-5.4"),
            _other_record(2, "2026-06-25T12:00:01.000Z"),
            _turn_context(3, "2026-06-25T12:00:02.000Z", "gpt-5.5"),
            _other_record(4, "2026-06-25T12:00:03.000Z"),
            _turn_context(5, "2026-06-25T12:00:04.000Z", "gpt-5.4"),
        ]
        self.assertEqual(last_turn_model(records), "gpt-5.4")

    def test_ignores_turn_context_without_model_when_later_ones_have_one(self):
        payload = {"turn_id": "turn-2", "cwd": "/tmp"}
        blank_turn = RolloutRecord(
            path=Path("/tmp/fake.jsonl"),
            line_number=2,
            timestamp="2026-06-25T12:00:01.000Z",
            record_type="turn_context",
            payload=payload,
            raw={"timestamp": "2026-06-25T12:00:01.000Z", "type": "turn_context", "payload": payload},
        )
        records = [
            _turn_context(1, "2026-06-25T12:00:00.000Z", "gpt-5.5"),
            blank_turn,
        ]
        # A later turn_context missing `model` must not blank out the last
        # real recorded model.
        self.assertEqual(last_turn_model(records), "gpt-5.5")


SESSION_ID = "019db111-1111-7111-8111-111111111111"


def _write_rollout(codex_home: Path, cwd: str, turn_models):
    """Write a minimal current-format rollout with one turn_context (and one
    user/assistant message pair) per entry in turn_models, in order."""
    session_dir = codex_home / "sessions" / "2026" / "04" / "21"
    session_dir.mkdir(parents=True, exist_ok=True)
    rollout_path = session_dir / f"rollout-2026-04-21T10-00-00-{SESSION_ID}.jsonl"
    records = [
        {
            "timestamp": "2026-04-21T15:00:00.000Z",
            "type": "session_meta",
            "payload": {
                "id": SESSION_ID,
                "timestamp": "2026-04-21T15:00:00.000Z",
                "cwd": cwd,
            },
        },
    ]
    for turn_index, model in enumerate(turn_models, start=1):
        base = 15 + turn_index
        turn_context = {
            "timestamp": f"2026-04-21T{base:02d}:00:00.000Z",
            "type": "turn_context",
            "payload": {"turn_id": f"turn-{turn_index}", "cwd": cwd, "model": model},
        }
        user_msg = {
            "timestamp": f"2026-04-21T{base:02d}:00:01.000Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": f"turn {turn_index}"}],
            },
        }
        assistant_msg = {
            "timestamp": f"2026-04-21T{base:02d}:00:02.000Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": f"reply {turn_index}"}],
            },
        }
        records.extend([turn_context, user_msg, assistant_msg])
    rollout_path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    return rollout_path


class SessionSummaryModelTests(unittest.TestCase):
    def test_session_summary_reports_model_from_last_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            _write_rollout(codex_home, project_path, ["gpt-5.4", "gpt-5.5"])
            client = CodexSessionsClient(codex_home=codex_home)

            sessions = client.list_sessions(project_path=project_path)

            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0].model, "gpt-5.5")

            session = client.get_session(SESSION_ID)
            self.assertEqual(session.model, "gpt-5.5")

    def test_session_summary_model_is_none_when_no_turn_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            _write_rollout(codex_home, project_path, [])
            client = CodexSessionsClient(codex_home=codex_home)

            sessions = client.list_sessions(project_path=project_path)

            self.assertEqual(len(sessions), 1)
            self.assertIsNone(sessions[0].model)

    def test_search_result_reports_model_from_last_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            _write_rollout(codex_home, project_path, ["gpt-5.4", "gpt-5.5"])
            client = CodexSessionsClient(codex_home=codex_home)

            results = client.search_sessions("turn", project_path=project_path)

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].model, "gpt-5.5")

    def test_conversation_summaries_track_model_per_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            _write_rollout(codex_home, project_path, ["gpt-5.4", "gpt-5.5"])
            client = CodexSessionsClient(codex_home=codex_home)

            conversations = client.list_conversations(project_path=project_path)

            self.assertEqual(len(conversations), 2)
            by_id = {c.conversation_id: c for c in conversations}
            self.assertEqual(by_id[1].model, "gpt-5.4")
            self.assertEqual(by_id[2].model, "gpt-5.5")


if __name__ == "__main__":
    unittest.main()
