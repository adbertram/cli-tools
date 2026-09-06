"""A content write to a human-verified artifact lands and un-stamps it.

The versioning engine clears a paired ``… Human Verified`` stamp in the same
PATCH as changed content. ``CourseCraftClient.update_record`` reports the clear
with the stable ``HV_CLEARED`` identifier.
"""

import json

from coursecraft_cli.client import CourseCraftClient

from test_client_write_verification import (
    _client,
    _install_base_id,
    _parse_sent_fields,
    _with_field_list,
)


def _stamped_demo():
    return {
        "Demo Overview": "old overview",
        "Demo Overview Review (AI)": "PASS",
        "Demo Overview Human Verified": True,
        "Version Control": json.dumps({
            "demo.overview": {
                "v": 3,
                "sha256": "0" * 64,
                "at": "2026-09-01T00:00:00Z",
            }
        }),
    }


def _stateful_client(monkeypatch, state):
    client = _client()
    _install_base_id(client)
    sent = []

    def fake_run(args):
        if args[:2] == ["records", "update"]:
            sent.append(_parse_sent_fields(args))
            state.update(sent[-1])
        return {"id": "recDemo", "fields": dict(state)}

    monkeypatch.setattr(client, "_run_airtable_command", _with_field_list(fake_run))
    monkeypatch.setattr(
        client,
        "get_record",
        lambda table, record_id: {"id": record_id, "fields": dict(state)},
    )
    return client, sent


def test_content_change_to_stamped_demo_lands_and_clears_the_stamp(monkeypatch, capsys):
    state = _stamped_demo()
    client, sent = _stateful_client(monkeypatch, state)

    result = client.update_record("Demos", "recDemo", {"Demo Overview": "new overview"})

    assert len(sent) == 1, "one PATCH carries the content and the clears"
    assert sent[0]["Demo Overview"] == "new overview"
    assert sent[0]["Demo Overview Human Verified"] is False
    assert sent[0]["Demo Overview Review (AI)"] == ""
    assert json.loads(sent[0]["Version Control"])["demo.overview"]["v"] == 4
    assert result["fields"]["Demo Overview Human Verified"] is False

    err = capsys.readouterr().err
    assert "⚠ REMINDER" in err, err
    assert "[HV_CLEARED]" in err, err
    assert "'Demo Overview Human Verified'" in err, err
    assert "rule 4a" not in err, err


def test_no_op_resubmission_keeps_the_stamp_and_says_nothing(monkeypatch, capsys):
    state = _stamped_demo()
    client, sent = _stateful_client(monkeypatch, state)

    client.update_record("Demos", "recDemo", {"Demo Overview": "old overview"})

    assert sent == [{"Demo Overview": "old overview"}]
    assert state["Demo Overview Human Verified"] is True
    assert "REMINDER" not in capsys.readouterr().err


def test_explicit_unstamp_is_the_callers_write_and_gets_no_reminder(monkeypatch, capsys):
    state = _stamped_demo()
    client, sent = _stateful_client(monkeypatch, state)

    client.update_record("Demos", "recDemo", {"Demo Overview Human Verified": False})

    assert sent == [{"Demo Overview Human Verified": False}]
    assert "REMINDER" not in capsys.readouterr().err


def test_remind_helper_is_reached_from_update_record():
    assert callable(CourseCraftClient._remind_cleared_human_verified)
