"""Regression tests for variation-parent PDP add-to-cart handling.

TCIN 83489325 (Old Spice body wash) is one variant of group 87220385: its PDP
renders a @web/VariationComponent of scent/size chips and keeps the fulfillment
'Add to cart' button disabled until a variant is chosen. ``add_to_cart`` must
select the requested (or first orderable) variant before waiting on the button.

The DOM-reading step is JS, but the decision (``_pick_variants``) is pure Python
and is exercised here with the exact chip shapes captured from the live PDP.
"""
import contextlib

import pytest

from target_cli.client import ClientError, TargetClient


# --- fakes -----------------------------------------------------------------

class FakeLocator:
    def __init__(self, page, selector):
        self._page = page
        self._selector = selector

    def count(self):
        return self._page.counts.get(self._selector, 1)

    @property
    def first(self):
        return self

    def click(self):
        self._page.clicks.append(self._selector)

    def get_attribute(self, name):
        return self._page.attrs.get((self._selector, name))


class FakePage:
    """Records interactions; ``evaluate`` dispatches by the JS it is handed."""

    def __init__(self, components, cell_aria="pickup - selected - 1 of 3 - Ready within 2 hours"):
        self._components = components
        self.clicks = []
        self.waits = []
        self.timeouts = []
        self.counts = {}
        self.attrs = {
            ('button[data-test="fulfillment-cell-pickup"]', "aria-label"): cell_aria,
        }

    def wait_for_selector(self, selector, timeout=None):
        self.waits.append(selector)
        return object()

    def evaluate(self, js, arg=None):
        if "VariationComponent" in js and "map(comp" in js:  # _READ_VARIANTS_JS
            return self._components
        if "AddToCart" in js:  # _confirm_add success/error probe
            return {"state": "ok"}
        return None

    def locator(self, selector):
        return FakeLocator(self, selector)

    def wait_for_timeout(self, ms):
        self.timeouts.append(ms)


class FakeBrowser:
    def __init__(self, page):
        self._page = page
        self.pages = []

    def get_page(self, url):
        self.pages.append(url)
        return self._page


def _client_with_headed(browser):
    client = TargetClient.__new__(TargetClient)
    client._headed_browser = lambda: contextlib.nullcontext(browser)
    return client


# --- _pick_variants: pure decision logic -----------------------------------

# The exact two chips the live PDP renders for group 87220385.
WARM = [[
    {"tcin": "83489325", "selected": True, "orderable": True, "label": "Count, 30 fl oz, selected"},
    {"tcin": "83489290", "selected": False, "orderable": True, "label": "Count, 18 fl oz"},
]]
# Cold state: the same chips with nothing selected (the confirmed failure mode).
COLD = [[
    {"tcin": "83489325", "selected": False, "orderable": True, "label": "Count, 30 fl oz"},
    {"tcin": "83489290", "selected": False, "orderable": True, "label": "Count, 18 fl oz"},
]]


def test_pick_variants_noop_when_requested_variant_already_selected():
    assert TargetClient._pick_variants(WARM, "83489325") == []


def test_pick_variants_switches_to_requested_variant_when_another_is_selected():
    # 30oz is auto-selected but the caller asked for 18oz -> must switch.
    assert TargetClient._pick_variants(WARM, "83489290") == ["83489290"]


def test_pick_variants_leaves_auto_selection_for_group_tcin():
    # Group TCIN matches no chip; a chip is already selected -> leave it.
    assert TargetClient._pick_variants(WARM, "87220385") == []


def test_pick_variants_cold_group_tcin_picks_first_orderable():
    # Nothing selected + group TCIN -> first orderable (the core fix).
    assert TargetClient._pick_variants(COLD, "87220385") == ["83489325"]


def test_pick_variants_cold_requested_variant_is_selected():
    assert TargetClient._pick_variants(COLD, "83489290") == ["83489290"]


def test_pick_variants_raises_when_no_orderable_variant():
    chips = [[{"tcin": "1", "selected": False, "orderable": False}]]
    with pytest.raises(ClientError):
        TargetClient._pick_variants(chips, "1")


def test_pick_variants_empty_component_is_skipped():
    assert TargetClient._pick_variants([[]], "83489325") == []


def test_pick_variants_multi_dimension_selects_only_the_unset_dimension():
    scent = [
        {"tcin": "111", "selected": True, "orderable": True},
        {"tcin": "222", "selected": False, "orderable": True},
    ]
    size = [
        {"tcin": "333", "selected": False, "orderable": True},
        {"tcin": "444", "selected": False, "orderable": True},
    ]
    # requested TCIN matches nothing; scent already set, size needs first orderable.
    assert TargetClient._pick_variants([scent, size], "999") == ["333"]


# --- _select_variant: READ -> DECIDE -> ACT wrapper ------------------------

def test_select_variant_single_sku_is_noop():
    page = FakePage([])  # no @web/VariationComponent
    client = TargetClient.__new__(TargetClient)
    assert client._select_variant(page, "92612650") is False
    assert page.clicks == []


def test_select_variant_clicks_requested_chip_and_settles():
    page = FakePage(COLD)
    client = TargetClient.__new__(TargetClient)
    assert client._select_variant(page, "83489290") is True
    assert any('button[href*="/A-83489290"]' in sel for sel in page.clicks)
    assert 1500 in page.timeouts


def test_select_variant_raises_if_chosen_chip_vanishes():
    page = FakePage(COLD)
    page.counts['[data-test="@web/VariationComponent"] button[href*="/A-83489325"]'] = 0
    client = TargetClient.__new__(TargetClient)
    with pytest.raises(ClientError):
        client._select_variant(page, "87220385")


# --- add_to_cart: orchestration --------------------------------------------

def test_add_to_cart_selects_variant_before_button_and_rewaits_cell():
    page = FakePage(COLD)
    client = _client_with_headed(FakeBrowser(page))
    client.add_to_cart("83489325", method="pickup")

    cell = 'button[data-test="fulfillment-cell-pickup"]'
    # variant chip selected, cell waited before AND after selection, then add clicked
    assert any('button[href*="/A-83489325"]' in sel for sel in page.clicks)
    assert page.waits.count(cell) == 2
    assert any("orderPickupButton" in sel for sel in page.clicks)


def test_add_to_cart_single_sku_skips_variant_and_waits_cell_once():
    page = FakePage([])
    client = _client_with_headed(FakeBrowser(page))
    client.add_to_cart("92612650", method="pickup")

    cell = 'button[data-test="fulfillment-cell-pickup"]'
    assert not any("VariationComponent" in sel for sel in page.clicks)
    assert page.waits.count(cell) == 1
    assert any("orderPickupButton" in sel for sel in page.clicks)


def test_add_to_cart_rejects_unknown_method():
    client = TargetClient.__new__(TargetClient)
    with pytest.raises(ClientError):
        client.add_to_cart("83489325", method="teleport")
