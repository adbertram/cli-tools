"""Poshmark client using BrowserAutomation from cli_tools_shared."""

import time
from typing import List, Optional

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .browser import PoshmarkBrowser
from .config import get_config
from .parsers import normalize_items


EXTRACT_LISTINGS_JS = """
() => {
  const listings = [];
  const cards = document.querySelectorAll('.tile-grid-redesign');
  cards.forEach((card) => {
    const link = card.querySelector('a[href*="/listing/"]');
    const titleEl = card.querySelector('.tile-grid-redesign__title');
    const priceEl = card.querySelector('.tile-grid-redesign__price-current');
    const sizeEl = card.querySelector('.tile-grid-redesign__size');
    const img = card.querySelector('img');
    listings.push({
      id: card.getAttribute('data-et-prop-listing_id') || '',
      lister_id: card.getAttribute('data-et-prop-lister_id') || '',
      title: titleEl ? titleEl.textContent.trim() : (img ? img.getAttribute('alt') || '' : ''),
      price: priceEl ? priceEl.textContent.trim() : '',
      size: sizeEl ? sizeEl.textContent.trim() : '',
      href: link ? link.getAttribute('href') || '' : '',
      image: img ? img.getAttribute('src') || '' : '',
    });
  });
  return listings;
}
"""

SCROLL_JS = "() => { window.scrollBy(0, document.body.scrollHeight); return document.body.scrollHeight; }"


class PoshmarkClient:
    """Client that uses BrowserAutomation to drive Poshmark."""

    def __init__(self):
        self.config = get_config()
        self._browser: Optional[PoshmarkBrowser] = None

    def _get_browser(self) -> PoshmarkBrowser:
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    @cached
    def search(self, query: str, limit: int = 100, sort_by: str = "added_desc") -> List[dict]:
        """Search Poshmark listings for ``query`` and return up to ``limit`` results.

        ``sort_by`` is a Poshmark ``?sort_by=`` value (e.g. ``added_desc``,
        ``price_asc``, ``price_desc``, ``relevance_v2``) resolved from the
        ``--sort``/``--desc`` flags by ``main._resolve_sort``.
        """
        encoded = query.replace(" ", "+").replace("&", "%26")
        url = f"{self.config.base_url}/search?query={encoded}&sort_by={sort_by}"
        browser = self._get_browser()
        page = browser.get_page(url)
        page.wait_for_selector(".tile-grid-redesign", timeout=30000)
        results: List[dict] = []
        last_count = 0
        unchanged_rounds = 0
        max_scroll_rounds = 20
        for _ in range(max_scroll_rounds):
            raw = page.evaluate(EXTRACT_LISTINGS_JS)
            if not isinstance(raw, list):
                raise ClientError("Unexpected response from Poshmark search page.")
            results = normalize_items(raw)
            if len(results) >= limit:
                break
            if len(results) == last_count:
                unchanged_rounds += 1
                if unchanged_rounds >= 2:
                    break
            else:
                unchanged_rounds = 0
            last_count = len(results)
            page.evaluate(SCROLL_JS)
            time.sleep(1.5)
        return results[:limit]

_client: Optional[PoshmarkClient] = None


def get_client() -> PoshmarkClient:
    """Get or create the global Poshmark client instance."""
    global _client
    if _client is None:
        _client = PoshmarkClient()
    return _client
