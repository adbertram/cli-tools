import hashlib

from tiktok_cli.config import API_AUTH_TYPE, BROWSER_AUTH_TYPE, Config
from tiktok_cli.oauth import generate_tiktok_pkce_pair
from tiktok_cli.posting import TikTokPostingClient, build_chunk_plan


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload or {}
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = str(self._payload)

    def json(self):
        return self._payload


class FakeConfig:
    access_token = "ACCESS"
    refresh_token = "REFRESH"
    token_expires_at = "99999999999"
    client_key = "KEY"
    client_secret = "SECRET"
    token_url = "https://open.tiktokapis.com/v2/oauth/token/"
    api_base_url = "https://open.tiktokapis.com"

    def save_tokens(self, access_token, refresh_token, expires_at):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_expires_at = expires_at

    def _set(self, key, value):
        setattr(self, key.lower(), value)


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if url.endswith("/creator_info/query/"):
            return FakeResponse({
                "data": {
                    "creator_username": "adam",
                    "privacy_level_options": ["SELF_ONLY", "PUBLIC_TO_EVERYONE"],
                    "comment_disabled": False,
                    "duet_disabled": False,
                    "stitch_disabled": False,
                },
                "error": {"code": "ok"},
            })
        if url.endswith("/video/init/"):
            return FakeResponse({
                "data": {
                    "publish_id": "PUB1",
                    "upload_url": "https://upload.tiktok.test/video",
                },
                "error": {"code": "ok"},
            })
        if url.endswith("/status/fetch/"):
            return FakeResponse({
                "data": {"status": "PUBLISH_COMPLETE", "uploaded_bytes": 11},
                "error": {"code": "ok"},
            })
        raise AssertionError(f"unexpected POST {url}")

    def put(self, url, **kwargs):
        self.calls.append(("PUT", url, kwargs))
        return FakeResponse(status_code=201)


def test_tiktok_supports_distinct_api_and_browser_profiles():
    assert API_AUTH_TYPE in Config.PROFILE_AUTH_TYPES
    assert BROWSER_AUTH_TYPE in Config.PROFILE_AUTH_TYPES


def test_tiktok_pkce_uses_hex_sha256():
    verifier, challenge = generate_tiktok_pkce_pair()
    assert len(verifier) >= 43
    assert challenge == hashlib.sha256(verifier.encode("ascii")).hexdigest()
    assert len(challenge) == 64


def test_chunk_plan_matches_tiktok_trailing_chunk_rule():
    chunk_size, ranges = build_chunk_plan(50_000_123)
    assert chunk_size == 50_000_123
    assert ranges == [(0, 50_000_122)]

    chunk_size, ranges = build_chunk_plan(70_000_123)
    assert chunk_size == 10_000_000
    assert len(ranges) == 7
    assert ranges[-1] == (60_000_000, 70_000_122)


def test_publish_video_uses_creator_info_init_upload_and_status(tmp_path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"hello world")
    session = FakeSession()
    client = TikTokPostingClient(config=FakeConfig(), session=session)

    result = client.publish_video(
        video,
        title="Caption",
        privacy_level="SELF_ONLY",
        is_aigc=True,
    )

    assert result["publish_id"] == "PUB1"
    assert result["status"] == "PUBLISH_COMPLETE"

    init_call = next(
        call for call in session.calls
        if call[0] == "POST" and call[1].endswith("/video/init/")
    )
    body = init_call[2]["json"]
    assert body["post_info"]["title"] == "Caption"
    assert body["post_info"]["is_aigc"] is True
    assert body["source_info"]["source"] == "FILE_UPLOAD"
    assert body["source_info"]["total_chunk_count"] == 1

    upload_call = next(call for call in session.calls if call[0] == "PUT")
    assert upload_call[2]["headers"]["Content-Range"] == "bytes 0-10/11"
    assert upload_call[2]["headers"]["Content-Type"] == "video/mp4"
