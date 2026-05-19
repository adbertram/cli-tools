from datetime import UTC, datetime
from tempfile import mkdtemp
from types import SimpleNamespace

import pytest
from cli_tools_shared.exceptions import ClientError

from linkedin_cli.client import CURRENT_MEMBER_PROFILE_URL, CURRENT_MEMBER_USERINFO_URL, LinkedInClient
from linkedin_cli.config import Config, TOKEN_INTROSPECTION_URL


class FakeResponse:
    def __init__(self, payload=None, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = str(payload)
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
