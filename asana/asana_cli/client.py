"""Asana API client."""
from typing import Dict, List, Optional, Any
import random
import time
import requests

from .config import get_config

# Retry configuration
MAX_RETRIES = 5
BASE_DELAY = 1.0  # seconds
MAX_DELAY = 60.0  # seconds
JITTER = 0.5  # max random jitter in seconds
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ClientError(Exception):
    """Custom exception for Asana API errors."""
    pass


def _normalize_ids(value: Any) -> Any:
    """Expose Asana gid values through the standard CLI id field."""
    if isinstance(value, list):
        return [_normalize_ids(item) for item in value]
    if isinstance(value, dict):
        normalized = {key: _normalize_ids(item) for key, item in value.items()}
        if "gid" in normalized:
            return {"id": normalized["gid"], **normalized}
        return normalized
    return value


class AsanaClient:
    """Client for interacting with Asana API."""

    def __init__(self, config=None):
        """Initialize Asana client from configuration."""
        self.config = config or get_config()

        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Set ASANA_PAT in .env file."
            )

        self.base_url = self.config.base_url
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.config.pat}",
        }
        # Retry configuration
        self.max_retries = MAX_RETRIES
        self.base_delay = BASE_DELAY
        self.max_delay = MAX_DELAY
        self.jitter = JITTER

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[int] = None) -> float:
        """
        Calculate delay before next retry using exponential backoff.

        Args:
            attempt: Current attempt number (0-indexed)
            retry_after: Optional Retry-After header value in seconds

        Returns:
            Delay in seconds before next retry
        """
        if retry_after is not None:
            return min(float(retry_after), self.max_delay)

        # Exponential backoff: base_delay * 2^attempt
        delay = self.base_delay * (2 ** attempt)
        # Add jitter to prevent thundering herd
        delay += random.uniform(0, self.jitter)
        # Cap at max delay
        return min(delay, self.max_delay)

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        paginate: bool = False,
        retry: bool = True,
    ) -> Any:
        """
        Make an HTTP request to the Asana API with retry support.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: API endpoint path (e.g., "/users/me")
            data: Request body data (will be wrapped in {"data": ...} for POST/PUT)
            params: Query parameters
            paginate: If True, automatically fetch all pages for list endpoints
            retry: If True, retry on transient errors (default True)

        Returns:
            Response JSON data (unwrapped from {"data": ...})

        Raises:
            ClientError: If request fails after all retries
        """
        if paginate and method == "GET":
            return self._make_paginated_request(endpoint, params)

        url = f"{self.base_url}{endpoint}"

        # Wrap POST/PUT data in {"data": ...} as Asana expects
        json_data = None
        if data and method in ("POST", "PUT"):
            json_data = {"data": data}
        elif data:
            json_data = data

        max_attempts = self.max_retries if retry else 1
        last_error = None

        for attempt in range(max_attempts):
            try:
                # Make the request
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    json=json_data,
                    params=params,
                )

                # Check for retryable status codes
                if response.status_code in RETRYABLE_STATUS_CODES and retry and attempt < max_attempts - 1:
                    # Get Retry-After header if present
                    retry_after = None
                    if "Retry-After" in response.headers:
                        try:
                            retry_after = int(response.headers["Retry-After"])
                        except ValueError:
                            pass
                    delay = self._calculate_retry_delay(attempt, retry_after)
                    time.sleep(delay)
                    continue

                if not response.ok:
                    # Try to get error details from response
                    try:
                        error_data = response.json()
                        errors = error_data.get("errors", [])
                        if errors:
                            error_msg = errors[0].get("message", response.text)
                        else:
                            error_msg = error_data.get("message") or error_data.get("error") or response.text
                    except Exception:
                        error_msg = response.text
                    raise ClientError(f"API request failed ({response.status_code}): {error_msg}")

                # Handle empty response (204 No Content)
                if response.status_code == 204:
                    return {}

                response_json = response.json()

                # Unwrap {"data": ...} envelope
                if "data" in response_json:
                    return _normalize_ids(response_json["data"])

                return _normalize_ids(response_json)

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                last_error = e
                if retry and attempt < max_attempts - 1:
                    delay = self._calculate_retry_delay(attempt)
                    time.sleep(delay)
                    continue
                raise ClientError(f"Connection error after {attempt + 1} attempts: {e}")

        # Should not reach here, but just in case
        raise ClientError(f"Request failed after {max_attempts} attempts: {last_error}")

    def _make_paginated_request(
        self,
        endpoint: str,
        params: Optional[Dict] = None,
        page_size: int = 100,
        total_limit: Optional[int] = None,
    ) -> List[Dict]:
        """
        Make paginated GET requests with retry support, stopping at total_limit.

        Args:
            endpoint: API endpoint path
            params: Query parameters
            page_size: Number of items per page (max 100)
            total_limit: Maximum total items to fetch (None = fetch all)

        Returns:
            Combined list of items up to total_limit
        """
        all_items = []
        params = dict(params) if params else {}
        params["limit"] = page_size

        while True:
            url = f"{self.base_url}{endpoint}"

            # Retry loop for this page
            last_error = None
            for attempt in range(self.max_retries):
                try:
                    response = requests.request(
                        method="GET",
                        url=url,
                        headers=self.headers,
                        params=params,
                    )

                    # Check for retryable status codes
                    if response.status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries - 1:
                        retry_after = None
                        if "Retry-After" in response.headers:
                            try:
                                retry_after = int(response.headers["Retry-After"])
                            except ValueError:
                                pass
                        delay = self._calculate_retry_delay(attempt, retry_after)
                        time.sleep(delay)
                        continue

                    break  # Success or non-retryable error

                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                    last_error = e
                    if attempt < self.max_retries - 1:
                        delay = self._calculate_retry_delay(attempt)
                        time.sleep(delay)
                        continue
                    raise ClientError(f"Connection error after {attempt + 1} attempts: {e}")
            else:
                raise ClientError(f"Request failed after {self.max_retries} attempts: {last_error}")

            if not response.ok:
                try:
                    error_data = response.json()
                    errors = error_data.get("errors", [])
                    if errors:
                        error_msg = errors[0].get("message", response.text)
                    else:
                        error_msg = error_data.get("message") or error_data.get("error") or response.text
                except Exception:
                    error_msg = response.text
                raise ClientError(f"API request failed ({response.status_code}): {error_msg}")

            response_json = response.json()

            # Get data from this page
            page_data = response_json.get("data", [])
            if isinstance(page_data, list):
                all_items.extend(page_data)
            else:
                # Single item response, return as-is
                return page_data

            # Check if we've reached the total limit
            if total_limit and len(all_items) >= total_limit:
                return _normalize_ids(all_items[:total_limit])

            # Check for next page
            next_page = response_json.get("next_page")
            if not next_page:
                break

            # Use offset for next request
            params["offset"] = next_page.get("offset")

        return _normalize_ids(all_items)

    # ==================== Workspaces ====================

    def list_workspaces(self, limit: Optional[int] = None) -> List[Dict]:
        """List all workspaces the user has access to."""
        return self._make_paginated_request("/workspaces", total_limit=limit)

    def get_workspace(self, workspace_id: str) -> Dict:
        """Get workspace details."""
        return self._make_request("GET", f"/workspaces/{workspace_id}")

    # ==================== Projects ====================

    def list_projects(self, workspace_id: Optional[str] = None, limit: Optional[int] = None) -> List[Dict]:
        """List projects in workspace."""
        params = {}
        if workspace_id:
            params["workspace"] = workspace_id
        elif self.config.workspace_id:
            params["workspace"] = self.config.workspace_id

        return self._make_paginated_request("/projects", params=params, total_limit=limit)

    def get_project(self, project_id: str) -> Dict:
        """Get project details."""
        return self._make_request("GET", f"/projects/{project_id}")

    # ==================== Tasks ====================

    def list_tasks(self, project_id: Optional[str] = None,
                   assignee: Optional[str] = None,
                   workspace_id: Optional[str] = None,
                   limit: Optional[int] = None) -> List[Dict]:
        """List tasks. Requires either project_id, assignee, or workspace_id."""
        params = {
            "opt_fields": "name,completed,due_on,created_at,assignee.name"
        }

        if project_id:
            params["project"] = project_id
        elif assignee:
            params["assignee"] = assignee
            if workspace_id:
                params["workspace"] = workspace_id
        elif workspace_id:
            params["assignee"] = "me"
            params["workspace"] = workspace_id
        elif self.config.workspace_id:
            params["assignee"] = "me"
            params["workspace"] = self.config.workspace_id
        else:
            raise ClientError("Must provide project_id, assignee, or workspace_id")

        # Use pagination with total_limit to stop fetching at the limit
        return _normalize_ids(self._make_paginated_request("/tasks", params=params, total_limit=limit))

    def get_task(self, task_id: str) -> Dict:
        """Get task details including custom fields."""
        params = {
            "opt_fields": "name,notes,assignee,assignee.name,projects,projects.gid,projects.name,custom_fields,custom_fields.gid,custom_fields.name,custom_fields.enum_value,custom_fields.multi_enum_values,custom_fields.text_value,custom_fields.people_value,custom_fields.display_value,completed,due_on,created_at"
        }
        return self._make_request("GET", f"/tasks/{task_id}", params=params)

    def create_task(self, name: str, workspace_id: Optional[str] = None,
                   projects: Optional[List[str]] = None,
                   assignee: Optional[str] = None,
                   notes: Optional[str] = None,
                   due_on: Optional[str] = None,
                   custom_fields: Optional[Dict[str, Any]] = None) -> Dict:
        """Create a new task."""
        data = {"name": name}

        if workspace_id:
            data["workspace"] = workspace_id
        elif self.config.workspace_id:
            data["workspace"] = self.config.workspace_id

        if projects:
            data["projects"] = projects
        if assignee:
            data["assignee"] = assignee
        if notes:
            data["notes"] = notes
        if due_on:
            data["due_on"] = due_on
        if custom_fields:
            data["custom_fields"] = custom_fields

        return self._make_request("POST", "/tasks", data=data)

    def update_task(self, task_id: str, **kwargs) -> Dict:
        """Update a task with any supported fields."""
        return self._make_request("PUT", f"/tasks/{task_id}", data=kwargs)

    def complete_task(self, task_id: str) -> Dict:
        """Mark task as complete."""
        return self._make_request("PUT", f"/tasks/{task_id}", data={"completed": True})

    def delete_task(self, task_id: str) -> Dict:
        """Delete a task."""
        return self._make_request("DELETE", f"/tasks/{task_id}")

    def search_tasks(self, query: str,
                     project_id: Optional[str] = None,
                     workspace_id: Optional[str] = None,
                     limit: Optional[int] = None) -> List[Dict]:
        """
        Search tasks with wildcard query matching any field.

        Query supports wildcards: * (any chars), ? (single char)
        Searches across: name, notes, assignee name
        """
        import fnmatch

        # Get tasks to search through
        tasks = self.list_tasks(
            project_id=project_id,
            workspace_id=workspace_id
        )

        # Normalize query for case-insensitive matching
        query_lower = query.lower()

        # Filter tasks matching query
        def matches(task: Dict) -> bool:
            # Fields to search
            searchable = [
                task.get("name", ""),
                task.get("notes", ""),
                (task.get("assignee") or {}).get("name", ""),
            ]
            # Check if query matches any field
            for field in searchable:
                if field and fnmatch.fnmatch(field.lower(), query_lower):
                    return True
            return False

        results = [t for t in tasks if matches(t)]

        if limit:
            return results[:limit]
        return results

    # ==================== Custom Fields ====================

    def list_custom_fields(self, project_id: str, limit: Optional[int] = None) -> List[Dict]:
        """List custom fields for a project with enum options."""
        params = {
            "opt_fields": "custom_field,custom_field.name,custom_field.enum_options,custom_field.type,custom_field.description"
        }
        return self._make_paginated_request(f"/projects/{project_id}/custom_field_settings", params=params, total_limit=limit)

    def get_custom_field(self, field_id: str) -> Dict:
        """Get custom field details including enum options."""
        params = {
            "opt_fields": "name,enum_options,type,description,precision,resource_subtype"
        }
        return self._make_request("GET", f"/custom_fields/{field_id}", params=params)

    # ==================== Users ====================

    def list_users(self, workspace_id: Optional[str] = None, limit: Optional[int] = None) -> List[Dict]:
        """List users in workspace."""
        params = {}
        if workspace_id:
            params["workspace"] = workspace_id
        elif self.config.workspace_id:
            params["workspace"] = self.config.workspace_id

        return self._make_paginated_request("/users", params=params, total_limit=limit)

    def get_user(self, user_id: str = "me") -> Dict:
        """Get user details. Defaults to current user."""
        return self._make_request("GET", f"/users/{user_id}")

    # ==================== Sections ====================

    def list_sections(self, project_id: str, limit: Optional[int] = None) -> List[Dict]:
        """List sections in a project."""
        return self._make_paginated_request(f"/projects/{project_id}/sections", total_limit=limit)

    def get_section(self, section_id: str) -> Dict:
        """Get section details."""
        return self._make_request("GET", f"/sections/{section_id}")


# Module-level client instance - singleton pattern
_client: Optional[AsanaClient] = None


def get_client() -> AsanaClient:
    """Get or create the global Asana client instance."""
    global _client
    if _client is None:
        _client = AsanaClient()
    return _client
