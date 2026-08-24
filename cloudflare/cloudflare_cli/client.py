"""Cloudflare API client with automatic token management and exponential retry."""
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Union
import json
import random
import re
import time
import requests

from .config import get_config
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
from .models import Zone, ZoneDetail, PurgeResult, create_zone, create_zone_detail, create_purge_result
from .models.access_rule import AccessRule, create_access_rule
from .models.dns_record import DNSRecord, create_dns_record
from .models.worker_route import WorkerRoute, create_worker_route


# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_JITTER = 0.1  # 10% jitter

# HTTP status codes that trigger retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Cloudflare zone IDs are 32 lowercase hex characters
ZONE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

# Cloudflare account IDs share the same 32-hex-character shape
ACCOUNT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

# HTTP methods that mutate Cloudflare state. A scoped API token that carries only
# Read permission groups authenticates fine and serves GET, then fails these with
# HTTP 403.
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# CLI-tools secret manager entry that holds the Cloudflare API token.
API_TOKEN_SECRET_NAME = "cloudflare-api-key"
SECRETS_MANAGER = (
    "/Users/adam/Dropbox/GitRepos/cli-tools/_repo/_secret-manager/secrets.sh"
)

# Cloudflare API-token permission groups required per endpoint family, as
# (endpoint fragment, read permission, write permission). Ordered most specific
# first; every fragment is matched against the request endpoint in order.
PERMISSION_GROUPS = (
    (
        "/workers/routes",
        "Zone > Workers Routes > Read",
        "Zone > Workers Routes > Edit",
    ),
    (
        "/workers/scripts",
        "Account > Workers Scripts > Read",
        "Account > Workers Scripts > Edit",
    ),
    ("/dns_records", "Zone > DNS > Read", "Zone > DNS > Edit"),
    (
        "/firewall/access_rules",
        "Zone > Firewall Services > Read",
        "Zone > Firewall Services > Edit",
    ),
    ("/purge_cache", "Zone > Cache Purge > Purge", "Zone > Cache Purge > Purge"),
    ("/settings/", "Zone > Zone Settings > Read", "Zone > Zone Settings > Edit"),
    ("/pages/", "Pages Read", "Pages Write"),
    ("/graphql", "Zone > Analytics > Read", "Zone > Analytics > Read"),
    ("/zones", "Zone > Zone > Read", "Zone > Zone > Edit"),
)


def required_permission_group(method: str, endpoint: str) -> Optional[str]:
    """
    Return the Cloudflare API-token permission group a request needs.

    Args:
        method: HTTP method of the request
        endpoint: API endpoint path (e.g. "/zones/<id>/dns_records/<id>")

    Returns:
        The permission group name, or None when the endpoint family is unmapped.
    """
    for fragment, read_group, write_group in PERMISSION_GROUPS:
        if fragment in endpoint:
            return write_group if method.upper() in WRITE_METHODS else read_group
    return None


def build_forbidden_error(method: str, endpoint: str, api_message: str) -> str:
    """
    Build an actionable message for a Cloudflare HTTP 403 response.

    Cloudflare returns 403 with the generic message "Authentication error" both
    for an invalid credential and for a valid token that lacks the permission
    group for the operation. The bare API message reads like a broken
    credential, which sends diagnosis down the wrong path, so name the real
    cause and the rotation command.

    Args:
        method: HTTP method of the failed request
        endpoint: API endpoint path of the failed request
        api_message: Message Cloudflare returned in the errors array

    Returns:
        Multi-line error message text
    """
    upper_method = method.upper()
    lines = [
        f"API request failed (403): {api_message}",
        "",
        f"Cloudflare refused {upper_method} {endpoint}.",
        "A Cloudflare 403 means either an invalid credential or a valid API "
        "token that lacks the permission group for this operation. Cloudflare "
        "reports both as an authentication error.",
    ]

    permission_group = required_permission_group(method, endpoint)
    if permission_group is not None:
        lines.append(f"Permission group required: {permission_group}")

    if upper_method in WRITE_METHODS:
        lines.append(
            "Read commands that keep working prove the token is valid and "
            "prove the token is missing Edit scope, not that it expired."
        )

    lines.extend(
        [
            "",
            "Confirm the token is valid and active:",
            "  cloudflare auth test",
            "",
            "Note: 'cloudflare auth test' only issues a read. It passes on a "
            "read-only token and cannot detect missing Edit scope.",
            "",
            "Mint a replacement token in the Cloudflare dashboard with the "
            "permission group above, then store it:",
            f"  {SECRETS_MANAGER} set {API_TOKEN_SECRET_NAME}",
        ]
    )

    return "\n".join(lines)

# GraphQL Analytics API queries
ANALYTICS_SUMMARY_QUERY = """
query AnalyticsSummary($zoneTag: string, $start: string, $end: string) {
  viewer {
    zones(filter: { zoneTag: $zoneTag }) {
      httpRequests1dGroups(
        limit: 366
        filter: { date_geq: $start, date_leq: $end }
        orderBy: [date_ASC]
      ) {
        dimensions { date }
        sum { pageViews requests bytes cachedRequests threats }
        uniq { uniques }
      }
    }
  }
}
"""

TOP_PATHS_QUERY = """
query TopPaths($zoneTag: string, $start: Time, $end: Time, $limit: uint64!) {
  viewer {
    zones(filter: { zoneTag: $zoneTag }) {
      total: httpRequestsAdaptiveGroups(
        limit: 1
        filter: { datetime_geq: $start, datetime_lt: $end, edgeResponseContentTypeName: "html" }
      ) {
        count
      }
      topPaths: httpRequestsAdaptiveGroups(
        limit: $limit
        filter: { datetime_geq: $start, datetime_lt: $end, edgeResponseContentTypeName: "html" }
        orderBy: [count_DESC]
      ) {
        count
        dimensions { clientRequestPath }
      }
    }
  }
}
"""


from cli_tools_shared.exceptions import ClientError


class CloudflareClient:
    """Client for interacting with Cloudflare API with automatic token management and retry."""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        """
        Initialize Cloudflare client from configuration.

        Args:
            max_retries: Maximum number of retry attempts for transient errors (default: 3)
            base_delay: Base delay in seconds for exponential backoff (default: 1.0)
            max_delay: Maximum delay in seconds between retries (default: 30.0)
            jitter: Random jitter factor to prevent thundering herd (default: 0.1)
        """
        self.config = get_config()

        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'cloudflare auth login' to authenticate."
            )

        self.base_url = self.config.base_url
        self._update_headers()

        # Retry configuration
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    def _update_headers(self):
        """Update request headers with current credentials."""
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        # Use Bearer token authentication
        if self.config.api_key:
            self.headers["Authorization"] = f"Bearer {self.config.api_key}"

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """
        Calculate delay before next retry using exponential backoff with jitter.

        Args:
            attempt: Current retry attempt number (0-indexed)
            retry_after: Optional Retry-After header value from server

        Returns:
            Delay in seconds before next retry
        """
        # Honor Retry-After header if present
        if retry_after is not None:
            return min(retry_after, self.max_delay)

        # Exponential backoff: base_delay * 2^attempt
        delay = self.base_delay * (2 ** attempt)

        # Add random jitter to prevent thundering herd
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)

        # Cap at max delay
        return min(delay, self.max_delay)

    def _is_retryable(self, response: Optional[requests.Response], exception: Optional[Exception]) -> bool:
        """
        Determine if a request should be retried.

        Args:
            response: Response object (if request completed)
            exception: Exception raised (if request failed)

        Returns:
            True if request should be retried
        """
        # Retry on connection errors
        if exception is not None:
            return isinstance(exception, (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ))

        # Retry on specific status codes
        if response is not None:
            return response.status_code in RETRYABLE_STATUS_CODES

        return False

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        """
        Extract Retry-After header value from response.

        Args:
            response: Response object

        Returns:
            Retry delay in seconds, or None if not present
        """
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return None

        try:
            # Try parsing as integer seconds
            return float(retry_after)
        except ValueError:
            # Could be HTTP-date format, but we'll skip that complexity
            return None

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
        files: Optional[Dict] = None,
        raw: bool = False,
        headers: Optional[Dict] = None,
    ) -> Union[Dict, str]:
        """
        Make an HTTP request to the Cloudflare API with exponential retry.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: API endpoint path (e.g., "/zones")
            data: Request body data
            params: Query parameters
            retry: Whether to retry on transient errors (default: True)
            files: Multipart form parts (requests-style). When set, the JSON
                body and the static Content-Type header are dropped so requests
                can build a multipart/form-data payload (Workers uploads).
            raw: When True, return the response body text on success instead
                of parsing the Cloudflare JSON envelope (Workers script
                download returns raw script content, not JSON).
            headers: Per-request header overrides merged over the client-wide
                headers (e.g. Accept: application/javascript for script
                downloads).

        Returns:
            Response JSON data, or the raw body text when raw=True

        Raises:
            ClientError: If request fails after all retries
        """
        url = f"{self.base_url}{endpoint}"

        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None

        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                # Make the request. A multipart upload must not carry the
                # client-wide "Content-Type: application/json" header; requests
                # supplies its own header with the boundary.
                request_headers = dict(self.headers)
                if headers:
                    request_headers.update(headers)
                if files is not None:
                    request_headers = {
                        k: v for k, v in request_headers.items()
                        if k.lower() != "content-type"
                    }
                response = requests.request(
                    method=method,
                    url=url,
                    headers=request_headers,
                    json=None if files is not None else data,
                    files=files,
                    params=params,
                )
                last_response = response

                # Check if we should retry this response
                if retry and self._is_retryable(response, None) and attempt < self.max_retries:
                    retry_after = self._get_retry_after(response)
                    delay = self._calculate_retry_delay(attempt, retry_after)
                    time.sleep(delay)
                    continue

                # Success or non-retryable error - exit loop
                break

            except requests.exceptions.RequestException as e:
                last_exception = e
                # Check if we should retry this exception
                if retry and self._is_retryable(None, e) and attempt < self.max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    time.sleep(delay)
                    continue
                # Non-retryable exception or exhausted retries
                break

        # Handle the final result
        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed after {attempt + 1} attempts: {last_exception}")

        if last_response is None:
            raise ClientError("Request failed: no response received")

        # Raw success responses (script content) skip envelope parsing.
        if raw and last_response.ok:
            return last_response.text

        # Parse Cloudflare API response
        try:
            response_data = last_response.json()
        except Exception:
            if not last_response.ok:
                raise ClientError(f"API request failed ({last_response.status_code}): {last_response.text}")
            return {}

        # Cloudflare API returns {"success": bool, "errors": [...], "result": ...}
        if not response_data.get("success", True):
            errors = response_data.get("errors", [])
            if errors:
                error_msg = errors[0].get("message", "Unknown error")
            else:
                error_msg = "Request failed"
            if last_response.status_code == 403:
                raise ClientError(build_forbidden_error(method, endpoint, error_msg))
            raise ClientError(f"API request failed ({last_response.status_code}): {error_msg}")

        return response_data

    # ==================== API Methods ====================
    # All methods return Pydantic models for type safety and validation

    def list_zones(self, limit: int = 50, filters: Optional[List[str]] = None) -> List[Zone]:
        """
        List zones from the Cloudflare API with automatic pagination.

        Limiting: API-level (uses 'per_page' query param)
        Filtering: API-level where supported

        Args:
            limit: Maximum number of zones to return
            filters: List of filter strings (field:op:value)

        Returns:
            List of Zone models
        """
        API_MAX_PER_PAGE = 50

        base_params = {}

        if filters:
            try:
                validate_filters(filters)
                for f in filters:
                    parts = f.split(":", 2)
                    if len(parts) >= 2:
                        field = parts[0]
                        value = parts[-1]
                        if field in ["name", "status"]:
                            base_params[field] = value
            except FilterValidationError as e:
                raise ClientError(f"Invalid filter: {e}")

        all_zones: List[Zone] = []
        page = 1
        remaining = limit

        while remaining > 0:
            per_page = min(remaining, API_MAX_PER_PAGE)
            params = {**base_params, "per_page": per_page, "page": page}

            response = self._make_request("GET", "/zones", params=params)
            raw_zones = response.get("result", [])
            zones = [create_zone(zone) for zone in raw_zones]
            all_zones.extend(zones)

            # Stop if fewer results than requested (no more pages)
            if len(raw_zones) < per_page:
                break

            # Check total pages from result_info
            result_info = response.get("result_info", {})
            total_pages = result_info.get("total_pages", 1)
            if page >= total_pages:
                break

            remaining -= len(raw_zones)
            page += 1

        return all_zones

    def get_zone(self, zone_id: str) -> ZoneDetail:
        """
        Get a specific zone by ID.

        Args:
            zone_id: The zone ID

        Returns:
            ZoneDetail model with full details
        """
        response = self._make_request("GET", f"/zones/{zone_id}")

        # Extract zone from response
        raw_zone = response.get("result", {})

        return create_zone_detail(raw_zone)

    def purge_cache(self, zone_id: str) -> PurgeResult:
        """
        Purge all cache for a zone.

        Args:
            zone_id: The zone ID to purge cache for

        Returns:
            PurgeResult model with operation ID
        """
        response = self._make_request(
            "POST",
            f"/zones/{zone_id}/purge_cache",
            data={"purge_everything": True}
        )

        # Extract result from response
        raw_result = response.get("result", {})

        return create_purge_result(raw_result)

    def set_security_level(self, zone_id: str, level: str) -> dict:
        """
        Set security level for a zone.

        Args:
            zone_id: The zone ID
            level: Security level (off, essentially_off, low, medium, high, under_attack)

        Returns:
            dict with updated setting
        """
        response = self._make_request(
            "PATCH",
            f"/zones/{zone_id}/settings/security_level",
            data={"value": level}
        )
        return response.get("result", {})

    def resolve_zone_id(self, zone: str) -> str:
        """
        Resolve a zone name or zone ID to a zone ID.

        Args:
            zone: Zone name (e.g. example.com) or 32-character hex zone ID

        Returns:
            The zone ID

        Raises:
            ClientError: If no zone matches the given name
        """
        if ZONE_ID_PATTERN.match(zone):
            return zone

        matches = [z for z in self.list_zones(filters=[f"name:eq:{zone}"]) if z.name == zone]
        if not matches:
            raise ClientError(f"Zone not found: {zone}")
        return matches[0].id

    # ==================== Analytics (GraphQL) ====================

    def graphql(self, query: str, variables: Dict) -> Dict:
        """
        Execute a query against the Cloudflare GraphQL Analytics API.

        Args:
            query: GraphQL query string
            variables: GraphQL variables

        Returns:
            The GraphQL "data" object

        Raises:
            ClientError: If the query returns errors or no data
        """
        response = self._make_request("POST", "/graphql", data={"query": query, "variables": variables})

        errors = response.get("errors")
        if errors:
            raise ClientError(f"GraphQL query failed: {errors[0].get('message', errors[0])}")

        data = response.get("data")
        if data is None:
            raise ClientError("GraphQL query returned no data")
        return data

    def _graphql_zone_data(self, query: str, variables: Dict, zone_id: str) -> Dict:
        """Run a zone-scoped GraphQL query and return the single zone node."""
        data = self.graphql(query, variables)
        zones = data["viewer"]["zones"]
        if not zones:
            raise ClientError(f"No analytics data returned for zone {zone_id}")
        return zones[0]

    def get_analytics_summary(self, zone_id: str, start: str, end: str) -> Dict:
        """
        Get zone traffic totals for a date range from httpRequests1dGroups.

        Args:
            zone_id: The zone ID
            start: Start date (YYYY-MM-DD, inclusive)
            end: End date (YYYY-MM-DD, inclusive)

        Returns:
            dict with totals: page_views, unique_visitors, requests, bytes, etc.
            unique_visitors is the SUM of per-day uniques (daily rollup dataset),
            not deduplicated across days.
        """
        zone_node = self._graphql_zone_data(
            ANALYTICS_SUMMARY_QUERY,
            {"zoneTag": zone_id, "start": start, "end": end},
            zone_id,
        )
        days = zone_node["httpRequests1dGroups"]

        return {
            "zone_id": zone_id,
            "start": start,
            "end": end,
            "days_with_data": len(days),
            "page_views": sum(d["sum"]["pageViews"] for d in days),
            "unique_visitors": sum(d["uniq"]["uniques"] for d in days),
            "unique_visitors_basis": "sum_of_daily_uniques",
            "requests": sum(d["sum"]["requests"] for d in days),
            "bytes": sum(d["sum"]["bytes"] for d in days),
            "cached_requests": sum(d["sum"]["cachedRequests"] for d in days),
            "threats": sum(d["sum"]["threats"] for d in days),
        }

    def get_top_paths(self, zone_id: str, start: str, end: str, limit: int = 20) -> List[Dict]:
        """
        Get top request paths by HTML page views from httpRequestsAdaptiveGroups.

        Filtered to edge responses with content type "html" (page views).
        Data is adaptively sampled by Cloudflare.

        Args:
            zone_id: The zone ID
            start: Start date (YYYY-MM-DD, inclusive)
            end: End date (YYYY-MM-DD, inclusive)
            limit: Maximum number of paths to return

        Returns:
            List of dicts with path, page_views, and pct_of_total
        """
        end_exclusive = date.fromisoformat(end) + timedelta(days=1)
        zone_node = self._graphql_zone_data(
            TOP_PATHS_QUERY,
            {
                "zoneTag": zone_id,
                "start": f"{start}T00:00:00Z",
                "end": f"{end_exclusive.isoformat()}T00:00:00Z",
                "limit": limit,
            },
            zone_id,
        )

        total_nodes = zone_node["total"]
        total = total_nodes[0]["count"] if total_nodes else 0

        return [
            {
                "path": node["dimensions"]["clientRequestPath"],
                "page_views": node["count"],
                "pct_of_total": round(node["count"] * 100.0 / total, 2) if total else 0.0,
            }
            for node in zone_node["topPaths"]
        ]

    # ==================== IP Access Rules ====================

    def list_access_rules(
        self,
        zone_id: str,
        limit: int = 50,
        mode: Optional[str] = None,
        target: Optional[str] = None,
        value: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> List[AccessRule]:
        """
        List IP Access rules for a zone with automatic pagination.

        Args:
            zone_id: The zone ID
            limit: Maximum number of rules to return
            mode: Filter by mode (whitelist, block, challenge, etc.)
            target: Filter by configuration target (ip, ip_range, asn, country)
            value: Filter by configuration value (IP address, ASN, etc.)
            notes: Filter by notes (partial match)

        Returns:
            List of AccessRule models
        """
        API_MAX_PER_PAGE = 50

        base_params: Dict = {}
        if mode:
            base_params["mode"] = mode
        if target:
            base_params["configuration.target"] = target
        if value:
            base_params["configuration.value"] = value
        if notes:
            base_params["notes"] = notes

        all_rules: List[AccessRule] = []
        page = 1
        remaining = limit

        while remaining > 0:
            per_page = min(remaining, API_MAX_PER_PAGE)
            params = {**base_params, "per_page": per_page, "page": page}

            response = self._make_request(
                "GET",
                f"/zones/{zone_id}/firewall/access_rules/rules",
                params=params
            )

            raw_rules = response.get("result", [])
            all_rules.extend([create_access_rule(rule) for rule in raw_rules])

            if len(raw_rules) < per_page:
                break

            result_info = response.get("result_info", {})
            total_pages = result_info.get("total_pages", 1)
            if page >= total_pages:
                break

            remaining -= len(raw_rules)
            page += 1

        return all_rules

    def get_access_rule(self, zone_id: str, rule_id: str) -> AccessRule:
        """
        Get a specific IP Access rule.

        Args:
            zone_id: The zone ID
            rule_id: The rule ID

        Returns:
            AccessRule model
        """
        response = self._make_request(
            "GET",
            f"/zones/{zone_id}/firewall/access_rules/rules/{rule_id}"
        )

        raw_rule = response.get("result", {})
        return create_access_rule(raw_rule)

    def create_access_rule(
        self,
        zone_id: str,
        target: str,
        value: str,
        mode: str,
        notes: Optional[str] = None,
    ) -> AccessRule:
        """
        Create a new IP Access rule.

        Args:
            zone_id: The zone ID
            target: Configuration target (ip, ip_range, asn, country, ipv6)
            value: Configuration value (IP address, CIDR, ASN, country code)
            mode: Action mode (whitelist, block, challenge, js_challenge, managed_challenge)
            notes: Optional notes/description

        Returns:
            Created AccessRule model
        """
        data = {
            "configuration": {
                "target": target,
                "value": value,
            },
            "mode": mode,
        }

        if notes:
            data["notes"] = notes

        response = self._make_request(
            "POST",
            f"/zones/{zone_id}/firewall/access_rules/rules",
            data=data
        )

        raw_rule = response.get("result", {})
        return create_access_rule(raw_rule)

    def update_access_rule(
        self,
        zone_id: str,
        rule_id: str,
        mode: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> AccessRule:
        """
        Update an IP Access rule.

        Args:
            zone_id: The zone ID
            rule_id: The rule ID
            mode: New action mode (if updating)
            notes: New notes (if updating)

        Returns:
            Updated AccessRule model
        """
        data = {}

        if mode is not None:
            data["mode"] = mode
        if notes is not None:
            data["notes"] = notes

        response = self._make_request(
            "PATCH",
            f"/zones/{zone_id}/firewall/access_rules/rules/{rule_id}",
            data=data
        )

        raw_rule = response.get("result", {})
        return create_access_rule(raw_rule)

    def delete_access_rule(self, zone_id: str, rule_id: str) -> dict:
        """
        Delete an IP Access rule.

        Args:
            zone_id: The zone ID
            rule_id: The rule ID

        Returns:
            dict with deleted rule ID
        """
        response = self._make_request(
            "DELETE",
            f"/zones/{zone_id}/firewall/access_rules/rules/{rule_id}"
        )

        return response.get("result", {})

    # ==================== DNS Records ====================

    def list_dns_records(
        self,
        zone_id: str,
        limit: int = 100,
        record_type: Optional[str] = None,
        name: Optional[str] = None,
        content: Optional[str] = None,
        proxied: Optional[bool] = None,
    ) -> List[DNSRecord]:
        """
        List DNS records for a zone with automatic pagination.

        Args:
            zone_id: The zone ID
            limit: Maximum number of records to return
            record_type: Filter by record type (A, AAAA, CNAME, TXT, etc.)
            name: Filter by exact name match
            content: Filter by content match
            proxied: Filter by proxied status

        Returns:
            List of DNSRecord models
        """
        API_MAX_PER_PAGE = 5000

        base_params: Dict = {}
        if record_type:
            base_params["type"] = record_type
        if name:
            base_params["name"] = name
        if content:
            base_params["content"] = content
        if proxied is not None:
            base_params["proxied"] = proxied

        all_records: List[DNSRecord] = []
        page = 1
        remaining = limit

        while remaining > 0:
            per_page = min(remaining, API_MAX_PER_PAGE)
            params = {**base_params, "per_page": per_page, "page": page}

            response = self._make_request(
                "GET",
                f"/zones/{zone_id}/dns_records",
                params=params
            )

            raw_records = response.get("result", [])
            all_records.extend([create_dns_record(record) for record in raw_records])

            if len(raw_records) < per_page:
                break

            result_info = response.get("result_info", {})
            total_pages = result_info.get("total_pages", 1)
            if page >= total_pages:
                break

            remaining -= len(raw_records)
            page += 1

        return all_records

    def get_dns_record(self, zone_id: str, record_id: str) -> DNSRecord:
        """
        Get a specific DNS record.

        Args:
            zone_id: The zone ID
            record_id: The record ID

        Returns:
            DNSRecord model
        """
        response = self._make_request(
            "GET",
            f"/zones/{zone_id}/dns_records/{record_id}"
        )

        raw_record = response.get("result", {})
        return create_dns_record(raw_record)

    def create_dns_record(
        self,
        zone_id: str,
        record_type: str,
        name: str,
        content: str,
        ttl: int = 1,
        proxied: bool = False,
        priority: Optional[int] = None,
        comment: Optional[str] = None,
    ) -> DNSRecord:
        """
        Create a new DNS record.

        Args:
            zone_id: The zone ID
            record_type: Record type (A, AAAA, CNAME, TXT, MX, etc.)
            name: Record name (e.g., example.com, subdomain.example.com)
            content: Record content (IP, hostname, text, etc.)
            ttl: TTL in seconds (1 = auto, 60-86400 for custom)
            proxied: Whether to proxy through Cloudflare
            priority: Priority for MX/SRV records
            comment: Optional comment

        Returns:
            Created DNSRecord model
        """
        data = {
            "type": record_type,
            "name": name,
            "content": content,
            "ttl": ttl,
            "proxied": proxied,
        }

        if priority is not None:
            data["priority"] = priority
        if comment:
            data["comment"] = comment

        response = self._make_request(
            "POST",
            f"/zones/{zone_id}/dns_records",
            data=data
        )

        raw_record = response.get("result", {})
        return create_dns_record(raw_record)

    def update_dns_record(
        self,
        zone_id: str,
        record_id: str,
        record_type: Optional[str] = None,
        name: Optional[str] = None,
        content: Optional[str] = None,
        ttl: Optional[int] = None,
        proxied: Optional[bool] = None,
        priority: Optional[int] = None,
        comment: Optional[str] = None,
    ) -> DNSRecord:
        """
        Update a DNS record.

        Args:
            zone_id: The zone ID
            record_id: The record ID
            record_type: New record type (if changing)
            name: New record name (if changing)
            content: New content (if changing)
            ttl: New TTL (if changing)
            proxied: New proxied status (if changing)
            priority: New priority (if changing)
            comment: New comment (if changing)

        Returns:
            Updated DNSRecord model
        """
        data = {}

        if record_type is not None:
            data["type"] = record_type
        if name is not None:
            data["name"] = name
        if content is not None:
            data["content"] = content
        if ttl is not None:
            data["ttl"] = ttl
        if proxied is not None:
            data["proxied"] = proxied
        if priority is not None:
            data["priority"] = priority
        if comment is not None:
            data["comment"] = comment

        response = self._make_request(
            "PATCH",
            f"/zones/{zone_id}/dns_records/{record_id}",
            data=data
        )

        raw_record = response.get("result", {})
        return create_dns_record(raw_record)

    def delete_dns_record(self, zone_id: str, record_id: str) -> dict:
        """
        Delete a DNS record.

        Args:
            zone_id: The zone ID
            record_id: The record ID

        Returns:
            dict with deleted record ID
        """
        response = self._make_request(
            "DELETE",
            f"/zones/{zone_id}/dns_records/{record_id}"
        )

        return response.get("result", {})

    # ==================== Account Workers Scripts ====================
    # Account-level endpoints need an account ID; scripts are listed,
    # downloaded (raw), uploaded (multipart), and deleted per account.

    def _envelope(self, method: str, endpoint: str, **kwargs) -> Dict:
        """
        Run a JSON-envelope request and narrow the Union result to a dict.

        Args:
            method: HTTP method
            endpoint: API endpoint path
            **kwargs: Forwarded to _make_request

        Returns:
            The parsed Cloudflare response envelope

        Raises:
            ClientError: If the API returns a non-JSON body
        """
        response = self._make_request(method, endpoint, **kwargs)
        if isinstance(response, dict):
            return response
        raise ClientError(f"Unexpected non-JSON response for {method} {endpoint}")

    def list_accounts(self, limit: int = 50) -> List[Dict]:
        """
        List Cloudflare accounts visible to the current token.

        Args:
            limit: Maximum number of accounts to return

        Returns:
            List of account dicts (id, name, ...)
        """
        API_MAX_PER_PAGE = 50

        all_accounts: List[Dict] = []
        page = 1
        remaining = limit

        while remaining > 0:
            per_page = min(remaining, API_MAX_PER_PAGE)
            params = {"per_page": per_page, "page": page}

            response = self._envelope("GET", "/accounts", params=params)
            raw_accounts = response.get("result", [])
            all_accounts.extend(raw_accounts)

            if len(raw_accounts) < per_page:
                break

            result_info = response.get("result_info", {})
            total_pages = result_info.get("total_pages", 1)
            if page >= total_pages:
                break

            remaining -= len(raw_accounts)
            page += 1

        return all_accounts

    def resolve_account_id(self, account: str) -> str:
        """
        Resolve an account name or account ID to an account ID.

        Args:
            account: Account name or 32-character hex account ID

        Returns:
            The account ID

        Raises:
            ClientError: If no account matches the given name
        """
        if ACCOUNT_ID_PATTERN.match(account):
            return account

        matches = [a for a in self.list_accounts(limit=100) if a.get("name") == account]
        if not matches:
            raise ClientError(f"Account not found: {account}")
        return matches[0]["id"]

    def default_account_id(self) -> str:
        """
        Return the single account visible to the current token.

        Raises:
            ClientError: If zero or multiple accounts are visible, naming them
                so the caller can pass one explicitly.
        """
        accounts = self.list_accounts(limit=2)
        if not accounts:
            raise ClientError(
                "No Cloudflare accounts are visible to this token. "
                "Workers commands need 'Account' scope."
            )
        if len(accounts) > 1:
            names = ", ".join(
                f"{a.get('name')} ({a.get('id')})" for a in accounts
            )
            raise ClientError(
                f"Multiple Cloudflare accounts are visible. Specify one: {names}"
            )
        return accounts[0]["id"]

    def list_worker_scripts(self, account_id: str, limit: int = 100) -> List[Dict]:
        """
        List Workers scripts for an account.

        The Workers Scripts endpoint returns the full script set in a single
        response (it ignores ``per_page``/``page`` query parameters), so the
        limit is enforced client-side.

        Args:
            account_id: The account ID
            limit: Maximum number of scripts to return

        Returns:
            List of script dicts (id, created_on, modified_on, ...)
        """
        response = self._envelope(
            "GET",
            f"/accounts/{account_id}/workers/scripts",
        )
        raw_scripts = response.get("result", [])
        if not isinstance(raw_scripts, list):
            raise ClientError(
                "Unexpected non-list result for GET "
                f"/accounts/{account_id}/workers/scripts"
            )
        return raw_scripts[:limit]

    def get_worker_script(self, account_id: str, script_name: str) -> str:
        """
        Download a Worker script's source content.

        Args:
            account_id: The account ID
            script_name: The worker script name

        Returns:
            The raw script content (not a JSON envelope)
        """
        content = self._make_request(
            "GET",
            f"/accounts/{account_id}/workers/scripts/{script_name}",
            headers={"Accept": "application/javascript"},
            raw=True,
        )
        if isinstance(content, str):
            return content
        raise ClientError(f"Unexpected response downloading script {script_name}")

    def upload_worker_script(
        self,
        account_id: str,
        script_name: str,
        content: str,
        script_format: str = "modules",
        main_module: str = "worker.js",
        bindings: Optional[List[Dict]] = None,
        compatibility_date: Optional[str] = None,
    ) -> Dict:
        """
        Upload (create or replace) a Worker script via multipart PUT.

        Args:
            account_id: The account ID
            script_name: The worker script name
            content: The script source content
            script_format: "modules" (default) or "service-worker"
            main_module: Entry module filename (modules format only)
            bindings: Optional list of binding dicts sent in the metadata part
            compatibility_date: Optional compatibility date (YYYY-MM-DD)

        Returns:
            dict with upload metadata from the API result
        """
        metadata: Dict = {}
        if script_format == "modules":
            metadata["main_module"] = main_module
        if compatibility_date:
            metadata["compatibility_date"] = compatibility_date
        if bindings is not None:
            metadata["bindings"] = bindings

        media_type = (
            "application/javascript+module"
            if script_format == "modules"
            else "application/javascript"
        )

        files = {
            "metadata": (
                None,
                json.dumps(metadata),
                "application/json",
            ),
            "file": (
                f"{script_name}.js",
                content,
                media_type,
            ),
        }

        response = self._envelope(
            "PUT",
            f"/accounts/{account_id}/workers/scripts/{script_name}",
            files=files,
        )
        return response.get("result", {})

    def delete_worker_script(self, account_id: str, script_name: str) -> Dict:
        """
        Delete a Worker script.

        Args:
            account_id: The account ID
            script_name: The worker script name

        Returns:
            dict with the deleted script ID
        """
        response = self._envelope(
            "DELETE",
            f"/accounts/{account_id}/workers/scripts/{script_name}"
        )
        return response.get("result", {})

    # ==================== Workers Routes (zone-scoped) ====================

    def list_worker_routes(self, zone_id: str) -> List[Dict]:
        """
        List Worker routes for a zone.

        The Worker routes endpoint returns the full route set in a single
        response (no pagination parameters), so limiting and filtering are
        applied at the command layer.

        Args:
            zone_id: The zone ID

        Returns:
            List of route dicts (id, pattern, script)
        """
        response = self._envelope("GET", f"/zones/{zone_id}/workers/routes")
        result = response.get("result", [])
        return result if isinstance(result, list) else []

    def get_worker_route(self, zone_id: str, route_id: str) -> Dict:
        """
        Get a single Worker route for a zone.

        Args:
            zone_id: The zone ID
            route_id: The route ID

        Returns:
            dict with the route details (id, pattern, script)
        """
        response = self._envelope(
            "GET",
            f"/zones/{zone_id}/workers/routes/{route_id}"
        )
        return response.get("result", {})

    def create_worker_route(self, zone_id: str, pattern: str, script: str) -> Dict:
        """
        Create a Worker route binding a URL pattern to a script.

        Args:
            zone_id: The zone ID
            pattern: Route pattern (e.g. "example.com/llms.txt*")
            script: Worker script name to invoke for matching requests

        Returns:
            dict with the created route (id, pattern, script)
        """
        response = self._envelope(
            "POST",
            f"/zones/{zone_id}/workers/routes",
            data={"pattern": pattern, "script": script}
        )
        return response.get("result", {})

    def delete_worker_route(self, zone_id: str, route_id: str) -> dict:
        """
        Delete a Worker route.

        Args:
            zone_id: The zone ID
            route_id: The route ID

        Returns:
            dict with the deleted route ID
        """
        response = self._envelope(
            "DELETE",
            f"/zones/{zone_id}/workers/routes/{route_id}"
        )
        return response.get("result", {})

    # ==================== Pages ====================
    # Account-level Pages management: projects, deployments, and custom
    # domains. All endpoints live under /accounts/{account_id}/pages/...
    # (Cloudflare v4 API). Projects and deployments list endpoints paginate
    # with page/per_page; the domains list endpoint returns everything in a
    # single response (no pagination parameters).

    def _paginated_list(self, endpoint: str, limit: int, base_params: Optional[Dict] = None) -> List[Dict]:
        """
        Fetch a paginated Cloudflare list endpoint up to ``limit`` items.

        Args:
            endpoint: API path returning {"result": [...], "result_info": {...}}
            limit: Maximum number of items to return
            base_params: Query params merged into every page request

        Returns:
            Combined result items across pages
        """
        API_MAX_PER_PAGE = 25

        all_items: List[Dict] = []
        page = 1
        remaining = limit

        while remaining > 0:
            per_page = min(remaining, API_MAX_PER_PAGE)
            params = {**(base_params or {}), "per_page": per_page, "page": page}

            response = self._envelope("GET", endpoint, params=params)
            raw_items = response.get("result", [])
            if not isinstance(raw_items, list):
                raise ClientError(f"Unexpected non-list result for GET {endpoint}")
            all_items.extend(raw_items)

            if len(raw_items) < per_page:
                break

            result_info = response.get("result_info", {})
            total_pages = result_info.get("total_pages", 1)
            if page >= total_pages:
                break

            remaining -= len(raw_items)
            page += 1

        return all_items

    def list_pages_projects(self, account_id: str, limit: int = 100) -> List[Dict]:
        """
        List Pages projects for an account with automatic pagination.

        Args:
            account_id: The account ID
            limit: Maximum number of projects to return

        Returns:
            List of project dicts (id/name via "name", production_branch, ...)
        """
        return self._paginated_list(f"/accounts/{account_id}/pages/projects", limit)

    def get_pages_project(self, account_id: str, project_name: str) -> Dict:
        """
        Get a single Pages project.

        Args:
            account_id: The account ID
            project_name: The project name

        Returns:
            Project dict
        """
        response = self._envelope(
            "GET", f"/accounts/{account_id}/pages/projects/{project_name}"
        )
        return response.get("result", {})

    def create_pages_project(
        self,
        account_id: str,
        name: str,
        production_branch: str,
        config: Optional[Dict] = None,
    ) -> Dict:
        """
        Create a Pages project.

        Args:
            account_id: The account ID
            name: Project name
            production_branch: Branch that identifies production deployments
            config: Optional extra body fields (build_config,
                deployment_configs, source, ...) merged into the request

        Returns:
            Created project dict
        """
        data: Dict = {"name": name, "production_branch": production_branch}
        if config:
            data.update(config)

        response = self._envelope("POST", f"/accounts/{account_id}/pages/projects", data=data)
        return response.get("result", {})

    def patch_pages_project(self, account_id: str, project_name: str, data: Dict) -> Dict:
        """
        Patch an existing Pages project (single PATCH edit endpoint).

        Args:
            account_id: The account ID
            project_name: The project name
            data: JSON body fields (production_branch, build_config,
                deployment_configs, ...). Setting an env var key to null
                deletes it per the Cloudflare API.

        Returns:
            Updated project dict
        """
        response = self._envelope(
            "PATCH", f"/accounts/{account_id}/pages/projects/{project_name}", data=data
        )
        return response.get("result", {})

    def delete_pages_project(self, account_id: str, project_name: str) -> Dict:
        """
        Delete a Pages project.

        Args:
            account_id: The account ID
            project_name: The project name

        Returns:
            Result dict from the delete response
        """
        response = self._envelope(
            "DELETE", f"/accounts/{account_id}/pages/projects/{project_name}"
        )
        return response.get("result", {})

    def purge_pages_build_cache(self, account_id: str, project_name: str) -> Dict:
        """
        Purge all cached build artifacts for a Pages project.

        Args:
            account_id: The account ID
            project_name: The project name

        Returns:
            Result dict from the purge response
        """
        response = self._envelope(
            "POST", f"/accounts/{account_id}/pages/projects/{project_name}/purge_build_cache"
        )
        return response.get("result", {})

    def get_pages_upload_token(self, account_id: str, project_name: str) -> Dict:
        """
        Get the direct-upload token for a Pages project.

        Args:
            account_id: The account ID
            project_name: The project name

        Returns:
            Result dict containing the upload token (e.g. {"jwt": "..."})
        """
        response = self._envelope(
            "GET", f"/accounts/{account_id}/pages/projects/{project_name}/upload-token"
        )
        return response.get("result", {})

    def list_pages_deployments(
        self,
        account_id: str,
        project_name: str,
        limit: int = 100,
        env: Optional[str] = None,
    ) -> List[Dict]:
        """
        List deployments for a Pages project with automatic pagination.

        Args:
            account_id: The account ID
            project_name: The project name
            limit: Maximum number of deployments to return
            env: Optional environment filter ("production" or "preview")

        Returns:
            List of deployment dicts
        """
        base_params: Dict = {}
        if env:
            base_params["env"] = env
        return self._paginated_list(
            f"/accounts/{account_id}/pages/projects/{project_name}/deployments",
            limit,
            base_params,
        )

    def get_pages_deployment(
        self, account_id: str, project_name: str, deployment_id: str
    ) -> Dict:
        """
        Get a single deployment.

        Args:
            account_id: The account ID
            project_name: The project name
            deployment_id: The deployment ID

        Returns:
            Deployment dict
        """
        response = self._envelope(
            "GET",
            f"/accounts/{account_id}/pages/projects/{project_name}/deployments/{deployment_id}",
        )
        return response.get("result", {})

    def create_pages_deployment(
        self,
        account_id: str,
        project_name: str,
        branch: Optional[str] = None,
        commit_message: Optional[str] = None,
        commit_hash: Optional[str] = None,
        commit_dirty: Optional[bool] = None,
        manifest: Optional[str] = None,
    ) -> Dict:
        """
        Start a new deployment (multipart/form-data POST).

        For git-connected projects pass --branch to build from the branch HEAD.
        For direct-upload projects pass --manifest (a JSON object mapping file
        paths to content hashes); uploading the actual asset files uses the
        separate Pages assets endpoints, which this CLI does not automate.

        Args:
            account_id: The account ID
            project_name: The project name
            branch: Branch to build from (defaults to production branch)
            commit_message: Commit message metadata
            commit_hash: Commit SHA metadata
            commit_dirty: Whether the source had uncommitted changes
            manifest: JSON string of {path: hash} entries for direct upload

        Returns:
            Created deployment dict
        """
        files: Dict = {}
        if branch is not None:
            files["branch"] = (None, branch, None)
        if commit_message is not None:
            files["commit_message"] = (None, commit_message, None)
        if commit_hash is not None:
            files["commit_hash"] = (None, commit_hash, None)
        if commit_dirty is not None:
            files["commit_dirty"] = (None, "true" if commit_dirty else "false", None)
        if manifest is not None:
            files["manifest"] = (None, manifest, None)

        response = self._envelope(
            "POST",
            f"/accounts/{account_id}/pages/projects/{project_name}/deployments",
            files=files,
        )
        return response.get("result", {})

    def delete_pages_deployment(
        self,
        account_id: str,
        project_name: str,
        deployment_id: str,
        allow_aliased: bool = False,
    ) -> Dict:
        """
        Delete a deployment.

        Args:
            account_id: The account ID
            project_name: The project name
            deployment_id: The deployment ID
            allow_aliased: Send force=true so aliased non-production
                deployments can be deleted too

        Returns:
            Result dict ({id} of the deleted deployment) when present
        """
        params = {"force": "true"} if allow_aliased else None
        response = self._envelope(
            "DELETE",
            f"/accounts/{account_id}/pages/projects/{project_name}/deployments/{deployment_id}",
            params=params,
        )
        return response.get("result") or {}

    def retry_pages_deployment(
        self, account_id: str, project_name: str, deployment_id: str
    ) -> Dict:
        """
        Retry a failed deployment build.

        Args:
            account_id: The account ID
            project_name: The project name
            deployment_id: The deployment ID

        Returns:
            Deployment dict for the retried build
        """
        response = self._envelope(
            "POST",
            f"/accounts/{account_id}/pages/projects/{project_name}/deployments/{deployment_id}/retry",
        )
        return response.get("result", {})

    def rollback_pages_deployment(
        self, account_id: str, project_name: str, deployment_id: str
    ) -> Dict:
        """
        Roll production back to a previous successful production deployment.

        Args:
            account_id: The account ID
            project_name: The project name
            deployment_id: Target deployment ID (must be a successful
                production deployment)

        Returns:
            Deployment dict now serving production
        """
        response = self._envelope(
            "POST",
            f"/accounts/{account_id}/pages/projects/{project_name}/deployments/{deployment_id}/rollback",
        )
        return response.get("result", {})

    def list_pages_domains(self, account_id: str, project_name: str) -> List[Dict]:
        """
        List custom domains attached to a Pages project.

        The domains endpoint does not paginate; one request returns all
        domains.

        Args:
            account_id: The account ID
            project_name: The project name

        Returns:
            List of domain dicts (name, status, validation_data, ...)
        """
        response = self._envelope(
            "GET", f"/accounts/{account_id}/pages/projects/{project_name}/domains"
        )
        result = response.get("result", [])
        return result if isinstance(result, list) else []

    def add_pages_domain(
        self, account_id: str, project_name: str, domain_name: str
    ) -> Dict:
        """
        Add a custom domain to a Pages project.

        Args:
            account_id: The account ID
            project_name: The project name
            domain_name: Domain name to attach

        Returns:
            Created domain dict
        """
        response = self._envelope(
            "POST",
            f"/accounts/{account_id}/pages/projects/{project_name}/domains",
            data={"name": domain_name},
        )
        return response.get("result", {})

    def get_pages_domain(
        self, account_id: str, project_name: str, domain_name: str
    ) -> Dict:
        """
        Get a single custom domain.

        Args:
            account_id: The account ID
            project_name: The project name
            domain_name: The domain name

        Returns:
            Domain dict
        """
        response = self._envelope(
            "GET",
            f"/accounts/{account_id}/pages/projects/{project_name}/domains/{domain_name}",
        )
        return response.get("result", {})

    def revalidate_pages_domain(
        self, account_id: str, project_name: str, domain_name: str
    ) -> Dict:
        """
        Retry validation of a custom domain (PATCH edit endpoint).

        Args:
            account_id: The account ID
            project_name: The project name
            domain_name: The domain name

        Returns:
            Updated domain dict
        """
        response = self._envelope(
            "PATCH",
            f"/accounts/{account_id}/pages/projects/{project_name}/domains/{domain_name}",
            data={},
        )
        return response.get("result", {})

    def delete_pages_domain(
        self, account_id: str, project_name: str, domain_name: str
    ) -> Dict:
        """
        Remove a custom domain from a Pages project.

        Args:
            account_id: The account ID
            project_name: The project name
            domain_name: The domain name

        Returns:
            Result dict from the delete response
        """
        response = self._envelope(
            "DELETE",
            f"/accounts/{account_id}/pages/projects/{project_name}/domains/{domain_name}",
        )
        return response.get("result", {})


# Module-level client instance - singleton pattern
_client: Optional[CloudflareClient] = None


def get_client() -> CloudflareClient:
    """Get or create the global Cloudflare client instance."""
    global _client
    if _client is None:
        _client = CloudflareClient()
    return _client
