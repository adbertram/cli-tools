"""Tests for batch record deletion (client ``delete_records`` and ``records delete-many``).

All HTTP is mocked at ``requests.request`` so the real ``_make_request``
path runs; no request ever reaches Airtable.
"""
import json

import pytest
import requests
from typer.testing import CliRunner

from airtable_cli.client import AirtableClient, PartialDeleteError
from airtable_cli.commands import records
from cli_tools_shared.exceptions import ClientError


runner = CliRunner()


def _ids(count):
    return [f"rec{i:014d}" for i in range(count)]


class _Response:
    headers = {}

    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeAirtable:
    """Records every request; answers like Airtable, failing on chosen call numbers."""

    def __init__(self, fail_on=()):
        self.calls = []
        self.fail_on = set(fail_on)

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) in self.fail_on:
            return _Response(404, {"error": {"type": "NOT_FOUND", "message": "Could not find record"}})
        ids = kwargs["params"]["records[]"]
        return _Response(200, {"records": [{"id": rid, "deleted": True} for rid in ids]})


def _client():
    client = AirtableClient.__new__(AirtableClient)
    client.base_url = "https://api.airtable.test/v0"
    client.headers = {"Authorization": "Bearer test"}
    return client


@pytest.fixture
def fake(monkeypatch):
    fake = _FakeAirtable()
    monkeypatch.setattr(requests, "request", fake)
    monkeypatch.setattr(AirtableClient, "MAX_RETRIES", 1)
    return fake


# ---------- client ----------


def test_delete_records_chunks_23_ids_into_10_10_3(fake):
    ids = _ids(23)

    result = _client().delete_records("appBase", "Tasks", ids)

    assert [len(c["params"]["records[]"]) for c in fake.calls] == [10, 10, 3]
    assert [c["params"]["records[]"] for c in fake.calls] == [ids[0:10], ids[10:20], ids[20:23]]
    assert all(c["method"] == "DELETE" for c in fake.calls)
    assert all(c["url"] == "https://api.airtable.test/v0/appBase/Tasks" for c in fake.calls)
    assert all(c["json"] is None for c in fake.calls)
    assert result == [{"id": rid, "deleted": True} for rid in ids]


def test_delete_records_sends_repeated_records_brackets_query_params(fake):
    _client().delete_records("appBase", "Tasks", ["recAAA", "recBBB"])

    call = fake.calls[0]
    prepared = requests.Request("DELETE", call["url"], params=call["params"]).prepare()
    assert prepared.url == (
        "https://api.airtable.test/v0/appBase/Tasks"
        "?records%5B%5D=recAAA&records%5B%5D=recBBB"
    )


def test_delete_records_exactly_10_ids_is_one_request(fake):
    _client().delete_records("appBase", "Tasks", _ids(10))

    assert len(fake.calls) == 1


def test_delete_records_rejects_invalid_id_before_any_request(fake):
    with pytest.raises(ClientError, match="Invalid record ID"):
        _client().delete_records("appBase", "Tasks", _ids(12) + ["../Other/recX"])

    assert fake.calls == []


def test_delete_records_stops_at_failed_chunk_and_reports_progress(fake):
    fake.fail_on = {2}
    ids = _ids(23)

    with pytest.raises(PartialDeleteError) as excinfo:
        _client().delete_records("appBase", "Tasks", ids)

    assert len(fake.calls) == 2  # chunk 3 never sent
    err = excinfo.value
    assert err.deleted == [{"id": rid, "deleted": True} for rid in ids[:10]]
    message = str(err)
    assert "Chunk 2 of 3 failed for " + ", ".join(ids[10:20]) in message
    assert "API request failed (404): Could not find record" in message
    assert "Deleted in completed chunks (10): " + ", ".join(ids[:10]) in message
    assert "Not attempted (3): " + ", ".join(ids[20:23]) in message


def test_delete_records_first_chunk_failure_reports_none_deleted(fake):
    fake.fail_on = {1}

    with pytest.raises(PartialDeleteError) as excinfo:
        _client().delete_records("appBase", "Tasks", _ids(5))

    assert excinfo.value.deleted == []
    assert "Deleted in completed chunks (0): none." in str(excinfo.value)
    assert "Not attempted (0): none." in str(excinfo.value)


# ---------- CLI ----------


@pytest.fixture
def cli(monkeypatch, fake):
    monkeypatch.setattr(records, "resolve_base_id", lambda base_id: base_id)
    monkeypatch.setattr(records, "get_client", _client)
    return fake


def test_delete_many_yes_prints_combined_rows(cli):
    ids = _ids(23)

    result = runner.invoke(records.app, ["delete-many", "Tasks", *ids, "--base", "appBase", "--yes"])

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == [{"id": rid, "deleted": True} for rid in ids]
    assert "Deleted 23 record(s)" in result.stderr
    assert len(cli.calls) == 3


def test_delete_many_mid_way_failure_exits_1_with_partial_stdout(cli):
    cli.fail_on = {2}
    ids = _ids(23)

    result = runner.invoke(records.app, ["delete-many", "Tasks", *ids, "--base", "appBase", "--yes"])

    assert result.exit_code == 1
    assert json.loads(result.stdout) == [{"id": rid, "deleted": True} for rid in ids[:10]]
    assert result.stderr.startswith("Error: Chunk 2 of 3 failed for ")
    assert "Deleted in completed chunks (10): " + ", ".join(ids[:10]) in result.stderr
    assert "Not attempted (3): " + ", ".join(ids[20:23]) in result.stderr
    assert len(cli.calls) == 2


def test_delete_many_non_tty_without_yes_refuses(cli):
    result = runner.invoke(records.app, ["delete-many", "Tasks", "recAAA", "recBBB", "--base", "appBase"])

    assert result.exit_code == 1
    assert "Refusing to delete 2 record(s) without confirmation." in result.stderr
    assert "Re-run with --yes in non-interactive contexts." in result.stderr
    assert result.stdout == ""
    assert cli.calls == []


def test_delete_many_interactive_decline_cancels(cli, monkeypatch):
    monkeypatch.setattr("cli_tools_shared.output._stdin_is_interactive_tty", lambda: True)

    result = runner.invoke(
        records.app, ["delete-many", "Tasks", "recAAA", "recBBB", "--base", "appBase"], input="n\n"
    )

    assert result.exit_code == 0
    assert "Are you sure you want to delete 2 record(s): recAAA, recBBB?" in result.stdout
    assert "Cancelled" in result.stderr
    assert cli.calls == []


def test_delete_many_interactive_accept_deletes(cli, monkeypatch):
    monkeypatch.setattr("cli_tools_shared.output._stdin_is_interactive_tty", lambda: True)

    result = runner.invoke(
        records.app, ["delete-many", "Tasks", "recAAA", "recBBB", "--base", "appBase"], input="y\n"
    )

    assert result.exit_code == 0, result.stderr
    assert len(cli.calls) == 1
    assert cli.calls[0]["params"] == {"records[]": ["recAAA", "recBBB"]}


def test_delete_many_requires_at_least_one_record_id(cli):
    result = runner.invoke(records.app, ["delete-many", "Tasks", "--base", "appBase", "--yes"])

    assert result.exit_code == 2
    assert cli.calls == []


# ---------- failures that are not an HTTP error status ----------


class _NonJsonResponse(_Response):
    """A 200 whose body is not JSON (e.g. an HTML proxy page)."""

    def __init__(self):
        super().__init__(200, {})
        self.text = "<html>gateway</html>"

    def json(self):
        raise requests.exceptions.JSONDecodeError("Expecting value", self.text, 0)


def _chunked_encoding_error(kwargs):
    raise requests.exceptions.ChunkedEncodingError("Connection broken: IncompleteRead")


def _non_json_body(kwargs):
    return _NonJsonResponse()


def _missing_records_key(kwargs):
    return _Response(200, {"unexpected": True})


SECOND_CHUNK_FAILURES = {
    "chunked-encoding": (_chunked_encoding_error, "Request failed: ChunkedEncodingError: Connection broken"),
    "non-json-200": (_non_json_body, "API returned a non-JSON body (200)"),
    "missing-records-key": (_missing_records_key, "KeyError: 'records'"),
}


@pytest.fixture
def second_chunk_fails(monkeypatch):
    """Answer like Airtable, except call 2 runs the failure under test."""

    def install(failure):
        calls = []

        def fake(**kwargs):
            calls.append(kwargs)
            if len(calls) == 2:
                return failure(kwargs)
            ids = kwargs["params"]["records[]"]
            return _Response(200, {"records": [{"id": rid, "deleted": True} for rid in ids]})

        monkeypatch.setattr(requests, "request", fake)
        monkeypatch.setattr(records, "resolve_base_id", lambda base_id: base_id)
        monkeypatch.setattr(records, "get_client", _client)
        return calls

    return install


@pytest.mark.parametrize("name", sorted(SECOND_CHUNK_FAILURES))
def test_delete_records_any_chunk_exception_becomes_partial_delete_error(second_chunk_fails, name):
    failure, reason = SECOND_CHUNK_FAILURES[name]
    calls = second_chunk_fails(failure)
    ids = _ids(25)

    with pytest.raises(PartialDeleteError) as excinfo:
        _client().delete_records("appBase", "Tasks", ids)

    assert len(calls) == 2  # chunk 3 never sent, failed chunk not retried
    err = excinfo.value
    assert err.deleted == [{"id": rid, "deleted": True} for rid in ids[:10]]
    message = str(err)
    assert message.startswith("Chunk 2 of 3 failed for " + ", ".join(ids[10:20]) + ": ")
    assert reason in message
    assert "Deleted in completed chunks (10): " + ", ".join(ids[:10]) in message
    assert "Not attempted (5): " + ", ".join(ids[20:25]) in message


@pytest.mark.parametrize("name", sorted(SECOND_CHUNK_FAILURES))
def test_delete_many_any_chunk_exception_prints_deleted_rows_and_exits_1(second_chunk_fails, name):
    failure, reason = SECOND_CHUNK_FAILURES[name]
    calls = second_chunk_fails(failure)
    ids = _ids(25)

    result = runner.invoke(records.app, ["delete-many", "Tasks", *ids, "--base", "appBase", "--yes"])

    assert result.exit_code == 1
    assert not isinstance(result.exception, (requests.RequestException, ValueError, KeyError))
    assert json.loads(result.stdout) == [{"id": rid, "deleted": True} for rid in ids[:10]]
    assert result.stderr.startswith("Error: Chunk 2 of 3 failed for ")
    assert reason in result.stderr
    assert "Not attempted (5): " + ", ".join(ids[20:25]) in result.stderr
    assert len(calls) == 2


class _RetryAfterDateResponse(_Response):
    def __init__(self, retry_after):
        super().__init__(429, {"error": {"type": "RATE_LIMIT", "message": "Too many requests"}})
        self.headers = {"Retry-After": retry_after}


def test_delete_many_http_date_retry_after_waits_and_retries(monkeypatch):
    """An HTTP-date Retry-After is honored instead of crashing int() mid-batch."""
    calls, sleeps = [], []

    def fake(**kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            return _RetryAfterDateResponse("Wed, 21 Oct 2015 07:28:00 GMT")
        ids = kwargs["params"]["records[]"]
        return _Response(200, {"records": [{"id": rid, "deleted": True} for rid in ids]})

    monkeypatch.setattr(requests, "request", fake)
    monkeypatch.setattr("airtable_cli.client.time.sleep", sleeps.append)
    monkeypatch.setattr(records, "resolve_base_id", lambda base_id: base_id)
    monkeypatch.setattr(records, "get_client", _client)
    ids = _ids(25)

    result = runner.invoke(records.app, ["delete-many", "Tasks", *ids, "--base", "appBase", "--yes"])

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == [{"id": rid, "deleted": True} for rid in ids]
    assert sleeps == [0.0]  # a past date means retry now
    assert [c["params"]["records[]"] for c in calls] == [ids[0:10], ids[10:20], ids[10:20], ids[20:25]]


def test_retry_after_seconds_parses_both_rfc_forms():
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime

    from airtable_cli.client import _retry_after_seconds

    assert _retry_after_seconds(None) is None
    assert _retry_after_seconds("7") == 7.0
    assert _retry_after_seconds(" 0 ") == 0.0
    assert _retry_after_seconds("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0
    future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=120), usegmt=True)
    assert 100 < _retry_after_seconds(future) <= 120
    assert _retry_after_seconds("soon") is None
    assert _retry_after_seconds("-5") is None
