"""Regression tests for `cart checkout`'s Place Order gate.

Live repro (profile randafaith, dry run only -- no --yes, no real order placed):
`cart add 87450164 -m pickup` succeeds, then `cart checkout --card redcard-1082`
raised "Could not reach the Place Order screen..." Investigation via a live DOM
snapshot at https://www.target.com/checkout (through the CLI's own authenticated
browser session) showed Target rendering a "Sign in to your account" step-up
re-authentication challenge (passkey / code / password options) instead of the
checkout page -- NOT a missing pickup-store/time-selection step as originally
hypothesized. Confirmed NOT pickup-specific: swapping the SAME TCIN to
`-m shipping` reproduced the identical wall. `target auth status` and a live
`/account` snapshot both confirmed the account session itself is authenticated
("Hello, Miranda") -- this is a checkout-specific Target step-up gate, not a
session/auth-profile expiry and not a CLI code defect. Per the browser-automation
skill's hard-stop rule, a passkey/password step-up challenge cannot be automated
through and was not attempted; no code fix applies here since checkout()'s
existing gate (wait_for_selector on placeOrderButton, timeout, raise ClientError)
already behaves correctly for "the expected element never appeared" -- these
tests are baseline coverage proving that gate's error and success paths are
exactly what they claim to be, so a future real fix (if Target's UI changes)
has a regression harness to build on.
"""
import contextlib

import pytest

from target_cli.client import ClientError, TargetClient


class FakeLocator:
    def __init__(self, page, selector):
        self._page = page
        self._selector = selector

    def count(self):
        return 1

    @property
    def first(self):
        return self

    def inner_text(self):
        return self._page.texts.get(self._selector, "")

    def click(self):
        self._page.clicks.append(self._selector)


class FakeCheckoutPage:
    """Fake /checkout page: place_order_button_appears toggles the exact gate
    checkout() waits on, so both outcomes (button present vs. never appears --
    the live-reproduced failure) are directly exercisable."""

    def __init__(self, *, place_order_button_appears: bool, order_total="$24.06", subtotal="$22.49"):
        self._place_order_button_appears = place_order_button_appears
        self.texts = {
            '[data-test="order-summary-total"], [data-test="cart-summary-total"]': order_total,
            '[data-test="cart-summary-subTotal"], [data-test="order-summary-subtotal"]': subtotal,
        }
        self.clicks = []
        self.waits = []

    def wait_for_selector(self, selector, timeout=None):
        self.waits.append(selector)
        if selector == 'button[data-test="placeOrderButton"]' and not self._place_order_button_appears:
            raise TimeoutError("placeOrderButton never appeared")
        return object()

    def locator(self, selector):
        return FakeLocator(self, selector)


class FakeBrowser:
    def __init__(self, page):
        self._page = page
        self.pages = []

    def get_page(self, url):
        self.pages.append(url)
        return self._page


def _client_with_headed(page):
    client = TargetClient.__new__(TargetClient)
    client._headed_browser = lambda: contextlib.nullcontext(FakeBrowser(page))
    # checkout() reads pickup-contact prefs unconditionally; stub the module
    # function it imports so these tests don't touch real profile data on disk.
    client.config = object()
    return client


@pytest.fixture(autouse=True)
def _stub_pickup_prefs(monkeypatch):
    from target_cli import prefs as prefs_module
    monkeypatch.setattr(prefs_module, "get_pickup_contact", lambda config: {"email": None, "name": None})


def _no_card_resolution(client):
    """checkout() calls self._resolve_checkout_card(card) before opening the
    browser; stub it so these gate-focused tests don't need cards.json state."""
    client._resolve_checkout_card = lambda card: (None, None)
    return client


# --- the exact live-reproduced failure: Place Order screen never reached ---

def test_checkout_raises_when_place_order_button_never_appears():
    """Live repro: cart add 87450164 -m pickup -> cart checkout --card
    redcard-1082 (dry run) raised exactly this ClientError. Root cause was a
    Target-side checkout step-up re-authentication wall (confirmed via a live
    DOM snapshot showing 'Sign in to your account' instead of the checkout
    page), NOT a missing pickup-store/time-selection step -- the SAME wall
    reproduced for the identical TCIN added via -m shipping too. This test
    guards the existing (correct) gate: when placeOrderButton never renders
    for ANY reason, checkout() must fail loud with this exact message, not
    hang or silently proceed."""
    page = FakeCheckoutPage(place_order_button_appears=False)
    client = _no_card_resolution(_client_with_headed(page))
    with pytest.raises(ClientError, match="Could not reach the Place Order screen"):
        client.checkout(place_order=False, card=None)


def test_checkout_dry_run_does_not_raise_when_place_order_button_present():
    """Positive control for the gate above: when the Place Order screen DOES
    render, a dry run must succeed and report placed=False without clicking
    anything (no --yes -> no order placed)."""
    page = FakeCheckoutPage(place_order_button_appears=True, order_total="$24.06", subtotal="$22.49")
    client = _no_card_resolution(_client_with_headed(page))
    result = client.checkout(place_order=False, card=None)
    assert result["placed"] is False
    assert result["order_total"] == "$24.06"
    assert result["subtotal"] == "$22.49"
    assert result["note"] == "Dry run -- order NOT placed. Re-run with --yes to buy."
    # Dry run must never click Place Order.
    assert 'button[data-test="placeOrderButton"]' not in page.clicks
