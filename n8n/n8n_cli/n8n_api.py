"""n8n REST API client for workflow and execution management.

Used by the test command to create temporary workflows, trigger them via webhook,
poll for execution results, and clean up.
"""
import os
import random
import time
import requests
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote


GLOBAL_ERROR_HANDLER_ID = "F79g2nlj6f1glf8u"


class N8nApiError(Exception):
    """Custom exception for n8n API errors."""
    pass


class N8nApiClient:
    """Client for n8n REST API operations."""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        """Initialize the API client.

        Args:
            base_url: n8n API base URL (from config or direct)
            api_key: n8n API key (from config or direct)
        """
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""

        if not self.base_url:
            raise N8nApiError("BASE_URL not configured. Run 'n8n auth login' to configure.")
        if not self.api_key:
            raise N8nApiError("API_KEY not configured. Run 'n8n auth login' to configure.")

        self.session = requests.Session()
        self.session.headers.update({
            "X-N8N-API-KEY": self.api_key,
            "Content-Type": "application/json",
        })

    def _request(self, method: str, endpoint: str, _retries: int = 3, **kwargs) -> Any:
        """Make an API request with exponential retry and jitter.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            endpoint: API endpoint (e.g., /workflows)
            _retries: Max retry attempts for transient failures
            **kwargs: Additional arguments to pass to requests

        Returns:
            JSON response data

        Raises:
            N8nApiError: If the request fails after all retries
        """
        url = f"{self.base_url}{endpoint}"
        last_error = None

        for attempt in range(_retries + 1):
            try:
                response = self.session.request(method, url, **kwargs)
                response.raise_for_status()

                # Handle 204 No Content
                if response.status_code == 204:
                    return None

                return response.json()
            except requests.exceptions.HTTPError as e:
                status = getattr(e.response, 'status_code', None)
                # Retry on 429 (rate limit) and 5xx (server errors)
                if status and (status == 429 or status >= 500) and attempt < _retries:
                    delay = (2 ** attempt) + random.uniform(0, 1)
                    time.sleep(delay)
                    last_error = e
                    continue
                error_msg = str(e)
                try:
                    error_data = response.json()
                    if "message" in error_data:
                        error_msg = error_data["message"]
                except Exception:
                    pass
                raise N8nApiError(f"API request failed: {error_msg}")
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if attempt < _retries:
                    delay = (2 ** attempt) + random.uniform(0, 1)
                    time.sleep(delay)
                    last_error = e
                    continue
                raise N8nApiError(f"Request failed: {e}")
            except requests.exceptions.RequestException as e:
                raise N8nApiError(f"Request failed: {e}")

        raise N8nApiError(f"Request failed after {_retries} retries: {last_error}")

    def wait_for_ready(self, timeout: int = 60, poll_interval: float = 2.0) -> bool:
        """Poll n8n until the server is fully ready (healthz + REST API).

        Checks /healthz first, then verifies the REST API is responding.
        n8n's healthz can return 200 before REST routes are initialized.

        Args:
            timeout: Maximum seconds to wait
            poll_interval: Seconds between polls

        Returns:
            True if server is ready

        Raises:
            N8nApiError: If server doesn't become ready within timeout
        """
        server_url = self.base_url.replace("/api/v1", "")
        health_url = f"{server_url}/healthz"
        rest_url = f"{server_url}/rest/settings"

        deadline = time.time() + timeout
        last_error = None
        healthz_ok = False

        while time.time() < deadline:
            try:
                if not healthz_ok:
                    resp = requests.get(health_url, timeout=5)
                    if resp.status_code == 200:
                        healthz_ok = True
                    else:
                        last_error = f"healthz HTTP {resp.status_code}"
                        time.sleep(poll_interval)
                        continue

                # healthz passed — now verify REST API is up
                resp = requests.get(rest_url, timeout=5)
                if resp.status_code in (200, 401):
                    # 200 or 401 both mean REST routes are loaded
                    return True
                last_error = f"REST API HTTP {resp.status_code}"
            except requests.exceptions.RequestException as e:
                last_error = str(e)

            time.sleep(poll_interval)

        raise N8nApiError(f"n8n not ready after {timeout}s (last error: {last_error})")

    def create_workflow(
        self,
        name: str,
        nodes: List[Dict],
        connections: Dict,
        error_workflow: Optional[str] = GLOBAL_ERROR_HANDLER_ID,
    ) -> Dict:
        """Create a new workflow.

        Args:
            name: Workflow name
            nodes: List of node definitions
            connections: Node connections
            error_workflow: Workflow ID to run on error (default: global error handler).
                           Pass None to skip.

        Returns:
            Created workflow object with id
        """
        settings: Dict[str, Any] = {
            "saveManualExecutions": True,
            "saveDataSuccessExecution": "all",
            "saveDataErrorExecution": "all",
        }
        if error_workflow:
            settings["errorWorkflow"] = error_workflow
        payload = {
            "name": name,
            "nodes": nodes,
            "connections": connections,
            "settings": settings,
        }
        return self._request("POST", "/workflows", json=payload)

    def delete_workflow(self, workflow_id: str) -> Dict:
        """Delete a workflow.

        Args:
            workflow_id: ID of the workflow to delete

        Returns:
            Deleted workflow object
        """
        return self._request("DELETE", f"/workflows/{workflow_id}")

    def get_executions(
        self,
        workflow_id: Optional[str] = None,
        include_data: bool = True,
        limit: int = 10
    ) -> List[Dict]:
        """Get workflow executions.

        Args:
            workflow_id: Filter by workflow ID
            include_data: Include detailed execution data
            limit: Maximum number of executions to return

        Returns:
            List of execution objects
        """
        params = {"limit": limit}
        if workflow_id:
            params["workflowId"] = workflow_id
        if include_data:
            params["includeData"] = "true"

        response = self._request("GET", "/executions", params=params)
        return response.get("data", [])

    def activate_workflow(self, workflow_id: str) -> Dict:
        """Activate a workflow.

        Args:
            workflow_id: ID of the workflow to activate

        Returns:
            Workflow object
        """
        return self._request("POST", f"/workflows/{workflow_id}/activate")

    def deactivate_workflow(self, workflow_id: str) -> Dict:
        """Deactivate a workflow.

        Args:
            workflow_id: ID of the workflow to deactivate

        Returns:
            Workflow object
        """
        return self._request("POST", f"/workflows/{workflow_id}/deactivate")

    def execute_workflow(self, workflow_id: str) -> Dict:
        """Execute a workflow via the internal REST API.

        Fetches the full workflow definition, finds a suitable trigger node,
        and posts to the internal /rest/workflows/:id/run endpoint.

        Args:
            workflow_id: ID of the workflow to execute

        Returns:
            Dict with executionId or waitingForWebhook status
        """
        workflow = self.get_workflow(workflow_id)

        # Find a trigger node to start from (prefer Manual Trigger)
        trigger_name = None
        for node in workflow.get("nodes", []):
            node_type = node.get("type", "")
            if node_type == "n8n-nodes-base.manualTrigger":
                trigger_name = node["name"]
                break
            if "trigger" in node_type.lower() and not trigger_name:
                trigger_name = node["name"]

        payload = {"workflowData": workflow}
        if trigger_name:
            payload["triggerToStartFrom"] = {"name": trigger_name}

        return self._rest_request(
            "POST",
            f"/rest/workflows/{workflow_id}/run",
            json=payload,
        )

    def trigger_webhook(self, webhook_path: str, data: Optional[Dict] = None) -> Any:
        """Trigger a webhook on the n8n server (production path).

        Args:
            webhook_path: The webhook path (e.g., "test-abc123")
            data: Optional JSON data to send

        Returns:
            Webhook response
        """
        # Base URL is .../api/v1, strip to get server root
        server_url = self.base_url.replace("/api/v1", "")
        url = f"{server_url}/webhook/{webhook_path}"
        try:
            response = requests.post(url, json=data or {}, timeout=300)
            response.raise_for_status()
            try:
                return response.json()
            except ValueError:
                return {"text": response.text}
        except requests.exceptions.RequestException as e:
            raise N8nApiError(f"Webhook trigger failed: {e}")

    def _get_server_url(self) -> str:
        """Get the n8n server root URL (without /api/v1)."""
        return self.base_url.replace("/api/v1", "")

    def _get_session_cookie(self) -> str:
        """Authenticate via internal REST API and return session cookie.

        Returns:
            Session cookie string (e.g., "n8n-auth=...")

        Raises:
            N8nApiError: If login fails or credentials not configured
        """
        email = os.environ.get("EMAIL", "")
        password = os.environ.get("PASSWORD", "")
        if not email or not password:
            raise N8nApiError("EMAIL and PASSWORD required in .env for session-based operations")

        server_url = self._get_server_url()
        try:
            resp = requests.post(
                f"{server_url}/rest/login",
                json={"emailOrLdapLoginId": email, "password": password},
                timeout=30,
            )
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise N8nApiError(f"Login failed: {e}")

        cookie = resp.cookies.get("n8n-auth")
        if not cookie:
            raise N8nApiError("No session cookie returned from login")
        return f"n8n-auth={cookie}"

    def _rest_request(self, method: str, path: str, **kwargs) -> Any:
        """Make a session-authenticated request to the internal REST API.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            path: REST API path (e.g., /rest/projects)
            **kwargs: Additional arguments to pass to requests

        Returns:
            JSON response data

        Raises:
            N8nApiError: If the request fails
        """
        server_url = self._get_server_url()
        cookie = self._get_session_cookie()
        headers = kwargs.pop("headers", {})
        headers["cookie"] = cookie
        headers.setdefault("Content-Type", "application/json")

        try:
            resp = requests.request(
                method,
                f"{server_url}{path}",
                headers=headers,
                timeout=kwargs.pop("timeout", 30),
                **kwargs,
            )
            resp.raise_for_status()
            if resp.status_code == 204:
                return None
            return resp.json()
        except requests.exceptions.RequestException as e:
            raise N8nApiError(f"REST request failed: {e}")

    def _get_project_id(self) -> str:
        """Get the default project ID from the n8n server.

        Returns:
            Project ID string

        Raises:
            N8nApiError: If no projects found
        """
        if not hasattr(self, "_project_id"):
            data = self._rest_request("GET", "/rest/projects")
            projects = data if isinstance(data, list) else data.get("data", [])
            if not projects:
                raise N8nApiError("No projects found on the n8n server")
            self._project_id = projects[0]["id"]
        return self._project_id

    def list_data_tables(self) -> List[Dict]:
        """List all data tables in the default project.

        Returns:
            List of data table dicts
        """
        pid = self._get_project_id()
        resp = self._rest_request("GET", f"/rest/projects/{pid}/data-tables")
        data = resp.get("data", resp) if isinstance(resp, dict) else resp
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data if isinstance(data, list) else []

    def create_data_table(self, name: str, columns: List[Dict]) -> Dict:
        """Create a new data table.

        Args:
            name: Table name
            columns: List of column dicts with 'name' and 'type' keys

        Returns:
            Created data table object
        """
        pid = self._get_project_id()
        payload = {"name": name, "columns": columns}
        resp = self._rest_request("POST", f"/rest/projects/{pid}/data-tables", json=payload)
        return resp.get("data", resp) if isinstance(resp, dict) and "data" in resp else resp

    def delete_data_table(self, table_id: str) -> None:
        """Delete a data table.

        Args:
            table_id: ID of the table to delete
        """
        pid = self._get_project_id()
        self._rest_request("DELETE", f"/rest/projects/{pid}/data-tables/{table_id}")

    def get_data_table_columns(self, table_id: str) -> List[Dict]:
        """Get columns for a data table.

        Args:
            table_id: Table ID

        Returns:
            List of column dicts
        """
        pid = self._get_project_id()
        resp = self._rest_request("GET", f"/rest/projects/{pid}/data-tables/{table_id}/columns")
        data = resp.get("data", resp) if isinstance(resp, dict) else resp
        return data if isinstance(data, list) else []

    def list_data_table_rows(self, table_id: str, limit: int = 100) -> List[Dict]:
        """List rows in a data table.

        Args:
            table_id: Table ID
            limit: Maximum number of rows to return

        Returns:
            List of row dicts
        """
        pid = self._get_project_id()
        resp = self._rest_request(
            "GET",
            f"/rest/projects/{pid}/data-tables/{table_id}/rows",
            params={"limit": limit},
        )
        data = resp.get("data", resp) if isinstance(resp, dict) else resp
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data if isinstance(data, list) else []

    def insert_data_table_rows(self, table_id: str, rows: List[Dict]) -> Any:
        """Insert rows into a data table.

        Args:
            table_id: Table ID
            rows: List of row dicts to insert

        Returns:
            Insert result (count or inserted rows)
        """
        pid = self._get_project_id()
        payload = {"returnType": "count", "data": rows}
        return self._rest_request(
            "POST",
            f"/rest/projects/{pid}/data-tables/{table_id}/insert",
            json=payload,
        )

    def update_data_table_rows(self, table_id: str, row_id: int, data: Dict) -> Any:
        """Update a data table row by ID.

        Args:
            table_id: Table ID
            row_id: Row ID (integer)
            data: Dict of column:value pairs to update

        Returns:
            Updated row data
        """
        pid = self._get_project_id()
        payload = {
            "filter": {
                "type": "and",
                "filters": [{"columnName": "id", "condition": "eq", "value": row_id}],
            },
            "data": data,
            "returnData": True,
        }
        return self._rest_request(
            "PATCH",
            f"/rest/projects/{pid}/data-tables/{table_id}/rows",
            json=payload,
        )

    def delete_data_table_rows(self, table_id: str, row_ids: List[str]) -> Any:
        """Delete rows from a data table by row IDs.

        Uses the filter query parameter (JSON-encoded string) as required
        by the n8n REST API.

        Args:
            table_id: Table ID
            row_ids: List of row IDs to delete (as strings; cast to int for filter)

        Returns:
            Delete result
        """
        import json as _json

        pid = self._get_project_id()
        filters = [{"columnName": "id", "condition": "eq", "value": int(rid)} for rid in row_ids]
        filter_type = "or" if len(filters) > 1 else "and"
        filter_obj = {"type": filter_type, "filters": filters}
        return self._rest_request(
            "DELETE",
            f"/rest/projects/{pid}/data-tables/{table_id}/rows",
            params={"filter": _json.dumps(filter_obj)},
        )

    def list_nodes(self, node_type: str = "default", include_tools: bool = False) -> List[Dict]:
        """List nodes installed on the n8n server.

        Fetches from /types/nodes.json. Community nodes are identified
        by the presence of a 'communityNodePackageVersion' field.

        Args:
            node_type: "default" for built-in nodes, "community" for community packages,
                       "all" for all nodes (needed for custom extensions which lack communityNodePackageVersion)
            include_tools: If True, include auto-generated AI tool variants (nodes with
                          usableAsTool=true get twin nodes with outputs=["ai_tool"])

        Returns:
            List of node dicts with name, displayName, description, version, group, isTool
        """
        server_url = self._get_server_url()
        cookie = self._get_session_cookie()

        try:
            resp = requests.get(
                f"{server_url}/types/nodes.json",
                headers={"cookie": cookie},
                timeout=30,
            )
            resp.raise_for_status()
            all_nodes = resp.json()
        except requests.exceptions.RequestException as e:
            raise N8nApiError(f"Failed to fetch nodes: {e}")

        if node_type == "community":
            nodes = [n for n in all_nodes if n.get("communityNodePackageVersion")]
        elif node_type == "all":
            # Return all nodes — used to find custom extension nodes
            nodes = all_nodes
        else:
            nodes = [n for n in all_nodes if not n.get("communityNodePackageVersion")]

        # Identify auto-generated tool twins. When a node has usableAsTool=true,
        # n8n auto-creates a twin with outputs=["ai_tool"] and no usableAsTool flag.
        usable_sigs = set()
        for n in all_nodes:
            if n.get("usableAsTool"):
                pkg = n.get("name", "").rsplit(".", 1)[0]
                usable_sigs.add((pkg, n.get("description", "")))

        def _is_auto_twin(n: Dict) -> bool:
            if n.get("usableAsTool") or n.get("outputs") != ["ai_tool"]:
                return False
            pkg = n.get("name", "").rsplit(".", 1)[0]
            return (pkg, n.get("description", "")) in usable_sigs

        if not include_tools:
            nodes = [n for n in nodes if not _is_auto_twin(n)]

        return [
            {
                "name": n.get("name", ""),
                "displayName": n.get("displayName", ""),
                "description": n.get("description", ""),
                "version": n.get("communityNodePackageVersion") or n.get("defaultVersion") or n.get("version", ""),
                "group": n.get("group", []),
                "isTool": _is_auto_twin(n),
            }
            for n in nodes
        ]

    def list_community_packages(self) -> List[Dict]:
        """List packages installed through n8n's community package manager."""
        data = self._request("GET", "/community-packages")
        if isinstance(data, dict):
            return data.get("data", [])
        return data

    def install_community_package(
        self,
        package_name: str,
        version: Optional[str] = None,
        verify: bool = False,
    ) -> Dict:
        """Install a community package through the running n8n instance."""
        payload: Dict[str, Any] = {"name": package_name, "verify": verify}
        if version:
            payload["version"] = version
        data = self._request("POST", "/community-packages", json=payload, timeout=300)
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data

    def uninstall_community_package(self, package_name: str) -> None:
        """Uninstall a community package through the running n8n instance."""
        encoded_name = quote(package_name, safe="")
        self._request("DELETE", f"/community-packages/{encoded_name}", timeout=300)

    def resolve_node_type(self, node_name: str) -> Optional[str]:
        """Resolve a short node name to its full node type by querying the server.

        Searches community nodes first, then falls back to all nodes.

        Args:
            node_name: Short node name (e.g., "claudecode")

        Returns:
            Full node type string (e.g., "n8n-nodes-claudecode.claudeCode") or None
        """
        if node_name.startswith("n8n-nodes-"):
            node_name = node_name[len("n8n-nodes-"):]
        prefix = f"n8n-nodes-{node_name}."
        try:
            # Check community nodes first (installed via npm in ~/.n8n/nodes/)
            nodes = self.list_nodes(node_type="community")
            for node in nodes:
                if node["name"].startswith(prefix):
                    return node["name"]
            # Fall back to all nodes
            nodes = self.list_nodes(node_type="all")
            for node in nodes:
                if node["name"].startswith(prefix):
                    return node["name"]
        except N8nApiError:
            pass
        return None

    def get_node_credential_types(self, full_node_type: str) -> List[str]:
        """Get the credential type names required by a node.

        Fetches the full node definition from /types/nodes.json and extracts
        the credential type names.

        Args:
            full_node_type: Full node type (e.g., "n8n-nodes-claudecode.claudeCode")

        Returns:
            List of credential type names (e.g., ["claudeCodeApi"])
        """
        server_url = self._get_server_url()
        cookie = self._get_session_cookie()

        try:
            resp = requests.get(
                f"{server_url}/types/nodes.json",
                headers={"cookie": cookie},
                timeout=30,
            )
            resp.raise_for_status()
            all_nodes = resp.json()
        except requests.exceptions.RequestException as e:
            raise N8nApiError(f"Failed to fetch nodes: {e}")

        for node in all_nodes:
            if node.get("name") == full_node_type:
                creds = node.get("credentials", [])
                return [c["name"] for c in creds if isinstance(c, dict) and "name" in c]

        return []

    def list_credentials(self) -> List[Dict]:
        """List all credentials via the internal REST API.

        Returns:
            List of credential dicts with id, name, type
        """
        server_url = self._get_server_url()
        cookie = self._get_session_cookie()

        try:
            resp = requests.get(
                f"{server_url}/rest/credentials",
                headers={"cookie": cookie},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
        except requests.exceptions.RequestException as e:
            raise N8nApiError(f"Failed to list credentials: {e}")

        return [{"id": c["id"], "name": c["name"], "type": c["type"]} for c in data]

    def create_credential(self, name: str, cred_type: str, data: Dict) -> Dict:
        """Create a credential on the n8n server via the public API.

        Args:
            name: Display name (e.g., "Brickowl API")
            cred_type: Credential type name (e.g., "brickowlApi")
            data: Credential data dict (e.g., {"apiKey": "abc123"})

        Returns:
            Created credential object with id, name, type
        """
        payload = {"name": name, "type": cred_type, "data": data}
        return self._request("POST", "/credentials", json=payload)

    def update_credential(self, credential_id: str, **kwargs) -> Dict:
        """Update a credential on the n8n server via the public API.

        Args:
            credential_id: ID of the credential to update
            **kwargs: Fields to update (name, type, data, isGlobal, isResolvable)

        Returns:
            Updated credential object
        """
        return self._request("PATCH", f"/credentials/{credential_id}", json=kwargs)

    def delete_credential(self, credential_id: str) -> Dict:
        """Delete a credential on the n8n server via the public API.

        Args:
            credential_id: ID of the credential to delete

        Returns:
            Deleted credential object
        """
        return self._request("DELETE", f"/credentials/{credential_id}")

    def get_credential_schema(self, cred_type: str) -> Dict:
        """Get the JSON schema for a credential type via the public API.

        Args:
            cred_type: Credential type name (e.g., "brickowlApi")

        Returns:
            JSON Schema dict with properties and required fields
        """
        return self._request("GET", f"/credentials/schema/{cred_type}")

    def list_workflows(
        self,
        active: Optional[bool] = None,
        tags: Optional[str] = None,
        name: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> List[Dict]:
        """List workflows with optional filtering.

        Paginates through all results using cursor-based pagination.

        Args:
            active: Filter by active status
            tags: Filter by tag name
            name: Filter by workflow name (substring match, client-side)
            limit: Maximum number of workflows to return
            cursor: Pagination cursor

        Returns:
            List of workflow dicts
        """
        all_workflows = []
        page_size = min(limit, 250)

        while True:
            params: Dict[str, Any] = {"limit": page_size}
            if active is not None:
                params["active"] = str(active).lower()
            if tags:
                params["tags"] = tags
            if cursor:
                params["cursor"] = cursor

            response = self._request("GET", "/workflows", params=params)
            data = response.get("data", [])
            all_workflows.extend(data)

            next_cursor = response.get("nextCursor")
            if not next_cursor or len(all_workflows) >= limit:
                break
            cursor = next_cursor

        # Client-side name filter
        if name:
            all_workflows = [
                wf for wf in all_workflows
                if name.lower() in wf.get("name", "").lower()
            ]

        return all_workflows[:limit]

    def get_workflow(self, workflow_id: str) -> Dict:
        """Get a specific workflow by ID.

        Args:
            workflow_id: Workflow ID

        Returns:
            Full workflow object with nodes, connections, settings
        """
        return self._request("GET", f"/workflows/{workflow_id}")

    def update_workflow(self, workflow_id: str, data: Dict) -> Dict:
        """Update an existing workflow.

        Args:
            workflow_id: ID of the workflow to update
            data: Updated workflow data

        Returns:
            Updated workflow object
        """
        return self._request("PUT", f"/workflows/{workflow_id}", json=data)

    def get_execution(self, execution_id: int, include_data: bool = True) -> Dict:
        """Get a specific execution by ID.

        Args:
            execution_id: Execution ID
            include_data: Include detailed execution data

        Returns:
            Execution object
        """
        params = {}
        if include_data:
            params["includeData"] = "true"

        return self._request("GET", f"/executions/{execution_id}", params=params)

    def _fetch_all_node_definitions(self) -> List[Dict]:
        """Fetch all node definitions from the server.

        Returns:
            List of full node definition dicts
        """
        server_url = self._get_server_url()
        cookie = self._get_session_cookie()

        try:
            resp = requests.get(
                f"{server_url}/types/nodes.json",
                headers={"cookie": cookie},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            raise N8nApiError(f"Failed to fetch nodes: {e}")

    def get_node_definition(self, name: str) -> Optional[Dict]:
        """Fetch full node definition by fuzzy match on displayName or exact match on type name.

        Args:
            name: Node name to search for (e.g., "slack", "n8n-nodes-base.slack")

        Returns:
            Full node definition dict, or None if not found
        """
        all_nodes = self._fetch_all_node_definitions()
        name_lower = name.lower()

        # Exact match on type name
        for node in all_nodes:
            if node.get("name", "") == name:
                return node

        # Case-insensitive match on full type name
        for node in all_nodes:
            if node.get("name", "").lower() == name_lower:
                return node

        # Match on the last segment of the type name (e.g., "slack" matches "n8n-nodes-base.slack")
        for node in all_nodes:
            node_type = node.get("name", "")
            suffix = node_type.rsplit(".", 1)[-1].lower() if "." in node_type else node_type.lower()
            if suffix == name_lower:
                return node

        # Fuzzy match on displayName (case-insensitive substring)
        for node in all_nodes:
            display = node.get("displayName", "").lower()
            if name_lower == display:
                return node

        # Partial displayName match
        for node in all_nodes:
            display = node.get("displayName", "").lower()
            if name_lower in display:
                return node

        return None

    def get_node_type(self, full_node_type: str) -> Optional[Dict]:
        """Fetch the full node type definition (schema) for a given node type name.

        Args:
            full_node_type: Full node type (e.g., "n8n-nodes-base.slackTrigger")

        Returns:
            Full node definition dict, or None if not found.
        """
        all_nodes = self._fetch_all_node_definitions()
        for node in all_nodes:
            if node.get("name") == full_node_type:
                return node
        return None

    def dynamic_options_request(
        self,
        node_type: str,
        type_version: Any,
        path: str,
        method_name: str,
        current_node_parameters: Optional[Dict] = None,
        credentials: Optional[Dict] = None,
    ) -> Any:
        """Call the n8n internal endpoint that resolves a loadOptionsMethod.

        Posts to /rest/dynamic-node-parameters/options-request which is what the
        n8n UI uses to populate dropdowns whose options come from a node's
        loadOptionsMethod.

        Args:
            node_type: Full node type name (e.g., "n8n-nodes-base.slackTrigger")
            type_version: Node typeVersion (number)
            path: Parameter path (e.g., "parameters.channelId")
            method_name: The loadOptionsMethod name from the node schema
            current_node_parameters: Current parameter values from the node
            credentials: Credential references from the node

        Returns:
            JSON response from the endpoint (typically a list of options on success,
            or a dict with an error/message field on failure).

        Raises:
            N8nApiError: If the request itself fails (network, non-2xx, etc.).
        """
        payload = {
            "nodeTypeAndVersion": {"name": node_type, "version": type_version},
            "path": path,
            "methodName": method_name,
            "currentNodeParameters": current_node_parameters or {},
            "credentials": credentials or {},
        }
        server_url = self._get_server_url()
        cookie = self._get_session_cookie()
        try:
            resp = requests.post(
                f"{server_url}/rest/dynamic-node-parameters/options",
                headers={"cookie": cookie, "Content-Type": "application/json"},
                json=payload,
                timeout=30,
            )
        except requests.exceptions.RequestException as e:
            raise N8nApiError(f"dynamic options request failed: {e}")
        try:
            body = resp.json()
        except ValueError:
            body = {"_status": resp.status_code, "_text": resp.text}
        return {"_status_code": resp.status_code, "_body": body}

    def get_credential(self, credential_id: str) -> Optional[Dict]:
        """Look up a credential by ID using list_credentials() (no public GET-by-id endpoint).

        Args:
            credential_id: Credential ID

        Returns:
            Credential dict (with id, name, type) or None if not found.
        """
        for cred in self.list_credentials():
            if cred.get("id") == credential_id:
                return cred
        return None

    def search_nodes(self, query: str, node_type: str = "default") -> List[Dict]:
        """Search nodes by name/description substring match.

        Args:
            query: Search query string
            node_type: "default" for built-in, "community" for community packages

        Returns:
            List of matching nodes with basic info
        """
        all_nodes = self._fetch_all_node_definitions()
        query_lower = query.lower()

        if node_type == "community":
            all_nodes = [n for n in all_nodes if n.get("communityNodePackageVersion")]
        elif node_type == "default":
            all_nodes = [n for n in all_nodes if not n.get("communityNodePackageVersion")]

        matches = []
        for node in all_nodes:
            name = node.get("name", "").lower()
            display = node.get("displayName", "").lower()
            desc = node.get("description", "").lower()
            if query_lower in name or query_lower in display or query_lower in desc:
                matches.append({
                    "name": node.get("name", ""),
                    "displayName": node.get("displayName", ""),
                    "description": node.get("description", ""),
                    "version": node.get("defaultVersion") or node.get("version", ""),
                })

        return matches


def parse_node_resources(node_def: Dict) -> Dict[str, List[Dict]]:
    """Parse a node definition's properties to extract a structured resource→operations map.

    Examines properties with name='resource' and name='operation' to build
    a {resource: [{value, name, action}]} mapping.

    Args:
        node_def: Full node definition dict from get_node_definition()

    Returns:
        Dict mapping resource values to lists of operation dicts
    """
    properties = node_def.get("properties", [])
    resources = {}
    operations = {}

    # Find the resource property
    for prop in properties:
        if prop.get("name") == "resource":
            options = prop.get("options", [])
            for opt in options:
                resources[opt.get("value", "")] = opt.get("name", opt.get("value", ""))

    # Find operation properties and map them to resources
    for prop in properties:
        if prop.get("name") == "operation":
            # Determine which resource this operation belongs to
            display_opts = prop.get("displayOptions", {}).get("show", {})
            resource_filters = display_opts.get("resource", [])

            opts = []
            for opt in prop.get("options", []):
                opts.append({
                    "value": opt.get("value", ""),
                    "name": opt.get("name", opt.get("value", "")),
                    "action": opt.get("action", ""),
                })

            if resource_filters:
                for res in resource_filters:
                    operations[res] = opts
            else:
                # No resource filter — applies to all or is the only set
                operations["_default"] = opts

    # Build the result map
    result = {}
    if resources:
        for res_value, res_name in resources.items():
            result[res_value] = operations.get(res_value, operations.get("_default", []))
    elif "_default" in operations:
        result["_default"] = operations["_default"]

    return result


# Module-level client instance - singleton pattern
_client: Optional[N8nApiClient] = None


def get_n8n_api_client(config=None) -> N8nApiClient:
    """Get or create the global n8n API client instance."""
    global _client
    if _client is None:
        if config is None:
            from .config import get_config
            config = get_config()
        _client = N8nApiClient(
            base_url=config.base_url,
            api_key=config.api_key,
        )
    return _client
