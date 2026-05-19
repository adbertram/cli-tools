"""Pipedrive client using shared browser session tooling."""
from typing import List, Optional, Sequence
from urllib.parse import urljoin, urlparse

from cli_tools_shared.http_session import BrowserAuthState, BrowserAuthenticatedHttpClient
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .config import get_config
from .parsers import extract_items_from_snapshot
from .models import Item, ItemDetail, create_item, create_item_detail


class PipedriveClient:
    """Client that uses shared browser auth plus fast saved-session HTTP reads."""

    def __init__(self):
        self.config = get_config()
        self._browser_instance = None
        self._http_client: Optional[BrowserAuthenticatedHttpClient] = None

    @property
    def _browser(self):
        """Lazily load the BrowserAutomation subclass."""
        if self._browser_instance is None:
            self._browser_instance = self.config.get_browser()
        return self._browser_instance

    def _browser_http_client(self) -> BrowserAuthenticatedHttpClient:
        """Get a direct HTTP client using cookies from the saved browser session."""
        if self._http_client is None:
            hostname = urlparse(self.config.base_url).hostname
            if not hostname:
                raise ClientError(f"BASE_URL does not contain a hostname: {self.config.base_url}")
            self._http_client = BrowserAuthenticatedHttpClient(
                auth_state=BrowserAuthState.from_config(self.config),
                allowed_domains=[hostname],
                timeout=10,
            )
        return self._http_client

    def _url(self, path: str) -> str:
        """Build an absolute URL from a site-relative path."""
        return urljoin(self.config.base_url.rstrip("/") + "/", path.lstrip("/"))

    def _fetch_authenticated_text(
        self,
        url: str,
        stop_after_markers: Sequence[str] = (),
    ) -> str:
        """Fetch authenticated page text without launching Chromium."""
        return self._browser_http_client().get_text(
            url,
            stop_after_markers=stop_after_markers,
        )

    def _get_page(self, url: str, settle_ms: int = 2000):
        """Open a BrowserAutomation page only when rendered DOM interaction is required."""
        page = self._browser.get_page(url)
        if settle_ms:
            page.wait_for_timeout(settle_ms)
        return page

    def _snapshot(self, page) -> str:
        """Take an accessibility tree snapshot and return YAML content."""
        try:
            raw_page = page._get_page()
            return raw_page.locator("body").aria_snapshot()
        except Exception as exc:
            raise ClientError(f"Failed to capture page snapshot: {exc}") from exc

    def close(self):
        """Close the browser session if this command opened one."""
        if self._browser_instance is not None:
            self._browser_instance.close()
            self._browser_instance = None

    # ==================== Domain-Specific Methods ====================
    # Implement these methods for your specific site.
    # All methods return Pydantic models for type safety.
    #
    # Browser performance rule:
    # 1. Use _fetch_authenticated_text() first for read-only commands.
    # 2. Parse embedded JSON or static HTML locally.
    # 3. Use _get_page() only when the page requires rendered DOM interaction.
    #
    # Caching: Add @cached to read-only methods (list, get, search).
    # On cache hit, the method body is skipped entirely.
    # Do NOT cache write methods (create, update, delete).
    # See: references/caching.md

    @cached
    def search(
        self,
        query: str,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Item]:
        """Search for items on Pipedrive.

        TODO: Implement for your site. Prefer direct HTTP:
            html = self._fetch_authenticated_text(self._url(f"/search?q={query}"))
            raw = extract_items_from_snapshot(html)
            return [create_item(d) for d in raw[:limit]]

        If the site only renders data after JavaScript:
            page = self._get_page(self._url(f"/search?q={query}"))
            snapshot = self._snapshot(page)
            raw = extract_items_from_snapshot(snapshot)
            return [create_item(d) for d in raw[:limit]]
        """
        raise NotImplementedError("Implement search for Pipedrive")

    @cached
    def get_item(self, item_id: str) -> ItemDetail:
        """Get details for a specific item.

        TODO: Implement for your site. Prefer direct HTTP:
            html = self._fetch_authenticated_text(self._url(f"/item/{item_id}"))
            raw = extract_items_from_snapshot(html)
            return create_item_detail(raw[0]) if raw else create_item_detail({"id": item_id})
        """
        raise NotImplementedError("Implement get_item for Pipedrive")

    @cached
    def list_items(
        self,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Item]:
        """List items from Pipedrive.

        TODO: Implement for your site. Prefer direct HTTP:
            html = self._fetch_authenticated_text(self._url("/items"))
            raw = extract_items_from_snapshot(html)
            return [create_item(d) for d in raw[:limit]]
        """
        raise NotImplementedError("Implement list_items for Pipedrive")


_client: Optional[PipedriveClient] = None


def get_client() -> PipedriveClient:
    """Get or create the global Pipedrive client instance."""
    global _client
    if _client is None:
        _client = PipedriveClient()
    return _client
