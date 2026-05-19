"""ManageEngine client for inspecting the configured affiliate program page."""
import re
from html import unescape
from typing import List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

import requests

from cli_tools_shared.http_session import BrowserAuthState, BrowserAuthenticatedHttpClient
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .config import get_config
from .models import Item, ItemDetail, create_item, create_item_detail


class ManageengineClient:
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

    def _fetch_public_text(self, url: str) -> str:
        """Fetch a public program page without requiring an authenticated session."""
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15,
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            raise ClientError(f"Failed to fetch page {url}: {exc}") from exc

    def _extract_page_payload(self, html_text: str, url: str) -> Tuple[dict, str]:
        """Extract the primary page metadata as a typed item payload."""
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
        title = unescape(title_match.group(1)).strip() if title_match else ""

        description = ""
        for pattern in (
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
        ):
            match = re.search(pattern, html_text, re.IGNORECASE | re.DOTALL)
            if match:
                description = unescape(match.group(1)).strip()
                break

        canonical_match = re.search(
            r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\'](.*?)["\']',
            html_text,
            re.IGNORECASE | re.DOTALL,
        )
        canonical_url = canonical_match.group(1).strip() if canonical_match else url

        body_text = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", html_text)
        body_text = re.sub(r"(?s)<[^>]+>", " ", body_text)
        body_text = unescape(re.sub(r"\s+", " ", body_text)).strip()
        body_excerpt = body_text[:500]

        item_name = title or canonical_url
        item_description = description or body_excerpt or None
        hostname = urlparse(canonical_url).hostname or "page"
        payload = {
            "id": canonical_url,
            "name": item_name,
            "status": "active",
            "description": item_description,
            "tags": [hostname],
        }
        haystack = " ".join(part for part in [item_name, item_description, body_excerpt] if part).lower()
        return payload, haystack

    @cached
    def search(
        self,
        query: str,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Item]:
        """Match a query against the configured page title and description."""
        html_text = self._fetch_public_text(self.config.base_url)
        payload, haystack = self._extract_page_payload(html_text, self.config.base_url)
        if query.lower() not in haystack:
            return []
        return [create_item(payload)][:limit]

    @cached
    def get_item(self, item_id: str) -> ItemDetail:
        """Fetch metadata for the configured page or a specific absolute URL."""
        url = item_id if item_id.startswith(("http://", "https://")) else self._url(item_id)
        html_text = self._fetch_public_text(url)
        payload, haystack = self._extract_page_payload(html_text, url)
        payload["metadata"] = {
            "url": url,
            "preview": haystack[:280],
        }
        return create_item_detail(payload)

    @cached
    def list_items(
        self,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Item]:
        """Return the configured program page as a single typed item."""
        html_text = self._fetch_public_text(self.config.base_url)
        payload, _ = self._extract_page_payload(html_text, self.config.base_url)
        return [create_item(payload)][:limit]


_client: Optional[ManageengineClient] = None


def get_client() -> ManageengineClient:
    """Get or create the global Manageengine client instance."""
    global _client
    if _client is None:
        _client = ManageengineClient()
    return _client
