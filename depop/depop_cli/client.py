"""Depop client driving the Cloudflare-cleared browser session's authenticated fetch.

Why in-page fetch instead of a standalone HTTP client
------------------------------------------------------
Depop's public marketplace search
(`GET www.depop.com/presentation/api/v1/search/products/`) sits behind
Cloudflare Bot Management. A plain HTTP client (requests/httpx) cannot
replicate the TLS/JA3 + HTTP/2 fingerprint of the real Chrome instance that
earned the `cf_clearance` cookie, so replaying that raw cookie value from a
non-browser client would very likely get re-challenged. Instead we execute
the fetch INSIDE the live, Cloudflare-cleared browser page via
`page.evaluate()`, so the request carries the real browser's session cookies
(`credentials: 'include'`) and its real network stack — no cookie/header
transplant, no second HTTP stack to keep in sync.

Endpoint, query params, and enum values below were all validated live via a
CDP-driven real-Chrome session against the real depop.com search UI (network
capture + UI-driven filter selection) during CLI creation. None of this is
guessed:
  - Endpoint: GET https://www.depop.com/presentation/api/v1/search/products/
  - what=<query>, limit=<n>, after=<cursor>, country=us, currency=USD,
    from=in_country_search, include_like_count=true
  - price_min / price_max: plain numbers, US dollars (confirmed via the live
    Price filter UI -> price_min=15&price_max=60)
  - conditions: comma-joined enum, confirmed via the live Condition filter UI:
    brand_new, used_like_new, used_excellent, used_good, used_fair
  - gender: male | female | unisex (confirmed live; "men"/"women"/"kids" 400)
  - groups: category slug (confirmed via the live Category filter UI, e.g.
    Women > Coats and jackets -> groups=coats-jackets&gender=female).
    Matches each result's attributes.group value.
  - sort: confirmed via the live Sort dropdown -- relevance (default),
    priceAscending, priceDescending (camelCase; NOT price_ascending)
  - after=<page_info.last from the previous page> drives cursor pagination
    (confirmed: page 2 returns a disjoint result set from page 1)
The `depop-device-id` / `depop-search-id` / `depop-session-id` headers are
per-request client identifiers the web app generates; freshly generated
random UUIDs were accepted live, so each request mints its own.

Size filtering is intentionally NOT implemented: Depop's size taxonomy uses
nested per-category/region composite ids (e.g. "101.16-EUR") resolved from
`webapi.depop.com/presentation/api/v1/search/sizeFilters/`, not a flat enum.
Guessing a param here risked a silently no-op filter, which the CLI standards
forbid; use `--filter "sizes:contains:<Label>"` against a result's `sizes[]`
array instead.

Why not `cli_tools_shared.http_session.BrowserAutomationJsonClient`
--------------------------------------------------------------------
That shared helper already runs same-origin authenticated JSON fetches
through a `BrowserAutomation` page and is the right default for new browser
CLIs. It was not reused here because its built-in retry is a fixed linear
sleep and does not read `Retry-After` -- Step 9.4 of the CLI creation
workflow requires exponential backoff with `Retry-After` honored, and
`request_json()` doesn't expose the raw status/headers a caller would need
to layer that in. We DO reuse its retry policy: `RequestsRetryPolicy` (below)
is the same exponential-backoff-with-jitter formula every `requests`-backed
CLI in this repo uses, applied here to the in-page fetch's own timing.
"""

import json
import time
import uuid
from typing import List, Optional

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.http_session import (
    DEFAULT_REQUESTS_BASE_DELAY,
    DEFAULT_REQUESTS_JITTER,
    DEFAULT_REQUESTS_MAX_DELAY,
    DEFAULT_REQUESTS_MAX_RETRIES,
    DEFAULT_REQUESTS_RETRYABLE_STATUS_CODES,
    RequestsRetryPolicy,
)

from .config import get_config
from .parsers import normalize_items

SEARCH_PATH = "presentation/api/v1/search/products/"

CONDITION_VALUES = {
    "brand_new",
    "used_like_new",
    "used_excellent",
    "used_good",
    "used_fair",
}
GENDER_VALUES = {"male", "female", "unisex"}

# ---------------------------------------------------------------------------
# Sort (Source-CLI Sort Standard)
# ---------------------------------------------------------------------------
# Canonical user-facing sort vocabulary resolved to Depop's real (camelCase)
# API `sort` token. A `None` token means "omit the sort param" (Depop's own
# default relevance ordering).
#
# Recency-sort exception (verified live against the endpoint this CLI uses,
# `presentation/api/v1/search/products/`):
#   * Depop's documented recency value `newlyListed` is deterministically
#     blocked with a Cloudflare 403 on THIS endpoint (every attempt), so it is
#     not usable as a sort here — making it the default would break every bare
#     search.
#   * The endpoint SILENTLY IGNORES any unrecognized sort value (e.g.
#     `oldestListed`), returning plain relevance order — so there is no
#     oldest/newest chronological ordering available at all.
# Per the standard's recency-sort exception we therefore REJECT `--sort newest`
# with a clear error instead of silently returning non-chronological order, and
# keep `relevance` as the default. `price` is directional (natural low->high);
# `--desc` reverses it to high->low. `relevance` has no natural direction, so
# `--desc` is rejected with it.
DEFAULT_SORT = "relevance"

# user value -> (natural api token [no --desc], reversed api token [--desc])
_SORT_DIRECTIONS = {
    "price": ("priceAscending", "priceDescending"),
    "relevance": (None, None),
}
SORT_VALUES = tuple(_SORT_DIRECTIONS)  # ("price", "relevance")


class SortError(ClientError):
    """Raised for an invalid ``--sort``/``--desc`` combination."""


def resolve_sort(sort: str, desc: bool = False) -> Optional[str]:
    """Resolve a ``(--sort, --desc)`` pair to Depop's API ``sort`` token.

    Returns the camelCase API token, or ``None`` to omit the sort param
    (relevance / API default). Raises :class:`SortError` with a clear,
    valid-values message on any unrecognized value or unsupported direction;
    never silently falls back to a default.
    """
    key = (sort or "").strip().lower()
    if key == "newest":
        raise SortError(
            "Depop's search API has no usable chronological ('newest') sort: "
            "its recency value is blocked by Depop on the search endpoint this "
            "CLI uses, and no oldest/newest ordering is available. "
            f"Use one of: {', '.join(SORT_VALUES)}."
        )
    if key not in _SORT_DIRECTIONS:
        raise SortError(
            f"Invalid --sort '{sort}'. Valid values: {', '.join(SORT_VALUES)}."
        )
    natural, reversed_token = _SORT_DIRECTIONS[key]
    if desc:
        if reversed_token is None:
            raise SortError(
                f"--desc is not supported with --sort {key}: {key} has no "
                "reverse direction. Drop --desc, or use --sort price."
            )
        return reversed_token
    return natural

PAGE_SIZE = 100
MAX_PAGES = 20

_FETCH_JS = """async (opts) => {
    const resp = await fetch(opts.url, {
        credentials: 'include',
        headers: {
            'depop-device-id': opts.deviceId,
            'depop-search-id': opts.searchId,
            'depop-session-id': opts.sessionId,
            'content-type': 'application/json',
        },
    });
    const text = await resp.text();
    return {
        status: resp.status,
        statusText: resp.statusText,
        retryAfter: resp.headers.get('retry-after'),
        body: text,
    };
}"""


def _validate_choices(value, allowed, label: str) -> None:
    if value is not None and value not in allowed:
        raise ClientError(f"Unknown {label} {value!r}. Choose from: {', '.join(sorted(allowed))}.")


class DepopClient:
    """Drives the Cloudflare-cleared Depop web session and calls its search API."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_REQUESTS_MAX_RETRIES,
        base_delay: float = DEFAULT_REQUESTS_BASE_DELAY,
        max_delay: float = DEFAULT_REQUESTS_MAX_DELAY,
        jitter: float = DEFAULT_REQUESTS_JITTER,
    ):
        self.config = config or get_config()
        # Reuse the shared exponential-backoff-with-jitter policy (the same
        # formula every `requests`-backed CLI in this repo uses) instead of
        # re-deriving `base_delay * 2**attempt` locally. The policy itself has
        # no dependency on the `requests` library, so it applies equally to
        # this browser-page-driven fetch.
        self._retry_policy = RequestsRetryPolicy(
            max_retries=max_retries,
            base_delay=base_delay,
            max_delay=max_delay,
            jitter=jitter,
            retryable_status_codes=DEFAULT_REQUESTS_RETRYABLE_STATUS_CODES,
        )
        self._device_id = str(uuid.uuid4())
        self._browser = None

    def _get_browser(self):
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    def _require_cloudflare_clearance(self) -> None:
        """Fail fast with a clear fix when the profile has never cleared Cloudflare.

        A brand-new persistent profile has no `cf_clearance` cookie, so a
        headless-only fetch would otherwise surface as a raw HTTP 403 with no
        indication of the fix. `auth login` runs the one-time headed pass that
        earns the cookie.
        """
        if not self._get_browser().is_authenticated():
            raise ClientError(
                "No Cloudflare-cleared Depop session found. Run 'depop auth login' "
                "to open a one-time headed browser pass, then retry."
            )

    def _retry_after_seconds(self, raw: Optional[str]) -> Optional[float]:
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _fetch(self, url: str, home_url: str) -> dict:
        """Run the authenticated in-page fetch with exponential-backoff retry."""
        page = self._get_browser().get_page(home_url)
        policy = self._retry_policy
        last_exception: Optional[Exception] = None
        last_status = None
        last_body = ""
        for attempt in range(policy.max_retries + 1):
            try:
                result = page.evaluate(
                    _FETCH_JS,
                    {
                        "url": url,
                        "deviceId": self._device_id,
                        "searchId": str(uuid.uuid4()),
                        "sessionId": str(uuid.uuid4()),
                    },
                )
            except Exception as exc:  # browser-harness/network failure
                last_exception = exc
                if attempt < policy.max_retries:
                    time.sleep(policy.calculate_delay(attempt))
                    continue
                raise ClientError(
                    f"Depop search request failed after {attempt + 1} attempts: {exc}"
                ) from exc

            status = int(result.get("status") or 0)
            last_status = status
            last_body = str(result.get("body") or "")
            if status in policy.retryable_status_codes and attempt < policy.max_retries:
                time.sleep(
                    policy.calculate_delay(attempt, self._retry_after_seconds(result.get("retryAfter")))
                )
                continue
            if status != 200:
                raise ClientError(
                    f"Depop search HTTP {status} {result.get('statusText', '')}: {last_body[:300]}"
                )
            try:
                return json.loads(last_body)
            except (ValueError, TypeError) as exc:
                raise ClientError(f"Depop search returned non-JSON body: {exc}") from exc

        raise ClientError(
            f"Depop search request failed after retries (last status={last_status}): {last_exception}"
        )

    def _build_url(
        self,
        query: str,
        limit: int,
        after: str,
        price_min: Optional[float],
        price_max: Optional[float],
        condition: Optional[List[str]],
        gender: Optional[str],
        category: Optional[str],
        sort_param: Optional[str],
    ) -> str:
        params = [
            ("what", query),
            ("after", after),
            ("limit", str(limit)),
            ("country", "us"),
            ("currency", "USD"),
            ("from", "in_country_search"),
            ("include_like_count", "true"),
        ]
        if price_min is not None:
            params.append(("price_min", str(price_min)))
        if price_max is not None:
            params.append(("price_max", str(price_max)))
        if condition:
            params.append(("conditions", ",".join(condition)))
        if gender is not None:
            params.append(("gender", gender))
        if category is not None:
            params.append(("groups", category))
        if sort_param:
            params.append(("sort", sort_param))
        from urllib.parse import urlencode

        base_url = self.config.base_url.rstrip("/")
        return f"{base_url}/{SEARCH_PATH}?{urlencode(params)}"

    @cached
    def search_items(
        self,
        query: str,
        limit: int = 24,
        price_min: Optional[float] = None,
        price_max: Optional[float] = None,
        condition: Optional[List[str]] = None,
        gender: Optional[str] = None,
        category: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> List[dict]:
        """Search public Depop listings by keyword.

        Every filter is sent to the API itself (server-side); `limit` drives
        the requested page size / cursor-paginates rather than slicing a
        client-side list. `sort_param` is the already-resolved Depop API sort
        token (from :func:`resolve_sort`), or ``None`` to omit the sort param.
        """
        if condition:
            bad = [c for c in condition if c not in CONDITION_VALUES]
            if bad:
                raise ClientError(
                    f"Unknown condition(s) {bad}. Choose from: {', '.join(sorted(CONDITION_VALUES))}."
                )
        _validate_choices(gender, GENDER_VALUES, "gender")
        self._require_cloudflare_clearance()
        home_url = f"{self.config.base_url.rstrip('/')}/"

        items: List[dict] = []
        seen = set()
        after = ""
        pages = 0
        while len(items) < limit and pages < MAX_PAGES:
            page_size = min(PAGE_SIZE, limit - len(items))
            url = self._build_url(
                query, page_size, after, price_min, price_max, condition, gender, category, sort_param
            )
            body = self._fetch(url, home_url)
            for obj in body.get("objects", []):
                obj_id = obj.get("id")
                if obj_id in seen:
                    continue
                seen.add(obj_id)
                items.append(obj)
            page_info = body.get("page_info") or {}
            pages += 1
            if not page_info.get("has_more"):
                break
            after = page_info.get("last") or ""
            if not after:
                break

        return normalize_items(items[:limit])


_client: Optional[DepopClient] = None


def get_client() -> DepopClient:
    """Get or create the global Depop client instance."""
    global _client
    if _client is None:
        _client = DepopClient()
    return _client
