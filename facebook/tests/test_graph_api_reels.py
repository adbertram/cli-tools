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
