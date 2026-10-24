import json
from pathlib import Path

import pytest
from dotenv import dotenv_values
from typer.testing import CliRunner

from cli_tools_shared.exceptions import ClientError
from facebook_cli import config as config_mod
from facebook_cli.commands import reels
from facebook_cli.config import API_AUTH_TYPE, BROWSER_AUTH_TYPE, Config
from facebook_cli.graph_api import FacebookGraphClient


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeConfig:
    access_token = "USER_TOKEN"
    graph_base_url = "https://graph.facebook.com/v24.0"


class FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith("/me/accounts"):
            return FakeResponse(
                {
                    "data": [
                        {
                            "id": "PAGE1",
                            "name": "ATA",
                            "access_token": "PAGE_TOKEN",
                            "tasks": ["CREATE_CONTENT"],
                        }
                    ]
                }
            )
        if url.endswith("/PAGE1"):
            return FakeResponse(
                {"id": "PAGE1", "name": "ATA", "access_token": "PAGE_TOKEN"}
            )
        if url.endswith("/me/video_reels"):
            data = kwargs.get("data") or {}
            if data.get("upload_phase") == "start":
                return FakeResponse(
                    {
                        "video_id": "VID1",
                        "upload_url": "https://rupload.facebook.test/VID1",
                    }
                )
            return FakeResponse({"success": True})
        if url.endswith("/VID1"):
            return FakeResponse({"id": "VID1", "status": {"video_status": "ready"}})
        raise AssertionError(f"unexpected request: {method} {url}")

    def post(self, url, **kwargs):
        self.calls.append(("POST_UPLOAD", url, kwargs))
        return FakeResponse({"success": True})


def test_facebook_supports_distinct_api_and_browser_auth_types():
    assert API_AUTH_TYPE in Config.PROFILE_AUTH_TYPES
    assert BROWSER_AUTH_TYPE in Config.PROFILE_AUTH_TYPES


def test_pages_list_never_returns_page_access_token():
    client = FacebookGraphClient(config=FakeConfig(), session=FakeSession())
    rows = client.list_pages(limit=10)
    assert rows == [{"id": "PAGE1", "name": "ATA", "tasks": ["CREATE_CONTENT"]}]
    assert "access_token" not in rows[0]


def test_publish_reel_runs_start_upload_finish_and_status(tmp_path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"video-bytes")
    session = FakeSession()
    client = FacebookGraphClient(config=FakeConfig(), session=session)

    result = client.publish_reel(
        "PAGE1",
        video,
        title="Title",
        description="Caption",
    )

    assert result["video_id"] == "VID1"
    assert result["page_id"] == "PAGE1"
    assert result["published"] is True

    upload_call = next(call for call in session.calls if call[0] == "POST_UPLOAD")
    assert upload_call[1] == "https://rupload.facebook.test/VID1"
    assert upload_call[2]["headers"]["Authorization"] == "OAuth PAGE_TOKEN"
    assert upload_call[2]["headers"]["file_size"] == str(video.stat().st_size)

    finish_call = [
        call
        for call in session.calls
        if call[0] == "POST"
        and call[1].endswith("/me/video_reels")
        and (call[2].get("data") or {}).get("upload_phase") == "finish"
    ][0]
    assert finish_call[2]["data"]["video_state"] == "PUBLISHED"
    assert finish_call[2]["data"]["title"] == "Title"
    assert finish_call[2]["data"]["description"] == "Caption"


class DeleteSession(FakeSession):
    def __init__(self, delete_payload):
        super().__init__()
        self.delete_payload = delete_payload

    def request(self, method, url, **kwargs):
        if method == "DELETE":
            self.calls.append((method, url, kwargs))
            return FakeResponse(self.delete_payload)
        return super().request(method, url, **kwargs)


def test_delete_reel_uses_page_token_on_video_node():
    session = DeleteSession({"success": True})
    client = FacebookGraphClient(config=FakeConfig(), session=session)

    result = client.delete_reel("PAGE1", "VID1")

    assert result == {"page_id": "PAGE1", "page_name": "ATA", "video_id": "VID1", "deleted": True}
    method, url, kwargs = session.calls[-1]
    assert (method, url) == ("DELETE", "https://graph.facebook.com/v24.0/VID1")
    assert kwargs["headers"]["Authorization"] == "Bearer PAGE_TOKEN"


def test_delete_reel_fails_when_graph_does_not_confirm():
    client = FacebookGraphClient(config=FakeConfig(), session=DeleteSession({"success": False}))
    with pytest.raises(ClientError, match="did not confirm deletion of video VID1"):
        client.delete_reel("PAGE1", "VID1")


def test_publish_reel_draft_sets_draft_state(tmp_path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"video-bytes")
    session = FakeSession()
    result = FacebookGraphClient(config=FakeConfig(), session=session).publish_reel(
        "PAGE1", video, draft=True
    )

    assert result["video_state"] == "DRAFT"
    assert result["published"] is False
    finish_call = [
        call for call in session.calls
        if call[0] == "POST" and (call[2].get("data") or {}).get("upload_phase") == "finish"
    ][0]
    assert finish_call[2]["data"]["video_state"] == "DRAFT"


def test_publish_reel_failure_after_start_names_created_video(tmp_path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"video-bytes")

    class FailingUploadSession(FakeSession):
        def post(self, url, **kwargs):
            return FakeResponse({"error": "boom"}, status_code=500)

    client = FacebookGraphClient(config=FakeConfig(), session=FailingUploadSession())
    with pytest.raises(ClientError, match=r"upload HTTP 500.*\[video_id=VID1\]"):
        client.publish_reel("PAGE1", video)


class FakeGraphClient:
    deleted = []

    def delete_reel(self, page_id, video_id):
        self.deleted.append((page_id, video_id))
        return {"page_id": page_id, "page_name": "ATA", "video_id": video_id, "deleted": True}


def test_reels_delete_refuses_without_yes(monkeypatch):
    monkeypatch.setattr(reels, "FacebookGraphClient", FakeGraphClient)
    FakeGraphClient.deleted = []
    result = CliRunner().invoke(reels.app, ["delete", "VID1", "--page", "PAGE1"])

    assert result.exit_code == 1
    assert "Refusing to delete Facebook Reel VID1 without confirmation" in result.output
    assert FakeGraphClient.deleted == []


def test_reels_delete_with_yes_prints_json(monkeypatch):
    monkeypatch.setattr(reels, "FacebookGraphClient", FakeGraphClient)
    FakeGraphClient.deleted = []
    result = CliRunner().invoke(reels.app, ["delete", "VID1", "--page", "PAGE1", "--yes"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["deleted"] is True
    assert FakeGraphClient.deleted == [("PAGE1", "VID1")]


def test_legacy_profiles_are_migrated_before_auth_commands(monkeypatch, tmp_path):
    profile = tmp_path / "default"
    profile.mkdir()
    (profile / ".env").write_text("ACTIVE=true\n")
    monkeypatch.setattr(config_mod, "get_profiles_base_dir", lambda _name: tmp_path)
    monkeypatch.setattr(config_mod, "resolve_tool_dir", lambda _name: tmp_path)
    monkeypatch.setattr(config_mod.BaseConfig, "__init__", lambda self, **_kwargs: None)

    config_mod.Config()

    assert dotenv_values(profile / ".env") == {
        "ACTIVE": "true",
        "AUTH_TYPE": BROWSER_AUTH_TYPE,
    }


def test_legacy_browser_credentials_move_to_secret_manager_before_config_load(monkeypatch, tmp_path):
    profile = tmp_path / "default"
    profile.mkdir()
    env_path = profile / ".env"
    env_path.write_text("ACTIVE=true\nUSERNAME=legacy-user\nPASSWORD=legacy-password\n")
    calls = []

    monkeypatch.setattr(config_mod, "get_profiles_base_dir", lambda _name: tmp_path)

    def fake_secret_exists(secret_name):
        calls.append(("has", secret_name, None))
        return False

    def fake_set_secret(secret_name, value, target_env_path):
        calls.append(("set", secret_name, value, target_env_path))

    monkeypatch.setattr(config_mod, "_secret_exists", fake_secret_exists)
    monkeypatch.setattr(config_mod, "_set_secret_value", fake_set_secret)

    config_mod.migrate_legacy_profiles()

    assert calls == [
        ("has", "facebook-username", None),
        ("set", "facebook-username", "legacy-user", env_path),
        ("has", "facebook-password", None),
        ("set", "facebook-password", "legacy-password", env_path),
    ]
    assert dotenv_values(env_path) == {
        "ACTIVE": "true",
        "AUTH_TYPE": BROWSER_AUTH_TYPE,
    }


def test_legacy_browser_credentials_preserve_literal_dollar_braces_before_scrubbing(
    monkeypatch, tmp_path
):
    profile = tmp_path / "default"
    profile.mkdir()
    env_path = profile / ".env"
    env_path.write_text(
        "ACTIVE=true\n"
        "USERNAME=legacy${UNSET}-user\n"
        "PASSWORD=legacy${UNSET}-password\n"
    )
    stored = []

    monkeypatch.setattr(config_mod, "get_profiles_base_dir", lambda _name: tmp_path)
    monkeypatch.setattr(config_mod, "_secret_exists", lambda _name: False)

    def fake_set_secret(secret_name, value, target_env_path):
        assert target_env_path == env_path
        assert "USERNAME=legacy${UNSET}-user" in env_path.read_text()
        assert "PASSWORD=legacy${UNSET}-password" in env_path.read_text()
        stored.append((secret_name, value))

    monkeypatch.setattr(config_mod, "_set_secret_value", fake_set_secret)

    config_mod.migrate_legacy_profiles()

    assert stored == [
        ("facebook-username", "legacy${UNSET}-user"),
        ("facebook-password", "legacy${UNSET}-password"),
    ]
    assert dotenv_values(env_path) == {
        "ACTIVE": "true",
        "AUTH_TYPE": BROWSER_AUTH_TYPE,
    }


def test_legacy_profile_uses_profile_scoped_secret_names(monkeypatch, tmp_path):
    profile = tmp_path / "work"
    profile.mkdir()
    env_path = profile / ".env"
    env_path.write_text(
        f"AUTH_TYPE={BROWSER_AUTH_TYPE}\nACTIVE=true\nUSERNAME=legacy-user\n"
    )
    calls = []

    monkeypatch.setattr(config_mod, "get_profiles_base_dir", lambda _name: tmp_path)
    monkeypatch.setattr(config_mod, "_secret_exists", lambda name: calls.append(name) or False)
    monkeypatch.setattr(config_mod, "_set_secret_value", lambda name, value, path: None)

    config_mod.migrate_legacy_profiles()

    assert calls == ["facebook-work-username"]
    assert dotenv_values(env_path) == {
        "AUTH_TYPE": BROWSER_AUTH_TYPE,
        "ACTIVE": "true",
    }


def test_blank_legacy_auth_type_is_replaced_once(monkeypatch, tmp_path):
    profile = tmp_path / "default"
    profile.mkdir()
    env_path = profile / ".env"
    env_path.write_text("ACTIVE=true\nAUTH_TYPE=\n")
    monkeypatch.setattr(config_mod, "get_profiles_base_dir", lambda _name: tmp_path)

    config_mod.migrate_legacy_profiles()

    assert dotenv_values(env_path)["AUTH_TYPE"] == BROWSER_AUTH_TYPE
    assert sum(line.startswith("AUTH_TYPE=") for line in env_path.read_text().splitlines()) == 1


def test_config_repairs_the_generated_default_profile_auth_type(monkeypatch, tmp_path):
    tool_dir = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(config_mod, "resolve_tool_dir", lambda _name: tool_dir)

    Config(profile_auth_type=BROWSER_AUTH_TYPE)

    env_path = tmp_path / "data" / "cli-tools" / "facebook" / "authentication_profiles" / "default" / ".env"
    assert dotenv_values(env_path)["AUTH_TYPE"] == BROWSER_AUTH_TYPE
    assert sum(line.startswith("AUTH_TYPE=") for line in env_path.read_text().splitlines()) == 1
