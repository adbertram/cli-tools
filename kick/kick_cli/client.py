"""Kick API client with automatic token management and exponential retry."""
from datetime import datetime
from typing import Dict, List, Optional, Any
import random
import time
import requests

from cli_tools_shared.filters import FilterValidationError, parse_filter_string, validate_filters

from .config import get_config


# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_JITTER = 0.1  # 10% jitter

# HTTP status codes that trigger retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ClientError(Exception):
    """Custom exception for Kick API errors."""
    pass


class KickClient:
    """Client for interacting with Kick API with automatic token management and retry."""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
        config=None,
    ):
        """
        Initialize Kick client from configuration.

        Args:
            max_retries: Maximum number of retry attempts for transient errors (default: 3)
            base_delay: Base delay in seconds for exponential backoff (default: 1.0)
            max_delay: Maximum delay in seconds between retries (default: 30.0)
            jitter: Random jitter factor to prevent thundering herd (default: 0.1)
        """
        self.config = config or get_config()

        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'kick auth login' to authenticate."
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
        # Use Bearer token if available, otherwise API key
        if self.config.access_token:
            self.headers["Authorization"] = f"Bearer {self.config.access_token}"
        elif self.config.api_key:
            self.headers["Authorization"] = f"Bearer {self.config.api_key}"

    def _is_token_expired(self) -> bool:
        """Check if access token is expired or about to expire."""
        expires_at = self.config.token_expires_at
        if not expires_at:
            return False  # No expiry tracking, assume valid

        try:
            expires_timestamp = float(expires_at)
            # Consider expired if less than 5 minutes remaining
            return datetime.now().timestamp() > (expires_timestamp - 300)
        except (ValueError, TypeError):
            return False

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

    def _refresh_token(self):
        """Refresh the access token using the refresh token via Auth0."""
        from .commands.auth import refresh_access_token, AuthError
        from datetime import datetime

        if not self.config.refresh_token:
            raise ClientError(
                "No refresh token available. Run 'kick auth login' to re-authenticate."
            )

        try:
            token_data = refresh_access_token(self.config)

            # Calculate expiration timestamp
            expires_at = str(datetime.now().timestamp() + token_data.get("expires_in", 86400))

            # Save tokens (refresh_token may be rotated)
            self.config.save_tokens(
                access_token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token", self.config.refresh_token),
                expires_at=expires_at,
            )

            self._update_headers()
        except AuthError as e:
            raise ClientError(f"Token refresh failed: {e}. Run 'kick auth login'.")

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
    ) -> Dict:
        """
        Make an HTTP request to the Kick API with exponential retry.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: API endpoint path (e.g., "/users")
            data: Request body data
            params: Query parameters
            retry: Whether to retry on transient errors (default: True)

        Returns:
            Response JSON data

        Raises:
            ClientError: If request fails after all retries
        """
        url = f"{self.base_url}{endpoint}"

        # Check if token needs refresh
        if self._is_token_expired():
            try:
                self._refresh_token()
            except Exception:
                pass  # Try with existing token

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

                # If 401, try refreshing token and retry (doesn't count against retry limit)
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

        if not last_response.ok:
            # Try to get error details from response
            try:
                error_data = last_response.json()
                error_msg = error_data.get("message") or error_data.get("error") or last_response.text
            except Exception:
                error_msg = last_response.text
            raise ClientError(f"API request failed ({last_response.status_code}): {error_msg}")

        # Handle empty response (204 No Content or empty body)
        if last_response.status_code == 204 or not last_response.text.strip():
            return {}

        return last_response.json()

    # ==================== Workspace Methods ====================

    def get_workspaces(self) -> List[Dict]:
        """
        Get list of workspaces for the authenticated user.

        Returns:
            List of workspace objects with their entities
        """
        endpoint = "/api/workspaces/"
        response = self._make_request("GET", endpoint)

        if isinstance(response, dict) and "data" in response:
            return response["data"]
        return response

    def get_default_workspace_id(self) -> str:
        """
        Get the default workspace ID for the authenticated user.

        Returns:
            Workspace UUID string
        """
        workspaces = self.get_workspaces()
        if not workspaces:
            raise ClientError("No workspaces found for this user")
        return workspaces[0]["workspace"]["id"]

    def get_entity_ids(self, workspace_id: Optional[str] = None) -> List[int]:
        """
        Get all entity IDs for a workspace.

        Args:
            workspace_id: Workspace UUID (uses default if not provided)

        Returns:
            List of entity IDs
        """
        workspaces = self.get_workspaces()
        if not workspaces:
            raise ClientError("No workspaces found")

        ws_id = workspace_id or workspaces[0]["workspace"]["id"]

        for ws_data in workspaces:
            if ws_data["workspace"]["id"] == ws_id:
                return [e["id"] for e in ws_data["workspace"].get("entities", [])]

        raise ClientError(f"Workspace {ws_id} not found")

    # ==================== Filter Translation ====================

    def _translate_filters(self, filters: List[str]) -> Dict[str, Any]:
        """
        Translate CLI filter strings to Kick API query parameters.

        Supported filters:
            - minAmount:value - Minimum transaction amount
            - maxAmount:value - Maximum transaction amount
            - category:uuid - Filter by category UUID (can specify multiple)
            - status:value - Filter by status (completed, pending, etc.)
            - type:value - Filter by type (external, internal, etc.)
            - dateFrom:YYYY-MM-DD - Filter from date
            - dateTo:YYYY-MM-DD - Filter to date
            - direction:in|out - Filter by money direction

        Args:
            filters: List of filter strings in format "field:value" or "field:op:value"

        Returns:
            Dict of API query parameters
        """
        params: Dict[str, Any] = {}
        category_index = 0

        for filter_str in filters:
            conditions = parse_filter_string(filter_str)

            for field, op, value in conditions:
                field_lower = field.lower()

                if field_lower == "minamount":
                    params["filters[minAmount]"] = value
                elif field_lower == "maxamount":
                    params["filters[maxAmount]"] = value
                elif field_lower == "category":
                    params[f"filters[category][{category_index}]"] = value
                    category_index += 1
                elif field_lower == "status":
                    params["filters[status]"] = value
                elif field_lower == "type":
                    params["filters[type]"] = value
                elif field_lower == "datefrom":
                    params["filters[dateFrom]"] = value
                elif field_lower == "dateto":
                    params["filters[dateTo]"] = value
                elif field_lower == "direction":
                    # direction: "in" for money in, "out" for money out
                    if value.lower() == "in":
                        params["filters[direction]"] = "moneyIn"
                    elif value.lower() == "out":
                        params["filters[direction]"] = "moneyOut"
                    else:
                        params["filters[direction]"] = value
                else:
                    # Pass through unknown filters directly
                    params[f"filters[{field}]"] = value

        return params

    # ==================== Transaction Methods ====================

    def list_transactions(
        self,
        page: int = 0,
        limit: int = 100,
        sort_field: str = "date",
        sort_order: str = "DESC",
        entity_ids: Optional[List[int]] = None,
        workspace_id: Optional[str] = None,
        filters: Optional[List[str]] = None,
    ) -> Dict:
        """
        List transactions from Kick.

        Args:
            page: Page number (0-indexed)
            limit: Maximum number of transactions to return
            sort_field: Field to sort by (default: date)
            sort_order: Sort order - ASC or DESC (default: DESC)
            entity_ids: List of entity IDs to filter by (default: all entities)
            workspace_id: Workspace UUID (uses default if not provided)
            filters: List of filter strings (field:op:value)

        Returns:
            Dict with 'data', 'total', and 'pageCount' keys
        """
        # Get workspace ID if not provided
        if not workspace_id:
            workspace_id = self.get_default_workspace_id()

        # Get entity IDs if not provided
        if not entity_ids:
            entity_ids = self.get_entity_ids(workspace_id)

        endpoint = "/api/transactions/"
        params = {
            "page": page,
            "limit": limit,
            "sort[field]": sort_field,
            "sort[order]": sort_order,
            "workspaceId": workspace_id,
        }

        # Add entity IDs as array params
        for i, eid in enumerate(entity_ids):
            params[f"filters[entityIds][{i}]"] = eid

        # Apply API-level filters if provided
        if filters:
            validate_filters(filters)
            filter_params = self._translate_filters(filters)
            params.update(filter_params)

        response = self._make_request("GET", endpoint, params=params)

        return {
            "data": response.get("data", []),
            "total": response.get("total", 0),
            "pageCount": response.get("pageCount", 1),
        }

    def get_transaction(self, transaction_id: int, workspace_id: Optional[str] = None) -> Dict:
        """
        Get a specific transaction by ID.

        Args:
            transaction_id: The transaction ID
            workspace_id: Workspace UUID (uses default if not provided)

        Returns:
            Transaction object
        """
        # Get workspace ID if not provided
        if not workspace_id:
            workspace_id = self.get_default_workspace_id()

        # Search through pages to find the transaction (API has 100 limit per page)
        page = 0
        max_pages = 100  # Safety limit

        while page < max_pages:
            result = self.list_transactions(
                page=page,
                limit=100,
                workspace_id=workspace_id,
            )

            for txn in result["data"]:
                if txn["id"] == transaction_id:
                    return txn

            # No more pages
            if page >= result.get("pageCount", 1) - 1:
                break

            page += 1

        raise ClientError(f"Transaction {transaction_id} not found")

    def update_transaction(
        self,
        transaction_id: int,
        category_id: Optional[str] = None,
        counterparty_id: Optional[str] = None,
        account_id: Optional[str] = None,
        memo: Optional[str] = None,
    ) -> Dict:
        """
        Update a transaction.

        Args:
            transaction_id: The transaction ID to update
            category_id: Category UUID to assign
            counterparty_id: Counterparty UUID to assign
            account_id: Account UUID to assign
            memo: Note/memo text to add to the transaction

        Returns:
            Updated transaction object
        """
        endpoint = f"/api/transactions/{transaction_id}"

        # Build request data - only include fields that are provided
        data: Dict[str, Any] = {
            "loosingAccessConfirmed": False,
        }

        if category_id is not None:
            data["categoryId"] = category_id
        if counterparty_id is not None:
            data["counterpartyId"] = counterparty_id
        if account_id is not None:
            data["accountId"] = account_id
        if memo is not None:
            data["memo"] = memo

        response = self._make_request("PATCH", endpoint, data=data)
        return response.get("transaction", response)

    # ==================== Client Methods ====================

    def list_clients(
        self,
        workspace_id: Optional[str] = None,
        limit: int = 50,
        sort: str = "name_asc",
        include_registered: str = "all",
        filters: Optional[List[str]] = None,
    ) -> List[Dict]:
        """
        List clients (counterparties) for a workspace.

        Args:
            workspace_id: Workspace UUID (uses default if not provided)
            limit: Maximum number of clients to return (default: 50)
            sort: Sort order (name_asc, name_desc, etc.)
            include_registered: Filter by registration status (all, used)
            filters: List of filter strings (field:op:value). Name filters are
                     converted to API search parameter.

        Returns:
            List of client objects

        API-level filters: name (converted to search parameter)
        Client-side filters: all other fields
        """
        if not workspace_id:
            workspace_id = self.get_default_workspace_id()

        endpoint = "/api/counterparty"
        params = {
            "workspaceId": workspace_id,
            "limit": limit,
            "sort": sort,
            "includeRegistered": include_registered,
            "format": "json",
        }

        # Extract name filter and convert to API search parameter
        if filters:
            search_term = self._extract_name_filter(filters)
            if search_term:
                params["search"] = search_term

        response = self._make_request("GET", endpoint, params=params)
        return response.get("data", [])

    def _extract_name_filter(self, filters: List[str]) -> Optional[str]:
        """
        Extract name filter value and convert to API search term.

        Handles:
            - name:value (eq operator)
            - name:eq:value
            - name:like:%value% (strips % wildcards)
            - name:ilike:%value%

        Returns:
            Search term string or None
        """
        for filter_str in filters:
            conditions = parse_filter_string(filter_str)
            for field, op, value in conditions:
                if field.lower() == "name" and value:
                    # Strip LIKE wildcards for API search
                    search_term = value.strip("%")
                    return search_term
        return None

    def get_client(self, client_id: str, workspace_id: Optional[str] = None) -> Dict:
        """
        Get a specific client by ID.

        Args:
            client_id: The client UUID
            workspace_id: Workspace UUID (uses default if not provided)

        Returns:
            Client object
        """
        # Search through list with a high limit to find the client
        clients = self.list_clients(workspace_id=workspace_id, limit=500)

        for item in clients:
            # Handle nested counterparty structure
            client = item.get("counterparty", item)
            if client.get("id") == client_id:
                return client

        raise ClientError(f"Client {client_id} not found")

    def create_client(self, name: str, workspace_id: Optional[str] = None) -> Dict:
        """
        Create a new client (counterparty).

        Args:
            name: Name of the client
            workspace_id: Workspace UUID (uses default if not provided)

        Returns:
            Created client object
        """
        if not workspace_id:
            workspace_id = self.get_default_workspace_id()

        endpoint = "/api/counterparty"
        data = {
            "name": name,
            "workspaceId": workspace_id,
        }

        response = self._make_request("POST", endpoint, data=data)
        return response.get("counterparty", response)

    # ==================== Category Methods ====================

    def list_categories(self, workspace_id: Optional[str] = None, include_subcategories: bool = True) -> List[Dict]:
        """
        List all categories for a workspace.

        Args:
            workspace_id: Workspace UUID (uses default if not provided)
            include_subcategories: Whether to flatten subcategories into the list (default: True)

        Returns:
            List of category objects
        """
        if not workspace_id:
            workspace_id = self.get_default_workspace_id()

        endpoint = f"/api/category/{workspace_id}"
        response = self._make_request("GET", endpoint)

        categories = response.get("categories", [])

        if include_subcategories:
            # Flatten subcategories into the main list
            flattened = []
            for cat in categories:
                # Add parent category
                cat_copy = {k: v for k, v in cat.items() if k != "subcategories"}
                cat_copy["isSubcategory"] = False
                flattened.append(cat_copy)

                # Add subcategories
                for subcat in cat.get("subcategories", []):
                    subcat_copy = {**subcat, "isSubcategory": True}
                    flattened.append(subcat_copy)

            return flattened

        return categories

    def get_category(self, category_id: str, workspace_id: Optional[str] = None) -> Dict:
        """
        Get a specific category by ID.

        Args:
            category_id: The category UUID
            workspace_id: Workspace UUID (uses default if not provided)

        Returns:
            Category object
        """
        categories = self.list_categories(workspace_id=workspace_id, include_subcategories=True)

        for cat in categories:
            if cat["id"] == category_id:
                return cat

        raise ClientError(f"Category {category_id} not found")

    # ==================== Rule Group Methods ====================

    def list_rule_groups(self, workspace_id: Optional[str] = None) -> Dict:
        """
        List all rule groups for a workspace.

        Args:
            workspace_id: Workspace UUID (uses default if not provided)

        Returns:
            Dict with 'ruleGroups', 'counterparties', and 'transactionCounts' keys
        """
        if not workspace_id:
            workspace_id = self.get_default_workspace_id()

        endpoint = f"/api/rule-groups/{workspace_id}"
        return self._make_request("GET", endpoint)

    def get_rule_group(self, group_id: str, workspace_id: Optional[str] = None) -> Dict:
        """
        Get a specific rule group by ID.

        Args:
            group_id: The rule group UUID
            workspace_id: Workspace UUID (uses default if not provided)

        Returns:
            Rule group object
        """
        result = self.list_rule_groups(workspace_id=workspace_id)

        for group in result.get("ruleGroups", []):
            if group["id"] == group_id:
                return group

        raise ClientError(f"Rule group {group_id} not found")

    def create_rule_group(
        self,
        name: str,
        rule_type: str = "transaction",
        icon: str = "briefcase",
        order: Optional[int] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict:
        """
        Create a new rule group.

        Args:
            name: Name for the rule group
            rule_type: Type of rule group (transaction, accounting, transfer, split)
            icon: Icon identifier (briefcase, bank, etc.)
            order: Order position (auto-calculated if not provided)
            workspace_id: Workspace UUID (uses default if not provided)

        Returns:
            Created rule group object
        """
        if not workspace_id:
            workspace_id = self.get_default_workspace_id()

        # Calculate order if not provided
        if order is None:
            result = self.list_rule_groups(workspace_id=workspace_id)
            existing_groups = [g for g in result.get("ruleGroups", []) if g.get("type") == rule_type]
            order = len(existing_groups) + 1

        endpoint = f"/api/rule-groups/{workspace_id}/group/"
        data = {
            "name": name,
            "icon": icon,
            "order": order,
            "type": rule_type,
        }

        response = self._make_request("POST", endpoint, data=data)
        return response.get("rule", response)

    def delete_rule_group(self, group_id: str, workspace_id: Optional[str] = None) -> None:
        """
        Delete a rule group.

        Args:
            group_id: The rule group UUID to delete
            workspace_id: Workspace UUID (uses default if not provided)
        """
        if not workspace_id:
            workspace_id = self.get_default_workspace_id()

        endpoint = f"/api/rule-groups/{workspace_id}/group/{group_id}"
        self._make_request("DELETE", endpoint)

    def create_rule(
        self,
        group_id: str,
        conditions: List[Dict],
        actions: List[Dict],
        apply_to_existing: bool = False,
        workspace_id: Optional[str] = None,
    ) -> Dict:
        """
        Create a new rule within a rule group.

        Args:
            group_id: The rule group UUID to add the rule to
            conditions: List of condition objects, e.g.:
                [{"conditionType": "counterparty", "value": "uuid", "transferDirection": None}]
            actions: List of action objects, e.g.:
                [{"actionType": "category", "value": "uuid", "order": 0, "transferDirection": None}]
            apply_to_existing: Whether to apply the rule to existing transactions
            workspace_id: Workspace UUID (uses default if not provided)

        Returns:
            Created rule object
        """
        if not workspace_id:
            workspace_id = self.get_default_workspace_id()

        endpoint = f"/api/rule-groups/{workspace_id}/rule/"
        data = {
            "rule": {
                "groupId": group_id,
                "conditions": conditions,
                "actions": actions,
            },
            "source": "settings",
            "applyToExistingTransactions": apply_to_existing,
            "excludedTransactionsIds": [],
        }

        response = self._make_request("POST", endpoint, data=data)
        return response.get("rule", response)

    def delete_rule(self, rule_id: str, workspace_id: Optional[str] = None) -> None:
        """
        Delete a rule.

        Args:
            rule_id: The rule UUID to delete
            workspace_id: Workspace UUID (uses default if not provided)
        """
        if not workspace_id:
            workspace_id = self.get_default_workspace_id()

        endpoint = f"/api/rule-groups/{workspace_id}/rule/{rule_id}"
        self._make_request("DELETE", endpoint)

    # ==================== Integration Methods ====================

    def list_integrations(self, workspace_id: Optional[str] = None) -> List[Dict]:
        """
        List all integrations for a workspace.

        Integrations represent linked financial accounts (banks, PayPal, Stripe, etc.)
        Merges data from both user/integrations (Plaid/Stripe) and integration-connection
        (direct OAuth like PayPal) endpoints.

        Args:
            workspace_id: Workspace UUID (uses default if not provided)

        Returns:
            List of integration objects with their financial accounts
        """
        if not workspace_id:
            workspace_id = self.get_default_workspace_id()

        connections = []

        # Get Plaid/Stripe connections from user/integrations endpoint
        endpoint = "/api/user/integrations"
        params = {"workspaceId": workspace_id}
        response = self._make_request("GET", endpoint, params=params)

        for item in response.get("financialConnections", []):
            conn = item.get("connection", {})
            if conn:
                # Mark source for clarity
                conn["_source"] = "user_integrations"
                connections.append(conn)

        # Get direct OAuth connections (PayPal direct) from integration-connection endpoint
        endpoint = f"/api/integration-connection/{workspace_id}"
        try:
            response = self._make_request("GET", endpoint)
            for conn in response.get("connections", []):
                # Normalize structure to match user/integrations format
                normalized = {
                    "id": conn.get("id"),
                    "bankName": conn.get("label") or conn.get("provider"),
                    "connectionProvider": conn.get("provider"),
                    "connectionExternalId": conn.get("providerId"),
                    "createdAt": conn.get("createdAt"),
                    "error": conn.get("error"),
                    "accounts": conn.get("integrationAccounts", []),
                    "_source": "integration_connection",
                }
                connections.append(normalized)
        except Exception:
            pass  # integration-connection endpoint may not exist or return empty

        return connections

    def get_integration(self, integration_id: str, workspace_id: Optional[str] = None) -> Dict:
        """
        Get a specific integration by ID.

        Args:
            integration_id: The integration ID (numeric or string)
            workspace_id: Workspace UUID (uses default if not provided)

        Returns:
            Integration object
        """
        integrations = self.list_integrations(workspace_id=workspace_id)

        # Try to match as both string and int
        for integ in integrations:
            integ_id = integ.get("id")
            if str(integ_id) == str(integration_id):
                return integ

        raise ClientError(f"Integration {integration_id} not found")


# Module-level client instance - singleton pattern
_client: Optional[KickClient] = None


def get_client() -> KickClient:
    """Get or create the global Kick client instance."""
    global _client
    if _client is None:
        _client = KickClient()
    return _client
