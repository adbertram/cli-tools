"""n8n REST API client for workflow and execution management.

Used by the test command to create temporary workflows, trigger them via webhook,
poll for execution results, and clean up.
"""
import requests
from pathlib import Path
from typing import Any, Dict, List, Optional


class N8nApiError(Exception):
    """Custom exception for n8n API errors."""
    pass


class N8nApiClient:
    """Client for n8n REST API operations."""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        """Initialize the API client.

        Args:
            base_url: n8n API base URL (default: from ~/.claude/skills/n8n/.env)
            api_key: n8n API key (default: from ~/.claude/skills/n8n/.env)
        """
        # Load from .env file if not provided
        env_path = Path.home() / ".claude" / "skills" / "n8n" / ".env"
        env_vars = {}
        if env_path.exists():
            for line in env_path.read_text().strip().split("\n"):
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip()

        self.base_url = (base_url or env_vars.get("N8N_BASE", "")).rstrip("/")
        self.api_key = api_key or env_vars.get("N8N_API_KEY", "")

        if not self.base_url:
            raise N8nApiError("N8N_BASE not configured. Set in ~/.claude/skills/n8n/.env")
        if not self.api_key:
            raise N8nApiError("N8N_API_KEY not configured. Set in ~/.claude/skills/n8n/.env")

        self.session = requests.Session()
        self.session.headers.update({
            "X-N8N-API-KEY": self.api_key,
            "Content-Type": "application/json",
        })

    def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Make an API request.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            endpoint: API endpoint (e.g., /workflows)
            **kwargs: Additional arguments to pass to requests

        Returns:
            JSON response data

        Raises:
            N8nApiError: If the request fails
        """
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()

            # Handle 204 No Content
            if response.status_code == 204:
                return None

            return response.json()
        except requests.exceptions.HTTPError as e:
            error_msg = str(e)
            try:
                error_data = response.json()
                if "message" in error_data:
                    error_msg = error_data["message"]
            except:
                pass
            raise N8nApiError(f"API request failed: {error_msg}")
        except requests.exceptions.RequestException as e:
            raise N8nApiError(f"Request failed: {e}")

    def create_workflow(self, name: str, nodes: List[Dict], connections: Dict) -> Dict:
        """Create a new workflow.

        Args:
            name: Workflow name
            nodes: List of node definitions
            connections: Node connections

        Returns:
            Created workflow object with id
        """
        payload = {
            "name": name,
            "nodes": nodes,
            "connections": connections,
            "settings": {
                "saveManualExecutions": True,
                "saveDataSuccessExecution": "all",
                "saveDataErrorExecution": "all",
            }
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
        env_path = Path.home() / ".claude" / "skills" / "n8n" / ".env"
        env_vars = {}
        if env_path.exists():
            for line in env_path.read_text().strip().split("\n"):
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip()

        email = env_vars.get("N8N_EMAIL", "")
        password = env_vars.get("N8N_PASSWORD", "")
        if not email or not password:
            raise N8nApiError("N8N_EMAIL and N8N_PASSWORD required in ~/.claude/skills/n8n/.env")

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

    def list_nodes(self, node_type: str = "default") -> List[Dict]:
        """List nodes installed on the n8n server.

        Fetches from /types/nodes.json. Community nodes are identified
        by the presence of a 'communityNodePackageVersion' field.

        Args:
            node_type: "default" for built-in nodes, "community" for community packages,
                       "all" for all nodes (needed for custom extensions which lack communityNodePackageVersion)

        Returns:
            List of node dicts with name, displayName, description, version, group
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

        # Filter out auto-generated tool twins. When a node has usableAsTool=true,
        # n8n auto-creates a twin with outputs=["ai_tool"] and no usableAsTool flag.
        # Identify twins by: same package + same description as a usableAsTool node.
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

        nodes = [n for n in nodes if not _is_auto_twin(n)]

        return [
            {
                "name": n.get("name", ""),
                "displayName": n.get("displayName", ""),
                "description": n.get("description", ""),
                "version": n.get("communityNodePackageVersion") or n.get("defaultVersion") or n.get("version", ""),
                "group": n.get("group", []),
            }
            for n in nodes
        ]

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

    def get_credential(self, credential_id: str) -> Dict:
        """Get a credential summary by ID."""
        for credential in self.list_credentials():
            if credential["id"] == credential_id:
                return credential
        raise N8nApiError(f"Credential not found: {credential_id}")

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


# Module-level client instance - singleton pattern
_client: Optional[N8nApiClient] = None


def get_n8n_api_client() -> N8nApiClient:
    """Get or create the global n8n API client instance."""
    global _client
    if _client is None:
        _client = N8nApiClient()
    return _client
