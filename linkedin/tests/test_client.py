import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp
from types import SimpleNamespace

import pytest
import requests
from cli_tools_shared.exceptions import ClientError

import linkedin_cli.client as client_module
from linkedin_cli.client import CURRENT_MEMBER_PROFILE_URL, CURRENT_MEMBER_USERINFO_URL, LinkedInClient
from linkedin_cli.config import Config, TOKEN_INTROSPECTION_URL


class FakeResponse:
    def __init__(self, payload=None, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = str(payload)
        self.content = str(payload).encode() if payload else b""
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)


def config():
    return SimpleNamespace(
        access_token="token-123",
        base_url="https://api.linkedin.com/rest",
        linkedin_version="202604",
        storage_dir=mkdtemp(prefix="linkedin-test-cache-"),
        has_credentials=lambda: True,
        get_missing_credentials=lambda: [],
        has_api_credentials=lambda: True,
        get_missing_api_credentials=lambda: [],
    )


def post_payload(commentary="Launch update", lifecycle_state="PUBLISHED"):
    return {
        "id": "urn:li:share:1",
        "author": "urn:li:organization:123456",
        "commentary": commentary,
        "visibility": "PUBLIC",
        "lifecycleState": lifecycle_state,
        "distribution": {"feedDistribution": "MAIN_FEED"},
        "isReshareDisabledByAuthor": False,
        "createdAt": 1716030000000,
        "publishedAt": 1716030060000,
        "lastModifiedAt": 1716030120000,
    }


def assert_successful_mutation_invalidates_post_read_caches(monkeypatch, mutation):
    monkeypatch.setenv("CACHE_ENABLED", "true")
    test_config = config()
    session = FakeSession(
        [
            FakeResponse(post_payload(commentary="Before")),
            FakeResponse({"elements": [post_payload(commentary="Before")]}),
            mutation["response"],
            FakeResponse(post_payload(commentary="After")),
        ]
    )
    client = LinkedInClient(config=test_config, session=session)

    assert client.get_post(
        post_urn="urn:li:share:1",
        permission_author="urn:li:organization:123456",
    )["commentary"] == "Before"
    assert client.list_posts(author="urn:li:organization:123456", limit=10)[0]["commentary"] == "Before"
    assert client.search_posts(query="Before", author="urn:li:organization:123456")

    cache_dir = Path(test_config.storage_dir) / "cache"
    assert sorted(path.name.split("_", 2)[0] for path in cache_dir.glob("*.json")) == [
        "get",
        "list",
        "search",
    ]

    mutation["call"](client)

    assert not list(cache_dir.glob("get_post_*.json"))
    assert not list(cache_dir.glob("list_posts_*.json"))
    assert not list(cache_dir.glob("search_posts_*.json"))
    assert client.get_post(
        post_urn="urn:li:share:1",
        permission_author="urn:li:organization:123456",
    )["commentary"] == "After"
    assert [call["method"] for call in session.calls] == ["GET", "GET", mutation["method"], "GET"]


def test_create_post_invalidates_post_read_caches(monkeypatch):
    assert_successful_mutation_invalidates_post_read_caches(
        monkeypatch,
        {
            "method": "POST",
            "response": FakeResponse(
                {},
                status_code=201,
                headers={"x-restli-id": "urn:li:share:99"},
            ),
            "call": lambda client: client.create_post(
                commentary="New post",
                author="urn:li:organization:123456",
            ),
        },
    )


def test_update_post_invalidates_post_read_caches(monkeypatch):
    assert_successful_mutation_invalidates_post_read_caches(
        monkeypatch,
        {
            "method": "POST",
            "response": FakeResponse({}, status_code=204),
            "call": lambda client: client.update_post(
                post_urn="urn:li:share:1",
                commentary="Updated commentary",
                permission_author="urn:li:organization:123456",
            ),
        },
    )


def test_delete_post_invalidates_post_read_caches(monkeypatch):
    assert_successful_mutation_invalidates_post_read_caches(
        monkeypatch,
        {
            "method": "DELETE",
            "response": FakeResponse({}, status_code=204),
            "call": lambda client: client.delete_post(
                post_urn="urn:li:share:1",
                permission_author="urn:li:organization:123456",
            ),
        },
    )


def test_create_post_requires_author_and_returns_restli_id():
    session = FakeSession(
        [
            FakeResponse({}, status_code=201, headers={"x-restli-id": "urn:li:share:99"}),
        ]
    )
    client = LinkedInClient(config=config(), session=session)

    result = client.create_post(
        commentary="Hello LinkedIn",
        author="urn:li:person:abc123",
    )

    assert result["id"] == "urn:li:share:99"
    assert result["author"] == "urn:li:person:abc123"
    assert result["commentary"] == "Hello LinkedIn"
    assert session.calls[0]["json"]["distribution"]["feedDistribution"] == "MAIN_FEED"
    assert session.calls[0]["headers"]["Linkedin-Version"] == "202604"


def test_list_posts_normalizes_elements():
    session = FakeSession(
        [
            FakeResponse(
                {
                    "elements": [
                        {
                            "id": "urn:li:share:1",
                            "author": "urn:li:person:abc123",
                            "commentary": "Launch update",
                            "visibility": "PUBLIC",
                            "lifecycleState": "PUBLISHED",
                            "distribution": {"feedDistribution": "MAIN_FEED"},
                            "isReshareDisabledByAuthor": False,
                            "createdAt": 1716030000000,
                            "publishedAt": 1716030060000,
                            "lastModifiedAt": 1716030120000,
                        }
                    ]
                }
            )
        ]
    )
    client = LinkedInClient(config=config(), session=session)

    result = client.list_posts(author="urn:li:person:abc123", limit=5)

    assert result[0]["id"] == "urn:li:share:1"
    assert result[0]["content_type"] == "text"
    assert result[0]["visibility"] == "PUBLIC"
    assert session.calls[0]["params"] == {
        "q": "author",
        "author": "urn:li:person:abc123",
        "count": 5,
        "start": 0,
        "sortBy": "LAST_MODIFIED",
    }
    assert session.calls[0]["headers"]["X-RestLi-Method"] == "FINDER"


def test_list_posts_raises_clear_member_permission_error():
    session = FakeSession(
        [
            FakeResponse(
                {
                    "message": (
                        "Not enough permissions to access: "
                        "partnerApiPostsExternal.FINDER-author.20260401"
                    )
                },
                status_code=403,
            )
        ]
    )
    client = LinkedInClient(config=config(), session=session)

    with pytest.raises(ClientError) as excinfo:
        client.list_posts(author="urn:li:person:abc123", limit=1)

    message = str(excinfo.value)
    assert "list posts by author" in message
    assert "member author" in message
    assert "r_member_social" in message
    assert "MEMBER_SHARE_INFO" in message
    assert "r_dma_portability_3rd_party" in message
    assert "linkedin auth login --force" in message
    assert "w_member_social" in message


def test_list_posts_raises_clear_organization_permission_error():
    session = FakeSession(
        [
            FakeResponse(
                {
                    "message": (
                        "Not enough permissions to access: "
                        "partnerApiPostsExternal.FINDER-author.20260401"
                    )
                },
                status_code=403,
            )
        ]
    )
    client = LinkedInClient(config=config(), session=session)

    with pytest.raises(ClientError) as excinfo:
        client.list_posts(author="urn:li:organization:123456", limit=1)

    message = str(excinfo.value)
    assert "list posts by author" in message
    assert "organization or showcase-page author" in message
    assert "r_organization_social" in message
    assert "Community Management API or Advertising API approval" in message
    assert "linkedin auth login --force" in message


def test_get_post_raises_clear_member_permission_error_with_author_context():
    session = FakeSession(
        [
            FakeResponse(
                {
                    "message": (
                        "Not enough permissions to access: "
                        "partnerApiPostsExternal.GET.20260401"
                    )
                },
                status_code=403,
            )
        ]
    )
    client = LinkedInClient(config=config(), session=session)

    with pytest.raises(ClientError) as excinfo:
        client.get_post(
            post_urn="urn:li:share:1",
            permission_author="urn:li:person:abc123",
        )

    message = str(excinfo.value)
    assert "get post" in message
    assert "member author" in message
    assert "r_member_social" in message
    assert "MEMBER_SHARE_INFO" in message


def test_get_post_raises_clear_organization_permission_error_with_author_context():
    session = FakeSession(
        [
            FakeResponse(
                {
                    "message": (
                        "Not enough permissions to access: "
                        "partnerApiPostsExternal.GET.20260401"
                    )
                },
                status_code=403,
            )
        ]
    )
    client = LinkedInClient(config=config(), session=session)

    with pytest.raises(ClientError) as excinfo:
        client.get_post(
            post_urn="urn:li:share:1",
            permission_author="urn:li:organization:123456",
        )

    message = str(excinfo.value)
    assert "get post" in message
    assert "organization or showcase-page author" in message
    assert "r_organization_social" in message
    assert "Community Management API or Advertising API approval" in message


def test_non_posts_403_preserves_original_error():
    session = FakeSession([FakeResponse({"message": "Not enough permissions"}, status_code=403)])
    client = LinkedInClient(config=config(), session=session)

    with pytest.raises(ClientError, match="HTTP 403: Not enough permissions"):
        client._request("GET", CURRENT_MEMBER_PROFILE_URL, versioned=False)


def test_update_post_uses_partial_update_header():
    session = FakeSession([FakeResponse({}, status_code=204)])
    client = LinkedInClient(config=config(), session=session)

    result = client.update_post(
        post_urn="urn:li:share:12345",
        commentary="Updated commentary",
        permission_author="urn:li:organization:123456",
    )

    assert result == {
        "id": "urn:li:share:12345",
        "commentary": "Updated commentary",
        "updated": True,
    }
    assert session.calls[0]["method"] == "POST"
    assert session.calls[0]["headers"]["X-RestLi-Method"] == "PARTIAL_UPDATE"


def test_delete_post_uses_delete_header_and_permission_author():
    session = FakeSession([FakeResponse({}, status_code=204)])
    client = LinkedInClient(config=config(), session=session)

    result = client.delete_post(
        post_urn="urn:li:share:12345",
        permission_author="urn:li:person:abc123",
    )

    assert result == {
        "id": "urn:li:share:12345",
        "deleted": True,
    }
    assert session.calls[0]["method"] == "DELETE"
    assert session.calls[0]["headers"]["X-RestLi-Method"] == "DELETE"


def test_config_test_connection_uses_token_introspection(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeResponse(
            {
                "active": True,
                "status": "active",
                "auth_type": "3L",
                "scope": "w_member_social,r_liteprofile",
                "expires_at": 1750000000,
            }
        )

    monkeypatch.setattr("linkedin_cli.config.requests.post", fake_post)
    fake_config = SimpleNamespace(
        has_api_credentials=lambda: True,
        get_missing_api_credentials=lambda: [],
        client_id="client-id",
        client_secret="client-secret",
        access_token="access-token",
    )

    result = Config.test_connection(fake_config)

    assert captured["url"] == TOKEN_INTROSPECTION_URL
    assert captured["kwargs"]["data"] == {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "token": "access-token",
    }
    assert result == {
        "api_test": "passed",
        "token_status": "active",
        "auth_type": "3L",
        "scopes": ["w_member_social", "r_liteprofile"],
        "expires_at": datetime.fromtimestamp(1750000000, tz=UTC).isoformat(),
    }


def test_config_test_connection_reports_inactive_tokens(monkeypatch):
    def fake_post(url, **kwargs):
        return FakeResponse({"active": False, "status": "expired"})

    monkeypatch.setattr("linkedin_cli.config.requests.post", fake_post)
    fake_config = SimpleNamespace(
        has_api_credentials=lambda: True,
        get_missing_api_credentials=lambda: [],
        client_id="client-id",
        client_secret="client-secret",
        access_token="access-token",
    )

    result = Config.test_connection(fake_config)

    assert result == {"api_test": "failed: token is not active (expired)"}


def test_config_test_connection_reports_http_errors(monkeypatch):
    def fake_post(url, **kwargs):
        return FakeResponse("bad secret", status_code=401)

    monkeypatch.setattr("linkedin_cli.config.requests.post", fake_post)
    fake_config = SimpleNamespace(
        has_api_credentials=lambda: True,
        get_missing_api_credentials=lambda: [],
        client_id="client-id",
        client_secret="client-secret",
        access_token="access-token",
    )

    result = Config.test_connection(fake_config)

    assert result == {"api_test": "failed: HTTP 401: bad secret"}


def test_get_current_member_urn_uses_profile_api():
    session = FakeSession([FakeResponse({"id": "person123"})])
    client = LinkedInClient(config=config(), session=session)

    result = client.get_current_member_urn()

    assert result == "urn:li:person:person123"
    assert session.calls[0]["url"] == CURRENT_MEMBER_PROFILE_URL
    assert "Linkedin-Version" not in session.calls[0]["headers"]


def test_get_current_member_urn_falls_back_to_userinfo_when_profile_scope_is_missing():
    session = FakeSession(
        [
            FakeResponse({"message": "Not enough permissions"}, status_code=403),
            FakeResponse({"sub": "oidc-person-456"}),
        ]
    )
    client = LinkedInClient(config=config(), session=session)

    result = client.get_current_member_urn()

    assert result == "urn:li:person:oidc-person-456"
    assert session.calls[0]["url"] == CURRENT_MEMBER_PROFILE_URL
    assert session.calls[1]["url"] == CURRENT_MEMBER_USERINFO_URL
    assert "Linkedin-Version" not in session.calls[1]["headers"]


def test_get_current_member_urn_raises_clear_error_when_both_identity_endpoints_fail():
    session = FakeSession(
        [
            FakeResponse({"message": "Not enough permissions"}, status_code=403),
            FakeResponse({"message": "OIDC product disabled"}, status_code=403),
        ]
    )
    client = LinkedInClient(config=config(), session=session)

    with pytest.raises(
        ClientError,
        match="Pass --person urn:li:person:<id>, set LINKEDIN_PERSON_URN, enable the LinkedIn OpenID Connect product",
    ):
        client.get_current_member_urn()


VIDEO_URN = "urn:li:video:D5610AQFYNmb9_sKaEw"
OWNER = "urn:li:organization:123456"


def init_value(*, parts, captions=False, thumbnail=False):
    value = {
        "video": VIDEO_URN,
        "uploadToken": "token-abc",
        "uploadUrlsExpireAt": 1,
        "uploadInstructions": [
            {"firstByte": first, "lastByte": last, "uploadUrl": f"https://upload.example/part{i}"}
            for i, (first, last) in enumerate(parts)
        ],
    }
    if captions:
        value["captionsUploadUrl"] = "https://upload.example/captions"
    if thumbnail:
        value["thumbnailUploadUrl"] = "https://upload.example/thumb"
    return {"value": value}


def available_video(**extra):
    return {"id": VIDEO_URN, "status": "AVAILABLE", **extra}


def test_upload_video_runs_initialize_parts_captions_finalize_and_poll(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"0123456789")
    captions = tmp_path / "clip.srt"
    captions.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n")
    session = FakeSession(
        [
            FakeResponse(init_value(parts=[(0, 5), (6, 9)], captions=True)),
            FakeResponse({}, headers={"ETag": '"etag-one"'}),
            FakeResponse({}, headers={"etag": "etag-two"}),
            FakeResponse({}, status_code=201),
            FakeResponse({}),
            FakeResponse({"id": VIDEO_URN, "status": "PROCESSING"}),
            FakeResponse(available_video(captions="https://dms.example/captions")),
        ]
    )
    client = LinkedInClient(config=config(), session=session)


    sleeps = []
    monkeypatch.setattr(client_module.time, "sleep", sleeps.append)
    video_record = client.upload_video(owner=OWNER, video_path=video, captions_path=captions)

    assert video_record["status"] == "AVAILABLE"
    calls = session.calls
    assert calls[0]["url"].endswith("/videos?action=initializeUpload")
    assert calls[0]["json"] == {
        "initializeUploadRequest": {
            "owner": OWNER,
            "fileSizeBytes": 10,
            "uploadCaptions": True,
            "uploadThumbnail": False,
        }
    }
    assert calls[0]["headers"]["Linkedin-Version"] == "202604"
    assert (calls[1]["method"], calls[1]["url"], calls[1]["data"]) == (
        "PUT",
        "https://upload.example/part0",
        b"012345",
    )
    assert (calls[2]["url"], calls[2]["data"]) == ("https://upload.example/part1", b"6789")
    assert "Authorization" not in calls[1]["headers"]
    assert calls[1]["headers"] == {"Content-Type": "application/octet-stream"}
    assert calls[3]["url"] == "https://upload.example/captions"
    assert json.loads(calls[3]["data"]["metadata"])["format"] == "SRT"
    assert json.loads(calls[3]["data"]["metadata"])["transcriptType"] == "CLOSED_CAPTION"
    assert calls[3]["files"]["file"][0] == "clip.srt"
    assert "Authorization" not in calls[3]["headers"]
    assert calls[4]["url"].endswith("/videos?action=finalizeUpload")
    assert calls[4]["json"] == {
        "finalizeUploadRequest": {
            "video": VIDEO_URN,
            "uploadToken": "token-abc",
            "uploadedPartIds": ["etag-one", "etag-two"],
        }
    }
    assert calls[5]["url"].endswith("/videos/urn%3Ali%3Avideo%3AD5610AQFYNmb9_sKaEw")
    assert sleeps == [client_module.VIDEO_POLL_INTERVAL_SECONDS]


def test_upload_video_sends_thumbnail_with_still_image_header(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"abcd")
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"jpg-bytes")
    session = FakeSession(
        [
            FakeResponse(init_value(parts=[(0, 3)], thumbnail=True)),
            FakeResponse({}, headers={"ETag": "e1"}),
            FakeResponse({}, status_code=201),
            FakeResponse({}),
            FakeResponse(available_video()),
        ]
    )
    client = LinkedInClient(config=config(), session=session)

    client.upload_video(owner=OWNER, video_path=video, thumbnail_path=thumb)

    assert session.calls[0]["json"]["initializeUploadRequest"]["uploadThumbnail"] is True
    assert session.calls[2]["url"] == "https://upload.example/thumb"
    assert session.calls[2]["data"] == b"jpg-bytes"
    assert session.calls[2]["headers"]["media-type-family"] == "STILLIMAGE"


def test_upload_video_fails_when_part_upload_returns_no_etag(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"abcd")
    session = FakeSession([FakeResponse(init_value(parts=[(0, 3)])), FakeResponse({})])
    client = LinkedInClient(config=config(), session=session)

    with pytest.raises(ClientError, match="did not return an ETag"):
        client.upload_video(owner=OWNER, video_path=video)


def test_wait_for_video_raises_on_processing_failure():
    session = FakeSession(
        [FakeResponse({"status": "PROCESSING_FAILED", "processingFailureReason": "bad codec"})]
    )
    client = LinkedInClient(config=config(), session=session)

    with pytest.raises(ClientError, match="failed processing: bad codec"):
        client.wait_for_video(VIDEO_URN, timeout=30)


def test_wait_for_video_times_out(monkeypatch):

    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: None)
    session = FakeSession([FakeResponse({"status": "PROCESSING"})])
    client = LinkedInClient(config=config(), session=session)

    with pytest.raises(ClientError, match="still PROCESSING after 0 seconds"):
        client.wait_for_video(VIDEO_URN, timeout=0)


def test_create_video_post_publishes_media_content_and_returns_url(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"abcd")
    session = FakeSession(
        [
            FakeResponse(init_value(parts=[(0, 3)])),
            FakeResponse({}, headers={"ETag": "e1"}),
            FakeResponse({}),
            FakeResponse(available_video()),
            FakeResponse({}, status_code=201, headers={"x-restli-id": "urn:li:share:77"}),
        ]
    )
    client = LinkedInClient(config=config(), session=session)

    result = client.create_video_post(
        commentary="Watch this",
        author=OWNER,
        video_path=video,
        title="Short title",
    )

    post_call = session.calls[-1]
    assert post_call["url"].endswith("/posts")
    assert post_call["json"]["content"] == {
        "media": {"id": VIDEO_URN, "title": "Short title"}
    }
    assert post_call["json"]["author"] == OWNER
    assert post_call["json"]["lifecycleState"] == "PUBLISHED"
    assert result["id"] == "urn:li:share:77"
    assert result["url"] == "https://www.linkedin.com/feed/update/urn:li:share:77/"
    assert result["video"] == VIDEO_URN
    assert result["captions_attached"] is False


def test_lookup_organization_resolves_vanity_name():
    session = FakeSession(
        [
            FakeResponse(
                {
                    "elements": [
                        {
                            "id": 27025192,
                            "vanityName": "atalearning",
                            "localizedName": "ATA Learning",
                            "localizedWebsite": "https://adamtheautomator.com",
                        }
                    ]
                }
            )
        ]
    )
    client = LinkedInClient(config=config(), session=session)

    result = client.lookup_organization("atalearning")

    assert result == {
        "urn": "urn:li:organization:27025192",
        "id": 27025192,
        "vanity_name": "atalearning",
        "name": "ATA Learning",
        "website": "https://adamtheautomator.com",
    }
    assert session.calls[0]["url"] == "https://api.linkedin.com/v2/organizations"
    assert session.calls[0]["params"] == {"q": "vanityName", "vanityName": "atalearning"}
    assert session.calls[0]["headers"]["Linkedin-Version"] == "202604"


def test_lookup_organization_rejects_no_match():
    session = FakeSession([FakeResponse({"elements": []})])
    client = LinkedInClient(config=config(), session=session)

    with pytest.raises(ClientError, match="got 0"):
        client.lookup_organization("nope")


def test_video_poll_interval_is_two_seconds():
    assert client_module.VIDEO_POLL_INTERVAL_SECONDS == 2.0


def test_post_is_never_retried_on_5xx(monkeypatch):
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: None)
    session = FakeSession([FakeResponse({"message": "Gateway Timeout"}, status_code=504)])
    client = LinkedInClient(config=config(), session=session)

    with pytest.raises(ClientError, match="HTTP 504"):
        client.create_post(commentary="hi", author=OWNER)

    assert [c["method"] for c in session.calls] == ["POST"]


def test_post_is_never_retried_on_connection_error(monkeypatch):
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: None)

    class ResettingSession:
        calls = 0

        def request(self, method, url, **kwargs):
            self.calls += 1
            raise requests.exceptions.ConnectionError("RemoteDisconnected")

    session = ResettingSession()
    client = LinkedInClient(config=config(), session=session)

    with pytest.raises(ClientError, match="after 1 attempts"):
        client.create_post(commentary="hi", author=OWNER)

    assert session.calls == 1


def test_get_is_retried_on_5xx(monkeypatch):
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: None)
    session = FakeSession(
        [FakeResponse({"message": "Bad Gateway"}, status_code=502), FakeResponse({"id": "urn:li:video:V", "status": "AVAILABLE"})]
    )
    client = LinkedInClient(config=config(), session=session)

    assert client.get_video("urn:li:video:V")["status"] == "AVAILABLE"
    assert [c["method"] for c in session.calls] == ["GET", "GET"]


def test_part_upload_put_is_retried_on_5xx(monkeypatch):
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: None)
    session = FakeSession([FakeResponse({}, status_code=503), FakeResponse({}, headers={"ETag": '"e1"'})])
    client = LinkedInClient(config=config(), session=session)

    client._upload_part("https://upload.example/1", b"abcd", {})

    assert [c["method"] for c in session.calls] == ["PUT", "PUT"]


def test_every_request_has_a_finite_timeout(monkeypatch):
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: None)
    session = FakeSession(
        [
            FakeResponse({"id": "urn:li:video:V", "status": "AVAILABLE"}),
            FakeResponse({}, status_code=201, headers={"x-restli-id": "urn:li:share:1"}),
            FakeResponse({}, headers={"ETag": '"e1"'}),
        ]
    )
    client = LinkedInClient(config=config(), session=session)

    client.get_video("urn:li:video:V")
    client.create_post(commentary="hi", author=OWNER)
    client._upload_part("https://upload.example/1", b"abcd", {})

    timeouts = [c["timeout"] for c in session.calls]
    assert all(t is not None and t > 0 for t in timeouts)
    assert timeouts[2] == client_module.UPLOAD_TIMEOUT_SECONDS
