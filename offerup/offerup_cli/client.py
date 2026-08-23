"""OfferUp client driving the live web session's own `/api/graphql` endpoint.

Why an in-page fetch instead of a standalone HTTP client
--------------------------------------------------------
OfferUp has no public API. Its web app posts every feed and detail query to
`POST https://offerup.com/api/graphql`. The app attaches a signed `userdata`
JWT (visitor location), a device token, and a session id that are all minted
inside the page. Rather than transplant those into a second HTTP stack, this
client runs the request INSIDE the live offerup.com page through
`page.evaluate()`, so it carries the real browser's cookies
(`credentials: 'include'`) and its real network stack.

Everything below was validated live against offerup.com during CLI creation —
none of it is guessed:

  * Endpoint: ``POST /api/graphql``. A plain ``content-type: application/json``
    header plus ``credentials: 'include'`` is accepted; the app's extra
    ``x-ou-*`` headers are NOT required (verified: HTTP 200 with listings).
  * Search/browse operation: ``GetModularFeed(params: [SearchParam])``.
    ``SearchParam`` is ``{key, value}`` with string values.
  * Detail operation: ``listing(listingId:)`` via
    ``GetListingDetailByListingId`` — captured from the app's own item page.

Search param names were each confirmed by the server's own filter echo
(``modularFeed.filters[].targetName`` reports the applied value):

  | CLI option                | param       | verified values                          |
  |---------------------------|-------------|------------------------------------------|
  | ``<query>`` argument      | ``q``       | free text                                 |
  | ``--sort`` / ``--desc``   | ``sort``    | best_match, -posted, distance, price, -price |
  | ``--condition``           | ``condition`` | NEW, OPEN_BOX, REFURBISHED, USED, BROKEN, OTHER |
  | ``--min-price``           | ``price_min`` | US dollars (echoed as PRICE_MIN)        |
  | ``--max-price``           | ``price_max`` | US dollars (echoed as PRICE_MAX)        |
  | ``--radius``              | ``radius``  | 5, 10, 20, 30, 50 (echoed as DISTANCE)   |
  | ``--latitude``/``--longitude`` | ``lat``/``lon`` | decimal degrees                 |
  | (pagination)              | ``page_cursor`` | opaque cursor from ``pageCursor``    |

**Unknown params are silently ignored by OfferUp** (verified: a nonsense key
returned the unfiltered baseline, and `conditions`/`condition_ids` produced an
empty CONDITION echo). A silently dropped filter is worse than an error, so
every option value is validated here against the vocabulary the server itself
publishes, and an unknown value raises instead of being passed through.
"""

import json
import time
from typing import List, Optional
from urllib.parse import urlparse

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
from .parsers import normalize_listing_detail, normalize_listings

GRAPHQL_PATH = "/api/graphql"
ITEM_PATH = "/item/detail"

# Page size OfferUp's own web app requests, and the paging ceiling this client
# will walk before giving up on reaching `--limit`.
PAGE_SIZE = 50
MAX_PAGES = 20

# Server-published CONDITION filter values (modularFeed.filters -> targetName
# "CONDITION"), captured live.
CONDITION_VALUES = ("NEW", "OPEN_BOX", "REFURBISHED", "USED", "BROKEN", "OTHER")

# Server-published DISTANCE filter values (targetName "DISTANCE"), in miles.
RADIUS_VALUES = ("5", "10", "20", "30", "50")

# ---------------------------------------------------------------------------
# Sort (Source-CLI Sort Standard)
# ---------------------------------------------------------------------------
# Canonical user-facing sort vocabulary resolved to OfferUp's real `sort` token.
# Each OfferUp token bakes in its own direction, so `--desc` is only meaningful
# where the server publishes both directions. OfferUp's SORT filter exposes
# exactly five values and no oldest-first order, so `--sort newest --desc` is
# rejected rather than silently returning non-chronological results.
DEFAULT_SORT = "relevance"

# user value -> (natural api token [no --desc], reversed api token [--desc])
_SORT_DIRECTIONS = {
    "relevance": ("best_match", None),
    "newest": ("-posted", None),
    "distance": ("distance", None),
    "price": ("price", "-price"),
}
SORT_VALUES = tuple(_SORT_DIRECTIONS)

SEARCH_QUERY = """query GetModularFeed($searchParams: [SearchParam], $debug: Boolean = false) {
  modularFeed(params: $searchParams, debug: $debug) {
    pageCursor
    looseTiles {
      ... on ModularFeedTileListing {
        tileId
        tileType
        listing {
          listingId
          title
          price
          conditionText
          locationName
          isFirmPrice
          flags
          vehicleMiles
          image { url width height }
          video { url thumbnailUrl width height }
        }
      }
    }
    modules {
      ... on ModularFeedModuleGrid {
        moduleId
        moduleType
        title
        grid {
          tiles {
            ... on ModularFeedTileListing {
              tileId
              tileType
              listing {
                listingId
                title
                price
                conditionText
                locationName
                isFirmPrice
                flags
                vehicleMiles
                image { url width height }
              }
            }
          }
        }
      }
    }
  }
}"""

DETAIL_QUERY = """query GetListingDetailByListingId($listingId: ID!) {
  listing(listingId: $listingId) {
    id
    listingId
    title
    originalTitle
    description
    price
    originalPrice
    condition
    quantity
    sku
    state
    isRemoved
    isLocal
    isFirmOnPrice
    isMerchantItem
    badges
    postDate
    lastEdited
    availabilityConfirmedAt
    distance { unit value }
    locationDetails { distance latitude longitude locationName }
    listingCategory {
      id
      categoryAttributeMap { attributeName attributePriority attributeUILabel attributeValue }
      categoryV2 { id l1Id l1Name l2Id l2Name l3Id l3Name name }
    }
    extractedAttributes { attributeName attributeValue attributeValueSource }
    fulfillmentDetails {
      buyItNowEnabled
      canShipToBuyer
      estimatedDeliveryDateEnd
      estimatedDeliveryDateStart
      localPickupEnabled
      sellerPaysShipping
      shippingEnabled
      shippingPrice
      showAsShipped
    }
    shippingOptions { name price priority minHandlingDays maxHandlingDays minShippingDays maxShippingDays }
    photos {
      uuid
      detail { url width height }
      detailFull { url width height }
      list { url width height }
      medium { url width height }
    }
    ownerId
    owner {
      id
      profile {
        name
        dateJoined
        lastActive
        publicLocationName
        itemsSold
        itemsPurchased
        responseTime
        isBusinessAccount
        isTruyouVerified
        ratingSummary { average count }
      }
    }
    vehicleAttributes {
      vehicleYear
      vehicleMake
      vehicleModel
      vehicleTrim
      vehicleMiles
      vehicleColor
      vehicleVin
      vehicleTransmission
      vehicleFuelType
      vehicleTitleStatus
    }
  }
}"""

_FETCH_JS = """async (opts) => {
    const resp = await fetch(opts.path, {
        method: 'POST',
        credentials: 'include',
        headers: {
            'content-type': 'application/json',
            'accept': '*/*',
            'x-ou-operation-name': opts.operationName,
        },
        body: JSON.stringify({
            operationName: opts.operationName,
            variables: opts.variables,
            query: opts.query,
        }),
    });
    const text = await resp.text();
    return {
        status: resp.status,
        statusText: resp.statusText,
        retryAfter: resp.headers.get('retry-after'),
        body: text,
    };
}"""


class SortError(ClientError):
    """Raised for an invalid ``--sort``/``--desc`` combination."""


def resolve_sort(sort: str, desc: bool = False) -> str:
    """Resolve a ``(--sort, --desc)`` pair to OfferUp's API ``sort`` token.

    Raises :class:`SortError` with a clear, valid-values message on any
    unrecognized value or unsupported direction. Never silently falls back to a
    default, because OfferUp ignores an unknown ``sort`` value and returns
    best-match order instead of failing.
    """
    key = (sort or "").strip().lower()
    if key not in _SORT_DIRECTIONS:
        raise SortError(
            f"Invalid --sort '{sort}'. Valid values: {', '.join(SORT_VALUES)}."
        )
    natural, reversed_token = _SORT_DIRECTIONS[key]
    if desc:
        if reversed_token is None:
            raise SortError(
                f"--desc is not supported with --sort {key}: OfferUp publishes no "
                f"reverse order for {key}. Drop --desc, or use --sort price."
            )
        return reversed_token
    return natural


def extract_listing_id(item: str) -> str:
    """Return the OfferUp listing id from a bare id or an item detail URL."""
    value = (item or "").strip()
    if not value:
        raise ClientError("A listing id or offerup.com item URL is required.")
    if "://" not in value:
        return value
    path = urlparse(value).path.rstrip("/")
    listing_id = path.rsplit("/", 1)[-1]
    if not listing_id:
        raise ClientError(f"No listing id found in URL {value!r}.")
    return listing_id


def _validate_choice(value: str, allowed: tuple, label: str) -> str:
    if value not in allowed:
        raise ClientError(
            f"Invalid {label} {value!r}. Valid values: {', '.join(allowed)}."
        )
    return value


class OfferupClient:
    """Drives a live offerup.com page and calls its own GraphQL feed API."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_REQUESTS_MAX_RETRIES,
        base_delay: float = DEFAULT_REQUESTS_BASE_DELAY,
        max_delay: float = DEFAULT_REQUESTS_MAX_DELAY,
        jitter: float = DEFAULT_REQUESTS_JITTER,
    ):
        self.config = config or get_config()
        # Shared exponential-backoff-with-jitter policy (the same formula every
        # requests-backed CLI here uses). It has no dependency on `requests`, so
        # it applies equally to this in-page fetch's own timing.
        self._retry_policy = RequestsRetryPolicy(
            max_retries=max_retries,
            base_delay=base_delay,
            max_delay=max_delay,
            jitter=jitter,
            retryable_status_codes=DEFAULT_REQUESTS_RETRYABLE_STATUS_CODES,
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

    @property
    def _home_url(self) -> str:
        return f"{self.config.base_url.rstrip('/')}/"

    def item_url(self, listing_id: str) -> str:
        return f"{self.config.base_url.rstrip('/')}{ITEM_PATH}/{listing_id}"

    def _retry_after_seconds(self, raw: Optional[str]) -> Optional[float]:
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _graphql(self, operation_name: str, query: str, variables: dict) -> dict:
        """Run the in-page GraphQL POST with exponential-backoff retry."""
        page = self._get_browser().get_page(self._home_url)
        policy = self._retry_policy
        last_exception: Optional[Exception] = None
        last_status = None

        for attempt in range(policy.max_retries + 1):
            try:
                result = page.evaluate(
                    _FETCH_JS,
                    {
                        "path": GRAPHQL_PATH,
                        "operationName": operation_name,
                        "query": query,
                        "variables": variables,
                    },
                )
            except Exception as exc:  # browser-harness / network failure
                last_exception = exc
                if attempt < policy.max_retries:
                    time.sleep(policy.calculate_delay(attempt))
                    continue
                raise ClientError(
                    f"OfferUp {operation_name} failed after {attempt + 1} attempts: {exc}"
                ) from exc

            status = int(result.get("status") or 0)
            last_status = status
            body = str(result.get("body") or "")
            if status in policy.retryable_status_codes and attempt < policy.max_retries:
                time.sleep(
                    policy.calculate_delay(
                        attempt, self._retry_after_seconds(result.get("retryAfter"))
                    )
                )
                continue
            if status != 200:
                raise ClientError(
                    f"OfferUp {operation_name} HTTP {status} "
                    f"{result.get('statusText', '')}: {body[:300]}"
                )
            try:
                payload = json.loads(body)
            except (ValueError, TypeError) as exc:
                raise ClientError(
                    f"OfferUp {operation_name} returned a non-JSON body: {exc}"
                ) from exc
            if payload.get("errors"):
                message = "; ".join(
                    str(err.get("message")) for err in payload["errors"]
                )
                raise ClientError(f"OfferUp {operation_name} returned errors: {message}")
            return payload["data"]

        raise ClientError(
            f"OfferUp {operation_name} failed after retries "
            f"(last status={last_status}): {last_exception}"
        )

    def _build_params(
        self,
        query: Optional[str],
        page_size: int,
        sort_token: Optional[str],
        condition: Optional[List[str]],
        min_price: Optional[float],
        max_price: Optional[float],
        radius: Optional[str],
        latitude: Optional[float],
        longitude: Optional[float],
        page_cursor: Optional[str],
    ) -> List[dict]:
        params = [{"key": "platform", "value": "web"}, {"key": "limit", "value": str(page_size)}]
        if query:
            params.append({"key": "q", "value": query})
        if sort_token:
            params.append({"key": "sort", "value": sort_token})
        if condition:
            values = [_validate_choice(c, CONDITION_VALUES, "--condition") for c in condition]
            params.append({"key": "condition", "value": ",".join(values)})
        if min_price is not None:
            params.append({"key": "price_min", "value": str(min_price)})
        if max_price is not None:
            params.append({"key": "price_max", "value": str(max_price)})
        if radius is not None:
            params.append({"key": "radius", "value": _validate_choice(str(radius), RADIUS_VALUES, "--radius")})
        if latitude is not None:
            params.append({"key": "lat", "value": str(latitude)})
        if longitude is not None:
            params.append({"key": "lon", "value": str(longitude)})
        if page_cursor:
            params.append({"key": "page_cursor", "value": page_cursor})
        return params

    @cached
    def search_listings(
        self,
        query: Optional[str] = None,
        limit: int = 50,
        sort_token: Optional[str] = None,
        condition: Optional[List[str]] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        radius: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> List[dict]:
        """Search public OfferUp listings, or browse the local feed when
        ``query`` is None.

        Every filter is sent to OfferUp itself (server-side). ``limit`` drives
        the requested page size and cursor pagination rather than slicing a
        client-side list. ``sort_token`` is the already-resolved OfferUp token
        from :func:`resolve_sort`, or ``None`` to use OfferUp's own default.
        """
        listings: List[dict] = []
        seen = set()
        cursor: Optional[str] = None
        pages = 0

        while len(listings) < limit and pages < MAX_PAGES:
            data = self._graphql(
                "GetModularFeed",
                SEARCH_QUERY,
                {
                    "debug": False,
                    "searchParams": self._build_params(
                        query,
                        min(PAGE_SIZE, max(limit - len(listings), 1)),
                        sort_token,
                        condition,
                        min_price,
                        max_price,
                        radius,
                        latitude,
                        longitude,
                        cursor,
                    ),
                },
            )
            feed = data["modularFeed"]
            for listing in _iter_feed_listings(feed):
                listing_id = listing.get("listingId")
                if listing_id in seen:
                    continue
                seen.add(listing_id)
                listings.append(listing)
            pages += 1
            cursor = feed.get("pageCursor")
            if not cursor:
                break

        return normalize_listings(listings[:limit], self.item_url)

    @cached
    def get_listing(self, item: str) -> dict:
        """Get the full detail record for one listing by id or item URL."""
        listing_id = extract_listing_id(item)
        data = self._graphql(
            "GetListingDetailByListingId", DETAIL_QUERY, {"listingId": listing_id}
        )
        listing = data.get("listing")
        if not listing:
            raise ClientError(f"OfferUp returned no listing for {listing_id!r}.")
        return normalize_listing_detail(listing, self.item_url)


def _iter_feed_listings(feed: dict):
    """Yield every listing record in a modularFeed response.

    OfferUp splits results between top-level ``looseTiles`` and grouped
    ``modules[].grid.tiles``; both carry the same ``ModularFeedTileListing``
    shape. Ad and job tiles come back as empty objects on this query because
    the inline fragment only selects listing tiles.
    """
    for tile in feed.get("looseTiles") or []:
        listing = tile.get("listing")
        if listing:
            yield listing
    for module in feed.get("modules") or []:
        grid = module.get("grid") or {}
        for tile in grid.get("tiles") or []:
            listing = tile.get("listing")
            if listing:
                yield listing


_client: Optional[OfferupClient] = None


def get_client() -> OfferupClient:
    """Get or create the global OfferUp client instance."""
    global _client
    if _client is None:
        _client = OfferupClient()
    return _client
