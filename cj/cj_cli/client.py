"""CJ Affiliate REST client.

Targets the legacy CJ Advertiser Lookup API
(``advertiser-lookup.api.cj.com/v2/advertiser-lookup``) which is the
only public endpoint that exposes the publisher's full advertiser
catalogue with relationship state.  Auth is a Bearer Personal Access
Token generated at
https://members.cj.com/member/PersonalAccessTokens/tokens.cj.

The endpoint returns XML.  We parse it with the stdlib
``xml.etree.ElementTree`` and return typed Pydantic models so command
handlers never see raw XML.

There is intentionally no GraphQL/REST endpoint for applying to an
advertiser program -- that action lives in
``commands/relationships.py`` and is driven by ``BrowserAutomation``.
"""

from __future__ import annotations

import fnmatch
import random
import time
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

import requests

from cli_tools_shared.exceptions import ClientError

from .config import get_config
from cli_tools_shared.filters import FilterValidationError, validate_filters
from .models import (
    Advertiser,
    AdvertiserDetail,
    Link,
    Relationship,
    RelationshipStatus,
    create_advertiser,
    create_advertiser_detail,
    create_link,
    create_relationship,
)


# Retry tuning -- inherited defaults from the scaffold.
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# CJ caps records-per-page at 100 across every public endpoint.
CJ_MAX_PAGE_SIZE = 100


def _text(element: Optional[ET.Element]) -> Optional[str]:
    """Return stripped text from an XML element, or None when missing/empty."""
    if element is None:
        return None
    if element.text is None:
        return None
    text = element.text.strip()
    return text if text else None


def _parse_advertiser_element(elem: ET.Element) -> Dict:
    """Translate a single ``<advertiser>`` XML element into a flat dict.

    Keys match the snake_case names used by the model factory functions
    in :mod:`cj_cli.models.advertiser`.
    """
    actions = []
    actions_root = elem.find("actions")
    if actions_root is not None:
        for action in actions_root.findall("action"):
            actions.append(
                {
                    "name": _text(action.find("name")),
                    "type": _text(action.find("type")),
                    "id": _text(action.find("id")),
                    "commission": {
                        "default": _text(action.find("commission/default")),
                        "itemlist": [
                            {
                                "name": _text(item.find("name")),
                                "id": _text(item.find("id")),
                                "value": _text(item.find("value")),
                            }
                            for item in action.findall("commission/itemlist")
                        ],
                    },
                }
            )

    secondary = []
    secondary_root = elem.find("secondary-category")
    if secondary_root is not None:
        for child in secondary_root.findall("category"):
            value = _text(child)
            if value:
                secondary.append(value)

    # CJ separates link types with commas; values themselves may contain spaces
    # (e.g. "Text Link", "Smart Zone"), so split on commas only.
    link_types_raw = _text(elem.find("link-types"))
    link_types = (
        [chunk.strip() for chunk in link_types_raw.split(",") if chunk.strip()]
        if link_types_raw
        else []
    )

    return {
        "advertiser_id": _text(elem.find("advertiser-id")),
        "advertiser_name": _text(elem.find("advertiser-name")),
        "account_status": _text(elem.find("account-status")),
        "program_url": _text(elem.find("program-url")),
        "relationship_status": _text(elem.find("relationship-status")),
        "mobile_tracking_certified": _text(elem.find("mobile-tracking-certified")),
        "cookieless_tracking_enabled": _text(elem.find("cookieless-tracking-enabled")),
        "network_rank": _text(elem.find("network-rank")),
        "primary_category": _text(elem.find("primary-category/parent"))
        or _text(elem.find("primary-category")),
        "secondary_categories": secondary,
        "performance_incentives": _text(elem.find("performance-incentives")),
        "seven_day_epc": _text(elem.find("seven-day-epc")),
        "three_month_epc": _text(elem.find("three-month-epc")),
        "language": _text(elem.find("language")),
        "actions": actions,
        "link_types": link_types,
    }


def _parse_link_element(elem: ET.Element) -> Dict:
    """Translate one ``<link>`` element into a flat dict.

    Keys match the snake_case field names on :class:`cj_cli.models.Link`.
    Preserves CJ's raw strings for commission and EPC fields -- the
    Link Search API uses the same sentinel-string pattern documented in
    Bug 1 / Bug 3 for the advertiser-lookup parser.
    """
    return {
        "link_id": _text(elem.find("link-id")),
        "advertiser_id": _text(elem.find("advertiser-id")),
        "advertiser_name": _text(elem.find("advertiser-name")),
        "link_name": _text(elem.find("link-name")),
        "link_type": _text(elem.find("link-type")),
        "click_url": _text(elem.find("clickUrl"))
        or _text(elem.find("click-url")),
        "destination": _text(elem.find("destination")),
        "description": _text(elem.find("description")),
        "category": _text(elem.find("category")),
        "language": _text(elem.find("language")),
        "promotion_type": _text(elem.find("promotion-type")),
        "promotion_start_date": _text(elem.find("promotion-start-date")),
        "promotion_end_date": _text(elem.find("promotion-end-date")),
        "relationship_status": _text(elem.find("relationship-status")),
        "sale_commission": _text(elem.find("sale-commission")),
        "click_commission": _text(elem.find("click-commission")),
        "seven_day_epc": _text(elem.find("seven-day-epc")),
        "three_month_epc": _text(elem.find("three-month-epc")),
        "creative_height": _text(elem.find("creative-height")),
        "creative_width": _text(elem.find("creative-width")),
    }


class CjClient:
    """REST client for CJ's advertiser-lookup API."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        # Allow callers (e.g. ``Config.test_connection``) to supply their
        # own config instance so per-profile validation never silently
        # falls back to the cached default profile.
        self.config = config if config is not None else get_config()

        # Dual-auth CLI: the REST surface only needs the PAT.  The
        # browser session is independent and is enforced where it is
        # actually used (apply flow in commands/relationships.py).
        if not self.config.has_api_credentials():
            raise ClientError(
                "CJ Personal Access Token is not configured. "
                "Run 'cj auth login' and paste a token generated at "
                "https://members.cj.com/member/PersonalAccessTokens/tokens.cj"
            )

        # Force the official endpoints -- DEFAULT_BASE_URL is just a
        # convenience for ``cj auth status`` reporting and can be
        # overridden via env, but the production endpoints below are
        # fixed.  CJ splits the publisher catalogue across two REST
        # APIs that share PAT auth but live at distinct hostnames:
        #   - advertiser-lookup -> programs and relationships
        #   - link-search       -> creatives / tracking URLs
        self.base_url = "https://advertiser-lookup.api.cj.com"
        self.link_search_base_url = "https://link-search.api.cj.com"
        self.headers = {
            "Authorization": f"Bearer {self.config.personal_access_token}",
            "Accept": "application/xml",
            "User-Agent": "cj-cli/1.0",
        }
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    # ------------------------------------------------------------------
    # HTTP plumbing
    # ------------------------------------------------------------------

    def _retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)
        return min(delay, self.max_delay)

    def _get(
        self,
        endpoint: str,
        params: Dict,
        base_url: Optional[str] = None,
    ) -> ET.Element:
        """GET an XML endpoint with retries; return the parsed root element.

        ``base_url`` overrides ``self.base_url`` for endpoints that live
        on a different CJ host (e.g. ``link-search.api.cj.com``).  The
        retry policy and auth header are the same across both hosts.
        """
        host = base_url if base_url is not None else self.base_url
        url = f"{host}{endpoint}"
        last_exc: Optional[Exception] = None
        last_resp: Optional[requests.Response] = None

        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.get(url, headers=self.headers, params=params, timeout=30)
                last_resp = resp
                if resp.status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                    retry_after = resp.headers.get("Retry-After")
                    delay = self._retry_delay(
                        attempt, float(retry_after) if retry_after else None
                    )
                    time.sleep(delay)
                    continue
                break
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    time.sleep(self._retry_delay(attempt))
                    continue
                break

        if last_resp is None:
            raise ClientError(f"CJ request failed: {last_exc}")

        if last_resp.status_code == 401:
            raise ClientError(
                "CJ rejected the Personal Access Token (HTTP 401). "
                "Generate a new token at "
                "https://members.cj.com/member/PersonalAccessTokens/tokens.cj "
                "and run 'cj auth login'."
            )
        if not last_resp.ok:
            raise ClientError(
                f"CJ API error HTTP {last_resp.status_code}: {last_resp.text[:500]}"
            )

        try:
            return ET.fromstring(last_resp.content)
        except ET.ParseError as exc:
            raise ClientError(f"CJ returned unparseable XML: {exc}") from exc

    # ------------------------------------------------------------------
    # Advertiser-lookup API
    # ------------------------------------------------------------------

    def list_advertisers(
        self,
        relationship: str = "joined",
        keywords: Optional[str] = None,
        advertiser_name: Optional[str] = None,
        category: Optional[str] = None,
        page: int = 1,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Advertiser]:
        """List advertisers from CJ.

        Args:
            relationship: one of ``joined``, ``notjoined``, ``all``, or
                a comma-separated list of advertiser IDs.  Maps to the
                ``advertiser-ids`` query param.
            keywords: free-text search across advertiser name and
                description.
            advertiser_name: exact advertiser-name filter.
            category: primary category name (e.g. ``Software``).
            page: 1-indexed page number.
            limit: page size (capped at 100 by CJ).
            filters: optional ``field:op:value`` filter strings applied
                client-side after the response is parsed.
        """
        if limit < 1:
            raise ClientError("limit must be >= 1")

        # CJ's ``advertiser-ids`` param accepts ``joined``, ``notjoined``,
        # or a comma-separated list of advertiser IDs.  It does NOT accept
        # the literal string ``all`` -- doing so returns HTTP 400
        # "Invalid advertiser id(s): all".  When the caller asks for
        # ``all`` we fetch joined + notjoined separately and merge.
        rel = (relationship or "joined").strip().lower()
        if rel == "all":
            joined = self.list_advertisers(
                relationship="joined",
                keywords=keywords,
                advertiser_name=advertiser_name,
                category=category,
                page=page,
                limit=limit,
                filters=filters,
            )
            notjoined = self.list_advertisers(
                relationship="notjoined",
                keywords=keywords,
                advertiser_name=advertiser_name,
                category=category,
                page=page,
                limit=limit,
                filters=filters,
            )
            return (joined + notjoined)[:limit]

        params = {
            "requestor-cid": self.config.publisher_id,
            "advertiser-ids": relationship or "joined",
            "page-number": page,
            "records-per-page": min(limit, CJ_MAX_PAGE_SIZE),
        }
        if keywords:
            params["keywords"] = keywords
        if advertiser_name:
            params["advertiser-name"] = advertiser_name
        if category:
            params["category"] = category

        if filters:
            try:
                validate_filters(filters)
            except FilterValidationError as exc:
                raise ClientError(f"Invalid filter: {exc}") from exc

        root = self._get("/v2/advertiser-lookup", params)
        rows = [
            create_advertiser(_parse_advertiser_element(elem))
            for elem in root.findall(".//advertiser")
        ]

        if filters:
            rows = _apply_filters(rows, filters)

        return rows[:limit]

    def search_advertisers(
        self,
        query: str,
        limit: int = 100,
        relationship: str = "all",
    ) -> List[Advertiser]:
        """Wildcard search over advertiser names.

        ``cj`` exposes a server-side keyword search via the ``keywords``
        query param.  We pass the query through unchanged (stripping
        wildcards) so the API does the heavy lifting, then apply
        client-side fnmatch to honour explicit ``*`` wildcards in the
        user's query.
        """
        if not query:
            raise ClientError("search query must not be empty")
        api_keywords = query.replace("*", "").strip() or query
        rows = self.list_advertisers(
            relationship=relationship,
            keywords=api_keywords,
            limit=limit,
        )

        pattern = query.lower()
        if "*" not in pattern:
            pattern = f"*{pattern}*"

        matches = []
        for row in rows:
            haystack = row.advertiser_name.lower()
            if fnmatch.fnmatch(haystack, pattern):
                matches.append(row)
        return matches[:limit]

    def get_advertiser(self, advertiser_id: str) -> AdvertiserDetail:
        """Return the full record for a single advertiser."""
        if not advertiser_id:
            raise ClientError("advertiser_id is required")
        params = {
            "requestor-cid": self.config.publisher_id,
            "advertiser-ids": str(advertiser_id),
            "page-number": 1,
            "records-per-page": 1,
        }
        root = self._get("/v2/advertiser-lookup", params)
        elem = root.find(".//advertiser")
        if elem is None:
            raise ClientError(f"No advertiser found with id {advertiser_id!r}")
        return create_advertiser_detail(_parse_advertiser_element(elem))

    def list_relationships(
        self,
        status: str = "joined",
        page: int = 1,
        limit: int = 100,
    ) -> List[Relationship]:
        """List the publisher's relationships at ``status``.

        ``status`` accepts ``joined``, ``notjoined``, ``pending``, or
        ``declined``.  CJ does not expose pending/declined directly via
        ``advertiser-ids`` -- we fetch a broader slice and then filter
        client-side using ``relationship-status``.
        """
        api_status = status.lower()
        if api_status in {"joined", "notjoined"}:
            rows = self.list_advertisers(relationship=api_status, page=page, limit=limit)
        else:
            # CJ returns pending/declined only in the joined+notjoined
            # union; we widen the query and filter.
            joined = self.list_advertisers(relationship="joined", page=page, limit=limit)
            notjoined = self.list_advertisers(relationship="notjoined", page=page, limit=limit)
            rows = joined + notjoined

        relationships: List[Relationship] = []
        for row in rows:
            row_status = row.relationship_status
            if row_status is None:
                continue
            if api_status != "all" and row_status.value != api_status:
                continue
            relationships.append(
                create_relationship(
                    {
                        "advertiser_id": row.advertiser_id,
                        "advertiser_name": row.advertiser_name,
                        "relationship_status": row_status.value,
                        "program_url": row.program_url,
                        "network_rank": row.network_rank,
                    }
                )
            )
        return relationships[:limit]

    # ------------------------------------------------------------------
    # Link Search API
    # ------------------------------------------------------------------

    def search_links(
        self,
        advertiser_ids: Optional[str] = None,
        keywords: Optional[str] = None,
        link_type: Optional[str] = None,
        category: Optional[str] = None,
        promotion_type: Optional[str] = None,
        page: int = 1,
        limit: int = 100,
    ) -> List[Link]:
        """List creatives from CJ's Link Search API.

        Requires ``website-id`` (the publisher's website id, equal to
        ``Config.publisher_id``).  At least one filter must be supplied
        by CJ's contract -- the CLI defaults to filtering by
        ``advertiser-ids`` when the caller provides ``advertiser_ids``.

        Returns links the publisher is authorized to use: typically only
        those for advertisers with relationship_status=joined.  CJ
        silently omits links for not-joined advertisers.
        """
        params: Dict = {
            "website-id": self.config.website_id,
            "records-per-page": min(limit, CJ_MAX_PAGE_SIZE),
            "page-number": page,
        }
        if advertiser_ids is not None:
            params["advertiser-ids"] = advertiser_ids
        if keywords is not None:
            params["keywords"] = keywords
        if link_type is not None:
            params["link-type"] = link_type
        if category is not None:
            params["category"] = category
        if promotion_type is not None:
            params["promotion-type"] = promotion_type

        root = self._get(
            "/v2/link-search",
            params,
            base_url=self.link_search_base_url,
        )
        rows = [
            create_link(_parse_link_element(elem))
            for elem in root.findall(".//link")
        ]
        return rows[:limit]

    def get_link(self, link_id: str) -> Link:
        """Return the full record for one link by id.

        CJ's link-search API has no per-id endpoint -- this method
        fetches a small page and filters client-side.  Callers should
        pass the ``advertiser_ids`` they know the link belongs to via
        ``search_links`` instead when the advertiser is known; this
        helper exists for the common case of "I have a link id, what
        is it?".
        """
        rows = self.search_links(limit=CJ_MAX_PAGE_SIZE)
        for row in rows:
            if row.link_id == str(link_id):
                return row
        raise ClientError(
            f"No link found with id {link_id!r} in the first "
            f"{CJ_MAX_PAGE_SIZE} results.  Narrow the search with "
            f"`search_links(advertiser_ids=...)` when the advertiser is known."
        )


# ----------------------------------------------------------------------
# Client-side filter application
# ----------------------------------------------------------------------


def _apply_filters(rows: List[Advertiser], filters: List[str]) -> List[Advertiser]:
    """Apply ``field:op:value`` filters to a list of Advertiser models.

    Only the small subset of operators we actually exercise is wired
    up; unsupported operators raise rather than silently passing items
    through.
    """
    def matches(row: Advertiser, expr: str) -> bool:
        parts = expr.split(":", 2)
        if len(parts) < 2:
            raise ClientError(f"Filter must be 'field:op[:value]': {expr!r}")
        field = parts[0]
        op = parts[1]
        value = parts[2] if len(parts) == 3 else None
        actual = getattr(row, field, None)
        if hasattr(actual, "value"):  # Enum
            actual = actual.value
        if op == "eq":
            return str(actual) == str(value)
        if op == "ne":
            return str(actual) != str(value)
        if op == "contains":
            return value is not None and value.lower() in (str(actual or "")).lower()
        if op == "exists":
            return actual is not None
        raise ClientError(f"Unsupported filter operator {op!r} in {expr!r}")

    return [r for r in rows if all(matches(r, expr) for expr in filters)]


# ----------------------------------------------------------------------
# Singleton
# ----------------------------------------------------------------------


_client: Optional[CjClient] = None


def get_client() -> CjClient:
    """Return a memoised :class:`CjClient` for the active profile."""
    global _client
    if _client is None:
        _client = CjClient()
    return _client


def reset_client() -> None:
    """Forget the cached client (used by tests / profile switches)."""
    global _client
    _client = None
