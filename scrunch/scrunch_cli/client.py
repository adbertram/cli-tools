"""Scrunch API client with automatic token management and exponential retry."""
from datetime import datetime
from typing import Dict, List, Optional, Any
import random
import time
import requests

from .config import get_config
from cli_tools_shared.filters import validate_filters, FilterValidationError
from .models import (
    Brand, CreateBrand, UpdateBrand, create_brand,
    Competitor, CreateCompetitor, UpdateCompetitor, create_competitor,
    Persona, CreatePersona, UpdatePersona, create_persona,
    Prompt, CreatePrompt, create_prompt,
    QueryResult, create_query_result,
    ResponseListing, create_response_listing,
    PageAuditRecord, CreatePageAudit, create_page_audit,
    AgentTrafficRow, AgentTrafficResponse, create_agent_traffic_row,
)


# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_JITTER = 0.1  # 10% jitter

# HTTP status codes that trigger retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


from cli_tools_shared.exceptions import ClientError


class ScrunchClient:
    """Client for interacting with Scrunch API with automatic token management and retry."""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        """
        Initialize Scrunch client from configuration.

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
                "Run 'scrunch auth login' to authenticate."
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
        if self.config.access_token:
            self.headers["Authorization"] = f"Bearer {self.config.access_token}"
        elif self.config.personal_access_token:
            self.headers["Authorization"] = f"Bearer {self.config.personal_access_token}"
        elif self.config.api_key:
            self.headers["Authorization"] = f"Bearer {self.config.api_key}"

    def _is_token_expired(self) -> bool:
        """Check if access token is expired or about to expire."""
        expires_at = self.config.token_expires_at
        if not expires_at:
            return False

        try:
            expires_timestamp = float(expires_at)
            return datetime.now().timestamp() > (expires_timestamp - 300)
        except (ValueError, TypeError):
            return False

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """Calculate delay before next retry using exponential backoff with jitter."""
        if retry_after is not None:
            return min(retry_after, self.max_delay)

        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)
        return min(delay, self.max_delay)

    def _is_retryable(self, response: Optional[requests.Response], exception: Optional[Exception]) -> bool:
        """Determine if a request should be retried."""
        if exception is not None:
            return isinstance(exception, (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ))

        if response is not None:
            return response.status_code in RETRYABLE_STATUS_CODES

        return False

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        """Extract Retry-After header value from response."""
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return None

        try:
            return float(retry_after)
        except ValueError:
            return None

    def _extract_error_detail(self, response: requests.Response) -> str:
        """Extract error detail from an HTTP error response."""
        try:
            error_body = response.json()

            if "_error" in error_body:
                err = error_body["_error"]
                if isinstance(err, dict):
                    return err.get("Description") or err.get("Message") or err.get("Code") or str(err)
                return str(err)

            if "error" in error_body:
                err = error_body["error"]
                if isinstance(err, dict):
                    return err.get("message") or err.get("code") or err.get("description") or str(err)
                return str(err)

            if "message" in error_body:
                return error_body["message"]

            return str(error_body)[:500]
        except Exception:
            return response.text[:500] if response.text else "Unknown error"

    def _refresh_token(self):
        """Refresh the access token using the refresh token."""
        refresh_token = self.config.refresh_token
        if not refresh_token:
            raise ClientError(
                "No refresh token available. Run 'scrunch auth login' to re-authenticate."
            )
        raise ClientError("Token refresh not implemented. Run 'scrunch auth login'.")

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
    ) -> Dict:
        """Make an HTTP request to the Scrunch API with exponential retry."""
        url = f"{self.base_url}{endpoint}"

        if self._is_token_expired():
            try:
                self._refresh_token()
            except Exception:
                pass

        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None

        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    json=data,
                    params=params,
                )
                last_response = response

                if response.status_code == 401:
                    try:
                        self._refresh_token()
                        response = requests.request(
                            method=method,
                            url=url,
                            headers=self.headers,
                            json=data,
                            params=params,
                        )
                        last_response = response
                    except Exception as e:
                        raise ClientError(f"Authentication failed: {e}")

                if retry and self._is_retryable(response, None) and attempt < self.max_retries:
                    retry_after = self._get_retry_after(response)
                    delay = self._calculate_retry_delay(attempt, retry_after)
                    time.sleep(delay)
                    continue

                break

            except requests.exceptions.RequestException as e:
                last_exception = e
                if retry and self._is_retryable(None, e) and attempt < self.max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    time.sleep(delay)
                    continue
                break

        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed after {attempt + 1} attempts: {last_exception}")

        if last_response is None:
            raise ClientError("Request failed: no response received")

        if not last_response.ok:
            error_msg = self._extract_error_detail(last_response)
            raise ClientError(f"HTTP {last_response.status_code}: {error_msg}")

        if last_response.status_code == 204:
            return {}

        return last_response.json()

    def _extract_items(self, response: Any) -> list:
        """Extract items array from a CollectionResponse or raw list."""
        if isinstance(response, dict):
            return response.get("items", response.get("data", response.get("results", [])))
        if isinstance(response, list):
            return response
        return []

    # ==================== Brands ====================

    def list_brands(self, limit: int = 100) -> List[Brand]:
        """List all brands."""
        params: Dict[str, Any] = {"limit": limit}
        response = self._make_request("GET", "/brands", params=params)
        raw_items = self._extract_items(response)
        return [create_brand(item) for item in raw_items]

    def get_brand(self, brand_id: int) -> Brand:
        """Get a specific brand by ID."""
        response = self._make_request("GET", f"/brands/{brand_id}")
        if isinstance(response, dict) and "items" in response:
            return create_brand(response["items"][0])
        return create_brand(response)

    def create_brand(self, data: CreateBrand) -> Brand:
        """Create a new brand."""
        payload = data.model_dump(exclude_none=True)
        response = self._make_request("POST", "/brands", data=payload)
        return create_brand(response)

    def update_brand(self, brand_id: int, data: UpdateBrand) -> Brand:
        """Update an existing brand."""
        payload = data.model_dump(exclude_none=True)
        response = self._make_request("PATCH", f"/brands/{brand_id}", data=payload)
        return create_brand(response)

    def delete_brand(self, brand_id: int) -> dict:
        """Archive (delete) a brand."""
        return self._make_request("DELETE", f"/brands/{brand_id}")

    # ==================== Competitors ====================

    def list_competitors(self, brand_id: int, limit: int = 100) -> List[Competitor]:
        """List competitors for a brand."""
        params: Dict[str, Any] = {"limit": limit}
        response = self._make_request("GET", f"/brands/{brand_id}/competitors", params=params)
        raw_items = self._extract_items(response)
        return [create_competitor(item) for item in raw_items]

    def get_competitor(self, brand_id: int, competitor_id: int) -> Competitor:
        """Get a specific competitor."""
        response = self._make_request("GET", f"/brands/{brand_id}/competitors/{competitor_id}")
        return create_competitor(response)

    def create_competitor(self, brand_id: int, data: CreateCompetitor) -> Competitor:
        """Create a new competitor for a brand."""
        payload = data.model_dump(exclude_none=True)
        response = self._make_request("POST", f"/brands/{brand_id}/competitors", data=payload)
        return create_competitor(response)

    def update_competitor(self, brand_id: int, competitor_id: int, data: UpdateCompetitor) -> Competitor:
        """Update a competitor."""
        payload = data.model_dump(exclude_none=True)
        response = self._make_request("PUT", f"/brands/{brand_id}/competitors/{competitor_id}", data=payload)
        return create_competitor(response)

    def delete_competitor(self, brand_id: int, competitor_id: int) -> dict:
        """Archive (delete) a competitor."""
        return self._make_request("DELETE", f"/brands/{brand_id}/competitors/{competitor_id}")

    # ==================== Personas ====================

    def list_personas(self, brand_id: int, limit: int = 100) -> List[Persona]:
        """List personas for a brand."""
        params: Dict[str, Any] = {"limit": limit}
        response = self._make_request("GET", f"/brands/{brand_id}/personas", params=params)
        raw_items = self._extract_items(response)
        return [create_persona(item) for item in raw_items]

    def get_persona(self, brand_id: int, persona_id: int) -> Persona:
        """Get a specific persona."""
        response = self._make_request("GET", f"/brands/{brand_id}/personas/{persona_id}")
        return create_persona(response)

    def create_persona(self, brand_id: int, data: CreatePersona) -> Persona:
        """Create a new persona for a brand."""
        payload = data.model_dump(exclude_none=True)
        response = self._make_request("POST", f"/brands/{brand_id}/personas", data=payload)
        return create_persona(response)

    def update_persona(self, brand_id: int, persona_id: int, data: UpdatePersona) -> Persona:
        """Update a persona."""
        payload = data.model_dump(exclude_none=True)
        response = self._make_request("PUT", f"/brands/{brand_id}/personas/{persona_id}", data=payload)
        return create_persona(response)

    def delete_persona(self, brand_id: int, persona_id: int) -> dict:
        """Archive (delete) a persona."""
        return self._make_request("DELETE", f"/brands/{brand_id}/personas/{persona_id}")

    # ==================== Prompts ====================

    def list_prompts(self, brand_id: int, limit: int = 100, offset: int = 0) -> List[Prompt]:
        """List prompts for a brand (paginated)."""
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        response = self._make_request("GET", f"/{brand_id}/prompts", params=params)
        raw_items = self._extract_items(response)
        return [create_prompt(item) for item in raw_items]

    def get_prompt(self, brand_id: int, prompt_id: int) -> Prompt:
        """Get a specific prompt."""
        response = self._make_request("GET", f"/{brand_id}/prompts/{prompt_id}")
        return create_prompt(response)

    def create_prompt(self, brand_id: int, data: CreatePrompt) -> Prompt:
        """Create a new prompt for a brand."""
        payload = data.model_dump(exclude_none=True)
        response = self._make_request("POST", f"/{brand_id}/prompts", data=payload)
        return create_prompt(response)

    def delete_prompt(self, brand_id: int, prompt_id: int) -> dict:
        """Archive (delete) a prompt."""
        return self._make_request("DELETE", f"/{brand_id}/prompts/{prompt_id}")

    # ==================== Query ====================

    def query_metrics(
        self,
        brand_id: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
        fields: Optional[str] = None,
    ) -> List[QueryResult]:
        """Query aggregated metrics for a brand."""
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if fields:
            params["fields"] = fields

        response = self._make_request("GET", f"/{brand_id}/query", params=params)
        raw_items = self._extract_items(response)
        return [create_query_result(item) for item in raw_items]

    # ==================== Responses ====================

    def list_responses(
        self,
        brand_id: int,
        limit: int = 100,
        offset: int = 0,
        platform: Optional[str] = None,
        prompt_id: Optional[int] = None,
        persona_id: Optional[int] = None,
        stage: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        has_shopping_data: Optional[bool] = None,
    ) -> List[ResponseListing]:
        """List AI responses for a brand with optional filters."""
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if platform:
            params["platform"] = platform
        if prompt_id is not None:
            params["prompt_id"] = prompt_id
        if persona_id is not None:
            params["persona_id"] = persona_id
        if stage:
            params["stage"] = stage
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if has_shopping_data is not None:
            params["has_shopping_data"] = has_shopping_data

        response = self._make_request("GET", f"/{brand_id}/responses", params=params)
        raw_items = self._extract_items(response)
        return [create_response_listing(item) for item in raw_items]

    # ==================== Page Audits ====================

    def list_page_audits(
        self,
        brand_id: int,
        limit: int = 100,
        status: Optional[str] = None,
        url: Optional[str] = None,
    ) -> List[PageAuditRecord]:
        """List page audits for a brand."""
        params: Dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        if url:
            params["url"] = url

        response = self._make_request("GET", f"/{brand_id}/page-audits", params=params)
        raw_items = self._extract_items(response)
        return [create_page_audit(item) for item in raw_items]

    def get_page_audit(self, brand_id: int, page_audit_id: int) -> PageAuditRecord:
        """Get a specific page audit."""
        response = self._make_request("GET", f"/{brand_id}/page-audits/{page_audit_id}")
        return create_page_audit(response)

    def create_page_audit(self, brand_id: int, data: CreatePageAudit) -> PageAuditRecord:
        """Create a new page audit for a brand."""
        payload = data.model_dump(exclude_none=True)
        response = self._make_request("POST", f"/{brand_id}/page-audits", data=payload)
        return create_page_audit(response)

    # ==================== Agent Traffic ====================

    def get_agent_traffic(
        self,
        brand_id: int,
        site_id: int,
        start_date: str,
        end_date: str,
        limit: int = 100,
        offset: int = 0,
        fields: Optional[str] = None,
        time_bucket: Optional[str] = None,
        path: Optional[str] = None,
    ) -> AgentTrafficResponse:
        """Get agent traffic data for a brand's site."""
        params: Dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
            "offset": offset,
        }
        if fields:
            params["fields"] = fields
        if time_bucket:
            params["time_bucket"] = time_bucket
        if path:
            params["path"] = path

        response = self._make_request(
            "GET", f"/{brand_id}/sites/{site_id}/agent-traffic", params=params
        )
        return AgentTrafficResponse(**response)


# Module-level client instance - singleton pattern
_client: Optional[ScrunchClient] = None


def get_client() -> ScrunchClient:
    """Get or create the global Scrunch client instance."""
    global _client
    if _client is None:
        _client = ScrunchClient()
    return _client
