"""Tests for the single-order read (`orders get` -> TargetClient.get_order).

``get_order`` loads an order's detail page through the logged-in browser session
and returns the same ``order_number/status/total`` shape as a ``list_orders`` row.
Verified here without a live browser via a fake page/browser (mirrors
``test_payment_default``): status comes from the page body, the total is scoped to
the "order total" label, and an unopenable order fails loud.
"""
import pytest

from target_cli.client import ClientError, TargetClient


class FakePage:
    def __init__(self, *, status_body="", total="", selector_ok=True):
        self._status_body = status_body
        self._total = total
        self._selector_ok = selector_ok

    def wait_for_selector(self, selector, timeout=None):
        if not self._selector_ok:
            raise RuntimeError("selector not found")
        return object()

    def wait_for_timeout(self, ms):
        return None

    def evaluate(self, js, arg=None):
        # get_order evaluates the "order total" scrape in-page; _order_status
        # evaluates document.body.innerText and matches in Python.
        if "order total" in js:
            return self._total
        if "document.body.innerText" in js:
            return self._status_body
        return None


class FakeBrowser:
    def __init__(self, page):
        self._page = page
        self.url = None

    def get_page(self, url):
        self.url = url
        return self._page


def _client(page):
    client = TargetClient.__new__(TargetClient)
    client._browser = FakeBrowser(page)
    return client


def test_get_order_returns_number_status_total():
    page = FakePage(status_body="Order #123 Delivered Jul 1", total="$41.98")
    order = _client(page).get_order("123456789")
    assert order == {"order_number": "123456789", "status": "Delivered", "total": "$41.98"}


def test_get_order_total_null_when_summary_absent():
    page = FakePage(status_body="processing", total=None)
    order = _client(page).get_order("999")
    assert order["order_number"] == "999"
    assert order["status"] == "processing"
    assert order["total"] is None


def test_get_order_loads_the_order_detail_url():
    page = FakePage(status_body="shipped", total="$5.00")
    client = _client(page)
    client.get_order("777888999")
    assert client._browser.url == "https://www.target.com/orders/777888999"


def test_get_order_fails_loud_when_page_will_not_open():
    page = FakePage(selector_ok=False)
    with pytest.raises(ClientError):
        _client(page).get_order("123")
