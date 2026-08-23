"""Fast HTTP helpers for commands backed by browser authentication.

These utilities fetch cookies from the active authentication profile so
read-only commands can make direct HTTP requests using the same cookies the
browser session holds. Browser-backed profiles may persist a verified
``AUTH_COOKIES_JSON`` value; profiles without that value read cookies live from
the running browser-harness daemon via ``BrowserAutomation.live_cookies()``.
"""

from __future__ import annotations

import gzip
import json
import random
import time
import zlib
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import requests

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
DEFAULT_BROWSER_JSON_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# ---------------------------------------------------------------------------
# requests-session retry policy
#
# Exponential-backoff-with-jitter retry for clients built on the ``requests``
# library. This is the shared replacement for the per-CLI ``_calculate_retry_delay``
# / ``_is_retryable`` / ``_get_retry_after`` helpers that several tools had copied
# verbatim. (``BrowserAutomationJsonClient`` below keeps its own simpler linear
# retry because it drives requests through a browser page, not ``requests``.)
# ---------------------------------------------------------------------------

DEFAULT_REQUESTS_MAX_RETRIES = 3
DEFAULT_REQUESTS_BASE_DELAY = 1.0
DEFAULT_REQUESTS_MAX_DELAY = 30.0
DEFAULT_REQUESTS_JITTER = 0.1
DEFAULT_REQUESTS_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# Transport-level exceptions that are safe to retry (the request never reached a
# response, so retrying cannot duplicate a server-side effect mid-stream).
RETRYABLE_REQUEST_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


@dataclass(frozen=True)
class RequestsRetryPolicy:
    """Retry decisions for ``requests``-backed HTTP clients.

    Encapsulates everything that a retry loop needs to decide: which HTTP status
    codes and transport exceptions are retryable, how long to back off
    (exponential growth with bounded jitter, capped at ``max_delay``), and how to
    honor a server ``Retry-After`` header. Drive a single request through the
    policy with :func:`request_with_retry`.
    """

    max_retries: int = DEFAULT_REQUESTS_MAX_RETRIES
    base_delay: float = DEFAULT_REQUESTS_BASE_DELAY
    max_delay: float = DEFAULT_REQUESTS_MAX_DELAY
    jitter: float = DEFAULT_REQUESTS_JITTER
    retryable_status_codes: frozenset[int] = DEFAULT_REQUESTS_RETRYABLE_STATUS_CODES

    def calculate_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """Seconds to wait before the retry following ``attempt`` (0-based).

        A server-provided ``retry_after`` wins (still capped at ``max_delay``).
        Otherwise the delay is ``base_delay * 2**attempt`` plus proportional
        ``+/- jitter`` noise, capped at ``max_delay``.
        """
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)
        return min(delay, self.max_delay)

    def is_retryable_response(self, response: requests.Response) -> bool:
        """True when ``response`` carries a retryable HTTP status code."""
        return response.status_code in self.retryable_status_codes

    def is_retryable_exception(self, exception: BaseException) -> bool:
        """True when a transport ``exception`` is safe to retry."""
        return isinstance(exception, RETRYABLE_REQUEST_EXCEPTIONS)

    def retry_after_seconds(self, response: requests.Response) -> Optional[float]:
        """Parse the ``Retry-After`` header as seconds; ``None`` if absent/invalid."""
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None


def request_with_retry(
    send: Callable[[], requests.Response],
    policy: RequestsRetryPolicy,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> requests.Response:
    """Call ``send`` until it yields a non-retryable response or attempts run out.

    ``send`` performs one HTTP attempt and returns its ``requests.Response``;
    callers own request construction inside it (headers, auth/token refresh,
    cookies). The final response is returned even when it still carries a
    retryable status after retries are exhausted — callers inspect
    ``response.ok`` themselves. If every attempt raised a retryable transport
    exception and none produced a response, the last exception propagates so the
    caller can wrap it in its own error type.
    """
    last_response: Optional[requests.Response] = None
    last_exception: Optional[BaseException] = None

    for attempt in range(policy.max_retries + 1):
        try:
            response = send()
            last_response = response
            if policy.is_retryable_response(response) and attempt < policy.max_retries:
                sleep(policy.calculate_delay(attempt, policy.retry_after_seconds(response)))
                continue
            return response
        except requests.exceptions.RequestException as exc:
            last_exception = exc
            if policy.is_retryable_exception(exc) and attempt < policy.max_retries:
                sleep(policy.calculate_delay(attempt))
                continue
            break

    if last_response is not None:
        return last_response
    if last_exception is not None:
        raise last_exception
    raise ClientError("request_with_retry made no attempts; max_retries must be >= 0.")


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
    user-data-dir is the single source of truth.
    """

    cookies: tuple[BrowserCookie, ...]
    origins: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_config(cls, config) -> "BrowserAuthState":
        """Fetch cookies from the profile or from the configured browser.

        Uses ``AUTH_COOKIES_JSON`` when the active profile stores verified
        cookies. Otherwise calls ``config.get_browser().live_cookies()``. Raises
        ``BrowserAuthStateError`` when no browser is configured or the
        live cookie list is empty (no session — fail fast, no fallback).
        """
        stored_cookie_json = None
        getter = getattr(config, "_get", None)
        if callable(getter):
            stored_cookie_json = getter("AUTH_COOKIES_JSON")
        if stored_cookie_json is not None:
            if not isinstance(stored_cookie_json, str):
                raise BrowserAuthStateError("AUTH_COOKIES_JSON must be a string.")
            try:
                raw_cookies = json.loads(stored_cookie_json)
            except json.JSONDecodeError as exc:
                raise BrowserAuthStateError("AUTH_COOKIES_JSON is not valid JSON.") from exc
            if not isinstance(raw_cookies, list) or not raw_cookies:
                raise BrowserAuthStateError("AUTH_COOKIES_JSON must contain a non-empty cookie list.")
            return cls(cookies=tuple(_parse_cookie(item) for item in raw_cookies), origins=())

        browser = config.get_browser() if hasattr(config, "get_browser") else None
        if browser is None:
            raise BrowserAuthStateError(
                "Config does not expose a browser (config.get_browser() is None)."
            )
        try:
            raw_cookies = browser.live_cookies()
        finally:
            if hasattr(browser, "close"):
                browser.close()
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


@dataclass(frozen=True)
class BrowserHttpResult:
    """Text response plus timing data for instrumentation."""

    url: str
    status: int
    text: str
    bytes_read: int
    elapsed_seconds: float


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
        return self.get_text_result(
            url,
            headers=headers,
            stop_after_markers=stop_after_markers,
            chunk_size=chunk_size,
            encoding=encoding,
        ).text

    def get_text_result(
        self,
        url: str,
        headers: Mapping[str, str] | None = None,
        stop_after_markers: Sequence[str] = (),
        chunk_size: int = 65536,
        encoding: str = "utf-8",
    ) -> BrowserHttpResult:
        """GET ``url`` and return response text with timing metadata."""
        request = Request(url, headers=self._headers_for_url(url, headers))
        return self._open_text_result(request, stop_after_markers, chunk_size, encoding)

    def post_form_text(
        self,
        url: str,
        form: Mapping[str, str],
        headers: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
    ) -> str:
        """POST URL-encoded form data and return response text."""
        return self.post_form_result(url, form, headers=headers, encoding=encoding).text

    def post_form_result(
        self,
        url: str,
        form: Mapping[str, str],
        headers: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
    ) -> BrowserHttpResult:
        """POST URL-encoded form data and return text with timing metadata."""
        _validate_string_mapping(form, "form")
        request_headers = self._headers_for_url(url, headers)
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = Request(
            url,
            data=urlencode(dict(form)).encode(encoding),
            headers=request_headers,
            method="POST",
        )
        return self._open_text_result(request, (), 65536, encoding)

    def _headers_for_url(
        self,
        url: str,
        headers: Mapping[str, str] | None,
    ) -> dict[str, str]:
        request_headers = dict(self.headers)
        if headers is not None:
            _validate_string_mapping(headers, "headers")
            request_headers.update(headers)
        request_headers["Cookie"] = self.auth_state.cookie_header_for_url(
            url,
            self.allowed_domains,
            required_cookies=self.required_cookies,
        )
        return request_headers

    def _open_text_result(
        self,
        request: Request,
        stop_after_markers: Sequence[str],
        chunk_size: int,
        encoding: str,
    ) -> BrowserHttpResult:
        started = time.perf_counter()
        try:
            with self.opener(request, timeout=self.timeout) as response:
                if response.status != 200:
                    raise ClientError(f"HTTP {response.status} returned for {request.full_url}")
                raw = _read_response(response, stop_after_markers, chunk_size, encoding)
                wire_bytes = len(raw)
                raw = _decode_response_body(raw, response.headers.get("Content-Encoding"))
        except HTTPError as exc:
            raise ClientError(f"HTTP {exc.code} returned for {request.full_url}") from exc
        except URLError as exc:
            raise ClientError(f"HTTP request failed for {request.full_url}: {exc.reason}") from exc
        return BrowserHttpResult(
            url=request.full_url,
            status=response.status,
            text=raw.decode(encoding),
            bytes_read=wire_bytes,
            elapsed_seconds=time.perf_counter() - started,
        )


@dataclass
class BrowserAutomationJsonClient:
    """Execute same-origin JSON requests through a BrowserAutomation session."""

    browser: Any
    origin: str
    retry_sleep: Callable[[float], None] = time.sleep
    max_attempts: int = 3
    retryable_status_codes: set[int] = field(
        default_factory=lambda: set(DEFAULT_BROWSER_JSON_RETRYABLE_STATUS_CODES)
    )
    csrf_cookie_name: str | None = "csrftoken"
    csrf_header_name: str = "X-CSRFToken"
    extra_headers: Mapping[str, str] = field(default_factory=dict)

    def request_json(self, method: str, path: str, json_body: Any = None) -> Any:
        """Request JSON from a same-origin browser session endpoint."""
        method = self._validate_method(method)
        self._validate_path(path)
        result = self._run_fetch_with_retry(method, path, json_body)
        status = result["status"]
        text = result["text"]
        if status < 200 or status >= 300:
            detail = text[:500] if text else result["statusText"]
            raise ClientError(f"Browser JSON request failed with HTTP {status}: {detail}")
        if text == "":
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ClientError(f"Browser JSON response was not valid JSON for {method} {path}.") from exc

    def _run_fetch_with_retry(self, method: str, path: str, json_body: Any) -> dict[str, Any]:
        for attempt in range(self.max_attempts):
            result = self._run_fetch(method, path, json_body)
            if result["status"] not in self.retryable_status_codes:
                return result
            if attempt == self.max_attempts - 1:
                return result
            self.retry_sleep(float(attempt + 1))
        raise ClientError("Browser JSON retry loop exited unexpectedly.")

    def _run_fetch(self, method: str, path: str, json_body: Any) -> dict[str, Any]:
        payload = json.dumps({
            "method": method,
            "path": path,
            "jsonBody": json_body,
            "origin": self._origin(),
            "csrfCookieName": self.csrf_cookie_name,
            "csrfHeaderName": self.csrf_header_name,
            "extraHeaders": dict(self.extra_headers),
        })
        code = f"""
async () => {{
  const request = {payload};
  const headers = {{
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    ...request.extraHeaders
  }};
  const options = {{
    method: request.method,
    credentials: "include",
    headers
  }};
  if (request.jsonBody !== null) {{
    if (request.csrfCookieName !== null) {{
      const prefix = request.csrfCookieName + "=";
      const csrf = document.cookie.split("; ").find((cookie) => cookie.startsWith(prefix));
      if (!csrf) {{
        throw new Error("CSRF cookie is required for browser writes: " + request.csrfCookieName);
      }}
      headers[request.csrfHeaderName] = decodeURIComponent(csrf.slice(prefix.length));
    }}
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(request.jsonBody);
  }}
  const response = await fetch(request.path, options);
  return {{
    status: response.status,
    statusText: response.statusText,
    text: await response.text()
  }};
}}
""".strip()
        page = self.browser.get_page(self._origin() + "/")
        try:
            evaluation = page.page_eval(code)
        except Exception as exc:
            raise ClientError(f"Browser JSON page evaluation failed: {exc}") from exc
        if not isinstance(evaluation, dict) or "result" not in evaluation:
            raise ClientError("Browser JSON page evaluation did not return a result.")
        result = evaluation["result"]
        if not isinstance(result, dict):
            raise ClientError("Browser JSON page evaluation result must be an object.")
        for field_name in ("status", "statusText", "text"):
            if field_name not in result:
                raise ClientError(f"Browser JSON result missing field: {field_name}")
        return result

    def _origin(self) -> str:
        parsed = urlparse(self.origin)
        if not parsed.scheme or not parsed.netloc:
            raise ClientError(f"Browser JSON origin must include scheme and host: {self.origin}")
        return self.origin.rstrip("/")

    def _validate_method(self, method: str) -> str:
        if not isinstance(method, str) or not method:
            raise ClientError("Browser JSON request method must be a non-empty string.")
        normalized = method.upper()
        if normalized not in {"GET", "PATCH", "POST", "PUT", "DELETE"}:
            raise ClientError(f"Unsupported browser JSON request method: {normalized}")
        return normalized

    def _validate_path(self, path: str) -> None:
        if not isinstance(path, str) or not path.startswith("/"):
            raise ClientError("Browser JSON request path must start with '/'.")


@dataclass(frozen=True)
class RelayFormRequest:
    """A Relay/GraphQL form POST with JSON variables."""

    endpoint: str
    operation_name: str
    document_id: str
    variables: Mapping[str, Any]
    base_fields: Mapping[str, str]
    operation_name_field: str = "fb_api_req_friendly_name"
    document_id_field: str = "doc_id"
    variables_field: str = "variables"

    def form_fields(self) -> dict[str, str]:
        """Build URL-encoded form fields for the Relay request."""
        _validate_string_mapping(self.base_fields, "base_fields")
        fields = dict(self.base_fields)
        fields[self.operation_name_field] = self.operation_name
        fields[self.document_id_field] = self.document_id
        fields[self.variables_field] = json.dumps(self.variables, separators=(",", ":"))
        return fields


@dataclass(frozen=True)
class RelayGraphQLClient:
    """Execute Relay form POSTs through ``BrowserAuthenticatedHttpClient``."""

    http: BrowserAuthenticatedHttpClient

    def execute(
        self,
        request: RelayFormRequest,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Execute a Relay request and parse streamed JSON object responses."""
        body = self.http.post_form_text(request.endpoint, request.form_fields(), headers=headers)
        return tuple(iter_json_objects(body))


def decode_json_at_marker(text: str, marker: str) -> Any:
    """Decode the first JSON value whose first character matches ``marker``."""
    for value in iter_json_values_at_marker(text, marker):
        return value
    raise ClientError(f"JSON marker not found: {marker}")


def iter_json_values_at_marker(text: str, marker: str) -> Iterable[Any]:
    """Yield JSON values decoded at each occurrence of ``marker``."""
    if not marker:
        raise ClientError("JSON marker must not be empty.")

    decoder = json.JSONDecoder()
    index = 0
    while True:
        start = text.find(marker, index)
        if start < 0:
            return
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError as exc:
            raise ClientError(f"Failed to decode JSON at marker: {marker}") from exc
        yield value
        index = end


def extract_embedded_define(text: str, name: str, payload_index: int = 2) -> dict[str, Any]:
    """Extract a dict payload from an embedded ``[name, ..., payload]`` array."""
    value = decode_json_at_marker(text, f'["{name}",')
    if not isinstance(value, list):
        raise ClientError(f"Embedded define {name} is not a JSON array.")
    if len(value) <= payload_index:
        raise ClientError(f"Embedded define {name} does not contain payload index {payload_index}.")
    payload = value[payload_index]
    if not isinstance(payload, dict):
        raise ClientError(f"Embedded define {name} payload is not a JSON object.")
    return payload


def iter_json_objects(text: str) -> Iterable[dict[str, Any]]:
    """Yield concatenated or newline-delimited JSON objects from ``text``."""
    decoder = json.JSONDecoder()
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            return
        value, end = decoder.raw_decode(text, index)
        if not isinstance(value, dict):
            raise ClientError("Expected a JSON object in streamed response.")
        yield value
        index = end


def required_path(
    data: Any,
    path: Sequence[str | int],
    expected_type: type | tuple[type, ...] | None = None,
) -> Any:
    """Read a nested dict/list path and fail if any segment is missing."""
    current = data
    rendered = []
    for segment in path:
        rendered.append(str(segment))
        if isinstance(segment, str):
            if not isinstance(current, dict):
                raise ClientError(f"Expected object before {'.'.join(rendered)}.")
            if segment not in current:
                raise ClientError(f"Missing required path: {'.'.join(rendered)}.")
            current = current[segment]
        elif isinstance(segment, int):
            if not isinstance(current, list):
                raise ClientError(f"Expected list before {'.'.join(rendered)}.")
            if segment < 0 or segment >= len(current):
                raise ClientError(f"Missing required path: {'.'.join(rendered)}.")
            current = current[segment]
        else:
            raise ClientError(f"Path segment must be str or int, got {type(segment).__name__}.")

    if expected_type is not None and not isinstance(current, expected_type):
        raise ClientError(
            f"Expected {'.'.join(rendered)} to be {_type_name(expected_type)}, "
            f"got {type(current).__name__}."
        )
    return current


def _validate_string_mapping(value: Mapping[str, str], label: str) -> None:
    for key, item in value.items():
        if not isinstance(key, str):
            raise ClientError(f"{label} keys must be strings, got {type(key).__name__}.")
        if not isinstance(item, str):
            raise ClientError(f"{label}.{key} must be a string, got {type(item).__name__}.")


def _type_name(expected_type: type | tuple[type, ...]) -> str:
    if isinstance(expected_type, tuple):
        return " or ".join(item.__name__ for item in expected_type)
    return expected_type.__name__


def _parse_cookie(raw: Any) -> BrowserCookie:
    if not isinstance(raw, dict):
        raise BrowserAuthStateError("Browser auth state contains a non-object cookie.")
    _require_keys(raw, ("name", "value", "domain", "path"), "cookie")
    name = _required_str(raw, "name", "cookie")
    value = _required_str(raw, "value", "cookie")
    domain = _required_str(raw, "domain", "cookie")
    path = _required_str(raw, "path", "cookie")
    expires = raw.get("expires", -1)
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
