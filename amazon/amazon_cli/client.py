"""Amazon order evidence client using cli_tools_shared browser sessions."""

from __future__ import annotations

from typing import Optional
from urllib.parse import quote_plus

from cli_tools_shared.browser_evidence import (
    evidence_matches,
    get_text_record,
    text_records,
    visible_text_snapshot,
)
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .browser import AmazonBrowser
from .config import get_config

ORDERS_URL = "https://www.amazon.com/gp/css/order-history"
ORDER_SEARCH_URL = "https://www.amazon.com/gp/your-account/order-history?opt=ab&search={query}"


class AmazonClient:
    """Read-only evidence lookup from Amazon order pages."""

    def __init__(self):
        self.config = get_config()
        self._browser: Optional[AmazonBrowser] = None

    def _get_browser(self) -> AmazonBrowser:
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    def _page_snapshot(self, url: str) -> dict:
        browser = self._get_browser()
        page = browser.get_page(url)
        page.wait_for_timeout(3000)
        if not browser._check_auth(page):
            raise ClientError("Saved Amazon browser session is not authenticated.")
        return visible_text_snapshot(page)

    @cached
    def list_orders(self, limit: int = 100) -> list[dict]:
        """List visible text evidence from the Amazon orders page."""
        return text_records(self._page_snapshot(ORDERS_URL), limit)

    @cached
    def get_order_line(self, record_id: str) -> dict:
        """Get one visible text evidence line by line id."""
        return get_text_record(self._page_snapshot(ORDERS_URL), record_id)

    @cached
    def match_order(self, amount: str = None, date: str = None, query: str = None, limit: int = 10) -> list[dict]:
        """Find Amazon order evidence matching amount, date, or query."""
        url = ORDER_SEARCH_URL.format(query=quote_plus(query)) if query else ORDERS_URL
        return evidence_matches(
            self._page_snapshot(url),
            amount=amount,
            date=date,
            query=query,
            limit=limit,
        )


_client: Optional[AmazonClient] = None


def get_client() -> AmazonClient:
    """Get or create the global Amazon client instance."""
    global _client
    if _client is None:
        _client = AmazonClient()
    return _client
