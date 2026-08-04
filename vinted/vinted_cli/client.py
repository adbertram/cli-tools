"""Vinted API client.

Vinted publishes no usable public catalog API. The site's own front end calls
`GET /api/v2/catalog/items`, which needs no account.

Cloudflare fronts the site and challenges clients it does not trust, so a plain
HTTP client is walled. Every request therefore runs inside the saved Chrome
profile that `vinted auth login` cleared, which carries both the Cloudflare
clearance and the real browser fingerprint. The profile runs headless, so no
window opens after the first login.
"""

import json
import re
from typing import Dict, List, Optional
from urllib.parse import urlencode

from cli_tools_shared.data_cache import cached, invalidate
from cli_tools_shared.exceptions import ClientError

from .config import get_config
from .parsers import normalize_listing, parse_item_page, parse_shipping
from .rate_limit import THROTTLED_STATUS_CODES, RateLimiter, parse_retry_after

# A saved profile can still meet a fresh Cloudflare challenge. The challenge
# clears without interaction, but it can take most of a minute. The page owns
# the delay, so the wait is a count of attempts rather than a wall clock.
CHALLENGE_ATTEMPTS = 20
CHALLENGE_POLL_INTERVAL = 3000

# Vinted caps the catalog page size at 96 regardless of the requested value.
MAX_PER_PAGE = 96

# Vinted repeats listings across pages, so a page can add no new records. These
# two bounds stop one search from issuing thousands of requests.
MAX_PAGES = 50
MAX_LIMIT = MAX_PER_PAGE * MAX_PAGES
BARREN_PAGE_LIMIT = 2

# Canonical sort vocabulary mapped to the `order` values Vinted accepts.
# Each entry is (natural direction value, reversed direction value). A None
# reversed value means Vinted offers no reverse order for that field.
SORT_ORDERS = {
    "newest": ("newest_first", None),
    "price": ("price_low_to_high", "price_high_to_low"),
    "relevance": ("relevance", None),
}
DEFAULT_SORT = "newest"
VALID_SORT_FIELDS = list(SORT_ORDERS)

# Vinted condition identifiers, confirmed against live catalog responses.
CONDITION_IDS = {
    "new-with-tags": 6,
    "new-without-tags": 1,
    "very-good": 2,
    "good": 3,
    "satisfactory": 4,
}
VALID_CONDITIONS = list(CONDITION_IDS)

# Any slug redirects to the canonical item URL, so the CLI needs only the ID.
ITEM_SLUG_PLACEHOLDER = "item"

# A Vinted listing ID is digits only. Anything else would rewrite the request
# path, so the CLI rejects it instead of sending it.
ITEM_ID_PATTERN = re.compile(r"\A[0-9]+\Z")


def resolve_item_id(item_id: str) -> str:
    """Return a listing ID that is safe to place in a URL path."""
    if not isinstance(item_id, str) or not ITEM_ID_PATTERN.match(item_id):
        raise ValueError(
            f"Invalid listing ID {item_id!r}. A Vinted listing ID is digits only, "
            "for example 9571854910."
        )
    return item_id


def resolve_price_range(
    min_price: Optional[float],
    max_price: Optional[float],
) -> None:
    """Reject a price range Vinted would silently ignore."""
    for label, value in (("--min-price", min_price), ("--max-price", max_price)):
        if value is not None and value < 0:
            raise ValueError(f"{label} must be 0 or more, got {value}.")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ValueError(
            f"--min-price {min_price} is greater than --max-price {max_price}. "
            "Vinted ignores an impossible range and returns unfiltered results."
        )


def resolve_order(sort: str, desc: bool) -> str:
    """Translate the canonical sort field into a Vinted `order` value."""
    key = sort.lower()
    if key not in SORT_ORDERS:
        raise ValueError(
            f"Invalid --sort '{sort}'. Valid values: {', '.join(VALID_SORT_FIELDS)}"
        )
    natural, reversed_order = SORT_ORDERS[key]
    if not desc:
        return natural
    if reversed_order is None:
        raise ValueError(
            f"--desc is not available for --sort {key}. Vinted offers no reverse "
            f"order for {key}. Reverse order is available for: price."
        )
    return reversed_order


def sort_newest_first(rows: List[dict]) -> List[dict]:
    """Order listings strictly newest first.

    Vinted's own `newest_first` order is close but not exact. It injects some
    listings out of order, so the newest listing can arrive part way down the
    page. Sorting on the listing time makes the documented default order true.
    A listing with no time keeps its Vinted position at the end.
    """
    return sorted(
        rows,
        key=lambda row: (row["listed_at"] is not None, row["listed_at"] or ""),
        reverse=True,
    )


def resolve_condition_ids(conditions: Optional[List[str]]) -> Optional[str]:
    """Translate condition names into the Vinted `status_ids` parameter."""
    if not conditions:
        return None
    ids = []
    for condition in conditions:
        key = condition.lower()
        if key not in CONDITION_IDS:
            raise ValueError(
                f"Invalid --condition '{condition}'. Valid values: "
                f"{', '.join(VALID_CONDITIONS)}"
            )
        ids.append(str(CONDITION_IDS[key]))
    return ",".join(ids)


class VintedClient:
    """Client for the Vinted catalog API and public item pages."""

    # Runs inside the saved Chrome profile. `credentials: 'include'` carries the
    # Cloudflare clearance and the Vinted anon_id cookie, and the request keeps
    # the real browser fingerprint that Cloudflare accepts.
    _FETCH_JS = """
    async ({url, accept}) => {
      const anon = document.cookie.split('; ').find(c => c.startsWith('anon_id='));
      const headers = {'Accept': accept};
      if (anon) { headers['X-Anon-Id'] = decodeURIComponent(anon.slice(8)); }
      const r = await fetch(url, {credentials: 'include', headers});
      return {
        status: r.status,
        contentType: r.headers.get('content-type') || '',
        retryAfter: r.headers.get('retry-after'),
        url: r.url,
        text: await r.text(),
      };
    }
    """

    def __init__(self, config=None, limiter=None):
        self.config = config or get_config()
        self.base_url = self.config.base_url.rstrip("/")
        # One limiter for the whole session. Every request passes through it,
        # so the pace Vinted sees is the pace this object allows.
        self.limiter = limiter or RateLimiter()
        self._browser = None
        self._page = None

    def _cleared_page(self):
        """Return a page in the Chrome profile that passed the Cloudflare check."""
        if self._page is not None:
            return self._page

        browser = self.config.get_browser()
        if not browser.is_authenticated():
            raise ClientError(
                f"No saved Vinted browser session for {self.base_url}. "
                "Run 'vinted auth login' once. Cloudflare fronts Vinted and only "
                "a real browser window can clear its check."
            )
        self._browser = browser
        page = browser.get_page(f"{self.base_url}/")
        self._wait_for_challenge(page)
        self._page = page
        return page

    def _wait_for_challenge(self, page) -> None:
        """Block until the page holds the real site, not a challenge.

        A saved profile can still meet a fresh challenge, and the challenge
        clears on its own after a delay. Vinted sets `anon_id` only on a page
        that really rendered, so that cookie marks the real site.
        """
        state = None
        for attempt in range(CHALLENGE_ATTEMPTS):
            state = page.evaluate(
                "() => ({cleared: document.cookie.includes('anon_id='), title: document.title})"
            )
            if isinstance(state, dict) and state.get("cleared"):
                return
            if attempt == CHALLENGE_ATTEMPTS - 1:
                break
            page.wait_for_timeout(CHALLENGE_POLL_INTERVAL)
            page.goto(f"{self.base_url}/")

        title = state.get("title") if isinstance(state, dict) else state
        raise ClientError(
            f"Cloudflare did not clear {self.base_url}/ after {CHALLENGE_ATTEMPTS} "
            f"attempts (page title: {title!r}). "
            "Run 'vinted auth login --force' to refresh the session."
        )

    def close(self) -> None:
        """Close the browser session this client opened."""
        if self._browser is not None:
            self._browser.close()
            self._browser = None
            self._page = None

    def _fetch(self, url: str, params: Optional[Dict] = None, accept: str = "application/json") -> Dict:
        """Fetch one URL from inside the cleared browser profile.

        This is the only place the CLI sends a request, so the rate limiter
        gates every catalog page, item page, and shipping read. A throttled
        answer widens the pace and retries the same request.
        """
        full_url = f"{url}?{urlencode(params)}" if params else url
        for attempt in range(self.limiter.max_retries + 1):
            self.limiter.acquire()
            result = self._evaluate_fetch(full_url, accept)
            if result["status"] not in THROTTLED_STATUS_CODES:
                self.limiter.on_answered()
                break
            if attempt == self.limiter.max_retries:
                break
            self.limiter.on_throttled(attempt, parse_retry_after(result.get("retryAfter")))

        if not 200 <= result["status"] < 300:
            detail = (
                f"HTTP {result['status']}: GET {result['url']} "
                f"({result['contentType'] or 'no content type'})"
            )
            if result["status"] in THROTTLED_STATUS_CODES:
                detail += (
                    f". Vinted throttled the request and kept throttling it after "
                    f"{self.limiter.max_retries} backoff retries, up to "
                    f"{self.limiter.interval:.0f}s between requests. Wait a few "
                    "minutes, then use a smaller --limit."
                )
            raise ClientError(detail)
        return result

    def _evaluate_fetch(self, full_url: str, accept: str) -> Dict:
        """Run one fetch inside the browser page and validate its shape."""
        result = self._cleared_page().evaluate(
            self._FETCH_JS, {"url": full_url, "accept": accept}
        )
        if not isinstance(result, dict) or "status" not in result:
            raise ClientError(
                f"The browser returned no usable response for {full_url}: {result!r}"
            )
        return result

    def _json(self, url: str, params: Optional[Dict] = None) -> Dict:
        """GET a JSON endpoint and decode it.

        Cloudflare answers a bot check with an HTML page under HTTP 200.
        Decoding that raises a bare parser error that names neither Vinted nor
        the cause, so the content type is checked first.
        """
        result = self._fetch(url, params=params)
        if "application/json" not in result["contentType"]:
            raise ClientError(
                f"Vinted returned {result['contentType'] or 'no content type'} "
                f"instead of JSON for {result['url']}. This is usually a Cloudflare "
                "check. Run 'vinted auth login --force' to refresh the session."
            )
        try:
            return json.loads(result["text"])
        except ValueError as exc:
            raise ClientError(
                f"Vinted returned a body that is not valid JSON for {result['url']}: "
                f"{result['text'][:200]}"
            ) from exc

    def search_listings(
        self,
        query: Optional[str] = None,
        limit: int = 50,
        order: str = "newest_first",
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        currency: Optional[str] = None,
        status_ids: Optional[str] = None,
        catalog_ids: Optional[str] = None,
        brand_ids: Optional[str] = None,
        size_ids: Optional[str] = None,
        color_ids: Optional[str] = None,
    ) -> List[dict]:
        """Search the Vinted catalog and return normalized listing records.

        Every filter is sent to the API. The marketplace goes to `_search_pages`
        as an argument so the response cache cannot serve one country site's
        listings for another.
        """
        if limit < 1:
            raise ValueError(f"--limit must be 1 or more, got {limit}.")
        if limit > MAX_LIMIT:
            raise ValueError(
                f"--limit must be {MAX_LIMIT} or less, got {limit}. Vinted serves "
                f"{MAX_PER_PAGE} listings per page and the CLI reads at most "
                f"{MAX_PAGES} pages per search."
            )
        resolve_price_range(min_price, max_price)

        # Insertion order is fixed so the cache key for the same search is stable.
        params = {
            "search_text": query or "",
            "order": order,
            "per_page": min(limit, MAX_PER_PAGE),
        }
        optional = {
            "price_from": min_price,
            "price_to": max_price,
            "currency": currency,
            "status_ids": status_ids,
            "catalog_ids": catalog_ids,
            "brand_ids": brand_ids,
            "size_ids": size_ids,
            "color_ids": color_ids,
        }
        params.update({key: value for key, value in optional.items() if value is not None})
        rows = self._search_pages(self.base_url, params, limit)
        if order == SORT_ORDERS[DEFAULT_SORT][0]:
            rows = sort_newest_first(rows)
        if not rows:
            # Vinted answers a soft block with HTTP 200 and an empty item list.
            # Caching that would return "no results" for every identical search
            # until the entry expires, long after Vinted recovered.
            invalidate(self, "_search_pages", self.base_url, params, limit)
        return rows

    @cached
    def _search_pages(self, marketplace: str, params: Dict, limit: int) -> List[dict]:
        """Page the catalog endpoint until `limit` distinct listings are held.

        Vinted orders the catalog newest-first, so a listing added between two
        page requests shifts the offset window and repeats a listing on the
        next page. Records are kept unique by ID.
        """
        rows: List[dict] = []
        seen_ids = set()
        barren_pages = 0
        page = 1
        while len(rows) < limit and page <= MAX_PAGES:
            body = self._json(
                f"{marketplace}/api/v2/catalog/items",
                params={**params, "page": page},
            )
            items = body.get("items") or []
            if not items:
                break

            added = 0
            for item in items:
                record = normalize_listing(item)
                if record["id"] in seen_ids:
                    continue
                seen_ids.add(record["id"])
                rows.append(record)
                added += 1

            # A page of nothing but repeats means the feed has stopped yielding
            # new listings. Without this the loop runs to total_pages, which can
            # be thousands of requests for a handful of rows.
            barren_pages = 0 if added else barren_pages + 1
            if barren_pages >= BARREN_PAGE_LIMIT:
                break

            pagination = body.get("pagination") or {}
            total_pages = pagination.get("total_pages")
            # Vinted can omit total_pages or send null. Treat an unusable value
            # as "no further page", so the loop cannot compare int to None.
            if not isinstance(total_pages, int) or page >= total_pages:
                break
            page += 1

        return rows[:limit]

    def add_shipping(self, rows: List[dict]) -> List[dict]:
        """Attach the shipping summary to each listing.

        Neither the catalog endpoint nor the search results page carries
        shipping, so this reads one item page per listing. That is one extra
        request each, so the caller opts in. The rate limiter paces the reads.
        """
        for row in rows:
            row["shipping"] = self._listing_shipping(self.base_url, str(row["id"]))
        return rows

    @cached
    def _listing_shipping(self, marketplace: str, item_id: str) -> Optional[dict]:
        """Read one listing's shipping summary. `marketplace` keys the cache."""
        url = f"{marketplace}/items/{resolve_item_id(item_id)}-{ITEM_SLUG_PLACEHOLDER}"
        return parse_shipping(self._fetch(url, accept="text/html")["text"])

    def get_listing(self, item_id: str) -> dict:
        """Return one listing's detail from its public item page."""
        return self._get_listing(self.base_url, resolve_item_id(item_id))

    @cached
    def _get_listing(self, marketplace: str, item_id: str) -> dict:
        """Fetch and parse one item page. `marketplace` keys the cache entry."""
        url = f"{marketplace}/items/{item_id}-{ITEM_SLUG_PLACEHOLDER}"
        result = self._fetch(url, accept="text/html")
        return parse_item_page(result["text"], item_id, result["url"])


_client: Optional[VintedClient] = None


def get_client() -> VintedClient:
    """Get or create the global Vinted client instance."""
    global _client
    if _client is None:
        _client = VintedClient()
    return _client
