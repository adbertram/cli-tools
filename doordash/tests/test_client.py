"""DoorDash client regressions."""

from doordash_cli.client import DoordashClient


def test_http_client_adds_csrf_headers_from_browser_cookies(monkeypatch):
    client = DoordashClient()

    monkeypatch.setattr(
        client,
        "_load_session_cookies",
        lambda: {
            "ddweb_session_id": "session",
            "XSRF-TOKEN": "csrf-token",
        },
    )

    http_client = client._create_http_client()

    assert http_client.headers["x-csrf-token"] == "csrf-token"
    assert http_client.headers["x-csrftoken"] == "csrf-token"
    assert http_client.headers["x-xsrf-token"] == "csrf-token"
    assert http_client.cookies.get("ddweb_session_id") == "session"
