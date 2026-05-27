from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from click.exceptions import Exit

from cli_tools_shared.oauth import oauth_login
from cli_tools_shared.token_manager import TokenManager


class FakeTokenResponse:
    status_code = 200

    def json(self):
        return {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
        }


def test_oauth_login_uses_system_browser_and_pasted_redirect_url(monkeypatch):
    opened_urls = []
    token_requests = []
    saved_tokens = {}

    config = SimpleNamespace(
        access_token=None,
        token_expires_at=None,
        redirect_uri="https://example.com/callback",
        OAUTH_REDIRECT_URI="",
        OAUTH_PKCE=False,
        OAUTH_SCOPES=["profile", "post"],
        OAUTH_EXTRA_AUTH_PARAMS={},
        OAUTH_AUTH_URL="https://auth.example.com/oauth",
        OAUTH_TOKEN_URL="https://auth.example.com/token",
        OAUTH_TOKEN_AUTH="body",
        client_id="client-123",
        client_secret="secret-456",
        save_tokens=lambda access, refresh, expires_at: saved_tokens.update(
            {
                "access_token": access,
                "refresh_token": refresh,
                "expires_at": expires_at,
            }
        ),
    )

    monkeypatch.setattr(
        "cli_tools_shared.oauth.webbrowser.open",
        lambda url: opened_urls.append(url),
    )
    monkeypatch.setattr(
        "cli_tools_shared.oauth.typer.prompt",
        lambda prompt: "https://example.com/callback?code=auth-code-789",
    )

    def fake_post(url, headers, data):
        token_requests.append({"url": url, "headers": headers, "data": data})
        return FakeTokenResponse()

    monkeypatch.setattr("cli_tools_shared.oauth.requests.post", fake_post)

    oauth_login(config, force=True)

    assert len(opened_urls) == 1
    auth_query = parse_qs(urlparse(opened_urls[0]).query)
    assert auth_query["client_id"] == ["client-123"]
    assert auth_query["redirect_uri"] == ["https://example.com/callback"]
    assert auth_query["response_type"] == ["code"]
    assert auth_query["scope"] == ["profile post"]

    assert token_requests == [
        {
            "url": "https://auth.example.com/token",
            "headers": {"Content-Type": "application/x-www-form-urlencoded"},
            "data": {
                "grant_type": "authorization_code",
                "code": "auth-code-789",
                "redirect_uri": "https://example.com/callback",
                "client_id": "client-123",
                "client_secret": "secret-456",
            },
        }
    ]
    assert saved_tokens["access_token"] == "new-access-token"
    assert saved_tokens["refresh_token"] == "new-refresh-token"


def test_oauth_login_can_omit_redirect_uri_when_provider_uses_registered_callback(monkeypatch):
    opened_urls = []
    token_requests = []
    saved_tokens = {}

    config = SimpleNamespace(
        access_token=None,
        token_expires_at=None,
        redirect_uri=None,
        OAUTH_REDIRECT_URI="",
        OAUTH_REDIRECT_URI_REQUIRED=False,
        OAUTH_PKCE=False,
        OAUTH_SCOPES=["public"],
        OAUTH_EXTRA_AUTH_PARAMS={},
        OAUTH_AUTH_URL="https://auth.example.com/oauth",
        OAUTH_TOKEN_URL="https://auth.example.com/token",
        OAUTH_TOKEN_AUTH="body",
        client_id="client-123",
        client_secret="secret-456",
        save_tokens=lambda access, refresh, expires_at: saved_tokens.update(
            {
                "access_token": access,
                "refresh_token": refresh,
                "expires_at": expires_at,
            }
        ),
    )

    monkeypatch.setattr(
        "cli_tools_shared.oauth.webbrowser.open",
        lambda url: opened_urls.append(url),
    )
    monkeypatch.setattr(
        "cli_tools_shared.oauth.typer.prompt",
        lambda prompt: "https://example.com/callback?code=auth-code-789",
    )

    def fake_post(url, headers, data):
        token_requests.append({"url": url, "headers": headers, "data": data})
        return FakeTokenResponse()

    monkeypatch.setattr("cli_tools_shared.oauth.requests.post", fake_post)

    oauth_login(config, force=True)

    auth_query = parse_qs(urlparse(opened_urls[0]).query)
    assert "redirect_uri" not in auth_query
    assert "redirect_uri" not in token_requests[0]["data"]
    assert saved_tokens["access_token"] == "new-access-token"


def test_oauth_login_errors_when_pasted_redirect_has_no_code(monkeypatch):
    config = SimpleNamespace(
        access_token=None,
        token_expires_at=None,
        redirect_uri="https://example.com/callback",
        OAUTH_REDIRECT_URI="",
        OAUTH_PKCE=False,
        OAUTH_SCOPES=[],
        OAUTH_EXTRA_AUTH_PARAMS={},
        OAUTH_AUTH_URL="https://auth.example.com/oauth",
        OAUTH_TOKEN_URL="https://auth.example.com/token",
        OAUTH_TOKEN_AUTH="body",
        client_id="client-123",
        client_secret="secret-456",
    )

    monkeypatch.setattr("cli_tools_shared.oauth.webbrowser.open", lambda url: None)
    monkeypatch.setattr(
        "cli_tools_shared.oauth.typer.prompt",
        lambda prompt: "https://example.com/callback?error=access_denied",
    )

    with pytest.raises(Exit):
        oauth_login(config, force=True)


def test_oauth_login_reports_provider_error_redirect(monkeypatch, capsys):
    config = SimpleNamespace(
        access_token=None,
        token_expires_at=None,
        redirect_uri="https://example.com/callback",
        OAUTH_REDIRECT_URI="",
        OAUTH_PKCE=False,
        OAUTH_SCOPES=[],
        OAUTH_EXTRA_AUTH_PARAMS={},
        OAUTH_AUTH_URL="https://auth.example.com/oauth",
        OAUTH_TOKEN_URL="https://auth.example.com/token",
        OAUTH_TOKEN_AUTH="body",
        client_id="client-123",
        client_secret="secret-456",
    )

    monkeypatch.setattr("cli_tools_shared.oauth.webbrowser.open", lambda url: None)
    monkeypatch.setattr(
        "cli_tools_shared.oauth.typer.prompt",
        lambda prompt: "https://example.com/callback?error=invalid_scope&error_description=Scope+not+authorized",
    )

    with pytest.raises(Exit):
        oauth_login(config, force=True)

    captured = capsys.readouterr()
    assert "OAuth authorization failed: invalid_scope: Scope not authorized" in captured.err


def test_oauth_login_unescapes_html_entities_in_provider_error(monkeypatch, capsys):
    config = SimpleNamespace(
        access_token=None,
        token_expires_at=None,
        redirect_uri="https://example.com/callback",
        OAUTH_REDIRECT_URI="",
        OAUTH_PKCE=False,
        OAUTH_SCOPES=[],
        OAUTH_EXTRA_AUTH_PARAMS={},
        OAUTH_AUTH_URL="https://auth.example.com/oauth",
        OAUTH_TOKEN_URL="https://auth.example.com/token",
        OAUTH_TOKEN_AUTH="body",
        client_id="client-123",
        client_secret="secret-456",
    )

    monkeypatch.setattr("cli_tools_shared.oauth.webbrowser.open", lambda url: None)
    monkeypatch.setattr(
        "cli_tools_shared.oauth.typer.prompt",
        lambda prompt: "https://example.com/callback?error=invalid_scope&error_description=Scope+%26quot%3Bw_organization_social%26quot%3B+is+not+authorized",
    )

    with pytest.raises(Exit):
        oauth_login(config, force=True)

    captured = capsys.readouterr()
    assert 'OAuth authorization failed: invalid_scope: Scope "w_organization_social" is not authorized' in captured.err


def test_token_manager_refresh_includes_redirect_uri(monkeypatch):
    token_requests = []
    saved_tokens = {}

    config = SimpleNamespace(
        refresh_token="old-refresh-token",
        redirect_uri="https://example.com/callback",
        OAUTH_REDIRECT_URI="",
        OAUTH_TOKEN_URL="https://auth.example.com/token",
        OAUTH_TOKEN_AUTH="body",
        client_id="client-123",
        client_secret="secret-456",
        save_tokens=lambda access, refresh, expires_at: saved_tokens.update(
            {
                "access_token": access,
                "refresh_token": refresh,
                "expires_at": expires_at,
            }
        ),
    )

    def fake_post(url, headers, data):
        token_requests.append({"url": url, "headers": headers, "data": data})
        return FakeTokenResponse()

    monkeypatch.setattr("cli_tools_shared.token_manager.requests.post", fake_post)

    TokenManager(config).force_refresh()

    assert token_requests == [
        {
            "url": "https://auth.example.com/token",
            "headers": {"Content-Type": "application/x-www-form-urlencoded"},
            "data": {
                "grant_type": "refresh_token",
                "refresh_token": "old-refresh-token",
                "redirect_uri": "https://example.com/callback",
                "client_id": "client-123",
                "client_secret": "secret-456",
            },
        }
    ]
    assert saved_tokens["access_token"] == "new-access-token"
    assert saved_tokens["refresh_token"] == "new-refresh-token"


def test_token_manager_refresh_does_not_require_redirect_uri(monkeypatch):
    token_requests = []
    saved_tokens = {}

    config = SimpleNamespace(
        refresh_token="old-refresh-token",
        redirect_uri=None,
        OAUTH_REDIRECT_URI="",
        OAUTH_TOKEN_URL="https://auth.example.com/token",
        OAUTH_TOKEN_AUTH="body",
        client_id="client-123",
        client_secret="secret-456",
        save_tokens=lambda access, refresh, expires_at: saved_tokens.update(
            {
                "access_token": access,
                "refresh_token": refresh,
                "expires_at": expires_at,
            }
        ),
    )

    def fake_post(url, headers, data):
        token_requests.append({"url": url, "headers": headers, "data": data})
        return FakeTokenResponse()

    monkeypatch.setattr("cli_tools_shared.token_manager.requests.post", fake_post)

    TokenManager(config).force_refresh()

    assert token_requests == [
        {
            "url": "https://auth.example.com/token",
            "headers": {"Content-Type": "application/x-www-form-urlencoded"},
            "data": {
                "grant_type": "refresh_token",
                "refresh_token": "old-refresh-token",
                "client_id": "client-123",
                "client_secret": "secret-456",
            },
        }
    ]
    assert saved_tokens["access_token"] == "new-access-token"
    assert saved_tokens["refresh_token"] == "new-refresh-token"
