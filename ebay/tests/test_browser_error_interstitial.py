"""Regression tests for eBay's error/bot-challenge interstitial handling.

Root cause covered here: eBay intermittently serves a generic error page
titled "🐴 Error Page | eBay" AT THE REQUESTED URL instead of the real
content (observed live 2026-08-27 on a completed-comps search:
``ebay listings search "LEGO 7094 King's Castle Siege" --sold --us-only``).
Nothing detected or retried that interstitial, so the search's
``_raise_for_search_blocker`` fell through to "eBay search results container
was not found on the page" and the command exited 1 on a transient wall that
clears on reload.

The fix (mirroring the bricklink CLI's AWS-WAF handling in
``bricklink_cli/browser_runtime.py::_get_page_for``) lives centrally in
``EbayBrowser.get_page``: detect the interstitial by its title, reload the
requested URL with a growing backoff up to ``ERROR_PAGE_MAX_RETRIES`` times,
and raise a descriptive error only when it persists. Every browser-backed
ebay command funnels through ``get_page``, so all of them inherit the retry.
"""

import pytest

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError

from ebay_cli.browser import EbayBrowser


SEARCH_URL = (
    "https://www.ebay.com/sch/i.html?_nkw=LEGO+7094&LH_Complete=1&LH_Sold=1"
)
ERROR_TITLE = "\U0001f434 Error Page | eBay"
RESULTS_TITLE = "LEGO 7094 for sale | eBay"
CAPTCHA_URL = "https://www.ebay.com/splashui/captcha?ap=1&appName=orch"


class FakePage:
    """Stand-in for BrowserHarnessService driven by a scripted title sequence.

    ``evaluate('document.title')`` consumes one title per detection probe
    (holding the last one), so a test can script "error, error, real page".
    """

    def __init__(self, titles, url=SEARCH_URL, goto_url=None):
        self._titles = list(titles)
        self.url = url
        self._goto_url = goto_url
        self.goto_calls = []
        self.waits = []

    def evaluate(self, script):
        assert script == "document.title"
        if len(self._titles) > 1:
            return self._titles.pop(0)
        return self._titles[0]

    def goto(self, url, wait_until=None):
        self.goto_calls.append(url)
        if self._goto_url is not None:
            self.url = self._goto_url

    def wait_for_timeout(self, ms):
        self.waits.append(ms)


class BrokenTitlePage(FakePage):
    def evaluate(self, script):
        raise RuntimeError("evaluate failed mid-navigation")


def _browser():
    from unittest.mock import MagicMock

    return EbayBrowser(MagicMock())


@pytest.fixture
def stub_base_get_page(monkeypatch):
    """Replace the shared base get_page with one returning a scripted page."""

    def install(page):
        monkeypatch.setattr(
            BrowserAutomation, "get_page", lambda self, url=None: page
        )
        return page

    return install


# ---- detection ----

def test_error_page_title_is_detected():
    page = FakePage([ERROR_TITLE])
    assert _browser()._detect_error_page(page) is True


def test_real_results_title_is_not_detected():
    page = FakePage([RESULTS_TITLE])
    assert _browser()._detect_error_page(page) is False


def test_title_probe_failure_is_not_detected():
    """A transient mid-navigation evaluate failure is not interstitial proof."""
    page = BrokenTitlePage([ERROR_TITLE])
    assert _browser()._detect_error_page(page) is False


# ---- retry loop ----

def test_get_page_reloads_until_error_page_clears(stub_base_get_page):
    page = stub_base_get_page(FakePage([ERROR_TITLE, ERROR_TITLE, RESULTS_TITLE]))
    result = _browser().get_page(SEARCH_URL)
    assert result is page
    assert page.goto_calls == [SEARCH_URL, SEARCH_URL]
    # Growing backoff between reloads.
    assert page.waits == [2000, 4000]


def test_get_page_passes_clean_page_through_without_reload(stub_base_get_page):
    page = stub_base_get_page(FakePage([RESULTS_TITLE]))
    assert _browser().get_page(SEARCH_URL) is page
    assert page.goto_calls == []
    assert page.waits == []


def test_get_page_reloads_current_url_when_no_url_requested(stub_base_get_page):
    """get_page(None) (auth-check path) still retries, using the page's URL."""
    page = stub_base_get_page(FakePage([ERROR_TITLE, RESULTS_TITLE]))
    assert _browser().get_page() is page
    assert page.goto_calls == [SEARCH_URL]


def test_get_page_raises_after_bounded_retries(stub_base_get_page):
    page = stub_base_get_page(FakePage([ERROR_TITLE]))
    with pytest.raises(BrowserAutomationError) as excinfo:
        _browser().get_page(SEARCH_URL)
    message = str(excinfo.value)
    assert "did not clear" in message
    assert SEARCH_URL in message
    assert page.goto_calls == [SEARCH_URL] * EbayBrowser.ERROR_PAGE_MAX_RETRIES
    assert page.waits == [2000, 4000, 6000, 8000]


def test_reload_landing_on_captcha_raises_auth_challenge(stub_base_get_page):
    """A reload that lands on eBay's captcha wall must raise the shared
    auth-challenge error, not keep reloading the captcha."""
    page = stub_base_get_page(
        FakePage([ERROR_TITLE, ERROR_TITLE], goto_url=CAPTCHA_URL)
    )
    with pytest.raises(BrowserAutomationError) as excinfo:
        _browser().get_page(SEARCH_URL)
    assert "challenge" in str(excinfo.value)
    assert page.goto_calls == [SEARCH_URL]
