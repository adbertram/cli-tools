"""Unit tests for the Microworkers client's headless session-refresh gate.

The seam: every command that touches a page goes through
``MicroworkersClient._page()``, which calls the shared engine's
``ensure_fresh_session()`` once per client instance before the first
navigation. These tests run without a live browser or config: the client's
browser is replaced with a fake, so the gate's decision handling is verified
in isolation (no visible browser, no TTY reads).
"""

import pytest

from cli_tools_shared.auth import AuthResult

from microworkers_cli.client import ClientError, MicroworkersClient


class _FakePage:
    def __init__(self, url):
        self.url = url

    def wait_for_timeout(self, ms):
        pass


class _FakeBrowser:
    """Double for MicroworkersBrowser exposing only the used surface."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.ensure_calls = 0
        self.get_page_calls = 0
        self.close_calls = 0

    def ensure_fresh_session(self):
        self.ensure_calls += 1
        return self.outcome

    def get_page(self, url):
        self.get_page_calls += 1
        return _FakePage(url)

    def close(self):
        self.close_calls += 1


def _client_with(browser: _FakeBrowser) -> MicroworkersClient:
    # Bypass __init__ (which loads the real config) so the test needs no
    # host profile state; the gate only touches the injected browser.
    client = object.__new__(MicroworkersClient)
    client.config = None
    client._browser = browser
    client._refresh_checked = False
    return client


def test_page_raises_structured_reason_when_refresh_needs_human():
    outcome = AuthResult(
        authenticated=False,
        live_check=True,
        refreshed=False,
        needs_human=True,
        reason="reCAPTCHA challenge detected on the login page; a human must complete it",
    )
    browser = _FakeBrowser(outcome)
    client = _client_with(browser)

    with pytest.raises(ClientError, match="reCAPTCHA challenge detected"):
        with client._page("https://www.microworkers.com/jobs.php") as _page:
            pass  # pragma: no cover — the gate must raise before the body

    assert browser.ensure_calls == 1
    assert browser.get_page_calls == 0, "no page may open when the session cannot refresh"
    assert browser.close_calls == 1


def test_page_fails_when_refresh_cannot_run():
    outcome = AuthResult(
        authenticated=False,
        live_check=True,
        refreshed=False,
        needs_human=False,
        reason="declarative non-interactive login is not configured",
    )
    browser = _FakeBrowser(outcome)
    client = _client_with(browser)

    with pytest.raises(ClientError, match="could not be refreshed"):
        with client._page("https://www.microworkers.com/jobs.php") as _page:
            pass  # pragma: no cover

    assert browser.ensure_calls == 1
    assert browser.get_page_calls == 0


def test_page_proceeds_on_fresh_session_and_checks_once_per_client():
    browser = _FakeBrowser(AuthResult(authenticated=True, live_check=True, refreshed=False))
    client = _client_with(browser)

    with client._page("https://www.microworkers.com/jobs.php") as page:
        assert page.url == "https://www.microworkers.com/jobs.php"
    with client._page("https://www.microworkers.com/jobs.php?page=2") as page:
        assert page.url == "https://www.microworkers.com/jobs.php?page=2"

    assert browser.ensure_calls == 1, "the refresh gate runs once per client instance"
    assert browser.get_page_calls == 2
