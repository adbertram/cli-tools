"""ClickBank marketplace GraphQL client (browser-driven).

The marketplace search endpoint at
``https://accounts.clickbank.com/graphql`` is not part of the public REST
documentation.  It is the same endpoint the marketplace SPA at
``/marketplace.htm`` talks to.  ClickBank's Cloudflare WAF blocks vanilla
HTTP clients (curl, httpx without browser fingerprint, etc.) before the
request even reaches GraphQL -- a 403 with a Cloudflare challenge page
comes back instead.

We bypass that the only sustainable way: by issuing the request from inside
a real Chromium session that has already rendered ``/marketplace.htm`` once.
The browser is the same persistent ``BrowserAutomation`` profile used by
``auth login`` / ``auth status``, so the user signs in (or just dismisses
the cookie banner) once and every subsequent marketplace call reuses the
session cookies.

Why GraphQL via ``page.evaluate(fetch(...))`` instead of an httpx client:

* The Cloudflare WAF gates on TLS fingerprint, JA3, User-Agent, and the
  ``cf_clearance`` cookie.  Reproducing that from outside the browser is a
  cat-and-mouse game; running the fetch inside the page sails through with
  zero maintenance.
* No CORS hassle -- the request is same-origin from inside the SPA.
* The shape of every parameter and field was discovered by capturing live
  XHR traffic from the marketplace UI, so the queries below match what
  ClickBank's own front-end sends.  Do not invent new fields or parameter
  names; if a feature is missing, capture another XHR and extend.

Public surface:

* ``MarketplaceClient.categories()`` -- returns the full category +
  subcategory tree.  One facet probe per category (about a dozen requests);
  cached at the command layer.
* ``MarketplaceClient.search(...)`` -- the workhorse.  Maps user-facing
  flags onto the GraphQL ``MarketplaceSearchParameters`` shape.
* ``MarketplaceClient.product(vendor)`` -- pulls the single-result search
  hit plus the historical-metrics ``marketplaceOfferDetails`` payload and
  merges them into one ``MarketplaceProduct`` view.
* ``MarketplaceClient.hoplink(vendor)`` -- offline URL builder.  Does not
  touch the network at all.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .config import Config, get_config
from .models.marketplace import (
    MarketplaceCategory,
    MarketplaceCategoryTree,
    MarketplaceHit,
    MarketplaceProduct,
    MarketplaceRangePoint,
    MarketplaceSearchResult,
    MarketplaceStats,
    MarketplaceSubcategory,
)

activity = get_activity_logger("clickbank-marketplace")


# Valid values for the ``--sort`` option, verified against the live API.
# These are the only enum values the ClickBank GraphQL endpoint accepts for
# ``MarketplaceSearchParameters.sortField``.  ``RANK`` is what the marketplace
# UI uses by default; ``GRAVITY`` and ``POPULARITY`` are the only other
# values that round-trip successfully.  Any other value -- including
# camelCase guesses like ``avgDollarsPerSale`` -- the API rejects with
# ``Value "X" does not exist in "MarketplaceSortByType" enum``.
VALID_SORT_FIELDS = {
    "rank": "rank",
    "gravity": "gravity",
    "popularity": "popularity",
    # User-friendly aliases:
    "avg-sale": "popularity",  # alias -- the UI surfaces popularity as the closest signal
    "new": "popularity",
}

# Full GraphQL query for marketplaceSearch -- mirrors what the live
# marketplace SPA sends so the response shape is identical.  Variable name
# stays as $parameters to match the front-end (no functional reason).
SEARCH_QUERY = """
query MarketplaceSearch($parameters: MarketplaceSearchParameters!) {
  marketplaceSearch(parameters: $parameters) {
    totalHits
    offset
    hits {
      site
      title
      description
      favorite
      url
      urlTitle
      urlDescription
      marketplaceStats {
        activateDate
        category
        subCategory
        initialDollarsPerSale
        averageDollarsPerSale
        gravity
        totalRebill
        de
        en
        es
        fr
        it
        pt
        standard
        physical
        rebill
        upsell
        standardUrlPresent
        mobileEnabled
        whitelistVendor
        cpaVisible
        dollarTrial
        hasAdditionalSiteHoplinks
        directTracking
        expectedReturnRate
        returnRateSource
        initialEPC
        futureEPC
        averageEPC
        conversionRate
        netEPC
        biGravity
        score
        rank
        sellerVolume
      }
      affiliateToolsUrl
      affiliateSupportEmail
      skypeName
      telegramName
      offerImageUrl
    }
  }
}
""".strip()


# Facets-only query used to discover categories without paying the cost of
# pulling 30 hits we will throw away.  ``parameters`` accepts the same
# filters as the search query; pass ``{category: "..."}`` to discover the
# subcategories for that category.
FACETS_QUERY = """
query MarketplaceFacets($parameters: MarketplaceSearchParameters!) {
  marketplaceSearch(parameters: $parameters) {
    facets {
      field
      buckets {
        value
        count
      }
    }
  }
}
""".strip()


# Historical-metrics query.  Vendor name is interpolated directly into the
# query string because the live front-end does the same -- this endpoint
# does not appear to support variables for the ``vendor`` argument.  All
# vendor names from the search hits are alphanumeric uppercase nicknames,
# which is safe to inline.  We assert that constraint before sending.
DETAILS_QUERY_TEMPLATE = """
query MarketplaceOfferDetails {
  marketplaceOfferDetails(vendor: "%s") {
    returnRates
    refundRates
    chargebackRates
    averageEPCRange {
      date
      value
    }
    rankRange {
      date
      value
    }
    gravityRange {
      date
      value
    }
  }
}
""".strip()


class MarketplaceClient:
    """Driver for the private marketplace GraphQL endpoint.

    The client lazily boots a ``BrowserAutomation`` session the first time a
    query runs, then reuses it for the lifetime of the process.  Callers do
    not need to manage the browser explicitly.
    """

    GRAPHQL_PATH = "/graphql"
    GRAPHQL_ORIGIN = "https://accounts.clickbank.com"
    MAX_RESULTS_PER_PAGE = 100  # ClickBank's UI tops out at 50; allow 100 for safety

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or get_config()
        self._browser = None
        self._page = None

    # ------------------------------------------------------------------ browser

    def _ensure_page(self):
        """Boot the persistent browser session and land on the marketplace.

        The marketplace page must be fully rendered before we issue
        ``fetch('/graphql', ...)`` from inside the page; without it Cloudflare
        rejects the request with a 403 challenge response.
        """
        if self._page is not None:
            return self._page
        if self._browser is None:
            self._browser = self.config.get_browser()
        # ``get_page(url)`` is provided by BrowserAutomation; it boots a
        # daemon if needed, loads saved storage state, then navigates.
        self._page = self._browser.get_page(
            f"{self.GRAPHQL_ORIGIN}/marketplace.htm"
        )
        return self._page

    def close(self) -> None:
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
            self._page = None

    # ------------------------------------------------------------------ raw POST

    def _graphql(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Issue one GraphQL request and return the ``data`` payload.

        Raises ``ClientError`` on:
        * Cloudflare WAF rejection (HTTP != 200 in the inner fetch)
        * GraphQL ``errors`` array in the response body
        """
        page = self._ensure_page()
        body = {"query": query}
        if variables is not None:
            body["variables"] = variables

        # Build the JS that does the POST.  Using JSON.stringify on the
        # Python side keeps quote handling clean and avoids template
        # injection (the only escape happens once, here).
        body_json = json.dumps(body)
        path = self.GRAPHQL_PATH
        # JS function expression: must be either a function() {...} or an
        # arrow.  page.evaluate() in Playwright accepts a function expr OR a
        # bare expression.  Wrap as an async IIFE so we can use await.
        js = (
            "async () => { "
            f"const resp = await fetch({json.dumps(path)}, "
            "{ method: 'POST', headers: {'Content-Type': 'application/json'}, "
            f"body: {json.dumps(body_json)} "
            "}); "
            "return { status: resp.status, text: await resp.text() }; "
            "}"
        )
        activity.debug("clickbank graphql POST %s", path)
        try:
            eval_result = page.page_eval(js)
        except Exception as exc:  # PlaywrightServiceError or page evaluation crash
            raise ClientError(f"ClickBank marketplace request failed: {exc}") from exc

        result = eval_result.get("result") if isinstance(eval_result, dict) else None
        if not isinstance(result, dict):
            raise ClientError(
                f"Unexpected eval result from ClickBank marketplace request: {eval_result!r}"
            )
        status = result.get("status")
        text = result.get("text") or ""
        if status != 200:
            # Cloudflare WAF returns HTML on a challenge; surface the first
            # line so the user can tell the difference between auth and WAF.
            snippet = text.strip().splitlines()[0] if text else ""
            raise ClientError(
                f"ClickBank GraphQL returned HTTP {status}. "
                f"Body starts with: {snippet[:200]!r}. "
                "Run 'clickbank auth login' to refresh the marketplace browser session."
            )
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise ClientError(
                f"ClickBank GraphQL returned non-JSON body: {text[:300]!r}"
            ) from exc
        errors = payload.get("errors")
        if errors:
            messages = "; ".join(
                e.get("message", str(e)) if isinstance(e, dict) else str(e)
                for e in errors
            )
            raise ClientError(f"ClickBank GraphQL error: {messages}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ClientError(
                f"ClickBank GraphQL response missing 'data': {payload!r}"
            )
        return data

    # ------------------------------------------------------------------ search

    def search(
        self,
        *,
        category: Optional[str] = None,
        sub_category: Optional[str] = None,
        query: Optional[str] = None,
        min_gravity: Optional[float] = None,
        max_gravity: Optional[float] = None,
        min_avg_sale: Optional[float] = None,
        max_avg_sale: Optional[float] = None,
        recurring: bool = False,
        sort: str = "rank",
        sort_descending: bool = False,
        limit: int = 25,
        page: int = 1,
    ) -> MarketplaceSearchResult:
        """Search the marketplace.  See ``clickbank marketplace search --help``."""
        if limit < 1:
            raise ClientError("--limit must be >= 1")
        if page < 1:
            raise ClientError("--page must be >= 1")
        sort_normalized = sort.lower()
        if sort_normalized not in VALID_SORT_FIELDS:
            raise ClientError(
                f"Invalid --sort value '{sort}'. "
                f"Valid values: {sorted(VALID_SORT_FIELDS)}"
            )
        # Page through, ClickBank counts ``offset`` in records.
        results_per_page = min(max(limit, 1), self.MAX_RESULTS_PER_PAGE)
        offset = (page - 1) * results_per_page

        parameters: Dict[str, Any] = {
            "sortField": VALID_SORT_FIELDS[sort_normalized],
            "sortDescending": bool(sort_descending) if sort_descending else (sort_normalized != "rank"),
            "resultsPerPage": results_per_page,
            "offset": offset,
            "nicknameMasq": None,
        }
        if category:
            parameters["category"] = category
        if sub_category:
            parameters["subCategory"] = sub_category
        if query:
            parameters["includeKeywords"] = query
        if min_gravity is not None:
            parameters["biGravityMin"] = min_gravity
        if max_gravity is not None:
            parameters["biGravityMax"] = max_gravity
        if min_avg_sale is not None:
            parameters["averageDollarsPerSaleMin"] = min_avg_sale
        if max_avg_sale is not None:
            parameters["averageDollarsPerSaleMax"] = max_avg_sale
        if recurring:
            parameters["productTypes"] = ["rebill"]

        data = self._graphql(SEARCH_QUERY, {"parameters": parameters})
        raw = data.get("marketplaceSearch") or {}
        total = int(raw.get("totalHits") or 0)
        offset_out = int(raw.get("offset") or 0)
        hits_raw = raw.get("hits") or []
        hits: List[MarketplaceHit] = []
        for h in hits_raw[:limit]:
            stats_raw = h.get("marketplaceStats") or {}
            stats = MarketplaceStats(**stats_raw) if stats_raw else None
            site = h.get("site") or ""
            hit = MarketplaceHit(
                site=site,
                title=h.get("title"),
                description=h.get("description"),
                favorite=h.get("favorite"),
                url=h.get("url"),
                urlTitle=h.get("urlTitle"),
                urlDescription=h.get("urlDescription"),
                marketplaceStats=stats,
                affiliateToolsUrl=h.get("affiliateToolsUrl"),
                affiliateSupportEmail=h.get("affiliateSupportEmail"),
                skypeName=h.get("skypeName"),
                telegramName=h.get("telegramName"),
                offerImageUrl=h.get("offerImageUrl"),
                hoplink=self.hoplink(site) if site else None,
                category=stats.category if stats else None,
                subCategory=stats.subCategory if stats else None,
                gravity=stats.gravity if stats else None,
                averageDollarsPerSale=stats.averageDollarsPerSale if stats else None,
                initialDollarsPerSale=stats.initialDollarsPerSale if stats else None,
                rebill=stats.rebill if stats else None,
            )
            hits.append(hit)
        return MarketplaceSearchResult(totalHits=total, offset=offset_out, hits=hits)

    # ------------------------------------------------------------------ details

    def product(self, vendor: str) -> MarketplaceProduct:
        """Return the merged product view for a single vendor nickname.

        Issues two GraphQL calls:

        * ``marketplaceSearch`` filtered to the vendor's nickname so we get
          the same ``site/title/stats`` shape the UI shows.
        * ``marketplaceOfferDetails`` for the historical ranges and rates.

        ``vendor`` is case-insensitive on the search side but the details
        endpoint expects lowercase.  We uppercase for the search filter and
        lowercase for the details call -- matching what the live UI does.
        """
        if not vendor or not vendor.strip():
            raise ClientError("vendor nickname is required")
        vendor_clean = vendor.strip()
        if not vendor_clean.replace("_", "").replace("-", "").isalnum():
            # Defence-in-depth: vendor goes straight into a GraphQL query
            # string.  ClickBank nicknames are alphanumeric (with rare
            # underscores/hyphens), so reject anything else.
            raise ClientError(
                f"Vendor nickname '{vendor}' contains invalid characters; "
                "ClickBank nicknames are alphanumeric only."
            )
        vendor_upper = vendor_clean.upper()
        vendor_lower = vendor_clean.lower()

        # 1. Pull the snapshot via a one-result search.  ClickBank's search
        # ``includeKeywords`` matches title text, not vendor nickname, so we
        # filter the response on ``site`` manually.
        search_result = self.search(query=vendor_clean, limit=25)
        hit = next(
            (h for h in search_result.hits if (h.site or "").upper() == vendor_upper),
            None,
        )
        if hit is None:
            # Try a broader gravity-sorted search; some vendors only appear
            # when not filtered by keyword (returns may have changed text).
            broader = self.search(sort="gravity", sort_descending=True, limit=100)
            hit = next(
                (h for h in broader.hits if (h.site or "").upper() == vendor_upper),
                None,
            )
        if hit is None:
            raise ClientError(
                f"Vendor '{vendor_clean}' not found in the marketplace. "
                "Vendor nicknames are exact matches -- check spelling and "
                "case (the marketplace stores them uppercase)."
            )

        # 2. Historical metrics.
        details_data = self._graphql(DETAILS_QUERY_TEMPLATE % vendor_lower)
        details_raw = details_data.get("marketplaceOfferDetails") or {}

        def _points(key: str) -> List[MarketplaceRangePoint]:
            arr = details_raw.get(key) or []
            out: List[MarketplaceRangePoint] = []
            for p in arr:
                if not isinstance(p, dict):
                    continue
                date = p.get("date")
                value = p.get("value")
                if date is None or value is None:
                    continue
                out.append(MarketplaceRangePoint(date=str(date), value=float(value)))
            return out

        stats = hit.marketplaceStats
        return MarketplaceProduct(
            site=hit.site,
            title=hit.title,
            description=hit.description,
            url=hit.url,
            category=stats.category if stats else None,
            subCategory=stats.subCategory if stats else None,
            gravity=stats.gravity if stats else None,
            biGravity=stats.biGravity if stats else None,
            averageDollarsPerSale=stats.averageDollarsPerSale if stats else None,
            initialDollarsPerSale=stats.initialDollarsPerSale if stats else None,
            averageEPC=stats.averageEPC if stats else None,
            initialEPC=stats.initialEPC if stats else None,
            conversionRate=stats.conversionRate if stats else None,
            rebill=stats.rebill if stats else None,
            standard=stats.standard if stats else None,
            physical=stats.physical if stats else None,
            cpaVisible=stats.cpaVisible if stats else None,
            mobileEnabled=stats.mobileEnabled if stats else None,
            activateDate=stats.activateDate if stats else None,
            rank=stats.rank if stats else None,
            sellerVolume=stats.sellerVolume if stats else None,
            expectedReturnRate=stats.expectedReturnRate if stats else None,
            affiliateToolsUrl=hit.affiliateToolsUrl,
            affiliateSupportEmail=hit.affiliateSupportEmail,
            offerImageUrl=hit.offerImageUrl,
            hoplink=self.hoplink(hit.site),
            returnRates=details_raw.get("returnRates") or [],
            refundRates=details_raw.get("refundRates") or [],
            chargebackRates=details_raw.get("chargebackRates") or [],
            averageEPCRange=_points("averageEPCRange"),
            rankRange=_points("rankRange"),
            gravityRange=_points("gravityRange"),
        )

    # ------------------------------------------------------------------ categories

    def categories(self) -> List[MarketplaceCategoryTree]:
        """Return all top-level categories with their subcategories.

        The marketplace facets endpoint scopes ``subCategory`` to whatever
        ``category`` is in the request: an empty request returns the
        cross-category subcategory list (which collapses duplicate names
        across categories and is misleading), but a category-scoped request
        returns the subcategories that actually belong to that category.

        So we issue:
        1. One unfiltered facets request to get the top-level category list.
        2. One facets request per category to get its subcategory list.

        Roughly a dozen requests on a cold cache.  Cached aggressively
        upstream (see the @cached decorator in callers).
        """
        # Step 1: top-level categories.
        data = self._graphql(FACETS_QUERY, {"parameters": {}})
        facets = (data.get("marketplaceSearch") or {}).get("facets") or []
        category_buckets = self._facet(facets, "category")
        if not category_buckets:
            raise ClientError(
                "ClickBank marketplace returned no categories. "
                "The session may be unauthenticated -- run 'clickbank auth login'."
            )

        # Step 2: per-category subcategory expansion.
        trees: List[MarketplaceCategoryTree] = []
        for bucket in category_buckets:
            name = bucket.get("value")
            count = int(bucket.get("count") or 0)
            if not name:
                continue
            sub_data = self._graphql(
                FACETS_QUERY, {"parameters": {"category": name}}
            )
            sub_facets = (sub_data.get("marketplaceSearch") or {}).get("facets") or []
            sub_buckets = self._facet(sub_facets, "subCategory")
            subs = [
                MarketplaceSubcategory(
                    name=str(b.get("value") or ""),
                    count=int(b.get("count") or 0),
                    category=name,
                )
                for b in sub_buckets
                if b.get("value")
            ]
            trees.append(
                MarketplaceCategoryTree(name=name, count=count, subcategories=subs)
            )
        return trees

    def categories_flat(self) -> List[MarketplaceCategory]:
        """Top-level categories only, no subcategory expansion.  One request."""
        data = self._graphql(FACETS_QUERY, {"parameters": {}})
        facets = (data.get("marketplaceSearch") or {}).get("facets") or []
        buckets = self._facet(facets, "category")
        return [
            MarketplaceCategory(name=str(b.get("value") or ""), count=int(b.get("count") or 0))
            for b in buckets
            if b.get("value")
        ]

    @staticmethod
    def _facet(facets: List[Dict[str, Any]], field: str) -> List[Dict[str, Any]]:
        for f in facets:
            if not isinstance(f, dict):
                continue
            if f.get("field") == field:
                return f.get("buckets") or []
        return []

    # ------------------------------------------------------------------ cached categories

    # The ``@cached`` decorator reads ``self.config.storage_dir`` to persist
    # results to disk.  ``MarketplaceClient`` already has ``self.config``
    # attached, so these wrappers reuse it directly -- no separate wrapper
    # class needed.  Returns plain dicts (not pydantic models) so they
    # round-trip through JSON cleanly.
    @cached
    def categories_cached(self):
        return [t.model_dump() for t in self.categories()]

    @cached
    def categories_flat_cached(self):
        return [c.model_dump() for c in self.categories_flat()]

    # ------------------------------------------------------------------ hoplink

    def hoplink(self, vendor: str) -> str:
        """Build the affiliate tracking URL (hoplink) for a vendor.

        Offline -- does not touch the network.  Substitutes the configured
        affiliate nickname when present; otherwise uses a ``{affiliate}``
        placeholder so the caller can see the URL was generated without an
        affiliate id (rather than silently emitting an unattributed link).
        """
        if not vendor:
            raise ClientError("vendor nickname is required to build a hoplink")
        affiliate = self.config.affiliate_nickname or "{affiliate}"
        return f"https://hop.clickbank.net/?affiliate={affiliate}&vendor={vendor.upper()}"


_marketplace_client: Optional[MarketplaceClient] = None


def get_marketplace_client(config: Optional[Config] = None) -> MarketplaceClient:
    """Return a process-wide singleton marketplace client.

    Singleton because spinning up a Chromium session on every command would
    be prohibitively slow.  The shared ``BrowserAutomation`` daemon already
    handles reuse across processes, but inside one process we want exactly
    one client instance so the page reference is reused.
    """
    global _marketplace_client
    if _marketplace_client is None or (config is not None and _marketplace_client.config is not config):
        _marketplace_client = MarketplaceClient(config=config)
    return _marketplace_client


__all__ = [
    "MarketplaceClient",
    "VALID_SORT_FIELDS",
    "get_marketplace_client",
]
