"""AuctionZip client driving the Cloudflare-cleared browser session.

AuctionZip search-results and lot pages are public server-rendered HTML (no JSON
API), but auctionzip.com sits behind Cloudflare Bot Management that returns a
hard 403 block page to every headless browser. This client therefore reads pages
through the persistent, Cloudflare-cleared `BrowserAutomation` session
(`page.content()` after navigation) rather than a raw HTTP client, so requests
carry the real browser's `cf_clearance` cookie and TLS/HTTP fingerprint. See
browser.py for the auth model.

The endpoints/paths below were validated live during CLI creation:
  - Search:  GET /search-results?query=<kw>   (server-rendered card list)
  - Lot:     GET /auction-lot/<slug>_<REF>     (server-rendered detail page)
Parsing is delegated to parsers.py (validated against real DOM fixtures).

Retry uses the shared exponential-backoff-with-jitter policy every requests-backed
CLI in this repo uses, applied here to the in-browser navigation + read.
"""

import time
from typing import List, Optional
from urllib.parse import quote_plus, urljoin

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.http_session import (
    DEFAULT_REQUESTS_BASE_DELAY,
    DEFAULT_REQUESTS_JITTER,
    DEFAULT_REQUESTS_MAX_DELAY,
    DEFAULT_REQUESTS_MAX_RETRIES,
    RequestsRetryPolicy,
)

from .config import get_config
from .parsers import parse_lot_detail, parse_search_results

SEARCH_PATH = "search-results"
LOT_PATH = "auction-lot"

# Signatures of Cloudflare's hard WAF block page (validated live).
_BLOCK_MARKERS = (
    "Attention Required! | Cloudflare",
    "Sorry, you have been blocked",
    "cf-error-details",
)


class AuctionzipClient:
    """Drives the Cloudflare-cleared AuctionZip web session and reads its pages."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_REQUESTS_MAX_RETRIES,
        base_delay: float = DEFAULT_REQUESTS_BASE_DELAY,
        max_delay: float = DEFAULT_REQUESTS_MAX_DELAY,
        jitter: float = DEFAULT_REQUESTS_JITTER,
    ):
        self.config = config or get_config()
        self._retry_policy = RequestsRetryPolicy(
            max_retries=max_retries,
            base_delay=base_delay,
            max_delay=max_delay,
            jitter=jitter,
        )
        self._browser = None

    def _get_browser(self):
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    def _require_saved_session(self) -> None:
        """Fail fast with a clear fix when the profile was never logged in.

        This is a static, non-navigating check (the persistent profile's Chrome
        cookie DB exists) — NOT the live ``is_authenticated()`` probe, which
        navigates the homepage and is subject to Cloudflare re-challenge timing.
        The live reality (a transient block or an expired session) is handled by
        ``_fetch_html``'s block-page detection + retry, which surfaces a clear
        re-auth error when a fetch is genuinely walled.
        """
        if not self.config.has_saved_session():
            raise ClientError(
                "No saved AuctionZip session found. Run 'auctionzip auth login' "
                "to open a one-time headed browser pass that clears Cloudflare, "
                "then retry."
            )

    @property
    def _base(self) -> str:
        return self.config.base_url.rstrip("/")

    def _fetch_html(self, url: str) -> tuple:
        """Navigate the cleared session to ``url`` and return ``(html, page_url)``.

        Retries transient browser/navigation failures and re-challenges with
        exponential backoff; surfaces a persistent Cloudflare block as a clear,
        actionable error rather than returning the block page as data.
        """
        policy = self._retry_policy
        last_error: Optional[Exception] = None
        for attempt in range(policy.max_retries + 1):
            try:
                page = self._get_browser().get_page(url)
                page.wait_for_timeout(1500)
                html = page.content()
                page_url = page.url
            except Exception as exc:  # browser-harness / navigation failure
                last_error = exc
                if attempt < policy.max_retries:
                    time.sleep(policy.calculate_delay(attempt))
                    continue
                raise ClientError(
                    f"AuctionZip request failed after {attempt + 1} attempts: {exc}"
                ) from exc

            if any(marker in html for marker in _BLOCK_MARKERS):
                if attempt < policy.max_retries:
                    time.sleep(policy.calculate_delay(attempt))
                    continue
                raise ClientError(
                    "AuctionZip served a Cloudflare block page. The saved session "
                    "may have expired — run 'auctionzip auth login --force' to "
                    "re-clear Cloudflare, then retry."
                )
            return html, page_url

        raise ClientError(
            f"AuctionZip request failed after retries: {last_error}"
        )

    def _resolve_lot_url(self, value: str) -> str:
        """Resolve a lot URL, path, ``slug_ref``, or bare ref into a full lot URL."""
        v = (value or "").strip()
        if not v:
            raise ClientError("A lot URL or reference is required.")
        if v.startswith("http://") or v.startswith("https://"):
            return v
        if v.startswith("/"):
            return urljoin(self._base + "/", v.lstrip("/"))
        if f"{LOT_PATH}/" in v:
            return urljoin(self._base + "/", v[v.index(LOT_PATH):])
        if "_" in v:
            return f"{self._base}/{LOT_PATH}/{v}"
        # Bare ref: AuctionZip routes on the trailing ref suffix, so a
        # placeholder slug still resolves to the canonical lot page.
        return f"{self._base}/{LOT_PATH}/lot_{v}"

    @cached
    def search(self, query: str, limit: int = 100) -> List[dict]:
        """Search public AuctionZip lots by keyword.

        Results are point-in-time (current bids/bid counts change); pass
        ``--no-cache`` for a fresh read.
        """
        self._require_saved_session()
        url = f"{self._base}/{SEARCH_PATH}?query={quote_plus(query)}"
        html, _ = self._fetch_html(url)
        return parse_search_results(html, self._base, limit=limit)

    @cached
    def get_item(self, item_id: str) -> dict:
        """Get full detail for a single lot by URL, ``slug_ref``, or bare ref.

        Bid, bid count, and status are point-in-time; pass ``--no-cache`` for a
        fresh read.
        """
        self._require_saved_session()
        url = self._resolve_lot_url(item_id)
        html, page_url = self._fetch_html(url)
        try:
            return parse_lot_detail(html, url=page_url or url)
        except ValueError as exc:
            raise ClientError(
                f"Could not read an AuctionZip lot at {page_url or url}: {exc}"
            ) from exc


_client: Optional[AuctionzipClient] = None


def get_client() -> AuctionzipClient:
    """Get or create the global AuctionZip client instance."""
    global _client
    if _client is None:
        _client = AuctionzipClient()
    return _client
