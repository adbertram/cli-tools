"""Dataverse API client for Copilot Studio agents."""
from __future__ import annotations

import subprocess
import shutil
import sys
import json
import re
import random
import string
import os
import mimetypes
import time
from typing import Any, List, Optional, Sequence, Union
from urllib.parse import urlparse, urlunparse
import httpx
from .config import get_config


# Transient HTTP status codes that should trigger a retry
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}

# Default retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 60.0
DEFAULT_JITTER = 0.1

# Power Platform custom connector OAuth identity providers.
# Each value is a preset that knows the vendor's OAuth dialect (e.g. Google
# injects access_type=offline, Azure AD expects offline_access scope). Using
# "oauth2" falls back to generic OAuth 2 with no provider-specific handling.
VALID_OAUTH_IDENTITY_PROVIDERS = frozenset({
    "oauth2",
    "aad",
    "google",
    "github",
    "facebook",
})


def parse_connection_string(connection_string: str) -> dict[str, str]:
    """
    Parse an Application Insights connection string into a dictionary.

    Connection strings have the format:
    InstrumentationKey=xxx;IngestionEndpoint=xxx;LiveEndpoint=xxx;ApplicationId=xxx

    Args:
        connection_string: The App Insights connection string

    Returns:
        Dict with keys like 'InstrumentationKey', 'ApplicationId', etc.
    """
    result = {}
    if not connection_string:
        return result

    for part in connection_string.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            result[key.strip()] = value.strip()

    return result


class ClientError(Exception):
    """Exception raised for client initialization or API errors."""
    pass


def _needs_mustache_template_format(text: str) -> bool:
    """
    Return True if `text` requires the Custom GPT botcomponent's TemplateLine
    fields (`instructions`, `responseInstructions`) to be parsed with the
    Mustache template format instead of the default Power Fx format.

    The Copilot Studio publish step parses TemplateLine values as a template
    whose default format is Power Fx. In Power Fx, `{ ... }` is a record /
    expression literal — so a literal `{` in user content (e.g. a JSON shape
    example like `{ "summary_markdown": ... }`) triggers expression parsing
    and fails PvaPublish with "Unexpected character in expression".

    Switching the per-component template format to Mustache changes the
    expression delimiter to `{{ ... }}`, so a single `{` is just plain text.
    """
    if not text:
        return False
    return "{" in text


def _validate_oauth_identity_provider(value: Optional[str]) -> None:
    """Raise ClientError if an OAuth identity provider value isn't supported."""
    if value is None:
        return
    if value not in VALID_OAUTH_IDENTITY_PROVIDERS:
        valid_list = ", ".join(sorted(VALID_OAUTH_IDENTITY_PROVIDERS))
        raise ClientError(
            f"Invalid OAuth identity provider '{value}'. "
            f"Valid values: {valid_list}"
        )


class DataverseClient:
    """Client for interacting with Dataverse Web API for Copilot Studio agents."""

    def __init__(self, base_url: str, access_token: str):
        """
        Initialize the Dataverse client.

        Args:
            base_url: Dataverse environment URL (e.g., https://yourorg.crm.dynamics.com)
            access_token: OAuth access token for authentication
        """
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}/api/data/v9.2"
        self.access_token = access_token
        self._http_client = httpx.Client(timeout=30.0)

    def _get_headers(self) -> dict[str, str]:
        """Get HTTP headers for API requests."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Prefer": "odata.include-annotations=*",
        }

    def _build_odata_filter(self, filters: list[str]) -> str:
        """
        Convert field:op:value filters to OData $filter syntax.

        Args:
            filters: List of filters in field:op:value format

        Returns:
            OData $filter query string

        Supported operators:
            eq: Equals (default)
            ne: Not equals
            gt: Greater than
            gte: Greater or equal (ge in OData)
            lt: Less than
            lte: Less or equal (le in OData)
            contains: Contains (for string fields)
        """
        if not filters:
            return ""

        odata_filters = []

        for filter_str in filters:
            parts = filter_str.split(":")

            # Handle field:value (default to eq)
            if len(parts) == 2:
                field, value = parts
                op = "eq"
            # Handle field:op:value
            elif len(parts) == 3:
                field, op, value = parts
            else:
                continue  # Skip invalid filters

            # Map operators to OData syntax
            if op == "eq":
                odata_filters.append(f"{field} eq '{value}'")
            elif op == "ne":
                odata_filters.append(f"{field} ne '{value}'")
            elif op == "gt":
                odata_filters.append(f"{field} gt '{value}'")
            elif op == "gte" or op == "ge":
                odata_filters.append(f"{field} ge '{value}'")
            elif op == "lt":
                odata_filters.append(f"{field} lt '{value}'")
            elif op == "lte" or op == "le":
                odata_filters.append(f"{field} le '{value}'")
            elif op == "contains":
                odata_filters.append(f"contains({field},'{value}')")

        return " and ".join(odata_filters)

    def _calculate_retry_delay(
        self,
        attempt: int,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
        retry_after: Optional[float] = None,
    ) -> float:
        """
        Calculate delay before next retry using exponential backoff.

        Args:
            attempt: Current attempt number (0-indexed)
            base_delay: Base delay in seconds
            max_delay: Maximum delay in seconds
            jitter: Jitter factor (0.0 to 1.0) to add randomness
            retry_after: Value from Retry-After header if present

        Returns:
            Delay in seconds before next retry
        """
        if retry_after is not None:
            return min(retry_after, max_delay)

        # Exponential backoff: base_delay * 2^attempt
        delay = base_delay * (2 ** attempt)
        delay = min(delay, max_delay)

        # Add jitter to prevent thundering herd
        if jitter > 0:
            jitter_range = delay * jitter
            delay += random.uniform(-jitter_range, jitter_range)

        return max(0, delay)

    def _should_retry(self, status_code: int) -> bool:
        """Check if a request should be retried based on status code."""
        return status_code in TRANSIENT_STATUS_CODES

    def _get_retry_after(self, response: httpx.Response) -> Optional[float]:
        """Extract Retry-After header value if present."""
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return None

        try:
            # Try parsing as seconds (integer)
            return float(retry_after)
        except ValueError:
            # Could be HTTP date format, but we'll just use default backoff
            return None

    def _extract_error_detail(self, response: httpx.Response) -> str:
        """Extract error detail from an HTTP error response.

        Handles multiple formats:
        - Dataverse: {"_error": {"Description": "...", "Code": "..."}}
        - Standard: {"error": {"message": "..."}} or {"error": "..."}
        - Generic: {"message": "..."} or raw text
        """
        try:
            error_body = response.json()

            # Dataverse format: _error.Description
            if "_error" in error_body:
                err = error_body["_error"]
                if isinstance(err, dict):
                    return err.get("Description") or err.get("Message") or err.get("Code") or str(err)
                return str(err)

            # Standard format: error.message
            if "error" in error_body:
                err = error_body["error"]
                if isinstance(err, dict):
                    return err.get("message") or err.get("code") or str(err)
                return str(err)

            # Generic format: message field
            if "message" in error_body:
                return error_body["message"]

            # Fallback: stringify the whole body
            return str(error_body)[:500]
        except Exception:
            # JSON parsing failed, use raw text
            return response.text[:500] if response.text else ""

    def _request(
        self,
        method: str,
        endpoint: str,
        max_retries: int = DEFAULT_MAX_RETRIES,
        **kwargs,
    ) -> Any:
        """
        Make an HTTP request to the Dataverse API with exponential retry.

        Args:
            method: HTTP method (GET, POST, PATCH, DELETE)
            endpoint: API endpoint (relative to api_url)
            max_retries: Maximum number of retry attempts for transient errors
            **kwargs: Additional arguments to pass to httpx

        Returns:
            Response data as dict/list

        Raises:
            ClientError: If the request fails after all retries
        """
        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        headers = self._get_headers()
        headers.update(kwargs.pop("headers", {}))

        return_id = kwargs.pop("return_id", False)
        last_exception = None

        for attempt in range(max_retries + 1):
            try:
                response = self._http_client.request(method, url, headers=headers, **kwargs)

                # Check for retryable status codes
                if self._should_retry(response.status_code) and attempt < max_retries:
                    retry_after = self._get_retry_after(response)
                    delay = self._calculate_retry_delay(attempt, retry_after=retry_after)
                    time.sleep(delay)
                    continue

                response.raise_for_status()

                if response.status_code == 204:
                    # Extract entity ID from OData-EntityId header if requested
                    if return_id:
                        odata_id = response.headers.get("OData-EntityId", "")
                        # Format: https://.../api/data/v9.2/bots(guid)
                        if "(" in odata_id and ")" in odata_id:
                            entity_id = odata_id.split("(")[-1].rstrip(")")
                            return {"id": entity_id}
                    return None

                return response.json()

            except httpx.HTTPStatusError as e:
                # Retry on transient errors
                if self._should_retry(e.response.status_code) and attempt < max_retries:
                    retry_after = self._get_retry_after(e.response)
                    delay = self._calculate_retry_delay(attempt, retry_after=retry_after)
                    time.sleep(delay)
                    last_exception = e
                    continue

                error_detail = self._extract_error_detail(e.response)
                raise ClientError(f"HTTP {e.response.status_code}: {error_detail}")

            except (httpx.RequestError, httpx.TimeoutException) as e:
                # Retry on connection errors and timeouts
                if attempt < max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    time.sleep(delay)
                    last_exception = e
                    continue
                raise ClientError(f"Request failed after {max_retries + 1} attempts: {e}")

        # If we exhausted retries, raise the last exception
        if last_exception:
            if isinstance(last_exception, httpx.HTTPStatusError):
                error_detail = self._extract_error_detail(last_exception.response)
                raise ClientError(f"HTTP {last_exception.response.status_code}: {error_detail}" if error_detail else f"HTTP {last_exception.response.status_code} after {max_retries + 1} attempts")
            raise ClientError(f"Request failed after {max_retries + 1} attempts: {last_exception}")

    def get(self, endpoint: str, params: Optional[dict] = None) -> Any:
        """Make a GET request."""
        return self._request("GET", endpoint, params=params)

    def post(self, endpoint: str, data: dict, return_id: bool = False) -> Any:
        """
        Make a POST request.

        Args:
            endpoint: API endpoint
            data: Request body data
            return_id: If True and response is 204, extract entity ID from OData-EntityId header

        Returns:
            Response JSON or dict with 'id' key if return_id=True and 204 response
        """
        return self._request("POST", endpoint, json=data, return_id=return_id)

    def patch(self, endpoint: str, data: dict) -> Any:
        """Make a PATCH request."""
        return self._request("PATCH", endpoint, json=data)

    def delete(self, endpoint: str, verify: bool = True) -> None:
        """
        Make a DELETE request.

        Args:
            endpoint: API endpoint to delete
            verify: If True, verify the resource was actually deleted by
                    attempting to GET it after deletion. Raises ClientError
                    if resource still exists.
        """
        self._request("DELETE", endpoint)

        if verify:
            try:
                self._request("GET", endpoint)
                # If we get here, resource still exists - deletion failed
                raise ClientError(f"Delete failed: resource still exists at {endpoint}")
            except ClientError as e:
                # 404 means successfully deleted, re-raise other errors
                if "404" not in str(e):
                    raise

    def list_bots(
        self,
        select: Optional[list[str]] = None,
        limit: Optional[int] = None,
        filter: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        List all Copilot Studio agents (bots) in the environment.

        Args:
            select: Optional list of fields to select
            limit: Maximum number of results to return (OData $top)
            filter: List of filters in field:op:value format

        Returns:
            List of bot records
        """
        params = []

        if select:
            params.append(f"$select={','.join(select)}")

        if limit is not None:
            params.append(f"$top={limit}")

        if filter:
            odata_filter = self._build_odata_filter(filter)
            if odata_filter:
                params.append(f"$filter={odata_filter}")

        endpoint = "bots"
        if params:
            endpoint += "?" + "&".join(params)

        result = self.get(endpoint)
        return result.get("value", [])

    def get_bot(self, bot_id: str) -> dict:
        """
        Get a specific bot by ID.

        Args:
            bot_id: The bot's unique identifier

        Returns:
            Bot record
        """
        if not self._is_guid(bot_id):
            raise ValueError(f"Invalid agent ID format: '{bot_id}'. Expected a full GUID (8-4-4-4-12 hex format, e.g. 12345678-1234-1234-1234-123456789abc).")
        return self.get(f"bots({bot_id})")

    def get_bot_by_name(self, name: str) -> Optional[dict]:
        """
        Get a bot by its display name.

        Args:
            name: The bot's display name (case-insensitive search)

        Returns:
            Bot record if found, None otherwise
        """
        # Use contains for flexible matching
        result = self.get(f"bots?$filter=contains(name,'{name}')&$select=botid,name")
        bots = result.get("value", [])

        # Try exact match first
        for bot in bots:
            if bot.get("name", "").lower() == name.lower():
                return bot

        # Return first match if no exact match
        return bots[0] if bots else None

    def get_bot_components(self, bot_id: str) -> list[dict]:
        """
        Get components for a specific bot.

        Args:
            bot_id: The bot's unique identifier

        Returns:
            List of bot component records
        """
        result = self.get(f"botcomponents?$filter=_parentbotid_value eq {bot_id}")
        return result.get("value", [])

    def list_topics(
        self,
        bot_id: str,
        include_tools: bool = False,
        system_only: bool = False,
        custom_only: bool = False,
    ) -> list[dict]:
        """
        List topics for a specific bot.

        Args:
            bot_id: The bot's unique identifier
            include_tools: If False (default), filters out agent tools (InvokeConnectedAgentTaskAction)
            system_only: If True, only return system topics (ismanaged=true)
            custom_only: If True, only return custom topics (ismanaged=false)

        Returns:
            List of topic component records

        Note:
            Topic component types:
            - 0 = Topic (legacy)
            - 9 = Topic (V2)

            System vs Custom topics:
            - System topics (ismanaged=true): Built-in topics from managed solutions
            - Custom topics (ismanaged=false): User-created topics

            Tools are identified by schema name patterns:
            - Contains 'TaskAction' (API-created tools)
            - Contains '.action.' (UI-created tools)
            These are filtered out by default.
        """
        # Build filter
        filters = [
            f"_parentbotid_value eq {bot_id}",
            "(componenttype eq 0 or componenttype eq 9)"
        ]

        # Add managed status filter
        if system_only:
            filters.append("ismanaged eq true")
        elif custom_only:
            filters.append("ismanaged eq false")

        filter_str = " and ".join(filters)
        result = self.get(f"botcomponents?$filter={filter_str}&$orderby=name")
        if not result:
            return []
        topics = result.get("value", [])

        if not include_tools:
            # Filter out ALL tools using same detection as list_tools()
            # Tools have schema names containing 'TaskAction' or '.action.'
            def is_tool(component: dict) -> bool:
                schema = component.get("schemaname") or ""
                return "TaskAction" in schema or ".action." in schema

            topics = [t for t in topics if not is_tool(t)]

        return topics

    def list_tools(
        self,
        bot_id: str = None,
        category: str = None,
        connection_id: str = None,
        connection_reference_id: str = None
    ) -> list[dict]:
        """
        List tools, optionally filtered by bot and/or connection.

        Args:
            bot_id: Optional bot's unique identifier. If None, lists all tools across all agents.
            category: Optional filter by category ('agent', 'flow', 'prompt', 'connector', 'http')
            connection_id: Optional connection ID to filter connector tools by
            connection_reference_id: Optional connection reference ID to filter connector tools by

        Returns:
            List of tool component records

        Note:
            Tools are Topic (V2) components with schema names containing 'TaskAction'.
            Categories are determined by the TaskAction type:
            - Agent: InvokeConnectedAgentTaskAction
            - Flow: InvokeFlowTaskAction
            - Prompt: InvokePromptTaskAction
            - Connector: InvokeConnectorTaskAction
            - HTTP: InvokeHttpTaskAction
        """
        import yaml as yaml_lib

        # Build filter - always require componenttype eq 9 (Topic V2)
        if bot_id:
            if not self._is_guid(bot_id):
                raise ValueError(f"Invalid agent ID format: '{bot_id}'. Expected a full GUID (8-4-4-4-12 hex format, e.g. 12345678-1234-1234-1234-123456789abc).")
            filter_clause = f"_parentbotid_value eq {bot_id} and componenttype eq 9"
        else:
            filter_clause = "componenttype eq 9"

        result = self.get(
            f"botcomponents?$filter={filter_clause}&$orderby=name"
        )
        components = result.get("value", [])

        # Filter to only tools
        # Tools can be identified by:
        # 1. Schema name containing "TaskAction" (API-created tools)
        # 2. Schema name containing ".action." (UI-created tools)
        # 3. Data containing "kind: TaskDialog" (all tools)
        tools = []
        for t in components:
            schema_name = t.get("schemaname") or ""
            data = t.get("data") or ""
            if ("TaskAction" in schema_name or
                ".action." in schema_name or
                "kind: TaskDialog" in data):
                tools.append(t)

        # Apply category filter if specified
        if category:
            category_patterns = {
                "agent": "InvokeConnectedAgentTaskAction",
                "flow": "InvokeFlowTaskAction",
                "prompt": "InvokePromptTaskAction",
                "connector": "InvokeConnectorTaskAction",
                "http": "InvokeHttpTaskAction",
            }
            pattern = category_patterns.get(category.lower())
            if pattern:
                # Check both schema name and data field for the pattern
                tools = [
                    t for t in tools
                    if pattern in (t.get("schemaname") or "") or
                       pattern in (t.get("data") or "")
                ]

        # Apply connection filters if specified (only for connector tools)
        if connection_id or connection_reference_id:
            # First get connection references if filtering by connection_id
            conn_ref_ids = set()
            conn_ref_logical_names = set()
            if connection_id:
                conn_refs = self.list_connection_references(connection_id=connection_id)
                conn_ref_ids = {ref.get("connectionreferenceid") for ref in conn_refs}
                conn_ref_logical_names = {ref.get("connectionreferencelogicalname") for ref in conn_refs}

            # Add explicitly provided connection_reference_id
            if connection_reference_id:
                conn_ref_ids.add(connection_reference_id)

            # Match set includes both GUIDs and logical names
            conn_ref_match = conn_ref_ids | conn_ref_logical_names

            # Filter tools by connection reference
            filtered_tools = []
            for tool in tools:
                data = tool.get("data", "") or ""
                if not data:
                    continue

                try:
                    parsed_data = yaml_lib.safe_load(data)
                    if not parsed_data:
                        continue

                    # Check action.connectionReference field
                    action = parsed_data.get("action", {})
                    conn_ref = action.get("connectionReference", "")

                    if conn_ref:
                        # connectionReference can be:
                        # - logical name directly: pub_mymcp_0145_conn
                        # - dotted path: {bot_schema}.{connector_id}.{connection_ref_id}
                        if conn_ref in conn_ref_match:
                            filtered_tools.append(tool)
                        else:
                            parts = conn_ref.split(".")
                            if len(parts) >= 3:
                                tool_conn_ref_id = parts[-1]
                                if tool_conn_ref_id in conn_ref_match:
                                    filtered_tools.append(tool)
                except Exception:
                    # Skip tools with invalid YAML
                    continue

            tools = filtered_tools

        return tools

    def get_topic(self, component_id: str) -> dict:
        """
        Get a specific topic by component ID.

        Args:
            component_id: The topic component's unique identifier

        Returns:
            Topic component record
        """
        return self.get(f"botcomponents({component_id})")

    def get_tool(self, component_id: str) -> dict:
        """
        Get a specific tool by component ID.

        Tools are stored as botcomponents with componenttype 9 (Topic V2).
        This method fetches the component and validates it's a tool.

        Args:
            component_id: The tool component's unique identifier

        Returns:
            Tool component record with full details including data field

        Raises:
            Exception: If component is not found or is not a tool
        """
        component = self.get(f"botcomponents({component_id})")

        # Validate this is actually a tool
        schema_name = component.get("schemaname") or ""
        data = component.get("data") or ""

        is_tool = (
            "TaskAction" in schema_name or
            ".action." in schema_name or
            "kind: TaskDialog" in data
        )

        if not is_tool:
            raise Exception(f"Component {component_id} is not a tool (schema: {schema_name})")

        return component

    def set_topic_state(self, component_id: str, enabled: bool) -> None:
        """
        Enable or disable a topic.

        Args:
            component_id: The topic component's unique identifier
            enabled: True to enable (Active), False to disable (Inactive)

        Note:
            statecode values:
            - 0 = Active (enabled)
            - 1 = Inactive (disabled)
        """
        state_data = {
            "statecode": 0 if enabled else 1,
        }
        self.patch(f"botcomponents({component_id})", state_data)

    @staticmethod
    def validate_topic_yaml(content: str) -> tuple[bool, list[str]]:
        """
        Validate topic YAML content against Copilot Studio schema.

        Args:
            content: YAML string to validate

        Returns:
            Tuple of (is_valid, list_of_errors)

        Note:
            This performs basic schema validation to catch common errors
            before sending to Dataverse. It validates:
            - Root kind must be 'AdaptiveDialog'
            - Trigger kinds must be valid
            - Action kinds must be valid
        """
        import yaml

        errors = []

        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            return False, [f"Invalid YAML syntax: {e}"]

        if not isinstance(data, dict):
            return False, ["Topic YAML must be a dictionary/object at root level"]

        # Valid root kinds
        valid_root_kinds = {'AdaptiveDialog'}

        # Valid trigger kinds (beginDialog.kind)
        valid_trigger_kinds = {
            'OnRecognizedIntent',       # Intent-based triggering (most common)
            'OnUnknownIntent',          # Fallback for unrecognized intents
            'OnInvokeActivity',         # Teams invoke activities
            'OnConversationUpdateActivity',  # Conversation updates
            'OnEventActivity',          # Event-based triggering
            'OnDialogStart',            # Dialog start trigger
            'OnBeginDialog',            # Begin dialog trigger
            'OnEndOfConversationActivity',  # End of conversation
            'OnMessageReceived',        # Message received (generative)
            'OnPlanComplete',           # Plan completion (generative)
            'OnBeforeAIResponse',       # Before AI response (generative)
            'OnInactivity',             # User inactivity
        }

        # Valid action kinds
        valid_action_kinds = {
            'SendMessage',              # Send message to user
            'Question',                 # Ask a question
            'SetVariable',              # Set a variable value
            'ParseValue',               # Parse/convert a value
            'ClearVariable',            # Clear a variable
            'ConditionGroup',           # Conditional branching
            'SwitchCondition',          # Switch statement
            'RedirectToTopic',          # Redirect to another topic
            'EndDialog',                # End the current dialog
            'EndConversation',          # End the conversation
            'InvokeFlowAction',         # Call Power Automate flow
            'InvokeConnectorTaskAction',  # Call connector operation
            'InvokeHttpAction',         # Make HTTP request
            'InvokeAIBuilderAction',    # Call AI Builder model
            'SearchAndSummarizeContent',  # Generative answers
            'BeginDialog',              # Begin a dialog
            'RepeatDialog',             # Repeat current dialog
            'CancelDialog',             # Cancel dialog
            'EmitEvent',                # Emit an event
            'TraceActivity',            # Trace for debugging
            'LogAction',                # Log action
            'SendActivity',             # Send activity
            'UpdateActivity',           # Update activity
            'DeleteActivity',           # Delete activity
            'GetConversationMember',    # Get conversation member
            'SignOutUser',              # Sign out user
            'ChoiceInput',              # Choice input
            'ConfirmInput',             # Confirm input
            'DateTimeInput',            # DateTime input
            'NumberInput',              # Number input
            'TextInput',                # Text input
            'AttachmentInput',          # Attachment input
            'OAuthInput',               # OAuth input
            'ForEach',                  # For each loop
            'ForEachPage',              # For each page
            'BreakLoop',                # Break from loop
            'ContinueLoop',             # Continue in loop
            'ThrowException',           # Throw exception
            'GenerativeAnswer',         # Generative answer node
            'AdaptiveCardAction',       # Adaptive card action
        }

        # Check root kind
        root_kind = data.get('kind')
        if root_kind not in valid_root_kinds:
            errors.append(
                f"Invalid root kind '{root_kind}'. "
                f"Must be one of: {', '.join(sorted(valid_root_kinds))}"
            )

        # Check beginDialog
        begin_dialog = data.get('beginDialog', {})
        if isinstance(begin_dialog, dict):
            trigger_kind = begin_dialog.get('kind')
            if trigger_kind and trigger_kind not in valid_trigger_kinds:
                errors.append(
                    f"Invalid trigger kind '{trigger_kind}' in beginDialog. "
                    f"Valid trigger kinds include: OnRecognizedIntent, OnUnknownIntent, "
                    f"OnEventActivity, OnConversationUpdateActivity, OnDialogStart, "
                    f"OnMessageReceived, OnPlanComplete, OnBeforeAIResponse, OnInactivity"
                )

            # Check actions
            actions = begin_dialog.get('actions', [])
            if isinstance(actions, list):
                for i, action in enumerate(actions):
                    if isinstance(action, dict):
                        action_kind = action.get('kind')
                        if action_kind and action_kind not in valid_action_kinds:
                            errors.append(
                                f"Invalid action kind '{action_kind}' at actions[{i}]. "
                                f"Common action kinds: SendMessage, Question, SetVariable, "
                                f"ConditionGroup, RedirectToTopic, EndDialog, InvokeFlowAction"
                            )

                        # Recursively check nested actions in conditions
                        if action_kind == 'ConditionGroup':
                            for cond in action.get('conditions', []):
                                if isinstance(cond, dict):
                                    for nested_action in cond.get('actions', []):
                                        if isinstance(nested_action, dict):
                                            nested_kind = nested_action.get('kind')
                                            if nested_kind and nested_kind not in valid_action_kinds:
                                                errors.append(
                                                    f"Invalid action kind '{nested_kind}' in condition. "
                                                    f"Common action kinds: SendMessage, Question, SetVariable"
                                                )
                            for else_action in action.get('elseActions', []):
                                if isinstance(else_action, dict):
                                    else_kind = else_action.get('kind')
                                    if else_kind and else_kind not in valid_action_kinds:
                                        errors.append(
                                            f"Invalid action kind '{else_kind}' in elseActions. "
                                            f"Common action kinds: SendMessage, Question, SetVariable"
                                        )

        return len(errors) == 0, errors

    def create_topic(
        self,
        bot_id: str,
        name: str,
        content: str,
        description: Optional[str] = None,
        language: int = 1033,
    ) -> str:
        """
        Create a new topic for a bot.

        Args:
            bot_id: The bot's unique identifier
            name: Display name for the topic
            content: YAML content defining the topic's conversation flow
            description: Optional description for the topic
            language: Language code (default: 1033 for English)

        Returns:
            The created component ID

        Note:
            Topic content must be valid AdaptiveDialog YAML format.
            Use generate_simple_topic_yaml() to create basic topic content.

            Component types:
            - 0 = Topic (legacy)
            - 9 = Topic (V2) - used for new topics

        Raises:
            ValueError: If the topic YAML content is invalid
        """
        # Validate topic YAML before creating
        is_valid, errors = self.validate_topic_yaml(content)
        if not is_valid:
            error_msg = "Invalid topic YAML:\n" + "\n".join(f"  - {e}" for e in errors)
            raise ValueError(error_msg)

        # Get bot schema name for generating component schema name
        bot = self.get_bot(bot_id)
        bot_schema = bot.get("schemaname") or f"{self._get_publisher_prefix()}_bot{bot_id[:8]}"

        # Generate schema name from display name
        clean_name = re.sub(r'[^a-zA-Z0-9]', '', name)
        schema_name = f"{bot_schema}.topic.{clean_name}"

        component_data = {
            "componenttype": 9,  # Topic (V2)
            "name": name,
            "schemaname": schema_name,
            "data": content,  # Topic YAML content is stored in 'data' field
            "language": language,
            "parentbotid@odata.bind": f"/bots({bot_id})"
        }

        if description:
            component_data["description"] = description

        # Use longer timeout for topic creation
        url = f"{self.api_url}/botcomponents"
        headers = self._get_headers()
        response = self._http_client.post(url, headers=headers, json=component_data, timeout=120.0)
        response.raise_for_status()

        # Extract component ID from OData-EntityId header
        entity_id = response.headers.get("OData-EntityId", "")
        if entity_id:
            match = re.search(r'botcomponents\(([^)]+)\)', entity_id)
            if match:
                return match.group(1)
        return ""

    def update_topic(
        self,
        component_id: str,
        name: Optional[str] = None,
        content: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None:
        """
        Update an existing topic.

        Args:
            component_id: The topic component's unique identifier
            name: New display name for the topic
            content: New YAML content for the topic
            description: New description for the topic

        Raises:
            ClientError: If no updates provided or update fails
            ValueError: If the topic YAML content is invalid
        """
        # Validate content if provided
        if content is not None:
            is_valid, errors = self.validate_topic_yaml(content)
            if not is_valid:
                error_msg = "Invalid topic YAML:\n" + "\n".join(f"  - {e}" for e in errors)
                raise ValueError(error_msg)

        data = {}

        if name is not None:
            data["name"] = name
        if content is not None:
            data["data"] = content  # Topic YAML content is stored in 'data' field
        if description is not None:
            data["description"] = description

        if not data:
            raise ClientError("No updates provided. Specify at least one field to update.")

        self.patch(f"botcomponents({component_id})", data)

    def delete_topic(self, component_id: str) -> None:
        """
        Delete a topic from a bot.

        Args:
            component_id: The topic component's unique identifier

        Note:
            System topics (ismanaged=true) cannot be deleted.
            Only custom topics (ismanaged=false) can be deleted.
        """
        self.delete(f"botcomponents({component_id})")

    # =========================================================================
    # Trigger Methods (External Triggers - componenttype=17)
    # =========================================================================

    def list_triggers(self, bot_id: str) -> list[dict]:
        """
        List external triggers for a specific bot.

        Args:
            bot_id: The bot's unique identifier

        Returns:
            List of trigger component records

        Note:
            External triggers (componenttype=17) are event-based triggers that
            invoke the agent without user input (e.g., email arrival, scheduled,
            Dataverse row changes).
        """
        filter_str = f"_parentbotid_value eq {bot_id} and componenttype eq 17"
        result = self.get(f"botcomponents?$filter={filter_str}&$orderby=name")
        if not result:
            return []
        return result.get("value", [])

    def get_trigger(self, trigger_id: str) -> dict:
        """
        Get a specific trigger by component ID.

        Args:
            trigger_id: The trigger component's unique identifier

        Returns:
            Trigger component record
        """
        return self.get(f"botcomponents({trigger_id})")

    def get_trigger_workflow(self, trigger_id: str) -> Optional[dict]:
        """
        Get the underlying workflow for a trigger.

        External triggers reference a Power Automate flow that contains
        the actual trigger definition. This method extracts the flowId
        from the trigger's data field and retrieves the workflow.

        Args:
            trigger_id: The trigger component's unique identifier

        Returns:
            Workflow record, or None if not found
        """
        import yaml as yaml_lib

        trigger = self.get_trigger(trigger_id)
        data = trigger.get("data", "")
        if not data:
            return None

        try:
            parsed = yaml_lib.safe_load(data)
            flow_id = parsed.get("externalTriggerSource", {}).get("flowId")
            if not flow_id:
                return None
            return self.get(f"workflows({flow_id})")
        except Exception:
            return None

    def set_trigger_state(self, trigger_id: str, enabled: bool) -> None:
        """
        Enable or disable a trigger.

        Args:
            trigger_id: The trigger component's unique identifier
            enabled: True to enable, False to disable
        """
        state = 0 if enabled else 1  # 0=Active, 1=Inactive
        status = 1 if enabled else 2  # 1=Active, 2=Inactive
        self.patch(
            f"botcomponents({trigger_id})",
            {"statecode": state, "statuscode": status}
        )

    def delete_trigger(self, trigger_id: str, delete_workflow: bool = True) -> None:
        """
        Delete a trigger from a bot.

        Args:
            trigger_id: The trigger component's unique identifier
            delete_workflow: If True, also delete the underlying workflow

        Note:
            By default, this also deletes the underlying Power Automate flow
            that powers the trigger. Set delete_workflow=False to keep it.
        """
        if delete_workflow:
            # Get the workflow ID before deleting the trigger
            workflow = self.get_trigger_workflow(trigger_id)
            if workflow:
                workflow_id = workflow.get("workflowid")
                if workflow_id:
                    try:
                        self.delete(f"workflows({workflow_id})")
                    except Exception:
                        # Workflow may already be deleted or inaccessible
                        pass

        self.delete(f"botcomponents({trigger_id})")

    @staticmethod
    def generate_simple_topic_yaml(
        display_name: str,
        trigger_phrases: list[str],
        message: str,
    ) -> str:
        """
        Generate basic topic YAML from simple inputs.

        Args:
            display_name: Display name shown in topic list
            trigger_phrases: List of phrases that trigger this topic
            message: Response message to show when topic is triggered

        Returns:
            YAML string for a simple message-response topic

        Example:
            yaml = DataverseClient.generate_simple_topic_yaml(
                display_name="Greeting",
                trigger_phrases=["hello", "hi", "hey there"],
                message="Hello! How can I help you today?"
            )
        """
        import uuid

        # Generate unique IDs for nodes
        msg_id = f"sendMessage_{uuid.uuid4().hex[:8]}"

        # Build trigger phrases YAML
        triggers_yaml = "\n".join(f"      - {phrase}" for phrase in trigger_phrases)

        return f"""kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: {display_name}
    triggerQueries:
{triggers_yaml}

  actions:
    - kind: SendMessage
      id: {msg_id}
      message: {message}
"""

    @staticmethod
    def generate_question_topic_yaml(
        display_name: str,
        trigger_phrases: list[str],
        question_prompt: str,
        variable_name: str,
        confirmation_message: str,
        entity_type: str = "StringPrebuiltEntity",
    ) -> str:
        """
        Generate topic YAML with a question node.

        Args:
            display_name: Display name shown in topic list
            trigger_phrases: List of phrases that trigger this topic
            question_prompt: The question to ask the user
            variable_name: Name for the variable to store the answer
            confirmation_message: Message shown after user answers
            entity_type: Entity type for validation (default: StringPrebuiltEntity)

        Returns:
            YAML string for a question-response topic

        Entity Types:
            - StringPrebuiltEntity: Free text input
            - BooleanPrebuiltEntity: Yes/No response
            - NumberPrebuiltEntity: Numeric input
            - DateTimePrebuiltEntity: Date/time input
            - EmailPrebuiltEntity: Email address
            - PersonNamePrebuiltEntity: Person's name
            - StatePrebuiltEntity: US state
            - CityPrebuiltEntity: City name
            - PhoneNumberPrebuiltEntity: Phone number
        """
        import uuid

        # Generate unique IDs for nodes
        question_id = f"question_{uuid.uuid4().hex[:8]}"
        msg_id = f"sendMessage_{uuid.uuid4().hex[:8]}"

        # Build trigger phrases YAML
        triggers_yaml = "\n".join(f"      - {phrase}" for phrase in trigger_phrases)

        return f"""kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: {display_name}
    triggerQueries:
{triggers_yaml}

  actions:
    - kind: Question
      id: {question_id}
      alwaysPrompt: false
      variable: init:Topic.{variable_name}
      prompt: {question_prompt}
      entity: {entity_type}

    - kind: SendMessage
      id: {msg_id}
      message: {confirmation_message}
"""

    def delete_bot(self, bot_id: str) -> None:
        """
        Delete a bot by ID.

        Args:
            bot_id: The bot's unique identifier
        """
        self.delete(f"bots({bot_id})")

    def publish_bot(self, bot_id: str, poll_timeout: float = 180.0, poll_interval: float = 3.0) -> dict:
        """
        Publish a Copilot Studio agent and verify the publish actually completed.

        Triggers the PvaPublish action and then polls the bot's
        synchronizationstatus.lastFinishedPublishOperation until the operation
        advances past its pre-publish baseline. Raises ClientError with full
        diagnostic details if the server-side job fails, if PvaPublish returns
        an empty payload (no job queued), or if the job does not complete
        within poll_timeout.

        Args:
            bot_id: The bot's unique identifier
            poll_timeout: Maximum seconds to wait for publish job completion
            poll_interval: Seconds between status polls

        Returns:
            dict containing:
                - status: "success"
                - PublishedBotContentId: ID of the published content
                - publishedon: New publishedon timestamp from Dataverse
                - operationEnd: When the publish job finished

        Raises:
            ClientError: If PvaPublish returns an error response, if the
                response payload is empty (publish rejected), if the async
                publish job fails with a diagnostic error, or if the job
                does not complete within poll_timeout.
        """
        baseline_operation_end, _ = self._read_publish_sync_state(bot_id)

        url = f"{self.api_url}/bots({bot_id})/Microsoft.Dynamics.CRM.PvaPublish"
        headers = self._get_headers()

        try:
            response = self._http_client.post(url, headers=headers, json={}, timeout=120.0)
            response.raise_for_status()
            result = response.json()
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                if "error" in error_body:
                    error_detail = error_body["error"].get("message", str(error_body))
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to publish agent: HTTP {e.response.status_code}: {error_detail}")

        published_content_id = result.get("PublishedBotContentId") or ""

        # PvaPublish queues an async publish job and may return immediately with an
        # empty payload. The REAL status lives in
        # synchronizationstatus.lastFinishedPublishOperation, which we poll below.
        # Do NOT treat the inline response alone as success or failure.
        deadline = time.monotonic() + poll_timeout
        last_seen_operation_end = baseline_operation_end
        last_sync = None

        while time.monotonic() < deadline:
            time.sleep(poll_interval)
            operation_end, sync = self._read_publish_sync_state(bot_id)
            last_sync = sync
            last_seen_operation_end = operation_end
            if operation_end and operation_end != baseline_operation_end:
                break
        else:
            raise ClientError(
                f"Publish job did not complete within {poll_timeout:.0f}s. "
                f"Baseline operationEnd={baseline_operation_end!r}, "
                f"last observed operationEnd={last_seen_operation_end!r}. "
                f"The publish may still be running server-side; re-check with "
                f"`copilot agent get {bot_id}` after a minute."
            )

        lfpo = (last_sync or {}).get("lastFinishedPublishOperation") or {}
        status = lfpo.get("status")

        if status != "Succeeded":
            diag_messages = []
            for dd in lfpo.get("diagnosticDetails") or []:
                component_id = dd.get("componentId", "?")
                for d in dd.get("diagnosticList") or []:
                    diag_messages.append(
                        f"component {component_id}: {d.get('errorMessage', 'unknown error')}"
                    )
            diag_str = "; ".join(diag_messages) if diag_messages else "no diagnostic details returned"
            raise ClientError(
                f"Publish job finished with status '{status}'. Errors: {diag_str}"
            )

        # Fetch the updated publishedon so callers can confirm it advanced.
        post_bot = self.get(f"bots({bot_id})?$select=publishedon")
        return {
            "status": "success",
            "PublishedBotContentId": published_content_id,
            "publishedon": post_bot.get("publishedon"),
            "operationEnd": lfpo.get("operationEnd"),
        }

    def _read_publish_sync_state(self, bot_id: str) -> tuple[Optional[str], Optional[dict]]:
        """
        Read the bot's synchronizationstatus and extract the current
        lastFinishedPublishOperation.operationEnd timestamp.

        synchronizationstatus is sometimes returned as a JSON-encoded string and
        sometimes as a parsed object depending on the query, so this helper
        normalizes both forms.

        Returns:
            (operation_end_iso_string_or_None, parsed_sync_dict_or_None)
        """
        bot = self.get(f"bots({bot_id})?$select=synchronizationstatus")
        raw = bot.get("synchronizationstatus")
        if raw is None:
            return None, None
        if isinstance(raw, str):
            try:
                sync = json.loads(raw)
            except (ValueError, TypeError):
                return None, None
        else:
            sync = raw
        lfpo = sync.get("lastFinishedPublishOperation") or {}
        return lfpo.get("operationEnd"), sync

    def create_bot(
        self,
        name: str,
        schema_name: Optional[str] = None,
        language: int = 1033,
        instructions: Optional[str] = None,
        description: Optional[str] = None,
        orchestration: bool = True,
        auth_mode: int = 2,
        auth_trigger: int = 1,
    ) -> dict:
        """
        Create a new Copilot Studio agent (bot).

        Args:
            name: Display name for the agent
            schema_name: Internal schema name (auto-generated from name if not provided)
            language: Language code (default: 1033 for English)
            instructions: Optional system instructions for the agent
            description: Optional description for the agent
            orchestration: Enable generative AI orchestration (default: True)
            auth_mode: Authentication mode (1=None, 2=Integrated, 3=Custom Azure AD)
            auth_trigger: Authentication trigger (0=As Needed, 1=Always)

        Returns:
            Created bot record

        Note:
            Model selection and web search must be configured via the Copilot Studio portal UI.
            The API does not support these settings.
        """
        # Publisher prefix required by Dataverse for custom entities
        publisher_prefix = f"{self._get_publisher_prefix()}_"

        # Generate schema name from display name if not provided
        if not schema_name:
            # Convert to camelCase and remove special characters
            clean_name = re.sub(r'[^a-zA-Z0-9\s]', '', name)
            words = clean_name.split()
            schema_name = words[0].lower() + ''.join(w.capitalize() for w in words[1:])

        # Add publisher prefix if not already present
        if not schema_name.startswith(publisher_prefix):
            schema_name = publisher_prefix + schema_name

        # Build configuration JSON
        config = {
            "$kind": "BotConfiguration",
            "settings": {
                "GenerativeActionsEnabled": orchestration
            },
            "isAgentConnectable": True,
            "gPTSettings": {
                "$kind": "GPTSettings",
                "defaultSchemaName": f"{schema_name}.gpt.default"
            },
            "aISettings": {
                "$kind": "AISettings",
                "useModelKnowledge": True,
                "isFileAnalysisEnabled": True,
                "isSemanticSearchEnabled": True,
                "contentModeration": "High",
                "optInUseLatestModels": True
            },
            "recognizer": {
                "$kind": "GenerativeAIRecognizer"
            }
        }

        # Add instructions if provided
        if instructions:
            config["gPTSettings"]["systemPrompt"] = instructions

        # Add description if provided
        if description:
            config["description"] = description

        bot_data = {
            "name": name,
            "schemaname": schema_name,
            "language": language,
            "runtimeprovider": 0,  # Power Virtual Agents
            "accesscontrolpolicy": 1,  # Copilot readers
            "authenticationmode": auth_mode,
            "authenticationtrigger": auth_trigger,
            "template": "default-2.1.0",
            "configuration": json.dumps(config, indent=2),
        }

        result = self.post("bots", bot_data, return_id=True)

        # Delete all default topics created by the template
        bot_id = None
        if result:
            # Result can be full response or just {"id": "..."} from 204 response
            bot_id = result.get("botid") or result.get("id")

        if bot_id:
            # Wait for topics to be provisioned - can take several seconds
            import time

            # Poll until topics appear (max 30 seconds)
            for _ in range(15):
                time.sleep(2)
                topics = self.list_topics(bot_id)
                if len(topics) >= 10:  # Expect ~13 default topics
                    break

            self.delete_all_topics(bot_id)

        return result

    def delete_all_topics(self, bot_id: str) -> int:
        """
        Delete all topics for a bot.

        Args:
            bot_id: The bot's unique identifier

        Returns:
            Number of topics deleted
        """
        topics = self.list_topics(bot_id)
        deleted_count = 0
        for topic in topics:
            component_id = topic.get("botcomponentid")
            if component_id:
                try:
                    self.delete_topic(component_id)
                    deleted_count += 1
                except Exception:
                    # Some topics may fail to delete (e.g., if referenced)
                    pass
        return deleted_count

    def update_bot(
        self,
        bot_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        orchestration: Optional[bool] = None,
        content_moderation: Optional[str] = None,
    ) -> None:
        """
        Update an existing Copilot Studio agent (bot) metadata.

        Args:
            bot_id: The bot's unique identifier
            name: New display name for the agent
            description: New description for the agent
            orchestration: Enable/disable generative AI orchestration
            content_moderation: Content moderation level (Low, Moderate, High)

        Note:
            Instructions must be updated via update_gpt_instructions() which uses
            the botcomponent API. Model selection must use model_set command.
        """
        # Get current bot to preserve existing configuration
        current_bot = self.get_bot(bot_id)
        current_config = json.loads(current_bot.get("configuration", "{}"))

        bot_data = {}

        # Update name if provided
        if name is not None:
            bot_data["name"] = name

        # Update configuration fields if any are provided
        config_changed = False

        if orchestration is not None:
            if "settings" not in current_config:
                current_config["settings"] = {}
            current_config["settings"]["GenerativeActionsEnabled"] = orchestration
            config_changed = True

        if description is not None:
            current_config["description"] = description
            config_changed = True

        if content_moderation is not None:
            if "aISettings" not in current_config:
                current_config["aISettings"] = {"$kind": "AISettings"}
            current_config["aISettings"]["contentModeration"] = content_moderation
            config_changed = True

        if config_changed:
            bot_data["configuration"] = json.dumps(current_config, indent=2)

        if not bot_data:
            raise ClientError("No updates provided. Specify at least one field to update.")

        self.patch(f"bots({bot_id})", bot_data)

    def get_bot_runtime_model(self, bot: Union[str, dict]) -> dict[str, Any]:
        """
        Get the runtime AI model configuration stored on the bot record.

        Args:
            bot: Bot GUID or full bot record

        Returns:
            Dict containing:
                - model_kind: Runtime model kind
                - model_hint: Runtime model hint
                - opt_in_use_latest_models: Whether latest-model opt-in is enabled
        """
        if isinstance(bot, str):
            bot = self.get_bot(bot)

        configuration = bot.get("configuration", "{}")
        if isinstance(configuration, str):
            try:
                configuration = json.loads(configuration)
            except json.JSONDecodeError:
                configuration = {}

        ai_settings = configuration.get("aISettings", {})
        model = ai_settings.get("model", {})

        return {
            "model_kind": model.get("kind"),
            "model_hint": model.get("modelNameHint"),
            "opt_in_use_latest_models": ai_settings.get("optInUseLatestModels"),
        }

    def update_bot_model(
        self,
        bot_id: str,
        model_kind: str,
        model_hint: str,
        opt_in_use_latest_models: bool = False,
    ) -> bool:
        """
        Update the runtime AI model configuration stored on the bot record.

        Copilot Studio stores model information in two places:
        1. The bot configuration (runtime source of truth)
        2. The Custom GPT component YAML (UI/editor representation)

        This method updates the runtime bot configuration only. Callers that want
        full consistency should also update the Custom GPT component.

        Returns:
            True when the bot configuration changed, otherwise False.
        """
        current_bot = self.get_bot(bot_id)
        configuration = current_bot.get("configuration", "{}")

        if isinstance(configuration, str):
            try:
                current_config = json.loads(configuration)
            except json.JSONDecodeError:
                current_config = {}
        else:
            current_config = configuration

        if "aISettings" not in current_config or not isinstance(current_config["aISettings"], dict):
            current_config["aISettings"] = {"$kind": "AISettings"}

        ai_settings = current_config["aISettings"]
        ai_settings.setdefault("$kind", "AISettings")

        current_runtime = self.get_bot_runtime_model(current_bot)
        if (
            current_runtime.get("model_kind") == model_kind
            and current_runtime.get("model_hint") == model_hint
            and current_runtime.get("opt_in_use_latest_models") == opt_in_use_latest_models
        ):
            return False

        ai_settings["optInUseLatestModels"] = opt_in_use_latest_models
        ai_settings["model"] = {
            "$kind": "CurrentModels",
            "kind": model_kind,
            "modelNameHint": model_hint,
        }

        self.patch(
            f"bots({bot_id})",
            {"configuration": json.dumps(current_config, indent=2)},
        )
        return True

    # =========================================================================
    # Custom GPT Component Methods (Model & Instructions via botcomponent)
    # =========================================================================

    def get_custom_gpt_component(self, bot_id: str) -> Optional[dict]:
        """
        Get the Custom GPT botcomponent (componenttype=15) for an agent.

        This component contains the actual AI configuration (model and instructions)
        in its 'data' field as YAML with structure:
            kind: GptComponentMetadata
            instructions: <system instructions>
            aISettings:
              model:
                kind: <MODEL_KIND>
                modelNameHint: <MODEL_HINT>
            tools:

        Args:
            bot_id: The bot's unique identifier (GUID)

        Returns:
            The Custom GPT component dict if found, None otherwise.
            Contains: botcomponentid, name, data, schemaname
        """
        result = self.get(
            f"botcomponents?$filter=_parentbotid_value eq {bot_id} and componenttype eq 15"
            "&$select=botcomponentid,name,data,schemaname"
        )
        components = result.get("value", [])
        return components[0] if components else None

    def parse_gpt_component_yaml(self, yaml_data: str) -> dict:
        """
        Parse the Custom GPT component YAML data.

        Args:
            yaml_data: The YAML string from botcomponent.data

        Returns:
            Dict with parsed fields: instructions, model_kind, model_hint
        """
        import yaml as yaml_lib

        result = {
            "instructions": None,
            "response_instructions": None,
            "model_kind": None,
            "model_hint": None,
            "web_browsing": None,
        }
        if not yaml_data:
            return result

        try:
            parsed = yaml_lib.safe_load(yaml_data)
            if parsed and isinstance(parsed, dict):
                result["instructions"] = parsed.get("instructions")
                result["response_instructions"] = parsed.get("responseInstructions")
                ai_settings = parsed.get("aISettings", {})
                model = ai_settings.get("model", {})
                result["model_kind"] = model.get("kind")
                result["model_hint"] = model.get("modelNameHint")
                result["web_browsing"] = parsed.get("webBrowsing")
        except Exception:
            # Fallback: parse with regex for robustness
            import re

            instr_match = re.search(r'instructions:\s*(.+?)(?:\n(?=\w)|$)', yaml_data, re.DOTALL)
            resp_instr_match = re.search(r'responseInstructions:\s*(.+?)(?:\n(?=\w)|$)', yaml_data, re.DOTALL)
            kind_match = re.search(r'kind:\s*(\S+)', yaml_data)
            hint_match = re.search(r'modelNameHint:\s*(\S+)', yaml_data)
            web_match = re.search(r'webBrowsing:\s*(true|false)', yaml_data, re.IGNORECASE)

            if instr_match:
                result["instructions"] = instr_match.group(1).strip()
            if resp_instr_match:
                result["response_instructions"] = resp_instr_match.group(1).strip()
            if kind_match:
                result["model_kind"] = kind_match.group(1)
            if hint_match:
                result["model_hint"] = hint_match.group(1)
            if web_match:
                result["web_browsing"] = web_match.group(1).lower() == "true"

        return result

    def build_gpt_component_yaml(
        self,
        instructions: Optional[str] = None,
        response_instructions: Optional[str] = None,
        model_kind: Optional[str] = None,
        model_hint: Optional[str] = None,
        web_browsing: Optional[bool] = None,
    ) -> str:
        """
        Build YAML data for the Custom GPT component.

        Args:
            instructions: System instructions/prompt (can be multiline)
            response_instructions: Response formatting instructions (can be multiline)
            model_kind: Model kind (DefaultModels, ChatPreviewModels, etc.)
            model_hint: Model name hint (GPT4o, GPT5Reasoning, etc.)
            web_browsing: Enable/disable web browsing (Bing search) capability

        Returns:
            YAML string for botcomponent.data field
        """
        import yaml as yaml_lib

        # Custom representer to force literal block scalar style for multiline strings
        # This avoids the escaped double-quoted style (with \ line continuations)
        # that Copilot Studio UI doesn't parse correctly
        class LiteralStr(str):
            pass

        def literal_str_representer(dumper, data):
            return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')

        yaml_lib.add_representer(LiteralStr, literal_str_representer)

        data = {"kind": "GptComponentMetadata"}

        if instructions:
            data["instructions"] = LiteralStr(instructions)

        if response_instructions:
            data["responseInstructions"] = LiteralStr(response_instructions)

        # `instructions` and `responseInstructions` are TemplateLine fields. The
        # Copilot Studio publish step parses TemplateLine values as a template
        # whose default format is Power Fx (per TemplateEngineOptions.format).
        # In a Power Fx template, `{ ... }` delimits a record/expression literal
        # — so a bare `{` in the text triggers expression parsing, and quoted
        # JSON keys like `"summary_markdown"` fail because Power Fx record
        # literals require unquoted keys. Symptom on publish:
        #
        #     Unexpected character in expression '
        #       "summary_markdown": "..."
        #
        # When the content contains a literal `{`, switch the template format
        # to Mustache. Mustache uses `{{ ... }}` (double braces) to delimit
        # expressions, so a single `{` is plain literal text — no escaping or
        # quote-doubling required, and the multi-line content round-trips as
        # a YAML literal block scalar. Setting `template.format: Mustache` is
        # the per-component opt-in defined by the Copilot Studio botcomponent
        # schema (foundry.schema.yaml.cli.json: TemplateFormat oneOf
        # {PowerFxOptionalKind, Mustache}).
        if (instructions and _needs_mustache_template_format(instructions)) or (
            response_instructions
            and _needs_mustache_template_format(response_instructions)
        ):
            data["template"] = {
                "kind": "TemplateEngineOptions",
                "format": "Mustache",
            }

        # Emit aISettings.model using the CurrentModelsNoKind variant
        # (modelNameHint only, no `kind:` field).
        #
        # The Copilot Studio YAML schema's AgentModelType is a oneOf over
        # {CustomModels, CurrentModels, CurrentModelsNoKind, PreviewModels,
        #  ExperimentalModels, TurboProductionModels, TurboPreviewModels,
        #  TurboExperimentalModels, ReasoningProductionModels,
        #  ReasoningPreviewModels, ReasoningExperimentalModels,
        #  DeferredUpdateModels}. The legacy kinds this CLI used to emit
        # (`DefaultModels`, `ChatPreviewModels`) are NOT in that union —
        # emitting them fails PvaPublish with "Node is unknown to the system".
        # Microsoft's official template (microsoft/skills-for-copilot-studio
        # templates/agents/agent.mcs.yml) uses the kindless variant, which is
        # what we match here. The `model_kind` parameter is accepted for
        # backward compatibility with callers but is intentionally ignored.
        if model_hint:
            data["aISettings"] = {
                "model": {
                    "modelNameHint": model_hint,
                }
            }

        if web_browsing is not None:
            data["webBrowsing"] = web_browsing

        # Use yaml library to properly handle multiline strings
        yaml_output = yaml_lib.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)

        return yaml_output

    def create_custom_gpt_component(
        self,
        bot_id: str,
        instructions: Optional[str] = None,
        response_instructions: Optional[str] = None,
        model_kind: Optional[str] = None,
        model_hint: Optional[str] = None,
        web_browsing: Optional[bool] = None,
    ) -> str:
        """
        Create a Custom GPT botcomponent (componenttype=15) for an agent.

        This component stores the AI configuration (model and instructions)
        in its 'data' field as YAML.

        Args:
            bot_id: The bot's unique identifier
            instructions: Optional system instructions/prompt
            response_instructions: Optional response formatting instructions
            model_kind: Optional model kind (DefaultModels, PreviewModels, etc.)
            model_hint: Optional model name hint (GPT4o, GPT5Reasoning, etc.)
            web_browsing: Optional enable/disable web browsing capability

        Returns:
            The created component ID

        Raises:
            ClientError: If component already exists or creation fails
        """
        # Check if component already exists
        existing = self.get_custom_gpt_component(bot_id)
        if existing:
            raise ClientError(f"Custom GPT component already exists for agent {bot_id}")

        # Get bot schema name for generating component schema name
        bot = self.get_bot(bot_id)
        bot_schema = bot.get("schemaname") or f"{self._get_publisher_prefix()}_bot{bot_id[:8]}"
        schema_name = f"{bot_schema}.gpt.default"

        # Build the YAML data
        yaml_data = self.build_gpt_component_yaml(
            instructions=instructions,
            response_instructions=response_instructions,
            model_kind=model_kind,
            model_hint=model_hint,
            web_browsing=web_browsing,
        )

        component_data = {
            "componenttype": 15,  # Custom GPT
            "name": "Custom GPT",
            "schemaname": schema_name,
            "data": yaml_data,
            "parentbotid@odata.bind": f"/bots({bot_id})"
        }

        # POST to create the component
        url = f"{self.api_url}/botcomponents"
        headers = self._get_headers()
        response = self._http_client.post(url, headers=headers, json=component_data, timeout=120.0)
        response.raise_for_status()

        # Extract component ID from OData-EntityId header
        entity_id = response.headers.get("OData-EntityId", "")
        if entity_id:
            match = re.search(r'botcomponents\(([^)]+)\)', entity_id)
            if match:
                return match.group(1)
        return ""

    def update_gpt_instructions(self, bot_id: str, instructions: str) -> None:
        """
        Update the system instructions for an agent.

        Updates instructions in BOTH locations:
        1. The bot's configuration.gPTSettings.systemPrompt (used at runtime)
        2. The Custom GPT botcomponent data YAML (for consistency)

        This preserves existing model settings while updating only the instructions.
        If the Custom GPT component doesn't exist, it will be created automatically.

        Args:
            bot_id: The bot's unique identifier
            instructions: New system instructions/prompt

        Raises:
            ClientError: If update fails
        """
        # 1. Update the bot's configuration.gPTSettings.systemPrompt (PRIMARY - used at runtime)
        current_bot = self.get(f"bots({bot_id})?$select=configuration")
        current_config = json.loads(current_bot.get("configuration", "{}"))

        # Ensure gPTSettings exists
        if "gPTSettings" not in current_config:
            current_config["gPTSettings"] = {"$kind": "GPTSettings"}

        current_config["gPTSettings"]["systemPrompt"] = instructions

        # PATCH the bot's configuration
        self.patch(f"bots({bot_id})", {"configuration": json.dumps(current_config, indent=2)})

        # 2. Update the Custom GPT botcomponent (SECONDARY - for consistency)
        gpt_component = self.get_custom_gpt_component(bot_id)
        if not gpt_component:
            # Create the component with the instructions
            self.create_custom_gpt_component(bot_id, instructions=instructions)
            return

        component_id = gpt_component.get("botcomponentid")
        current_yaml = gpt_component.get("data", "")

        # Parse existing settings to preserve model config
        yaml_config = self.parse_gpt_component_yaml(current_yaml)

        # Build new YAML with updated instructions but preserved model, web browsing, and response instructions
        new_yaml = self.build_gpt_component_yaml(
            instructions=instructions,
            response_instructions=yaml_config.get("response_instructions"),
            model_kind=yaml_config.get("model_kind"),
            model_hint=yaml_config.get("model_hint"),
            web_browsing=yaml_config.get("web_browsing"),
        )

        # PATCH the botcomponent
        self.patch(f"botcomponents({component_id})", {"data": new_yaml})

    def get_gpt_instructions(self, bot_id: str) -> Optional[str]:
        """
        Get the current system instructions for an agent.

        Args:
            bot_id: The bot's unique identifier

        Returns:
            The current instructions, or None if not set
        """
        gpt_component = self.get_custom_gpt_component(bot_id)
        if not gpt_component:
            return None

        current_yaml = gpt_component.get("data", "")
        config = self.parse_gpt_component_yaml(current_yaml)
        return config.get("instructions")

    def get_response_instructions(self, bot_id: str) -> Optional[str]:
        """
        Get the current response formatting instructions for an agent.

        Args:
            bot_id: The bot's unique identifier

        Returns:
            The current response instructions, or None if not set
        """
        gpt_component = self.get_custom_gpt_component(bot_id)
        if not gpt_component:
            return None

        current_yaml = gpt_component.get("data", "")
        config = self.parse_gpt_component_yaml(current_yaml)
        return config.get("response_instructions")

    def update_response_instructions(self, bot_id: str, response_instructions: str) -> None:
        """
        Update the response formatting instructions for an agent.

        Updates the responseInstructions field in the Custom GPT botcomponent YAML.
        Preserves existing instructions, model settings, and web browsing.

        Args:
            bot_id: The bot's unique identifier
            response_instructions: New response formatting instructions

        Raises:
            ClientError: If update fails
        """
        gpt_component = self.get_custom_gpt_component(bot_id)
        if not gpt_component:
            # Create the component with response instructions
            self.create_custom_gpt_component(bot_id, response_instructions=response_instructions)
            return

        component_id = gpt_component.get("botcomponentid")
        current_yaml = gpt_component.get("data", "")

        # Parse existing settings to preserve everything else
        yaml_config = self.parse_gpt_component_yaml(current_yaml)

        # Build new YAML with updated response instructions but preserved everything else
        new_yaml = self.build_gpt_component_yaml(
            instructions=yaml_config.get("instructions"),
            response_instructions=response_instructions,
            model_kind=yaml_config.get("model_kind"),
            model_hint=yaml_config.get("model_hint"),
            web_browsing=yaml_config.get("web_browsing"),
        )

        # PATCH the botcomponent
        self.patch(f"botcomponents({component_id})", {"data": new_yaml})

    def get_web_search(self, bot_id: str) -> Optional[bool]:
        """
        Get the current web search (web browsing) setting for an agent.

        Args:
            bot_id: The bot's unique identifier

        Returns:
            True if web browsing is enabled, False if disabled, None if not set
        """
        gpt_component = self.get_custom_gpt_component(bot_id)
        if not gpt_component:
            return None

        current_yaml = gpt_component.get("data", "")
        config = self.parse_gpt_component_yaml(current_yaml)
        return config.get("web_browsing")

    def update_web_search(self, bot_id: str, enabled: bool) -> None:
        """
        Enable or disable web search (web browsing via Bing) for an agent.

        Updates the webBrowsing field in the Custom GPT botcomponent YAML.
        Preserves existing instructions and model settings.

        Args:
            bot_id: The bot's unique identifier
            enabled: True to enable web browsing, False to disable

        Raises:
            ClientError: If update fails
        """
        gpt_component = self.get_custom_gpt_component(bot_id)
        if not gpt_component:
            # Create the component with web browsing setting
            self.create_custom_gpt_component(bot_id, web_browsing=enabled)
            return

        component_id = gpt_component.get("botcomponentid")
        current_yaml = gpt_component.get("data", "")

        # Parse existing settings to preserve instructions and model
        yaml_config = self.parse_gpt_component_yaml(current_yaml)

        # Build new YAML with updated web browsing but preserved everything else
        new_yaml = self.build_gpt_component_yaml(
            instructions=yaml_config.get("instructions"),
            response_instructions=yaml_config.get("response_instructions"),
            model_kind=yaml_config.get("model_kind"),
            model_hint=yaml_config.get("model_hint"),
            web_browsing=enabled,
        )

        # PATCH the botcomponent
        self.patch(f"botcomponents({component_id})", {"data": new_yaml})

    # =========================================================================
    # Authentication Methods
    # =========================================================================

    # Authentication mode constants
    AUTH_MODE_NONE = 1
    AUTH_MODE_INTEGRATED = 2
    AUTH_MODE_CUSTOM_AZURE_AD = 3

    AUTH_MODE_NAMES = {
        1: "None",
        2: "Integrated",
        3: "Custom Azure AD",
    }

    def get_bot_auth(self, bot_id: str) -> dict:
        """
        Get authentication configuration for a bot.

        Args:
            bot_id: The bot's unique identifier

        Returns:
            Dict containing authentication settings:
                - mode: Authentication mode integer (1=None, 2=Integrated, 3=Custom Azure AD)
                - mode_name: Human-readable authentication mode name
                - trigger: Authentication trigger (0=As Needed, 1=Always)
                - configuration: Authentication configuration JSON (if any)
        """
        bot = self.get_bot(bot_id)

        auth_mode = bot.get("authenticationmode", 2)
        auth_trigger = bot.get("authenticationtrigger", 1)
        auth_config = bot.get("authenticationconfiguration")

        return {
            "mode": auth_mode,
            "mode_name": self.AUTH_MODE_NAMES.get(auth_mode, f"Unknown({auth_mode})"),
            "trigger": auth_trigger,
            "trigger_name": "Always" if auth_trigger == 1 else "As Needed",
            "configuration": json.loads(auth_config) if auth_config else None,
        }

    def update_bot_auth(
        self,
        bot_id: str,
        mode: Optional[int] = None,
        trigger: Optional[int] = None,
        configuration: Optional[dict] = None,
    ) -> None:
        """
        Update authentication configuration for a bot.

        Args:
            bot_id: The bot's unique identifier
            mode: Authentication mode:
                - 1 = None (no authentication required)
                - 2 = Integrated (Microsoft Entra ID integrated)
                - 3 = Custom Azure AD (manual Microsoft Entra ID configuration)
            trigger: Authentication trigger:
                - 0 = As Needed (authenticate only when required)
                - 1 = Always (require authentication for all conversations)
            configuration: Authentication configuration dict (for Custom Azure AD mode)

        Note:
            When changing to Custom Azure AD (mode 3), you may also need to configure
            the authentication settings via the Copilot Studio portal, including:
            - Service provider settings
            - Client ID and tenant ID
            - Token exchange URL
        """
        bot_data = {}

        if mode is not None:
            if mode not in self.AUTH_MODE_NAMES:
                raise ClientError(f"Invalid authentication mode: {mode}. Valid modes: 1=None, 2=Integrated, 3=Custom Azure AD")
            bot_data["authenticationmode"] = mode

        if trigger is not None:
            if trigger not in (0, 1):
                raise ClientError(f"Invalid authentication trigger: {trigger}. Valid triggers: 0=As Needed, 1=Always")
            bot_data["authenticationtrigger"] = trigger

        if configuration is not None:
            bot_data["authenticationconfiguration"] = json.dumps(configuration)

        if not bot_data:
            raise ClientError("No updates provided. Specify at least one field to update.")

        self.patch(f"bots({bot_id})", bot_data)

    # =========================================================================
    # Application Insights Methods
    # =========================================================================

    def get_bot_app_insights(self, bot_id: str) -> dict:
        """
        Get Application Insights configuration for a bot.

        Args:
            bot_id: The bot's unique identifier

        Returns:
            Dict containing Application Insights settings:
                - enabled: Whether App Insights is configured
                - connectionString: The App Insights connection string (if set)
                - logActivities: Whether activity logging is enabled
                - logSensitiveProperties: Whether sensitive property logging is enabled
        """
        bot = self.get_bot(bot_id)
        config = json.loads(bot.get("configuration", "{}"))

        # Extract App Insights settings from configuration
        app_insights = config.get("applicationInsights", {})

        return {
            "enabled": bool(app_insights.get("connectionString")),
            "connectionString": app_insights.get("connectionString", ""),
            "logActivities": app_insights.get("logActivities", False),
            "logSensitiveProperties": app_insights.get("logSensitiveProperties", False),
        }

    def update_bot_app_insights(
        self,
        bot_id: str,
        connection_string: Optional[str] = None,
        log_activities: Optional[bool] = None,
        log_sensitive_properties: Optional[bool] = None,
        disable: bool = False,
    ) -> None:
        """
        Update Application Insights configuration for a bot.

        Args:
            bot_id: The bot's unique identifier
            connection_string: App Insights connection string (from Azure portal)
            log_activities: Enable logging of incoming/outgoing messages and events
            log_sensitive_properties: Enable logging of sensitive properties (userid, name, text, speak)
            disable: Set to True to disable Application Insights (clears connection string)

        Note:
            - Multiple agents can share the same App Insights instance by using the same connection string.
            - The connection string can be found in your Azure Application Insights resource overview.
            - After enabling, telemetry will be available in the Application Insights Logs section.
        """
        # Get current bot configuration
        current_bot = self.get_bot(bot_id)
        current_config = json.loads(current_bot.get("configuration", "{}"))

        # Initialize applicationInsights section if not present
        if "applicationInsights" not in current_config:
            current_config["applicationInsights"] = {}

        app_insights = current_config["applicationInsights"]

        # Handle disable
        if disable:
            app_insights["connectionString"] = ""
            app_insights["logActivities"] = False
            app_insights["logSensitiveProperties"] = False
        else:
            # Update connection string if provided
            if connection_string is not None:
                app_insights["connectionString"] = connection_string

            # Update logging options if provided
            if log_activities is not None:
                app_insights["logActivities"] = log_activities

            if log_sensitive_properties is not None:
                app_insights["logSensitiveProperties"] = log_sensitive_properties

        # Save updated configuration
        bot_data = {
            "configuration": json.dumps(current_config, indent=2)
        }

        self.patch(f"bots({bot_id})", bot_data)

    def get_app_insights_workspace_id(self, app_id: str) -> str:
        """
        Get Log Analytics workspace ID from Application Insights ApplicationId.

        This method queries Azure Resource Manager to find the App Insights resource
        and extract its linked Log Analytics workspace ID.

        Args:
            app_id: The ApplicationId from the App Insights connection string

        Returns:
            The Log Analytics workspace ID (GUID)

        Raises:
            ClientError: If the App Insights resource cannot be found
        """
        # Get ARM token
        arm_token = get_access_token("https://management.azure.com")

        # List all subscriptions to search for the App Insights resource
        headers = {
            "Authorization": f"Bearer {arm_token}",
            "Content-Type": "application/json",
        }

        # First, get subscriptions
        subs_url = "https://management.azure.com/subscriptions?api-version=2022-12-01"
        try:
            subs_response = self._http_client.get(subs_url, headers=headers, timeout=30.0)
            subs_response.raise_for_status()
            subscriptions = subs_response.json().get("value", [])
        except Exception as e:
            raise ClientError(f"Failed to list subscriptions: {e}")

        # Search each subscription for the App Insights resource
        for sub in subscriptions:
            sub_id = sub.get("subscriptionId")
            if not sub_id:
                continue

            # List App Insights components in this subscription
            components_url = (
                f"https://management.azure.com/subscriptions/{sub_id}"
                f"/providers/Microsoft.Insights/components"
                f"?api-version=2020-02-02"
            )

            try:
                response = self._http_client.get(components_url, headers=headers, timeout=30.0)
                if response.status_code == 200:
                    components = response.json().get("value", [])
                    for component in components:
                        # Check if this is the matching App Insights resource
                        if component.get("properties", {}).get("AppId") == app_id:
                            # Found it! Extract workspace ID
                            workspace_resource_id = component.get("properties", {}).get("WorkspaceResourceId")
                            if workspace_resource_id:
                                # Extract workspace ID from resource path
                                # Format: /subscriptions/.../workspaces/{workspace-name}
                                # We need to get the workspace GUID from the workspace resource
                                workspace_url = (
                                    f"https://management.azure.com{workspace_resource_id}"
                                    f"?api-version=2023-09-01"
                                )
                                ws_response = self._http_client.get(workspace_url, headers=headers, timeout=30.0)
                                if ws_response.status_code == 200:
                                    workspace = ws_response.json()
                                    # The customerId property is the workspace ID (GUID)
                                    workspace_id = workspace.get("properties", {}).get("customerId")
                                    if workspace_id:
                                        return workspace_id
                            raise ClientError(
                                f"App Insights resource found but no Log Analytics workspace linked. "
                                f"Please link the App Insights resource to a Log Analytics workspace."
                            )
            except httpx.HTTPStatusError:
                continue  # Try next subscription

        raise ClientError(
            f"Could not find Application Insights resource with ApplicationId: {app_id}. "
            f"Ensure you have access to the subscription containing this resource."
        )

    def query_app_insights(
        self,
        app_id: str,
        query: str,
        timespan: str = "P1D"
    ) -> dict:
        """
        Execute a KQL query against Application Insights.

        Args:
            app_id: The Application Insights App ID (from connection string)
            query: KQL query string
            timespan: ISO 8601 duration (e.g., "P1D" for 1 day, "PT24H" for 24 hours)

        Returns:
            Query results containing tables with columns and rows

        Raises:
            ClientError: If the query fails
        """
        # Get Application Insights API token
        ai_token = get_access_token("https://api.applicationinsights.io")

        url = f"https://api.applicationinsights.io/v1/apps/{app_id}/query"

        headers = {
            "Authorization": f"Bearer {ai_token}",
            "Content-Type": "application/json",
        }

        body = {
            "query": query,
            "timespan": timespan,
        }

        try:
            response = self._http_client.post(url, headers=headers, json=body, timeout=60.0)
            response.raise_for_status()
            result = response.json()

            # Check for query errors (semantic errors like missing tables)
            if "error" in result:
                error = result["error"]
                # Check if it's a "table not found" error
                inner = error.get("innererror", {})
                if "SEM0100" in str(inner) or "Failed to resolve table" in str(inner):
                    # Return empty result instead of error - no telemetry data yet
                    return {"tables": [{"name": "PrimaryResult", "columns": [], "rows": []}]}
                raise ClientError(f"Query error: {error.get('message', str(error))}")

            return result
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                if "error" in error_body:
                    error_msg = error_body["error"].get("message", "")
                    inner = error_body["error"].get("innererror", {})
                    # Check if it's a "table not found" error (400 Bad Request)
                    if "SEM0100" in str(inner) or "Failed to resolve table" in str(inner):
                        # Return empty result - no telemetry data yet
                        return {"tables": [{"name": "PrimaryResult", "columns": [], "rows": []}]}
                    error_detail = error_msg or str(error_body)
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Application Insights query failed: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Query request failed: {e}")

    def get_bot_telemetry(
        self,
        bot_id: str,
        timespan: str = "P1D",
        events_only: bool = False,
    ) -> dict:
        """
        Get telemetry data for a bot from Application Insights.

        This method retrieves the bot's App Insights configuration and queries
        the telemetry data directly using the Application Insights API.

        Args:
            bot_id: The bot's unique identifier
            timespan: ISO 8601 duration (e.g., "P1D" for 1 day, "PT1H" for 1 hour)
            events_only: If True, only query customEvents table

        Returns:
            Query results containing telemetry data

        Raises:
            ClientError: If App Insights is not configured or query fails
        """
        # Get bot's App Insights config
        config = self.get_bot_app_insights(bot_id)
        if not config["enabled"]:
            raise ClientError(
                "Application Insights is not configured for this agent. "
                "Use 'copilot agent analytics enable' to configure it first."
            )

        # Parse ApplicationId from connection string
        connection_string = config["connectionString"]
        app_id = parse_connection_string(connection_string).get("ApplicationId")
        if not app_id:
            raise ClientError(
                "Could not extract ApplicationId from connection string. "
                "Please check the App Insights configuration."
            )

        # Build KQL query
        if events_only:
            query = """
customEvents
| project timestamp, name, customDimensions, customMeasurements
| order by timestamp desc
"""
        else:
            query = """
customEvents
| extend _table = "customEvents"
| project timestamp, _table, name, message = "", customDimensions
| union (
    requests
    | extend _table = "requests"
    | project timestamp, _table, name, message = "", customDimensions
)
| union (
    traces
    | extend _table = "traces"
    | project timestamp, _table, name = "", message, customDimensions
)
| union (
    exceptions
    | extend _table = "exceptions"
    | project timestamp, _table, name = type, message = outerMessage, customDimensions
)
| order by timestamp desc
"""

        # Execute query using app_id directly (not workspace ID)
        return self.query_app_insights(app_id, query, timespan)

    def list_knowledge_sources(self, bot_id: str, source_type: Optional[str] = None) -> list[dict]:
        """
        List knowledge sources for a bot.

        Args:
            bot_id: The bot's unique identifier
            source_type: Filter by type - 'file' (14), 'connector' (16), or None for all

        Returns:
            List of knowledge source records
        """
        # Component types: 14 = Bot File Attachment, 16 = Knowledge Source (connectors)
        type_filter = ""
        if source_type == "file":
            type_filter = " and componenttype eq 14"
        elif source_type == "connector":
            type_filter = " and componenttype eq 16"
        else:
            # Get both file attachments and knowledge sources
            type_filter = " and (componenttype eq 14 or componenttype eq 16)"

        result = self.get(f"botcomponents?$filter=_parentbotid_value eq {bot_id}{type_filter}")
        return result.get("value", [])

    def list_all_knowledge_sources(
        self,
        agent_id: Optional[str] = None,
        unassociated_only: bool = False,
        source_type: Optional[str] = None,
    ) -> list[dict]:
        """
        List knowledge sources with flexible filtering.

        Args:
            agent_id: Filter by specific agent (GUID). If None, lists all.
            unassociated_only: If True, only list sources not associated with any agent.
            source_type: Filter by type - 'file' (14), 'connector' (16), or None for all.

        Returns:
            List of knowledge source records
        """
        # Build component type filter
        if source_type == "file":
            type_filter = "componenttype eq 14"
        elif source_type == "connector":
            type_filter = "componenttype eq 16"
        else:
            type_filter = "(componenttype eq 14 or componenttype eq 16)"

        # Build agent filter
        if agent_id:
            agent_filter = f"_parentbotid_value eq {agent_id}"
        elif unassociated_only:
            agent_filter = "_parentbotid_value eq null"
        else:
            agent_filter = None

        # Combine filters
        if agent_filter:
            full_filter = f"{agent_filter} and {type_filter}"
        else:
            full_filter = type_filter

        result = self.get(f"botcomponents?$filter={full_filter}")
        return result.get("value", [])

    def associate_knowledge_with_agent(self, bot_id: str, component_id: str) -> None:
        """
        Associate an existing knowledge source with an agent.

        Args:
            bot_id: The agent's unique identifier
            component_id: The knowledge source component ID
        """
        # Update the parentbotid on the botcomponent
        update_data = {
            "parentbotid@odata.bind": f"/bots({bot_id})"
        }
        self.patch(f"botcomponents({component_id})", update_data)

    def disassociate_knowledge_from_agent(self, component_id: str) -> None:
        """
        Disassociate a knowledge source from its agent (make it standalone).

        Args:
            component_id: The knowledge source component ID
        """
        # Set parentbotid to null
        update_data = {
            "parentbotid@odata.bind": None
        }
        self.patch(f"botcomponents({component_id})", update_data)

    def add_file_knowledge_source(
        self,
        bot_id: str,
        name: str,
        content: str,
        description: Optional[str] = None,
    ) -> str:
        """
        Add a file-based knowledge source to a bot.

        Args:
            bot_id: The bot's unique identifier
            name: Display name for the knowledge source
            content: Text content for the knowledge source
            description: Optional description (auto-generated if not provided)

        Returns:
            The created component ID
        """
        # Get bot schema name for generating component schema name
        bot = self.get_bot(bot_id)
        bot_schema = bot.get("schemaname") or f"{self._get_publisher_prefix()}_bot{bot_id[:8]}"

        # Generate schema name from display name
        clean_name = re.sub(r'[^a-zA-Z0-9]', '', name)
        schema_name = f"{bot_schema}.file.{clean_name}"

        # Auto-generate description if not provided
        if not description:
            description = f"This knowledge source searches information contained in {name}"

        component_data = {
            "componenttype": 14,  # Bot File Attachment
            "name": name,
            "schemaname": schema_name,
            "description": description,
            "content": content,
            "parentbotid@odata.bind": f"/bots({bot_id})"
        }

        # Use longer timeout for file operations
        url = f"{self.api_url}/botcomponents"
        headers = self._get_headers()
        response = self._http_client.post(url, headers=headers, json=component_data, timeout=120.0)
        response.raise_for_status()

        # Extract component ID from OData-EntityId header
        entity_id = response.headers.get("OData-EntityId", "")
        if entity_id:
            # Extract GUID from URL like .../botcomponents(guid)
            match = re.search(r'botcomponents\(([^)]+)\)', entity_id)
            if match:
                return match.group(1)
        return ""

    def add_azure_ai_search_knowledge_source(
        self,
        bot_id: str,
        name: str,
        search_endpoint: str,
        search_index: str,
        api_key: str,
        description: Optional[str] = None,
    ) -> str:
        """
        Add an Azure AI Search knowledge source to a bot.

        Args:
            bot_id: The bot's unique identifier
            name: Display name for the knowledge source
            search_endpoint: Azure AI Search endpoint URL
            search_index: Name of the search index
            api_key: Azure AI Search API key
            description: Optional description

        Returns:
            The created component ID

        Note:
            Azure AI Search knowledge sources require:
            1. A connection reference to the Azure AI Search connector
            2. Component type 16 (Knowledge Source)

            This method creates the necessary configuration.
        """
        # Get bot schema name for generating component schema name
        bot = self.get_bot(bot_id)
        bot_schema = bot.get("schemaname") or f"{self._get_publisher_prefix()}_bot{bot_id[:8]}"

        # Generate schema name from display name
        clean_name = re.sub(r'[^a-zA-Z0-9]', '', name)
        schema_name = f"{bot_schema}.knowledge.{clean_name}"

        # Auto-generate description if not provided
        if not description:
            description = f"Azure AI Search knowledge source: {name}"

        # Build the knowledge source configuration
        # This follows the pattern used by Copilot Studio for Azure AI Search
        knowledge_config = {
            "$kind": "AzureAISearchKnowledgeSource",
            "endpoint": search_endpoint,
            "indexName": search_index,
            "apiKey": api_key,
        }

        component_data = {
            "componenttype": 16,  # Knowledge Source
            "name": name,
            "schemaname": schema_name,
            "description": description,
            "data": json.dumps(knowledge_config),
            "parentbotid@odata.bind": f"/bots({bot_id})"
        }

        # Use longer timeout
        url = f"{self.api_url}/botcomponents"
        headers = self._get_headers()
        response = self._http_client.post(url, headers=headers, json=component_data, timeout=120.0)
        response.raise_for_status()

        # Extract component ID from OData-EntityId header
        entity_id = response.headers.get("OData-EntityId", "")
        if entity_id:
            match = re.search(r'botcomponents\(([^)]+)\)', entity_id)
            if match:
                return match.group(1)
        return ""

    # Backwards compatibility alias
    def add_knowledge_source(
        self,
        bot_id: str,
        name: str,
        content: str,
        description: Optional[str] = None,
    ) -> str:
        """Alias for add_file_knowledge_source for backwards compatibility."""
        return self.add_file_knowledge_source(bot_id, name, content, description)

    def remove_knowledge_source(self, component_id: str) -> None:
        """
        Remove a knowledge source from a bot.

        Args:
            component_id: The knowledge source component's unique identifier
        """
        self.delete(f"botcomponents({component_id})")

    # =========================================================================
    # Tool Methods (Connected Agents, Flows, etc.)
    # =========================================================================

    def add_connected_agent_tool(
        self,
        bot_id: str,
        target_bot_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        pass_conversation_history: bool = True,
    ) -> str:
        """
        Add a connected agent tool to a bot.

        This creates an InvokeConnectedAgentTaskAction component that allows
        the bot to invoke another Copilot Studio agent as a sub-agent.

        Args:
            bot_id: The parent bot's unique identifier
            target_bot_id: The target agent's unique identifier to connect to
            name: Display name for the tool (defaults to target agent's name)
            description: Description of when to use this tool (for orchestration)
            pass_conversation_history: Whether to pass conversation history to the connected agent

        Returns:
            The created component ID

        Note:
            The target agent must:
            - Be in the same environment
            - Be published
            - Have "Let other agents connect" enabled in settings
        """
        # Get parent bot schema name
        bot = self.get_bot(bot_id)
        bot_schema = bot.get("schemaname") or f"{self._get_publisher_prefix()}_bot{bot_id[:8]}"

        # Get target bot details
        target_bot = self.get_bot(target_bot_id)
        target_bot_name = target_bot.get("name", "Connected Agent")
        target_bot_schema = target_bot.get("schemaname") or f"{self._get_publisher_prefix()}_bot{target_bot_id[:8]}"

        # Use target bot name if no name provided
        if not name:
            name = target_bot_name

        # Generate clean name for schema (remove spaces and special chars)
        clean_name = re.sub(r'[^a-zA-Z0-9]', '', name)
        schema_name = f"{bot_schema}.InvokeConnectedAgentTaskAction.{clean_name}"

        # Auto-generate description if not provided
        if not description:
            target_description = target_bot.get("description", "")
            if target_description:
                description = target_description
            else:
                description = f"Invoke the {target_bot_name} agent to handle specialized tasks."

        # Build the connected agent tool configuration in YAML format
        # This follows the Copilot Studio TaskDialog pattern
        tool_yaml = f"""kind: TaskDialog
modelDescription: {description}
schemaName: {schema_name}
action:
  kind: InvokeConnectedAgentTaskAction
  botSchemaName: {target_bot_schema}
  passConversationHistory: {str(pass_conversation_history).lower()}
inputType: {{}}
outputType: {{}}"""

        component_data = {
            "componenttype": 9,  # Topic (V2)
            "name": name,
            "schemaname": schema_name,
            "description": description,
            "data": tool_yaml,
            "parentbotid@odata.bind": f"/bots({bot_id})"
        }

        # Create the component
        url = f"{self.api_url}/botcomponents"
        headers = self._get_headers()
        response = self._http_client.post(url, headers=headers, json=component_data, timeout=120.0)
        response.raise_for_status()

        # Extract component ID from OData-EntityId header
        entity_id = response.headers.get("OData-EntityId", "")
        if entity_id:
            match = re.search(r'botcomponents\(([^)]+)\)', entity_id)
            if match:
                return match.group(1)
        return ""

    def remove_tool(self, component_id: str) -> None:
        """
        Remove a tool from a bot.

        Args:
            component_id: The tool component's unique identifier
        """
        self.delete(f"botcomponents({component_id})")

    def update_tool(
        self,
        component_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        availability: Optional[bool] = None,
        confirmation: Optional[bool] = None,
        confirmation_message: Optional[str] = None,
        inputs: Optional[dict] = None,
        connection_mode: Optional[str] = None,
    ) -> dict:
        """
        Update a tool's attributes.

        Args:
            component_id: The tool component's unique identifier
            name: New display name for the tool
            description: New description for the tool (used by AI for orchestration)
            availability: Whether agent can use this tool dynamically (True = anytime, False = only from topics)
            confirmation: Whether to ask user for confirmation before running
            confirmation_message: Custom message to show when asking for confirmation
            inputs: Input parameter defaults as dict, e.g., {"workspace": "123", "project": "456"}
            connection_mode: Connection mode for connector tools ('Maker' or 'Invoker')

        Returns:
            The updated component data
        """
        # Get current component data
        component = self.get(f"botcomponents({component_id})")

        updates = {}
        data = component.get("data", "")

        if name is not None:
            updates["name"] = name

        if description is not None:
            updates["description"] = description
            # Also update modelDescription in the YAML data
            if data:
                # Match modelDescription: followed by the value (until next line with key or end)
                pattern = r'(modelDescription:)\s*[^\n]*'
                # Escape any special chars in description for YAML
                escaped_desc = description.replace('\\', '\\\\').replace('"', '\\"')
                replacement = f'\\1 {escaped_desc}'
                data = re.sub(pattern, replacement, data)

        # Handle availability setting (allowDynamicInvocation)
        if availability is not None and data:
            # Check if allowDynamicInvocation already exists
            if 'allowDynamicInvocation:' in data:
                # Update existing value
                pattern = r'(allowDynamicInvocation:)\s*(true|false)'
                replacement = f'\\1 {str(availability).lower()}'
                data = re.sub(pattern, replacement, data)
            else:
                # Add after kind: TaskDialog line
                pattern = r'(kind:\s*TaskDialog\n)'
                replacement = f'\\1allowDynamicInvocation: {str(availability).lower()}\n'
                data = re.sub(pattern, replacement, data)

        # Handle confirmation setting
        if confirmation is not None and data:
            if confirmation:
                # Add or update confirmation block
                message = confirmation_message or "Do you want to proceed with this action?"
                # Escape special characters in the message
                escaped_message = message.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')

                confirmation_block = f'''confirmation:
  activity: "{escaped_message}"
  mode: Strict
'''
                # Check if confirmation block already exists
                if 'confirmation:' in data:
                    # Update existing confirmation block
                    # Match the entire confirmation block (multi-line)
                    pattern = r'confirmation:\s*\n\s*activity:[^\n]*\n\s*mode:[^\n]*\n?'
                    data = re.sub(pattern, confirmation_block, data)
                else:
                    # Add confirmation block after kind: TaskDialog (or allowDynamicInvocation if present)
                    if 'allowDynamicInvocation:' in data:
                        pattern = r'(allowDynamicInvocation:[^\n]*\n)'
                        replacement = f'\\1{confirmation_block}'
                    else:
                        pattern = r'(kind:\s*TaskDialog\n)'
                        replacement = f'\\1{confirmation_block}'
                    data = re.sub(pattern, replacement, data)
            else:
                # Remove confirmation block if it exists
                pattern = r'confirmation:\s*\n\s*activity:[^\n]*\n\s*mode:[^\n]*\n?'
                data = re.sub(pattern, '', data)
        elif confirmation_message is not None and data:
            # Only updating the confirmation message (confirmation is not explicitly set)
            if 'confirmation:' in data:
                escaped_message = confirmation_message.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
                pattern = r'(confirmation:\s*\n\s*activity:)[^\n]*'
                replacement = f'\\1 "{escaped_message}"'
                data = re.sub(pattern, replacement, data)

        # Handle input default values
        if inputs is not None and data:
            data = self._update_tool_inputs(data, inputs)

        # Handle connection mode for connector tools
        if connection_mode is not None and data:
            # Check if this is a connector tool (has connectionProperties)
            if 'connectionProperties:' in data:
                # Update the mode within connectionProperties
                pattern = r'(connectionProperties:\s*\n\s*mode:)\s*\w+'
                replacement = f'\\1 {connection_mode}'
                data = re.sub(pattern, replacement, data)
            elif 'InvokeConnectorTaskAction' in data:
                # Has connector action but no connectionProperties - add it after connectionReference
                pattern = r'(connectionReference:[^\n]*\n)'
                replacement = f'\\1  connectionProperties:\n    mode: {connection_mode}\n'
                data = re.sub(pattern, replacement, data)

        # Check if YAML data was modified
        if data != component.get("data", ""):
            updates["data"] = data

        if not updates:
            return component

        # PATCH the component
        url = f"{self.api_url}/botcomponents({component_id})"
        headers = self._get_headers()
        response = self._http_client.patch(url, headers=headers, json=updates, timeout=60.0)
        response.raise_for_status()

        # Return updated component
        return self.get(f"botcomponents({component_id})")

    def add_tool(
        self,
        bot_id: str,
        tool_type: str,
        tool_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        inputs: Optional[dict] = None,
        outputs: Optional[dict] = None,
        # Type-specific parameters
        connection_reference_id: Optional[str] = None,
        connection_mode: str = "Maker",
        no_history: bool = False,
        method: str = "GET",
        headers: Optional[dict] = None,
        body: Optional[str] = None,
        force: bool = False,
    ) -> str:
        """
        Add a tool to a bot.

        Args:
            bot_id: The parent bot's unique identifier
            tool_type: Tool type: 'connector', 'prompt', 'flow', 'http', 'agent'
            tool_id: Tool identifier (format depends on tool_type)
            name: Display name for the tool (auto-generated if not provided)
            description: Description for AI orchestration
            inputs: Input parameter schema (JSON dict)
            outputs: Output parameter schema (JSON dict)
            connection_reference_id: Connection reference ID (GUID) for connector tools (required)
            connection_mode: Connection mode ('Invoker' for user auth, 'Maker' for maker auth)
            no_history: Don't pass conversation history (for agent)
            method: HTTP method (for http)
            headers: HTTP headers (for http)
            body: Request body template (for http)
            force: Force adding tool even if operation has internal visibility

        Returns:
            The created component ID
        """
        # Get parent bot schema name
        bot = self.get_bot(bot_id)
        bot_schema = bot.get("schemaname") or f"{self._get_publisher_prefix()}_bot{bot_id[:8]}"

        # Build connection reference path from provided connection reference
        connection_reference_path = None
        runtime_connection_reference_id = None  # Will store the ID for M2M association
        if connection_reference_id:
            try:
                conn_ref = self.get_connection_reference(connection_reference_id)

                # Use the existing connection reference's logical name directly
                # The runtime uses this logical name to look up the connection reference
                logical_name = conn_ref.get("connectionreferencelogicalname")
                connection_id = conn_ref.get("connectionid")
                connector_id_raw = conn_ref.get("connectorid", "")

                # Remove /providers/Microsoft.PowerApps/apis/ prefix if present
                connector_id = connector_id_raw.replace("/providers/Microsoft.PowerApps/apis/", "")

                if not logical_name:
                    raise ClientError(
                        f"Connection reference '{connection_reference_id}' is missing logical name."
                    )

                if not connection_id or not connector_id:
                    raise ClientError(
                        f"Connection reference '{connection_reference_id}' is missing connectionid or connectorid.\n"
                        f"Connection ID: {connection_id}\n"
                        f"Connector ID: {connector_id}"
                    )

                # Use the connection reference logical name directly
                # The runtime looks up connection references by logical name, not by path
                connection_reference_path = logical_name

                # Store the existing connection reference ID for M2M association
                runtime_connection_reference_id = conn_ref.get("connectionreferenceid")

            except ClientError:
                raise
            except Exception as e:
                raise ClientError(
                    f"Connection reference '{connection_reference_id}' not found.\n"
                    f"Use 'copilot connection-references list --table' to find existing connection references.\n"
                    f"Error: {str(e)}"
                )

        # Dispatch to type-specific generator
        generators = {
            'connector': self._generate_connector_tool_yaml,
            'prompt': self._generate_prompt_tool_yaml,
            'flow': self._generate_flow_tool_yaml,
            'http': self._generate_http_tool_yaml,
            'agent': self._generate_agent_tool_yaml,
        }

        generator = generators.get(tool_type.lower())
        if not generator:
            raise ClientError(f"Invalid tool type: {tool_type}. Must be one of: {', '.join(generators.keys())}")

        # Generate YAML and metadata
        tool_yaml, schema_name, resolved_name, resolved_description = generator(
            bot_id=bot_id,
            bot_schema=bot_schema,
            tool_id=tool_id,
            name=name,
            description=description,
            inputs=inputs,
            outputs=outputs,
            connection_reference_path=connection_reference_path,
            connection_mode=connection_mode,
            no_history=no_history,
            method=method,
            headers=headers,
            body=body,
            force=force,
        )

        # Apply static input values if provided
        if inputs:
            tool_yaml = self._update_tool_inputs(tool_yaml, inputs)

        component_data = {
            "componenttype": 9,  # Topic (V2)
            "name": resolved_name,
            "schemaname": schema_name,
            "description": resolved_description,
            "data": tool_yaml,
            "parentbotid@odata.bind": f"/bots({bot_id})"
        }

        # Create the component
        url = f"{self.api_url}/botcomponents"
        headers_req = self._get_headers()
        response = self._http_client.post(url, headers=headers_req, json=component_data, timeout=120.0)
        response.raise_for_status()

        # Extract component ID from OData-EntityId header
        component_id = ""
        entity_id = response.headers.get("OData-EntityId", "")
        if entity_id:
            match = re.search(r'botcomponents\(([^)]+)\)', entity_id)
            if match:
                component_id = match.group(1)

        # CRITICAL: Associate the bot component with the connection reference (M2M relationship)
        # This is REQUIRED for connector tools to resolve the connection at runtime.
        # Without this association, the runtime cannot find the connection reference.
        if runtime_connection_reference_id and component_id:
            self._associate_botcomponent_connectionreference(component_id, runtime_connection_reference_id)

        return component_id

    def _update_tool_inputs(self, data: str, inputs: dict) -> str:
        """
        Update input values in tool YAML data.

        Uses regex to preserve the original YAML structure while only modifying
        the specific input value fields.

        Args:
            data: The YAML data string from the tool component
            inputs: Dict of property names to values, e.g., {"workspace": "123", "projects": "456"}

        Returns:
            Updated YAML data string
        """
        # Normalize line endings to \n for processing, then restore original style
        original_has_crlf = '\r\n' in data
        if original_has_crlf:
            data = data.replace('\r\n', '\n')

        # Check if inputs section exists
        has_inputs_section = 'inputs:' in data

        for prop_name, input_value in inputs.items():
            # Escape special YAML characters in value
            escaped_value = str(input_value)
            if any(c in escaped_value for c in [':', '#', '{', '}', '[', ']', ',', '&', '*', '?', '|', '-', '<', '>', '=', '!', '%', '@', '`']):
                escaped_value = f'"{escaped_value}"'

            # Check if this input already exists with value
            # Pattern matches: "- kind: ManualTaskInput\n    propertyName: X\n    value: Y"
            pattern_with_value = rf'(- kind: ManualTaskInput\s*\n\s*propertyName: {re.escape(prop_name)}\s*\n\s*)value:[^\n]*'
            if re.search(pattern_with_value, data):
                # Update existing value
                data = re.sub(pattern_with_value, rf'\1value: {escaped_value}', data)
            else:
                # Check if input exists without value (just kind and propertyName)
                pattern = rf'(- kind: ManualTaskInput\s*\n\s*propertyName: {re.escape(prop_name)})\s*\n'
                if re.search(pattern, data):
                    # Add value after propertyName
                    data = re.sub(pattern, rf'\1\n    value: {escaped_value}\n', data)
                elif not has_inputs_section:
                    # Need to add inputs section - add after kind: TaskDialog line
                    new_input = f"inputs:\n  - kind: ManualTaskInput\n    propertyName: {prop_name}\n    value: {escaped_value}\n"
                    data = re.sub(r'(kind: TaskDialog\n)', rf'\1{new_input}', data)
                    has_inputs_section = True
                else:
                    # inputs section exists but this input doesn't - add to it
                    new_input = f"  - kind: ManualTaskInput\n    propertyName: {prop_name}\n    value: {escaped_value}\n"
                    data = re.sub(r'(inputs:\n)', rf'\1{new_input}', data)

        # Restore original line ending style
        if original_has_crlf:
            data = data.replace('\n', '\r\n')

        return data

    def _build_input_output_yaml(self, inputs: Optional[dict], outputs: Optional[dict]) -> tuple[str, str]:
        """Build inputType and outputType YAML sections."""
        if inputs:
            input_props = []
            for prop_name, prop_config in inputs.items():
                prop_type = prop_config.get("type", "String") if isinstance(prop_config, dict) else "String"
                prop_desc = prop_config.get("description", "") if isinstance(prop_config, dict) else ""
                if prop_desc:
                    input_props.append(f"    {prop_name}:\n      type: {prop_type}\n      description: {prop_desc}")
                else:
                    input_props.append(f"    {prop_name}:\n      type: {prop_type}")
            input_yaml = "inputType:\n  properties:\n" + "\n".join(input_props) if input_props else "inputType: {}"
        else:
            input_yaml = "inputType: {}"

        if outputs:
            output_props = []
            for prop_name, prop_config in outputs.items():
                prop_type = prop_config.get("type", "String") if isinstance(prop_config, dict) else "String"
                output_props.append(f"    {prop_name}:\n      type: {prop_type}")
            output_yaml = "outputType:\n  properties:\n" + "\n".join(output_props) if output_props else "outputType: {}"
        else:
            output_yaml = "outputType: {}"

        return input_yaml, output_yaml

    def _build_connector_outputs_yaml(self, connector_id: str, operation_id: str) -> str:
        """Build outputs YAML from connector's swagger response schema."""
        try:
            # Get connector details
            connector = self.get_connector(connector_id)
            swagger = connector.get('properties', {}).get('swagger', {})
            paths = swagger.get('paths', {})
            definitions = swagger.get('definitions', {})

            # Find the operation
            for path, methods in paths.items():
                for method, details in methods.items():
                    if details.get('operationId') == operation_id:
                        # Get response schema
                        responses = details.get('responses', {})
                        for code, resp in responses.items():
                            schema = resp.get('schema', {})
                            if '$ref' in schema:
                                # Resolve reference
                                ref_name = schema['$ref'].split('/')[-1]
                                schema = definitions.get(ref_name, {})

                            # Extract property names recursively
                            props = self._extract_property_names(schema, definitions, prefix='')
                            if props:
                                outputs_lines = ['outputs:']
                                for prop in props:
                                    outputs_lines.append(f'  - propertyName: {prop}')
                                    outputs_lines.append('')  # Empty line after each
                                return '\n'.join(outputs_lines) + '\n'
            return ''
        except Exception:
            return ''

    def _extract_property_names(self, schema: dict, definitions: dict, prefix: str = '', max_depth: int = 2) -> list:
        """Extract property names from schema, handling nested objects."""
        if max_depth <= 0:
            return []

        props = []
        properties = schema.get('properties', {})

        for name, prop_schema in properties.items():
            full_name = f'{prefix}{name}' if prefix else name

            # Check if it's a reference to another definition
            if '$ref' in prop_schema:
                ref_name = prop_schema['$ref'].split('/')[-1]
                nested_schema = definitions.get(ref_name, {})
                nested_props = self._extract_property_names(nested_schema, definitions, f'{full_name}.', max_depth - 1)
                props.extend(nested_props)
            elif prop_schema.get('type') == 'object' and 'properties' in prop_schema:
                nested_props = self._extract_property_names(prop_schema, definitions, f'{full_name}.', max_depth - 1)
                props.extend(nested_props)
            elif prop_schema.get('type') == 'array':
                # For arrays, just add the property name
                props.append(full_name)
            else:
                props.append(full_name)

        return props

    def _generate_agent_tool_yaml(
        self, bot_id: str, bot_schema: str, tool_id: str,
        name: Optional[str], description: Optional[str],
        inputs: Optional[dict], outputs: Optional[dict],
        no_history: bool = False, **kwargs
    ) -> tuple[str, str, str, str]:
        """Generate YAML for InvokeConnectedAgentTaskAction."""
        # Get target bot details
        target_bot = self.get_bot(tool_id)
        target_bot_name = target_bot.get("name", "Connected Agent")
        target_bot_schema = target_bot.get("schemaname") or f"{self._get_publisher_prefix()}_bot{tool_id[:8]}"

        # Use target bot name if no name provided
        resolved_name = name or target_bot_name

        # Generate clean name for schema
        clean_name = re.sub(r'[^a-zA-Z0-9]', '', resolved_name)
        schema_name = f"{bot_schema}.InvokeConnectedAgentTaskAction.{clean_name}"

        # Auto-generate description if not provided
        if not description:
            target_description = target_bot.get("description", "")
            resolved_description = target_description or f"Invoke the {target_bot_name} agent to handle specialized tasks."
        else:
            resolved_description = description

        pass_history = str(not no_history).lower()
        input_yaml, output_yaml = self._build_input_output_yaml(inputs, outputs)

        tool_yaml = f"""kind: TaskDialog
modelDescription: {resolved_description}
schemaName: {schema_name}
action:
  kind: InvokeConnectedAgentTaskAction
  botSchemaName: {target_bot_schema}
  passConversationHistory: {pass_history}
{input_yaml}
{output_yaml}"""

        return tool_yaml, schema_name, resolved_name, resolved_description

    def _generate_connector_tool_yaml(
        self, bot_id: str, bot_schema: str, tool_id: str,
        name: Optional[str], description: Optional[str],
        inputs: Optional[dict], outputs: Optional[dict],
        connection_reference_path: Optional[str] = None,
        force: bool = False,
        connection_mode: str = "Maker",
        **kwargs
    ) -> tuple[str, str, str, str]:
        """Generate YAML for InvokeConnectorTaskAction."""
        # Parse connector_id:operation_id format
        if ':' not in tool_id:
            raise ClientError("Connector tool --id must be in format 'connector_id:operation_id' (e.g., 'shared_asana:GetTask')")

        # Connection reference path is required for connector tools
        if not connection_reference_path:
            raise ClientError(
                "Connector tools require --connection-reference-id parameter.\n"
                "Use 'copilot connection-references list --table' to find existing connection references."
            )

        connector_id, operation_id = tool_id.split(':', 1)

        # Validate operation exists and get its details from swagger
        operation_details = None
        operation_description = None
        try:
            connector = self.get_connector(connector_id)
            swagger = connector.get('properties', {}).get('swagger', {})
            paths = swagger.get('paths', {})

            # Find the operation in swagger
            for path, methods in paths.items():
                for method, details in methods.items():
                    if details.get('operationId') == operation_id:
                        operation_details = details
                        operation_description = details.get('description') or details.get('summary', '')
                        visibility = details.get('x-ms-visibility', '')
                        if visibility == 'internal' and not force:
                            raise ClientError(
                                f"Operation '{operation_id}' has internal visibility and cannot be used as a tool.\n"
                                f"Internal operations are not exposed in the Copilot Studio UI and may not work correctly.\n"
                                f"Use --force to add anyway, or use 'copilot managed-connector get {connector_id}' to see available operations."
                            )
                        break
                if operation_details:
                    break

            # If operation not found, reject with helpful error
            if not operation_details:
                # Get list of available operations for error message
                available_ops = []
                for path, methods in paths.items():
                    for method, details in methods.items():
                        op_id = details.get('operationId', '')
                        visibility = details.get('x-ms-visibility', '')
                        if op_id and visibility != 'internal':
                            available_ops.append(op_id)

                # Suggest similar operations
                similar = [op for op in available_ops if operation_id.lower().replace('_', '') in op.lower().replace('_', '')
                           or op.lower().replace('_', '') in operation_id.lower().replace('_', '')]

                error_msg = f"Operation '{operation_id}' not found in connector '{connector_id}'."
                if similar:
                    error_msg += f"\n\nDid you mean one of these?\n  " + "\n  ".join(similar[:5])
                error_msg += f"\n\nUse 'copilot managed-connector get {connector_id}' or 'copilot custom-connector get {connector_id}' to see all available operations."
                raise ClientError(error_msg)

        except ClientError:
            raise
        except Exception as e:
            raise ClientError(f"Failed to validate operation: {e}")

        # Get connector display name for naming - prefer actual name from connector metadata
        # Custom connectors have long IDs like "shared_asana-20custom-5fd251d00ef0afcb57-..."
        # which would create schema names exceeding 100 char limit
        connector_display_name = (
            connector.get('name') or
            connector.get('properties', {}).get('displayName') or
            connector_id.replace('shared_', '').split('-')[0].title()  # Fallback: use first segment
        )
        # Remove spaces for schema name (keep spaces for display name)
        connector_schema_name = connector_display_name.replace(' ', '')

        # Get operation display name from swagger
        operation_display_name = operation_details.get('summary', operation_id)

        # UI default name format: "{Connector} - {OperationDisplayName}"
        if name:
            resolved_name = name
        else:
            resolved_name = f"{connector_display_name} - {operation_display_name}"

        # Generate schema name matching UI pattern: {bot}.action.{Connector}-{OperationId}_{random}
        # Use random 3-char suffix like UI does for uniqueness
        # Schema name must be <= 100 characters
        random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=3))
        schema_name = f"{bot_schema}.action.{connector_schema_name}-{operation_id}_{random_suffix}"

        # Truncate if still too long (max 100 chars for botcomponent schemaname)
        if len(schema_name) > 100:
            # Keep bot_schema.action. prefix and truncate middle
            prefix = f"{bot_schema}.action."
            suffix = f"_{random_suffix}"
            max_middle = 100 - len(prefix) - len(suffix)
            middle = f"{connector_schema_name[:max_middle//2]}-{operation_id}"[:max_middle]
            schema_name = f"{prefix}{middle}{suffix}"

        # Use swagger description if not provided by user
        resolved_description = description
        if not resolved_description:
            resolved_description = operation_description or f"Invoke {operation_id} operation from {connector_id} connector."

        # Build outputs from connector response schema
        outputs_yaml = self._build_connector_outputs_yaml(connector_id, operation_id)

        tool_yaml = f"""kind: TaskDialog
modelDisplayName: {resolved_name}
modelDescription: {resolved_description}
{outputs_yaml}action:
  kind: InvokeConnectorTaskAction
  connectionReference: {connection_reference_path}
  connectionProperties:
    mode: {connection_mode}

  operationId: {operation_id}

outputMode: All"""

        return tool_yaml, schema_name, resolved_name, resolved_description

    def _generate_prompt_tool_yaml(
        self, bot_id: str, bot_schema: str, tool_id: str,
        name: Optional[str], description: Optional[str],
        inputs: Optional[dict], outputs: Optional[dict], **kwargs
    ) -> tuple[str, str, str, str]:
        """Generate YAML for InvokePromptTaskAction."""
        # Try to get prompt details
        try:
            prompt = self.get_prompt(tool_id)
            prompt_name = prompt.get("msdyn_name", "AI Prompt")
            prompt_schema = prompt.get("schemaname", "")
        except Exception:
            prompt_name = "AI Prompt"
            prompt_schema = ""

        # Use prompt name if no name provided
        resolved_name = name or prompt_name

        # Generate clean name for schema
        clean_name = re.sub(r'[^a-zA-Z0-9]', '', resolved_name)
        schema_name = f"{bot_schema}.InvokePromptTaskAction.{clean_name}"

        # Auto-generate description if not provided
        resolved_description = description or f"Invoke the {prompt_name} AI Builder prompt."

        input_yaml, output_yaml = self._build_input_output_yaml(inputs, outputs)

        # Build action section
        action_lines = [
            "action:",
            "  kind: InvokePromptTaskAction",
            f"  promptId: {tool_id}",
        ]
        if prompt_schema:
            action_lines.append(f"  promptSchemaName: {prompt_schema}")

        tool_yaml = f"""kind: TaskDialog
modelDescription: {resolved_description}
schemaName: {schema_name}
{chr(10).join(action_lines)}
{input_yaml}
{output_yaml}"""

        return tool_yaml, schema_name, resolved_name, resolved_description

    def _generate_flow_tool_yaml(
        self, bot_id: str, bot_schema: str, tool_id: str,
        name: Optional[str], description: Optional[str],
        inputs: Optional[dict], outputs: Optional[dict],
        connection_reference_path: Optional[str] = None, **kwargs
    ) -> tuple[str, str, str, str]:
        """Generate YAML for InvokeFlowTaskAction."""
        # Use flow ID as name if not provided
        resolved_name = name or f"Flow {tool_id[:8]}"

        # Generate clean name for schema
        clean_name = re.sub(r'[^a-zA-Z0-9]', '', resolved_name)
        schema_name = f"{bot_schema}.InvokeFlowTaskAction.{clean_name}"

        # Auto-generate description if not provided
        resolved_description = description or f"Invoke Power Automate flow."

        input_yaml, output_yaml = self._build_input_output_yaml(inputs, outputs)

        # Build action section with proper flow ID format
        flow_ref = tool_id if tool_id.startswith('/providers/') else f"/providers/Microsoft.Flow/flows/{tool_id}"
        action_lines = [
            "action:",
            "  kind: InvokeFlowTaskAction",
            f"  flowId: {flow_ref}",
        ]
        if connection_reference_path:
            action_lines.append(f"  connectionReference: {connection_reference_path}")

        tool_yaml = f"""kind: TaskDialog
modelDescription: {resolved_description}
schemaName: {schema_name}
{chr(10).join(action_lines)}
{input_yaml}
{output_yaml}"""

        return tool_yaml, schema_name, resolved_name, resolved_description

    def _generate_http_tool_yaml(
        self, bot_id: str, bot_schema: str, tool_id: str,
        name: Optional[str], description: Optional[str],
        inputs: Optional[dict], outputs: Optional[dict],
        method: str = "GET", headers: Optional[dict] = None,
        body: Optional[str] = None, **kwargs
    ) -> tuple[str, str, str, str]:
        """Generate YAML for InvokeHttpTaskAction."""
        # tool_id is the URL for HTTP tools
        url = tool_id

        # Use method + shortened URL as name if not provided
        resolved_name = name or f"{method} API"

        # Generate clean name for schema
        clean_name = re.sub(r'[^a-zA-Z0-9]', '', resolved_name)
        schema_name = f"{bot_schema}.InvokeHttpTaskAction.{clean_name}"

        # Auto-generate description if not provided
        resolved_description = description or f"Make {method} request to {url}"

        input_yaml, output_yaml = self._build_input_output_yaml(inputs, outputs)

        # Build action section
        action_lines = [
            "action:",
            "  kind: InvokeHttpTaskAction",
            f"  method: {method.upper()}",
            f"  url: {url}",
        ]

        if headers:
            action_lines.append("  headers:")
            for header_name, header_value in headers.items():
                action_lines.append(f"    {header_name}: {header_value}")

        if body:
            # Use YAML literal block for body
            body_indented = body.replace('\n', '\n    ')
            action_lines.append(f"  body: |\n    {body_indented}")

        tool_yaml = f"""kind: TaskDialog
modelDescription: {resolved_description}
schemaName: {schema_name}
{chr(10).join(action_lines)}
{input_yaml}
{output_yaml}"""

        return tool_yaml, schema_name, resolved_name, resolved_description

    # =========================================================================
    # Environment Methods
    # =========================================================================

    def list_environments(self) -> list[dict]:
        """
        List all Power Platform environments accessible to the user.

        Returns:
            List of environment records from Business App Platform API

        Note:
            This uses the BAP (Business App Platform) API to list environments.
        """
        bap_token = get_access_token("https://api.bap.microsoft.com/")

        url = (
            "https://api.bap.microsoft.com/providers/Microsoft.BusinessAppPlatform/environments"
            "?api-version=2021-04-01"
        )

        headers = {
            "Authorization": f"Bearer {bap_token}",
            "Accept": "application/json",
        }

        try:
            response = self._http_client.get(url, headers=headers, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            return data.get("value", [])
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                error_detail = f": {error_body}"
            except Exception:
                error_detail = f": {e.response.text[:200]}" if e.response.text else ""
            raise ClientError(f"Failed to list environments (HTTP {e.response.status_code}){error_detail}")

    def get_environment(self, environment_id: str) -> dict:
        """
        Get details for a specific Power Platform environment.

        Args:
            environment_id: The environment ID (e.g., Default-<tenant-id> or GUID)

        Returns:
            Environment record from Business App Platform API
        """
        bap_token = get_access_token("https://api.bap.microsoft.com/")

        url = (
            f"https://api.bap.microsoft.com/providers/Microsoft.BusinessAppPlatform/environments/{environment_id}"
            "?api-version=2021-04-01"
        )

        headers = {
            "Authorization": f"Bearer {bap_token}",
            "Accept": "application/json",
        }

        try:
            response = self._http_client.get(url, headers=headers, timeout=60.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                error_detail = f": {error_body}"
            except Exception:
                error_detail = f": {e.response.text[:200]}" if e.response.text else ""
            raise ClientError(f"Failed to get environment (HTTP {e.response.status_code}){error_detail}")

    def create_environment(
        self,
        display_name: str,
        location: str,
        environment_sku: str = "Sandbox",
        description: str = "",
        provision_dataverse: bool = True,
        language_code: int = 1033,
        currency_code: str = "USD",
    ) -> dict:
        """
        Create a new Power Platform environment.

        Args:
            display_name: Display name for the environment
            location: Azure region (e.g., "unitedstates", "europe", "asia")
            environment_sku: Environment type - Sandbox, Production, Developer, Trial, Teams
            description: Optional description for the environment
            provision_dataverse: If True, provision a Dataverse database after creation
            language_code: Base language for Dataverse (default: 1033 for English)
            currency_code: Currency code for Dataverse (default: USD)

        Returns:
            The created environment record

        Note:
            Creating a Developer environment requires the user to have a Power Apps Developer Plan.
            Creating a Production environment may require capacity allocation in the tenant.
        """
        bap_token = get_access_token("https://api.bap.microsoft.com/")

        url = (
            "https://api.bap.microsoft.com/providers/Microsoft.BusinessAppPlatform/environments"
            "?api-version=2021-04-01"
        )

        headers = {
            "Authorization": f"Bearer {bap_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        body = {
            "location": location,
            "properties": {
                "displayName": display_name,
                "environmentSku": environment_sku,
            }
        }

        if description:
            body["properties"]["description"] = description

        try:
            response = self._http_client.post(url, headers=headers, json=body, timeout=120.0)
            response.raise_for_status()
            environment = response.json()

            # Optionally provision Dataverse
            if provision_dataverse:
                env_id = environment.get("name")
                if env_id:
                    try:
                        self._provision_dataverse(
                            environment_id=env_id,
                            language_code=language_code,
                            currency_code=currency_code,
                            bap_token=bap_token,
                        )
                    except ClientError as e:
                        # Environment created but Dataverse provisioning failed
                        environment["_dataverse_error"] = str(e)

            return environment

        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                error_detail = f": {error_body}"
            except Exception:
                error_detail = f": {e.response.text[:500]}" if e.response.text else ""
            raise ClientError(f"Failed to create environment (HTTP {e.response.status_code}){error_detail}")

    def _provision_dataverse(
        self,
        environment_id: str,
        language_code: int = 1033,
        currency_code: str = "USD",
        bap_token: Optional[str] = None,
    ) -> dict:
        """
        Provision a Dataverse database in an existing environment.

        Args:
            environment_id: The environment ID to provision Dataverse in
            language_code: Base language code (default: 1033 for English)
            currency_code: Currency code (default: USD)
            bap_token: Optional pre-fetched BAP token

        Returns:
            Provisioning response
        """
        if not bap_token:
            bap_token = get_access_token("https://api.bap.microsoft.com/")

        url = (
            f"https://api.bap.microsoft.com/providers/Microsoft.BusinessAppPlatform/environments/{environment_id}/provisionInstance"
            "?api-version=2021-04-01"
        )

        headers = {
            "Authorization": f"Bearer {bap_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        body = {
            "baseLanguage": language_code,
            "currency": {
                "code": currency_code
            }
        }

        try:
            response = self._http_client.post(url, headers=headers, json=body, timeout=300.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                error_detail = f": {error_body}"
            except Exception:
                error_detail = f": {e.response.text[:500]}" if e.response.text else ""
            raise ClientError(f"Failed to provision Dataverse (HTTP {e.response.status_code}){error_detail}")

    def list_environment_locations(self) -> list[dict]:
        """
        List supported locations for creating Power Platform environments.

        Returns:
            List of location records with name and displayName
        """
        bap_token = get_access_token("https://api.bap.microsoft.com/")

        url = (
            "https://api.bap.microsoft.com/providers/Microsoft.BusinessAppPlatform/locations"
            "?api-version=2021-04-01"
        )

        headers = {
            "Authorization": f"Bearer {bap_token}",
            "Accept": "application/json",
        }

        try:
            response = self._http_client.get(url, headers=headers, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            return data.get("value", [])
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                error_detail = f": {error_body}"
            except Exception:
                error_detail = f": {e.response.text[:200]}" if e.response.text else ""
            raise ClientError(f"Failed to list locations (HTTP {e.response.status_code}){error_detail}")

    def delete_environment(self, environment_id: str) -> None:
        """
        Delete a Power Platform environment.

        Args:
            environment_id: The environment ID to delete

        Note:
            This is a destructive operation. The environment and all its data will be deleted.
        """
        bap_token = get_access_token("https://api.bap.microsoft.com/")

        # Use the admin scopes endpoint for delete operations
        url = (
            f"https://api.bap.microsoft.com/providers/Microsoft.BusinessAppPlatform/scopes/admin/environments/{environment_id}"
            "?api-version=2023-06-01"
        )

        headers = {
            "Authorization": f"Bearer {bap_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # Delete requires a reason code
        body = {
            "code": "Manual"
        }

        try:
            response = self._http_client.request(
                "DELETE",
                url,
                headers=headers,
                json=body,
                timeout=120.0
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                error_detail = f": {error_body}"
            except Exception:
                error_detail = f": {e.response.text[:500]}" if e.response.text else ""
            raise ClientError(f"Failed to delete environment (HTTP {e.response.status_code}){error_detail}")

    def rename_environment(self, environment_id: str, new_display_name: str) -> dict:
        """
        Rename a Power Platform environment.

        Args:
            environment_id: The environment ID to rename
            new_display_name: The new display name for the environment

        Returns:
            The updated environment record
        """
        bap_token = get_access_token("https://api.bap.microsoft.com/")

        url = (
            f"https://api.bap.microsoft.com/providers/Microsoft.BusinessAppPlatform/scopes/admin/environments/{environment_id}"
            "?api-version=2021-04-01"
        )

        headers = {
            "Authorization": f"Bearer {bap_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        body = {
            "properties": {
                "displayName": new_display_name
            }
        }

        try:
            response = self._http_client.patch(url, headers=headers, json=body, timeout=60.0)
            response.raise_for_status()
            if response.status_code == 204 or not response.text:
                return self.get_environment(environment_id)
            return response.json()
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                error_detail = f": {error_body}"
            except Exception:
                error_detail = f": {e.response.text[:500]}" if e.response.text else ""
            raise ClientError(f"Failed to rename environment (HTTP {e.response.status_code}){error_detail}")

    def get_environment_settings(self, environment_id: str, select: Optional[list[str]] = None) -> dict:
        """
        Get environment management settings via the Power Platform API.

        Args:
            environment_id: The environment GUID
            select: Optional list of specific setting names to retrieve

        Returns:
            Dict of setting name -> value pairs from the API response
        """
        pp_token = get_access_token("https://api.powerplatform.com")

        url = (
            f"https://api.powerplatform.com/environmentmanagement/environments/{environment_id}/settings/"
            "?api-version=2022-03-01-preview"
        )
        if select:
            url += f"&$select={','.join(select)}"

        headers = {
            "Authorization": f"Bearer {pp_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            response = self._http_client.get(url, headers=headers, timeout=60.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                error_detail = f": {error_body}"
            except Exception:
                error_detail = f": {e.response.text[:500]}" if e.response.text else ""
            raise ClientError(f"Failed to get environment settings (HTTP {e.response.status_code}){error_detail}")

    def update_environment_settings(self, environment_id: str, settings: dict) -> dict:
        """
        Update environment management settings via the Power Platform API.

        Args:
            environment_id: The environment GUID
            settings: Dict of setting name -> value pairs to update

        Returns:
            The API response
        """
        pp_token = get_access_token("https://api.powerplatform.com")

        url = (
            f"https://api.powerplatform.com/environmentmanagement/environments/{environment_id}/settings/"
            "?api-version=2022-03-01-preview"
        )

        headers = {
            "Authorization": f"Bearer {pp_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            response = self._http_client.patch(url, headers=headers, json=settings, timeout=60.0)
            response.raise_for_status()
            if response.status_code == 204 or not response.text:
                return self.get_environment_settings(environment_id)
            return response.json()
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                error_detail = f": {error_body}"
            except Exception:
                error_detail = f": {e.response.text[:500]}" if e.response.text else ""
            raise ClientError(f"Failed to update environment settings (HTTP {e.response.status_code}){error_detail}")

    # =========================================================================
    # Connector Methods
    # =========================================================================

    def list_connectors(
        self,
        custom_only: bool = False,
        managed_only: bool = False,
        environment_id: Optional[str] = None,
    ) -> list[dict]:
        """
        List all connectors in the environment (both custom and managed).

        This queries multiple APIs to get complete connector coverage:
        1. Dataverse 'connector' table - for custom connectors registered in Dataverse
        2. Power Apps API - for managed (Microsoft) connectors AND custom connectors
           created via the Power Apps API that may not be in Dataverse

        Args:
            custom_only: If True, only return custom connectors.
            managed_only: If True, only return managed (Microsoft) connectors.
            environment_id: Power Platform environment ID. If not provided,
                           will use DATAVERSE_ENVIRONMENT_ID from config.

        Returns:
            List of connector records with normalized properties structure.

        Note:
            Custom connectors are merged from both Dataverse and Power Apps API
            to ensure ALL custom connectors are visible regardless of how they
            were created.
        """
        # Get environment ID from config if not provided
        if not environment_id:
            config = get_config()
            environment_id = config.environment_id
            if not environment_id:
                raise ClientError(
                    "Environment ID not found. Please set DATAVERSE_ENVIRONMENT_ID "
                    "in your .env file (e.g., Default-<tenant-id> or the environment GUID).\n\n"
                    "You can find your environment ID in the Power Platform admin center."
                )

        all_connectors = []

        # Get custom connectors from Dataverse (unless managed_only)
        if not managed_only:
            custom_connectors = self._list_custom_connectors_from_dataverse()
            all_connectors.extend(custom_connectors)

            # Also get custom connectors from Power Apps API
            # These may have different IDs than Dataverse even for "same" connector,
            # so we return both and let the user see all sources
            powerapps_custom = self._list_custom_connectors_from_powerapps(environment_id)
            all_connectors.extend(powerapps_custom)

        # Get managed connectors from Power Apps API (unless custom_only)
        if not custom_only:
            managed_connectors = self._list_managed_connectors_from_powerapps(environment_id)
            all_connectors.extend(managed_connectors)

        return all_connectors

    def _list_custom_connectors_from_dataverse(self) -> list[dict]:
        """
        List custom connectors from the Dataverse connector table.

        Returns:
            List of custom connector records with normalized properties.
        """
        # Build query - select only needed fields to reduce response size
        select_fields = (
            "connectorid,name,displayname,connectorinternalid,connectortype,"
            "description,ismanaged,statecode,statuscode,createdon,modifiedon,"
            "openapidefinition,connectionparameters,iconbrandcolor"
        )

        endpoint = f"connectors?$select={select_fields}&$orderby=displayname asc"

        try:
            data = self._request("GET", endpoint)
            connectors = data.get("value", [])

            # Normalize to a compatible format
            normalized = []
            for conn in connectors:
                conn_type = conn.get("connectortype", 0)
                is_custom = conn_type == 1

                # Parse OpenAPI definition to extract additional info
                openapi_def = {}
                try:
                    openapi_str = conn.get("openapidefinition", "{}")
                    if openapi_str:
                        openapi_def = json.loads(openapi_str)
                except (json.JSONDecodeError, TypeError):
                    pass

                # Extract publisher from OpenAPI info if available
                info = openapi_def.get("info", {})
                publisher = info.get("contact", {}).get("name", "")
                if not publisher:
                    publisher = info.get("x-ms-publisher", "")

                normalized.append({
                    "name": conn.get("connectorinternalid", conn.get("name", "")),
                    "properties": {
                        "displayName": conn.get("displayname", ""),
                        "description": conn.get("description", "") or info.get("description", ""),
                        "publisher": publisher,
                        "tier": "Standard" if is_custom else "N/A",
                        "environment": True if is_custom else False,
                        "swagger": openapi_def,
                    },
                    "_dataverse": {
                        "connectorid": conn.get("connectorid", ""),
                        "name": conn.get("name", ""),
                        "connectorinternalid": conn.get("connectorinternalid", ""),
                        "connectortype": conn_type,
                        "ismanaged": conn.get("ismanaged", False),
                        "statecode": conn.get("statecode", 0),
                        "statuscode": conn.get("statuscode", 1),
                        "createdon": conn.get("createdon", ""),
                        "modifiedon": conn.get("modifiedon", ""),
                        "iconbrandcolor": conn.get("iconbrandcolor", ""),
                    },
                    "_source": "dataverse",
                })

            return normalized
        except ClientError:
            raise
        except Exception as e:
            raise ClientError(f"Failed to list custom connectors from Dataverse: {e}")

    def _list_custom_connectors_from_powerapps(self, environment_id: str) -> list[dict]:
        """
        List custom connectors from the Power Apps API.

        Custom connectors created via the Power Apps API may not be registered
        in Dataverse, so we need to query both sources to get complete coverage.

        Uses the admin scope API to see ALL custom connectors in the environment,
        not just those created by or shared with the current user.

        Args:
            environment_id: Power Platform environment ID.

        Returns:
            List of custom connector records with normalized properties.
        """
        powerapps_token = get_access_token("https://service.powerapps.com/")

        # Use admin scope API to see all connectors regardless of ownership
        url = (
            f"https://api.powerapps.com/providers/Microsoft.PowerApps/scopes/admin"
            f"/environments/{environment_id}/apis"
            f"?api-version=2016-11-01"
            f"&$filter=IsCustomApi eq true"
        )

        headers = {
            "Authorization": f"Bearer {powerapps_token}",
            "Accept": "application/json",
        }

        try:
            response = self._http_client.get(url, headers=headers, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            connectors = data.get("value", [])

            # Process custom connectors (already filtered by API with IsCustomApi eq true)
            custom = []
            for conn in connectors:
                props = conn.get("properties", {})
                # Double-check isCustomApi in case API filter wasn't applied
                if props.get("isCustomApi", False):
                    # Normalize to match format from other sources
                    info = props.get("swagger", {}).get("info", {}) if props.get("swagger") else {}
                    publisher = props.get("publisher", "")
                    if not publisher:
                        publisher = info.get("contact", {}).get("name", "")

                    # Extract creator info from admin API response
                    created_by = props.get("createdBy", {})
                    creator_email = created_by.get("email", "") if isinstance(created_by, dict) else ""

                    custom.append({
                        "name": conn.get("name", ""),
                        "properties": {
                            "displayName": props.get("displayName", ""),
                            "description": props.get("description", "") or info.get("description", ""),
                            "publisher": publisher,
                            "tier": props.get("tier", "Standard"),
                            "isCustomApi": True,
                            "iconBrandColor": props.get("iconBrandColor", ""),
                            "createdBy": creator_email,
                        },
                        "_source": "powerapps",
                    })

            return custom
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                if "error" in error_body:
                    error_detail = error_body["error"].get("message", str(error_body))
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to list custom connectors from Power Apps: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Request failed: {e}")

    def _list_managed_connectors_from_powerapps(self, environment_id: str) -> list[dict]:
        """
        List managed (Microsoft) connectors from the Power Apps API.

        Args:
            environment_id: Power Platform environment ID.

        Returns:
            List of managed connector records with normalized properties.
        """
        powerapps_token = get_access_token("https://service.powerapps.com/")

        url = (
            f"https://api.powerapps.com/providers/Microsoft.PowerApps/apis"
            f"?api-version=2016-11-01"
            f"&$filter=environment eq '{environment_id}'"
        )

        headers = {
            "Authorization": f"Bearer {powerapps_token}",
            "Accept": "application/json",
        }

        try:
            response = self._http_client.get(url, headers=headers, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            connectors = data.get("value", [])

            # Filter to only managed connectors (exclude custom ones - we get those from Dataverse)
            # Custom connectors have "environment" in properties
            managed = []
            for conn in connectors:
                props = conn.get("properties", {})
                # Skip custom connectors - they come from Dataverse
                if "environment" in props:
                    continue

                # Add source marker
                conn["_source"] = "powerapps"
                managed.append(conn)

            return managed
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                if "error" in error_body:
                    error_detail = error_body["error"].get("message", str(error_body))
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to list managed connectors: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Request failed: {e}")

    def get_connector(self, connector_id: str, environment_id: Optional[str] = None) -> dict:
        """
        Get a specific connector by ID.

        This method checks both Dataverse (for custom connectors) and Power Apps API
        (for managed connectors) to find the connector.

        Args:
            connector_id: The connector's unique identifier (e.g., shared_office365,
                         shared_pub-5fasana-1234567890abcdef)
            environment_id: Power Platform environment ID. If not provided,
                            will use DATAVERSE_ENVIRONMENT_ID from config.

        Returns:
            Connector record (normalized format)
        """
        # Get environment ID from config if not provided
        if not environment_id:
            config = get_config()
            environment_id = config.environment_id
            if not environment_id:
                raise ClientError(
                    "Environment ID not found. Please set DATAVERSE_ENVIRONMENT_ID "
                    "in your .env file (e.g., Default-<tenant-id> or the environment GUID).\n\n"
                    "You can find your environment ID in the Power Platform admin center."
                )

        # First, try to find in Dataverse (custom connectors)
        try:
            connector = self._get_connector_from_dataverse(connector_id)
            if connector:
                return connector
        except ClientError:
            pass  # Not found in Dataverse, try Power Apps API

        # Then try Power Apps API (managed connectors)
        return self._get_connector_from_powerapps(connector_id, environment_id)

    def _get_connector_from_dataverse(self, connector_id: str) -> Optional[dict]:
        """
        Get a custom connector from Dataverse by connectorinternalid.

        Args:
            connector_id: The connector's internal ID (e.g., shared_pub-5fasana-...)

        Returns:
            Connector record or None if not found
        """
        # Query by connectorinternalid
        endpoint = (
            f"connectors?$filter=connectorinternalid eq '{connector_id}'"
            f"&$select=connectorid,name,displayname,connectorinternalid,connectortype,"
            f"description,ismanaged,statecode,statuscode,createdon,modifiedon,"
            f"openapidefinition,connectionparameters,iconbrandcolor"
        )

        try:
            data = self._request("GET", endpoint)
            connectors = data.get("value", [])

            if not connectors:
                return None

            conn = connectors[0]
            conn_type = conn.get("connectortype", 0)
            is_custom = conn_type == 1

            # Parse OpenAPI definition
            openapi_def = {}
            try:
                openapi_str = conn.get("openapidefinition", "{}")
                if openapi_str:
                    openapi_def = json.loads(openapi_str)
            except (json.JSONDecodeError, TypeError):
                pass

            info = openapi_def.get("info", {})
            publisher = info.get("contact", {}).get("name", "") or info.get("x-ms-publisher", "")

            return {
                "name": conn.get("connectorinternalid", conn.get("name", "")),
                "properties": {
                    "displayName": conn.get("displayname", ""),
                    "description": conn.get("description", "") or info.get("description", ""),
                    "publisher": publisher,
                    "tier": "Standard" if is_custom else "N/A",
                    "environment": True if is_custom else False,
                    "swagger": openapi_def,
                },
                "_dataverse": {
                    "connectorid": conn.get("connectorid", ""),
                    "name": conn.get("name", ""),
                    "connectorinternalid": conn.get("connectorinternalid", ""),
                    "connectortype": conn_type,
                    "ismanaged": conn.get("ismanaged", False),
                    "statecode": conn.get("statecode", 0),
                    "statuscode": conn.get("statuscode", 1),
                    "createdon": conn.get("createdon", ""),
                    "modifiedon": conn.get("modifiedon", ""),
                    "iconbrandcolor": conn.get("iconbrandcolor", ""),
                },
                "_source": "dataverse",
            }
        except ClientError:
            return None

    def _get_custom_connector_entity_id(self, connector_id: str) -> Optional[str]:
        """
        Get the Dataverse entity ID for a custom connector.

        This is used when creating connection references to properly link them
        to custom connectors via the CustomConnectorId field. Without this link,
        connector operations may not be discoverable by agents.

        Args:
            connector_id: The connector's internal ID (e.g., shared_asana-20custom-...)

        Returns:
            The connector's Dataverse entity ID (GUID), or None if not a custom connector
        """
        # Query Dataverse for the connector
        # Note: Dataverse may modify the connectorinternalid during registration,
        # so we use contains filter instead of exact match
        # Also query all connectors and match in Python for more flexibility
        endpoint = "connectors?$select=connectorid,connectorinternalid,displayname"

        try:
            data = self._request("GET", endpoint)
            connectors = data.get("value", [])

            # Try exact match first
            for conn in connectors:
                if conn.get("connectorinternalid") == connector_id:
                    return conn.get("connectorid")

            # Try partial match - look for common prefix (before environment suffix)
            # Power Apps IDs: shared_asana-20custom-5fd251d00ef0afcb57-5fe2f45645c919b585
            # Dataverse IDs: shared_asana-5fasana-20custom-5fd251d00ef0afcb57
            # Common pattern: extract the core connector name
            connector_parts = connector_id.replace("shared_", "").split("-")
            if connector_parts:
                # Look for connectors that share the first part (e.g., "asana")
                search_term = connector_parts[0].lower()
                for conn in connectors:
                    internal_id = conn.get("connectorinternalid", "").lower()
                    if search_term in internal_id and "custom" in internal_id:
                        return conn.get("connectorid")

            return None
        except ClientError:
            # Not found or not a custom connector
            return None

    def _get_publisher_prefix(self) -> str:
        """
        Get the customization prefix from the environment's non-system publisher.

        Dataverse requires entity names to use a recognized publisher prefix
        (2-8 alphanumeric chars). This queries the publishers table and returns
        the first non-system publisher's customization prefix.

        Returns:
            Publisher customization prefix from the active environment.

        Raises:
            ClientError: If the publishers query fails.
            ValueError: If no non-system publisher is found in the environment.
        """
        result = self.get(
            "publishers?$select=customizationprefix,uniquename"
            "&$filter=uniquename ne 'MicrosoftCorporation' "
            "and uniquename ne 'microsoftdynamic' "
            "and uniquename ne 'MicrosoftPowerApps'"
            "&$top=1"
        )
        publishers = result.get("value", [])
        if publishers:
            prefix = publishers[0].get("customizationprefix", "")
            if prefix:
                return prefix
        raise ValueError(
            "No non-system publisher found in this Dataverse environment. "
            "Create a custom publisher in the Power Platform admin center "
            "before running publisher-prefix-dependent operations."
        )

    def register_connector_in_dataverse(
        self,
        connector_id: str,
        display_name: str,
        openapi_definition: dict,
        description: Optional[str] = None,
        icon_brand_color: str = "#007ee5",
    ) -> Optional[str]:
        """
        Register a custom connector in the Dataverse connector table.

        Custom connectors created via Power Apps API are not automatically registered
        in Dataverse. This method creates a record in the Dataverse connector table
        so that connection references can properly link to the connector via
        CustomConnectorId.

        Args:
            connector_id: The connector's internal ID (e.g., shared_asana-20custom-...)
            display_name: Display name for the connector
            openapi_definition: OpenAPI 2.0 definition (dict)
            description: Connector description (optional)
            icon_brand_color: Icon brand color in hex format

        Returns:
            The created connector's Dataverse entity ID (GUID), or None if failed
        """
        import re

        # Check if already registered (by connectorinternalid)
        existing_id = self._get_custom_connector_entity_id(connector_id)
        if existing_id:
            return existing_id

        # Generate logical name for Dataverse connector record.
        # Dataverse requires: alphanumeric prefix (2-8 chars) + '_' + alphanumeric name.
        # The prefix must be a recognized publisher customization prefix in the environment.
        # Examples: pub_AsanaCustom, pub_GoogleAnalytics
        prefix = self._get_publisher_prefix()
        sanitized_name = re.sub(r'[^a-zA-Z0-9]', '', display_name)
        if not sanitized_name:
            # Fallback: derive from connector_id
            sanitized_name = re.sub(r'[^a-zA-Z0-9]', '', connector_id.replace('shared_', ''))
        logical_name = f"{prefix}_{sanitized_name}"

        # Also check by logical name in case _get_custom_connector_entity_id missed it
        # (e.g., connector was registered but connectorinternalid doesn't match patterns)
        try:
            result = self.get(
                f"connectors?$filter=name eq '{logical_name}'"
                "&$select=connectorid"
            )
            existing = result.get("value", [])
            if existing:
                return existing[0].get("connectorid")
        except ClientError:
            pass

        # Serialize OpenAPI definition
        openapi_str = json.dumps(openapi_definition)

        payload = {
            "name": logical_name,
            "displayname": display_name,
            "connectorinternalid": connector_id,
            "connectortype": 1,  # 1 = Custom connector
            "openapidefinition": openapi_str,
            "iconbrandcolor": icon_brand_color,
            "statecode": 0,  # Active
            "statuscode": 1,  # Active
        }

        if description:
            payload["description"] = description

        endpoint = "connectors"

        try:
            # Use POST with Prefer header to get created record back
            headers = self._get_headers()
            headers["Prefer"] = "return=representation"
            url = f"{self.api_url}/{endpoint}"

            response = self._http_client.post(url, headers=headers, json=payload, timeout=60.0)
            response.raise_for_status()

            result = response.json()
            return result.get("connectorid")

        except httpx.HTTPStatusError as e:
            # Log but don't fail - connector can still work without Dataverse registration
            # (just connection references won't have CustomConnectorId linked)
            error_detail = str(e)
            if e.response is not None:
                try:
                    error_body = e.response.json()
                    if "error" in error_body:
                        error_detail = error_body["error"].get("message", str(error_body))
                except Exception:
                    error_detail = e.response.text[:500] if e.response.text else str(e)
            # Raise with details so caller can see the error
            raise ClientError(f"Failed to register connector in Dataverse: HTTP {e.response.status_code}: {error_detail}")
        except Exception as ex:
            raise ClientError(f"Failed to register connector in Dataverse: {ex}")

    def _get_connector_from_powerapps(self, connector_id: str, environment_id: str) -> dict:
        """
        Get a connector from Power Apps API.

        Args:
            connector_id: The connector's unique identifier
            environment_id: Power Platform environment ID

        Returns:
            Connector record from Power Apps API
        """
        powerapps_token = get_access_token("https://service.powerapps.com/")

        url = (
            f"https://api.powerapps.com/providers/Microsoft.PowerApps/apis/{connector_id}"
            f"?api-version=2016-11-01"
            f"&$filter=environment eq '{environment_id}'"
        )

        headers = {
            "Authorization": f"Bearer {powerapps_token}",
            "Accept": "application/json",
        }

        try:
            response = self._http_client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            connector = response.json()
            connector["_source"] = "powerapps"
            return connector
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                if "error" in error_body:
                    error_detail = error_body["error"].get("message", str(error_body))
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to get connector: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Request failed: {e}")

    def _get_operations_from_openapi(self, openapi_def: dict) -> list[str]:
        """
        Extract all operation IDs from an OpenAPI definition.

        By default, custom code scripts apply to all operations, but you can
        limit this by specifying specific operation IDs in script_operations.

        Args:
            openapi_def: OpenAPI 2.0 definition

        Returns:
            list[str]: List of all operationId values found in the definition
        """
        operations = []
        paths = openapi_def.get("paths", {})

        for path, path_item in paths.items():
            for method in ["get", "post", "put", "patch", "delete", "options", "head"]:
                if method in path_item:
                    operation = path_item[method]
                    operation_id = operation.get("operationId")
                    if operation_id:
                        operations.append(operation_id)

        return operations

    def _generate_api_properties(
        self,
        openapi_def: dict,
        icon_brand_color: str = "#007ee5",
        oauth_client_id: Optional[str] = None,
        oauth_client_secret: Optional[str] = None,
        oauth_redirect_url: Optional[str] = None,
        oauth_identity_provider: Optional[str] = None,
    ) -> dict:
        """
        Generate apiProperties content from OpenAPI definition.

        Extracts authentication configuration from securityDefinitions and creates
        the properties structure needed by Power Platform custom connectors.

        Args:
            openapi_def: OpenAPI 2.0 definition
            icon_brand_color: Icon brand color in hex format
            oauth_client_id: OAuth 2.0 Client ID (optional)
            oauth_client_secret: OAuth 2.0 Client Secret (optional)
            oauth_redirect_url: Custom OAuth redirect URL (optional)
            oauth_identity_provider: Power Platform identity provider preset
                (oauth2|aad|google|github|facebook). Defaults to "oauth2".

        Returns:
            dict: API properties structure
        """
        properties = {
            "iconBrandColor": icon_brand_color,
            "capabilities": [],
            "policyTemplateInstances": []
        }

        # Extract connection parameters from securityDefinitions
        security_defs = openapi_def.get("securityDefinitions", {})
        connection_params = {}

        for sec_name, sec_def in security_defs.items():
            sec_type = sec_def.get("type", "")

            if sec_type == "oauth2":
                # OAuth2 configuration
                oauth_flow = sec_def.get("flow", "")
                token_url = sec_def.get("tokenUrl", "")

                # Prefer explicit refreshUrl, then x-ms-refresh-url, then fall back to tokenUrl
                refresh_url = sec_def.get("refreshUrl", sec_def.get("x-ms-refresh-url", token_url))

                # Build scopes list. Provider-specific scope requirements (e.g.
                # offline_access for Entra ID) are the swagger author's
                # responsibility — the CLI does not inject them implicitly.
                scopes = list(sec_def.get("scopes", {}).keys())

                # Use custom redirect URL if provided, otherwise use default
                redirect_url = oauth_redirect_url or "https://global.consent.azure-apim.net/redirect"

                oauth_settings = {
                    "identityProvider": oauth_identity_provider or "oauth2",
                    "clientId": oauth_client_id or "",
                    "scopes": scopes,
                    "redirectMode": "Global",
                    "redirectUrl": redirect_url,
                    "properties": {
                        "IsFirstParty": "False"
                    },
                    "customParameters": {
                        "authorizationUrl": {
                            "value": sec_def.get("authorizationUrl", "")
                        },
                        "tokenUrl": {
                            "value": token_url
                        },
                        "refreshUrl": {
                            "value": refresh_url if oauth_flow == "accessCode" else ""
                        },
                        "resourceUri": {
                            "value": sec_def.get("x-ms-resource-uri", "")
                        }
                    }
                }

                # Add client secret if provided
                if oauth_client_secret:
                    oauth_settings["clientSecret"] = oauth_client_secret

                connection_params["token"] = {
                    "type": "oauthSetting",
                    "oAuthSettings": oauth_settings
                }
            elif sec_type == "apiKey":
                # API Key authentication
                param_name = sec_def.get("name", "api_key")
                in_location = sec_def.get("in", "header")

                connection_params[param_name] = {
                    "type": "securestring",
                    "uiDefinition": {
                        "displayName": f"API Key ({param_name})",
                        "description": f"The API Key for authentication (sent in {in_location})",
                        "tooltip": "Provide your API Key",
                        "constraints": {
                            "required": "true",
                            "clearText": False
                        }
                    }
                }
            elif sec_type == "basic":
                # Basic authentication
                connection_params["username"] = {
                    "type": "string",
                    "uiDefinition": {
                        "displayName": "Username",
                        "description": "Username for basic authentication",
                        "tooltip": "Provide your username",
                        "constraints": {
                            "required": "true"
                        }
                    }
                }
                connection_params["password"] = {
                    "type": "securestring",
                    "uiDefinition": {
                        "displayName": "Password",
                        "description": "Password for basic authentication",
                        "tooltip": "Provide your password",
                        "constraints": {
                            "required": "true",
                            "clearText": False
                        }
                    }
                }

        if connection_params:
            properties["connectionParameters"] = connection_params

        return {"properties": properties}

    def _get_user_object_id(self) -> str:
        """
        Get the current user's Azure AD object ID from the Azure CLI.

        Returns:
            str: User's Azure AD object ID

        Raises:
            ClientError: If unable to get the object ID
        """
        try:
            az = _resolve_az_command()
            result = subprocess.run(
                [az, "ad", "signed-in-user", "show", "--query", "id", "-o", "tsv"],
                capture_output=True,
                text=True,
                check=True
            )
            object_id = result.stdout.strip()
            if not object_id:
                raise ClientError("Unable to get user object ID from Azure CLI")
            return object_id
        except subprocess.CalledProcessError as e:
            raise ClientError(f"Failed to get user object ID: {e.stderr}")
        except FileNotFoundError:
            raise ClientError(
                "Azure CLI not found. Please install Azure CLI and login with 'az login'."
            )

    def generate_resource_storage(
        self,
        environment_id: Optional[str] = None
    ) -> str:
        """
        Generate a shared access signature (SAS) URL for uploading connector assets.

        This calls the Power Apps API to get a temporary Azure Blob Storage URL
        for uploading files like custom code scripts or icons.

        Args:
            environment_id: Environment ID (optional, uses config if not provided)

        Returns:
            str: SAS URL for Azure Blob Storage uploads

        Raises:
            ClientError: If the API call fails
        """
        if not environment_id:
            config = get_config()
            environment_id = config.environment_id
            if not environment_id:
                raise ClientError(
                    "Environment ID not found. Please set DATAVERSE_ENVIRONMENT_ID "
                    "in your .env file or provide --environment option."
                )

        # Get user's object ID for the API call
        user_object_id = self._get_user_object_id()

        # Get Power Apps token
        powerapps_token = get_access_token("https://service.powerapps.com/")

        # Call generateResourceStorage API - requires objectIds/{oid} in path
        url = (
            f"https://api.powerapps.com/providers/Microsoft.PowerApps"
            f"/objectIds/{user_object_id}/generateResourceStorage"
            f"?api-version=2016-11-01"
        )

        headers = {
            "Authorization": f"Bearer {powerapps_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        payload = {
            "environment": {
                "name": environment_id
            }
        }

        try:
            response = self._http_client.post(url, headers=headers, json=payload, timeout=30.0)
            response.raise_for_status()
            result = response.json()

            sas_url = result.get("sharedAccessSignature")
            if not sas_url:
                raise ClientError("No sharedAccessSignature returned from API")

            return sas_url
        except httpx.HTTPStatusError as e:
            error_detail = "Unknown error"
            try:
                error_json = e.response.json()
                if "error" in error_json:
                    error_detail = error_json["error"].get("message", str(error_json))
                else:
                    error_detail = str(error_json)
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to generate resource storage: {error_detail}")

    def upload_file_to_blob(
        self,
        sas_url: str,
        file_path: str
    ) -> str:
        """
        Upload a file to Azure Blob Storage using a SAS URL.

        This uploads files (like custom code scripts) to the storage container
        provided by the generateResourceStorage API.

        Args:
            sas_url: SAS URL from generate_resource_storage()
            file_path: Local path to the file to upload

        Returns:
            str: Download URL for the uploaded file

        Raises:
            ClientError: If upload fails or file not found
        """
        if not os.path.exists(file_path):
            raise ClientError(f"File not found: {file_path}")

        # Parse the SAS URL to extract components
        parsed = urlparse(sas_url)
        # Account name is the subdomain (e.g., 'accountname' from 'accountname.blob.core.windows.net')
        netloc = parsed.netloc
        account_name = netloc.split('.')[0]
        # Container name is the path (strip leading /)
        container_name = parsed.path.strip('/')
        # SAS token is the query string
        sas_token = parsed.query

        # Get file info
        file_name = os.path.basename(file_path)
        content_type, _ = mimetypes.guess_type(file_name)
        if not content_type:
            content_type = "application/octet-stream"

        # Read file content
        with open(file_path, 'rb') as f:
            file_content = f.read()

        # Build the blob upload URL
        # Format: https://{account}.blob.core.windows.net/{container}/{blob}?{sas}
        blob_url = f"https://{netloc}/{container_name}/{file_name}?{sas_token}"

        headers = {
            "x-ms-blob-type": "BlockBlob",
            "Content-Type": content_type,
            "Content-Length": str(len(file_content)),
        }

        try:
            response = self._http_client.put(blob_url, headers=headers, content=file_content, timeout=60.0)
            response.raise_for_status()

            # Build the download URL (same URL without the SAS token for reference,
            # but we return with SAS for immediate use)
            download_url = f"https://{netloc}/{container_name}/{file_name}?{sas_token}"
            return download_url
        except httpx.HTTPStatusError as e:
            error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to upload file to blob storage: {error_detail}")

    def create_custom_connector(
        self,
        name: str,
        openapi_definition: dict,
        description: Optional[str] = None,
        icon_brand_color: str = "#007ee5",
        environment_id: Optional[str] = None,
        oauth_client_id: Optional[str] = None,
        oauth_client_secret: Optional[str] = None,
        oauth_redirect_url: Optional[str] = None,
        oauth_identity_provider: Optional[str] = None,
        script_file: Optional[str] = None,
        script_operations: Optional[list[str]] = None,
    ) -> dict:
        """
        Create a custom connector in the current environment via Power Apps API.

        This uses the Power Apps Management API (same as list/get connectors and
        connections) to ensure full connector registration, following the pattern
        used by Microsoft's official paconn CLI tool.

        Args:
            name: Display name for the connector
            openapi_definition: OpenAPI 2.0 definition (dict, not stringified)
            description: Connector description (optional)
            icon_brand_color: Icon brand color in hex format
            environment_id: Environment ID (optional, uses config if not provided)
            oauth_client_id: OAuth 2.0 Client ID (required for OAuth connectors)
            oauth_client_secret: OAuth 2.0 Client Secret (required for OAuth connectors)
            oauth_redirect_url: Custom OAuth redirect URL (optional)
            oauth_identity_provider: Power Platform identity provider preset
                (oauth2|aad|google|github|facebook). Defaults to "oauth2".
            script_file: Path to C# script file (.csx) for custom code (optional)
            script_operations: List of operation IDs that use the script (optional,
                defaults to all operations if script_file is provided)

        Returns:
            dict: Created connector details including connector_id

        Raises:
            ClientError: If creation fails
        """
        _validate_oauth_identity_provider(oauth_identity_provider)
        import re

        # Get environment ID
        if not environment_id:
            config = get_config()
            environment_id = config.environment_id
            if not environment_id:
                raise ClientError(
                    "Environment ID not found. Please set DATAVERSE_ENVIRONMENT_ID "
                    "in your .env file or provide --environment option."
                )

        # Generate connector ID from name
        sanitized = re.sub(r'[^a-z0-9_]', '_', name.lower())
        connector_id = f"cr_{sanitized}"

        # Check for name conflicts before attempting creation
        existing = self._list_custom_connectors_from_powerapps(environment_id)
        conflicts = [
            c for c in existing
            if c.get("properties", {}).get("displayName", "").lower() == name.lower()
        ]
        if conflicts:
            conflict_id = conflicts[0].get("name", "unknown")
            raise ClientError(
                f"A connector named '{name}' already exists (ID: {conflict_id}).\n"
                f"Use 'copilot custom-connector update {conflict_id}' to update it, "
                f"or 'copilot custom-connector remove {conflict_id} --force' to delete it first."
            )

        # Handle script upload if provided
        script_url = None
        if script_file:
            if not os.path.exists(script_file):
                raise ClientError(f"Script file not found: {script_file}")

            # Get SAS URL for blob storage
            sas_url = self.generate_resource_storage(environment_id)

            # Upload the script
            script_url = self.upload_file_to_blob(sas_url, script_file)

            # If no operations specified, get all POST/PUT/PATCH operations from OpenAPI
            if not script_operations:
                script_operations = self._get_operations_from_openapi(openapi_definition)

        # Generate apiProperties from OpenAPI securityDefinitions
        api_properties = self._generate_api_properties(
            openapi_definition,
            icon_brand_color,
            oauth_client_id,
            oauth_client_secret,
            oauth_redirect_url,
            oauth_identity_provider,
        )

        # Extract backend service URL from OpenAPI definition
        schemes = openapi_definition.get("schemes", ["https"])
        scheme = schemes[0] if schemes else "https"
        host = openapi_definition.get("host", "")
        base_path = openapi_definition.get("basePath", "")
        backend_url = f"{scheme}://{host}{base_path}"

        # Build payload following Power Apps API format
        # Use OpenApiDefinition (not swagger) and merge apiProperties
        payload = {
            "properties": {
                "displayName": name,
                "OpenApiDefinition": openapi_definition,  # Use OpenApiDefinition, not swagger
                "iconBrandColor": icon_brand_color,
                "backendService": {
                    "serviceUrl": backend_url
                },
                "environment": {
                    "id": f"/providers/Microsoft.PowerApps/environments/{environment_id}",
                    "name": environment_id
                },
                # Merge connection parameters and other properties from apiProperties
                **api_properties.get("properties", {})
            }
        }

        # Add script configuration if script was uploaded
        if script_url:
            payload["properties"]["scriptDefinitionUrl"] = script_url
            if script_operations:
                payload["properties"]["scriptOperations"] = script_operations

        if description:
            payload["properties"]["description"] = description

        # Get Power Apps token
        powerapps_token = get_access_token("https://service.powerapps.com/")

        # Build endpoint - POST to collection, not to specific ID
        url = (
            f"https://api.powerapps.com/providers/Microsoft.PowerApps/apis"
            f"?api-version=2016-11-01"
            f"&$filter=environment eq '{environment_id}'"
        )

        headers = {
            "Authorization": f"Bearer {powerapps_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        try:
            # Use longer timeout for connector creation (involves script compilation)
            response = self._http_client.post(url, headers=headers, json=payload, timeout=180.0)
            response.raise_for_status()
            result = response.json()

            # Extract actual connector ID from API response
            actual_connector_id = result.get("name", connector_id)

            # Power Apps API ignores scriptOperations during creation (POST).
            # Apply script config via a follow-up PATCH so operations are mapped.
            # Brief delay required — API may not return the new connector immediately.
            if script_url and script_operations:
                import time
                time.sleep(3)
                self.update_custom_connector(
                    connector_id=actual_connector_id,
                    script_file=script_file,
                    script_operations=script_operations,
                    environment_id=environment_id,
                )

            return {
                "connector_id": actual_connector_id,
                "display_name": name,
                "description": description,
                "environment_id": environment_id,
                "result": result,
            }
        except httpx.HTTPStatusError as e:
            error_detail = "Unknown error"
            try:
                error_json = e.response.json()
                if "error" in error_json:
                    error_detail = error_json["error"].get("message", str(error_json))
                else:
                    error_detail = str(error_json)
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to create connector: {error_detail}")

    def update_custom_connector(
        self,
        connector_id: str,
        openapi_definition: Optional[dict] = None,
        description: Optional[str] = None,
        icon_brand_color: Optional[str] = None,
        environment_id: Optional[str] = None,
        oauth_client_id: Optional[str] = None,
        oauth_client_secret: Optional[str] = None,
        oauth_redirect_url: Optional[str] = None,
        oauth_identity_provider: Optional[str] = None,
        script_file: Optional[str] = None,
        script_operations: Optional[list[str]] = None,
    ) -> dict:
        """
        Update an existing custom connector via Power Apps API.

        This method updates a connector's OpenAPI definition, authentication settings,
        and/or custom code script.

        Args:
            connector_id: The connector's unique identifier (e.g., shared_pub-5fasana-...)
            openapi_definition: OpenAPI 2.0 definition (dict, optional - keep existing if not provided)
            description: Connector description (optional)
            icon_brand_color: Icon brand color in hex format (optional)
            environment_id: Environment ID (optional, uses config if not provided)
            oauth_client_id: OAuth 2.0 Client ID (optional)
            oauth_client_secret: OAuth 2.0 Client Secret (optional)
            oauth_redirect_url: Custom OAuth redirect URL (optional)
            oauth_identity_provider: Power Platform identity provider preset
                (oauth2|aad|google|github|facebook). Optional.
            script_file: Path to C# script file (.csx) for custom code (optional)
            script_operations: List of operation IDs that use the script (optional)

        Returns:
            dict: Updated connector details

        Raises:
            ClientError: If update fails
        """
        _validate_oauth_identity_provider(oauth_identity_provider)
        # Get environment ID
        if not environment_id:
            config = get_config()
            environment_id = config.environment_id
            if not environment_id:
                raise ClientError(
                    "Environment ID not found. Please set DATAVERSE_ENVIRONMENT_ID "
                    "in your .env file or provide --environment option."
                )

        # Get current connector details to preserve existing settings
        powerapps_token = get_access_token("https://service.powerapps.com/")

        get_url = f"https://api.powerapps.com/providers/Microsoft.PowerApps/apis/{connector_id}"
        get_params = {
            "api-version": "2016-11-01",
            "$filter": f"environment eq '{environment_id}'"
        }

        headers = {
            "Authorization": f"Bearer {powerapps_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        try:
            response = self._http_client.get(get_url, headers=headers, params=get_params, timeout=30.0)
            response.raise_for_status()
            existing_connector = response.json()
        except httpx.HTTPStatusError as e:
            error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to get existing connector: {error_detail}")

        # Get existing properties
        existing_props = existing_connector.get("properties", {})

        # Handle script upload if provided
        script_url = None
        if script_file:
            if not os.path.exists(script_file):
                raise ClientError(f"Script file not found: {script_file}")

            # Get SAS URL for blob storage
            sas_url = self.generate_resource_storage(environment_id)

            # Upload the script
            script_url = self.upload_file_to_blob(sas_url, script_file)

            # If no operations specified and OpenAPI provided, get all operations
            if not script_operations and openapi_definition:
                script_operations = self._get_operations_from_openapi(openapi_definition)
            elif not script_operations:
                # Use existing OpenAPI to get operations
                # Power Platform returns the spec under "swagger" (not "OpenApiDefinition")
                existing_openapi = existing_props.get("swagger") or existing_props.get("OpenApiDefinition", {})
                if existing_openapi:
                    script_operations = self._get_operations_from_openapi(existing_openapi)

        # Build update payload - only include properties we want to update
        # Don't copy all existing properties as some (like displayName) cannot be updated
        payload = {
            "properties": {}
        }

        # Update with new values if provided
        if openapi_definition:
            payload["properties"]["OpenApiDefinition"] = openapi_definition

            # Generate new apiProperties if OpenAPI definition changed
            api_properties = self._generate_api_properties(
                openapi_definition,
                icon_brand_color or existing_props.get("iconBrandColor", "#007ee5"),
                oauth_client_id,
                oauth_client_secret,
                oauth_redirect_url,
                oauth_identity_provider,
            )
            payload["properties"].update(api_properties.get("properties", {}))

            # Update backend service URL
            schemes = openapi_definition.get("schemes", ["https"])
            scheme = schemes[0] if schemes else "https"
            host = openapi_definition.get("host", "")
            base_path = openapi_definition.get("basePath", "")
            backend_url = f"{scheme}://{host}{base_path}"
            payload["properties"]["backendService"] = {"serviceUrl": backend_url}

        # Handle OAuth credential updates even without new OpenAPI definition
        if (
            oauth_client_id
            or oauth_client_secret
            or oauth_identity_provider
        ) and not openapi_definition:
            # Get existing connection parameters
            existing_conn_params = existing_props.get("connectionParameters", {})
            token_settings = existing_conn_params.get("token", {})

            if token_settings.get("type") == "oauthSetting":
                # Update OAuth settings with new credentials
                oauth_settings = token_settings.get("oAuthSettings", {})

                if oauth_client_id:
                    oauth_settings["clientId"] = oauth_client_id
                if oauth_client_secret:
                    oauth_settings["clientSecret"] = oauth_client_secret
                if oauth_redirect_url:
                    oauth_settings["redirectUrl"] = oauth_redirect_url
                    oauth_settings["redirectMode"] = "Global"
                if oauth_identity_provider:
                    oauth_settings["identityProvider"] = oauth_identity_provider

                # Build updated connection parameters
                updated_conn_params = dict(existing_conn_params)
                updated_conn_params["token"] = {
                    "type": "oauthSetting",
                    "oAuthSettings": oauth_settings
                }

                payload["properties"]["connectionParameters"] = updated_conn_params

        if description is not None:
            payload["properties"]["description"] = description

        if icon_brand_color:
            payload["properties"]["iconBrandColor"] = icon_brand_color

        # Add script configuration if script was uploaded
        if script_url:
            payload["properties"]["scriptDefinitionUrl"] = script_url
            if script_operations:
                payload["properties"]["scriptOperations"] = script_operations

        # Update via PATCH - use params dict to properly encode query string
        update_url = f"https://api.powerapps.com/providers/Microsoft.PowerApps/apis/{connector_id}"
        params = {
            "api-version": "2016-11-01",
            "$filter": f"environment eq '{environment_id}'"
        }

        try:
            response = self._http_client.patch(update_url, headers=headers, params=params, json=payload, timeout=60.0)
            response.raise_for_status()

            # PATCH returns 204 No Content on success
            if response.status_code == 204:
                return {
                    "connector_id": connector_id,
                    "display_name": existing_props.get("displayName", ""),
                    "environment_id": environment_id,
                    "script_uploaded": script_url is not None,
                    "result": {},
                }

            result = response.json()
            return {
                "connector_id": connector_id,
                "display_name": result.get("properties", {}).get("displayName", ""),
                "environment_id": environment_id,
                "script_uploaded": script_url is not None,
                "result": result,
            }
        except httpx.HTTPStatusError as e:
            error_detail = "Unknown error"
            try:
                error_json = e.response.json()
                if "error" in error_json:
                    error_detail = error_json["error"].get("message", str(error_json))
                else:
                    error_detail = str(error_json)
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to update connector: {error_detail}")

    def delete_custom_connector(
        self,
        connector_id: str,
        environment_id: Optional[str] = None,
        display_name: Optional[str] = None
    ) -> dict:
        """
        Delete a custom connector from both Dataverse and Power Apps API.

        Custom connectors can exist in Dataverse, Power Apps API, or both with
        different IDs. When a connector is created, both a Power Apps entry and a
        Dataverse record are generated, each with a different ID. This method
        deletes by connector_id first, then cleans up any remaining "ghost"
        entries that share the same display_name.

        Args:
            connector_id: The connector's unique identifier (e.g., shared_pub-5fasana-...)
            environment_id: Environment ID (optional, uses config if not provided)
            display_name: The connector's display name. When provided, after deleting
                by connector_id, any remaining entries with this display name are
                also deleted (ghost cleanup).

        Returns:
            dict with 'dataverse', 'powerapps', and optionally 'ghost_cleanup' keys

        Raises:
            ClientError: If deletion fails from all sources
        """
        # Get environment ID
        if not environment_id:
            config = get_config()
            environment_id = config.environment_id
            if not environment_id:
                raise ClientError(
                    "Environment ID not found. Please set DATAVERSE_ENVIRONMENT_ID "
                    "in your .env file or provide --environment option."
                )

        results = {"dataverse": None, "powerapps": None}
        errors = []

        # Try to delete from Dataverse
        dataverse_connector = self._get_connector_from_dataverse(connector_id)
        if dataverse_connector:
            connector_guid = dataverse_connector.get("_dataverse", {}).get("connectorid")
            if connector_guid:
                try:
                    self._request("DELETE", f"connectors({connector_guid})", timeout=60.0)
                    results["dataverse"] = "deleted"
                except ClientError as e:
                    results["dataverse"] = f"failed: {e}"
                    errors.append(f"Dataverse: {e}")
        else:
            results["dataverse"] = "not found"

        # Also try to delete from Power Apps API (may have different ID)
        try:
            self._delete_connector_via_powerapps(connector_id, environment_id)
            results["powerapps"] = "deleted"
        except ClientError as e:
            if "404" in str(e) or "not found" in str(e).lower():
                results["powerapps"] = "not found"
            else:
                results["powerapps"] = f"failed: {e}"
                errors.append(f"Power Apps: {e}")

        # If both failed (not just "not found"), raise error
        if results["dataverse"] not in ["deleted", "not found"] and \
           results["powerapps"] not in ["deleted", "not found"]:
            raise ClientError(f"Failed to delete connector: {'; '.join(errors)}")

        # If neither found the connector
        if results["dataverse"] == "not found" and results["powerapps"] == "not found":
            raise ClientError(f"Connector '{connector_id}' not found in Dataverse or Power Apps API")

        # Ghost cleanup: delete any remaining entries with the same display name.
        # When a connector is created, two entries can appear (one from Power Apps API,
        # one from Dataverse registration) with different IDs. Deleting by connector_id
        # only removes one, leaving a ghost that causes name conflicts on re-create.
        #
        # Build a set of IDs that were already handled by the primary deletion above,
        # so ghost cleanup only removes UNRELATED entries with the same display name.
        if display_name:
            # Collect all IDs associated with the primary connector (both the passed ID
            # and the Dataverse record's connectorinternalid, which may differ)
            already_handled = {connector_id}
            if dataverse_connector:
                dv_internal = dataverse_connector.get("_dataverse", {}).get("connectorinternalid", "")
                if dv_internal:
                    already_handled.add(dv_internal)

            ghost_results = []

            # Check Dataverse for remaining entries with this display name
            endpoint = f"connectors?$filter=displayname eq '{display_name}'&$select=connectorid,connectorinternalid,displayname"
            dv_data = self._request("GET", endpoint)
            dv_ghosts = dv_data.get("value", [])
            for ghost in dv_ghosts:
                ghost_internal_id = ghost.get("connectorinternalid", "")
                ghost_guid = ghost.get("connectorid", "")
                if ghost_internal_id in already_handled or ghost_guid in already_handled:
                    continue  # Part of primary connector, not a ghost
                self._request("DELETE", f"connectors({ghost_guid})", timeout=60.0)
                ghost_results.append(f"dataverse:{ghost_internal_id}")

            # Only clean up Power Apps ghosts if the primary deletion targeted
            # Power Apps (not just a Dataverse-only ghost). Power Apps entries are
            # canonical; Dataverse entries are the duplicates that need cleanup.
            if results.get("powerapps") == "deleted":
                pa_connectors = self._list_custom_connectors_from_powerapps(environment_id)
                for pa_conn in pa_connectors:
                    pa_name = pa_conn.get("properties", {}).get("displayName", "")
                    pa_id = pa_conn.get("name", "")
                    if pa_name != display_name:
                        continue
                    if pa_id in already_handled:
                        continue  # Part of primary connector, not a ghost
                    self._delete_connector_via_powerapps(pa_id, environment_id)
                    ghost_results.append(f"powerapps:{pa_id}")

            if ghost_results:
                results["ghost_cleanup"] = ghost_results

        return results

    def _delete_connector_via_powerapps(
        self,
        connector_id: str,
        environment_id: str
    ) -> None:
        """
        Delete a custom connector via Power Apps API.

        Args:
            connector_id: The connector's unique identifier
            environment_id: Environment ID

        Raises:
            ClientError: If deletion fails
        """
        powerapps_token = get_access_token("https://service.powerapps.com/")

        url = (
            f"https://api.powerapps.com/providers/Microsoft.PowerApps/apis/{connector_id}"
            f"?api-version=2016-11-01"
            f"&$filter=environment eq '{environment_id}'"
        )

        headers = {
            "Authorization": f"Bearer {powerapps_token}",
            "Accept": "application/json",
        }

        try:
            response = self._http_client.delete(url, headers=headers, timeout=30.0)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                if "error" in error_body:
                    error_detail = error_body["error"].get("message", str(error_body))
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to delete connector: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Request failed: {e}")

    # =========================================================================
    # Flow Methods
    # =========================================================================

    def list_flows(self, category: int = None) -> list[dict]:
        """
        List Power Automate cloud flows in the environment.

        Args:
            category: Optional filter by flow category:
                - 0: Standard (automated/scheduled flows)
                - 5: Instant (button/HTTP triggered flows)
                - 6: Business process flows

        Returns:
            List of workflow (flow) records

        Note:
            Flows that can be used as agent tools are typically category 5 (instant)
            or flows with HTTP triggers.
        """
        endpoint = "workflows?$filter=type eq 1"  # type 1 = Flow (vs 2 = Action)
        if category is not None:
            endpoint += f" and category eq {category}"
        endpoint += "&$orderby=name"
        result = self.get(endpoint)
        return result.get("value", [])

    def get_flow(self, workflow_id: str) -> dict:
        """
        Get a specific flow by ID.

        Args:
            workflow_id: The workflow's unique identifier (GUID)

        Returns:
            Workflow (flow) record
        """
        return self.get(f"workflows({workflow_id})")

    # =========================================================================
    # Agent Flow Methods (Copilot Studio Agent Flows)
    # =========================================================================

    def list_agent_flows(self, include_clientdata: bool = False) -> list[dict]:
        """
        List Copilot Studio agent flows in the environment.

        Agent flows are Power Automate flows designed specifically to work with
        Copilot Studio agents. They have the "When an agent calls the flow"
        trigger and can be added as tools to agents.

        Agent flows are identified by:
        - category = 5 (Modern flows)
        - modernflowtype = 1 (CopilotStudioFlow)

        Status values:
        - statecode=0: Draft - flow exists but has not been published
        - statecode=1: Activated - flow is published and running

        Type values:
        - type=1: Definition - the editable draft version
        - type=2: Activation - the published/running version

        Uses RetrieveUnpublishedMultiple to return both draft and published
        agent flows. A regular GET /workflows query only returns published flows.

        Args:
            include_clientdata: If True, include the flow definition (clientdata)
                which contains trigger information.

        Returns:
            List of agent flow (workflow) records
        """
        # Use RetrieveUnpublishedMultiple to get both draft and published flows
        # Regular GET /workflows only returns published (activated) flows
        select_fields = (
            "workflowid,name,description,statecode,statuscode,type,"
            "parentworkflowid,createdon,modifiedon"
        )
        if include_clientdata:
            select_fields += ",clientdata"

        endpoint = (
            "workflows/Microsoft.Dynamics.CRM.RetrieveUnpublishedMultiple()"
            f"?$filter=category eq 5 and modernflowtype eq 1"
            f"&$select={select_fields}"
            "&$orderby=modifiedon desc"
            "&$expand=owninguser($select=systemuserid,fullname)"
        )
        result = self.get(endpoint)
        return result.get("value", [])

    def get_agent_flow(self, workflow_id: str) -> dict:
        """
        Get a specific agent flow by ID.

        Args:
            workflow_id: The agent flow's unique identifier (GUID)

        Returns:
            Agent flow (workflow) record
        """
        return self.get(f"workflows({workflow_id})")

    def update_agent_flow(
        self,
        workflow_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict:
        """
        Update an agent flow's properties.

        NOTE: This only works for PUBLISHED (activated) flows. Draft flows
        (statecode=0, type=1) cannot be updated via the public Dataverse API.
        The Copilot Studio UI uses internal APIs for draft flow updates.

        Args:
            workflow_id: The agent flow's unique identifier (GUID)
            name: New name for the flow (optional)
            description: New description for the flow (optional)

        Returns:
            Empty dict on success (PATCH returns 204 No Content)

        Raises:
            ClientError: If the update fails or if trying to update a draft flow
        """
        data = {}
        if name is not None:
            data["name"] = name
        if description is not None:
            data["description"] = description

        if not data:
            raise ClientError("At least one of --name or --description must be provided")

        # Check if this is a draft flow (type=1) which cannot be updated via API
        # Use RetrieveUnpublished since draft flows return 404 on normal GET
        try:
            flow = self.get(
                f"workflows({workflow_id})/Microsoft.Dynamics.CRM.RetrieveUnpublished()"
                f"?$select=type,statecode,name"
            )
            flow_type = flow.get("type")
            statecode = flow.get("statecode")

            # type=1 is Definition (draft), type=2 is Activation (published)
            # statecode=0 is Draft, statecode=1 is Activated
            if flow_type == 1 and statecode == 0:
                raise ClientError(
                    f"Cannot update draft flow '{flow.get('name', workflow_id)}' via API. "
                    f"Draft flows (type=1, statecode=0) can only be updated through the "
                    f"Copilot Studio UI at: https://copilotstudio.microsoft.com"
                )
        except ClientError:
            raise
        except Exception:
            # If we can't check the flow state, proceed with the update
            # and let it fail naturally if it's a draft
            pass

        self.patch(f"workflows({workflow_id})", data)
        return {}

    def export_agent_flow(self, workflow_id: str, draft: bool = False) -> dict:
        """
        Export an agent flow's definition.

        Retrieves the flow's clientdata field which contains the JSON definition
        of the flow including triggers, actions, and connection references.

        Args:
            workflow_id: The agent flow's unique identifier (GUID)
            draft: If True, retrieve the draft version instead of published.
                   For solution-aware flows, draft and published versions are
                   stored as separate workflow records.

        Returns:
            Dict containing:
                - name: Flow display name
                - workflowid: Flow GUID
                - description: Flow description (if any)
                - definition: Parsed JSON flow definition
                - connectionReferences: Connection references used by the flow
                - raw_clientdata: Original clientdata string (for debugging)
                - version: "draft" or "published" indicating which version

        Raises:
            ClientError: If the flow is not found or clientdata is missing
        """
        # Fetch workflow with clientdata field, including type and parentworkflowid
        endpoint = (
            f"workflows({workflow_id})"
            "?$select=workflowid,name,description,clientdata,statecode,category,type,parentworkflowid"
        )
        flow = self.get(endpoint)

        if draft:
            # For draft version, we need to find the definition record (type=1)
            # If current workflow is type=2 (Activation), find its parent
            # If current workflow is type=1 (Definition), use it directly
            workflow_type = flow.get("type")

            if workflow_type == 2:
                # This is an activation, get the parent (definition) workflow
                parent_id = flow.get("_parentworkflowid_value") or flow.get("parentworkflowid")
                if parent_id:
                    endpoint = (
                        f"workflows({parent_id})"
                        "?$select=workflowid,name,description,clientdata,statecode,category,type"
                    )
                    flow = self.get(endpoint)
                else:
                    # Try to find definition by name with type=1
                    flow_name = flow.get("name", "")
                    search_endpoint = (
                        f"workflows?$filter=name eq '{flow_name}' and type eq 1"
                        "&$select=workflowid,name,description,clientdata,statecode,category,type"
                        "&$top=1"
                    )
                    results = self.get(search_endpoint)
                    flows = results.get("value", [])
                    if flows:
                        flow = flows[0]
                    else:
                        raise ClientError(
                            f"Draft version not found for workflow {workflow_id}. "
                            "The flow may not have a separate draft version."
                        )

        if not flow:
            raise ClientError(f"Agent flow {workflow_id} not found")

        actual_workflow_id = flow.get("workflowid", workflow_id)
        clientdata_str = flow.get("clientdata", "")
        if not clientdata_str:
            raise ClientError(
                f"Agent flow {actual_workflow_id} has no clientdata. "
                "This may not be a modern flow or the definition is empty."
            )

        # Parse the clientdata JSON
        try:
            clientdata = json.loads(clientdata_str)
        except json.JSONDecodeError as e:
            raise ClientError(f"Failed to parse flow clientdata: {e}")

        # Extract the flow definition and connection references
        # clientdata typically has structure: {"properties": {"definition": {...}, "connectionReferences": {...}}}
        properties = clientdata.get("properties", {})
        definition = properties.get("definition", clientdata.get("definition", {}))
        connection_refs = properties.get(
            "connectionReferences",
            clientdata.get("connectionReferences", {})
        )

        # Determine version type based on workflow type field
        workflow_type = flow.get("type")
        version = "draft" if workflow_type == 1 else "published" if workflow_type == 2 else "unknown"

        return {
            "name": flow.get("name", ""),
            "workflowid": actual_workflow_id,
            "description": flow.get("description", ""),
            "definition": definition,
            "connectionReferences": connection_refs,
            "raw_clientdata": clientdata_str,
            "version": version,
            "statecode": flow.get("statecode"),
            "type": workflow_type,
        }

    def import_agent_flow(
        self,
        workflow_id: str,
        definition: dict,
        connection_references: Optional[dict] = None,
    ) -> dict:
        """
        Import/update an agent flow's definition.

        Updates the flow's clientdata field with a new definition. Can optionally
        update connection references as well.

        Args:
            workflow_id: The agent flow's unique identifier (GUID)
            definition: The flow definition dict (triggers, actions, parameters, etc.)
            connection_references: Optional dict of connection references. If not
                provided, existing connection references are preserved.

        Returns:
            Dict with update status

        Raises:
            ClientError: If the flow is not found or update fails
        """
        # First, get the current flow to retrieve existing clientdata structure
        current_flow = self.export_agent_flow(workflow_id)

        # If no connection_references provided, preserve existing ones
        if connection_references is None:
            connection_references = current_flow.get("connectionReferences", {})

        # Build the new clientdata structure
        # schemaVersion is required at the root level
        new_clientdata = {
            "properties": {
                "definition": definition,
                "connectionReferences": connection_references,
            },
            "schemaVersion": "1.0.0.0",
        }

        # Serialize to JSON string for the PATCH request
        clientdata_str = json.dumps(new_clientdata)

        # CRITICAL: Auto-associate connection references with bot components BEFORE updating
        # The workflow definition validation requires connection references to be associated
        # with the workflow's bot components, otherwise the save will fail with
        # "API connection reference could not be found" error
        if connection_references:
            self._auto_associate_workflow_connection_references(
                workflow_id, connection_references
            )

        # Update the workflow
        self.patch(f"workflows({workflow_id})", {"clientdata": clientdata_str})

        return {
            "workflowid": workflow_id,
            "status": "updated",
            "message": f"Flow definition updated successfully",
        }

    def create_agent_flow(
        self,
        name: str,
        definition: Optional[dict] = None,
        connection_references: Optional[dict] = None,
        description: Optional[str] = None,
    ) -> dict:
        """
        Create a new Copilot Studio agent flow.

        Creates a new modern flow configured as a CopilotStudioFlow that can be
        used as a tool in Copilot Studio agents. The flow is created in Draft
        state (statecode=0).

        Agent flows have the "When an agent calls the flow" trigger type.

        Args:
            name: Display name for the agent flow
            definition: Optional flow definition dict (triggers, actions, parameters).
                       If not provided, creates an empty flow with a basic agent trigger.
            connection_references: Optional dict of connection references
            description: Optional description for the flow

        Returns:
            Dict containing:
                - workflowid: The created flow's unique identifier
                - name: Flow display name
                - status: "created"

        Raises:
            ClientError: If the creation fails
        """
        # Build default agent flow definition if not provided
        if definition is None:
            definition = {
                "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
                "contentVersion": "1.0.0.0",
                "triggers": {
                    "manual": {
                        "type": "Request",
                        "kind": "CopilotStudioAgent",
                        "inputs": {
                            "triggerAuthenticationType": "All",
                            "schema": {
                                "type": "object",
                                "properties": {}
                            }
                        }
                    }
                },
                "actions": {},
                "parameters": {
                    "$authentication": {
                        "defaultValue": {},
                        "type": "SecureObject"
                    },
                    "$connections": {
                        "defaultValue": {},
                        "type": "Object"
                    }
                },
                "outputs": {}
            }

        # Build clientdata structure
        clientdata = {
            "properties": {
                "definition": definition,
                "connectionReferences": connection_references or {},
            },
            "schemaVersion": "1.0.0.0",
        }

        # Build workflow record
        workflow_data = {
            "name": name,
            "category": 5,  # Modern Flow
            "modernflowtype": 1,  # CopilotStudioFlow
            "type": 1,  # Definition (draft)
            "primaryentity": "none",
            "clientdata": json.dumps(clientdata),
        }

        if description:
            workflow_data["description"] = description

        # Create the workflow
        result = self.post("workflows", workflow_data, return_id=True)

        # Extract the workflow ID from the result
        workflow_id = None
        if result:
            workflow_id = result.get("workflowid") or result.get("id")

        return {
            "workflowid": workflow_id,
            "name": name,
            "status": "created",
        }

    def delete_agent_flow(self, workflow_id: str, force: bool = False) -> dict:
        """
        Delete an agent flow (draft or published).

        For published flows (statecode=1), the flow is deactivated first before
        deletion. For draft flows (statecode=0), the flow is deleted directly.

        Args:
            workflow_id: The agent flow's unique identifier (GUID)
            force: If True, skip confirmation and force deletion even if
                   the flow is published. Default is False.

        Returns:
            Dict containing:
                - workflowid: The deleted flow's ID
                - name: Flow display name
                - status: "deleted"
                - was_published: True if the flow was published before deletion

        Raises:
            ClientError: If the flow is not found or deletion fails
        """
        # Get flow info using RetrieveUnpublished to handle both draft and published
        try:
            flow = self.get(
                f"workflows({workflow_id})/Microsoft.Dynamics.CRM.RetrieveUnpublished()"
                f"?$select=workflowid,name,type,statecode,parentworkflowid"
            )
        except ClientError as e:
            if "404" in str(e):
                raise ClientError(f"Agent flow {workflow_id} not found")
            raise

        flow_name = flow.get("name", workflow_id)
        flow_type = flow.get("type")
        statecode = flow.get("statecode")
        parent_id = flow.get("_parentworkflowid_value") or flow.get("parentworkflowid")
        was_published = statecode == 1

        # If this is a type=2 (activation/published) record, we need to find
        # and delete the parent definition record as well
        definition_id = None
        activation_id = None

        if flow_type == 2:
            # This is the activation record - find the definition (draft)
            activation_id = workflow_id
            if parent_id:
                definition_id = parent_id
        elif flow_type == 1:
            # This is the definition record - check if there's an activation child
            definition_id = workflow_id
            # Search for activation record that has this as parent
            try:
                search_result = self.get(
                    f"workflows?$filter=parentworkflowid eq {workflow_id} and type eq 2"
                    f"&$select=workflowid&$top=1"
                )
                activations = search_result.get("value", [])
                if activations:
                    activation_id = activations[0].get("workflowid")
            except Exception:
                # If search fails, proceed without activation record
                pass

        # Deactivate published flow first (set statecode=0)
        # Only the activation record needs deactivation
        if activation_id and was_published:
            try:
                self.patch(f"workflows({activation_id})", {
                    "statecode": 0,
                    "statuscode": 1,  # Draft status
                })
            except ClientError as e:
                raise ClientError(
                    f"Failed to deactivate flow '{flow_name}' before deletion: {e}"
                )

        # Delete the activation record first if it exists (child must be deleted before parent)
        if activation_id:
            try:
                self._delete_workflow_record(activation_id)
            except ClientError as e:
                # If 404, it's already deleted or doesn't exist
                if "404" not in str(e):
                    raise ClientError(f"Failed to delete activation record: {e}")

        # Delete the definition record
        if definition_id:
            try:
                self._delete_workflow_record(definition_id)
            except ClientError as e:
                if "404" not in str(e):
                    raise ClientError(f"Failed to delete definition record: {e}")

        return {
            "workflowid": workflow_id,
            "name": flow_name,
            "status": "deleted",
            "was_published": was_published,
        }

    def enable_agent_flow(self, workflow_id: str) -> dict:
        """
        Enable (activate) an agent flow.

        Changes a draft flow to activated state so it can receive triggers
        and execute. This is required for flows created via the API before
        they can be tested or used.

        Args:
            workflow_id: The agent flow's unique identifier (GUID)

        Returns:
            Dict containing:
                - workflowid: The flow's ID
                - name: Flow display name
                - status: "Activated"
                - was_draft: True if the flow was in draft state before

        Raises:
            ClientError: If the flow is not found or activation fails
        """
        # Get flow info using RetrieveUnpublished to handle both draft and published
        try:
            flow = self.get(
                f"workflows({workflow_id})/Microsoft.Dynamics.CRM.RetrieveUnpublished()"
                f"?$select=workflowid,name,type,statecode,parentworkflowid"
            )
        except ClientError as e:
            if "404" in str(e):
                raise ClientError(f"Agent flow {workflow_id} not found")
            raise

        flow_name = flow.get("name", workflow_id)
        flow_type = flow.get("type")
        statecode = flow.get("statecode")
        was_draft = statecode == 0

        # If already activated, nothing to do
        if statecode == 1:
            return {
                "workflowid": workflow_id,
                "name": flow_name,
                "status": "Activated",
                "was_draft": False,
                "message": "Flow was already activated",
            }

        # Activate the flow by setting statecode=1
        try:
            self.patch(f"workflows({workflow_id})", {
                "statecode": 1,
                "statuscode": 2,  # Activated status
            })
        except ClientError as e:
            raise ClientError(
                f"Failed to activate flow '{flow_name}': {e}"
            )

        return {
            "workflowid": workflow_id,
            "name": flow_name,
            "status": "Activated",
            "was_draft": was_draft,
        }

    def disable_agent_flow(self, workflow_id: str) -> dict:
        """
        Disable (deactivate) an agent flow.

        Changes an activated flow back to draft state. The flow will no longer
        receive triggers or execute until re-enabled.

        Args:
            workflow_id: The agent flow's unique identifier (GUID)

        Returns:
            Dict containing:
                - workflowid: The flow's ID
                - name: Flow display name
                - status: "Draft"
                - was_activated: True if the flow was activated before

        Raises:
            ClientError: If the flow is not found or deactivation fails
        """
        # Get flow info using RetrieveUnpublished to handle both draft and published
        try:
            flow = self.get(
                f"workflows({workflow_id})/Microsoft.Dynamics.CRM.RetrieveUnpublished()"
                f"?$select=workflowid,name,type,statecode,parentworkflowid"
            )
        except ClientError as e:
            if "404" in str(e):
                raise ClientError(f"Agent flow {workflow_id} not found")
            raise

        flow_name = flow.get("name", workflow_id)
        statecode = flow.get("statecode")
        was_activated = statecode == 1

        # If already draft, nothing to do
        if statecode == 0:
            return {
                "workflowid": workflow_id,
                "name": flow_name,
                "status": "Draft",
                "was_activated": False,
                "message": "Flow was already in draft state",
            }

        # Deactivate the flow by setting statecode=0
        try:
            self.patch(f"workflows({workflow_id})", {
                "statecode": 0,
                "statuscode": 1,  # Draft status
            })
        except ClientError as e:
            raise ClientError(
                f"Failed to deactivate flow '{flow_name}': {e}"
            )

        return {
            "workflowid": workflow_id,
            "name": flow_name,
            "status": "Draft",
            "was_activated": was_activated,
        }

    def _delete_workflow_record(self, workflow_id: str) -> None:
        """
        Delete a workflow record via the Dataverse API.

        Args:
            workflow_id: The workflow's unique identifier (GUID)

        Raises:
            ClientError: If deletion fails
        """
        try:
            self.delete(f"workflows({workflow_id})", verify=False)
        except ClientError as e:
            error_str = str(e)
            # Provide clearer error message for null definition flows
            if "DefinitionRequestMissingFields" in error_str:
                raise ClientError(
                    f"Cannot delete flow {workflow_id}: This flow has a null definition "
                    "which prevents deletion via the API. Delete it manually via "
                    "Copilot Studio at https://copilotstudio.microsoft.com"
                )
            raise

    def _get_workflow_botcomponents(self, workflow_id: str) -> list[dict]:
        """
        Get bot components associated with a workflow via the botcomponent_workflow M2M relationship.

        Args:
            workflow_id: The workflow's unique identifier (GUID)

        Returns:
            List of bot component records associated with the workflow
        """
        try:
            url = f"{self.api_url}/workflows({workflow_id})/botcomponent_workflow"
            headers = self._get_headers()
            response = self._http_client.get(url, headers=headers, timeout=60.0)
            response.raise_for_status()
            return response.json().get("value", [])
        except Exception:
            return []

    def _auto_associate_workflow_connection_references(
        self,
        workflow_id: str,
        connection_references: dict,
    ) -> None:
        """
        Automatically associate connection references with bot components linked to a workflow.

        When importing a flow definition with new connection references, those references
        must be associated with the flow's bot components via the botcomponent_connectionreference
        M2M relationship for connector tools to work at runtime.

        Args:
            workflow_id: The workflow's unique identifier (GUID)
            connection_references: Dict of connection references from the flow definition
                                   Keys are logical names, values contain connection ref config
        """
        if not connection_references:
            return

        # Get bot components associated with this workflow
        botcomponents = self._get_workflow_botcomponents(workflow_id)
        if not botcomponents:
            return

        # For each connection reference in the definition, find it and associate with bot components
        for logical_name, ref_config in connection_references.items():
            # Try to find the connection reference by logical name
            conn_ref = self._find_connection_reference_by_logical_name(logical_name)
            if not conn_ref:
                # Also try the connectionReferenceLogicalName from the config if different
                nested_logical_name = ref_config.get("connection", {}).get(
                    "connectionReferenceLogicalName"
                )
                if nested_logical_name and nested_logical_name != logical_name:
                    conn_ref = self._find_connection_reference_by_logical_name(nested_logical_name)

            if not conn_ref:
                continue

            conn_ref_id = conn_ref.get("connectionreferenceid")
            if not conn_ref_id:
                continue

            # Associate with each bot component linked to this workflow
            for botcomponent in botcomponents:
                botcomponent_id = botcomponent.get("botcomponentid")
                if botcomponent_id:
                    try:
                        self._associate_botcomponent_connectionreference(
                            botcomponent_id, conn_ref_id
                        )
                    except Exception:
                        # Association may already exist or fail for other reasons
                        # Continue with other associations
                        pass

    # =========================================================================
    # Prompt Methods (AI Builder Prompts)
    # =========================================================================

    # GptPowerPrompt template ID - identifies AI Builder prompts
    GPT_POWER_PROMPT_TEMPLATE_ID = "edfdb190-3791-45d8-9a6c-8f90a37c278a"

    def list_prompts(self) -> list[dict]:
        """
        List AI Builder prompts available as agent tools.

        AI Builder prompts are custom prompts that can be attached to
        Copilot Studio agents as tools. They use GPT models to perform
        specific tasks like classification, extraction, or content generation.

        Returns:
            List of prompt (msdyn_aimodel) records with GptPowerPrompt template

        Note:
            Prompts are stored as msdyn_aimodels with the GptPowerPrompt template.
            This filters out other AI model types like Invoice Processing, etc.
        """
        result = self.get(
            f"msdyn_aimodels?$filter=_msdyn_templateid_value eq {self.GPT_POWER_PROMPT_TEMPLATE_ID}"
            f"&$orderby=msdyn_name"
        )
        return result.get("value", [])

    def get_prompt(self, prompt_id: str) -> dict:
        """
        Get a specific AI Builder prompt by ID.

        Args:
            prompt_id: The prompt's unique identifier (GUID)

        Returns:
            Prompt (msdyn_aimodel) record
        """
        return self.get(f"msdyn_aimodels({prompt_id})")

    def delete_prompt(self, prompt_id: str) -> None:
        """
        Delete an AI Builder prompt by ID.

        Args:
            prompt_id: The prompt's unique identifier (GUID)

        Note:
            Managed (system) prompts cannot be deleted.
            Only custom prompts can be deleted.
        """
        self.delete(f"msdyn_aimodels({prompt_id})")

    def get_prompt_configuration(self, prompt_id: str, active_only: bool = True) -> dict:
        """
        Get the AI Configuration for a prompt, including the prompt text.

        Args:
            prompt_id: The prompt's unique identifier (GUID)
            active_only: If True (default), return the published/active configuration.
                        If False, return the most recently modified configuration.

        Returns:
            Dict containing:
                - configuration_id: The AI configuration ID
                - prompt_text: The full prompt text (all literal parts concatenated)
                - prompt_parts: The raw prompt parts array
                - custom_configuration: The full custom configuration JSON
                - model_type: The GPT model type (e.g., gpt-41-mini)
                - status: Status code (0=Draft, 7=Published, etc.)
                - version: Version string (major.minor)

        Raises:
            ClientError: If no configuration found for the prompt
        """
        import json

        # Get AI configurations for this model
        # Type 190690001 = RunConfiguration (the ones with prompt text)
        result = self.get(
            f"msdyn_aiconfigurations?"
            f"$filter=_msdyn_aimodelid_value eq {prompt_id} and msdyn_type eq 190690001"
            f"&$orderby=modifiedon desc"
        )
        configs = result.get("value", [])

        if not configs:
            raise ClientError(f"No AI configuration found for prompt {prompt_id}")

        # Find the appropriate config
        config = None
        if active_only:
            # Look for published config (statuscode=7)
            for c in configs:
                if c.get("statuscode") == 7:
                    config = c
                    break
            # Fall back to most recent if no published config
            if not config:
                config = configs[0]
        else:
            config = configs[0]

        config_id = config.get("msdyn_aiconfigurationid")
        custom_config_str = config.get("msdyn_customconfiguration", "")
        status = config.get("statuscode", 0)
        major = config.get("msdyn_majoriterationnumber", 1)
        minor = config.get("msdyn_minoriterationnumber", 0)

        # Parse the custom configuration JSON
        prompt_text = ""
        prompt_parts = []
        model_type = ""
        custom_config = {}

        if custom_config_str:
            try:
                custom_config = json.loads(custom_config_str)
                prompt_parts = custom_config.get("prompt", [])

                # Extract just the literal text parts to form the prompt text
                text_parts = []
                for part in prompt_parts:
                    if part.get("type") == "literal":
                        text_parts.append(part.get("text", ""))

                prompt_text = "".join(text_parts)

                # Get model type
                model_params = custom_config.get("modelParameters", {})
                model_type = model_params.get("modelType", "")

            except json.JSONDecodeError:
                pass

        return {
            "configuration_id": config_id,
            "prompt_text": prompt_text,
            "prompt_parts": prompt_parts,
            "custom_configuration": custom_config,
            "model_type": model_type,
            "status": status,
            "version": f"{major}.{minor}",
        }

    def publish_prompt(self, prompt_id: str) -> dict:
        """
        Publish an AI Builder prompt.

        Args:
            prompt_id: The prompt's unique identifier (GUID)

        Returns:
            Dict with publish status and details

        Raises:
            ClientError: If publish fails
        """
        import time

        # Get the configuration info
        config_info = self.get_prompt_configuration(prompt_id, active_only=False)
        config_id = config_info["configuration_id"]
        status = config_info["status"]
        version = config_info["version"]

        if status == 7:  # Already published
            return {
                "status": "already_published",
                "config_id": config_id,
                "version": version,
            }

        # Publish the configuration
        self.post(
            f"msdyn_aiconfigurations({config_id})/Microsoft.Dynamics.CRM.PublishAIConfiguration",
            {"version": version}
        )

        # Wait for publish to complete
        for _ in range(30):
            config = self.get(f"msdyn_aiconfigurations({config_id})")
            current_status = config.get("statuscode")
            if current_status == 7:  # Published
                return {
                    "status": "published",
                    "config_id": config_id,
                    "version": version,
                }
            # Status codes: 10=PublishFailed, 11=UnpublishFailed, 12=CancelFailed, 13=DeleteFailed
            if current_status == 10:
                raise ClientError("Publish failed (status 10: PublishFailed). The AI model may need to be activated first, or there may be a configuration issue.")
            if current_status in [11, 12, 13]:
                raise ClientError(f"Publish failed with status {current_status}")
            time.sleep(1)

        raise ClientError("Publish timed out - status did not change to Published")

    def update_prompt(
        self,
        prompt_id: str,
        prompt_text: Optional[str] = None,
        model_type: Optional[str] = None,
        temperature: Optional[float] = None,
        input_types: Optional[dict[str, str]] = None,
        code_interpreter: Optional[bool] = None,
        publish: bool = True,
    ) -> None:
        """
        Update an AI Builder prompt's text, model type, temperature, input types, or code interpreter setting.

        This method handles the full publish workflow:
        1. Finds the active (published) configuration
        2. Unpublishes it if currently published
        3. Updates the configuration
        4. Republishes it (if publish=True)

        Args:
            prompt_id: The prompt's unique identifier (GUID)
            prompt_text: New prompt text (replaces all literal parts with single text)
            model_type: New model type (gpt-41-mini, gpt-41, gpt-5-chat, gpt-5-reasoning)
            temperature: Model temperature 0.0-1.0 for controlling randomness
            input_types: Dict mapping input IDs to new types (e.g., {"content": "text"})
                         Valid types: "text", "document"
            code_interpreter: Enable or disable code interpreter for Python execution.
                              When enabled, prompts can be invoked via Dataverse Predict API.
            publish: If True (default), republish after updating

        Raises:
            ClientError: If update fails or no configuration found
        """
        import json
        import time

        if not prompt_text and not model_type and temperature is None and not input_types and code_interpreter is None:
            raise ClientError("Must provide prompt_text, model_type, temperature, input_types, or code_interpreter to update")

        # Get current active configuration
        config_info = self.get_prompt_configuration(prompt_id, active_only=True)
        config_id = config_info["configuration_id"]
        custom_config = config_info["custom_configuration"]
        status = config_info["status"]
        version = config_info["version"]

        if not custom_config:
            raise ClientError("No custom configuration found for prompt")

        # If published, unpublish first
        if status == 7:  # Published
            self.post(
                f"msdyn_aiconfigurations({config_id})/Microsoft.Dynamics.CRM.UnpublishAIConfiguration",
                {"version": version}
            )
            # Wait for unpublish to complete
            for _ in range(15):
                config = self.get(f"msdyn_aiconfigurations({config_id})")
                if config.get("statuscode") != 4:  # 4 = Unpublishing
                    break
                time.sleep(1)

        # Update prompt text if provided
        if prompt_text is not None:
            # Get existing input variables from prompt parts
            input_vars = [
                part for part in custom_config.get("prompt", [])
                if part.get("type") == "inputVariable"
            ]

            # Create new prompt parts with the new text
            new_prompt_parts = [{"type": "literal", "text": prompt_text}]

            # Append any input variables that were in the original
            for var in input_vars:
                new_prompt_parts.append(var)

            custom_config["prompt"] = new_prompt_parts

        # Update model type if provided
        if model_type is not None:
            if "modelParameters" not in custom_config:
                custom_config["modelParameters"] = {}
            custom_config["modelParameters"]["modelType"] = model_type

        # Update temperature if provided
        if temperature is not None:
            if "modelParameters" not in custom_config:
                custom_config["modelParameters"] = {}
            custom_config["modelParameters"]["temperature"] = temperature

        # Update input types if provided
        if input_types is not None:
            valid_types = {"text", "document"}
            definitions = custom_config.get("definitions", {})
            inputs = definitions.get("inputs", [])

            for input_id, new_type in input_types.items():
                if new_type not in valid_types:
                    raise ClientError(f"Invalid input type '{new_type}'. Valid types: {', '.join(valid_types)}")

                # Find and update the input
                found = False
                for inp in inputs:
                    if inp.get("id") == input_id:
                        inp["type"] = new_type
                        found = True
                        break

                if not found:
                    raise ClientError(f"Input '{input_id}' not found in prompt. Available inputs: {[i.get('id') for i in inputs]}")

            # Write back the updated definitions
            custom_config["definitions"] = definitions

        # Update code interpreter setting if provided
        # Note: The exact property location is undocumented by Microsoft.
        # We try setting it at root level as 'isCodeInterpreterEnabled' based on
        # patterns seen in M365 Copilot declarative agents.
        if code_interpreter is not None:
            # Set at root level of customConfiguration
            custom_config["isCodeInterpreterEnabled"] = code_interpreter
            # Also set in modelParameters for backwards compatibility
            if "modelParameters" not in custom_config:
                custom_config["modelParameters"] = {}
            custom_config["modelParameters"]["codeInterpreter"] = code_interpreter

        # Update the configuration
        update_data = {
            "msdyn_customconfiguration": json.dumps(custom_config)
        }
        self.patch(f"msdyn_aiconfigurations({config_id})", update_data)

        # Republish if requested
        if publish:
            self.post(
                f"msdyn_aiconfigurations({config_id})/Microsoft.Dynamics.CRM.PublishAIConfiguration",
                {"version": version}
            )
            # Wait for publish to complete
            for _ in range(30):
                config = self.get(f"msdyn_aiconfigurations({config_id})")
                current_status = config.get("statuscode")
                if current_status == 7:  # Published
                    break
                # Status codes: 10=PublishFailed, 11=UnpublishFailed, 12=CancelFailed, 13=DeleteFailed
                if current_status == 10:
                    raise ClientError("Publish failed (status 10: PublishFailed). The AI model may need to be activated first.")
                if current_status in [11, 12, 13]:
                    raise ClientError(f"Publish failed with status {current_status}")
                time.sleep(1)

    def create_prompt(
        self,
        name: str,
        prompt_text: str,
        inputs: Optional[list[dict]] = None,
        model_type: str = "gpt-41-mini",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        response_format: str = "text",
    ) -> dict:
        """
        Create a new AI Builder prompt.

        Uses the AIModelPublish action to create and publish a new prompt.

        Args:
            name: Display name for the prompt
            prompt_text: The prompt instruction text
            inputs: List of input definitions, each with:
                - id: Input identifier (e.g., "content")
                - displayName: Display name (e.g., "Content")
                - description: Optional description
                - type: Input type - "text" or "document" (default: "text")
            model_type: GPT model type (default: "gpt-41-mini")
                Options: gpt-41-mini, gpt-41, gpt-5-chat, gpt-5-reasoning
            temperature: Model temperature 0.0-1.0 (default: 0)
            max_tokens: Maximum tokens in response (default: 2000)
            top_p: Top-p (nucleus) sampling 0.0-1.0 (default: 1.0)
            response_format: Output format - "text" or "json" (default: "text")

        Returns:
            Dict containing:
                - model_id: The created AI model ID
                - name: The prompt name

        Raises:
            ClientError: If creation fails

        Example:
            client.create_prompt(
                name="Classify Content",
                prompt_text="Classify the following content into categories...",
                inputs=[
                    {"id": "content", "displayName": "Content", "type": "text"}
                ],
                temperature=0,
                max_tokens=2000
            )
        """
        import json
        import uuid
        import time

        # Generate a new model ID
        model_id = str(uuid.uuid4())

        # Build the custom configuration
        # Start with prompt parts - the literal text
        prompt_parts = [{"type": "literal", "text": prompt_text}]

        # Build input definitions
        input_defs = []
        if inputs:
            for inp in inputs:
                input_def = {
                    "id": inp.get("id", "input"),
                    "displayName": inp.get("displayName", inp.get("id", "Input")),
                    "type": inp.get("type", "text"),
                }
                if inp.get("description"):
                    input_def["description"] = inp["description"]
                input_defs.append(input_def)

                # Add input variable reference to prompt parts
                prompt_parts.append({
                    "type": "inputVariable",
                    "id": inp.get("id", "input"),
                })

        # Build output definition based on response format
        output_def = {
            "id": "response",
            "displayName": "Response",
            "type": response_format,
        }

        # Build the full custom configuration
        # Use provided values or defaults
        temp_value = temperature if temperature is not None else 0
        max_tokens_value = max_tokens if max_tokens is not None else 2000

        # Build model parameters
        model_params = {
            "modelType": model_type,
            "temperature": temp_value,
            "maxTokens": max_tokens_value,
        }

        # Add top_p if specified (omit to use model default)
        if top_p is not None:
            model_params["topP"] = top_p

        custom_config = {
            # REQUIRED: Version identifier for GPT prompt configurations
            # Without this, publish fails with "Unsupported custom config version"
            "version": "GptDynamicPrompt-1",
            "modelParameters": model_params,
            "prompt": prompt_parts,
            "definitions": {
                "inputs": input_defs,
                "outputs": [output_def],
            },
        }

        # Build the run configuration (minimal)
        run_config = {
            "schemaVersion": "1.0",
        }

        # Generate a run configuration ID (required by the API)
        run_config_id = str(uuid.uuid4())

        # Call AIModelPublish action
        try:
            result = self.post(
                "AIModelPublish",
                {
                    "TemplateId": self.GPT_POWER_PROMPT_TEMPLATE_ID,
                    "ModelId": model_id,
                    "ModelName": name,
                    "CustomConfiguration": json.dumps(custom_config),
                    "RunConfiguration": json.dumps(run_config),
                    "RunConfigurationId": run_config_id,
                }
            )

            # The result should contain the created model info
            created_model_id = result.get("msdyn_aimodelid", model_id)

            # Wait for the model to be published
            for _ in range(30):
                try:
                    model = self.get_prompt(created_model_id)
                    if model.get("statecode") == 1:  # Active
                        break
                except Exception:
                    pass
                time.sleep(1)

            return {
                "model_id": created_model_id,
                "name": name,
            }

        except Exception as e:
            raise ClientError(f"Failed to create prompt: {e}")

    def run_prompt(
        self,
        prompt_id: str,
        inputs: dict[str, Any],
        wait: bool = True,
        poll_interval: float = 2.0,
        timeout: float = 300.0,
    ) -> dict:
        """
        Run an AI Builder prompt using the Dataverse Predict action.

        Invokes the prompt with the provided inputs and returns the generated response.
        Supports both synchronous (wait for result) and asynchronous (background) execution.

        IMPORTANT: This API currently works for code-interpreter-enabled prompts.
        Standard GPT prompts (GptPowerPrompt template) may require additional
        undocumented parameters. Microsoft recommends using Power Automate flows
        or Power Apps for invoking standard prompts.

        Args:
            prompt_id: The prompt's unique identifier (GUID)
            inputs: Dictionary of input name to value mappings.
                    Keys should match the input IDs defined in the prompt.
                    Example: {"content": "Text to analyze", "category": "news"}
            wait: If True (default), wait for completion and return the result.
                  If False, return immediately with polling information for async tracking.
            poll_interval: Seconds between polling attempts when wait=True (default: 2.0)
            timeout: Maximum seconds to wait for completion when wait=True (default: 300)

        Returns:
            Dict containing:
                - status: "Success" or "Error"
                - text: The generated text response (if successful)
                - mimetype: Response MIME type (e.g., "text/markdown")
                - finish_reason: Why the generation stopped (e.g., "stop")
                - raw_response: Full responsev2 object for advanced use cases

            For async (wait=False) when polling is needed:
                - status: "Pending"
                - poll_url: URL to poll for results
                - retry_after: Suggested seconds to wait before polling

        Raises:
            ClientError: If the prompt execution fails

        Example:
            # Synchronous execution (code-interpreter enabled prompts)
            result = client.run_prompt(
                prompt_id="12345678-1234-1234-1234-123456789abc",
                inputs={"markdown_content": "# Hello World"}
            )
            print(result["text"])

            # Asynchronous execution
            result = client.run_prompt(
                prompt_id="12345678-1234-1234-1234-123456789abc",
                inputs={"content": "Long document..."},
                wait=False
            )
            if result["status"] == "Pending":
                # Poll at result["poll_url"] later
                pass
        """
        import time

        # Build the requestv2 payload with expando type annotation
        # For GPT prompts, the structure appears to be different from code interpreter prompts.
        # Based on Power Automate connector patterns, inputs go into a nested structure.

        # Build the inner inputs object
        inputs_obj = {
            "@odata.type": "#Microsoft.Dynamics.CRM.expando",
        }
        for input_id, input_value in inputs.items():
            if isinstance(input_value, dict):
                nested = {"@odata.type": "#Microsoft.Dynamics.CRM.expando"}
                nested.update(input_value)
                inputs_obj[input_id] = nested
            else:
                inputs_obj[input_id] = input_value

        # Wrap in the requestv2 structure
        request_v2 = {
            "@odata.type": "#Microsoft.Dynamics.CRM.expando",
        }
        request_v2.update(inputs_obj)

        # Build the Predict request payload
        payload = {
            "version": "2.0",
            "requestv2": request_v2,
        }

        # Call the Predict action bound to the msdyn_aimodel entity
        # Format: msdyn_aimodels(<id>)/Microsoft.Dynamics.CRM.Predict
        endpoint = f"msdyn_aimodels({prompt_id})/Microsoft.Dynamics.CRM.Predict"

        start_time = time.time()

        try:
            response = self.post(endpoint, payload)
        except ClientError as e:
            # Parse specific error codes from the response
            error_str = str(e)
            if "EntitlementNotAvailable" in error_str or "NoCapacity" in error_str:
                raise ClientError(
                    "AI Builder capacity exhausted. "
                    "Purchase more AI Builder credits or wait for capacity to be available."
                )
            if "MaxConcurrentPlexCallsReachedException" in error_str:
                raise ClientError(
                    "Too many concurrent requests. Please wait and try again."
                )
            raise

        # Check for async polling response (202)
        override_status = response.get("overrideHttpStatusCode")
        if override_status == 202:
            poll_url = response.get("overrideLocation", "")
            retry_after = response.get("overrideRetryAfter")

            if not wait:
                # Return polling info for async tracking
                return {
                    "status": "Pending",
                    "poll_url": poll_url,
                    "retry_after": float(retry_after) if retry_after else poll_interval,
                }

            # Poll until completion
            while True:
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    raise ClientError(f"Prompt execution timed out after {timeout} seconds")

                time.sleep(poll_interval)

                # Poll the provided URL
                try:
                    poll_response = self._http_client.get(
                        poll_url,
                        headers=self._get_headers(),
                    )
                    poll_response.raise_for_status()
                    response = poll_response.json()

                    # Check if still pending
                    if response.get("overrideHttpStatusCode") == 202:
                        continue  # Keep polling

                    # Got final response, break out of loop
                    break

                except Exception as poll_error:
                    raise ClientError(f"Polling failed: {poll_error}")

        # Parse the response
        responsev2 = response.get("responsev2", {})
        operation_status = responsev2.get("operationStatus", "")

        if operation_status == "Error":
            error_info = responsev2.get("error", {})
            error_message = error_info.get("message", "Unknown error")
            error_code = error_info.get("code", "Unknown")
            raise ClientError(f"Prompt execution failed: [{error_code}] {error_message}")

        # Extract prediction output
        prediction_output = responsev2.get("predictionOutput", {})

        result = {
            "status": operation_status,
            "text": prediction_output.get("text", ""),
            "mimetype": prediction_output.get("mimetype", ""),
            "finish_reason": prediction_output.get("finishReason", ""),
            "raw_response": responsev2,
        }

        # Include structured output if available
        structured_output = prediction_output.get("structuredOutput")
        if structured_output:
            result["structured_output"] = structured_output

        # Include files/artifacts if present
        files = prediction_output.get("files", [])
        if files:
            result["files"] = files

        artifacts = prediction_output.get("artifacts")
        if artifacts:
            result["artifacts"] = artifacts

        # Include code if present (for code interpreter enabled prompts)
        code = prediction_output.get("code")
        if code:
            result["code"] = code

        logs = prediction_output.get("logs")
        if logs:
            result["logs"] = logs

        return result

    def get_prompt_inputs(self, prompt_id: str) -> list[dict]:
        """
        Get the input definitions for a prompt.

        Args:
            prompt_id: The prompt's unique identifier (GUID)

        Returns:
            List of input definitions, each with:
                - id: Input identifier
                - displayName: Display name
                - type: Input type (text, document)
                - description: Optional description
        """
        config = self.get_prompt_configuration(prompt_id)
        custom_config = config.get("custom_configuration", {})
        definitions = custom_config.get("definitions", {})
        return definitions.get("inputs", [])

    # =========================================================================
    # REST API Methods (Custom Connectors)
    # =========================================================================

    def list_rest_apis(self) -> list[dict]:
        """
        List REST API tools (custom connectors) available for agents.

        REST API tools are custom connectors defined with OpenAPI specifications
        that can be attached to Copilot Studio agents as tools.

        Returns:
            List of connector records with connectortype=1 (CustomConnector)

        Note:
            These are custom connectors stored in Dataverse, not the Power Apps
            connector catalog (which is queried by list_connectors()).
        """
        result = self.get(
            "connectors?$filter=connectortype eq 1"
            "&$orderby=displayname"
        )
        return result.get("value", [])

    def get_rest_api(self, connector_id: str) -> dict:
        """
        Get a specific REST API tool (custom connector) by ID.

        Args:
            connector_id: The connector's unique identifier (GUID)

        Returns:
            Connector record
        """
        return self.get(f"connectors({connector_id})")

    def delete_rest_api(self, connector_id: str) -> None:
        """
        Delete a REST API tool (custom connector) by ID.

        Args:
            connector_id: The connector's unique identifier (GUID)
        """
        self.delete(f"connectors({connector_id})")

    # =========================================================================
    # MCP Server Methods (Model Context Protocol)
    # =========================================================================

    def list_mcp_servers(self, environment_id: Optional[str] = None) -> list[dict]:
        """
        List MCP (Model Context Protocol) servers available as agent tools.

        MCP servers are connectors that implement the Model Context Protocol,
        allowing agents to connect to external data sources and tools.

        Args:
            environment_id: Power Platform environment ID. If not provided,
                            will use DATAVERSE_ENVIRONMENT_ID from config.

        Returns:
            List of MCP server connector records from Power Apps API

        Note:
            MCP servers are identified by having 'mcp' in their connector ID,
            name, or description.
        """
        # Get all connectors from Power Apps API
        connectors = self.list_connectors(environment_id)

        # Filter for MCP servers
        mcp_servers = []
        for connector in connectors:
            name = connector.get("name", "")
            props = connector.get("properties", {})
            display_name = props.get("displayName", "")
            description = (props.get("description", "") or "").lower()

            # Check for MCP indicators
            is_mcp = False
            if "mcpserver" in name.lower():
                is_mcp = True
            elif "mcp" in name.lower() and name.startswith("shared_"):
                is_mcp = True
            elif "mcp" in display_name.lower():
                is_mcp = True
            elif "model context protocol" in description:
                is_mcp = True

            if is_mcp:
                mcp_servers.append(connector)

        return mcp_servers

    def get_mcp_server(self, connector_id: str) -> dict:
        """
        Get a specific MCP server connector by ID.

        Args:
            connector_id: The connector's unique identifier (e.g., shared_microsoftlearndocsmcpserver)

        Returns:
            MCP server connector record from Power Apps API
        """
        return self.get_connector(connector_id)

    # --- Dataverse mcpservers entity (custom MCP registrations) ---

    def create_mcp_server(
        self,
        name: str,
        url: str,
        description: Optional[str] = None,
        instructions: Optional[str] = None,
        scope: Optional[str] = None,
        audience: Optional[str] = None,
    ) -> dict:
        """
        Create a custom MCP server registration in Dataverse.

        Args:
            name: Display name for the MCP server
            url: The MCP server endpoint URL
            description: Optional description
            instructions: Optional instructions for agents using this server
            scope: Optional scope value
            audience: Optional audience value

        Returns:
            Created mcpserver record (with mcpserverid)
        """
        configuration = json.dumps({"url": url})

        data = {
            "name": name,
            "isremote": True,
            "servertype": 0,
            "configuration": configuration,
        }

        if description:
            data["description"] = description
        if instructions:
            data["instructions"] = instructions
        if scope:
            data["scope"] = scope
        if audience:
            data["audience"] = audience

        result = self.post("mcpservers", data, return_id=True)

        # If we only got an ID back (204 response), fetch the full record
        if result and "mcpserverid" not in result and "id" in result:
            try:
                result = self.get_mcp_server_record(result["id"])
            except Exception:
                pass  # Return the partial result if fetch fails

        return result

    def delete_mcp_server(self, mcp_server_id: str) -> None:
        """
        Delete a custom MCP server registration.

        Args:
            mcp_server_id: The mcpserver's unique identifier (GUID)
        """
        self.delete(f"mcpservers({mcp_server_id})")

    def get_mcp_server_record(self, mcp_server_id: str) -> dict:
        """
        Get a custom MCP server registration by ID from Dataverse.

        Args:
            mcp_server_id: The mcpserver's unique identifier (GUID)

        Returns:
            mcpserver record from Dataverse
        """
        return self.get(f"mcpservers({mcp_server_id})")

    def list_mcp_server_records(self) -> list[dict]:
        """
        List custom MCP server registrations from Dataverse.

        Returns:
            List of mcpserver records
        """
        params = [
            "$select=mcpserverid,name,description,instructions,isremote,servertype,configuration,createdon,modifiedon",
        ]
        endpoint = "mcpservers?" + "&".join(params)
        result = self.get(endpoint)
        return result.get("value", [])

    # =========================================================================
    # Transcript Methods
    # =========================================================================

    def list_transcripts(
        self,
        bot_id: Optional[str] = None,
        bot_name: Optional[str] = None,
        limit: int = 20,
        select: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        List conversation transcripts, optionally filtered by bot ID or name.

        Args:
            bot_id: Optional bot ID to filter transcripts
            bot_name: Optional bot name to filter transcripts (resolved to ID)
            limit: Maximum number of transcripts to return (default: 20)
            select: Optional list of fields to select

        Returns:
            List of transcript records

        Raises:
            ClientError: If bot_name is provided but no matching bot is found
        """
        # Resolve bot name to ID if provided
        filter_bot_id = bot_id
        if bot_name and not bot_id:
            bot = self.get_bot_by_name(bot_name)
            if not bot:
                raise ClientError(f"No bot found with name: {bot_name}")
            filter_bot_id = bot.get("botid")

        endpoint = "conversationtranscripts"
        params = []

        # Default fields if not specified
        if not select:
            select = [
                "conversationtranscriptid",
                "name",
                "conversationstarttime",
                "_bot_conversationtranscriptid_value",
                "schematype",
            ]
        params.append(f"$select={','.join(select)}")

        # Filter by bot if specified
        if filter_bot_id:
            params.append(f"$filter=_bot_conversationtranscriptid_value eq {filter_bot_id}")

        # Order by most recent first
        params.append("$orderby=conversationstarttime desc")
        params.append(f"$top={limit}")

        if params:
            endpoint += "?" + "&".join(params)

        result = self.get(endpoint)
        return result.get("value", [])

    def get_transcript(self, transcript_id: str) -> dict:
        """
        Get a single transcript with full content.

        Args:
            transcript_id: The transcript's unique identifier

        Returns:
            Transcript record including full content
        """
        return self.get(f"conversationtranscripts({transcript_id})")

    # =========================================================================
    # User and Environment Methods
    # =========================================================================

    def whoami(self) -> dict:
        """
        Get information about the current authenticated user.

        Returns:
            Dict with BusinessUnitId, UserId, and OrganizationId
        """
        return self.get("WhoAmI")

    def get_user_preferred_solution(self) -> Optional[str]:
        """
        Get the current user's preferred solution ID.

        The preferred solution is the default solution where new components
        are automatically added when created outside of a specific solution context.

        Returns:
            The solution ID (GUID) of the preferred solution, or None if not set
        """
        # Get current user's ID
        whoami = self.whoami()
        user_id = whoami.get("UserId")
        if not user_id:
            return None

        # Query usersettings for this user to get their preferred solution
        result = self.get(
            f"usersettingscollection?$filter=systemuserid eq {user_id}"
            "&$select=preferredsolution"
        )
        settings = result.get("value", [])
        if settings:
            # preferredsolution is a lookup field, the value is the solution ID
            return settings[0].get("_preferredsolution_value")
        return None

    def set_user_preferred_solution(self, solution_id: str) -> None:
        """
        Set the current user's preferred solution.

        Args:
            solution_id: The solution ID (GUID) to set as preferred
        """
        # Get current user's ID
        whoami = self.whoami()
        user_id = whoami.get("UserId")
        if not user_id:
            raise ClientError("Could not determine current user ID")

        # Update usersettings with the preferred solution
        # The preferredsolution field is a lookup, so we use @odata.bind syntax
        self.patch(
            f"usersettingscollection({user_id})",
            data={
                "preferredsolution@odata.bind": f"/solutions({solution_id})"
            }
        )

    def clear_user_preferred_solution(self) -> None:
        """
        Clear the current user's preferred solution (set to null).
        """
        # Get current user's ID
        whoami = self.whoami()
        user_id = whoami.get("UserId")
        if not user_id:
            raise ClientError("Could not determine current user ID")

        # Set preferredsolution to null
        self.patch(
            f"usersettingscollection({user_id})",
            data={
                "preferredsolution@odata.bind": None
            }
        )

    # =========================================================================
    # Solution Management Methods
    # =========================================================================

    def list_solutions(
        self,
        select: Optional[list[str]] = None,
        unmanaged_only: bool = False,
        include_invisible: bool = False,
        include_internal: bool = False,
    ) -> list[dict]:
        """
        List all solutions in the environment.

        Args:
            select: Optional list of fields to select
            unmanaged_only: If True, only return unmanaged solutions
            include_invisible: If True, include solutions not visible in the UI
            include_internal: If True, include internal/system solutions

        Returns:
            List of solution records
        """
        endpoint = "solutions"
        params = {}
        if select:
            params["$select"] = ",".join(select)

        # Build filter conditions
        filters = []
        if unmanaged_only:
            filters.append("ismanaged eq false")
        if not include_invisible:
            filters.append("isvisible eq true")
        # Note: isinternal is not readable via API, so we filter client-side

        if filters:
            params["$filter"] = " and ".join(filters)
        params["$orderby"] = "friendlyname"
        result = self.get(endpoint, params=params if params else None)
        return result.get("value", [])

    def get_solution(self, solution_id: str) -> dict:
        """
        Get a specific solution by ID.

        Args:
            solution_id: The solution's unique identifier (GUID) or unique name

        Returns:
            Solution record
        """
        # Try to get by GUID first
        try:
            return self.get(f"solutions({solution_id})")
        except ClientError:
            # If that fails, try to find by unique name
            result = self.get(f"solutions?$filter=uniquename eq '{solution_id}'")
            solutions = result.get("value", [])
            if not solutions:
                raise ClientError(f"Solution not found: {solution_id}")
            return solutions[0]

    def get_solution_component_type(self, entity_logical_name: str) -> Optional[int]:
        """
        Get the solution component type for a given entity logical name.

        Args:
            entity_logical_name: The logical name of the entity (e.g., 'bot', 'connectionreference')

        Returns:
            The component type integer value, or None if not found
        """
        # Query solutioncomponentdefinitions to find the component type
        result = self.get(
            f"solutioncomponentdefinitions?$filter=primaryentityname eq '{entity_logical_name}'"
            "&$select=solutioncomponenttype,name,primaryentityname"
        )
        definitions = result.get("value", [])
        if definitions:
            return definitions[0].get("solutioncomponenttype")
        return None

    def list_solution_component_definitions(self) -> list[dict]:
        """
        List all solution component type definitions.

        Returns:
            List of component type definitions with id, name, and entity info
        """
        result = self.get(
            "solutioncomponentdefinitions"
            "?$select=solutioncomponenttype,name,primaryentityname,isviewable"
            "&$orderby=name"
        )
        return result.get("value", [])

    def get_component_type_name(self, component_type: int) -> str:
        """
        Get the display name for a component type integer.

        Args:
            component_type: The numeric component type

        Returns:
            Human-readable component type name
        """
        # Common component types - cached for performance
        component_type_names = {
            1: "Entity",
            2: "Attribute",
            3: "Relationship",
            9: "Option Set",
            10: "Entity Relationship",
            20: "Role",
            21: "Role Privilege",
            24: "Form",
            25: "Organization",
            26: "Saved Query",
            29: "Workflow",
            31: "Report",
            36: "Email Template",
            37: "Contract Template",
            38: "KB Article Template",
            39: "Mail Merge Template",
            44: "Duplicate Detection Rule",
            60: "System Form",
            61: "Web Resource",
            62: "Site Map",
            63: "Connection Role",
            65: "Hierarchy Rule",
            66: "Custom Control",
            68: "Custom Control Default Config",
            70: "Field Security Profile",
            80: "Field Permission",
            90: "Plugin Type",
            91: "Plugin Assembly",
            92: "SDK Message Processing Step",
            93: "SDK Message Processing Step Image",
            95: "Service Endpoint",
            150: "Routing Rule",
            151: "Routing Rule Item",
            152: "SLA",
            154: "Convert Rule",
            155: "Convert Rule Item",
            161: "Mobile Offline Profile",
            162: "Mobile Offline Profile Item",
            165: "Similarity Rule",
            166: "Data Source Mapping",
            201: "SDK Message",
            202: "SDK Message Filter",
            203: "SDK Message Pair",
            204: "SDK Message Request",
            205: "SDK Message Request Field",
            206: "SDK Message Response",
            207: "SDK Message Response Field",
            208: "Import Map",
            210: "Web Wizard",
            300: "Canvas App",
            371: "Connector",
            372: "Connector",
            380: "Environment Variable Definition",
            381: "Environment Variable Value",
            400: "AI Project Type",
            401: "AI Project",
            402: "AI Configuration",
            430: "Entity Analytics Config",
            431: "Attribute Image Config",
            432: "Entity Image Config",
            10001: "Bot",  # Copilot Studio agent
            10014: "Connection Reference",
            10029: "AI Builder Model",
            10030: "AI Builder Dataset",
            10049: "Power Automate Flow",  # Agent flow / cloud flow
        }
        return component_type_names.get(component_type, f"Unknown ({component_type})")

    def get_dependencies(self, object_id: str, component_type: int) -> list[dict]:
        """
        Get dependencies that would prevent a component from being deleted.

        Args:
            object_id: The GUID of the component
            component_type: The solution component type integer

        Returns:
            List of dependency records with dependent component info
        """
        result = self.get(
            f"RetrieveDependenciesForDelete(ObjectId={object_id},ComponentType={component_type})"
        )
        return result.get("value", [])

    def get_dependencies_for_entity(self, object_id: str, entity_name: str) -> list[dict]:
        """
        Get dependencies for a component, resolving entity name to component type.

        Args:
            object_id: The GUID of the component
            entity_name: The logical name of the entity (e.g., 'connector', 'msdyn_aimodel')

        Returns:
            List of dependency records, or empty list if component type not found
        """
        component_type = self.get_solution_component_type(entity_name)
        if component_type is None:
            return []
        return self.get_dependencies(object_id, component_type)

    def add_solution_component(
        self,
        solution_unique_name: str,
        component_id: str,
        component_type: int,
        add_required_components: bool = False,
    ) -> dict:
        """
        Add a component to an unmanaged solution.

        Args:
            solution_unique_name: The unique name of the target solution
            component_id: The GUID of the component to add
            component_type: The component type integer value
            add_required_components: Whether to also add required dependencies

        Returns:
            Response from the AddSolutionComponent action
        """
        action_data = {
            "ComponentId": component_id,
            "ComponentType": component_type,
            "SolutionUniqueName": solution_unique_name,
            "AddRequiredComponents": add_required_components,
        }
        return self.post("AddSolutionComponent", action_data)

    def remove_solution_component(
        self,
        solution_unique_name: str,
        component_id: str,
        component_type: int,
    ) -> dict:
        """
        Remove a component from an unmanaged solution.

        Args:
            solution_unique_name: The unique name of the target solution
            component_id: The GUID of the component to remove (the actual entity ID, e.g., bot ID)
            component_type: The component type integer value

        Returns:
            Response from the RemoveSolutionComponent action

        Note:
            The RemoveSolutionComponent Web API action expects the component's actual
            entity ID (e.g., botid) passed as 'solutioncomponentid', not the
            solutioncomponent record ID. This is counterintuitive but required.
        """
        action_data = {
            "SolutionComponent": {
                "@odata.type": "Microsoft.Dynamics.CRM.solutioncomponent",
                "solutioncomponentid": component_id,
            },
            "ComponentType": component_type,
            "SolutionUniqueName": solution_unique_name,
        }
        return self.post("RemoveSolutionComponent", action_data)

    def get_solution_components(
        self,
        solution_id: str,
        component_type: Optional[int] = None,
        include_type_names: bool = False,
    ) -> list[dict]:
        """
        Get components in a solution.

        Args:
            solution_id: The solution's unique identifier (GUID)
            component_type: Optional filter by component type
            include_type_names: Add human-readable component type names

        Returns:
            List of solution component records
        """
        endpoint = f"solutioncomponents?$filter=_solutionid_value eq {solution_id}"
        if component_type is not None:
            endpoint += f" and componenttype eq {component_type}"
        result = self.get(endpoint)
        components = result.get("value", [])

        if include_type_names:
            for comp in components:
                comp_type = comp.get("componenttype")
                if comp_type is not None:
                    comp["componenttype_name"] = self.get_component_type_name(comp_type)

        return components

    def get_solution_components_summary(
        self,
        solution_id: str,
    ) -> dict:
        """
        Get a summary of components in a solution grouped by type.

        Args:
            solution_id: The solution's unique identifier (GUID)

        Returns:
            Dict with component counts by type and detailed component list
        """
        components = self.get_solution_components(solution_id, include_type_names=True)

        # Group by component type
        by_type: dict[str, list[dict]] = {}
        for comp in components:
            type_name = comp.get("componenttype_name", "Unknown")
            if type_name not in by_type:
                by_type[type_name] = []
            by_type[type_name].append(comp)

        # Build summary
        summary = {
            "total_count": len(components),
            "by_type": {
                type_name: {
                    "count": len(comps),
                    "component_type": comps[0].get("componenttype") if comps else None,
                }
                for type_name, comps in sorted(by_type.items())
            },
            "components": components,
        }

        return summary

    def add_bot_to_solution(
        self,
        solution_unique_name: str,
        bot_id: str,
        add_required_components: bool = True,
    ) -> dict:
        """
        Add a Copilot agent (bot) to an unmanaged solution.

        Args:
            solution_unique_name: The unique name of the target solution
            bot_id: The bot's unique identifier (GUID)
            add_required_components: Whether to also add required dependencies (default: True)

        Returns:
            Response from the AddSolutionComponent action
        """
        # Get the component type for bot
        component_type = self.get_solution_component_type("bot")
        if component_type is None:
            raise ClientError("Could not determine component type for 'bot' entity")

        return self.add_solution_component(
            solution_unique_name=solution_unique_name,
            component_id=bot_id,
            component_type=component_type,
            add_required_components=add_required_components,
        )

    def remove_bot_from_solution(
        self,
        solution_unique_name: str,
        bot_id: str,
    ) -> dict:
        """
        Remove a Copilot agent (bot) from an unmanaged solution.

        Args:
            solution_unique_name: The unique name of the target solution
            bot_id: The bot's unique identifier (GUID)

        Returns:
            Response from the RemoveSolutionComponent action
        """
        # Get the component type for bot
        component_type = self.get_solution_component_type("bot")
        if component_type is None:
            raise ClientError("Could not determine component type for 'bot' entity")

        return self.remove_solution_component(
            solution_unique_name=solution_unique_name,
            component_id=bot_id,
            component_type=component_type,
        )

    def add_connection_reference_to_solution(
        self,
        solution_unique_name: str,
        connection_reference_id: str,
        add_required_components: bool = False,
    ) -> dict:
        """
        Add a connection reference to an unmanaged solution.

        Args:
            solution_unique_name: The unique name of the target solution
            connection_reference_id: The connection reference's unique identifier (GUID)
            add_required_components: Whether to also add required dependencies

        Returns:
            Response from the AddSolutionComponent action
        """
        # Get the component type for connectionreference
        component_type = self.get_solution_component_type("connectionreference")
        if component_type is None:
            raise ClientError("Could not determine component type for 'connectionreference' entity")

        return self.add_solution_component(
            solution_unique_name=solution_unique_name,
            component_id=connection_reference_id,
            component_type=component_type,
            add_required_components=add_required_components,
        )

    def remove_connection_reference_from_solution(
        self,
        solution_unique_name: str,
        connection_reference_id: str,
    ) -> dict:
        """
        Remove a connection reference from an unmanaged solution.

        Args:
            solution_unique_name: The unique name of the target solution
            connection_reference_id: The connection reference's unique identifier (GUID)

        Returns:
            Response from the RemoveSolutionComponent action
        """
        # Get the component type for connectionreference
        component_type = self.get_solution_component_type("connectionreference")
        if component_type is None:
            raise ClientError("Could not determine component type for 'connectionreference' entity")

        return self.remove_solution_component(
            solution_unique_name=solution_unique_name,
            component_id=connection_reference_id,
            component_type=component_type,
        )

    def add_custom_connector_to_solution(
        self,
        solution_unique_name: str,
        connector_id: str,
        add_required_components: bool = False,
    ) -> dict:
        """
        Add a custom connector to an unmanaged solution.

        IMPORTANT: Custom connectors cannot be in the same solution as cloud flows
        and connection references that use them. You need separate solutions:
        - Solution 1: Custom connector(s)
        - Solution 2: Cloud flows + connection references

        Args:
            solution_unique_name: The unique name of the target solution
            connector_id: The connector's Dataverse entity ID (GUID from connector table)
            add_required_components: Whether to also add required dependencies

        Returns:
            Response from the AddSolutionComponent action

        Raises:
            ClientError: If component type cannot be determined or validation fails
        """
        # Get the component type for connector
        component_type = self.get_solution_component_type("connector")
        if component_type is None:
            raise ClientError("Could not determine component type for 'connector' entity")

        return self.add_solution_component(
            solution_unique_name=solution_unique_name,
            component_id=connector_id,
            component_type=component_type,
            add_required_components=add_required_components,
        )

    def remove_custom_connector_from_solution(
        self,
        solution_unique_name: str,
        connector_id: str,
    ) -> dict:
        """
        Remove a custom connector from an unmanaged solution.

        Args:
            solution_unique_name: The unique name of the target solution
            connector_id: The connector's Dataverse entity ID (GUID)

        Returns:
            Response from the RemoveSolutionComponent action

        Raises:
            ClientError: If component type cannot be determined
        """
        # Get the component type for connector
        component_type = self.get_solution_component_type("connector")
        if component_type is None:
            raise ClientError("Could not determine component type for 'connector' entity")

        return self.remove_solution_component(
            solution_unique_name=solution_unique_name,
            component_id=connector_id,
            component_type=component_type,
        )

    def validate_solution_for_custom_connector(
        self,
        solution_unique_name: str,
    ) -> tuple[bool, str]:
        """
        Validate that a solution is suitable for adding a custom connector.

        Custom connectors cannot be in the same solution as cloud flows and
        connection references that use them.

        Args:
            solution_unique_name: The unique name of the solution to validate

        Returns:
            Tuple of (is_valid, error_message). If valid, error_message is empty.
        """
        # Get the solution first
        solution = self.get_solution(solution_unique_name)
        solution_id = solution.get("solutionid")
        if not solution_id:
            return False, f"Solution '{solution_unique_name}' not found"

        # Get component types
        workflow_type = self.get_solution_component_type("workflow")
        conn_ref_type = self.get_solution_component_type("connectionreference")

        # Check for workflows (cloud flows) in the solution
        if workflow_type is not None:
            workflows = self.get_solution_components(solution_id, workflow_type)
            if workflows:
                return False, (
                    f"Solution '{solution_unique_name}' contains {len(workflows)} cloud flow(s). "
                    "Custom connectors cannot be in the same solution as cloud flows. "
                    "Create a separate solution for custom connectors."
                )

        # Check for connection references in the solution
        if conn_ref_type is not None:
            conn_refs = self.get_solution_components(solution_id, conn_ref_type)
            if conn_refs:
                return False, (
                    f"Solution '{solution_unique_name}' contains {len(conn_refs)} connection reference(s). "
                    "Custom connectors cannot be in the same solution as connection references. "
                    "Create a separate solution for custom connectors."
                )

        return True, ""

    def get_bot_connection_reference(self, bot_id: str) -> Optional[dict]:
        """
        Get the provider connection reference for a specific bot.

        Args:
            bot_id: The bot's unique identifier

        Returns:
            Connection reference record, or None if not found
        """
        bot = self.get_bot(bot_id)
        provider_ref_id = bot.get("_providerconnectionreferenceid_value")
        if provider_ref_id:
            result = self.get(f"connectionreferences({provider_ref_id})")
            return result if result else None
        return None

    # =========================================================================
    # Publisher Methods
    # =========================================================================

    def list_publishers(self) -> list[dict]:
        """
        List all publishers in the environment.

        Returns:
            List of publisher records
        """
        result = self.get("publishers?$orderby=friendlyname")
        return result.get("value", [])

    def get_publisher(self, publisher_id: str) -> dict:
        """
        Get a publisher by ID or unique name.

        Args:
            publisher_id: The publisher's unique identifier (GUID) or unique name

        Returns:
            Publisher record
        """
        # Check if it's a GUID or unique name
        if self._is_guid(publisher_id):
            return self.get(f"publishers({publisher_id})")
        else:
            # Query by unique name
            result = self.get(f"publishers?$filter=uniquename eq '{publisher_id}'")
            publishers = result.get("value", [])
            if not publishers:
                raise ClientError(f"Publisher '{publisher_id}' not found")
            return publishers[0]

    def create_publisher(
        self,
        unique_name: str,
        friendly_name: str,
        customization_prefix: str,
        customization_option_value_prefix: int,
        description: Optional[str] = None,
    ) -> dict:
        """
        Create a new publisher.

        Args:
            unique_name: Unique name for the publisher (alphanumeric, no spaces)
            friendly_name: Display name for the publisher
            customization_prefix: Prefix for customizations (2-8 lowercase letters)
            customization_option_value_prefix: Prefix for option values (10000-99999)
            description: Optional description

        Returns:
            Created publisher record (from OData-EntityId header)
        """
        publisher_data = {
            "uniquename": unique_name,
            "friendlyname": friendly_name,
            "customizationprefix": customization_prefix,
            "customizationoptionvalueprefix": customization_option_value_prefix,
        }

        if description:
            publisher_data["description"] = description

        return self.post("publishers", publisher_data)

    def delete_publisher(self, publisher_id: str) -> None:
        """
        Delete a publisher by ID or unique name.

        Args:
            publisher_id: The publisher's unique identifier (GUID) or unique name

        Note:
            Publishers cannot be deleted if they have solutions associated with them.
        """
        # Resolve publisher ID if it's a unique name
        if not self._is_guid(publisher_id):
            publisher = self.get_publisher(publisher_id)
            publisher_id = publisher.get("publisherid")
            if not publisher_id:
                raise ClientError(f"Could not resolve publisher ID for '{publisher_id}'")

        self.delete(f"publishers({publisher_id})")

    # =========================================================================
    # Solution Creation Methods
    # =========================================================================

    def create_solution(
        self,
        unique_name: str,
        friendly_name: str,
        publisher_id: str,
        version: str = "1.0.0.0",
        description: Optional[str] = None,
    ) -> dict:
        """
        Create a new unmanaged solution.

        Args:
            unique_name: Unique name for the solution (alphanumeric, no spaces)
            friendly_name: Display name for the solution
            publisher_id: The publisher's unique identifier (GUID) or unique name
            version: Version string (default: "1.0.0.0")
            description: Optional description

        Returns:
            Created solution record (from OData-EntityId header)
        """
        # Resolve publisher ID if it's a unique name
        if not self._is_guid(publisher_id):
            publisher = self.get_publisher(publisher_id)
            publisher_id = publisher.get("publisherid")
            if not publisher_id:
                raise ClientError(f"Could not resolve publisher ID for '{publisher_id}'")

        solution_data = {
            "uniquename": unique_name,
            "friendlyname": friendly_name,
            "version": version,
            "publisherid@odata.bind": f"/publishers({publisher_id})",
        }

        if description:
            solution_data["description"] = description

        return self.post("solutions", solution_data)

    def delete_solution(self, solution_id: str) -> None:
        """
        Delete a solution by ID or unique name.

        Args:
            solution_id: The solution's unique identifier (GUID) or unique name
        """
        # Resolve to GUID if it's a unique name
        if not self._is_guid(solution_id):
            solution = self.get_solution(solution_id)
            solution_id = solution.get("solutionid")
            if not solution_id:
                raise ClientError(f"Could not resolve solution ID for '{solution_id}'")

        self.delete(f"solutions({solution_id})")

    # =========================================================================
    # Solution Export/Import Methods
    # =========================================================================

    def poll_async_operation(
        self,
        async_operation_id: str,
        timeout: float = 300,
        poll_interval: float = 5,
    ) -> dict:
        """
        Poll an async operation until completion.

        Args:
            async_operation_id: The async operation GUID
            timeout: Maximum time to wait in seconds (default: 300)
            poll_interval: Time between polls in seconds (default: 5)

        Returns:
            The completed async operation record

        Raises:
            ClientError: If operation fails or times out

        Note:
            Async operation statecodes:
            - 0 = Ready
            - 1 = Suspended
            - 2 = Locked
            - 3 = Completed

            Async operation statuscodes when completed (statecode=3):
            - 30 = Succeeded
            - 31 = Failed
            - 32 = Canceled
        """
        import time as time_module

        start_time = time_module.time()

        while True:
            elapsed = time_module.time() - start_time
            if elapsed > timeout:
                raise ClientError(
                    f"Async operation {async_operation_id} timed out after {timeout} seconds"
                )

            # Query the async operation
            result = self.get(
                f"asyncoperations({async_operation_id})"
                "?$select=statecode,statuscode,message,friendlymessage"
            )

            statecode = result.get("statecode")
            statuscode = result.get("statuscode")

            # Check if completed (statecode == 3)
            if statecode == 3:
                if statuscode == 30:
                    # Succeeded
                    return result
                elif statuscode == 31:
                    # Failed
                    message = result.get("friendlymessage") or result.get("message") or "Unknown error"
                    raise ClientError(f"Async operation failed: {message}")
                elif statuscode == 32:
                    # Canceled
                    raise ClientError("Async operation was canceled")
                else:
                    raise ClientError(f"Async operation completed with unexpected status: {statuscode}")

            # Wait before polling again
            time_module.sleep(poll_interval)

    def export_solution_async(
        self,
        solution_name: str,
        managed: bool = False,
        timeout: float = 300,
    ) -> bytes:
        """
        Export a solution asynchronously.

        Args:
            solution_name: The solution's unique name
            managed: Export as managed solution (default: False for unmanaged)
            timeout: Maximum time to wait in seconds (default: 300)

        Returns:
            Solution zip file as bytes

        Raises:
            ClientError: If export fails
        """
        # Start the async export
        export_data = {
            "SolutionName": solution_name,
            "Managed": managed,
        }

        response = self.post("ExportSolutionAsync", export_data)

        async_operation_id = response.get("AsyncOperationId")
        export_job_id = response.get("ExportJobId")

        if not async_operation_id or not export_job_id:
            raise ClientError(
                f"ExportSolutionAsync did not return expected IDs. Response: {response}"
            )

        # Poll until complete
        self.poll_async_operation(async_operation_id, timeout=timeout)

        # Download the exported solution
        return self.download_solution_export_data(export_job_id)

    def download_solution_export_data(self, export_job_id: str) -> bytes:
        """
        Download exported solution data.

        Args:
            export_job_id: The export job ID from ExportSolutionAsync

        Returns:
            Solution zip file as bytes
        """
        import base64

        response = self.post(
            "DownloadSolutionExportData",
            {"ExportJobId": export_job_id}
        )

        export_solution_file = response.get("ExportSolutionFile")
        if not export_solution_file:
            raise ClientError("DownloadSolutionExportData did not return solution file")

        # The response is base64 encoded
        return base64.b64decode(export_solution_file)

    def stage_solution(self, solution_file: bytes) -> dict:
        """
        Stage a solution for validation before import.

        Args:
            solution_file: Solution zip file as bytes

        Returns:
            StageSolutionResults containing:
            - StageSolutionUploadId: ID to use for ImportSolutionAsync
            - SolutionComponentsDetails: List of components with connection refs and env vars
            - SolutionDetails: Solution metadata
            - MissingDependencies: Any missing dependencies

        Raises:
            ClientError: If staging fails
        """
        import base64

        # Encode the solution file
        customization_file = base64.b64encode(solution_file).decode("utf-8")

        response = self.post(
            "StageSolution",
            {"CustomizationFile": customization_file}
        )

        results = response.get("StageSolutionResults")
        if not results:
            raise ClientError(f"StageSolution did not return expected results. Response: {response}")

        return results

    def import_solution_async(
        self,
        solution_file: bytes,
        overwrite_unmanaged_customizations: bool = False,
        publish_workflows: bool = False,
        component_parameters: Optional[list[dict]] = None,
        stage_solution_upload_id: Optional[str] = None,
        import_as_holding: bool = False,
        timeout: float = 600,
    ) -> dict:
        """
        Import a solution asynchronously.

        Args:
            solution_file: Solution zip file as bytes
            overwrite_unmanaged_customizations: Overwrite existing customizations (default: False)
            publish_workflows: Publish workflows after import (default: False)
            component_parameters: List of component parameter dicts for connection
                                  references and environment variables
            stage_solution_upload_id: If provided, uses staged solution instead of file
            import_as_holding: Import as holding solution for upgrade (default: False)
            timeout: Maximum time to wait in seconds (default: 600)

        Returns:
            Import result containing:
            - AsyncOperationId: The async operation ID
            - ImportJobKey: The import job ID

        Raises:
            ClientError: If import fails

        Note:
            component_parameters format for connection references:
            [
                {
                    "@odata.type": "Microsoft.Dynamics.CRM.connectionreference",
                    "connectionreferencelogicalname": "prefix_connrefname",
                    "connectionid": "guid-of-target-connection",
                    "connectorid": "/providers/Microsoft.PowerApps/apis/shared_connector"
                }
            ]

            For environment variables:
            [
                {
                    "@odata.type": "Microsoft.Dynamics.CRM.environmentvariablevalue",
                    "schemaname": "prefix_VariableName",
                    "value": "target-environment-value"
                }
            ]
        """
        import base64

        import_data: dict[str, Any] = {
            "OverwriteUnmanagedCustomizations": overwrite_unmanaged_customizations,
            "PublishWorkflows": publish_workflows,
            "ImportJobId": self._generate_guid(),
        }

        # Use staged solution or raw file
        if stage_solution_upload_id:
            import_data["SolutionParameters"] = {
                "StageSolutionUploadId": stage_solution_upload_id
            }
        else:
            import_data["CustomizationFile"] = base64.b64encode(solution_file).decode("utf-8")

        if import_as_holding:
            import_data["HoldingSolution"] = True

        # Add component parameters if provided
        if component_parameters:
            import_data["ComponentParameters"] = component_parameters

        response = self.post("ImportSolutionAsync", import_data)

        async_operation_id = response.get("AsyncOperationId")
        import_job_key = response.get("ImportJobKey")

        if not async_operation_id:
            raise ClientError(
                f"ImportSolutionAsync did not return AsyncOperationId. Response: {response}"
            )

        # Poll until complete
        self.poll_async_operation(async_operation_id, timeout=timeout)

        return {
            "AsyncOperationId": async_operation_id,
            "ImportJobKey": import_job_key,
        }

    def _generate_guid(self) -> str:
        """Generate a new GUID."""
        import uuid
        return str(uuid.uuid4())

    def _is_guid(self, value: str) -> bool:
        """Check if a string is a valid GUID format."""
        import re
        guid_pattern = r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
        return bool(re.match(guid_pattern, value))

    # =========================================================================
    # Power Platform Connection Methods
    # =========================================================================

    def create_azure_ai_search_connection(
        self,
        connection_name: str,
        search_endpoint: str,
        api_key: str,
        environment_id: str,
    ) -> dict:
        """
        Create a Power Platform connection for Azure AI Search.

        This creates a connection that can be used by Copilot Studio to access
        Azure AI Search indexes. After creation, the connection must be linked
        to an agent as a knowledge source through the Copilot Studio UI.

        Args:
            connection_name: Display name for the connection
            search_endpoint: Azure AI Search endpoint URL (e.g., https://mysearch.search.windows.net)
            api_key: Azure AI Search admin or query key
            environment_id: Power Platform environment ID (e.g., Default-<tenant-id>)

        Returns:
            Dict containing connection details including:
            - name: Connection ID (GUID)
            - properties.displayName: Display name
            - properties.statuses: Connection status

        Raises:
            ClientError: If connection creation fails

        Note:
            This method creates the Power Platform connection but does NOT
            add it as a knowledge source to a Copilot agent. Copilot Studio
            requires the connection to be linked through the UI, as the
            knowledge source configuration involves complex internal linking
            that is not exposed via public APIs.

            After creating a connection, use the Copilot Studio UI to:
            1. Open your agent
            2. Go to Knowledge > Add knowledge
            3. Select Azure AI Search
            4. The connection you created will be available to select
            5. Specify the index name and complete the setup
        """
        import uuid

        # Generate a new connection ID
        connection_id = str(uuid.uuid4())

        # Get access token for Power Apps API
        powerapps_token = get_access_token("https://service.powerapps.com/")

        # Build the connection request
        connection_data = {
            "properties": {
                "environment": {
                    "id": f"/providers/Microsoft.PowerApps/environments/{environment_id}",
                    "name": environment_id
                },
                "displayName": connection_name,
                "connectionParametersSet": {
                    "name": "adminkey",
                    "values": {
                        "ConnectionEndpoint": {
                            "value": search_endpoint
                        },
                        "AdminKey": {
                            "value": api_key
                        }
                    }
                }
            }
        }

        # Create the connection via Power Apps API
        url = (
            f"https://api.powerapps.com/providers/Microsoft.PowerApps/apis/"
            f"shared_azureaisearch/connections/{connection_id}"
            f"?api-version=2016-11-01&$filter=environment%20eq%20%27{environment_id}%27"
        )

        headers = {
            "Authorization": f"Bearer {powerapps_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            response = self._http_client.put(url, headers=headers, json=connection_data, timeout=60.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                if "error" in error_body:
                    error_detail = error_body["error"].get("message", str(error_body))
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to create connection: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Connection request failed: {e}")

    def list_connection_references(
        self,
        connection_id: Optional[str] = None,
        connector_id: Optional[str] = None,
    ) -> list[dict]:
        """
        List all connection references in the Dataverse environment.

        Connection references are solution-aware references to connections
        used in flows and agents.

        Args:
            connection_id: Optional connection ID to filter connection references by.
            connector_id: Optional connector ID to filter connection references by.
                          Accepts both short form (shared_asana) and full path
                          (/providers/Microsoft.PowerApps/apis/shared_asana).

        Returns:
            List of connection reference objects
        """
        select = (
            "connectionreferenceid,connectionreferencelogicalname,"
            "connectionreferencedisplayname,connectorid,connectionid,statecode"
        )
        url = f"{self.api_url}/connectionreferences?$select={select}"

        filters = []
        if connection_id:
            filters.append(f"connectionid eq '{connection_id}'")
        if connector_id:
            # Normalize to full path format for filtering
            if not connector_id.startswith("/"):
                connector_id = f"/providers/Microsoft.PowerApps/apis/{connector_id}"
            filters.append(f"connectorid eq '{connector_id}'")

        if filters:
            url += f"&$filter={' and '.join(filters)}"

        url += "&$orderby=connectionreferencedisplayname"
        headers = self._get_headers()
        response = self._http_client.get(url, headers=headers, timeout=60.0)
        response.raise_for_status()
        data = response.json()
        return data.get("value", [])

    def delete_connection_reference(self, connection_reference_id: str) -> bool:
        """
        Delete a connection reference from the Dataverse environment.

        Args:
            connection_reference_id: The connection reference's unique identifier (GUID)

        Returns:
            True if deletion was successful

        Raises:
            ClientError: If the connection reference cannot be deleted
        """
        url = f"{self.api_url}/connectionreferences({connection_reference_id})"
        headers = self._get_headers()
        response = self._http_client.delete(url, headers=headers, timeout=60.0)
        response.raise_for_status()
        return True

    def update_connection_reference(
        self,
        connection_reference_id: str,
        connection_id: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> dict:
        """
        Update a connection reference in the Dataverse environment.

        Args:
            connection_reference_id: The connection reference's unique identifier (GUID)
            connection_id: New connection ID to associate with this reference
            display_name: New display name for the connection reference

        Returns:
            Updated connection reference object

        Raises:
            ClientError: If the connection reference cannot be updated
        """
        url = f"{self.api_url}/connectionreferences({connection_reference_id})"
        headers = self._get_headers()

        # Build update payload with only provided fields
        payload = {}
        if connection_id is not None:
            payload["connectionid"] = connection_id
        if display_name is not None:
            payload["connectionreferencedisplayname"] = display_name

        if not payload:
            raise ClientError("No update fields provided")

        try:
            response = self._http_client.patch(url, headers=headers, json=payload, timeout=60.0)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            error_detail = str(e)
            if e.response is not None:
                try:
                    error_body = e.response.json()
                    if "error" in error_body:
                        error_detail = error_body["error"].get("message", str(error_body))
                except Exception:
                    error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(
                f"Failed to update connection reference: HTTP {e.response.status_code}: {error_detail}"
            )
        except httpx.RequestError as e:
            raise ClientError(f"Connection reference update request failed: {e}")

        # Fetch and return the updated record
        get_response = self._http_client.get(url, headers=headers, timeout=60.0)
        get_response.raise_for_status()
        return get_response.json()

    def get_connection_reference(self, connection_reference_id: str) -> dict:
        """
        Get a single connection reference by ID.

        Args:
            connection_reference_id: The connection reference's unique identifier (GUID)

        Returns:
            Connection reference object

        Raises:
            ClientError: If the connection reference is not found
        """
        url = f"{self.api_url}/connectionreferences({connection_reference_id})"
        headers = self._get_headers()
        response = self._http_client.get(url, headers=headers, timeout=60.0)
        response.raise_for_status()
        return response.json()

    def _find_connection_reference_by_logical_name(self, logical_name: str) -> Optional[dict]:
        """
        Find a connection reference by its exact logical name.

        Args:
            logical_name: The exact connectionreferencelogicalname to search for

        Returns:
            Connection reference dict if found, None otherwise
        """
        try:
            # Query for connection reference with exact logical name match
            filter_query = f"connectionreferencelogicalname eq '{logical_name}'"
            url = f"{self.api_url}/connectionreferences?$filter={filter_query}"
            headers = self._get_headers()
            response = self._http_client.get(url, headers=headers, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            results = data.get("value", [])
            return results[0] if results else None
        except Exception:
            return None

    def _create_bot_connection_reference(
        self,
        logical_name: str,
        display_name: str,
        connector_id: str,
        connection_id: str,
    ) -> dict:
        """
        Create a connection reference with a specific logical name for bot tools.

        This is used internally when creating connector tools to ensure the
        connection reference exists with the exact logical name format that
        the Copilot Studio runtime expects.

        Args:
            logical_name: The exact connectionreferencelogicalname to use
            display_name: Display name for the connection reference
            connector_id: Full connector ID path
            connection_id: Connection ID to link

        Returns:
            Created connection reference object

        Raises:
            ClientError: If the connection reference cannot be created
        """
        # Normalize connector_id to full path format if not already
        if not connector_id.startswith("/"):
            connector_id = f"/providers/Microsoft.PowerApps/apis/{connector_id}"

        payload = {
            "connectionreferencedisplayname": display_name,
            "connectionreferencelogicalname": logical_name,
            "connectorid": connector_id,
            "connectionid": connection_id,
        }

        url = f"{self.api_url}/connectionreferences"
        headers = self._get_headers()

        try:
            response = self._http_client.post(url, headers=headers, json=payload, timeout=60.0)
            response.raise_for_status()

            # Extract the created reference ID from response headers
            entity_id_header = response.headers.get("OData-EntityId", "")
            if entity_id_header:
                import re
                match = re.search(r"connectionreferences\(([^)]+)\)", entity_id_header)
                if match:
                    created_id = match.group(1)
                    return self.get_connection_reference(created_id)

            return payload

        except httpx.HTTPStatusError as e:
            error_detail = str(e)
            if e.response is not None:
                try:
                    error_body = e.response.json()
                    if "error" in error_body:
                        error_detail = error_body["error"].get("message", str(error_body))
                except Exception:
                    error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to create bot connection reference '{logical_name}': {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Connection reference request failed: {e}")

    def _associate_botcomponent_connectionreference(
        self,
        botcomponent_id: str,
        connection_reference_id: str,
    ) -> bool:
        """
        Associate a bot component with a connection reference via the many-to-many relationship.

        This is REQUIRED for connector tools to work at runtime. The Copilot Studio runtime
        looks up connection references through this relationship, not just by logical name.

        Args:
            botcomponent_id: The bot component's unique identifier (GUID)
            connection_reference_id: The connection reference's unique identifier (GUID)

        Returns:
            True if association was successful or already exists

        Raises:
            ClientError: If the association cannot be created
        """
        url = f"{self.api_url}/botcomponents({botcomponent_id})/botcomponent_connectionreference/$ref"
        headers = self._get_headers()
        payload = {
            "@odata.id": f"{self.api_url}/connectionreferences({connection_reference_id})"
        }

        try:
            response = self._http_client.post(url, headers=headers, json=payload, timeout=60.0)
            # 204 = success, 409 = already exists (both are fine)
            if response.status_code in [204, 409]:
                return True
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            # 409 Conflict means the association already exists - that's fine
            if e.response.status_code == 409:
                return True
            error_detail = str(e)
            if e.response is not None:
                try:
                    error_body = e.response.json()
                    if "error" in error_body:
                        error_detail = error_body["error"].get("message", str(error_body))
                except Exception:
                    error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to associate bot component with connection reference: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Association request failed: {e}")

    def create_connection_reference(
        self,
        display_name: str,
        connector_id: str,
        connection_id: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict:
        """
        Create a new connection reference in the Dataverse environment.

        Connection references are solution-aware pointers to connections,
        allowing flows and agents to reference connections without being
        directly tied to them.

        Args:
            display_name: Display name for the connection reference
            connector_id: Connector identifier (e.g., 'shared_asana' or full path
                          '/providers/Microsoft.PowerApps/apis/shared_asana')
            connection_id: Optional connection ID to link to an existing connection
            description: Optional description for the connection reference

        Returns:
            Created connection reference object

        Raises:
            ClientError: If the connection reference cannot be created
        """
        # Normalize connector_id to full path format if not already
        if not connector_id.startswith("/"):
            connector_id = f"/providers/Microsoft.PowerApps/apis/{connector_id}"

        # Generate logical name from display name (lowercase, alphanumeric + underscore)
        import re
        logical_name = re.sub(r"[^a-z0-9_]", "_", display_name.lower())
        # Add prefix to ensure uniqueness
        logical_name = f"cr_{logical_name}"

        payload = {
            "connectionreferencedisplayname": display_name,
            "connectionreferencelogicalname": logical_name,
            "connectorid": connector_id,
        }

        if connection_id is not None:
            payload["connectionid"] = connection_id

        if description is not None:
            payload["description"] = description

        # For custom connectors, look up the Dataverse connector entity ID
        # and set CustomConnectorId to link the connection reference properly.
        # This is required for connector operations to be discovered correctly.
        short_connector_id = connector_id.split("/")[-1] if "/" in connector_id else connector_id
        custom_connector_entity_id = self._get_custom_connector_entity_id(short_connector_id)
        if custom_connector_entity_id:
            payload["CustomConnectorId@odata.bind"] = f"/connectors({custom_connector_entity_id})"

        url = f"{self.api_url}/connectionreferences"
        headers = self._get_headers()

        try:
            response = self._http_client.post(url, headers=headers, json=payload, timeout=60.0)
            response.raise_for_status()

            # Extract the created reference ID from response headers
            # OData-EntityId header contains the URL with the new ID
            entity_id_header = response.headers.get("OData-EntityId", "")
            if entity_id_header:
                # Extract GUID from URL like https://.../connectionreferences(guid)
                import re as re_module
                match = re_module.search(r"connectionreferences\(([^)]+)\)", entity_id_header)
                if match:
                    created_id = match.group(1)
                    # Fetch the created record
                    return self.get_connection_reference(created_id)

            # If we can't get the ID from headers, return what we can
            return payload

        except httpx.HTTPStatusError as e:
            error_detail = str(e)
            if e.response is not None:
                try:
                    error_body = e.response.json()
                    if "error" in error_body:
                        error_detail = error_body["error"].get("message", str(error_body))
                except Exception:
                    error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to create connection reference: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Connection reference request failed: {e}")

    def _list_connections_for_connector(
        self,
        connector_id: str,
        environment_id: str,
        powerapps_token: str,
        headers: dict,
    ) -> list[dict]:
        """
        Fallback: list connections for a specific connector using the non-admin endpoint.

        Used when the admin endpoint returns 403 (user lacks ManageAnyConnection permission).
        This endpoint does NOT work for custom connectors that aren't visible in the
        Power Apps API (e.g., MCP connectors), but handles standard/managed connectors fine.
        """
        url = (
            f"https://api.powerapps.com/providers/Microsoft.PowerApps/apis/"
            f"{connector_id}/connections"
            f"?api-version=2016-11-01"
            f"&$filter=environment%20eq%20%27{environment_id}%27"
        )

        try:
            response = self._http_client.get(url, headers=headers, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            return data.get("value", [])
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                if "error" in error_body:
                    error_detail = error_body["error"].get("message", str(error_body))
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(
                f"Failed to list connections for connector '{connector_id}': "
                f"HTTP {e.response.status_code}: {error_detail}"
            )
        except httpx.RequestError as e:
            raise ClientError(f"Request failed: {e}")

    def list_connections(
        self, connector_id: Optional[str] = None, environment_id: Optional[str] = None
    ) -> list[dict]:
        """
        List connections in the environment.

        If connector_id is provided, lists connections for that specific connector.
        If connector_id is not provided, lists all connections across all connectors
        using the admin API.

        Args:
            connector_id: Optional connector identifier (e.g., shared_office365,
                          shared_pub-5fasana-1234567890abcdef).
                          If not provided, returns all connections.
            environment_id: Power Platform environment ID. If not provided,
                            will use DATAVERSE_ENVIRONMENT_ID from config.

        Returns:
            List of connection objects
        """
        # Get environment ID from config if not provided
        if not environment_id:
            config = get_config()
            environment_id = config.environment_id
            if not environment_id:
                raise ClientError(
                    "Environment ID not found. Please set DATAVERSE_ENVIRONMENT_ID "
                    "in your .env file (e.g., Default-<tenant-id> or the environment GUID)."
                )

        powerapps_token = get_access_token("https://service.powerapps.com/")

        # Prefer admin endpoint - it works for both custom and managed connectors.
        # The connector-specific endpoint doesn't work for custom connectors not visible
        # in the Power Apps API (like MCP connectors).
        # On 403 (ManageAnyConnection permission missing), fall back to the
        # connector-specific endpoint when a connector_id is provided.
        admin_url = (
            f"https://api.powerapps.com/providers/Microsoft.PowerApps/scopes/admin/"
            f"environments/{environment_id}/connections"
            f"?api-version=2016-11-01"
        )

        headers = {
            "Authorization": f"Bearer {powerapps_token}",
            "Accept": "application/json",
        }

        try:
            response = self._http_client.get(admin_url, headers=headers, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            connections = data.get("value", [])

            # Filter by connector_id if provided
            if connector_id:
                # Try exact match first
                filtered = [
                    c for c in connections
                    if c.get("properties", {}).get("apiId", "").endswith(f"/{connector_id}")
                ]
                # Fall back to prefix match (e.g., "shared_googleanalytics" matches
                # "shared_googleanalytics-2d4710-5f21a7edd202320fa1-5f39056b10a5231222")
                if not filtered:
                    filtered = [
                        c for c in connections
                        if c.get("properties", {}).get("apiId", "").rsplit("/", 1)[-1]
                        .startswith(connector_id)
                    ]
                connections = filtered

            return connections
        except httpx.HTTPStatusError as e:
            # On 403, fall back to the connector-specific (non-admin) endpoint
            # when a connector_id is provided. This endpoint works for standard
            # connectors without requiring ManageAnyConnection permission.
            if e.response.status_code == 403 and connector_id:
                return self._list_connections_for_connector(
                    connector_id, environment_id, powerapps_token, headers
                )

            error_detail = ""
            try:
                error_body = e.response.json()
                if "error" in error_body:
                    error_detail = error_body["error"].get("message", str(error_body))
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to list connections: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Request failed: {e}")

    def get_connection(
        self, connection_id: str, environment_id: Optional[str] = None
    ) -> dict:
        """
        Get a specific connection by ID.

        Searches all connections in the environment to find the one with
        the matching connection ID.

        Args:
            connection_id: The connection's unique identifier (GUID)
            environment_id: Power Platform environment ID. If not provided,
                            will use DATAVERSE_ENVIRONMENT_ID from config.

        Returns:
            Connection object with properties including connector ID

        Raises:
            ClientError: If the connection is not found
        """
        # List all connections and find the matching one
        connections = self.list_connections(environment_id=environment_id)

        for conn in connections:
            if conn.get("name") == connection_id:
                return conn

        raise ClientError(f"Connection '{connection_id}' not found")

    def test_connection(
        self, connector_id: str, connection_id: str, environment_id: Optional[str] = None
    ) -> dict:
        """
        Test authentication for a specific connection.

        Args:
            connector_id: The connector's unique identifier (e.g., shared_office365)
            connection_id: The connection's unique identifier (GUID)
            environment_id: Power Platform environment ID. If not provided,
                            will use DATAVERSE_ENVIRONMENT_ID from config.

        Returns:
            Test result with status information
        """
        # Get environment ID from config if not provided
        if not environment_id:
            config = get_config()
            environment_id = config.environment_id
            if not environment_id:
                raise ClientError(
                    "Environment ID not found. Please set DATAVERSE_ENVIRONMENT_ID "
                    "in your .env file (e.g., Default-<tenant-id> or the environment GUID)."
                )

        powerapps_token = get_access_token("https://service.powerapps.com/")

        # The testConnection REST endpoint returns 404 for most connectors in
        # Power Platform. Instead, read the connection's own status properties
        # from the admin connections API — this is the same data the Power
        # Platform portal displays.
        #
        # The statuses[0].status field is the authoritative signal:
        #   - "Connected" = healthy (Power Platform auto-refreshes OAuth tokens)
        #   - "Error" = refresh token revoked or connection misconfigured
        #   - "Unauthenticated" = needs initial auth
        #
        # Note: expirationTime refers to the short-lived access token, NOT the
        # refresh token. Power Platform auto-refreshes it, so a past
        # expirationTime is normal and does NOT indicate a broken connection.
        conn = self.get_connection(connection_id, environment_id)
        props = conn.get("properties", {})

        statuses = props.get("statuses", [])
        stored_status = statuses[0].get("status", "Unknown") if statuses else "Unknown"

        is_connected = stored_status.lower() == "connected"
        status_error = ""
        if not is_connected and statuses and statuses[0].get("error"):
            err = statuses[0]["error"]
            status_error = err.get("message", str(err)) if isinstance(err, dict) else str(err)

        return {
            "status_code": 200 if is_connected else 401,
            "success": is_connected,
            "error": status_error if not is_connected else "",
            "stored_status": stored_status,
        }

    def invoke_connector_operation(
        self,
        swagger: dict,
        connection_id: str,
        operation_id: str,
        params: Optional[dict] = None,
        runtime_url: Optional[str] = None,
    ) -> dict:
        """
        Invoke a connector operation through the APIM gateway.

        Builds the URL from the swagger host/basePath + operation path,
        classifies params into path/query/body based on swagger definitions,
        and makes the HTTP call with a Bearer token for https://apihub.azure.com.

        Args:
            swagger: Connector's OpenAPI/Swagger definition
            connection_id: Connection GUID (substituted for {connectionId} in path)
            operation_id: The operationId to invoke
            params: Dict of key=value parameters to pass

        Returns:
            Response dict with status_code, headers, and body

        Raises:
            ClientError: If operation not found or request fails
        """
        params = params or {}

        # Find the operation in swagger paths
        target_op = None
        target_method = None
        target_path = None
        for path, methods in swagger.get("paths", {}).items():
            for method, details in methods.items():
                if method in ("get", "post", "put", "patch", "delete"):
                    if details.get("operationId") == operation_id:
                        target_op = details
                        target_method = method.upper()
                        target_path = path
                        break
            if target_op:
                break

        if not target_op:
            raise ClientError(f"Operation '{operation_id}' not found in connector swagger")

        url_path = target_path

        # Classify parameters from swagger definition
        swagger_params = {p["name"]: p for p in target_op.get("parameters", [])}

        # Replace path parameters (including {connectionId})
        path_params = {
            name: defn for name, defn in swagger_params.items()
            if defn.get("in") == "path"
        }
        for pname in path_params:
            if pname == "connectionId":
                url_path = url_path.replace("{connectionId}", connection_id)
            elif pname in params:
                url_path = url_path.replace(f"{{{pname}}}", params.pop(pname))

        # Build URL: prefer APIM runtime URL (routes through gateway with auth),
        # fall back to swagger host/basePath for direct backend calls
        if runtime_url:
            url = f"{runtime_url.rstrip('/')}{url_path}"
        else:
            host = swagger.get("host", "")
            base_path = swagger.get("basePath", "")
            scheme = "https"
            schemes = swagger.get("schemes", [])
            if schemes:
                scheme = schemes[0]
            url = f"{scheme}://{host}{base_path}{url_path}"

        # Separate header, query, and body params
        header_params = {}
        query_params = {}
        body_data = None  # Will be sent as the request body directly
        extra_body_fields = {}
        for key, value in params.items():
            if key in swagger_params and swagger_params[key].get("in") == "header":
                header_params[key] = value
            elif key in swagger_params and swagger_params[key].get("in") == "query":
                query_params[key] = value
            elif key in swagger_params and swagger_params[key].get("in") == "body":
                # Swagger "in: body" param — the value IS the entire request body.
                # If the value is a JSON string, parse it; otherwise use as-is.
                import json as _json
                try:
                    body_data = _json.loads(value) if isinstance(value, str) else value
                except _json.JSONDecodeError:
                    body_data = value
            else:
                # Default: query for GET/DELETE, body for POST/PUT/PATCH
                if target_method in ("GET", "DELETE"):
                    query_params[key] = value
                else:
                    extra_body_fields[key] = value

        # Merge extra body fields into body_data if both exist
        if extra_body_fields:
            if body_data is None:
                body_data = extra_body_fields
            elif isinstance(body_data, dict):
                body_data.update(extra_body_fields)

        # Get APIM token
        apim_token = get_access_token("https://apihub.azure.com")

        # MCP endpoints require both application/json and text/event-stream
        is_mcp = operation_id == "InvokeMCP" or "/mcp" in url_path
        accept = "application/json, text/event-stream" if is_mcp else "application/json"

        headers = {
            "Authorization": f"Bearer {apim_token}",
            "Accept": accept,
        }
        headers.update(header_params)

        kwargs = {}
        if query_params:
            kwargs["params"] = query_params
        if body_data is not None:
            headers["Content-Type"] = "application/json"
            kwargs["json"] = body_data

        try:
            response = self._http_client.request(
                target_method, url, headers=headers, timeout=60.0, **kwargs
            )

            # Parse response body
            try:
                body = response.json()
            except Exception:
                body = response.text

            result = {
                "status_code": response.status_code,
                "body": body,
            }

            # Include select response headers (e.g., Mcp-Session-Id)
            interesting_headers = {
                k: v for k, v in response.headers.items()
                if k.lower().startswith("mcp-") or k.lower() == "location"
            }
            if interesting_headers:
                result["headers"] = interesting_headers

            if not response.is_success:
                result["error"] = True

            return result

        except httpx.RequestError as e:
            raise ClientError(f"Request to APIM gateway failed: {e}")

    def list_azure_ai_search_connections(self, environment_id: str) -> list[dict]:
        """
        List Azure AI Search connections in a Power Platform environment.

        Args:
            environment_id: Power Platform environment ID

        Returns:
            List of connection objects

        Note:
            This is a convenience method. Use list_connections() for any connector.
        """
        return self.list_connections("shared_azureaisearch", environment_id)

    def _list_azure_ai_search_connections_legacy(self, environment_id: str) -> list[dict]:
        """
        Legacy implementation - kept for reference.
        """
        powerapps_token = get_access_token("https://service.powerapps.com/")

        url = (
            f"https://api.powerapps.com/providers/Microsoft.PowerApps/apis/"
            f"shared_azureaisearch/connections"
            f"?api-version=2016-11-01&$filter=environment%20eq%20%27{environment_id}%27"
        )

        headers = {
            "Authorization": f"Bearer {powerapps_token}",
            "Accept": "application/json",
        }

        try:
            response = self._http_client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            return data.get("value", [])
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                if "error" in error_body:
                    error_detail = error_body["error"].get("message", str(error_body))
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to list connections: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Request failed: {e}")

    def delete_connection(
        self, connection_id: str, connector_id: str, environment_id: str
    ) -> None:
        """
        Delete a Power Platform connection.

        Args:
            connection_id: The connection's unique identifier (GUID)
            connector_id: The connector's unique identifier (e.g., shared_asana, shared_office365)
            environment_id: Power Platform environment ID
        """
        powerapps_token = get_access_token("https://service.powerapps.com/")

        url = (
            f"https://api.powerapps.com/providers/Microsoft.PowerApps/apis/"
            f"{connector_id}/connections/{connection_id}"
            f"?api-version=2016-11-01&$filter=environment%20eq%20%27{environment_id}%27"
        )

        headers = {
            "Authorization": f"Bearer {powerapps_token}",
            "Accept": "application/json",
        }

        try:
            response = self._http_client.delete(url, headers=headers, timeout=30.0)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                if "error" in error_body:
                    error_detail = error_body["error"].get("message", str(error_body))
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to delete connection: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Request failed: {e}")

    def create_connection(
        self,
        connector_id: str,
        connection_name: str,
        environment_id: str,
        parameters: Optional[dict] = None,
    ) -> dict:
        """
        Create a Power Platform connection for any connector.

        Args:
            connector_id: The connector's unique identifier (e.g., shared_asana)
            connection_name: Display name for the connection
            environment_id: Power Platform environment ID
            parameters: Connection parameters (connector-specific)

        Returns:
            Dict containing connection details

        Raises:
            ClientError: If connection creation fails
        """
        import uuid

        connection_id = str(uuid.uuid4())
        powerapps_token = get_access_token("https://service.powerapps.com/")

        # Build the connection request
        connection_data = {
            "properties": {
                "environment": {
                    "id": f"/providers/Microsoft.PowerApps/environments/{environment_id}",
                    "name": environment_id
                },
                "displayName": connection_name,
            }
        }

        # Add parameters if provided
        if parameters:
            connection_data["properties"]["connectionParameters"] = parameters

        url = (
            f"https://api.powerapps.com/providers/Microsoft.PowerApps/apis/"
            f"{connector_id}/connections/{connection_id}"
            f"?api-version=2016-11-01&$filter=environment%20eq%20%27{environment_id}%27"
        )

        headers = {
            "Authorization": f"Bearer {powerapps_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            response = self._http_client.put(url, headers=headers, json=connection_data, timeout=60.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                if "error" in error_body:
                    error_detail = error_body["error"].get("message", str(error_body))
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to create connection: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Connection request failed: {e}")

    def create_oauth_connection(
        self,
        connector_id: str,
        connection_name: str,
        environment_id: str,
    ) -> dict:
        """
        Create a Power Platform connection for an OAuth-based connector.

        This creates the connection record but the user must complete the
        OAuth consent flow via the returned URL or Power Platform portal.

        Args:
            connector_id: The connector's unique identifier (e.g., shared_asana)
            connection_name: Display name for the connection
            environment_id: Power Platform environment ID

        Returns:
            Dict containing connection details and consent URL if available

        Raises:
            ClientError: If connection creation fails
        """
        import uuid

        connection_id = str(uuid.uuid4())
        powerapps_token = get_access_token("https://service.powerapps.com/")

        # OAuth connections require minimal initial parameters
        connection_data = {
            "properties": {
                "environment": {
                    "id": f"/providers/Microsoft.PowerApps/environments/{environment_id}",
                    "name": environment_id
                },
                "displayName": connection_name,
            }
        }

        url = (
            f"https://api.powerapps.com/providers/Microsoft.PowerApps/apis/"
            f"{connector_id}/connections/{connection_id}"
            f"?api-version=2016-11-01&$filter=environment%20eq%20%27{environment_id}%27"
        )

        headers = {
            "Authorization": f"Bearer {powerapps_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            response = self._http_client.put(url, headers=headers, json=connection_data, timeout=60.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                if "error" in error_body:
                    error_detail = error_body["error"].get("message", str(error_body))
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to create connection: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Connection request failed: {e}")

    def create_connection_with_auth_type(
        self,
        connector_id: str,
        connection_name: str,
        environment_id: str,
        auth_type_name: str,
        parameters: Optional[dict] = None,
    ) -> dict:
        """
        Create a Power Platform connection with a specific authentication type.

        This method is used for connectors that support multiple authentication types
        (e.g., Dataverse supports Oauth, ServicePrincipalOauth, CertOauth). The auth
        type is specified via connectionParameterSet in the request body.

        Args:
            connector_id: The connector's unique identifier (e.g., shared_commondataserviceforapps)
            connection_name: Display name for the connection
            environment_id: Power Platform environment ID
            auth_type_name: The authentication type name (e.g., "ServicePrincipalOauth")
            parameters: Connection parameters required for the auth type (e.g., client ID, secret)

        Returns:
            Dict containing connection details including:
            - name: Connection ID (GUID)
            - properties.displayName: Display name
            - properties.statuses: Connection status

        Raises:
            ClientError: If connection creation fails

        Example:
            For ServicePrincipalOauth, parameters should include:
            {
                "token:clientId": "<client-id>",
                "token:clientSecret": "<client-secret>",
                "token:TenantId": "<tenant-id>"
            }
        """
        import uuid

        connection_id = str(uuid.uuid4())
        powerapps_token = get_access_token("https://service.powerapps.com/")

        # Build the connection request with connectionParametersSet for multi-auth
        # Note: The field is "connectionParametersSet" (plural) and requires API version 2025-04-01
        connection_data = {
            "properties": {
                "environment": {
                    "id": f"/providers/Microsoft.PowerApps/environments/{environment_id}",
                    "name": environment_id
                },
                "displayName": connection_name,
                "connectionParametersSet": {
                    "name": auth_type_name,
                    "values": {}
                }
            }
        }

        # Add parameters to the connectionParametersSet values
        if parameters:
            for key, value in parameters.items():
                connection_data["properties"]["connectionParametersSet"]["values"][key] = {
                    "value": value
                }

        url = (
            f"https://api.powerapps.com/providers/Microsoft.PowerApps/apis/"
            f"{connector_id}/connections/{connection_id}"
            f"?api-version=2025-04-01&$filter=environment%20eq%20%27{environment_id}%27"
        )

        headers = {
            "Authorization": f"Bearer {powerapps_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            response = self._http_client.put(url, headers=headers, json=connection_data, timeout=60.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                if "error" in error_body:
                    error_detail = error_body["error"].get("message", str(error_body))
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to create connection: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Connection request failed: {e}")

    def get_consent_link(
        self,
        connector_id: str,
        connection_id: str,
        environment_id: str,
    ) -> str:
        """
        Get the OAuth consent link for an unauthenticated connection.

        Args:
            connector_id: The connector's unique identifier (e.g., shared_asana)
            connection_id: The connection's unique identifier (GUID)
            environment_id: Power Platform environment ID

        Returns:
            The consent URL to complete OAuth authentication

        Raises:
            ClientError: If getting consent link fails
        """
        powerapps_token = get_access_token("https://service.powerapps.com/")

        url = (
            f"https://api.powerapps.com/providers/Microsoft.PowerApps/apis/"
            f"{connector_id}/connections/{connection_id}/getConsentLink"
            f"?api-version=2016-11-01&$filter=environment eq '{environment_id}'"
        )

        headers = {
            "Authorization": f"Bearer {powerapps_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        body = {
            "redirectUrl": "https://make.powerapps.com"
        }

        try:
            response = self._http_client.post(url, headers=headers, json=body, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            return data.get("consentLink", "")
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                if "error" in error_body:
                    error_detail = error_body["error"].get("message", str(error_body))
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to get consent link: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Consent link request failed: {e}")

    def get_connection_user(
        self,
        connector_id: str,
        connection_id: str,
    ) -> dict:
        """
        Get the authenticated user for a connection by calling the connector's API.

        This works by calling a user/me endpoint through the connector to retrieve
        the authenticated user's information from the external service.

        Args:
            connector_id: The connector's unique identifier (e.g., shared_asana)
            connection_id: The connection's unique identifier (GUID)

        Returns:
            Dict with user info (varies by connector), or empty dict if not supported

        Raises:
            ClientError: If the request fails
        """
        apihub_token = get_access_token("https://apihub.azure.com")

        # Map connectors to their user info endpoints
        user_endpoints = {
            "shared_asana": "/v2/users/me",
            "shared_office365": "/v2/Me",
            "shared_sharepointonline": "/_api/web/currentuser",
            "shared_dynamicscrmonline": "/api/data/v9.2/WhoAmI",
        }

        # Get the appropriate endpoint for this connector
        endpoint = user_endpoints.get(connector_id)
        if not endpoint:
            return {}

        url = f"https://msmanaged-na.azure-apim.net/apim/{connector_id.replace('shared_', '')}/{connection_id}{endpoint}"

        headers = {
            "Authorization": f"Bearer {apihub_token}",
            "Accept": "application/json",
        }

        try:
            response = self._http_client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception:
            # Silently return empty if we can't get user info
            return {}

    def bind_user_connection(
        self,
        bot_id: str,
        connector_id: str,
        connection_id: str,
        environment_id: Optional[str] = None,
    ) -> dict:
        """
        Bind a connection to a Copilot Studio bot (agent).

        This uses the Power Platform user-connections API to associate a connection
        with a bot, enabling the bot to use the connection's credentials when
        executing connector tools.

        This is the same operation performed by the Copilot Studio UI when you
        click "Connect" on a connector tool's connection prompt.

        Args:
            bot_id: The bot's unique identifier (GUID)
            connector_id: The connector's identifier (e.g., shared_asana or
                         shared_asana-20tasks-20api-5fd251d00e-f825669a42b5e533)
            connection_id: The connection's unique identifier (GUID)
            environment_id: Power Platform environment ID. If not provided,
                           will use DATAVERSE_ENVIRONMENT_ID from config.

        Returns:
            Dict containing:
                - success: True if binding succeeded
                - bot_id: The bot ID
                - connector_id: The connector ID
                - connection_id: The connection ID
                - binding_key: The full binding key used

        Raises:
            ClientError: If the binding fails

        Example:
            >>> client.bind_user_connection(
            ...     bot_id="12345678-1234-1234-1234-123456789abc",
            ...     connector_id="shared_asana",
            ...     connection_id="abcdef01-2345-6789-abcd-ef0123456789"
            ... )
        """
        # Get environment ID from config if not provided
        if not environment_id:
            config = get_config()
            environment_id = config.environment_id
            if not environment_id:
                raise ClientError(
                    "Environment ID not found. Please set DATAVERSE_ENVIRONMENT_ID "
                    "in your .env file or provide the environment_id parameter."
                )

        # Get bot details to retrieve schema name (bot_internal_id)
        bot = self.get_bot(bot_id)
        bot_schema = bot.get("schemaname")
        if not bot_schema:
            raise ClientError(
                f"Could not get schemaname for bot {bot_id}. "
                "The bot may not exist or you may not have access to it."
            )

        # Normalize connection_id - remove dashes for the binding key
        connection_id_normalized = connection_id.replace("-", "")

        # Build the connector bindings key
        # Format: {bot_schema}.{connector_id}.{connection_id_no_dashes}
        binding_key = f"{bot_schema}.{connector_id}.{connection_id_normalized}"

        # Build the request body
        request_body = {
            "connectorBindings": {
                binding_key: {
                    "connectorId": f"/providers/Microsoft.PowerApps/apis/{connector_id}",
                    "connectionId": connection_id_normalized
                }
            },
            "flowBindings": {},
            "aiModelBindings": {}
        }

        # Get Power Platform API token
        powerplatform_token = get_access_token("https://api.powerplatform.com")

        # Extract GUID from environment ID if it's in "Default-{GUID}" format
        # The API URL uses just the GUID portion, not the "Default-" prefix
        env_guid = environment_id
        if environment_id.lower().startswith("default-"):
            env_guid = environment_id[8:]  # Remove "Default-" prefix

        # Transform environment GUID to Power Platform API URL format
        # The environment ID needs special formatting for the API URL:
        # 1. Remove all dashes from the GUID
        # 2. Insert a period before the last 2 characters
        # Example: "6b6c3ede-aa0d-4268-a46f-96b7621b13a4" -> "6b6c3edeaa0d4268a46f96b7621b13.a4"
        # Reference: https://dev.to/wyattdave/the-4-apis-of-the-power-platform-1mm8
        env_guid_no_dashes = env_guid.replace("-", "")
        # Insert period before last 2 chars
        env_url_id = f"{env_guid_no_dashes[:-2]}.{env_guid_no_dashes[-2:]}"

        # Build the API URL
        # Format: https://default{formatted_env_id}.environment.api.powerplatform.com/powervirtualagents/bots/{bot_schema}/channels/pva-studio/user-connections
        url = (
            f"https://{env_url_id}.environment.api.powerplatform.com"
            f"/powervirtualagents/bots/{bot_schema}/channels/pva-studio/user-connections"
            f"?api-version=2022-03-01-preview"
        )

        headers = {
            "Authorization": f"Bearer {powerplatform_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            response = self._http_client.post(url, headers=headers, json=request_body, timeout=60.0)
            response.raise_for_status()

            # API returns 204 No Content on success
            return {
                "success": True,
                "bot_id": bot_id,
                "bot_schema": bot_schema,
                "connector_id": connector_id,
                "connection_id": connection_id,
                "binding_key": binding_key,
            }
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                if "error" in error_body:
                    error_detail = error_body["error"].get("message", str(error_body))
                elif "message" in error_body:
                    error_detail = error_body.get("message", str(error_body))
                else:
                    error_detail = str(error_body)
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to bind connection to bot: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Connection binding request failed: {e}")

    # ========================================================================
    # Channel Management Methods
    # ========================================================================

    def get_directline_token(self, bot_schema: str) -> dict:
        """
        Get a Direct Line token for a bot.

        Uses the PVA Studio API to retrieve a Direct Line token that can be used
        to start conversations with the bot programmatically.

        Args:
            bot_schema: The bot's schema name (e.g., 'pub_searchExpert')

        Returns:
            dict with 'token', 'conversationId', 'expires_in' keys
        """
        config = get_config()
        environment_id = config.environment_id
        if not environment_id:
            raise ClientError(
                "Environment ID not found. Please set DATAVERSE_ENVIRONMENT_ID "
                "in your .env file or provide the environment_id parameter."
            )

        powerplatform_token = get_access_token("https://api.powerplatform.com")

        # Format environment ID for PVA API URL
        env_guid = environment_id
        if environment_id.lower().startswith("default-"):
            env_guid = environment_id[8:]
        env_guid_no_dashes = env_guid.replace("-", "")
        env_url_id = f"{env_guid_no_dashes[:-2]}.{env_guid_no_dashes[-2:]}"

        url = (
            f"https://{env_url_id}.environment.api.powerplatform.com"
            f"/powervirtualagents/botsbyschema/{bot_schema}/directline/token"
            f"?api-version=2022-03-01-preview"
        )

        headers = {
            "Authorization": f"Bearer {powerplatform_token}",
            "Accept": "application/json",
        }

        try:
            response = self._http_client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                if "error" in error_body:
                    error_detail = error_body["error"].get("message", str(error_body))
                elif "message" in error_body:
                    error_detail = error_body.get("message", str(error_body))
                else:
                    error_detail = str(error_body)
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to get Direct Line token: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Direct Line token request failed: {e}")

    def get_bot_channel_info(self, bot_id: str) -> dict:
        """
        Get channel configuration information from a bot's Dataverse record.

        Reads applicationmanifestinformation and Configuration fields from the bot entity.

        Args:
            bot_id: The bot's Dataverse GUID

        Returns:
            dict with 'bot_id', 'schema_name', 'bot_name', 'channels',
            'teams_manifest', 'configuration' keys
        """
        select_fields = "applicationmanifestinformation,configuration,schemaname,name"
        url = f"{self.api_url}/bots({bot_id})?$select={select_fields}"

        headers = self._get_headers()

        try:
            response = self._http_client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                if "error" in error_body:
                    error_detail = error_body["error"].get("message", str(error_body))
                elif "message" in error_body:
                    error_detail = error_body.get("message", str(error_body))
                else:
                    error_detail = str(error_body)
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"Failed to get bot channel info: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Bot channel info request failed: {e}")

        # Parse the JSON fields
        teams_manifest = None
        manifest_raw = data.get("applicationmanifestinformation")
        if manifest_raw:
            try:
                teams_manifest = json.loads(manifest_raw)
            except (json.JSONDecodeError, TypeError):
                teams_manifest = {"raw": manifest_raw}

        configuration = None
        config_raw = data.get("configuration")
        if config_raw:
            try:
                configuration = json.loads(config_raw)
            except (json.JSONDecodeError, TypeError):
                configuration = {"raw": config_raw}

        schema_name = data.get("schemaname", "")

        # Build channel info
        channels = []

        # Direct Line is always available for published bots
        channels.append({
            "name": "Direct Line",
            "type": "directline",
            "status": "Available",
            "description": "API-based channel for programmatic conversations",
        })

        # Teams info from manifest
        if teams_manifest and isinstance(teams_manifest, dict) and teams_manifest.get("teams"):
            teams_data = teams_manifest["teams"]
            channels.append({
                "name": "Microsoft Teams",
                "type": "msteams",
                "status": "Configured" if teams_data.get("version") else "Available",
                "description": "Teams app integration",
                "version": teams_data.get("version"),
            })

        # Web Chat is always available alongside Direct Line
        channels.append({
            "name": "Web Chat",
            "type": "webchat",
            "status": "Available",
            "description": "Embeddable web chat widget",
        })

        return {
            "bot_id": bot_id,
            "schema_name": schema_name,
            "bot_name": data.get("name", ""),
            "channels": channels,
            "teams_manifest": teams_manifest,
            "configuration": configuration,
        }

    # ========================================================================
    # Power Platform Environment API - Flow Testing Methods
    # ========================================================================

    def _get_powerplatform_env_api_base_url(self, environment_id: str) -> str:
        """
        Build the Power Platform Environment API base URL.

        The environment ID needs special formatting for the API URL:
        1. Remove "Default-" prefix if present
        2. Remove all dashes from the GUID
        3. Insert a period before the last 2 characters

        Example: "Default-12345678-1234-1234-1234-123456789012"
              -> "https://123456781234123412341234567890.12.environment.api.powerplatform.com"

        Args:
            environment_id: The environment ID (with or without "Default-" prefix)

        Returns:
            The base URL for the Power Platform Environment API
        """
        # Extract GUID from environment ID if it's in "Default-{GUID}" format
        env_guid = environment_id
        if environment_id.lower().startswith("default-"):
            env_guid = environment_id[8:]  # Remove "Default-" prefix

        # Transform environment GUID to Power Platform API URL format
        env_guid_no_dashes = env_guid.replace("-", "")
        # Insert period before last 2 chars
        env_url_id = f"{env_guid_no_dashes[:-2]}.{env_guid_no_dashes[-2:]}"

        return f"https://{env_url_id}.environment.api.powerplatform.com"

    def _get_powerplatform_headers(self) -> dict:
        """Get headers for Power Platform Environment API requests."""
        # Power Automate flow APIs require the Flow service resource token
        token = get_access_token("https://service.flow.microsoft.com")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def get_flow_trigger_histories(self, workflow_id: str) -> list:
        """
        List trigger execution history for an agent flow.

        Args:
            workflow_id: The flow's unique identifier (GUID)

        Returns:
            List of trigger history entries with id, startTime, status, etc.
        """
        config = get_config()
        if not config.environment_id:
            raise ClientError("DATAVERSE_ENVIRONMENT_ID or POWERPLATFORM_ENVIRONMENT_ID environment variable is required")
        # Use the Flow Management API endpoint
        url = f"https://api.flow.microsoft.com/providers/Microsoft.ProcessSimple/environments/{config.environment_id}/flows/{workflow_id}/triggers/manual/histories?api-version=2016-11-01"

        headers = self._get_powerplatform_headers()

        try:
            response = self._http_client.get(url, headers=headers, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            return data.get("value", [])
        except httpx.HTTPStatusError as e:
            error_detail = self._extract_error_detail(e.response)
            raise ClientError(f"Failed to get flow trigger histories: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Flow trigger histories request failed: {e}")

    def resubmit_flow_trigger(self, workflow_id: str, history_id: str) -> dict:
        """
        Resubmit a previous trigger to run the flow.

        Args:
            workflow_id: The flow's unique identifier (GUID)
            history_id: The trigger history ID to resubmit

        Returns:
            Response containing run information
        """
        config = get_config()
        if not config.environment_id:
            raise ClientError("DATAVERSE_ENVIRONMENT_ID or POWERPLATFORM_ENVIRONMENT_ID environment variable is required")
        # Use the Flow Management API endpoint
        url = f"https://api.flow.microsoft.com/providers/Microsoft.ProcessSimple/environments/{config.environment_id}/flows/{workflow_id}/triggers/manual/histories/{history_id}/resubmit?api-version=2016-11-01"

        headers = self._get_powerplatform_headers()

        try:
            response = self._http_client.post(url, headers=headers, timeout=60.0)
            response.raise_for_status()
            # May return 202 Accepted with run info
            if response.status_code == 202 or response.status_code == 200:
                try:
                    return response.json()
                except Exception:
                    return {"success": True, "status_code": response.status_code}
            return {"success": True, "status_code": response.status_code}
        except httpx.HTTPStatusError as e:
            error_detail = self._extract_error_detail(e.response)
            raise ClientError(f"Failed to resubmit flow trigger: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Flow trigger resubmit request failed: {e}")

    def get_flow_callback_url(self, workflow_id: str) -> dict:
        """
        Get the callback URL for manual flow invocation.

        Uses the Flow Management API (api.flow.microsoft.com) to retrieve
        the callback URL for HTTP-triggered flows.

        Args:
            workflow_id: The flow's unique identifier (GUID)

        Returns:
            Dict containing 'value' with the callback URL
        """
        config = get_config()
        if not config.environment_id:
            raise ClientError("DATAVERSE_ENVIRONMENT_ID or POWERPLATFORM_ENVIRONMENT_ID environment variable is required")

        # Use the Flow Management API endpoint (not the environment API)
        # Format: POST https://api.flow.microsoft.com/providers/Microsoft.ProcessSimple/environments/{env}/flows/{flow}/triggers/manual/listCallbackUrl
        url = f"https://api.flow.microsoft.com/providers/Microsoft.ProcessSimple/environments/{config.environment_id}/flows/{workflow_id}/triggers/manual/listCallbackUrl?api-version=2016-11-01"

        headers = self._get_powerplatform_headers()

        try:
            response = self._http_client.post(url, headers=headers, timeout=60.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            error_detail = self._extract_error_detail(e.response)
            raise ClientError(f"Failed to get flow callback URL: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Flow callback URL request failed: {e}")

    def invoke_flow_manual(self, callback_url: str, body: dict) -> dict:
        """
        Invoke a flow using its callback URL.

        Args:
            callback_url: The flow's callback URL (from get_flow_callback_url)
            body: The JSON body to send to the flow

        Returns:
            Response from the flow invocation
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # Use 5 minute timeout for flow invocations since flows can take
        # several minutes to complete, especially when they involve AI processing
        try:
            response = self._http_client.post(callback_url, headers=headers, json=body, timeout=300.0)
            response.raise_for_status()
            try:
                return response.json()
            except Exception:
                return {"success": True, "status_code": response.status_code}
        except httpx.HTTPStatusError as e:
            error_detail = self._extract_error_detail(e.response)
            raise ClientError(f"Failed to invoke flow: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Flow invocation request failed: {e}")

    def list_flow_runs(self, workflow_id: str, top: int = 50) -> list:
        """
        List flow run executions.

        Args:
            workflow_id: The flow's unique identifier (GUID)
            top: Maximum number of runs to return (default: 50)

        Returns:
            List of flow run entries
        """
        config = get_config()
        if not config.environment_id:
            raise ClientError("DATAVERSE_ENVIRONMENT_ID or POWERPLATFORM_ENVIRONMENT_ID environment variable is required")
        # Use the Flow Management API endpoint
        url = f"https://api.flow.microsoft.com/providers/Microsoft.ProcessSimple/environments/{config.environment_id}/flows/{workflow_id}/runs?api-version=2016-11-01&$top={top}"

        headers = self._get_powerplatform_headers()

        try:
            response = self._http_client.get(url, headers=headers, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            return data.get("value", [])
        except httpx.HTTPStatusError as e:
            error_detail = self._extract_error_detail(e.response)
            raise ClientError(f"Failed to list flow runs: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Flow runs list request failed: {e}")

    def get_flow_run(self, workflow_id: str, run_id: str, expand_actions: bool = True) -> dict:
        """
        Get details for a specific flow run.

        Args:
            workflow_id: The flow's unique identifier (GUID)
            run_id: The run's unique identifier
            expand_actions: Whether to include action details (default: True)

        Returns:
            Flow run details including status and action results
        """
        config = get_config()
        if not config.environment_id:
            raise ClientError("DATAVERSE_ENVIRONMENT_ID or POWERPLATFORM_ENVIRONMENT_ID environment variable is required")
        # Use the Flow Management API endpoint
        url = f"https://api.flow.microsoft.com/providers/Microsoft.ProcessSimple/environments/{config.environment_id}/flows/{workflow_id}/runs/{run_id}?api-version=2016-11-01"
        if expand_actions:
            url += "&$expand=properties/actions"

        headers = self._get_powerplatform_headers()

        try:
            response = self._http_client.get(url, headers=headers, timeout=60.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            error_detail = self._extract_error_detail(e.response)
            raise ClientError(f"Failed to get flow run: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Flow run request failed: {e}")

    def cancel_flow_run(self, workflow_id: str, run_id: str) -> dict:
        """
        Cancel a running flow run.

        Args:
            workflow_id: The flow's unique identifier (GUID)
            run_id: The run's unique identifier

        Returns:
            Dict with status_code and (optional) response body. Successful cancels
            typically return 200 or 202 with an empty body.
        """
        config = get_config()
        if not config.environment_id:
            raise ClientError("DATAVERSE_ENVIRONMENT_ID or POWERPLATFORM_ENVIRONMENT_ID environment variable is required")
        # Use the Flow Management API endpoint
        url = f"https://api.flow.microsoft.com/providers/Microsoft.ProcessSimple/environments/{config.environment_id}/flows/{workflow_id}/runs/{run_id}/cancel?api-version=2016-11-01"

        headers = self._get_powerplatform_headers()

        try:
            response = self._http_client.post(url, headers=headers, timeout=60.0)
            response.raise_for_status()
            result = {"status_code": response.status_code}
            # Cancel often returns no body; only parse when there is content.
            if response.content:
                try:
                    result["body"] = response.json()
                except ValueError:
                    result["body"] = response.text
            return result
        except httpx.HTTPStatusError as e:
            error_detail = self._extract_error_detail(e.response)
            raise ClientError(f"Failed to cancel flow run: HTTP {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"Flow run cancel request failed: {e}")

    # =========================================================================
    # Permission Management Methods
    # =========================================================================

    def grant_access(
        self,
        odata_type: str,
        id_field: str,
        entity_id: str,
        principal_id: str,
        access_mask: str = "ReadAccess",
    ) -> None:
        """
        Grant access to a Dataverse record for a principal (user or team).

        Uses the ModifyAccess action to grant permissions.

        Args:
            odata_type: OData type for the entity (e.g., "Microsoft.Dynamics.CRM.msdyn_aimodel")
            id_field: The ID field name for the entity (e.g., "msdyn_aimodelid")
            entity_id: The GUID of the record to grant access to
            principal_id: The GUID of the systemuser or team to grant access to
            access_mask: Access level to grant. Options:
                - "ReadAccess" (default) - Read-only access
                - "WriteAccess" - Write/edit access
                - "DeleteAccess" - Delete access
                - "ShareAccess" - Re-share capability
                - "AssignAccess" - Reassign ownership
                - Combine with commas: "ReadAccess,WriteAccess"

        Raises:
            ClientError: If the grant operation fails
        """
        payload = {
            "Target": {
                "@odata.type": odata_type,
                id_field: entity_id,
            },
            "PrincipalAccess": {
                "Principal": {
                    "@odata.type": "Microsoft.Dynamics.CRM.systemuser",
                    "systemuserid": principal_id,
                },
                "AccessMask": access_mask,
            },
        }

        try:
            self.post("ModifyAccess", payload)
        except ClientError as e:
            raise ClientError(f"Failed to grant access: {e}")

    def revoke_access(
        self,
        odata_type: str,
        id_field: str,
        entity_id: str,
        principal_id: str,
    ) -> None:
        """
        Revoke all access to a Dataverse record for a principal.

        Uses the RevokeAccess action to remove permissions.

        Args:
            odata_type: OData type for the entity (e.g., "Microsoft.Dynamics.CRM.msdyn_aimodel")
            id_field: The ID field name for the entity (e.g., "msdyn_aimodelid")
            entity_id: The GUID of the record to revoke access from
            principal_id: The GUID of the systemuser or team to revoke access from

        Raises:
            ClientError: If the revoke operation fails
        """
        payload = {
            "Target": {
                "@odata.type": odata_type,
                id_field: entity_id,
            },
            "Revokee": {
                "@odata.type": "Microsoft.Dynamics.CRM.systemuser",
                "systemuserid": principal_id,
            },
        }

        try:
            self.post("RevokeAccess", payload)
        except ClientError as e:
            raise ClientError(f"Failed to revoke access: {e}")

    def list_principals_with_access(
        self,
        entity_logical_name: str,
        entity_id: str,
    ) -> list[dict]:
        """
        List all principals (users/teams) that have explicit access to a record.

        Queries the principalobjectaccessset table.

        Args:
            entity_logical_name: Logical name of the entity (e.g., "msdyn_aimodel")
            entity_id: The GUID of the record

        Returns:
            List of dicts with principal info:
            [
                {
                    "principal_id": "guid",
                    "principal_type": "systemuser" | "team",
                    "access_rights": 1,  # bitmask
                    "access_rights_display": "ReadAccess"
                },
                ...
            ]

        Raises:
            ClientError: If the query fails
        """
        # Query principalobjectaccessset for this record
        # Note: objectid is the record GUID, objecttypecode varies by entity
        filter_query = f"objectid eq '{entity_id}'"
        select = "principalid,principaltypecode,accessrightsmask"

        try:
            result = self.get(
                "principalobjectaccessset",
                params={
                    "$filter": filter_query,
                    "$select": select,
                },
            )

            principals = []
            for record in result.get("value", []):
                access_mask = record.get("accessrightsmask", 0)
                principal_type_code = record.get("principaltypecode", 8)

                # Convert type code to name (8 = systemuser, 9 = team)
                principal_type = "team" if principal_type_code == 9 else "systemuser"

                # Convert access mask to readable names
                access_names = []
                if access_mask & 1:
                    access_names.append("ReadAccess")
                if access_mask & 2:
                    access_names.append("WriteAccess")
                if access_mask & 4:
                    access_names.append("DeleteAccess")
                if access_mask & 8:
                    access_names.append("ShareAccess")
                if access_mask & 16:
                    access_names.append("AssignAccess")

                principals.append({
                    "principal_id": record.get("principalid"),
                    "principal_type": principal_type,
                    "access_rights": access_mask,
                    "access_rights_display": ",".join(access_names) if access_names else "None",
                })

            return principals

        except ClientError as e:
            raise ClientError(f"Failed to list principals with access: {e}")

    def get_systemuser_by_id(self, user_id: str) -> dict:
        """
        Get a systemuser record by ID.

        Args:
            user_id: The GUID of the systemuser

        Returns:
            Dict with user info including fullname, domainname, etc.

        Raises:
            ClientError: If the user is not found
        """
        try:
            return self.get(
                f"systemusers({user_id})",
                params={"$select": "systemuserid,fullname,domainname,internalemailaddress,isdisabled"},
            )
        except ClientError as e:
            raise ClientError(f"Failed to get systemuser: {e}")

    # =========================================================================
    # File Upload Methods (for knowledge sources and other file columns)
    # =========================================================================

    def create_file_knowledge_component(
        self,
        name: str,
        file_name: str,
        bot_id: Optional[str] = None,
        description: Optional[str] = None,
    ) -> str:
        """
        Create a botcomponent record for a file-based knowledge source.

        This creates the record but does NOT upload the file data. Use upload_file_single
        or upload_file_chunked to upload the file data to the filedata column.

        Args:
            name: Display name for the knowledge source
            file_name: Name of the file being uploaded
            bot_id: Optional bot's unique identifier (for associating with an agent)
            description: Optional description (auto-generated if not provided)

        Returns:
            The created component ID
        """
        # Generate schema name
        clean_name = re.sub(r'[^a-zA-Z0-9]', '', name)

        if bot_id:
            # Get bot schema name for generating component schema name
            bot = self.get_bot(bot_id)
            bot_schema = bot.get("schemaname") or f"{self._get_publisher_prefix()}_bot{bot_id[:8]}"
            schema_name = f"{bot_schema}.file.{clean_name}"
        else:
            # Standalone knowledge source
            import time
            timestamp = int(time.time())
            schema_name = f"{self._get_publisher_prefix()}_knowledge.file.{clean_name}_{timestamp}"

        # Auto-generate description if not provided
        if not description:
            description = f"This knowledge source searches information contained in {name}"

        component_data = {
            "componenttype": 14,  # Bot File Attachment
            "name": name,
            "schemaname": schema_name,
            "description": description,
        }

        # Only add bot binding if bot_id is provided
        if bot_id:
            component_data["parentbotid@odata.bind"] = f"/bots({bot_id})"

        # Use longer timeout for file operations
        url = f"{self.api_url}/botcomponents"
        headers = self._get_headers()
        response = self._http_client.post(url, headers=headers, json=component_data, timeout=120.0)
        response.raise_for_status()

        # Extract component ID from OData-EntityId header
        entity_id = response.headers.get("OData-EntityId", "")
        if entity_id:
            # Extract GUID from URL like .../botcomponents(guid)
            match = re.search(r'botcomponents\(([^)]+)\)', entity_id)
            if match:
                return match.group(1)
        return ""

    def upload_file_single(
        self,
        table: str,
        record_id: str,
        column: str,
        file_name: str,
        file_data: bytes,
        mime_type: Optional[str] = None,
    ) -> None:
        """
        Upload a file to a Dataverse file column in a single request.

        This method is suitable for files less than 128 MB.

        Args:
            table: Table logical name (e.g., 'botcomponents')
            record_id: Record GUID
            column: File column logical name (e.g., 'filedata')
            file_name: Name of the file
            file_data: Binary file content
            mime_type: Optional MIME type (defaults to application/octet-stream)

        Raises:
            ClientError: If upload fails
        """
        if mime_type is None:
            mime_type = "application/octet-stream"

        url = f"{self.api_url}/{table}({record_id})/{column}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/json",
            "Content-Type": "application/octet-stream",
            "x-ms-file-name": file_name,
            "Content-Length": str(len(file_data)),
        }

        try:
            response = self._http_client.patch(url, headers=headers, content=file_data, timeout=300.0)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_body = e.response.json()
                if "error" in error_body:
                    error_detail = error_body["error"].get("message", str(error_body))
            except Exception:
                error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"File upload failed (HTTP {e.response.status_code}): {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"File upload request failed: {e}")

    def upload_file_chunked(
        self,
        table: str,
        record_id: str,
        column: str,
        file_name: str,
        file_data: bytes,
        mime_type: Optional[str] = None,
        chunk_size: int = 4 * 1024 * 1024,  # 4 MB default
    ) -> None:
        """
        Upload a file to a Dataverse file column using chunked transfer.

        This method is suitable for files larger than 128 MB.

        Args:
            table: Table logical name (e.g., 'botcomponents')
            record_id: Record GUID
            column: File column logical name (e.g., 'filedata')
            file_name: Name of the file
            file_data: Binary file content
            mime_type: Optional MIME type (defaults to application/octet-stream)
            chunk_size: Size of each chunk in bytes (default 4 MB)

        Raises:
            ClientError: If upload fails
        """
        if mime_type is None:
            mime_type = "application/octet-stream"

        file_size = len(file_data)

        # Step 1: Initialize chunked upload
        init_url = f"{self.api_url}/{table}({record_id})/{column}?x-ms-file-name={file_name}"
        init_headers = {
            "Authorization": f"Bearer {self.access_token}",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/json",
            "x-ms-transfer-mode": "chunked",
        }

        try:
            init_response = self._http_client.patch(init_url, headers=init_headers, timeout=60.0)
            init_response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise ClientError(f"Chunked upload initialization failed (HTTP {e.response.status_code}): {e.response.text[:500]}")

        # Get the location URL with session token
        location_url = init_response.headers.get("Location")
        if not location_url:
            raise ClientError("Chunked upload: No Location header in response")

        # Get recommended chunk size from response (optional)
        server_chunk_size = init_response.headers.get("x-ms-chunk-size")
        if server_chunk_size:
            chunk_size = int(server_chunk_size)

        # Step 2: Upload chunks
        offset = 0
        while offset < file_size:
            # Calculate chunk boundaries
            range_end = min(offset + chunk_size - 1, file_size - 1)
            chunk = file_data[offset:range_end + 1]

            chunk_headers = {
                "Authorization": f"Bearer {self.access_token}",
                "OData-MaxVersion": "4.0",
                "OData-Version": "4.0",
                "Accept": "application/json",
                "Content-Type": "application/octet-stream",
                "x-ms-file-name": file_name,
                "Content-Range": f"bytes {offset}-{range_end}/{file_size}",
                "Content-Length": str(len(chunk)),
            }

            try:
                chunk_response = self._http_client.patch(location_url, headers=chunk_headers, content=chunk, timeout=300.0)
                # Expect 206 PartialContent for all but final chunk, 204 NoContent for final
                if chunk_response.status_code not in (200, 204, 206):
                    chunk_response.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise ClientError(f"Chunk upload failed at offset {offset} (HTTP {e.response.status_code}): {e.response.text[:500]}")

            offset = range_end + 1

    def download_file(
        self,
        table: str,
        record_id: str,
        column: str,
    ) -> bytes:
        """
        Download a file from a Dataverse file column.

        Args:
            table: Table logical name (e.g., 'botcomponents')
            record_id: Record GUID
            column: File column logical name (e.g., 'filedata')

        Returns:
            Binary file content

        Raises:
            ClientError: If download fails
        """
        url = f"{self.api_url}/{table}({record_id})/{column}/$value"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/octet-stream",
        }

        try:
            response = self._http_client.get(url, headers=headers, timeout=300.0)
            response.raise_for_status()

            # Check if we need to download in chunks
            file_size = response.headers.get("x-ms-file-size")
            if file_size and int(file_size) > 16 * 1024 * 1024:  # > 16 MB
                return self._download_file_chunked(url, headers, int(file_size))

            return response.content

        except httpx.HTTPStatusError as e:
            error_detail = e.response.text[:500] if e.response.text else str(e)
            raise ClientError(f"File download failed (HTTP {e.response.status_code}): {error_detail}")
        except httpx.RequestError as e:
            raise ClientError(f"File download request failed: {e}")

    def _download_file_chunked(self, url: str, base_headers: dict, file_size: int) -> bytes:
        """
        Download a file in chunks.

        Args:
            url: The file download URL
            base_headers: Base HTTP headers
            file_size: Total file size in bytes

        Returns:
            Complete binary file content
        """
        chunk_size = 4 * 1024 * 1024  # 4 MB
        chunks = []
        offset = 0

        while offset < file_size:
            range_end = min(offset + chunk_size - 1, file_size - 1)
            headers = base_headers.copy()
            headers["Range"] = f"bytes={offset}-{range_end}"

            try:
                response = self._http_client.get(url, headers=headers, timeout=300.0)
                response.raise_for_status()
                chunks.append(response.content)
            except httpx.HTTPStatusError as e:
                raise ClientError(f"Chunk download failed at offset {offset}: {e.response.text[:500]}")

            offset = range_end + 1

        return b"".join(chunks)

    def close(self):
        """Close the HTTP client."""
        self._http_client.close()


# Global client instance
_client: Optional[DataverseClient] = None


def _resolve_az_command() -> str:
    """Resolve the Azure CLI command, handling Windows where 'az' is 'az.cmd'."""
    if sys.platform == "win32":
        for candidate in ("az", "az.cmd"):
            path = shutil.which(candidate)
            if path:
                return path
        raise FileNotFoundError("Azure CLI not found")
    return "az"


def _is_az_cli_installed() -> bool:
    """Check whether Azure CLI is on PATH (cross-platform)."""
    if sys.platform == "win32":
        return any(shutil.which(c) for c in ("az", "az.cmd"))
    return shutil.which("az") is not None


def get_access_token_from_azure_cli(resource: str) -> str:
    """
    Get an access token using Azure CLI.

    Validates that the current Azure CLI user matches the profile's
    AZURE_CLI_EXPECTED_USER before acquiring a token.

    Args:
        resource: The resource URL to get a token for

    Returns:
        Access token string

    Raises:
        ClientError: If token acquisition fails or user mismatch
    """
    try:
        az = _resolve_az_command()

        # Validate Azure CLI user matches profile expectation
        config = get_config()
        expected_user = config.expected_user
        if expected_user:
            user_result = subprocess.run(
                [az, "account", "show", "--query", "user.name", "-o", "tsv"],
                capture_output=True, text=True, check=True,
            )
            actual_user = user_result.stdout.strip()
            if actual_user.lower() != expected_user.lower():
                raise ClientError(
                    f"Azure CLI is logged in as '{actual_user}' but profile "
                    f"'{config.get_active_profile_name()}' requires '{expected_user}'.\n\n"
                    f"  Run: az login --tenant {config.tenant_id or '<tenant-id>'}\n\n"
                    f"  Then authenticate as {expected_user}."
                )

        result = subprocess.run(
            [az, "account", "get-access-token", "--resource", resource, "--query", "accessToken", "-o", "tsv"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise ClientError(
            f"Failed to get access token from Azure CLI. "
            f"Make sure you're logged in with 'az login'. Error: {e.stderr}"
        )
    except FileNotFoundError:
        raise ClientError(
            "Azure CLI not found. Please install Azure CLI and login with 'az login'."
        )


# MSAL-based service principal token acquisition
_msal_app = None
_msal_app_key = None


def _get_msal_app(tenant_id: str, client_id: str, client_secret: str):
    """Get or create a cached MSAL ConfidentialClientApplication."""
    global _msal_app, _msal_app_key
    key = (tenant_id, client_id)
    if _msal_app is not None and _msal_app_key == key:
        return _msal_app
    import msal
    _msal_app = msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
    )
    _msal_app_key = key
    return _msal_app


def _get_access_token_from_service_principal(resource: str) -> str:
    """Acquire an access token using service principal credentials via MSAL."""
    config = get_config()
    app = _get_msal_app(config.tenant_id, config.azure_client_id, config.azure_client_secret)
    scopes = [f"{resource.rstrip('/')}/.default"]
    result = app.acquire_token_for_client(scopes=scopes)
    if "access_token" in result:
        return result["access_token"]
    error_msg = result.get("error_description", result.get("error", "Unknown MSAL error"))
    raise ClientError(f"Service principal token acquisition failed: {error_msg}")


def get_access_token(resource: str) -> str:
    """Get an access token for general CLI operations.

    The public Copilot CLI contract uses Azure CLI delegated auth for its
    normal Dataverse/Graph command surface. Service principal credentials can
    coexist in the active profile for command groups that explicitly opt into
    client-credential auth, but they must not silently hijack the default
    Dataverse client path.
    """
    return get_access_token_from_azure_cli(resource)


def get_client_for_environment(environment_id: str) -> "DataverseClient":
    """
    Get a Dataverse client for a specific environment.

    Resolves the environment ID to a Dataverse URL using the BAP API,
    then creates a client for that environment.

    Args:
        environment_id: The environment's unique identifier (e.g., Default-<tenant-id> or GUID)

    Returns:
        DataverseClient: Authenticated Dataverse API client for the specified environment

    Raises:
        ClientError: If environment not found or has no Dataverse instance
    """
    # Get environment details from BAP API
    bap_token = get_access_token("https://api.bap.microsoft.com/")

    url = (
        f"https://api.bap.microsoft.com/providers/Microsoft.BusinessAppPlatform/environments/{environment_id}"
        "?api-version=2021-04-01"
    )

    headers = {
        "Authorization": f"Bearer {bap_token}",
        "Accept": "application/json",
    }

    try:
        import httpx
        with httpx.Client() as http_client:
            response = http_client.get(url, headers=headers, timeout=60.0)
            response.raise_for_status()
            environment = response.json()
    except httpx.HTTPStatusError as e:
        raise ClientError(f"Environment not found: {environment_id} (HTTP {e.response.status_code})")

    # Extract Dataverse URL
    props = environment.get("properties", {})
    linked_env = props.get("linkedEnvironmentMetadata", {})
    dataverse_url = linked_env.get("instanceUrl", "")

    if not dataverse_url:
        display_name = props.get("displayName", environment_id)
        raise ClientError(
            f"Environment '{display_name}' does not have a linked Dataverse instance. "
            "Only environments with Dataverse can be queried."
        )

    # Get access token for this environment's Dataverse URL and create client
    access_token = get_access_token(dataverse_url)
    return DataverseClient(base_url=dataverse_url, access_token=access_token)


def get_client(dataverse_url: str = None, config=None) -> DataverseClient:
    """
    Get or create the global Dataverse client.

    Uses Azure CLI authentication by default (requires 'az login').

    Args:
        dataverse_url: Optional Dataverse URL override. If provided, bypasses
            config/env lookup and uses this URL directly.

    Returns:
        DataverseClient: Authenticated Dataverse API client

    Raises:
        ClientError: If credentials are missing or authentication fails
    """
    global _client

    if _client is not None and dataverse_url is None:
        return _client

    if dataverse_url is None:
        config = get_config()

        # Check for missing credentials
        missing = config.get_missing_credentials()
        if missing:
            error_msg = "Missing required credentials: " + ", ".join(missing) + "\n\n"

            if _is_az_cli_installed():
                error_msg += (
                    "Quick start:\n"
                    "  1. Run:  copilot auth login\n"
                    "     (runs `az login` if needed and prompts for DATAVERSE_URL)\n\n"
                )
            else:
                error_msg += (
                    "Azure CLI ('az') is not installed. Install it first:\n"
                    "  https://learn.microsoft.com/cli/azure/install-azure-cli\n\n"
                    "Then run:\n"
                    "  copilot auth login\n\n"
                )

            error_msg += (
                "Or manually:\n"
                f"  Edit:  {config.env_file_path}\n"
                "  Add:   DATAVERSE_URL=https://yourorg.crm.dynamics.com\n\n"
                "Find your Dataverse URL in the Power Platform admin center:\n"
                "  https://admin.powerplatform.microsoft.com\n"
            )

            raise ClientError(error_msg)

        dataverse_url = config.dataverse_url

    try:
        access_token = get_access_token(dataverse_url)
        _client = DataverseClient(dataverse_url, access_token)
        return _client
    except Exception as e:
        raise ClientError(f"Failed to authenticate: {e}")


def reset_client():
    """Reset the global client instance (useful for testing)."""
    global _client
    if _client is not None:
        _client.close()
    _client = None
