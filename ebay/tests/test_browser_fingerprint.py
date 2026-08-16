"""Browser fingerprint regression tests for eBay public pages."""

from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import ebay_cli.config as ebay_config
from cli_tools_shared.browser import BrowserHarnessService


def test_should_use_real_chrome_user_agent_when_headless(monkeypatch):
    expected = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    )
    monkeypatch.setattr(
        ebay_config,
        "derive_real_chrome_user_agent",
        lambda: expected,
        raising=False,
    )

    assert ebay_config.Config().browser_user_agent == expected
    assert "Headless" not in ebay_config.Config().browser_user_agent


def test_should_send_matching_real_chrome_fingerprint_when_headless(tmp_path):
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
    service = BrowserHarnessService("ebay-user-agent-e2e")
    try:
        service.browser_open(
            f"http://127.0.0.1:{server.server_port}/",
            headed=False,
            persistent_profile_dir=tmp_path / "profile",
            user_agent=ebay_config.Config().browser_user_agent,
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
