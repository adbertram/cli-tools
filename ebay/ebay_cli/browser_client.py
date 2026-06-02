"""Browser-based eBay client for marketplace search.

Uses Playwright to scrape eBay search results for completed/sold listings,
which are not available via the public API (Terapeak partner restriction).
"""
import re
from typing import Any, Optional
from urllib.parse import urlencode

from cli_tools_shared.output import print_info, print_warning

from .browser import BrowserError, EbayBrowser
from .config import get_config
from .models.search_result import SearchResult


# CSS selectors for eBay search results page (2025+ s-card layout)
SELECTORS = {
    "results_container": ".srp-results",
    "item": "li.s-card",
    "title": ".s-card__title .su-styled-text",
    "price": ".s-card__price",
    "caption": ".s-card__caption .su-styled-text",
    "condition": ".s-card__subtitle .su-styled-text",
    "link": "a.s-card__link",
    "image": ".s-card__image",
    "next_page": "a.pagination__next",
}

# JavaScript to extract search results from the page
EXTRACT_JS = """() => {
    const cards = document.querySelectorAll('li.s-card');
    const results = [];

    for (const card of cards) {
        // Title
        const titleEl = card.querySelector('.s-card__title .su-styled-text');
        if (!titleEl) continue;
        const title = titleEl.textContent.trim();
        if (title === 'Shop on eBay' || title === 'Results matching fewer words') continue;

        // Item ID from data attribute or URL
        let itemId = card.dataset.listingid || '';
        const linkEl = card.querySelector('a.s-card__link[href*="/itm/"]');
        const url = linkEl ? linkEl.href : '';
        if (!itemId && url) {
            const idMatch = url.match(/itm\\/(?:[^/]*\\/)?(\\d+)|itm\\/(\\d+)/);
            itemId = idMatch ? (idMatch[1] || idMatch[2] || '') : '';
        }

        // Price
        const priceEl = card.querySelector('.s-card__price');
        let price = priceEl ? priceEl.textContent.trim() : '';
        const priceMatch = price.match(/[\\$\\u00A3\\u20AC]([\\d,\\.]+)/);
        price = priceMatch ? priceMatch[1].replace(',', '') : price;

        // Currency
        const currMatch = (priceEl ? priceEl.textContent : '').match(/([\\$\\u00A3\\u20AC])/);
        let currency = 'USD';
        if (currMatch) {
            if (currMatch[1] === '\\u00A3') currency = 'GBP';
            else if (currMatch[1] === '\\u20AC') currency = 'EUR';
        }

        // Caption: "Sold  Mar 9, 2026" or similar
        const captionEl = card.querySelector('.s-card__caption .su-styled-text');
        const captionText = captionEl ? captionEl.textContent.trim() : '';
        const isSold = captionText.toLowerCase().includes('sold');
        const status = isSold ? 'sold' : 'unsold';

        let dateSold = null;
        if (captionText) {
            const dateMatch = captionText.match(/(\\w+ \\d+, \\d{4})/);
            dateSold = dateMatch ? dateMatch[1] : null;
        }

        // Condition
        const condEl = card.querySelector('.s-card__subtitle .su-styled-text');
        const condition = condEl ? condEl.textContent.trim() : null;

        // Attribute rows: shipping, format, bids, seller
        const attrRows = card.querySelectorAll('.s-card__attribute-row');
        let shippingPrice = null;
        let format = null;
        let bids = null;
        let seller = null;

        for (const row of attrRows) {
            const text = row.textContent.trim();
            const textLower = text.toLowerCase();

            // Shipping
            if (textLower.includes('delivery') || textLower.includes('shipping')) {
                if (textLower.includes('free')) {
                    shippingPrice = '0.00';
                } else {
                    const shipMatch = text.match(/[\\$\\u00A3\\u20AC]([\\d,\\.]+)/);
                    shippingPrice = shipMatch ? shipMatch[1].replace(',', '') : null;
                }
            }

            // Format
            if (textLower.includes('buy it now') || textLower === 'or best offer') {
                format = 'Buy It Now';
            }

            // Bids
            const bidsMatch = text.match(/(\\d+)\\s*bid/i);
            if (bidsMatch) {
                bids = parseInt(bidsMatch[1]);
                format = 'Auction';
            }

            // Seller (pattern: "username NN% positive (N)")
            const sellerMatch = text.match(/^(\\S+)\\s+[\\d.]+%\\s+positive/);
            if (sellerMatch) {
                seller = sellerMatch[1];
            }
        }

        // Default format
        if (!format) {
            format = bids !== null ? 'Auction' : 'Buy It Now';
        }

        // Image
        const imgEl = card.querySelector('.s-card__image');
        const imageUrl = imgEl ? (imgEl.src || imgEl.dataset.src || null) : null;

        if (itemId && title) {
            results.push({
                item_id: itemId,
                title: title,
                price: price,
                currency: currency,
                shipping_price: shippingPrice,
                status: status,
                date_sold: dateSold,
                condition: condition,
                format: format,
                bids: bids,
                seller: seller,
                url: url,
                image_url: imageUrl,
            });
        }
    }

    return results;
}"""


class EbayBrowserClient:
    """Browser-based eBay client for marketplace search."""

    BASE_URL = "https://www.ebay.com"
    SEARCH_PATH = "/sch/i.html"

    def __init__(self, profile: Optional[str] = None, config: Optional[Any] = None):
        self.config = config or get_config(profile=profile)
        self._browser: Optional[EbayBrowser] = None

    @property
    def browser(self) -> EbayBrowser:
        """Lazy-initialize browser service."""
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        """Close browser service."""
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False

    def ensure_authenticated(self):
        """Ensure browser session is authenticated."""
        if not self.browser.is_authenticated():
            raise BrowserError(
                "No browser session found. Run 'ebay auth login --credential-type browser_session' first."
            )

    def search_completed(
        self,
        keywords: str,
        sold_only: bool = False,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        category: Optional[str] = None,
        condition: Optional[str] = None,
        limit: int = 50,
    ) -> list[SearchResult]:
        """Search eBay completed listings.

        Args:
            keywords: Search keywords
            sold_only: If True, only return sold items (not unsold)
            min_price: Minimum price filter
            max_price: Maximum price filter
            category: eBay category ID
            condition: Item condition filter
            limit: Maximum number of results to return

        Returns:
            List of SearchResult objects
        """
        self.ensure_authenticated()

        all_results = []
        page_num = 1
        max_pages = (limit // 240) + 2  # 240 items per page max

        while len(all_results) < limit and page_num <= max_pages:
            url = self._build_search_url(
                keywords=keywords,
                sold_only=sold_only,
                min_price=min_price,
                max_price=max_price,
                category=category,
                condition=condition,
                page=page_num,
            )

            print_info(f"Fetching page {page_num}...")

            # Navigate to search results
            page = self.browser.get_page()
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)  # Let results load

            # Extract results via JavaScript
            raw_results = page.evaluate(EXTRACT_JS)

            if not raw_results:
                break

            # Convert to SearchResult models
            for raw in raw_results:
                if len(all_results) >= limit:
                    break
                all_results.append(SearchResult(**raw))

            # Check if there's a next page
            next_btn = page.locator(SELECTORS["next_page"])
            if next_btn.count() == 0:
                break

            page_num += 1
            # Brief delay between pages
            page.wait_for_timeout(1000)

        return all_results[:limit]

    def _build_search_url(
        self,
        keywords: str,
        sold_only: bool = False,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        category: Optional[str] = None,
        condition: Optional[str] = None,
        page: int = 1,
    ) -> str:
        """Build eBay search URL with filters."""
        params = {
            "_nkw": keywords,
            "LH_Complete": "1",  # Completed listings
            "_ipg": "240",  # Items per page (max)
        }

        if sold_only:
            params["LH_Sold"] = "1"

        if min_price is not None:
            params["_udlo"] = str(min_price)

        if max_price is not None:
            params["_udhi"] = str(max_price)

        if category:
            params["_sacat"] = category

        if condition:
            # Map common condition names to eBay condition IDs
            condition_map = {
                "new": "1000",
                "open_box": "1500",
                "refurbished": "2000",
                "used": "3000",
                "for_parts": "7000",
            }
            cond_id = condition_map.get(condition.lower(), condition)
            params["LH_ItemCondition"] = cond_id

        if page > 1:
            params["_pgn"] = str(page)

        return f"{self.BASE_URL}{self.SEARCH_PATH}?{urlencode(params)}"


def get_browser_client(profile: Optional[str] = None, config: Optional[Any] = None) -> EbayBrowserClient:
    """Get an EbayBrowserClient instance."""
    return EbayBrowserClient(profile=profile, config=config)
