from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from cli_tools_shared.browser import BrowserHarnessService
from facebook_cli.browser import FacebookBrowser
from facebook_cli.config import Config


def test_facebook_browser_keeps_auth_lifecycle_declarative():
    assert FacebookBrowser.SESSION_NAME == "facebook"
    assert FacebookBrowser.LOGIN_URL == "https://www.facebook.com/login"
    assert FacebookBrowser.AUTH_CHECK_URL == "https://m.facebook.com/"
    assert FacebookBrowser.AUTH_COOKIE_PATTERNS == ["c_user"]
    assert FacebookBrowser.MANUAL_LOGIN is True


def test_facebook_headless_automation_uses_real_chrome_user_agent(monkeypatch):
    expected = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/149.0.7827.201 Safari/537.36"
    )
    monkeypatch.setattr(
        "facebook_cli.config.derive_real_chrome_user_agent",
        lambda: expected,
    )

    assert Config().browser_user_agent == expected
    assert "Headless" not in Config().browser_user_agent


def test_facebook_headless_browser_sends_matching_real_chrome_fingerprint(tmp_path):
    observed = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            observed["user-agent"] = self.headers["User-Agent"]
            observed["sec-ch-ua"] = self.headers["sec-ch-ua"]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    service = BrowserHarnessService("facebook-user-agent-e2e")
    try:
        service.browser_open(
            f"http://127.0.0.1:{server.server_port}/",
            headed=False,
            persistent_profile_dir=tmp_path / "profile",
            user_agent=Config().browser_user_agent,
        )
    finally:
        service.browser_close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert "Headless" not in observed["user-agent"]
    assert "Chrome/" in observed["user-agent"]
    assert "Headless" not in observed["sec-ch-ua"]
    assert "Google Chrome" in observed["sec-ch-ua"]
