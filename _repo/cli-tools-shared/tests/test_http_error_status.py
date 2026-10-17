"""Main-document HTTP-status detection on BrowserAutomation.get_page.

A site that answers HTTP 429 (rate limit) or >=500 (outage) renders a
normal-looking error document at the requested URL. A scraper that only reads
the DOM records that error page as valid (often empty) content -- silent data
loss. The motivating live case (microworkers.com, 2026-09-04): /jobs.php
answered 429, the task-list extractor found zero rows, and discovery logged an
``ok`` envelope with 0 tasks while ~1600 were actually available.

These tests pin the generic engine: get_page raises only on 429 / >=500 (4xx
and unreadable statuses pass through), and a tool can opt out with
``HTTP_ERROR_STATUS_RAISE = False``.
"""

import pytest

from cli_tools_shared.auth import (
    HTTP_ERROR_STATUS_JS,
    BrowserAutomation,
    BrowserAutomationError,
)
from cli_tools_shared.exceptions import ClientError


class FakePage:
    """Scripted page: ``evaluate`` returns the configured status, or the URL
    when the script asks for ``location.href``."""

    def __init__(self, status):
        self.status = status

    def evaluate(self, js: str):
        if "location.href" in js:
            return "https://example.com/results"
        return self.status


class ProbeBrowser(BrowserAutomation):
    """BrowserAutomation whose navigation is scripted to one FakePage."""

    HTTP_ERROR_STATUS_RAISE = True

    def __init__(self, status):
        self._fake = FakePage(status)
        super().__init__(object())  # config unused on this probe path

    def _navigate_page(self, url: str = None):
        return self._fake

    def _resolve_interstitials(self, page, url: str = None):
        return page


class OptOutBrowser(ProbeBrowser):
    HTTP_ERROR_STATUS_RAISE = False


@pytest.mark.parametrize("status", [200, 404, 403, 418])
def test_healthy_and_other_4xx_pages_pass_through(status):
    page = ProbeBrowser(status).get_page("https://example.com/results")
    assert page.status == status


def test_status_readable_via_navigation_timing_js():
    # The evaluate contract: JS returns the navigation entry's responseStatus
    # or None (0/undefined when unreadable). FakePage status None models that.
    assert "getEntriesByType('navigation')" in HTTP_ERROR_STATUS_JS
    assert ProbeBrowser(200).get_page(None).status == 200
    assert ProbeBrowser(None).get_page(None).status is None


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_rate_limit_and_5xx_raise_naming_status(status):
    with pytest.raises(BrowserAutomationError) as excinfo:
        ProbeBrowser(status).get_page("https://example.com/results")
    assert f"HTTP {status}" in str(excinfo.value)
    assert "rate limiting or an outage" in str(excinfo.value)
    assert "https://example.com/results" in str(excinfo.value)


def test_opt_out_returns_error_page_unchanged():
    browser = OptOutBrowser(429)
    assert browser.get_page("https://example.com/results").status == 429


def test_default_raise_is_on():
    assert BrowserAutomation.HTTP_ERROR_STATUS_RAISE is True


def test_browser_errors_route_through_client_error_handling():
    # Browser failures (including 429/5xx pages) print as one-line errors via
    # the shared run_app path instead of escaping as tracebacks.
    assert issubclass(BrowserAutomationError, ClientError)
