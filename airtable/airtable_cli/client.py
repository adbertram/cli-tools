"""Airtable API client with automatic token management."""
import random
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

import requests

from .config import get_config
from cli_tools_shared import FilterMap
from cli_tools_shared.filters import FilterValidationError, validate_filters

from cli_tools_shared.exceptions import ClientError


class AirtableClient:
    """Client for interacting with Airtable API."""

    # Retry configuration
    MAX_RETRIES = 3
    BASE_DELAY = 1.0
    MAX_DELAY = 30.0
    JITTER = 0.1

    # Retryable HTTP status codes
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(self, profile=None):
        """Initialize Airtable client from configuration."""
        self.config = get_config(profile=profile)

        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'airtable auth login' to authenticate."
            )

        self.base_url = self.config.base_url
        self._update_headers()

    def _update_headers(self):
        """Update request headers with current credentials."""
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        # Use Personal Access Token as Bearer token
        if self.config.personal_access_token:
            self.headers["Authorization"] = f"Bearer {self.config.personal_access_token}"

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
    ) -> Dict:
        """
        Make an HTTP request to the Airtable API with optional retry.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: API endpoint path (e.g., "/appXXX/TableName")
            data: Request body data
            params: Query parameters
            retry: Whether to use exponential retry for transient errors

        Returns:
            Response JSON data

        Raises:
            ClientError: If request fails
        """
        url = f"{self.base_url}{endpoint}"
        max_attempts = self.MAX_RETRIES if retry else 1

        for attempt in range(max_attempts):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    json=data,
                    params=params,
                )

                # Check for retryable status codes
                if retry and response.status_code in self.RETRYABLE_STATUS_CODES:
                    if attempt < max_attempts - 1:
                        # Honor Retry-After header if present
                        if "Retry-After" in response.headers:
                            delay = int(response.headers["Retry-After"])
                        else:
                            delay = min(
                                self.BASE_DELAY * (2 ** attempt) + random.uniform(0, self.JITTER),
                                self.MAX_DELAY,
                            )
                        time.sleep(delay)
                        continue

                if not response.ok:
                    try:
                        error_data = response.json()
                        error_msg = (
                            error_data.get("error", {}).get("message")
                            or error_data.get("message")
                            or error_data.get("error")
                            or response.text
                        )
                    except Exception:
                        error_msg = response.text
                    raise ClientError(f"API request failed ({response.status_code}): {error_msg}")

                # Handle empty response (204 No Content)
                if response.status_code == 204:
                    return {}

                return response.json()

            except (requests.ConnectionError, requests.Timeout) as e:
                if attempt < max_attempts - 1:
                    delay = min(
                        self.BASE_DELAY * (2 ** attempt) + random.uniform(0, self.JITTER),
                        self.MAX_DELAY,
                    )
                    time.sleep(delay)
                    continue
                raise ClientError(f"Connection error: {e}")

        raise ClientError("Max retries exceeded")

    # ==================== API Methods ====================

    def list_records(
        self,
        base_id: str,
        table_id: str,
        limit: int = 100,
        offset: Optional[str] = None,
        view: Optional[str] = None,
        sort: Optional[List[Dict[str, str]]] = None,
        filter_by_formula: Optional[str] = None,
        fields: Optional[List[str]] = None,
        filters: Optional[List[str]] = None,
    ) -> Dict:
        """
        List records from a table with auto-pagination.

        Args:
            base_id: The base ID (e.g., appXXXXXXXXXXXXXX)
            table_id: The table ID or name
            limit: Maximum total records to return
            offset: Offset from previous request for pagination
            view: Name or ID of a view to filter records
            sort: List of sort objects with 'field' and optional 'direction'
            filter_by_formula: Formula to filter records
            fields: Only return specific fields
            filters: Standard CLI filter strings (field:op:value)

        Returns:
            Response with records list and optional offset
        """
        API_MAX_PAGE_SIZE = 100
        endpoint = f"/{base_id}/{table_id}"

        all_records = []
        remaining = limit
        current_offset = offset

        while remaining > 0:
            page_size = min(remaining, API_MAX_PAGE_SIZE)
            params = {"pageSize": page_size}

            if current_offset:
                params["offset"] = current_offset
            if view:
                params["view"] = view
            if sort:
                for i, s in enumerate(sort):
                    params[f"sort[{i}][field]"] = s["field"]
                    if "direction" in s:
                        params[f"sort[{i}][direction]"] = s["direction"]
            if filter_by_formula:
                params["filterByFormula"] = filter_by_formula
            if fields:
                for field in fields:
                    params.setdefault("fields[]", []).append(field)

            # Translate standard filters to Airtable formula
            if filters:
                formula = self._filters_to_formula(filters)
                if formula:
                    if "filterByFormula" in params:
                        params["filterByFormula"] = f"AND({params['filterByFormula']},{formula})"
                    else:
                        params["filterByFormula"] = formula

            result = self._make_request("GET", endpoint, params=params)
            records = result.get("records", [])
            all_records.extend(records)
            remaining -= len(records)

            # Stop if no more pages
            next_offset = result.get("offset")
            if not next_offset or len(records) < page_size:
                break
            current_offset = next_offset

        response = {"records": all_records}
        if result.get("offset") and remaining > 0:
            response["offset"] = result["offset"]
        return response

    def _filters_to_formula(self, filters: List[str]) -> Optional[str]:
        """Convert standard filter strings (field:op:value) to Airtable formula.

        Translates CLI filter syntax to Airtable filterByFormula API parameter.
        """
        from cli_tools_shared.filters import parse_filter_string

        def _is_numeric(v: str) -> bool:
            if v is None:
                return False
            try:
                float(v)
                return True
            except (ValueError, TypeError):
                return False

        def _esc(v: str) -> str:
            return v.replace("'", "\\'")

        def _quote(v: str) -> str:
            if _is_numeric(v):
                return v
            return f"'{_esc(v)}'"

        formulas = []
        for f_str in filters:
            conditions = parse_filter_string(f_str)
            for field, op, val in conditions:
                if op == "eq":
                    formulas.append(f"{{{field}}}={_quote(val)}")
                elif op == "ne":
                    formulas.append(f"{{{field}}}!={_quote(val)}")
                elif op == "gt":
                    formulas.append(f"{{{field}}}>{_quote(val)}")
                elif op == "gte":
                    formulas.append(f"{{{field}}}>={_quote(val)}")
                elif op == "lt":
                    formulas.append(f"{{{field}}}<{_quote(val)}")
                elif op == "lte":
                    formulas.append(f"{{{field}}}<={_quote(val)}")
                elif op == "contains":
                    formulas.append(f"FIND('{_esc(val)}',{{{field}}})>0")
                elif op in ("like", "ilike"):
                    formulas.append(
                        f"FIND(LOWER('{_esc(val)}'),LOWER({{{field}}}&''))>0"
                    )
                elif op == "startswith":
                    formulas.append(f"LEFT({{{field}}},{len(val)})='{_esc(val)}'")
                elif op == "endswith":
                    formulas.append(f"RIGHT({{{field}}},{len(val)})='{_esc(val)}'")
                elif op == "in":
                    options = val.split("|")
                    or_parts = [f"{{{field}}}={_quote(o)}" for o in options]
                    formulas.append(f"OR({','.join(or_parts)})")
                elif op == "nin":
                    options = val.split("|")
                    and_parts = [f"{{{field}}}!={_quote(o)}" for o in options]
                    formulas.append(f"AND({','.join(and_parts)})")
                elif op == "null":
                    formulas.append(f"{{{field}}}=BLANK()")
                elif op == "notnull":
                    formulas.append(f"{{{field}}}!=BLANK()")
                else:
                    raise FilterValidationError(
                        f"Unsupported operator '{op}' for Airtable filter formula"
                    )

        if not formulas:
            return None
        if len(formulas) == 1:
            return formulas[0]
        return f"AND({','.join(formulas)})"

    def get_record(self, base_id: str, table_id: str, record_id: str) -> Dict:
        """Get a specific record by ID."""
        endpoint = f"/{base_id}/{table_id}/{record_id}"
        return self._make_request("GET", endpoint)

    def update_record(
        self,
        base_id: str,
        table_id: str,
        record_id: str,
        fields: Dict[str, Any],
        typecast: bool = False,
    ) -> Dict:
        """Update a record (PATCH - only updates specified fields)."""
        endpoint = f"/{base_id}/{table_id}/{record_id}"
        data = {"fields": fields}
        if typecast:
            data["typecast"] = True
        return self._make_request("PATCH", endpoint, data=data)

    def replace_record(
        self,
        base_id: str,
        table_id: str,
        record_id: str,
        fields: Dict[str, Any],
        typecast: bool = False,
    ) -> Dict:
        """Replace a record (PUT - clears unspecified fields)."""
        endpoint = f"/{base_id}/{table_id}/{record_id}"
        data = {"fields": fields}
        if typecast:
            data["typecast"] = True
        return self._make_request("PUT", endpoint, data=data)

    def create_record(
        self,
        base_id: str,
        table_id: str,
        fields: Dict[str, Any],
        typecast: bool = False,
    ) -> Dict:
        """Create a new record."""
        endpoint = f"/{base_id}/{table_id}"
        data = {"fields": fields}
        if typecast:
            data["typecast"] = True
        return self._make_request("POST", endpoint, data=data)

    def delete_record(self, base_id: str, table_id: str, record_id: str) -> Dict:
        """Delete a record."""
        endpoint = f"/{base_id}/{table_id}/{record_id}"
        return self._make_request("DELETE", endpoint)

    def create_field(
        self,
        base_id: str,
        table_id: str,
        name: str,
        field_type: str,
        description: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        """Create a field in an Airtable table."""
        endpoint = f"/meta/bases/{base_id}/tables/{table_id}/fields"
        data: Dict[str, Any] = {
            "name": name,
            "type": field_type,
        }
        if description is not None:
            data["description"] = description
        if options is not None:
            data["options"] = options
        return self._make_request("POST", endpoint, data=data)

    def update_field(
        self,
        base_id: str,
        table_id: str,
        field_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        """Update a field's name, description, or options."""
        endpoint = f"/meta/bases/{base_id}/tables/{table_id}/fields/{field_id}"
        data: Dict[str, Any] = {}
        if name is not None:
            data["name"] = name
        if description is not None:
            data["description"] = description
        if options is not None:
            data["options"] = options
        if not data:
            raise ClientError("At least one of --name, --description, or --options must be specified")
        return self._make_request("PATCH", endpoint, data=data)

    def list_fields(self, base_id: str, table_id: str) -> List[Dict[str, Any]]:
        """List fields for a table in an Airtable base."""
        endpoint = f"/meta/bases/{base_id}/tables"
        result = self._make_request("GET", endpoint)
        for table in result.get("tables", []):
            if table.get("id") == table_id or table.get("name") == table_id:
                return table.get("fields", [])
        raise ClientError(f"Table not found in base metadata: {table_id}")

    def get_field(self, base_id: str, table_id: str, field_id: str) -> Dict[str, Any]:
        """Get one field by ID or name from a table schema."""
        for field in self.list_fields(base_id, table_id):
            if field.get("id") == field_id or field.get("name") == field_id:
                return field
        raise ClientError(f"Field not found in table metadata: {field_id}")

    def list_tables(self, base_id: str) -> List[Dict[str, Any]]:
        """List all tables in an Airtable base.

        Hits GET /meta/bases/{baseId}/tables and returns the tables array.
        """
        endpoint = f"/meta/bases/{base_id}/tables"
        result = self._make_request("GET", endpoint)
        return result.get("tables", [])

    def get_table(self, base_id: str, table_id: str) -> Dict[str, Any]:
        """Get one table by ID or name from base metadata."""
        for table in self.list_tables(base_id):
            if table.get("id") == table_id or table.get("name") == table_id:
                return table
        raise ClientError(f"Table not found in base metadata: {table_id}")

    def create_table(
        self,
        base_id: str,
        name: str,
        description: Optional[str] = None,
        fields: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Create a new table in an Airtable base.

        The Meta API requires at least one field. When fields is None or empty,
        a default primary field of type singleLineText named "Name" is used.
        """
        endpoint = f"/meta/bases/{base_id}/tables"
        if not fields:
            fields = [{"name": "Name", "type": "singleLineText"}]
        data: Dict[str, Any] = {
            "name": name,
            "fields": fields,
        }
        if description is not None:
            data["description"] = description
        return self._make_request("POST", endpoint, data=data)

    def update_table(
        self,
        base_id: str,
        table_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update a table's name or description."""
        endpoint = f"/meta/bases/{base_id}/tables/{table_id}"
        data: Dict[str, Any] = {}
        if name is not None:
            data["name"] = name
        if description is not None:
            data["description"] = description
        if not data:
            raise ClientError("At least one of --name or --description must be specified")
        return self._make_request("PATCH", endpoint, data=data)


# Module-level client instance - singleton pattern
_client: Optional[AirtableClient] = None


def get_client() -> AirtableClient:
    """Get or create the global Airtable client instance."""
    global _client
    if _client is None:
        _client = AirtableClient()
    return _client
