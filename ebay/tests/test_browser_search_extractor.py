"""Regression tests for the completed-listings browser extractor."""

from playwright.sync_api import sync_playwright

from ebay_cli.browser_client import EXTRACT_JS, SELECTORS


def test_extract_js_parses_current_su_item_card_layout():
    """The extractor reads the current eBay su-item-card completed-listing layout."""
    html = """
    <html>
      <body>
        <main class="srp-river-main clearfix">
          <div class="su-item-card s-item-card" data-listingid="2500219655424533">
            <a class="su-item-card__title" href="https://www.ebay.com/itm/123456">Shop on eBay</a>
            <span class="su-item-card__price">$20.00</span>
          </div>
          <ul class="su-grid su-grid--is-list">
            <li class="su-grid__item">
              <div class="su-item-card s-item-card" data-listingid="377305506170">
                <div class="su-card-container su-card-container--horizontal">
                  <div class="su-card-container__media">
                    <div class="su-image">
                      <img src="https://i.ebayimg.com/images/g/CIEAAeSwLi5qQxbw/s-l500.webp" />
                    </div>
                  </div>
                  <div class="su-card-container__content">
                    <div class="su-card-container__header">
                      <span class="signal signal--recent">SOLD JUL 5, 2026</span>
                      <div class="su-item-card__header">
                        <a class="su-link su-item-card__title"
                           href="https://www.ebay.com/itm/377305506170?_skw=HP+63XL">
                          New HP 63 XL Black Ink Printer Cartridge High Yield
                        </a>
                      </div>
                      <div class="su-item-card__subtitle">
                        <span class="su-styled-text secondary small clamped">Brand New</span>
                      </div>
                      <div class="su-item-card__price-container">
                        <span class="su-styled-text primary bold medium su-item-card__price">$45.00</span>
                      </div>
                    </div>
                    <div class="su-card-container__attributes">
                      <div class="su-card-container__attributes__primary">
                        <span class="su-styled-text primary default">Best offer accepted</span>
                        <span class="su-styled-text primary default">Free delivery</span>
                      </div>
                      <div class="su-card-container__attributes__secondary">
                        <span class="su-styled-text default">scarbalde_0 98.6% positive (69)</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </li>
            <li class="su-grid__item">
              <div class="su-item-card s-item-card" data-listingid="267717942253">
                <span class="signal">ENDED JUL 4, 2026</span>
                <a class="su-link su-item-card__title"
                   href="https://www.ebay.com/itm/267717942253?_skw=HP+63XL">
                  HP 63XL Ink Cartridge - Black
                </a>
                <div class="su-item-card__subtitle">Open Box</div>
                <span class="su-item-card__price">$27.99</span>
                <div class="su-card-container__attributes__primary">
                  <span class="su-styled-text primary default">+$8.60 delivery in 2-4 days</span>
                  <span class="su-styled-text primary default">3 bids</span>
                </div>
                <div class="su-card-container__attributes__secondary">
                  <span class="su-styled-text default">letsdeal108 100% positive (1.9K)</span>
                </div>
              </div>
            </li>
          </ul>
        </main>
      </body>
    </html>
    """

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        rows = page.evaluate(EXTRACT_JS, SELECTORS)
        browser.close()

    assert rows == [
        {
            "item_id": "377305506170",
            "title": "New HP 63 XL Black Ink Printer Cartridge High Yield",
            "price": "45.00",
            "currency": "USD",
            "shipping_price": "0.00",
            "status": "sold",
            "date_sold": "Jul 5, 2026",
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
            "condition": "Open Box",
            "format": "Auction",
            "bids": 3,
            "seller": "letsdeal108",
            "url": "https://www.ebay.com/itm/267717942253?_skw=HP+63XL",
            "image_url": None,
        },
    ]
