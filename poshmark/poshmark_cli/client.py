"""Poshmark client using BrowserAutomation from cli_tools_shared."""

import time
import re
from typing import List, Optional
from urllib.parse import urlparse

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .browser import PoshmarkBrowser
from .config import get_config
from .parsers import normalize_item_detail, normalize_items


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

EXTRACT_LISTING_DETAIL_JS = r"""
() => {
  const bodyText = (document.body?.innerText || '').trim();
  const productScript = Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
    .find((element) => (element.textContent || '').includes('"@type":"Product"'));
  const sellerLink = Array.from(document.querySelectorAll('a[href*="/closet/"]'))
    .find((element) => (element.textContent || '').trim());
  const shippingElement = Array.from(document.querySelectorAll('body *'))
    .find((element) => element.children.length === 0 && /^(?:\$[\d,.]+|Free) Shipping$/i.test((element.textContent || '').trim()));
  const lines = bodyText.split('\n').map((value) => value.trim()).filter(Boolean);
  const sizeIndex = lines.indexOf('SIZE');
  return {
    page_url: window.location.href,
    login_required: /\/login(?:\?|$)/.test(window.location.pathname) || Boolean(document.querySelector('input[type="password"], form[action*="login"]')),
    human_challenge: /captcha|verify you are human|turnstile|access denied/i.test(bodyText),
    product: productScript ? JSON.parse(productScript.textContent) : null,
    seller_name: sellerLink ? (sellerLink.textContent || '').trim() : '',
    shipping_text: shippingElement ? (shippingElement.textContent || '').trim() : '',
    size: sizeIndex >= 0 ? lines[sizeIndex + 1] : null,
  };
}
"""


class ListingDetailBlocked(ClientError):
    """A page state that requires a human or a fresh browser login."""

    def __init__(self, blocker_type: str, message: str, url: str):
        super().__init__(message)
        self.blocker_type = blocker_type
        self.url = url

    def as_dict(self) -> dict:
        return {
            "blocked": True,
            "blocker_type": self.blocker_type,
            "blocker": str(self),
            "url": self.url,
        }


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

    @cached
    def get_listing(self, listing_id_or_url: str) -> dict:
        """Get one listing detail by ID or direct URL through the CLI browser profile."""
        if re.fullmatch(r"[0-9a-fA-F]{24}", listing_id_or_url):
            listing_url = f"{self.config.base_url}/listing/{listing_id_or_url.lower()}"
        else:
            listing_url = listing_id_or_url
            parsed = urlparse(listing_url)
            if parsed.scheme != "https" or parsed.netloc not in {"poshmark.com", "www.poshmark.com"} or not parsed.path.startswith("/listing/"):
                raise ClientError("Expected a 24-character listing ID or direct https://poshmark.com/listing/... URL.")

        page = self._get_browser().get_page(listing_url)
        page.wait_for_selector(
            'script[type="application/ld+json"]',
            state="attached",
            timeout=30000,
        )
        raw = page.evaluate(EXTRACT_LISTING_DETAIL_JS)
        if not isinstance(raw, dict):
            raise ClientError("Unexpected response from Poshmark listing page.")
        page_url = str(raw.get("page_url") or listing_url)
        if raw.get("human_challenge") is True:
            raise ListingDetailBlocked(
                "human_challenge",
                "Poshmark displayed a CAPTCHA or human-verification challenge.",
                page_url,
            )
        if raw.get("login_required") is True:
            raise ListingDetailBlocked(
                "authentication_required",
                "Poshmark redirected the saved browser profile to login.",
                page_url,
            )
        return normalize_item_detail(raw)

_client: Optional[PoshmarkClient] = None


def get_client() -> PoshmarkClient:
    """Get or create the global Poshmark client instance."""
    global _client
    if _client is None:
        _client = PoshmarkClient()
    return _client
