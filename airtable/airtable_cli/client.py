"""Airtable API client with automatic token management."""
import base64
import mimetypes
import os
import random
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

import requests

from .config import get_config
from cli_tools_shared import FilterMap
from cli_tools_shared.filters import FilterValidationError, validate_filters

from cli_tools_shared.exceptions import ClientError


# Airtable's update-field endpoint only changes a field's name and description.
# Any select-field "choices" payload (add/remove/rename/recolor/reorder, even a
# no-op resend of the current choices) is rejected with HTTP 422
# INVALID_REQUEST_UNKNOWN. Fail fast with an actionable message instead of
# forwarding the doomed request and surfacing Airtable's opaque validation error.
SELECT_CHOICES_UPDATE_MESSAGE = (
    "Airtable's Web API cannot modify a select field's choices "
    "(add, remove, rename, recolor, or reorder) through 'fields update'. "
    "The update-field endpoint only changes a field's name and description; "
    "any 'choices' payload is rejected by Airtable with HTTP 422 "
    "(even a no-op that resends the current choices).\n"
    "  * Add a choice: write the value to a record with typecast, e.g.\n"
    "      airtable records update <table> <record> 'Field Name=New Choice' --typecast\n"
    "    (Airtable auto-creates the option.)\n"
    "  * Remove, rename, recolor, or reorder choices: use the Airtable web UI; "
    "the public API exposes no endpoint for this."
)


class AirtableClient:
    """Client for interacting with Airtable API."""

    # Retry configuration
    REQUEST_TIMEOUT_SECONDS = 10.0
    MAX_RETRIES = 3
    BASE_DELAY = 1.0
    MAX_DELAY = 30.0
    JITTER = 0.1

    # Retryable HTTP status codes
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    # Attachment uploads use a separate content host, not the standard API host.
    CONTENT_BASE_URL = "https://content.airtable.com/v0"
    # Airtable's uploadAttachment endpoint limits the base64 payload to 5 MB.
    UPLOAD_MAX_BASE64_BYTES = 5 * 1024 * 1024
    # Longer timeout than read calls: an upload sends the full file body.
    UPLOAD_TIMEOUT_SECONDS = 60.0

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
                    timeout=self.REQUEST_TIMEOUT_SECONDS,
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
        # Expose the upstream Airtable offset whenever the last page reported one.
        # A present offset means Airtable has more records after what was returned,
        # so a caller resuming with --offset must always receive it. Gating this on
        # ``remaining > 0`` silently dropped the offset when the requested ``limit``
        # landed exactly on a page boundary (e.g. limit=100 with 200 total), which
        # made external page-by-page resumption lose every record past that point.
        if result.get("offset"):
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

    def upload_attachment(
        self,
        base_id: str,
        record_id: str,
        field_name: str,
        file_path: str,
        content_type: Optional[str] = None,
    ) -> Dict:
        """Upload a local file to a record's attachment field.

        Uses Airtable's content-upload endpoint:
        POST https://content.airtable.com/v0/{baseId}/{recordId}/{fieldIdOrName}/uploadAttachment

        The record must already exist. The base64-encoded payload is capped at
        5 MB by Airtable; larger files raise ClientError (use the URL-based
        attachment method via update_record for bigger files).

        Args:
            base_id: The base ID (e.g., appXXXXXXXXXXXXXX)
            record_id: The existing record ID to attach to
            field_name: Attachment field ID or name
            file_path: Path to the local file to upload
            content_type: MIME type override; auto-detected from the filename
                when not provided

        Returns:
            Response JSON from Airtable (record id, createdTime, fields)

        Raises:
            ClientError: If the file is missing, unreadable, exceeds the 5 MB
                base64 limit, has an undetectable content type, or the API
                request fails.
        """
        if not os.path.isfile(file_path):
            raise ClientError(f"Attachment file not found: {file_path}")

        try:
            with open(file_path, "rb") as handle:
                raw_bytes = handle.read()
        except OSError as exc:
            raise ClientError(f"Could not read attachment file {file_path}: {exc}")

        resolved_content_type = content_type or mimetypes.guess_type(file_path)[0]
        if not resolved_content_type:
            raise ClientError(
                f"Could not determine content type for {file_path}. "
                "Pass an explicit MIME type with --content-type."
            )

        encoded = base64.b64encode(raw_bytes).decode("ascii")
        if len(encoded) > self.UPLOAD_MAX_BASE64_BYTES:
            limit_mb = self.UPLOAD_MAX_BASE64_BYTES / (1024 * 1024)
            raise ClientError(
                f"Attachment too large for direct upload: base64 payload is "
                f"{len(encoded)} bytes, which exceeds Airtable's "
                f"{limit_mb:.0f} MB uploadAttachment limit. "
                "Host the file and attach it by URL with "
                "`records update <table> <record> 'Field=[{\"url\":\"...\"}]'` instead."
            )

        filename = os.path.basename(file_path)
        url = f"{self.CONTENT_BASE_URL}/{base_id}/{record_id}/{field_name}/uploadAttachment"
        payload = {
            "contentType": resolved_content_type,
            "filename": filename,
            "file": encoded,
        }

        try:
            response = requests.post(
                url,
                headers=self.headers,
                json=payload,
                timeout=self.UPLOAD_TIMEOUT_SECONDS,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise ClientError(f"Connection error: {exc}")

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

        return response.json()

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
        """Update a field's name or description.

        Airtable's metadata API also accepts ``options`` for field types whose
        config is editable (e.g. formula), but it cannot modify a select
        field's ``choices``. A ``choices`` payload is blocked before the request
        with a clear message; see ``SELECT_CHOICES_UPDATE_MESSAGE``.
        """
        endpoint = f"/meta/bases/{base_id}/tables/{table_id}/fields/{field_id}"
        data: Dict[str, Any] = {}
        if name is not None:
            data["name"] = name
        if description is not None:
            data["description"] = description
        if options is not None:
            if isinstance(options, dict) and "choices" in options:
                raise ClientError(SELECT_CHOICES_UPDATE_MESSAGE)
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

    def list_bases(self) -> List[Dict[str, Any]]:
        """List every base the active Personal Access Token can access.

        Hits GET /meta/bases and returns the combined bases array. The
        Metadata API paginates this endpoint with an ``offset`` token; this
        method follows the token until Airtable stops returning one so the
        full set of accessible bases is returned, not just the first page.

        Each base record has ``id``, ``name``, and ``permissionLevel``.
        """
        endpoint = "/meta/bases"
        all_bases: List[Dict[str, Any]] = []
        offset: Optional[str] = None

        while True:
            params = {"offset": offset} if offset else None
            result = self._make_request("GET", endpoint, params=params)
            all_bases.extend(result.get("bases", []))

            offset = result.get("offset")
            if not offset:
                break

        return all_bases

    def get_base(self, base_id: str) -> Dict[str, Any]:
        """Get one base by ID or name from the accessible bases list.

        Airtable's Metadata API exposes no single-base detail endpoint, so this
        resolves the base from the full GET /meta/bases listing, matching on
        either the base ID (appXXXXXXXXXXXXXX) or the base name.
        """
        for base in self.list_bases():
            if base.get("id") == base_id or base.get("name") == base_id:
                return base
        raise ClientError(f"Base not found for the active token: {base_id}")

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
