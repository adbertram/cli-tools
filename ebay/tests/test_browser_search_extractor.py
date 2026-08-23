"""Regression tests for the completed-listings browser extractor."""

import pytest
from cli_tools_shared.browser import BrowserHarnessError
from playwright.sync_api import sync_playwright

from ebay_cli.browser import BrowserError
from ebay_cli.browser_client import (
    EXTRACT_JS,
    PAGE_STATE_JS,
    SEARCH_RESULTS_TIMEOUT_MS,
    SELECTORS,
    EbayBrowserClient,
)


def _run_extract_js(html: str, active: bool = False):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        rows = page.evaluate(EXTRACT_JS, {"selectors": SELECTORS, "active": active})
        browser.close()
    return rows


def _run_page_state_js(html: str):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        state = page.evaluate(PAGE_STATE_JS, SELECTORS)
        browser.close()
    return state


def test_extract_js_parses_current_s_card_layout():
    """The extractor reads eBay's current "s-card" completed-listing layout
    (eBay replaced the earlier "su-item-card" markup with this -- verified
    2026-07-23 against live search-result HTML)."""
    html = """
    <html>
      <body>
        <main class="srp-river-main clearfix">
          <div class="srp-controls__count-heading">140,000+ results for HP 63XL</div>
          <ul class="srp-results">
            <li class="s-card s-card--horizontal" data-listingid="2500219655424533">
              <div class="su-card-container">
                <a class="s-card__link"><div class="s-card__title">Shop on eBay</div></a>
              </div>
            </li>
            <li class="s-card s-card--horizontal" data-listingid="377305506170">
              <div class="su-card-container su-card-container--horizontal">
                <div class="su-card-container__media">
                  <div class="su-image">
                    <img class="s-card__image" src="https://i.ebayimg.com/images/g/CIEAAeSwLi5qQxbw/s-l500.webp" />
                  </div>
                </div>
                <div class="su-card-container__content">
                  <div class="su-card-container__header">
                    <div class="s-card__caption">
                      <span class="su-styled-text positive default" aria-label="Sold Item">Sold  Jul 5, 2026</span>
                    </div>
                    <a class="s-card__link" href="https://www.ebay.com/itm/377305506170?_skw=HP+63XL">
                      <div class="s-card__title">
                        <span class="s-card__new-listing">New Listing</span>
                        <span class="su-styled-text primary default">New HP 63 XL Black Ink Printer Cartridge High Yield</span>
                        <span class="clipped">Opens in a new window or tab</span>
                      </div>
                    </a>
                    <div class="s-card__subtitle-row">
                      <div class="s-card__subtitle">
                        <span class="su-styled-text secondary default">Brand New</span>
                      </div>
                    </div>
                  </div>
                  <div class="su-card-container__attributes su-card-container__attributes--has-secondary">
                    <div class="su-card-container__attributes__primary">
                      <div class="s-card__attribute-row">
                        <span class="su-styled-text positive strikethrough large-1 s-card__price">$45.00</span>
                      </div>
                      <div class="s-card__attribute-row">
                        <span class="su-styled-text secondary large">Best offer accepted</span>
                      </div>
                      <div class="s-card__attribute-row">
                        <span class="su-styled-text secondary large">Free delivery</span>
                      </div>
                    </div>
                    <div class="su-card-container__attributes__secondary">
                      <div class="s-card__attribute-row">
                        <span class="su-styled-text primary large">scarbalde_0 </span>
                        <span class="su-styled-text primary large">98.6% positive (69)</span>
                      </div>
                      <div class="s-card__attribute-row">
                        <span class="su-styled-text secondary large">Item: 377305506170</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </li>
            <li class="s-card s-card--horizontal" data-listingid="267717942253">
              <div class="su-card-container su-card-container--horizontal">
                <div class="su-card-container__content">
                  <div class="su-card-container__header">
                    <div class="s-card__caption">
                      <span class="su-styled-text default" aria-label="Ended Item">Ended  Jul 4, 2026</span>
                    </div>
                    <a class="s-card__link" href="https://www.ebay.com/itm/267717942253?_skw=HP+63XL">
                      <div class="s-card__title">
                        <span class="su-styled-text primary default">HP 63XL Ink Cartridge - Black</span>
                        <span class="clipped">Opens in a new window or tab</span>
                      </div>
                    </a>
                    <div class="s-card__subtitle-row">
                      <div class="s-card__subtitle">
                        <span class="su-styled-text secondary default">Open Box</span>
                      </div>
                    </div>
                  </div>
                  <div class="su-card-container__attributes su-card-container__attributes--has-secondary">
                    <div class="su-card-container__attributes__primary">
                      <div class="s-card__attribute-row">
                        <span class="su-styled-text positive strikethrough large-1 s-card__price">$27.99</span>
                      </div>
                      <div class="s-card__attribute-row">
                        <span class="su-styled-text secondary large">+$8.60 delivery in 2-4 days</span>
                      </div>
                      <div class="s-card__attribute-row">
                        <span class="su-styled-text secondary large">3 bids</span>
                      </div>
                    </div>
                    <div class="su-card-container__attributes__secondary">
                      <div class="s-card__attribute-row">
                        <span class="su-styled-text primary large">letsdeal108 </span>
                        <span class="su-styled-text primary large">100% positive (1.9K)</span>
                      </div>
                      <div class="s-card__attribute-row">
                        <span class="su-styled-text secondary large">Item: 267717942253</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </li>
          </ul>
        </main>
      </body>
    </html>
    """

    rows = _run_extract_js(html)

    assert rows == [
        {
            "item_id": "377305506170",
            "title": "New HP 63 XL Black Ink Printer Cartridge High Yield",
            "price": "45.00",
            "currency": "USD",
            "shipping_price": "0.00",
            "status": "sold",
            "date_sold": "Jul 5, 2026",
            "time_left": None,
            "condition": "Brand New",
            "format": "Best Offer",
            "bids": None,
            "seller": "scarbalde_0",
            "url": "https://www.ebay.com/itm/377305506170?_skw=HP+63XL",
            "image_url": "https://i.ebayimg.com/images/g/CIEAAeSwLi5qQxbw/s-l500.webp",
        },
        {
            "item_id": "267717942253",
            "title": "HP 63XL Ink Cartridge - Black",
            "price": "27.99",
            "currency": "USD",
            "shipping_price": "8.60",
            "status": "unsold",
            "date_sold": "Jul 4, 2026",
            "time_left": None,
            "condition": "Open Box",
            "format": "Auction",
            "bids": 3,
            "seller": "letsdeal108",
            "url": "https://www.ebay.com/itm/267717942253?_skw=HP+63XL",
            "image_url": None,
        },
    ]


def test_extract_js_active_bin_card():
    """Active BIN card: status is 'active', no date_sold, listing date is NOT
    mistaken for time-left, and price/shipping/seller/format parse."""
    html = """
    <html><body>
      <main class="srp-river-main clearfix">
        <div class="srp-controls__count-heading">55,000+ results for LEGO bulk lot</div>
        <ul class="srp-results">
          <li class="s-card s-card--horizontal" data-listingid="127992747834">
            <div class="su-card-container su-card-container--horizontal">
              <div class="su-card-container__content">
                <div class="su-card-container__header">
                  <a class="s-card__link" href="https://www.ebay.com/itm/127992747834?_skw=LEGO+bulk+lot">
                    <div class="s-card__title">
                      <span class="s-card__new-listing">New Listing</span>
                      <span class="su-styled-text primary default">LEGO White Technic, Panel Fairing #13/14</span>
                      <span class="clipped">Opens in a new window or tab</span>
                    </div>
                  </a>
                  <div class="s-card__subtitle-row">
                    <div class="s-card__subtitle"><span class="su-styled-text secondary default">Brand New</span></div>
                  </div>
                </div>
                <div class="su-card-container__attributes su-card-container__attributes--has-secondary">
                  <div class="su-card-container__attributes__primary">
                    <div class="s-card__attribute-row"><span class="su-styled-text primary bold large-1 s-card__price">$2.95</span></div>
                    <div class="s-card__attribute-row"><span class="su-styled-text secondary large">or Best Offer</span></div>
                    <div class="s-card__attribute-row"><span class="su-styled-text secondary large">+$6.25 delivery</span></div>
                    <div class="s-card__attribute-row"><span class="su-styled-text secondary large">Located in United States</span></div>
                    <div class="s-card__attribute-row"><span class="su-styled-text secondary large">Jul-24 15:33</span></div>
                  </div>
                  <div class="su-card-container__attributes__secondary">
                    <div class="s-card__attribute-row">
                      <span class="su-styled-text primary large">akp516 </span>
                      <span class="su-styled-text primary large">100% positive (3.9K)</span>
                    </div>
                    <div class="s-card__attribute-row"><span class="su-styled-text secondary large">Item: 127992747834</span></div>
                  </div>
                </div>
              </div>
            </div>
          </li>
        </ul>
      </main>
    </body></html>
    """

    rows = _run_extract_js(html, active=True)

    assert len(rows) == 1
    row = rows[0]
    assert row["item_id"] == "127992747834"
    assert row["status"] == "active"
    assert row["date_sold"] is None
    assert row["time_left"] is None  # "Jul-24 15:33" is a listing date, not time-left
    assert row["price"] == "2.95"
    assert row["shipping_price"] == "6.25"
    assert row["format"] == "Best Offer"
    assert row["seller"] == "akp516"
    assert row["bids"] is None


def test_extract_js_active_auction_card():
    """Active auction card: status 'active', bids parsed, and the time-left
    attribute row ('1m (Today 3:52PM)') is captured as time_left."""
    html = """
    <html><body>
      <main class="srp-river-main clearfix">
        <div class="srp-controls__count-heading">1,200 results for LEGO bulk lot</div>
        <ul class="srp-results">
          <li class="s-card s-card--horizontal" data-listingid="158093790272">
            <div class="su-card-container su-card-container--horizontal">
              <div class="su-card-container__content">
                <div class="su-card-container__header">
                  <a class="s-card__link" href="https://www.ebay.com/itm/158093790272?_skw=LEGO+bulk+lot">
                    <div class="s-card__title">
                      <span class="su-styled-text primary default">LEGO Batman Batmobile Set 76139</span>
                      <span class="clipped">Opens in a new window or tab</span>
                    </div>
                  </a>
                  <div class="s-card__subtitle-row">
                    <div class="s-card__subtitle"><span class="su-styled-text secondary default">Pre-Owned</span></div>
                  </div>
                </div>
                <div class="su-card-container__attributes su-card-container__attributes--has-secondary">
                  <div class="su-card-container__attributes__primary">
                    <div class="s-card__attribute-row"><span class="su-styled-text primary bold large-1 s-card__price">$250.00</span></div>
                    <div class="s-card__attribute-row">
                      <span class="su-styled-text secondary large">1m</span>
                      <span class="su-styled-text secondary large">(Today 3:52PM)</span>
                    </div>
                    <div class="s-card__attribute-row"><span class="su-styled-text secondary large">3 bids</span></div>
                    <div class="s-card__attribute-row"><span class="su-styled-text secondary large">+$12.22 delivery</span></div>
                    <div class="s-card__attribute-row"><span class="su-styled-text secondary large">Located in United States</span></div>
                  </div>
                  <div class="su-card-container__attributes__secondary">
                    <div class="s-card__attribute-row">
                      <span class="su-styled-text primary large">cloudstrife768 </span>
                      <span class="su-styled-text primary large">0% positive (24)</span>
                    </div>
                    <div class="s-card__attribute-row"><span class="su-styled-text secondary large">Item: 158093790272</span></div>
                  </div>
                </div>
              </div>
            </div>
          </li>
        </ul>
      </main>
    </body></html>
    """

    rows = _run_extract_js(html, active=True)

    assert len(rows) == 1
    row = rows[0]
    assert row["item_id"] == "158093790272"
    assert row["status"] == "active"
    assert row["date_sold"] is None
    assert row["time_left"] == "1m (Today 3:52PM)"
    assert row["bids"] == 3
    assert row["format"] == "Auction"
    assert row["price"] == "250.00"
    assert row["shipping_price"] == "12.22"
    assert row["seller"] == "cloudstrife768"


def test_page_state_js_flags_dom_mismatch_as_not_zero_results():
    """If eBay changes its search-result markup again, the results container
    is present (page loaded) but the heading reports real matches -- this
    must NOT be treated as a legitimate zero-result search, so callers know
    to raise instead of silently returning an empty list."""
    html = """
    <html>
      <body>
        <main class="srp-river-main clearfix">
          <div class="srp-controls__count-heading">140,000+ results for HP 63XL</div>
          <!-- Intentionally no li.s-card items: simulates eBay changing the
               item markup again so the extractor's item selector no longer
               matches anything, even though real results exist. -->
        </main>
      </body>
    </html>
    """

    state = _run_page_state_js(html)

    assert state["container_exists"] is True
    assert state["zero_results"] is False
    assert state["heading_text"] == "140,000+ results for HP 63XL"


def test_page_state_js_recognizes_genuine_zero_results():
    """eBay's own '0 results for ...' heading is the only signal that should
    be treated as a legitimate empty search."""
    html = """
    <html>
      <body>
        <main class="srp-river-main clearfix">
          <div class="srp-controls__count-heading">0 results for asdkjhqwerkjhasdlkj12345</div>
        </main>
      </body>
    </html>
    """

    state = _run_page_state_js(html)

    assert state["container_exists"] is True
    assert state["zero_results"] is True


class _ColdProfileSearchPage:
    """A page that requires the verified eBay homepage-first search path."""

    def __init__(self):
        self.events = []

    def get_page(self, url):
        self.events.append(("get_page", url))
        return self

    def is_authenticated(self):
        self.events.append(("is_authenticated",))
        return True

    def wait_for_selector(self, selector, *, state, timeout):
        self.events.append(("wait_for_selector", selector, state, timeout))
        return object()

    def evaluate(self, script, params=None):
        if script != EXTRACT_JS:
            raise AssertionError("The search extractor used an unexpected script")
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
        self.events.append(("locator", selector))
        return self

    def count(self):
        return 0


class _HydratingSearchPage(_ColdProfileSearchPage):
    """A result container that attaches before its listing cards."""

    def __init__(self):
        super().__init__()
        self.items_attached = False

    def wait_for_selector(self, selector, *, state, timeout):
        result = super().wait_for_selector(
            selector,
            state=state,
            timeout=timeout,
        )
        if selector == SELECTORS["item"]:
            self.items_attached = True
        return result

    def evaluate(self, script, params=None):
        if script == EXTRACT_JS:
            if not self.items_attached:
                return []
            return super().evaluate(script, params)
        if script == PAGE_STATE_JS:
            return {
                "url": "https://www.ebay.com/sch/i.html?_nkw=lego+technic+lbs",
                "title": "Lego Technic Lbs for sale | eBay",
                "body_text_snippet": "318 results for lego technic lbs",
                "container_exists": True,
                "heading_text": "318 results for lego technic lbs",
                "zero_results": False,
            }
        raise AssertionError("The search used an unexpected script")


class _ZeroResultsSearchPage(_HydratingSearchPage):
    """A result container with an explicit zero-results heading."""

    def wait_for_selector(self, selector, *, state, timeout):
        if selector == SELECTORS["item"]:
            self.events.append(("wait_for_selector", selector, state, timeout))
            raise BrowserHarnessError("selector timed out")
        return super().wait_for_selector(selector, state=state, timeout=timeout)

    def evaluate(self, script, params=None):
        if script == EXTRACT_JS:
            return []
        if script == PAGE_STATE_JS:
            return {
                "url": "https://www.ebay.com/sch/i.html?_nkw=no-matches",
                "title": "No matches | eBay",
                "body_text_snippet": "0 results for no-matches",
                "container_exists": True,
                "heading_text": "0 results for no-matches",
                "zero_results": True,
            }
        raise AssertionError("The search used an unexpected script")


def test_should_warm_cold_profile_and_wait_for_listing_cards():
    """Live evidence showed a cold profile's direct search returned eBay's
    error page. A homepage request established the guest session. The search
    then crossed a transient interstitial and rendered the listing cards."""
    page = _ColdProfileSearchPage()
    client = EbayBrowserClient(config=object())
    client._browser = page

    results = client.search_active("LEGO complete set no box no instructions", limit=1)

    assert [result.item_id for result in results] == ["127992747834"]
    assert page.events[0] == ("get_page", "https://www.ebay.com")
    assert page.events[1] == (
        "wait_for_selector",
        SELECTORS["homepage_search_input"],
        "attached",
        SEARCH_RESULTS_TIMEOUT_MS,
    )
    assert page.events[2][0] == "get_page"
    assert page.events[2][1].startswith("https://www.ebay.com/sch/i.html?")
    assert page.events[3] == (
        "wait_for_selector",
        SELECTORS["item"],
        "attached",
        SEARCH_RESULTS_TIMEOUT_MS,
    )


def test_should_wait_for_listing_cards_when_container_attaches_first():
    """The extractor waits for card hydration after the container attaches."""
    page = _HydratingSearchPage()
    client = EbayBrowserClient(config=object())
    client._browser = page

    results = client.search_completed("lego technic lbs", limit=1)

    assert [result.item_id for result in results] == ["127992747834"]
    assert page.events[4] == (
        "wait_for_selector",
        SELECTORS["item"],
        "attached",
        SEARCH_RESULTS_TIMEOUT_MS,
    )


def test_search_keeps_explicit_zero_results_after_item_wait_timeout():
    """A timed out item wait returns empty only for eBay's zero heading."""
    page = _ZeroResultsSearchPage()
    client = EbayBrowserClient(config=object())
    client._browser = page

    results = client.search_completed("no-matches", limit=1)

    assert results == []
    assert page.events[4] == (
        "wait_for_selector",
        SELECTORS["item"],
        "attached",
        SEARCH_RESULTS_TIMEOUT_MS,
    )


def test_persistent_pardon_interruption_is_a_security_blocker():
    """The live cold-profile DOM used eBay's exact interstitial title."""
    with pytest.raises(BrowserError, match="CAPTCHA/security-verification"):
        EbayBrowserClient._raise_for_search_blocker(
            {
                "url": "https://www.ebay.com/sch/i.html?_nkw=LEGO",
                "title": "🐴 Pardon Our Interruption...",
                "body_text_snippet": "Pardon Our Interruption",
                "container_exists": False,
            }
        )
