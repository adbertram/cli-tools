"""Fast HTTP helpers for commands backed by browser authentication.

These utilities fetch cookies live from the running browser-harness daemon
via ``BrowserAutomation.live_cookies()`` so read-only commands can make
direct HTTP requests using the same cookies the user's browser session
holds. The persistent Chromium user-data-dir is the single source of
truth; there is no on-disk snapshot.
"""

from __future__ import annotations

import gzip
import time
import zlib
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .exceptions import ClientError


DEFAULT_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


class BrowserAuthStateError(ClientError):
    """Raised when saved browser auth state is missing or invalid."""


@dataclass(frozen=True)
class BrowserCookie:
    """A validated cookie entry from browser auth state."""

    name: str
    value: str
    domain: str
    path: str
    expires: float


@dataclass(frozen=True)
class BrowserAuthState:
    """Live browser auth state.

    Cookies are read live from the running browser-harness daemon via CDP
    (``config.get_browser().live_cookies()``). The persistent Chromium
    user-data-dir is the single source of truth — there is no on-disk
    ``auth-state.json`` snapshot.
    """

    cookies: tuple[BrowserCookie, ...]
    origins: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_config(cls, config) -> "BrowserAuthState":
        """Fetch cookies live from the configured browser.

        Calls ``config.get_browser().live_cookies()``. Raises
        ``BrowserAuthStateError`` when no browser is configured or the
        live cookie list is empty (no session — fail fast, no fallback).
        """
        browser = config.get_browser() if hasattr(config, "get_browser") else None
        if browser is None:
            raise BrowserAuthStateError(
                "Config does not expose a browser (config.get_browser() is None)."
            )
        raw_cookies = browser.live_cookies()
        if not raw_cookies:
            tool_name = getattr(config, "_tool_name", "<tool>")
            raise BrowserAuthStateError(
                f"No browser session for {tool_name}. "
                f"Run '{tool_name} auth login'."
            )
        cookies = tuple(_parse_cookie(item) for item in raw_cookies)
        return cls(cookies=cookies, origins=())

    def cookies_for_host(
        self,
        hostname: str,
        allowed_domains: Sequence[str],
        now: float | None = None,
    ) -> tuple[BrowserCookie, ...]:
        """Return non-expired cookies that apply to ``hostname``."""
        if not allowed_domains:
            raise BrowserAuthStateError("At least one allowed cookie domain is required.")
        checked_at = time.time() if now is None else now
        normalized_allowed = tuple(_normalize_domain(domain) for domain in allowed_domains)
        normalized_host = _normalize_domain(hostname)

        selected = []
        for cookie in self.cookies:
            if _cookie_expired(cookie, checked_at):
                continue
            cookie_domain = _normalize_domain(cookie.domain)
            if not any(_cookie_domain_allowed(cookie_domain, domain) for domain in normalized_allowed):
                continue
            if not _cookie_applies_to_host(cookie_domain, normalized_host):
                continue
            selected.append(cookie)
        return tuple(selected)

    def cookie_header_for_url(
        self,
        url: str,
        allowed_domains: Sequence[str],
        required_cookies: Sequence[str] = (),
        now: float | None = None,
    ) -> str:
        """Build a Cookie header for ``url`` from saved browser state."""
        hostname = urlparse(url).hostname
        if not hostname:
            raise BrowserAuthStateError(f"URL does not contain a hostname: {url}")
        cookies = self.cookies_for_host(hostname, allowed_domains, now=now)
        return _cookie_header(cookies, allowed_domains, required_cookies)

@dataclass
class BrowserAuthenticatedHttpClient:
    """Direct HTTP client using cookies from saved browser auth state."""

    auth_state: BrowserAuthState
    allowed_domains: Sequence[str]
    required_cookies: Sequence[str] = ()
    timeout: float = 10.0
    headers: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_BROWSER_HEADERS))
    opener: Callable[..., Any] = urlopen

    def get_text(
        self,
        url: str,
        headers: Mapping[str, str] | None = None,
        stop_after_markers: Sequence[str] = (),
        chunk_size: int = 65536,
        encoding: str = "utf-8",
    ) -> str:
        """GET ``url`` and return response text.

        When ``stop_after_markers`` is supplied, response streaming stops after
        every marker appears in the bytes read so far.
        """
        request_headers = dict(self.headers)
        if headers is not None:
            request_headers.update(headers)
        request_headers["Cookie"] = self.auth_state.cookie_header_for_url(
            url, self.allowed_domains, required_cookies=self.required_cookies,
        )
        request = Request(url, headers=request_headers)
        try:
            with self.opener(request, timeout=self.timeout) as response:
                if response.status != 200:
                    raise ClientError(f"HTTP {response.status} returned for {url}")
                raw = _read_response(response, stop_after_markers, chunk_size, encoding)
                raw = _decode_response_body(raw, response.headers.get("Content-Encoding"))
        except HTTPError as exc:
            raise ClientError(f"HTTP {exc.code} returned for {url}") from exc
        except URLError as exc:
            raise ClientError(f"HTTP request failed for {url}: {exc.reason}") from exc
        return raw.decode(encoding)


def _parse_cookie(raw: Any) -> BrowserCookie:
    if not isinstance(raw, dict):
        raise BrowserAuthStateError("Browser auth state contains a non-object cookie.")
    _require_keys(raw, ("name", "value", "domain", "path", "expires"), "cookie")
    name = _required_str(raw, "name", "cookie")
    value = _required_str(raw, "value", "cookie")
    domain = _required_str(raw, "domain", "cookie")
    path = _required_str(raw, "path", "cookie")
    expires = raw["expires"]
    if not isinstance(expires, (int, float)):
        raise BrowserAuthStateError("Browser auth state cookie expires must be numeric.")
    return BrowserCookie(name=name, value=value, domain=domain, path=path, expires=float(expires))


def _required_str(data: Mapping[str, Any], key: str, label: str) -> str:
    value = data[key]
    if not isinstance(value, str):
        raise BrowserAuthStateError(f"Browser auth state {label} {key} must be a string.")
    return value


def _require_keys(data: Mapping[str, Any], keys: Sequence[str], label: str) -> None:
    missing = [key for key in keys if key not in data]
    if missing:
        raise BrowserAuthStateError(f"Browser auth state {label} is missing: {', '.join(missing)}.")


def _normalize_domain(domain: str) -> str:
    if not isinstance(domain, str) or not domain:
        raise BrowserAuthStateError("Cookie domain must be a non-empty string.")
    return domain.lstrip(".").lower()


def _cookie_expired(cookie: BrowserCookie, now: float) -> bool:
    return 0 < cookie.expires < now


def _cookie_domain_allowed(cookie_domain: str, allowed_domain: str) -> bool:
    return cookie_domain == allowed_domain or cookie_domain.endswith("." + allowed_domain)


def _cookie_applies_to_host(cookie_domain: str, hostname: str) -> bool:
    return hostname == cookie_domain or hostname.endswith("." + cookie_domain)


def _cookie_header(
    cookies: Sequence[BrowserCookie],
    allowed_domains: Sequence[str],
    required_cookies: Sequence[str],
) -> str:
    found_names = {cookie.name for cookie in cookies}
    missing = [name for name in required_cookies if name not in found_names]
    if missing:
        raise BrowserAuthStateError(
            "Saved browser auth state is missing required cookies: " + ", ".join(missing)
        )
    if not cookies:
        raise BrowserAuthStateError(
            "Saved browser auth state has no usable cookies for domains: "
            + ", ".join(allowed_domains)
        )
    return "; ".join(f"{cookie.name}={cookie.value}" for cookie in cookies)


def _read_response(response, stop_after_markers, chunk_size, encoding) -> bytes:
    markers = tuple(marker.encode(encoding) for marker in stop_after_markers)
    raw_body = bytearray()
    while True:
        chunk = response.read(chunk_size)
        if not chunk:
            break
        raw_body.extend(chunk)
        if markers and all(marker in raw_body for marker in markers):
            break
    return bytes(raw_body)


def _decode_response_body(raw_body: bytes, content_encoding: str | None) -> bytes:
    if content_encoding is None:
        return raw_body
    normalized = content_encoding.strip().lower()
    if normalized in ("", "identity"):
        return raw_body
    if normalized == "gzip":
        return gzip.decompress(raw_body)
    if normalized == "deflate":
        return zlib.decompress(raw_body)
    raise ClientError(f"Unsupported HTTP content encoding: {content_encoding}")
