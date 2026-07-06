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


# CSS selectors for eBay search results page (2026 su-item-card layout)
SELECTORS = {
    "results_container": ".srp-river-main",
    "item": "div.su-item-card.s-item-card[data-listingid]",
    "title": "a.su-item-card__title",
    "price": ".su-item-card__price",
    "caption": ".signal",
    "condition": ".su-item-card__subtitle",
    "link": "a.su-item-card__title[href*='/itm/']",
    "image": ".su-image img",
    "attributes_primary": ".su-card-container__attributes__primary .su-styled-text",
    "attributes_secondary": ".su-card-container__attributes__secondary .su-styled-text",
    "next_page": "a.pagination__next",
}

SEARCH_CONDITION_ALIASES = {
    "new": "1000",
    "open_box": "1500",
    "refurbished": "2000",
    "used": "3000",
    "for_parts": "7000",
}
SEARCH_CONDITION_HELP = (
    "Item condition ("
    + ", ".join(SEARCH_CONDITION_ALIASES)
    + ", or eBay condition ID)"
)

# JavaScript to extract search results from the page
EXTRACT_JS = """(selectors) => {
    const cards = document.querySelectorAll(selectors.item);
    const results = [];
    const seenItemIds = new Set();

    function cleanText(el) {
        return el ? el.textContent.replace(/\\s+/g, ' ').trim() : '';
    }

    function cleanCardText(el) {
        return el ? el.innerText.replace(/\\s+/g, ' ').trim() : '';
    }

    function parsePrice(text) {
        const match = text.match(/[\\$\\u00A3\\u20AC]([\\d,]+(?:\\.\\d{2})?)/);
        return match ? match[1].replace(/,/g, '') : text.trim();
    }

    function parseCurrency(text) {
        const currMatch = text.match(/([\\$\\u00A3\\u20AC])/);
        if (!currMatch) return 'USD';
        if (currMatch[1] === '\\u00A3') return 'GBP';
        if (currMatch[1] === '\\u20AC') return 'EUR';
        return 'USD';
    }

    function normalizeDate(text) {
        const match = text.match(/\\b(?:sold|ended)\\s+(.+)/i);
        if (!match) return null;
        return match[1].replace(/\\b[A-Z]{3}\\b/g, (month) => (
            month.charAt(0) + month.slice(1).toLowerCase()
        ));
    }

    for (const card of cards) {
        const titleEl = card.querySelector(selectors.title);
        if (!titleEl) continue;
        const title = cleanText(titleEl);
        if (title === 'Shop on eBay' || title === 'Results matching fewer words') continue;

        const itemId = card.getAttribute('data-listingid') || '';
        if (!itemId || seenItemIds.has(itemId)) continue;
        seenItemIds.add(itemId);

        const linkEl = card.querySelector(selectors.link);
        const url = linkEl ? linkEl.href : '';

        const priceEl = card.querySelector(selectors.price);
        const priceText = cleanText(priceEl);
        const price = parsePrice(priceText);
        const currency = parseCurrency(priceText);

        const captionEl = card.querySelector(selectors.caption);
        const captionText = cleanText(captionEl);
        const isSold = captionText.toLowerCase().includes('sold');
        const status = isSold ? 'sold' : 'unsold';
        const dateSold = normalizeDate(captionText);

        const condEl = card.querySelector(selectors.condition);
        const condition = cleanText(condEl) || null;

        const fullText = cleanCardText(card);
        const attributeEls = card.querySelectorAll(selectors.attributes_primary);
        let shippingPrice = null;
        let format = null;
        let bids = null;
        let seller = null;

        for (const attrEl of attributeEls) {
            const text = cleanText(attrEl);
            const textLower = text.toLowerCase();

            if (textLower.includes('delivery') || textLower.includes('shipping')) {
                if (textLower.includes('free')) {
                    shippingPrice = '0.00';
                } else {
                    const shipMatch = text.match(/[\\$\\u00A3\\u20AC]([\\d,\\.]+)/);
                    shippingPrice = shipMatch ? shipMatch[1].replace(/,/g, '') : null;
                }
            }

            if (textLower.includes('best offer')) {
                format = 'Best Offer';
            } else if (textLower.includes('buy it now')) {
                format = 'Buy It Now';
            }
        }

        const bidsMatch = fullText.match(/(\\d+)\\s*bid/i);
        if (bidsMatch) {
            bids = parseInt(bidsMatch[1], 10);
            format = 'Auction';
        }

        const sellerEl = card.querySelector(selectors.attributes_secondary);
        const sellerText = cleanText(sellerEl);
        const sellerMatch = sellerText.match(/^(\\S+)\\s+[\\d.]+%\\s+positive/);
        if (sellerMatch) {
            seller = sellerMatch[1];
        }

        if (!format) {
            format = bids !== null ? 'Auction' : 'Buy It Now';
        }

        const imgEl = card.querySelector(selectors.image);
        const imageUrl = imgEl ? (imgEl.src || imgEl.dataset.src || null) : null;

        if (title && price && url) {
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
            raw_results = page.evaluate(EXTRACT_JS, SELECTORS)

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
            cond_id = SEARCH_CONDITION_ALIASES.get(condition.lower(), condition)
            params["LH_ItemCondition"] = cond_id

        if page > 1:
            params["_pgn"] = str(page)

        return f"{self.BASE_URL}{self.SEARCH_PATH}?{urlencode(params)}"


def get_browser_client(profile: Optional[str] = None, config: Optional[Any] = None) -> EbayBrowserClient:
    """Get an EbayBrowserClient instance."""
    return EbayBrowserClient(profile=profile, config=config)
