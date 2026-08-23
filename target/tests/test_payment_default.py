"""Regression tests for `payment list` default-card detection.

The bug: every saved card showed ``default: true`` because the default flag was
computed with ``/\bdefault\b/i.test(txt)``, which also matches the "Set as
default payment card" control on NON-default rows. The real default card carries
a dedicated ``[data-test="defaultPill"]`` element (verified on the live wallet).
"""
import inspect

from target_cli.client import TargetClient


class FakePage:
    def __init__(self, rows):
        self._rows = rows

    def wait_for_selector(self, selector, timeout=None):
        return object()

    def evaluate(self, js, arg=None):
        return self._rows


class FakeBrowser:
    def __init__(self, page):
        self._page = page

    def get_page(self, url):
        return self._page


def _client_listing(rows):
    client = TargetClient.__new__(TargetClient)
    client._browser = FakeBrowser(FakePage(rows))
    return client


def test_list_payments_returns_rows_from_page():
    rows = [
        {"brand": "American", "last4": "1004", "expires": "07/2027", "default": True},
        {"brand": "Mastercard", "last4": "5636", "expires": "04/2029", "default": False},
    ]
    assert _client_listing(rows).list_payments() == rows


def test_list_payments_marks_exactly_one_default():
    rows = [
        {"brand": "American", "last4": "1004", "expires": "07/2027", "default": True},
        {"brand": "Mastercard", "last4": "5636", "expires": "04/2029", "default": False},
    ]
    defaults = [r for r in _client_listing(rows).list_payments() if r["default"]]
    assert len(defaults) == 1
    assert defaults[0]["last4"] == "1004"


def test_wallet_card_reader_uses_default_pill_marker_not_word_match():
    """Guard the fix: default is keyed off the pill element, not the word 'default'.

    Inspect the whole class so the guard survives the reader living in
    ``list_payments`` or an extracted helper (``_read_wallet_cards``).
    """
    src = inspect.getsource(TargetClient)
    assert 'data-test="defaultPill"' in src
    assert r"\bdefault\b" not in src
