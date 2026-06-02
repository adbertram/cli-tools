import json
from pathlib import Path

from typer.testing import CliRunner

import elevenlabs_cli.client as client_module
import elevenlabs_cli.config as config_module
from elevenlabs_cli.main import app


runner = CliRunner()


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b"audio", headers=None):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.content = content
        self.headers = headers or {}
        self.text = json.dumps(self._json_data)
        self.ok = status_code < 400

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"Unexpected HTTP status: {self.status_code}")


def reset_client_cache():
    client_module._client = None
    config_module._configs.clear()


def configure_test_config(monkeypatch):
    reset_client_cache()
    monkeypatch.setattr(config_module.Config, "has_credentials", lambda self: True)
    monkeypatch.setattr(config_module.Config, "get_missing_credentials", lambda self: [])
    monkeypatch.setattr(config_module.Config, "api_key", property(lambda self: "test-key"))
    monkeypatch.setattr(config_module.Config, "base_url", property(lambda self: "https://api.example.test"))


def test_speech_create_sends_pronunciation_dictionary_locators(monkeypatch, tmp_path):
    configure_test_config(monkeypatch)
    requests = []

    def fake_request(method, url, **kwargs):
        requests.append({"method": method, "url": url, **kwargs})
        return FakeResponse(
            content=b"mp3-bytes",
            headers={
                "request-id": "req-123",
                "history-item-id": "hist-123",
                "character-cost": "11",
            },
        )

    monkeypatch.setattr("requests.request", fake_request)

    output_path = tmp_path / "speech.mp3"
    result = runner.invoke(
        app,
        [
            "speech",
            "create",
            "voice-123",
            "Hello sysadmins.",
            "--output",
            str(output_path),
            "--pronunciation-dictionary",
            "dict-1:version-1",
            "--pronunciation-dictionary",
            "dict-2:version-2",
        ],
    )

    assert result.exit_code == 0, result.output
    assert output_path.read_bytes() == b"mp3-bytes"
    assert requests[0]["method"] == "POST"
    assert requests[0]["url"] == "https://api.example.test/v1/text-to-speech/voice-123"
    assert requests[0]["json"]["pronunciation_dictionary_locators"] == [
        {"pronunciation_dictionary_id": "dict-1", "version_id": "version-1"},
        {"pronunciation_dictionary_id": "dict-2", "version_id": "version-2"},
    ]


def test_pronunciation_dictionaries_create_from_rules_sends_alias_and_phoneme_rules(monkeypatch):
    configure_test_config(monkeypatch)
    requests = []

    def fake_request(method, url, **kwargs):
        requests.append({"method": method, "url": url, **kwargs})
        return FakeResponse(
            json_data={
                "id": "dict-123",
                "name": "Course Terms",
                "version_id": "version-123",
                "version_rules_num": 2,
            }
        )

    monkeypatch.setattr("requests.request", fake_request)

    result = runner.invoke(
        app,
        [
            "pronunciation-dictionaries",
            "create-from-rules",
            "--name",
            "Course Terms",
            "--alias-rule",
            "Sysadmins=sys admins",
            "--phoneme-rule",
            "tomato|ipa|/tə'meɪtoʊ/",
            "--description",
            "Course pronunciation fixes",
            "--workspace-access",
            "viewer",
        ],
    )

    assert result.exit_code == 0, result.output
    assert requests[0]["method"] == "POST"
    assert requests[0]["url"] == "https://api.example.test/v1/pronunciation-dictionaries/add-from-rules"
    assert requests[0]["json"] == {
        "name": "Course Terms",
        "rules": [
            {"string_to_replace": "Sysadmins", "type": "alias", "alias": "sys admins"},
            {
                "string_to_replace": "tomato",
                "type": "phoneme",
                "alphabet": "ipa",
                "phoneme": "/tə'meɪtoʊ/",
            },
        ],
        "description": "Course pronunciation fixes",
        "workspace_access": "viewer",
    }


def test_pronunciation_dictionaries_create_from_file_uploads_pls(monkeypatch, tmp_path):
    configure_test_config(monkeypatch)
    requests = []

    def fake_request(method, url, **kwargs):
        requests.append({"method": method, "url": url, **kwargs})
        return FakeResponse(json_data={"id": "dict-file", "name": "PLS", "version_id": "version-file"})

    monkeypatch.setattr("requests.request", fake_request)
    pls_path = tmp_path / "dictionary.pls"
    pls_path.write_text("<lexicon></lexicon>", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "pronunciation-dictionaries",
            "create-from-file",
            "--name",
            "PLS",
            "--file",
            str(pls_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert requests[0]["method"] == "POST"
    assert requests[0]["url"] == "https://api.example.test/v1/pronunciation-dictionaries/add-from-file"
    assert requests[0]["data"] == {"name": "PLS"}
    assert requests[0]["files"]["file"][0] == "dictionary.pls"
    assert requests[0]["files"]["file"][1] == b"<lexicon></lexicon>"


def test_pronunciation_dictionaries_list_get_update(monkeypatch):
    configure_test_config(monkeypatch)
    requests = []

    def fake_request(method, url, **kwargs):
        requests.append({"method": method, "url": url, **kwargs})
        if method == "GET" and url.endswith("/v1/pronunciation-dictionaries"):
            return FakeResponse(
                json_data={
                    "pronunciation_dictionaries": [
                        {
                            "id": "dict-1",
                            "latest_version_id": "version-1",
                            "latest_version_rules_num": 1,
                            "name": "Terms",
                        }
                    ],
                    "has_more": False,
                    "next_cursor": None,
                }
            )
        if method == "GET":
            return FakeResponse(json_data={"id": "dict-1", "name": "Terms"})
        return FakeResponse(json_data={"id": "dict-1", "name": "Renamed", "archived": True})

    monkeypatch.setattr("requests.request", fake_request)

    list_result = runner.invoke(app, ["pronunciation-dictionaries", "list", "--page-size", "10"])
    get_result = runner.invoke(app, ["pronunciation-dictionaries", "get", "dict-1"])
    update_result = runner.invoke(
        app,
        ["pronunciation-dictionaries", "update", "dict-1", "--name", "Renamed", "--archived"],
    )

    assert list_result.exit_code == 0, list_result.output
    assert get_result.exit_code == 0, get_result.output
    assert update_result.exit_code == 0, update_result.output
    assert json.loads(list_result.output)["next_cursor"] is None
    assert requests[0]["method"] == "GET"
    assert requests[0]["params"] == {
        "page_size": 10,
        "sort": "creation_time_unix",
        "sort_direction": "DESCENDING",
    }
    assert requests[1]["method"] == "GET"
    assert requests[1]["url"] == "https://api.example.test/v1/pronunciation-dictionaries/dict-1"
    assert requests[2]["method"] == "PATCH"
    assert requests[2]["json"] == {"name": "Renamed", "archived": True}


def test_pronunciation_dictionary_rules_set_add_remove(monkeypatch):
    configure_test_config(monkeypatch)
    requests = []

    def fake_request(method, url, **kwargs):
        requests.append({"method": method, "url": url, **kwargs})
        return FakeResponse(json_data={"id": "dict-1", "version_id": "version-2", "version_rules_num": 2})

    monkeypatch.setattr("requests.request", fake_request)

    set_result = runner.invoke(
        app,
        [
            "pronunciation-dictionaries",
            "set-rules",
            "dict-1",
            "--alias-rule",
            "Sysadmins=sys admins",
        ],
    )
    add_result = runner.invoke(
        app,
        [
            "pronunciation-dictionaries",
            "add-rules",
            "dict-1",
            "--phoneme-rule",
            "route|cmu|R AW1 T",
        ],
    )
    remove_result = runner.invoke(
        app,
        [
            "pronunciation-dictionaries",
            "remove-rules",
            "dict-1",
            "--rule-string",
            "Sysadmins",
            "--rule-string",
            "route",
        ],
    )

    assert set_result.exit_code == 0, set_result.output
    assert add_result.exit_code == 0, add_result.output
    assert remove_result.exit_code == 0, remove_result.output
    assert requests[0]["url"] == "https://api.example.test/v1/pronunciation-dictionaries/dict-1/set-rules"
    assert requests[0]["json"] == {
        "rules": [{"string_to_replace": "Sysadmins", "type": "alias", "alias": "sys admins"}]
    }
    assert requests[1]["url"] == "https://api.example.test/v1/pronunciation-dictionaries/dict-1/add-rules"
    assert requests[1]["json"] == {
        "rules": [
            {
                "string_to_replace": "route",
                "type": "phoneme",
                "alphabet": "cmu",
                "phoneme": "R AW1 T",
            }
        ]
    }
    assert requests[2]["url"] == "https://api.example.test/v1/pronunciation-dictionaries/dict-1/remove-rules"
    assert requests[2]["json"] == {"rule_strings": ["Sysadmins", "route"]}


def test_pronunciation_dictionaries_download_version(monkeypatch, tmp_path):
    configure_test_config(monkeypatch)
    requests = []

    def fake_request(method, url, **kwargs):
        requests.append({"method": method, "url": url, **kwargs})
        return FakeResponse(
            content=b"<lexicon></lexicon>",
            headers={"content-type": "application/pls+xml"},
        )

    monkeypatch.setattr("requests.request", fake_request)

    output_path = tmp_path / "dictionary.pls"
    result = runner.invoke(
        app,
        [
            "pronunciation-dictionaries",
            "download",
            "dict-1",
            "version-1",
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert output_path.read_bytes() == b"<lexicon></lexicon>"
    assert requests[0]["method"] == "GET"
    assert (
        requests[0]["url"]
        == "https://api.example.test/v1/pronunciation-dictionaries/dict-1/version-1/download"
    )
    assert requests[0]["headers"]["Accept"] == "application/pls+xml"
