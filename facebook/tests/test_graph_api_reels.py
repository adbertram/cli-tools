import json

import pytest
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

    config_mod.migrate_legacy_profiles()

    assert (profile / ".env").read_text() == f"AUTH_TYPE={BROWSER_AUTH_TYPE}\nACTIVE=true\n"
