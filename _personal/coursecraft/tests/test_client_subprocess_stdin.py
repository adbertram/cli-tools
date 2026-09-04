"""Regression tests for CourseCraft's nested Airtable CLI process boundary."""

import subprocess
from types import SimpleNamespace

import pytest

from coursecraft_cli.client import ClientError, CourseCraftClient


def _client() -> CourseCraftClient:
    client = CourseCraftClient.__new__(CourseCraftClient)
    client.base_id = "appTEST"
    return client


def test_airtable_json_command_does_not_inherit_stdin(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout='{"id": "recTEST"}', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = _client()._run_airtable_command(["records", "get", "Slides", "recTEST"])

    assert result == {"id": "recTEST"}
    assert captured["stdin"] is subprocess.DEVNULL


def test_airtable_delete_does_not_inherit_stdin(monkeypatch):
    client = _client()
    captured = {}

    monkeypatch.setattr(client, "_ensure_mutation_allowed", lambda *args, **kwargs: None)

    def fake_run(args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            returncode=0,
            stdout='{"id": "recTEST", "deleted": true}',
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert client.delete_record("Slides", "recTEST") is True
    assert captured["stdin"] is subprocess.DEVNULL


def test_airtable_attachment_upload_does_not_inherit_stdin(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout='{"id": "recTEST"}', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = _client().upload_attachment("recTEST", "Image", "/tmp/image.png")

    assert result == {"id": "recTEST"}
    assert captured["stdin"] is subprocess.DEVNULL


def test_airtable_json_command_rejects_status_text_before_json(monkeypatch):
    def fake_run(args, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout='Loading records\n{"id": "recTEST"}',
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ClientError, match="Could not parse airtable CLI output"):
        _client()._run_airtable_command(
            ["records", "get", "Slides", "recTEST"]
        )


def test_airtable_nonzero_error_has_one_client_error_boundary(monkeypatch):
    def fake_run(args, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="API failed")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ClientError) as error:
        _client()._run_airtable_command(
            ["records", "get", "Slides", "recTEST"]
        )

    assert str(error.value) == "airtable CLI error: API failed"


def test_airtable_attachment_error_uses_stdout_when_stderr_is_empty(monkeypatch):
    def fake_run(args, **kwargs):
        return SimpleNamespace(returncode=1, stdout="upload rejected", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ClientError) as error:
        _client().upload_attachment("recTEST", "Image", "/tmp/image.png")

    assert str(error.value) == (
        "Failed to upload attachment to recTEST field 'Image': upload rejected"
    )
