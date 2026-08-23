"""Regression tests for eBay's four-page search navigation limit."""

import json
from urllib.parse import parse_qs, urlparse

from typer.testing import CliRunner

from ebay_cli import browser_client as browser_client_module
from ebay_cli.browser_client import EXTRACT_JS, SELECTORS, EbayBrowserClient
from ebay_cli.commands import search as search_commands
from ebay_cli.main import app


class _FourPageSearchBrowser:
    """Return 240 unique rows per page and advertise another page."""

    def __init__(self) -> None:
        self.current_page = 0
        self.requested_pages: list[int] = []
        self.waited_selectors: list[str] = []
        self.auth_checks = 0
        self.closed = False

    def is_authenticated(self):
        self.auth_checks += 1
        return True

    def get_page(self, url: str):
        if url == EbayBrowserClient.BASE_URL:
            return self
        query = parse_qs(urlparse(url).query)
        self.current_page = int(query.get("_pgn", ["1"])[0])
        self.requested_pages.append(self.current_page)
        return self

    def wait_for_selector(self, selector: str, *, state: str, timeout: int):
        self.waited_selectors.append(selector)
        assert selector in {
            SELECTORS["homepage_search_input"],
            SELECTORS["item"],
        }
        assert state == "attached"
        assert timeout > 0
        return object()

    def evaluate(self, script: str, params=None):
        assert script == EXTRACT_JS
        assert params == {"selectors": SELECTORS, "active": False}
        return [
            {
                "item_id": f"{self.current_page}-{index}",
                "title": f"LEGO lot {self.current_page}-{index}",
                "price": "10.00",
                "currency": "USD",
                "shipping_price": None,
                "status": "sold",
                "date_sold": None,
                "time_left": None,
                "condition": "Pre-Owned",
                "format": "Buy It Now",
                "bids": None,
                "seller": "seller",
                "url": f"https://www.ebay.com/itm/{self.current_page}-{index}",
                "image_url": None,
            }
            for index in range(240)
        ]

    def locator(self, selector: str):
        assert selector == SELECTORS["next_page"]
        return self

    def count(self) -> int:
        return 1

    def wait_for_timeout(self, timeout: int) -> None:
        assert timeout == 1000

    def close(self) -> None:
        self.closed = True


def _pagination_client() -> tuple[EbayBrowserClient, _FourPageSearchBrowser]:
    browser = _FourPageSearchBrowser()
    client = EbayBrowserClient(config=object())
    client._browser = browser
    return client, browser


def test_search_should_stop_before_ebays_unsupported_fifth_page(monkeypatch):
    client, browser = _pagination_client()
    warnings: list[str] = []
    monkeypatch.setattr(browser_client_module, "print_warning", warnings.append)

    results = client.search_completed("lego lbs", sold_only=True, limit=1000)

    assert len(results) == 960
    assert browser.auth_checks == 1
    assert browser.requested_pages == [1, 2, 3, 4]
    assert browser.waited_selectors == [
        SELECTORS["homepage_search_input"],
        *([SELECTORS["item"]] * 4),
    ]
    assert warnings == [
        "eBay search provides at most four result pages. "
        "Returned 960 of 1000 requested results."
    ]


def test_listings_search_command_should_return_four_pages_with_a_truncation_warning(
    monkeypatch,
):
    client, browser = _pagination_client()
    monkeypatch.setattr(
        search_commands,
        "get_browser_client",
        lambda profile=None: client,
    )

    result = CliRunner().invoke(
        app,
        [
            "listings",
            "search",
            "lego lbs",
            "--sold",
            "--limit",
            "1000",
            "--properties",
            "item_id",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert len(payload) == 960
    assert browser.auth_checks == 1
    assert browser.requested_pages == [1, 2, 3, 4]
    assert browser.waited_selectors == [
        SELECTORS["homepage_search_input"],
        *([SELECTORS["item"]] * 4),
    ]
    assert browser.closed is True
    assert "eBay search provides at most four result pages." in result.stderr
    assert "Returned 960 of 1000 requested results." in result.stderr
