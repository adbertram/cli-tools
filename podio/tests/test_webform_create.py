"""Focused tests for `podio webform create`."""

import json

from typer.testing import CliRunner

from pypodio2.transport import TransportException

from podio_cli.commands import webform


runner = CliRunner()


class _FakeTransport:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def POST(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


class _FakeClient:
    def __init__(self, result=None, error=None):
        self.transport = _FakeTransport(result=result, error=error)


def _write_json(tmp_path, content):
    json_file = tmp_path / "webform.json"
    if isinstance(content, str):
        json_file.write_text(content, encoding="utf-8")
    else:
        json_file.write_text(json.dumps(content), encoding="utf-8")
    return json_file


def test_create_webform_posts_complete_body_and_preserves_response(monkeypatch, tmp_path):
    webform_data = {
        "settings": {"title": "Contact us"},
        "domains": ["example.com"],
        "fields": [{"field_id": 12345}],
        "attachments": False,
    }
    json_file = _write_json(tmp_path, webform_data)
    fake_client = _FakeClient(result={"form_id": 98765})
    monkeypatch.setattr(webform, "get_client", lambda: fake_client)

    result = runner.invoke(
        webform.app,
        ["create", "30831886", "--json-file", str(json_file)],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"form_id": 98765}
    assert fake_client.transport.calls == [
        {
            "url": "/form/app/30831886/",
            "body": json.dumps(webform_data),
            "type": "application/json",
        }
    ]


def test_create_webform_rejects_malformed_json_before_api_call(monkeypatch, tmp_path):
    json_file = _write_json(tmp_path, '{"settings":')
    fake_client = _FakeClient(result={"form_id": 98765})
    monkeypatch.setattr(webform, "get_client", lambda: fake_client)

    result = runner.invoke(
        webform.app,
        ["create", "30831886", "--json-file", str(json_file)],
    )

    assert result.exit_code == 1
    assert f"Invalid JSON in {json_file}" in result.stderr
    assert fake_client.transport.calls == []


def test_create_webform_rejects_non_object_before_api_call(monkeypatch, tmp_path):
    json_file = _write_json(tmp_path, [{"field_id": 12345}])
    fake_client = _FakeClient(result={"form_id": 98765})
    monkeypatch.setattr(webform, "get_client", lambda: fake_client)

    result = runner.invoke(
        webform.app,
        ["create", "30831886", "--json-file", str(json_file)],
    )

    assert result.exit_code == 1
    assert "Webform configuration must be a JSON object" in result.stderr
    assert fake_client.transport.calls == []


def test_create_webform_reports_api_failure(monkeypatch, tmp_path):
    json_file = _write_json(
        tmp_path,
        {
            "settings": {},
            "domains": [],
            "fields": [],
            "attachments": False,
        },
    )
    error = TransportException(
        {"status": "400"},
        '{"error_description":"webform settings are invalid"}',
    )
    fake_client = _FakeClient(error=error)
    monkeypatch.setattr(webform, "get_client", lambda: fake_client)

    result = runner.invoke(
        webform.app,
        ["create", "30831886", "--json-file", str(json_file)],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Invalid request: webform settings are invalid" in result.stderr
    assert len(fake_client.transport.calls) == 1
