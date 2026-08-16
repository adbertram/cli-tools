"""Cold-profile readiness tests for eBay public search."""

import pytest
from cli_tools_shared.browser import BrowserHarnessError

from ebay_cli.browser import BrowserError
from ebay_cli.browser_client import (
    EXTRACT_JS,
    PAGE_STATE_JS,
    SEARCH_RESULTS_TIMEOUT_MS,
    SELECTORS,
    EbayBrowserClient,
)


HOMEPAGE_SEARCH_INPUT = 'input[name="_nkw"]'


class _ColdProfileBrowser:
    def __init__(self):
        self.events = []

    def get_page(self, url):
        self.events.append(("get_page", url))
        return self

    def wait_for_selector(self, selector, *, state, timeout):
        self.events.append(("wait_for_selector", selector, state, timeout))
        return object()

    def evaluate(self, script, params=None):
        if script != EXTRACT_JS:
            raise AssertionError("The search used an unexpected script")
        return [
            {
                "item_id": "127992747834",
                "title": "LEGO White Technic Panel",
                "price": "2.95",
                "currency": "USD",
                "shipping_price": "6.25",
                "status": "active",
                "date_sold": None,
                "time_left": None,
                "condition": "Pre-Owned",
                "format": "Buy It Now",
                "bids": None,
                "seller": "seller",
                "url": "https://www.ebay.com/itm/127992747834",
                "image_url": None,
            }
        ]

    def locator(self, selector):
        return self

    def count(self):
        return 0


class _CompletedSearchBrowser(_ColdProfileBrowser):
    def __init__(self, authenticated):
        super().__init__()
        self.authenticated = authenticated

    def is_authenticated(self):
        self.events.append(("is_authenticated",))
        return self.authenticated


class _PersistentHomepageChallenge(_ColdProfileBrowser):
    def wait_for_selector(self, selector, *, state, timeout):
        self.events.append(("wait_for_selector", selector, state, timeout))
        raise BrowserHarnessError("selector timed out")

    def evaluate(self, script, params=None):
        if script == PAGE_STATE_JS:
            return {
                "url": "https://www.ebay.com/splashui/challenge?ap=1",
                "title": "🐴 Pardon Our Interruption...",
                "body_text_snippet": "Pardon Our Interruption",
                "container_exists": False,
                "heading_text": None,
                "zero_results": False,
            }
        return super().evaluate(script, params)


def test_should_wait_for_homepage_readiness_before_search_navigation():
    browser = _ColdProfileBrowser()
    client = EbayBrowserClient(config=object())
    client._browser = browser

    results = client.search_active("lego", limit=1)

    assert [result.item_id for result in results] == ["127992747834"]
    assert browser.events[:4] == [
        ("get_page", "https://www.ebay.com"),
        (
            "wait_for_selector",
            HOMEPAGE_SEARCH_INPUT,
            "attached",
            SEARCH_RESULTS_TIMEOUT_MS,
        ),
        ("get_page", browser.events[2][1]),
        (
            "wait_for_selector",
            SELECTORS["item"],
            "attached",
            SEARCH_RESULTS_TIMEOUT_MS,
        ),
    ]
    assert browser.events[2][1].startswith("https://www.ebay.com/sch/i.html?")


def test_should_stop_before_search_when_homepage_challenge_persists():
    browser = _PersistentHomepageChallenge()
    client = EbayBrowserClient(config=object())
    client._browser = browser

    with pytest.raises(BrowserError, match="CAPTCHA/security-verification"):
        client.search_active("lego", limit=1)

    assert browser.events == [
        ("get_page", "https://www.ebay.com"),
        (
            "wait_for_selector",
            HOMEPAGE_SEARCH_INPUT,
            "attached",
            SEARCH_RESULTS_TIMEOUT_MS,
        ),
    ]


def test_completed_search_should_require_authenticated_browser_session():
    browser = _CompletedSearchBrowser(authenticated=False)
    client = EbayBrowserClient(config=object())
    client._browser = browser

    with pytest.raises(BrowserError, match="No browser session found"):
        client.search_completed("lego", sold_only=True, limit=1)

    assert browser.events == [("is_authenticated",)]


def test_active_search_should_not_check_browser_session():
    browser = _ColdProfileBrowser()
    client = EbayBrowserClient(config=object())
    client._browser = browser

    results = client.search_active("lego", limit=1)

    assert [result.item_id for result in results] == ["127992747834"]


def test_authenticated_completed_search_should_check_session_before_homepage():
    browser = _CompletedSearchBrowser(authenticated=True)
    client = EbayBrowserClient(config=object())
    client._browser = browser

    results = client.search_completed("lego", sold_only=True, limit=1)

    assert [result.item_id for result in results] == ["127992747834"]
    assert browser.events[:3] == [
        ("is_authenticated",),
        ("get_page", "https://www.ebay.com"),
        (
            "wait_for_selector",
            SELECTORS["homepage_search_input"],
            "attached",
            SEARCH_RESULTS_TIMEOUT_MS,
        ),
    ]
