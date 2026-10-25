"""Amazon order evidence client using cli_tools_shared browser sessions."""

from __future__ import annotations

import re
from datetime import date as calendar_date
from typing import Optional
from urllib.parse import quote_plus, urlsplit

from cli_tools_shared.browser_evidence import (
    evidence_matches,
    get_text_record,
    text_records,
    visible_text_snapshot,
)
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import CredentialError
from cli_tools_shared.exceptions import ClientError

from .browser import AmazonBrowser
from .config import get_config

ORDERS_URL = "https://www.amazon.com/gp/css/order-history"
ORDER_SEARCH_URL = "https://www.amazon.com/gp/your-account/order-history?opt=ab&search={query}"
AUTH_BLOCKED_MESSAGE = (
    "AUTH_BLOCKED: amazon browser session is not authenticated. "
    "Run 'amazon auth login --force' to reauthenticate."
)


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

    def _require_authenticated_browser(self) -> AmazonBrowser:
        browser = self._get_browser()
        if not browser.is_authenticated():
            raise CredentialError(AUTH_BLOCKED_MESSAGE)
        return browser

    def _page_snapshot(self, url: str) -> dict:
        browser = self._require_authenticated_browser()
        page = browser.get_page(url)
        page.wait_for_timeout(3000)
        if not browser._check_auth(page):
            raise CredentialError(AUTH_BLOCKED_MESSAGE)
        return visible_text_snapshot(page)

    def _year_snapshot(self, year: int) -> dict:
        """Read complete order cards across the selected year's pages."""
        browser = self._require_authenticated_browser()
        url = f"https://www.amazon.com/your-orders/orders?timeFilter=year-{year}"
        visited = set()
        texts = []
        while url:
            if url in visited or urlsplit(url).hostname != "www.amazon.com":
                raise ClientError("Amazon order pagination returned an invalid or repeated page.")
            visited.add(url)
            page = browser.get_page(url)
            page.wait_for_timeout(2000)
            if not browser._check_auth(page):
                raise CredentialError(AUTH_BLOCKED_MESSAGE)
            data = page.evaluate("""() => ({
                texts: [...document.querySelectorAll('.js-order-card')].map(e => e.innerText),
                next: document.querySelector('.a-pagination .a-last a')?.href || null
            })""")
            if not isinstance(data, dict) or not isinstance(data.get("texts"), list) or not all(isinstance(text, str) for text in data["texts"]):
                raise ClientError("Amazon order cards could not be read.")
            texts.extend(data["texts"])
            url = data.get("next")
        return {"url": f"https://www.amazon.com/your-orders/orders?timeFilter=year-{year}",
                "title": "Your Orders", "texts": texts}

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
        snapshot = None
        match_date = date
        if date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) and not query:
            try:
                parsed_date = calendar_date.fromisoformat(date)
            except ValueError as exc:
                raise ClientError("Transaction date must be a valid ISO date.") from exc
            snapshot = self._year_snapshot(parsed_date.year)
            match_date = f"{parsed_date.strftime('%B')} {parsed_date.day}, {parsed_date.year}"
        rows = evidence_matches(
            snapshot if snapshot is not None else self._page_snapshot(url),
            amount=amount,
            date=match_date,
            query=query,
            limit=limit,
        )
        return [_with_reviewer_fields(row, date=date) for row in rows]


_client: Optional[AmazonClient] = None


def get_client() -> AmazonClient:
    """Get or create the global Amazon client instance."""
    global _client
    if _client is None:
        _client = AmazonClient()
    return _client


def _with_reviewer_fields(row: dict, *, date: str = None) -> dict:
    """Add reviewer-friendly field names derived from the evidence row."""
    enriched = dict(row)
    text = enriched.get("text")
    if text:
        enriched["summary"] = text
    if "score" in enriched:
        enriched["match_score"] = enriched["score"]
    if enriched.get("matched_amount") and text:
        enriched["total"] = text
    if text and (order_id := re.search(r"ORDER #\s*(\d{3}-\d{7}-\d{7})", text)):
        enriched["order_id"] = order_id.group(1)
        for label, field in (("ORDER PLACED", "order_date"), ("TOTAL", "total")):
            if match := re.search(rf"{label}\s*\n([^\n]+)", text):
                enriched[field] = match.group(1).strip()
    if date and text:
        matched_terms = {
            str(term).lower()
            for term in enriched.get("matched_terms", [])
        }
        if date.lower() in matched_terms:
            enriched["order_date"] = text
    return enriched
