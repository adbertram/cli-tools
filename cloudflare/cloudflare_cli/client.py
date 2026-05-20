"""Cloudflare API client with automatic token management and exponential retry."""
from typing import Dict, List, Optional
import random
import time
import requests

from .config import get_config
from cli_tools_shared.filters import validate_filters, FilterValidationError
from .models import Zone, ZoneDetail, PurgeResult, create_zone, create_zone_detail, create_purge_result
from .models.access_rule import AccessRule, create_access_rule
from .models.dns_record import DNSRecord, create_dns_record


# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_JITTER = 0.1  # 10% jitter

# HTTP status codes that trigger retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


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
    ) -> Dict:
        """
        Make an HTTP request to the Cloudflare API with exponential retry.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: API endpoint path (e.g., "/zones")
            data: Request body data
            params: Query parameters
            retry: Whether to retry on transient errors (default: True)

        Returns:
            Response JSON data

        Raises:
            ClientError: If request fails after all retries
        """
        url = f"{self.base_url}{endpoint}"

        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None

        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                # Make the request
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    json=data,
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


# Module-level client instance - singleton pattern
_client: Optional[CloudflareClient] = None


def get_client() -> CloudflareClient:
    """Get or create the global Cloudflare client instance."""
    global _client
    if _client is None:
        _client = CloudflareClient()
    return _client
