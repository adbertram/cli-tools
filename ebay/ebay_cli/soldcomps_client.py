"""SoldComps API client for eBay marketplace search (sold comps + active listings).

eBay restricts completed-listing search to Terapeak partners and exposes no
public API for active-listing discovery, so this CLI used to scrape
``/sch/i.html`` through a signed-in stealth browser. SoldComps
(``api.sold-comps.com``) sells that same data as a hosted API, which removes the
browser session, the CAPTCHA/interstitial walls, and the markup dependency from
the search path entirely. Single-item lookups (``listings get`` /
``listings status``) still scrape ``/itm/<id>`` — see ``browser_client.py``.

Quota is the binding constraint on the Starter plan (2,000 requests/month), so:

* completed/sold search is cached — a listing that ended last Tuesday will still
  have ended last Tuesday tomorrow — while active search never is, because its
  whole value is "what is live right now";
* every page of a paginated search costs one request, and a ``--limit`` above
  one page's worth says so on stderr before it spends them;
* every response's quota headers are recorded for ``ebay quota``.

The API key is a reusable credential and lives in the CLI-tools secret manager
under ``ebay-soldcomps-api-key`` — never in a ``.env`` file.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

from cli_tools_shared.config import read_cli_tool_secret, secret_manager_set_command
from cli_tools_shared.data_cache import cached
from cli_tools_shared.output import print_info
from cli_tools_shared.credentials import CredentialType

from .config import get_config
from .models.search_result import SearchResult


API_BASE_URL = "https://api.sold-comps.com"
SCRAPE_PATH = "/v1/scrape"
REQUEST_TIMEOUT_SECONDS = 60

# CLI-tools secret-manager entry holding the SoldComps API key.
API_KEY_SECRET_NAME = "ebay-soldcomps-api-key"

# SoldComps returns at most 200 items per request and each request costs one
# unit of the monthly quota. The 960-result ceiling is carried over from the
# scraper (4 pages x 240) so no caller's --limit changes meaning.
MAX_COUNT_PER_REQUEST = 200
SEARCH_MAX_RESULTS = 960

# Matches the scraper's behavior: eBay's own keyword matching, not a loosened
# "results matching fewer words" fallback set.
EXACT_MATCH = "true"

# SoldComps' documented `categoryId` value for "search every category" — what
# this CLI asks for when no --category narrows the search.
ALL_CATEGORIES = "0"

# Item condition (--condition). Unchanged from the scraping implementation:
# these are eBay's numeric condition IDs, which SoldComps takes as `conditionId`.
SEARCH_CONDITION_ALIASES = {
    "new": "1000",
    "open_box": "1500",
    "refurbished": "2000",
    "used": "3000",
    "for_parts": "7000",
}
SEARCH_CONDITION_HELP = (
    "Item condition ("
    + ", ".join(SEARCH_CONDITION_ALIASES)
    + ", or eBay condition ID)"
)

# Listing-format filters for active search (--format) -> SoldComps buyingFormat.
LISTING_FORMATS = ("bin", "auction", "all")
LISTING_FORMAT_HELP = (
    "Active-listing format: bin (Buy It Now), auction, or all (default all)"
)
BUYING_FORMAT_PARAMS = {
    "bin": "buyItNow",
    "auction": "auction",
    "all": "all",
}

# Source-CLI Sort Standard -> SoldComps `sortOrder`.
#
# `newest` means different things either side of a listing's end, exactly as it
# did against eBay's own `_sop` codes: for ended listings there is no "newly
# listed" order, so it means "ended most recently"; for live listings it means
# "newly listed". Each map is keyed by (field, descending); combinations the API
# cannot produce are absent on purpose and rejected fail-fast.
SORT_ORDER_COMPLETED = {
    ("newest", False): "endedRecently",
    ("price", False): "pricePlusPostageLowest",
    ("price", True): "pricePlusPostageHighest",
}
SORT_ORDER_ACTIVE = {
    ("newest", False): "timeNewlyListed",
    ("price", False): "pricePlusPostageLowest",
    ("price", True): "pricePlusPostageHighest",
}

VALID_SORT_FIELDS = ("newest", "price")
DEFAULT_SORT = "newest"

# Sort fields the scraper supported that SoldComps has no order for. Named
# explicitly so the request fails with the real reason instead of being silently
# reinterpreted as a different order or rejected as a typo.
REMOVED_SORT_FIELDS = {
    "ending": (
        "--sort ending (eBay's 'ending soonest') is no longer supported: the "
        "SoldComps search API this CLI now uses offers no ending-soonest order. "
        "Use --sort newest (newly listed) or --sort price."
    ),
}

# SoldComps buyingFormat -> the format vocabulary this CLI has always emitted.
# Callers filter on these exact labels (e.g. the ebay-listing workflow keeps
# only rows with format "Auction"), so the API's own spelling is translated
# rather than passed through.
BUYING_FORMAT_LABELS = {
    "auction": "Auction",
    "auctionWithBIN": "Auction",
    "buyItNow": "Buy It Now",
    "acceptsOffers": "Best Offer",
}

# SoldComps listingType -> SearchResult.status.
LISTING_TYPE_STATUS = {
    "sold": "sold",
    "unsold": "unsold",
    "active": "active",
}

# Response headers carrying plan usage, recorded after every request so
# `ebay quota` can report them without spending a request of its own.
USAGE_HEADER_FIELDS = {
    "X-Usage-Limit": "quota_limit",
    "X-Usage-Remaining": "quota_remaining",
    "X-Usage-Reset": "quota_reset",
    "X-RateLimit-Limit": "rate_limit",
    "X-RateLimit-Remaining": "rate_limit_remaining",
    "X-RateLimit-Reset": "rate_limit_reset",
}
QUOTA_FILE_NAME = "soldcomps_quota.json"

QUOTA_CODE_EXCEEDED = "quota_exceeded"
QUOTA_CODE_RATE_LIMITED = "rate_limited"


class SoldCompsError(Exception):
    """A SoldComps request failed. Carries the actionable reason, not a status."""


def missing_api_key_message() -> str:
    """Message telling the user exactly how to store the SoldComps API key."""
    return (
        f"No SoldComps API key found. eBay marketplace search reads the key from "
        f"the CLI-tools secret manager under '{API_KEY_SECRET_NAME}'. Store it "
        f"with:\n  {secret_manager_set_command(API_KEY_SECRET_NAME)}\n"
        "The key comes from the SoldComps dashboard (https://sold-comps.com)."
    )


def resolve_sort_order(sort: str, desc: bool, active: bool = False) -> str:
    """Resolve a canonical (``--sort``, ``--desc``) pair to a SoldComps ``sortOrder``.

    ``active`` selects the active-listing map (``newest`` -> newly listed) over
    the completed-comps map (``newest`` -> ended recently).

    Fail-fast, no silent fallback: a removed field, an unknown field, or a
    ``--desc`` direction the API cannot produce raises ``ValueError`` naming the
    real reason.
    """
    field = sort.lower()
    if field in REMOVED_SORT_FIELDS:
        raise ValueError(REMOVED_SORT_FIELDS[field])
    if field not in VALID_SORT_FIELDS:
        valid = ", ".join(VALID_SORT_FIELDS)
        raise ValueError(f"Invalid --sort '{sort}'. Valid values: {valid}")
    sort_map = SORT_ORDER_ACTIVE if active else SORT_ORDER_COMPLETED
    try:
        return sort_map[(field, desc)]
    except KeyError:
        raise ValueError(
            f"SoldComps {'active' if active else 'completed'}-listing search has "
            f"no descending order for --sort {field}; --desc is only supported "
            "with --sort price."
        )


def _money(value: Any, field: str, item_id: str) -> Optional[str]:
    """Format a SoldComps monetary value the way this CLI has always emitted it."""
    if value is None:
        return None
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        raise SoldCompsError(
            f"SoldComps item {item_id} has a non-numeric {field}: {value!r}"
        )


def _require(item: dict, field: str) -> Any:
    value = item.get(field)
    if value is None or value == "":
        raise SoldCompsError(
            f"SoldComps item is missing the required field '{field}'. "
            f"item={json.dumps(item, default=str)[:400]}"
        )
    return value


def map_item(item: dict) -> SearchResult:
    """Map one SoldComps item onto this CLI's :class:`SearchResult`.

    Every ``SearchResult`` field has a declared source; a missing required field
    is an error, never a null passed through as if the listing had no value.
    """
    item_id = str(_require(item, "itemId"))

    listing_type = str(_require(item, "listingType"))
    status = LISTING_TYPE_STATUS.get(listing_type)
    if status is None:
        raise SoldCompsError(
            f"SoldComps item {item_id} reports an unrecognized listingType "
            f"{listing_type!r}. Known values: {', '.join(LISTING_TYPE_STATUS)}."
        )

    # Sold rows price the completed sale; active rows price the live listing.
    if status == "active":
        price_field, currency_field = "currentPrice", "currentCurrency"
    else:
        price_field, currency_field = "soldPrice", "soldCurrency"

    listing_format = None
    raw_format = item.get("buyingFormat")
    if raw_format is not None:
        listing_format = BUYING_FORMAT_LABELS.get(str(raw_format))
        if listing_format is None:
            raise SoldCompsError(
                f"SoldComps item {item_id} reports an unrecognized buyingFormat "
                f"{raw_format!r}. Known values: "
                f"{', '.join(BUYING_FORMAT_LABELS)}."
            )

    bids = item.get("bidCount")
    if bids is not None:
        try:
            bids = int(bids)
        except (TypeError, ValueError):
            raise SoldCompsError(
                f"SoldComps item {item_id} has a non-integer bidCount: {bids!r}"
            )

    return SearchResult(
        item_id=item_id,
        title=str(_require(item, "title")),
        price=_money(_require(item, price_field), price_field, item_id),
        currency=str(_require(item, currency_field)),
        shipping_price=_money(item.get("shippingPrice"), "shippingPrice", item_id),
        status=status,
        date_sold=item.get("endedAt"),
        time_left=item.get("timeLeft"),
        condition=item.get("condition"),
        format=listing_format,
        bids=bids,
        seller=item.get("sellerUsername"),
        url=str(_require(item, "url")),
        image_url=item.get("thumbnailUrl"),
    )


def _error_body(response: requests.Response) -> dict:
    """Return the JSON object of an error response, or ``{}`` when it has none.

    SoldComps documents a JSON error body (``code``/``message``/``retry_after``/
    ``reset_at``), but a gateway between here and the service can answer with
    HTML. An empty mapping records "this response carried no structured error",
    which the caller reports as such rather than treating as a value.
    """
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _first_present(*candidates):
    """Return the first candidate SoldComps actually sent, or ``None``.

    A value can arrive in a response header or the JSON error body depending on
    the failure; these are two places for the SAME value, not a value and a
    stand-in for it.
    """
    for candidate in candidates:
        if candidate is not None:
            return candidate
    return None


def _retry_hint(response: requests.Response, body: dict) -> str:
    """Render whatever timing SoldComps reported with a 429, or nothing."""
    retry_after = _first_present(
        response.headers.get("Retry-After"), body.get("retry_after")
    )
    reset_at = _first_present(
        response.headers.get("X-RateLimit-Reset"), body.get("reset_at")
    )
    parts = []
    if retry_after is not None:
        parts.append(f"Retry-After={retry_after}s")
    if reset_at is not None:
        parts.append(f"resets at {reset_at}")
    if not parts:
        return ""
    return f" ({'; '.join(parts)})"


def raise_for_status(response: requests.Response) -> None:
    """Turn a SoldComps error response into an actionable ``SoldCompsError``.

    No silent retry and no fallback to the browser scraper: each status names
    what actually went wrong and what the caller can do about it.
    """
    if response.ok:
        return

    body = _error_body(response)
    status = response.status_code
    if "message" in body:
        message = body["message"]
    else:
        # No structured error body — quote what the response did carry so the
        # real cause is visible instead of an empty detail.
        message = response.text.strip()[:300]

    if status == 401:
        raise SoldCompsError(
            "SoldComps rejected the API key (HTTP 401). Store or rotate it with:"
            f"\n  {secret_manager_set_command(API_KEY_SECRET_NAME)}"
        )
    if status == 400:
        raise SoldCompsError(
            f"SoldComps rejected the search parameters (HTTP 400): {message}"
        )
    if status == 429:
        code = body.get("code")
        hint = _retry_hint(response, body)
        if code == QUOTA_CODE_EXCEEDED:
            raise SoldCompsError(
                "SoldComps monthly quota is exhausted (HTTP 429 "
                f"quota_exceeded){hint}. Run 'ebay quota' for the recorded plan "
                "usage. Cached sold-comp searches still serve; a new search "
                "needs quota."
            )
        if code == QUOTA_CODE_RATE_LIMITED:
            raise SoldCompsError(
                "SoldComps per-minute rate limit hit (HTTP 429 rate_limited)"
                f"{hint}. The monthly quota is unaffected — wait and retry."
            )
        raise SoldCompsError(
            f"SoldComps returned HTTP 429 with an unrecognized code {code!r}"
            f"{hint}: {message}"
        )
    if status == 502:
        raise SoldCompsError(
            "SoldComps could not read eBay for this search (HTTP 502 — eBay "
            f"blocked the upstream fetch): {message}"
        )
    if status == 503:
        raise SoldCompsError(
            "SoldComps is at its concurrency limit (HTTP 503). Retry once the "
            f"in-flight requests finish: {message}"
        )
    if status == 500:
        raise SoldCompsError(f"SoldComps server error (HTTP 500): {message}")

    raise SoldCompsError(f"SoldComps request failed (HTTP {status}): {message}")


class SoldCompsClient:
    """SoldComps-backed search over eBay sold comps and active listings."""

    BASE_URL = API_BASE_URL

    def __init__(self, profile: Optional[str] = None, config: Optional[Any] = None):
        self.config = config or get_config(profile=profile)
        self._api_key: Optional[str] = None
        self._session: Optional[requests.Session] = None

    # ---- lifecycle -------------------------------------------------------

    @property
    def api_key(self) -> str:
        """The SoldComps API key from the CLI-tools secret manager."""
        if self._api_key is None:
            key = read_cli_tool_secret(API_KEY_SECRET_NAME)
            if key is None:
                raise SoldCompsError(missing_api_key_message())
            self._api_key = key
        return self._api_key

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
        return self._session

    def close(self):
        if self._session is not None:
            self._session.close()
            self._session = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False

    # ---- quota bookkeeping ----------------------------------------------

    @property
    def quota_file(self) -> Path:
        """Where the last response's plan-usage headers are recorded."""
        return Path(self.config.storage_dir) / QUOTA_FILE_NAME

    def record_usage(self, headers) -> dict:
        """Persist the plan-usage headers from one response and return them."""
        usage = {
            field: headers[header]
            for header, field in USAGE_HEADER_FIELDS.items()
            if header in headers
        }
        if not usage:
            return {}
        usage["recorded_at"] = datetime.now(timezone.utc).isoformat()
        self.quota_file.write_text(json.dumps(usage, indent=2))
        return usage

    def read_usage(self) -> dict:
        """Return the recorded plan usage, or raise when nothing is recorded."""
        if not self.quota_file.exists():
            raise SoldCompsError(
                "No SoldComps plan usage has been recorded yet. Usage is read "
                "from the headers of a real search response — run a search "
                "(e.g. ebay listings search \"LEGO 75192\" --sold --limit 5) "
                "first."
            )
        return json.loads(self.quota_file.read_text())

    # ---- search ----------------------------------------------------------

    @cached(credential_type=CredentialType.API_KEY)
    def search_sold(
        self,
        keywords: str,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        category: Optional[str] = None,
        condition: Optional[str] = None,
        us_only: bool = False,
        limit: int = 50,
        sort_order: str = "endedRecently",
    ) -> list[SearchResult]:
        """Search completed, SOLD listings (the comps used for pricing).

        Cached: sold comps are historical, so a repeat of the same search reads
        the previous answer instead of spending another request against the
        monthly quota. ``--no-cache`` forces a fresh fetch, ``ebay cache clear``
        drops every stored answer.
        """
        return self._search(
            keywords=keywords,
            sold=True,
            min_price=min_price,
            max_price=max_price,
            category=category,
            condition=condition,
            us_only=us_only,
            limit=limit,
            sort_order=sort_order,
        )

    def search_active(
        self,
        keywords: str,
        listing_format: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        category: Optional[str] = None,
        condition: Optional[str] = None,
        us_only: bool = False,
        limit: int = 50,
        sort_order: str = "timeNewlyListed",
    ) -> list[SearchResult]:
        """Search ACTIVE (live, purchasable) listings.

        Deliberately not cached: the whole value of an active search is "what is
        live right now", so a stale answer is a wrong answer.
        """
        return self._search(
            keywords=keywords,
            sold=False,
            listing_format=listing_format,
            min_price=min_price,
            max_price=max_price,
            category=category,
            condition=condition,
            us_only=us_only,
            limit=limit,
            sort_order=sort_order,
        )

    def build_params(
        self,
        keywords: str,
        sold: bool,
        page: int,
        count: int,
        listing_format: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        category: Optional[str] = None,
        condition: Optional[str] = None,
        us_only: bool = False,
        sort_order: str = "endedRecently",
    ) -> dict[str, str]:
        """Build one ``/v1/scrape`` query string."""
        params: dict[str, str] = {
            "keyword": keywords,
            "count": str(count),
            "page": str(page),
            "categoryId": category if category else ALL_CATEGORIES,
            "sortOrder": sort_order,
            "sold": "true" if sold else "false",
            "exactMatch": EXACT_MATCH,
        }

        if listing_format is not None:
            fmt = listing_format.lower()
            if fmt not in BUYING_FORMAT_PARAMS:
                raise SoldCompsError(
                    f"Invalid listing format '{listing_format}'. Valid values: "
                    f"{', '.join(LISTING_FORMATS)}"
                )
            params["buyingFormat"] = BUYING_FORMAT_PARAMS[fmt]

        if min_price is not None:
            params["minPrice"] = str(min_price)
        if max_price is not None:
            params["maxPrice"] = str(max_price)
        if condition:
            params["conditionId"] = SEARCH_CONDITION_ALIASES.get(
                condition.lower(), condition
            )
        if us_only:
            params["itemLocation"] = "domestic"

        return params

    def _request_page(self, params: dict[str, str]) -> dict:
        """Issue one ``/v1/scrape`` request and return its parsed envelope."""
        response = self.session.get(
            f"{self.BASE_URL}{SCRAPE_PATH}",
            params=params,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        self.record_usage(response.headers)
        raise_for_status(response)

        try:
            envelope = response.json()
        except ValueError:
            raise SoldCompsError(
                "SoldComps returned a non-JSON response body for "
                f"{response.url!r}: {response.text.strip()[:300]}"
            )
        if not isinstance(envelope, dict) or not isinstance(
            envelope.get("items"), list
        ):
            raise SoldCompsError(
                "SoldComps response is missing the items array. "
                f"keys={sorted(envelope) if isinstance(envelope, dict) else type(envelope).__name__}"
            )
        return envelope

    def _search(
        self,
        keywords: str,
        sold: bool,
        listing_format: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        category: Optional[str] = None,
        condition: Optional[str] = None,
        us_only: bool = False,
        limit: int = 50,
        sort_order: str = "endedRecently",
    ) -> list[SearchResult]:
        """Page through ``/v1/scrape`` until ``limit`` results or the last page."""
        if limit < 1:
            raise SoldCompsError(f"--limit must be at least 1 (got {limit}).")
        if limit > SEARCH_MAX_RESULTS:
            raise SoldCompsError(
                f"--limit {limit} exceeds the {SEARCH_MAX_RESULTS}-result ceiling."
            )

        # One page size for the whole search: `page` indexes windows of `count`,
        # so shrinking `count` on the last page would move the window rather
        # than trim it, silently returning the wrong slice of results.
        page_count = min(limit, MAX_COUNT_PER_REQUEST)
        pages_needed = -(-limit // page_count)  # ceiling division
        if pages_needed > 1:
            print_info(
                f"--limit {limit} needs up to {pages_needed} SoldComps requests "
                f"({page_count} results per request), each one unit of the "
                "monthly quota."
            )

        results: list[SearchResult] = []
        for page in range(1, pages_needed + 1):
            params = self.build_params(
                keywords=keywords,
                sold=sold,
                page=page,
                count=page_count,
                listing_format=listing_format,
                min_price=min_price,
                max_price=max_price,
                category=category,
                condition=condition,
                us_only=us_only,
                sort_order=sort_order,
            )
            envelope = self._request_page(params)

            for item in envelope["items"]:
                if len(results) >= limit:
                    break
                results.append(map_item(item))

            if len(results) >= limit or not envelope.get("hasNextPage"):
                break

        return results


def get_soldcomps_client(
    profile: Optional[str] = None, config: Optional[Any] = None
) -> SoldCompsClient:
    """Get a SoldCompsClient instance."""
    return SoldCompsClient(profile=profile, config=config)
