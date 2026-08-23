"""Tests for `cart list` (tcin exposure) and `cart clear`.

``get_cart`` reads each ``[data-test="cartItem"]`` row's ``data-tcin`` attribute
directly -- verified live on the real cart page for profile ``randafaith``
(one "All In Motion" shorts item): the row element itself carries
``data-tcin="95015332"``, and its linked title/image ``<a>`` tags independently
carry the same TCIN in their ``/A-95015332`` product href, corroborating the
attribute. ``title``/``price`` are unchanged; only ``tcin`` is added.

``clear_cart`` is built entirely on the two existing per-item paths: it lists
via ``get_cart`` (now tcin-bearing) and removes each item via the existing
``remove_from_cart(tcin)`` -- no separate "clear" DOM interaction. An
already-empty cart is a no-op that reports 0 removed, mirroring how
``favorites_remove`` reports a count (``result['remaining']``) rather than
raising on an empty/no-op outcome.
"""
import pytest

from target_cli.client import ClientError, TargetClient


# --- fakes -------------------------------------------------------------
# Mirrors the FakeLocator/FakePage/FakeBrowser pattern used in
# test_variant_selection.py / test_payment_default.py / test_orders.py.

class FakeElementLocator:
    """A locator scoped to one already-resolved cart-item row element."""

    def __init__(self, row, page=None):
        self._row = row
        self._page = page

    def get_attribute(self, name):
        return self._row.attrs.get(name)

    def locator(self, selector):
        return FakeRowChildLocator(self._row, selector, page=self._page)


class FakeRowChildLocator:
    """A locator for a child selector (title/price/anchor/delete button) within one row."""

    def __init__(self, row, selector, page=None):
        self._row = row
        self._selector = selector
        self._page = page

    def count(self):
        return self._row.child_counts.get(self._selector, 0)

    @property
    def first(self):
        return self

    def inner_text(self):
        return self._row.child_text[self._selector]

    def click(self):
        self._row.clicks.append(self._selector)
        # Clicking the delete button removes the row from the live page, same
        # as the real DOM after Target's delete API call resolves -- so a
        # post-removal re-read of the page (get_cart / clear_cart's re-check)
        # sees the item actually gone, not just "clicked".
        if self._selector == 'button[data-test="cartItem-deleteBtn"]' and self._page is not None:
            if self._row in self._page.rows:
                self._page.rows.remove(self._row)


class FakeCartRow:
    """One cart-item row: carries data-tcin plus child selector counts/text."""

    def __init__(self, tcin, title, price, *, has_delete_button=True):
        self.attrs = {"data-tcin": tcin}
        self.child_counts = {
            '[data-test="cartItem-title"]': 1,
            '[data-test="cartItem-price"]': 1,
            f'a[href*="A-{tcin}"]': 1,
            'button[data-test="cartItem-deleteBtn"]': 1 if has_delete_button else 0,
        }
        self.child_text = {
            '[data-test="cartItem-title"]': title,
            '[data-test="cartItem-price"]': price,
        }
        self.clicks = []


class FakeCartLocator:
    """Stands in for ``page.locator('[data-test="cartItem"]')``."""

    def __init__(self, page):
        self._page = page

    def count(self):
        return len(self._page.rows)

    def all(self):
        # Snapshot the row list before iterating: a delete click during
        # iteration mutates ``page.rows`` in place (see FakeElementLocator),
        # exactly like the real DOM update racing a live NodeList.
        return [FakeElementLocator(row, page=self._page) for row in list(self._page.rows)]


class FakeTotalLocator:
    def __init__(self, total):
        self._total = total

    def count(self):
        return 1 if self._total is not None else 0

    def inner_text(self):
        return self._total


class FakeCartPage:
    """Fake page for the cart URL: dispatches selector -> the right fake locator.

    ``rows`` is mutable so ``remove_from_cart`` (invoked once per item by
    ``clear_cart``) can delete the matched row, exactly like clicking the real
    delete button removes it from the live DOM before the next ``get_page`` re-read.
    """

    def __init__(self, rows, total="$0.00", *, selector_ok=True):
        self.rows = list(rows)
        self._total = total
        self._selector_ok = selector_ok
        self.timeouts = []

    def wait_for_selector(self, selector, timeout=None):
        if not self._selector_ok or not self.rows:
            raise RuntimeError("no cart items")
        return object()

    def wait_for_timeout(self, ms):
        self.timeouts.append(ms)

    def locator(self, selector):
        if selector == '[data-test="cartItem"]':
            return FakeCartLocator(self)
        if selector == '[data-test="cart-summary-total"]':
            return FakeTotalLocator(self._total)
        raise AssertionError(f"unexpected top-level selector: {selector}")


class FakeCartBrowser:
    """Returns the same page for every ``get_page`` call (list, then N removes)."""

    def __init__(self, page):
        self._page = page
        self.urls = []

    def get_page(self, url):
        self.urls.append(url)
        return self._page

    def close(self):
        pass


def _client(page):
    """Client for get_cart-only tests. ``get_cart`` reads via ``_get_browser()``."""
    client = TargetClient.__new__(TargetClient)
    client._browser = FakeCartBrowser(page)
    client._get_browser = lambda: client._browser
    return client


def _client_with_headed(page):
    """Client for remove_from_cart-only tests. ``remove_from_cart`` reads via
    the ``_headed_browser()`` context manager, not ``_get_browser()``."""
    import contextlib
    client = TargetClient.__new__(TargetClient)
    browser = FakeCartBrowser(page)
    client._headed_browser = lambda: contextlib.nullcontext(browser)
    return client


def _client_for_clear(page):
    """Client for clear_cart tests: stub BOTH browser paths (get_cart uses
    ``_get_browser()``, remove_from_cart uses ``_headed_browser()``) so
    clear_cart's real list-then-remove-each call chain runs against the same
    fake page/browser end to end."""
    import contextlib
    client = TargetClient.__new__(TargetClient)
    browser = FakeCartBrowser(page)
    client._browser = browser
    client._get_browser = lambda: client._browser
    client._headed_browser = lambda: contextlib.nullcontext(browser)
    return client


class CountingHeadedBrowserFactory:
    """A real (non-no-op) ``_headed_browser()`` stand-in that COUNTS open/close
    cycles, unlike ``contextlib.nullcontext`` (which can't tell 1-open-N-removes
    apart from N-open-N-close since it never actually enters/exits anything).

    Mirrors the real ``_headed_browser`` contract: a ``@contextmanager`` that
    yields a browser and closes it in a ``finally`` on exit. Each ``__call__``
    (i.e. each ``with self._headed_browser() as browser:``) increments
    ``opens``; the browser's ``close()`` increments ``closes``. A caller that
    opens once for N removals -> ``opens == closes == 1``; the old
    per-item-loop bug would have produced ``opens == closes == N``.
    """

    def __init__(self, page):
        self._page = page
        self.opens = 0
        self.closes = 0

    def __call__(self):
        import contextlib

        @contextlib.contextmanager
        def _cm():
            self.opens += 1
            browser = FakeCartBrowser(self._page)
            browser.close = lambda: setattr(self, "closes", self.closes + 1)
            try:
                yield browser
            finally:
                browser.close()

        return _cm()


def _client_for_clear_counting(page):
    """Client for clear_cart tests that must PROVE the headed browser is opened
    at most once, regardless of cart size. ``get_cart`` (the initial list) still
    uses the separate headless ``_get_browser()`` path -- only
    ``_headed_browser()`` opens/closes are counted here."""
    client = TargetClient.__new__(TargetClient)
    client._browser = FakeCartBrowser(page)
    client._get_browser = lambda: client._browser
    factory = CountingHeadedBrowserFactory(page)
    client._headed_browser = factory
    return client, factory


# --- get_cart: tcin exposure --------------------------------------------

def test_get_cart_includes_tcin_from_data_tcin_attribute():
    """Real captured shape: the live randafaith cart's one item (TCIN 95015332,
    'All In Motion' shorts, $14.25; cart total $15.25)."""
    page = FakeCartPage(
        [FakeCartRow("95015332", 'Women\'s Active Light Woven High-Rise Shorts 3" - All In Motion™ Red M', "$14.25")],
        total="$15.25",
    )
    cart = _client(page).get_cart()
    assert cart["items"] == [
        {
            "tcin": "95015332",
            "title": 'Women\'s Active Light Woven High-Rise Shorts 3" - All In Motion™ Red M',
            "price": "$14.25",
        }
    ]
    assert cart["total"] == "$15.25"


def test_get_cart_includes_tcin_for_multiple_items():
    page = FakeCartPage(
        [
            FakeCartRow("95015332", "Shorts", "$14.25"),
            FakeCartRow("87450164", "Bounty Paper Towels", "$22.49"),
        ],
        total="$36.74",
    )
    cart = _client(page).get_cart()
    assert [item["tcin"] for item in cart["items"]] == ["95015332", "87450164"]


def test_get_cart_empty_cart_returns_no_items():
    page = FakeCartPage([], total=None, selector_ok=False)
    cart = _client(page).get_cart()
    assert cart["items"] == []
    assert cart["total"] == "$0.00"


# --- clear_cart: list -> remove each, built on existing paths -----------

def test_clear_cart_removes_every_item_via_existing_remove_from_cart():
    """Multi-item cart: clear_cart must call the existing remove_from_cart for
    each tcin discovered by get_cart, and return the count removed."""
    page = FakeCartPage(
        [
            FakeCartRow("95015332", "Shorts", "$14.25"),
            FakeCartRow("87450164", "Bounty Paper Towels", "$22.49"),
        ],
        total="$36.74",
    )
    client = _client_for_clear(page)
    # clear_cart calls self.remove_from_cart(tcin) directly (same object, same
    # page) -- exercise the real remove_from_cart rather than re-mocking it, so
    # the test proves clear_cart reuses that exact method.
    removed = client.clear_cart()
    assert removed == 2
    # Both rows' delete buttons were clicked (both items got removed).
    assert all(row.clicks == ['button[data-test="cartItem-deleteBtn"]'] for row in page.rows)


def test_clear_cart_no_op_on_already_empty_cart():
    """An already-empty cart must not error -- 0 items removed."""
    page = FakeCartPage([], total=None, selector_ok=False)
    client = _client_for_clear(page)
    assert client.clear_cart() == 0


def test_clear_cart_single_item_cart():
    page = FakeCartPage(
        [FakeCartRow("95015332", "Shorts", "$14.25")],
        total="$14.25",
    )
    client = _client_for_clear(page)
    assert client.clear_cart() == 1


# --- clear_cart: reuses ONE headed browser for the whole operation ------
# Regression coverage for the "cart clear --yes hangs 10+ minutes" bug: the
# original clear_cart called remove_from_cart in a loop, and remove_from_cart
# opens its own _headed_browser() per call -- so an N-item cart paid a full
# fresh-Chrome + fresh-daemon launch/teardown cycle N times. These tests use a
# _headed_browser() stand-in that actually counts open/close cycles (unlike
# contextlib.nullcontext, which can't tell 1-open-N-removes apart from
# N-open-N-close since it never truly enters/exits anything).

def test_clear_cart_opens_headed_browser_at_most_once_for_multi_item_cart():
    """The bug: N items -> N _headed_browser() opens. The fix: 1 open total,
    regardless of cart size, with every removal driven off that one session."""
    page = FakeCartPage(
        [
            FakeCartRow("95015332", "Shorts", "$14.25"),
            FakeCartRow("87450164", "Bounty Paper Towels", "$22.49"),
            FakeCartRow("16951588", "Pens", "$5.99"),
        ],
        total="$44.23",
    )
    client, factory = _client_for_clear_counting(page)
    removed = client.clear_cart()
    assert removed == 3
    assert factory.opens == 1, f"expected exactly 1 _headed_browser() open, got {factory.opens}"
    assert factory.closes == 1, f"expected exactly 1 _headed_browser() close, got {factory.closes}"


def test_clear_cart_opens_headed_browser_once_for_single_item_cart():
    page = FakeCartPage([FakeCartRow("95015332", "Shorts", "$14.25")], total="$14.25")
    client, factory = _client_for_clear_counting(page)
    assert client.clear_cart() == 1
    assert factory.opens == 1
    assert factory.closes == 1


def test_clear_cart_does_not_open_headed_browser_when_cart_already_empty():
    """A no-op clear (cart already empty) must not pay for a headed browser at
    all -- get_cart (headless) alone is enough to see there's nothing to do."""
    page = FakeCartPage([], total=None, selector_ok=False)
    client, factory = _client_for_clear_counting(page)
    assert client.clear_cart() == 0
    assert factory.opens == 0
    assert factory.closes == 0


# --- clear_cart: bounded retry, then raise on a pathological stuck item --

def test_clear_cart_retries_bounded_times_then_raises_when_item_never_disappears():
    """A pathological item that survives every removal click must not loop
    forever: clear_cart retries up to _CLEAR_CART_MAX_RETRY_PASSES bounded
    passes, then raises ClientError -- no silent infinite loop, no swallowed
    failure."""
    tcin = "99999999"
    row = FakeCartRow(tcin, "Cursed Item", "$1.00")
    page = FakeCartPage([row], total="$1.00")
    # Neuter the click's row-removal side effect for THIS row only, so the item
    # is "clicked" every pass but never actually leaves page.rows -- exercising
    # the exhaustion path without special-casing the shared fakes above.
    original_click = FakeRowChildLocator.click

    def stuck_click(self):
        self._row.clicks.append(self._selector)  # record the click like normal

    FakeRowChildLocator.click = stuck_click
    try:
        client, factory = _client_for_clear_counting(page)
        with pytest.raises(ClientError, match="99999999"):
            client.clear_cart()
    finally:
        FakeRowChildLocator.click = original_click
    # Still exactly ONE _headed_browser() open despite multiple retry passes
    # inside it -- retries must happen on the SAME open session, not by
    # reopening the browser per attempt.
    assert factory.opens == 1
    assert factory.closes == 1
    # The delete button was clicked once per retry pass (3 total).
    assert row.clicks.count('button[data-test="cartItem-deleteBtn"]') == TargetClient._CLEAR_CART_MAX_RETRY_PASSES


def test_clear_cart_retry_recovers_when_item_disappears_on_a_later_pass():
    """A slow-to-update item that only disappears on the 2nd removal pass must
    still succeed (not raise) -- the retry loop exists precisely for this."""
    tcin = "88888888"
    row = FakeCartRow(tcin, "Slow Item", "$2.00")
    page = FakeCartPage([row], total="$2.00")

    attempts = {"count": 0}
    original_click = FakeRowChildLocator.click

    def flaky_click(self):
        self._row.clicks.append(self._selector)
        attempts["count"] += 1
        if attempts["count"] >= 2:  # disappears on the 2nd click (2nd retry pass)
            if self._row in self._page.rows:
                self._page.rows.remove(self._row)

    FakeRowChildLocator.click = flaky_click
    try:
        client, factory = _client_for_clear_counting(page)
        removed = client.clear_cart()
    finally:
        FakeRowChildLocator.click = original_click
    assert removed == 1
    assert factory.opens == 1
    assert factory.closes == 1


# --- remove_from_cart: existing behavior used by clear_cart -------------

def test_remove_from_cart_raises_when_item_not_found():
    page = FakeCartPage([FakeCartRow("11111111", "Other Item", "$9.99")], total="$9.99")
    client = _client_with_headed(page)
    with pytest.raises(ClientError):
        client.remove_from_cart("95015332")


def test_remove_from_cart_raises_when_cart_did_not_load():
    page = FakeCartPage([], total=None, selector_ok=False)
    client = _client_with_headed(page)
    with pytest.raises(ClientError):
        client.remove_from_cart("95015332")
