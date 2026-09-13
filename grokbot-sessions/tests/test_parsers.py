"""Offline parser tests for the Grok Bot Sessions CLI.

Fixtures are hand-written from the documented entry taxonomy; no live account
data, token, machine id, or account scope appears here.
"""
import base64
import json

from grokbot_sessions_cli import parsers


def encode(body: dict) -> str:
    return base64.b64encode(json.dumps(body).encode()).decode()


def test_turn_index_parses_user_send_and_authored_ids():
    assert parsers.turn_index("t3u") == 3
    assert parsers.turn_index("t14s16") == 14
    assert parsers.turn_index("t17a0") == 17
    assert parsers.turn_index("t0s0") == 0


def test_turn_index_rejects_non_turn_ids():
    assert parsers.turn_index("event-47931f30") is None
    assert parsers.turn_index("spend-initiation:abc") is None
    assert parsers.turn_index(None) is None


def test_as_int_handles_protobuf_es_int64_strings():
    assert parsers.as_int("1788905903533") == 1788905903533
    assert parsers.as_int(7) == 7
    assert parsers.as_int("-3") == -3
    assert parsers.as_int("not-a-number") is None
    assert parsers.as_int(None) is None
    assert parsers.as_int(True) is None


def test_epoch_to_iso_accepts_string_millis():
    assert parsers.epoch_to_iso("0") == "1970-01-01T00:00:00+00:00"
    assert parsers.epoch_to_iso(None) == ""
    assert parsers.epoch_to_iso("bogus") == ""


def test_decode_body_round_trips_and_tolerates_bad_input():
    raw = {"body": encode({"kind": "message", "id": "t3u", "role": "user"})}
    assert parsers.decode_body(raw) == {"kind": "message", "id": "t3u", "role": "user"}

    assert parsers.decode_body({"body": "!!!not-base64!!!"}) is None
    assert parsers.decode_body({"body": encode(["not", "a", "dict"])}) is None
    assert parsers.decode_body({}) is None


def test_normalize_entry_prefixes_id_and_groups_turn():
    agent = {"id": "1036984", "legacy_id": "5658aa56-122b-4f56-acd9-5102e4f39d1b", "name": "Lego Scout"}
    raw = {
        "seq": "100",
        "entryKind": "message",
        "entryId": "t6u",
        "updatedSeq": "100",
        "body": encode(
            {
                "kind": "message",
                "id": "t6u",
                "role": "user",
                "content": "hello there",
                "timestampMs": 1789299653334,
            }
        ),
    }

    row = parsers.normalize_entry(raw, agent)

    assert row["id"] == "5658aa56-122b-4f56-acd9-5102e4f39d1b:t6u"
    assert row["entry_id"] == "t6u"
    assert row["turn"] == 6
    assert row["kind"] == "message"
    assert row["role"] == "user"
    assert row["agent_name"] == "Lego Scout"
    assert row["timestamp"] == "2026-09-13T11:40:53.334000+00:00"
    assert row["payload"]["content"] == "hello there"


def test_normalize_entry_marks_omitted_body_without_crashing():
    row = parsers.normalize_entry(
        {"seq": "1", "entryKind": "message", "entryId": "t1u", "bodyOmitted": True},
        {"legacy_id": "uuid"},
    )
    assert row["body_omitted"] is True
    assert row["payload"] == {}
    assert row["summary"] == "undecoded body (t1u)"


def test_normalize_agent_shortens_kind_and_flags_rooms():
    room = parsers.normalize_agent(
        {
            "id": "2781289",
            "legacyAgentId": "4d966ea1-4b17-480b-96cc-3f197e9ea2ea",
            "name": "Fff, Adam Bertram",
            "kind": "GROK_BOT_AGENT_KIND_ROOM",
            "memberAgentIds": ["cd58935c-b2fa-448e-ac49-15fe781ddcec"],
            "createdAtMs": "1789309888840",
        }
    )
    assert room["kind"] == "ROOM"
    assert room["is_group"] is True
    assert room["member_count"] == 1
    assert room["legacy_id"] == "4d966ea1-4b17-480b-96cc-3f197e9ea2ea"


def test_turn_rows_group_entries_and_count_cards():
    agent = {"id": "1", "legacy_id": "uuid", "name": "Bot"}
    entries = [
        parsers.normalize_entry(
            {
                "entryId": "t3u",
                "body": encode({"kind": "message", "id": "t3u", "role": "user", "content": "hi", "timestampMs": 10}),
            },
            agent,
        ),
        parsers.normalize_entry(
            {
                "entryId": "t3s1",
                "body": encode(
                    {
                        "kind": "send-message",
                        "id": "t3s1",
                        "message": {"type": "widget", "widget": {"prompt": "ok?"}},
                        "timestampMs": 20,
                        "respondedValue": "yes",
                    }
                ),
            },
            agent,
        ),
        parsers.normalize_entry(
            {
                "entryId": "event-1",
                "body": encode({"kind": "event", "id": "event-1", "event": {"type": "name-changed"}, "timestampMs": 30}),
            },
            agent,
        ),
    ]

    rows = parsers.turn_rows(agent, entries)

    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "uuid:t3"
    assert row["entry_count"] == 2
    assert row["tool_call_count"] == 1
    assert row["user_text"] == "hi"
    assert row["entry_ids"] == ["t3u", "t3s1"]


def test_approval_rows_read_permission_and_review_fields():
    agent = {"id": "1", "legacy_id": "uuid", "name": "Bot"}
    permission = parsers.normalize_entry(
        {
            "entryId": "t2s1",
            "body": encode(
                {
                    "kind": "send-message",
                    "id": "t2s1",
                    "message": {
                        "type": "local-tool-permission",
                        "ask": {
                            "requestId": "a" * 64,
                            "action": "run-command",
                            "target": "ls -la",
                            "machineId": "machine-uuid",
                            "machineLabel": "host.local",
                            "status": "allowed",
                        },
                    },
                    "timestampMs": 5,
                    "respondedValue": "allowed-once",
                }
            ),
        },
        agent,
    )
    approval = parsers.normalize_entry(
        {
            "entryId": "t2s2",
            "body": encode(
                {
                    "kind": "send-message",
                    "id": "t2s2",
                    "message": {
                        "type": "auto-review-approval",
                        "approval": {"requestId": "b" * 8, "summary": "Run a task", "status": "always", "reason": "needs review"},
                    },
                    "timestampMs": 6,
                }
            ),
        },
        agent,
    )

    rows = parsers.approval_rows(agent, [permission, approval])

    assert [row["kind"] for row in rows] == ["local-tool-permission", "auto-review-approval"]
    assert rows[0]["action"] == "run-command"
    assert rows[0]["machine_label"] == "host.local"
    assert rows[0]["resolved_value"] == "allowed-once"
    assert rows[1]["status"] == "always"
    assert rows[1]["reason"] == "needs review"


def test_conversation_rows_summarize_generation():
    agent = {"id": "1", "legacy_id": "uuid", "name": "Bot"}
    entries = [
        parsers.normalize_entry(
            {"entryId": "t0u", "body": encode({"kind": "message", "id": "t0u", "role": "user", "content": "one", "timestampMs": 100})},
            agent,
        ),
        parsers.normalize_entry(
            {"entryId": "t0s0", "body": encode({"kind": "send-message", "id": "t0s0", "message": {"type": "text", "content": "two"}, "timestampMs": 200})},
            agent,
        ),
    ]

    rows = parsers.conversation_rows(agent, entries, 1)

    assert len(rows) == 1
    assert rows[0]["id"] == "uuid:1"
    assert rows[0]["entry_count"] == 2
    assert rows[0]["message_count"] == 1
    assert rows[0]["send_count"] == 1
    assert rows[0]["turn_count"] == 1
    assert rows[0]["first_prompt"] == "one"
    assert rows[0]["last_activity"].startswith("1970-01-01T00:00:00.200")


def test_conversation_rows_default_generation():
    agent = {"legacy_id": "uuid"}
    entries = [
        parsers.normalize_entry(
            {"entryId": "t0u", "body": encode({"kind": "message", "id": "t0u", "role": "user", "content": "one", "timestampMs": 1})},
            agent,
        )
    ]
    assert parsers.conversation_rows(agent, entries, None)[0]["generation"] == 1


def test_subagent_rows_scope_to_selected_agents():
    roster = [
        {"id": "1", "legacy_id": "room", "name": "Room", "is_group": True, "member_agent_ids": ["member"]},
        {"id": "2", "legacy_id": "member", "name": "Member", "kind": "AGENT"},
        {"id": "3", "legacy_id": "other", "name": "Other", "is_group": True, "member_agent_ids": ["member"]},
    ]

    rows = parsers.subagent_rows(roster, {"member": []})

    assert rows == []

    rows = parsers.subagent_rows(roster, {"room": []})
    assert len(rows) == 1
    assert rows[0]["kind"] == "room-member"
    assert rows[0]["member_name"] == "Member"


def test_automation_rows_parse_record_json():
    agent = {"id": "1", "legacy_id": "uuid", "name": "Bot"}
    raw = [
        {
            "automationId": "auto-1",
            "recordJson": json.dumps(
                {
                    "id": "auto-1",
                    "name": "Nightly scan",
                    "prompt": "do the thing",
                    "trigger": {"type": "cron", "schedule": "0 9 * * *"},
                    "isEnabled": True,
                    "provenance": "user",
                    "createdAt": 1000,
                    "runs": [{"id": "r1"}],
                }
            ),
        }
    ]

    rows = parsers.automation_rows(agent, raw)

    assert rows[0]["id"] == "auto-1"
    assert rows[0]["trigger_type"] == "cron"
    assert rows[0]["is_enabled"] is True
    assert rows[0]["run_count"] == 1


def test_effective_generation_defaults_only_for_unlabelled_transcripts():
    assert parsers.effective_generation(1) == 1
    assert parsers.effective_generation(4) == 4
    assert parsers.effective_generation(None) == 1
    assert parsers.effective_generation("1") == 1


def test_conversation_rows_report_whether_the_api_labelled_the_generation():
    agent = {"legacy_id": "uuid"}
    entries = [
        parsers.normalize_entry(
            {
                "entryId": "t0u",
                "body": encode({"kind": "message", "id": "t0u", "role": "user", "content": "hi", "timestampMs": 1}),
            },
            agent,
        )
    ]

    labelled = parsers.conversation_rows(agent, entries, 1)[0]
    unlabelled = parsers.conversation_rows(agent, entries, None)[0]

    assert labelled["generation"] == 1
    assert labelled["generation_reported"] is True
    assert unlabelled["generation"] == 1
    assert unlabelled["generation_reported"] is False
