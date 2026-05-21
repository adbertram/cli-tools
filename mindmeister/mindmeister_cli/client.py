"""MindMeister API client with automatic token management and exponential retry.

Uses the v1 API with OAuth2 authentication (Personal Access Token).
API Endpoint: https://www.mindmeister.com/services/rest/oauth2
"""
from typing import Dict, List, Optional
import random
import time
import requests

from cli_tools_shared.filters import FilterValidationError, apply_filters, validate_filters

from .config import get_config
from .models import Map, MapDetail, ExportUrls, create_map, create_map_detail


# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_JITTER = 0.1  # 10% jitter

# HTTP status codes that trigger retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ClientError(Exception):
    """Custom exception for MindMeister API errors."""
    pass


class MindmeisterClient:
    """Client for interacting with MindMeister API v1 with OAuth2 authentication."""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
        config=None,
    ):
        """Initialize MindMeister client from configuration."""
        self.config = config or get_config()

        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Set MINDMEISTER_ACCESS_TOKEN in .env file."
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
            "Accept": "application/json",
        }
        # Use Bearer token for OAuth2 authentication
        if self.config.access_token:
            self.headers["Authorization"] = f"Bearer {self.config.access_token}"
        elif self.config.api_key:
            self.headers["Authorization"] = f"Bearer {self.config.api_key}"

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

    def _make_request(
        self,
        method: str,
        params: Optional[Dict] = None,
        retry: bool = True,
    ) -> Dict:
        """Make an API request to MindMeister v1 API.

        The v1 API uses RPC-style calls where 'method' is passed as a query parameter.

        Args:
            method: API method name (e.g., "mm.maps.getList")
            params: Additional query parameters
            retry: Whether to retry on transient errors

        Returns:
            Response JSON data (the 'rsp' object)

        Raises:
            ClientError: If request fails
        """
        request_params = {"method": method}
        if params:
            request_params.update(params)

        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                response = requests.get(
                    self.base_url,
                    headers=self.headers,
                    params=request_params,
                )
                last_response = response

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
            raise ClientError(f"API request failed ({last_response.status_code}): {last_response.text}")

        # Parse JSON response
        data = last_response.json()
        rsp = data.get("rsp", data)

        # Check for API-level errors
        if rsp.get("stat") == "fail":
            err = rsp.get("err", {})
            code = err.get("code", "unknown")
            msg = err.get("msg", "Unknown error")
            raise ClientError(f"API Error {code}: {msg}")

        return rsp

    # ==================== Map Methods ====================

    def list_maps(self, limit: int = 100, filters: Optional[List[str]] = None) -> List[Map]:
        """List all mind maps.

        Args:
            limit: Maximum number of maps to return (API-level)
            filters: Optional filter strings

        Returns:
            List of Map models
        """
        params = {"perpage": limit}

        if filters:
            try:
                validate_filters(filters)
            except FilterValidationError as e:
                raise ClientError(f"Invalid filter: {e}")

        rsp = self._make_request("mm.maps.getList", params)

        # Extract maps from nested structure
        maps_data = rsp.get("maps", {})
        raw_maps = maps_data.get("map", [])

        if isinstance(raw_maps, dict):
            raw_maps = [raw_maps]

        if filters:
            raw_maps = apply_filters(raw_maps, filters)
        raw_maps = raw_maps[:limit]
        return [create_map(m) for m in raw_maps]

    def get_map(self, map_id: str) -> MapDetail:
        """Get a specific map with full structure including ideas/nodes.

        Args:
            map_id: The map ID

        Returns:
            MapDetail model with full map structure
        """
        params = {"map_id": map_id}
        rsp = self._make_request("mm.maps.getMap", params)
        return create_map_detail(rsp)

    def create_map(self, title: str) -> Map:
        """Create a new empty mind map.

        Args:
            title: The map title

        Returns:
            Created Map model
        """
        params = {"title": title}
        rsp = self._make_request("mm.maps.add", params)
        map_data = rsp.get("map", {})
        return create_map(map_data)

    def update_map(self, map_id: str, title: Optional[str] = None, description: Optional[str] = None) -> Map:
        """Update map metadata.

        Args:
            map_id: The map ID
            title: New title (optional)
            description: New description (optional)

        Returns:
            Updated Map model
        """
        params = {"map_id": map_id}
        if title:
            params["title"] = title
        if description:
            params["description"] = description

        rsp = self._make_request("mm.maps.setMetaData", params)
        map_data = rsp.get("map", {})
        return create_map(map_data)

    def duplicate_map(self, map_id: str) -> Map:
        """Duplicate an existing map.

        Args:
            map_id: The map ID to duplicate

        Returns:
            New Map model (the duplicate)
        """
        params = {"map_id": map_id}
        rsp = self._make_request("mm.maps.duplicate", params)
        map_data = rsp.get("map", {})
        return create_map(map_data)

    def delete_map(self, map_id: str) -> bool:
        """Delete a map.

        Args:
            map_id: The map ID to delete

        Returns:
            True if successful
        """
        params = {"map_id": map_id}
        self._make_request("mm.maps.delete", params)
        return True

    def export_map(self, map_id: str) -> Dict:
        """Get export URLs for a map.

        Args:
            map_id: The map ID

        Returns:
            Dict with export URLs for various formats
        """
        params = {"map_id": map_id}
        rsp = self._make_request("mm.maps.export", params)
        return rsp

    def import_map(self, file_content: bytes, filename: str = "import.mm") -> Map:
        """Import a mind map from file content.

        Args:
            file_content: The file content (FreeMind XML, etc.)
            filename: Filename with extension (.mm, .mmap, .xmind)

        Returns:
            Created Map model
        """
        # Import requires multipart file upload
        files = {
            "file": (filename, file_content, "application/octet-stream"),
        }

        # Build the URL with method parameter
        url = f"{self.base_url}?method=mm.maps.import"

        # Use only Authorization header for file uploads
        headers = {"Authorization": self.headers.get("Authorization", "")}

        response = requests.post(url, headers=headers, files=files)

        if not response.ok:
            raise ClientError(f"Import failed ({response.status_code}): {response.text}")

        data = response.json()
        rsp = data.get("rsp", data)

        if rsp.get("stat") == "fail":
            err = rsp.get("err", {})
            code = err.get("code", "unknown")
            msg = err.get("msg", "Unknown error")
            raise ClientError(f"API Error {code}: {msg}")

        map_data = rsp.get("map", {})
        return create_map(map_data)

    def import_map_from_ideas(
        self,
        title: str,
        ideas: List[Dict],
    ) -> Map:
        """Create a new map by importing ideas as FreeMind format.

        This is a workaround since the API doesn't support adding ideas directly.
        Creates a new map with the specified structure.

        Args:
            title: Map title (root node text)
            ideas: List of idea dicts with 'id', 'title', 'parent' keys

        Returns:
            Created Map model
        """
        from .freemind import ideas_to_freemind_xml

        xml_content = ideas_to_freemind_xml(ideas, title=title)
        return self.import_map(xml_content.encode("utf-8"), f"{title}.mm")

    def create_map_with_children(
        self,
        title: str,
        children: List[str],
    ) -> Map:
        """Create a new map with root node and first-level children.

        Args:
            title: Root node text (also used as map title)
            children: List of first-level child node texts

        Returns:
            Created Map model
        """
        from .freemind import create_simple_mindmap

        xml_content = create_simple_mindmap(title, children)
        return self.import_map(xml_content.encode("utf-8"), f"{title}.mm")

    def create_map_from_structure(
        self,
        structure: Dict,
    ) -> Map:
        """Create a new map from a nested dictionary structure.

        Args:
            structure: Nested dict where keys are node titles.
                Example: {"Root": {"Branch1": ["Leaf1", "Leaf2"], "Branch2": "Leaf3"}}

        Returns:
            Created Map model
        """
        from .freemind import create_hierarchical_mindmap

        xml_content = create_hierarchical_mindmap(structure)
        # Get title from first key
        title = next(iter(structure.keys()), "Mind Map")
        return self.import_map(xml_content.encode("utf-8"), f"{title}.mm")

    def create_annotated_map(
        self,
        nodes: List[Dict],
    ) -> Map:
        """Create a new map with notes/annotations on nodes.

        Args:
            nodes: List of node dicts with 'title', optional 'note', and optional 'children'.
                Example: [{"title": "Root", "note": "Description", "children": [...]}]

        Returns:
            Created Map model
        """
        from .freemind import create_annotated_mindmap

        xml_content = create_annotated_mindmap(nodes)
        # Get title from first node
        title = nodes[0].get("title", "Mind Map") if nodes else "Mind Map"
        return self.import_map(xml_content.encode("utf-8"), f"{title}.mm")

    # ==================== Ideas Methods ====================

    def get_ideas(self, map_id: str) -> List[Dict]:
        """Get all ideas/nodes from a map.

        Args:
            map_id: The map ID

        Returns:
            List of idea dicts
        """
        map_detail = self.get_map(map_id)
        return [idea.model_dump() for idea in map_detail.ideas]

    def toggle_idea_closed(self, map_id: str, idea_id: str, closed: Optional[bool] = None) -> Dict:
        """Toggle or set the open/closed (folded) status of a branch.

        Args:
            map_id: The map ID
            idea_id: The idea/node ID to toggle
            closed: If provided, set to this value; otherwise toggle

        Returns:
            Response dict
        """
        params = {"map_id": map_id, "idea_id": idea_id}
        if closed is not None:
            params["closed"] = "1" if closed else "0"

        rsp = self._make_request("mm.ideas.toggleClosed", params)
        return rsp

    # ==================== Auth Methods ====================

    def check_auth(self) -> bool:
        """Check if authentication is valid by making a simple API call.

        Returns:
            True if authenticated
        """
        try:
            # Use list_maps with limit 1 to verify auth works
            self.list_maps(limit=1)
            return True
        except ClientError:
            return False


# Module-level client instance - singleton pattern
_client: Optional[MindmeisterClient] = None


def get_client() -> MindmeisterClient:
    """Get or create the global MindMeister client instance."""
    global _client
    if _client is None:
        _client = MindmeisterClient()
    return _client
