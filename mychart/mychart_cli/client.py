"""Epic MyChart SMART on FHIR API client."""

from __future__ import annotations

import random
import time
from typing import Dict, Iterable, List, Optional

import requests
from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import parse_filter_string, validate_filters
from cli_tools_shared.token_manager import TokenManager

from .config import get_config

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
DEFAULT_SUMMARY_RESOURCES = [
    "AllergyIntolerance",
    "Condition",
    "MedicationRequest",
    "Observation",
    "Immunization",
    "Appointment",
    "DiagnosticReport",
    "DocumentReference",
]
SANDBOX_TEST_PATIENTS = [
    {
        "id": "erXuFYUfucBZaryVksYEcMg3",
        "name": "Camila Lopez",
        "mychart_username": "fhircamila",
        "available_resources": [
            "DiagnosticReport",
            "Goal",
            "Medication",
            "MedicationRequest",
            "Observation",
            "Patient",
            "Procedure",
        ],
        "source": "epic_sandbox_catalog",
    },
    {
        "id": "eq081-VQEgP8drUUqCWzHfw3",
        "name": "Derrick Lin",
        "mychart_username": "fhirderrick",
        "available_resources": [
            "CarePlan",
            "Condition",
            "Goal",
            "Medication",
            "MedicationRequest",
            "Observation",
            "Patient",
        ],
        "source": "epic_sandbox_catalog",
    },
    {
        "id": "eAB3mDIBBcyUKviyzrxsnAw3",
        "name": "Desiree Powell",
        "mychart_username": "fhirdesiree",
        "available_resources": ["Immunization", "Observation", "Patient"],
        "source": "epic_sandbox_catalog",
    },
]
FHIR_PREFIX_OPERATORS = {
    "eq": "",
    "ne": "ne",
    "gt": "gt",
    "gte": "ge",
    "lt": "lt",
    "lte": "le",
}

activity = get_activity_logger("mychart")


def _append_param(params: dict, key: str, value: str) -> None:
    existing = params.get(key)
    if existing is None:
        params[key] = value
    elif isinstance(existing, list):
        existing.append(value)
    else:
        params[key] = [existing, value]


def filters_to_search_params(filters: Optional[List[str]]) -> dict:
    """Translate standard CLI filters into FHIR search parameters."""
    if not filters:
        return {}
    validate_filters(filters)
    params: dict = {}
    for filter_string in filters:
        for field, operator, value in parse_filter_string(filter_string):
            if operator in FHIR_PREFIX_OPERATORS:
                _append_param(params, field, f"{FHIR_PREFIX_OPERATORS[operator]}{value}")
                continue
            if operator == "in":
                _append_param(params, field, ",".join(str(value).split("|")))
                continue
            raise ClientError(
                "FHIR server-side filtering supports eq, ne, gt, gte, lt, lte, and in. "
                f"Unsupported operator for '{field}': {operator}"
            )
    return params


def _bundle_resources(payload: dict) -> list[dict]:
    if payload.get("resourceType") != "Bundle":
        raise ClientError(f"Expected FHIR Bundle, got {payload.get('resourceType', 'unknown')}")
    return [
        entry["resource"]
        for entry in payload.get("entry", [])
        if isinstance(entry, dict) and isinstance(entry.get("resource"), dict)
    ]


def _oauth_extensions(metadata: dict) -> dict:
    security = (metadata.get("rest") or [{}])[0].get("security") or {}
    for extension in security.get("extension", []):
        if extension.get("url") != "http://fhir-registry.smarthealthit.org/StructureDefinition/oauth-uris":
            continue
        return {
            item.get("url"): item.get("valueUri")
            for item in extension.get("extension", [])
            if item.get("url") and item.get("valueUri")
        }
    return {}


def _resource_rows(metadata: dict) -> list[dict]:
    resources = (metadata.get("rest") or [{}])[0].get("resource") or []
    rows = []
    for resource in resources:
        search_params = [
            search_param.get("name")
            for search_param in resource.get("searchParam", [])
            if search_param.get("name")
        ]
        rows.append(
            {
                "type": resource.get("type", ""),
                "profile": resource.get("profile", ""),
                "interaction": [
                    item.get("code")
                    for item in resource.get("interaction", [])
                    if item.get("code")
                ],
                "search_params": search_params,
            }
        )
    return sorted(rows, key=lambda row: row["type"])


class MychartClient:
    """Client for Epic MyChart SMART on FHIR endpoints."""

    def __init__(
        self,
        config=None,
        *,
        require_auth: bool = True,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = config or get_config()
        self.require_auth = require_auth
        if require_auth and not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'mychart auth login' to authenticate."
            )
        self.base_url = self.config.base_url.rstrip("/")
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.tokens = TokenManager(self.config, on_refresh=self._update_headers)
        self._update_headers()

    def _update_headers(self):
        self.headers = {
            "Accept": "application/fhir+json",
            "Content-Type": "application/fhir+json",
        }
        if self.config.client_id:
            self.headers["Epic-Client-ID"] = self.config.client_id
        if self.config.access_token:
            self.headers["Authorization"] = f"Bearer {self.config.access_token}"

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        delay = self.base_delay * (2**attempt)
        jitter_range = delay * self.jitter
        return min(delay + random.uniform(-jitter_range, jitter_range), self.max_delay)

    def _is_retryable(self, response: Optional[requests.Response], exception: Optional[Exception]) -> bool:
        if exception is not None:
            return isinstance(
                exception,
                (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError,
                ),
            )
        return bool(response is not None and response.status_code in RETRYABLE_STATUS_CODES)

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def _extract_error_detail(self, response: requests.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return response.text[:500]
        if isinstance(body, dict) and body.get("resourceType") == "OperationOutcome":
            issues = body.get("issue") or []
            details = [
                issue.get("diagnostics")
                or (issue.get("details") or {}).get("text")
                or issue.get("code")
                for issue in issues
                if isinstance(issue, dict)
            ]
            return "; ".join(detail for detail in details if detail) or str(body)[:500]
        if isinstance(body, dict) and "message" in body:
            return str(body["message"])
        return str(body)[:500]

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
        auth_required: Optional[bool] = None,
    ) -> Dict:
        if auth_required is None:
            auth_required = self.require_auth
        if auth_required:
            self.tokens.ensure_valid()
            self._update_headers()

        url = endpoint if endpoint.startswith("http") else f"{self.base_url}/{endpoint.lstrip('/')}"
        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                response = requests.request(
                    method,
                    url,
                    headers=self.headers,
                    json=data,
                    params=params,
                    timeout=30,
                )
                last_response = response
                activity.info("%s %s -> %s", method, endpoint, response.status_code)
                if retry and self._is_retryable(response, None) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt, self._get_retry_after(response)))
                    continue
                break
            except requests.exceptions.RequestException as exc:
                last_exception = exc
                activity.warning("%s %s failed: %s", method, endpoint, exc)
                if retry and self._is_retryable(None, exc) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt))
                    continue
                break

        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed after {attempt + 1} attempts: {last_exception}")
        if last_response is None:
            raise ClientError("Request failed: no response received")
        if not last_response.ok:
            raise ClientError(f"HTTP {last_response.status_code}: {self._extract_error_detail(last_response)}")
        if last_response.status_code == 204:
            return {}
        return last_response.json()

    @cached
    def get_metadata(self) -> dict:
        """Return the FHIR CapabilityStatement."""
        return self._make_request("GET", "metadata", auth_required=False)

    @cached
    def get_oauth_endpoints(self) -> dict:
        """Return SMART OAuth endpoint URIs advertised by the server."""
        return _oauth_extensions(self.get_metadata())

    @cached
    def list_resource_types(self, limit: int = 100) -> list[dict]:
        """List FHIR resource types advertised by the server."""
        return _resource_rows(self.get_metadata())[:limit]

    @cached
    def get_resource_type(self, resource_type: str) -> dict:
        """Return CapabilityStatement details for one FHIR resource type."""
        for row in _resource_rows(self.get_metadata()):
            if row["type"].lower() == resource_type.lower():
                return row
        raise ClientError(f"FHIR resource type not advertised by this server: {resource_type}")

    @cached
    def list_resource(
        self,
        resource_type: str,
        *,
        patient_id: Optional[str] = None,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[dict]:
        """List a FHIR resource collection with server-side search parameters."""
        params = {"_count": limit}
        scoped_patient_id = patient_id or self.config.patient_id
        if scoped_patient_id and resource_type.lower() != "patient":
            params["patient"] = scoped_patient_id
        params.update(filters_to_search_params(filters))
        payload = self._make_request("GET", resource_type, params=params)
        return _bundle_resources(payload)[:limit]

    @cached
    def get_resource(self, resource_type: str, resource_id: str) -> dict:
        """Get one FHIR resource by type and ID."""
        return self._make_request("GET", f"{resource_type}/{resource_id}")

    @cached
    def get_patient(self, patient_id: Optional[str] = None) -> dict:
        """Get the current or requested patient resource."""
        selected_patient_id = patient_id or self.config.patient_id
        if not selected_patient_id:
            raise ClientError("No patient ID is saved. Run 'mychart auth login' or pass --patient-id.")
        return self.get_resource("Patient", selected_patient_id)

    def list_sandbox_test_patients(self, limit: int = 100) -> list[dict]:
        """List public Epic sandbox test patients without exposing passwords."""
        return SANDBOX_TEST_PATIENTS[:limit]

    def get_sandbox_test_patient(self, patient_id: str) -> dict:
        """Get one public Epic sandbox test patient catalog row."""
        for patient in SANDBOX_TEST_PATIENTS:
            if patient["id"] == patient_id:
                return patient
        raise ClientError(f"Unknown Epic sandbox test patient ID: {patient_id}")

    @cached
    def get_summary(
        self,
        *,
        patient_id: Optional[str] = None,
        resource_types: Optional[Iterable[str]] = None,
        limit_per_resource: int = 10,
    ) -> dict:
        """Return a grouped read-only clinical summary for the patient context."""
        selected_patient_id = patient_id or self.config.patient_id
        if not selected_patient_id:
            raise ClientError("No patient ID is saved. Run 'mychart auth login' or pass --patient-id.")
        selected_resource_types = list(resource_types or DEFAULT_SUMMARY_RESOURCES)
        resources = {}
        errors = {}
        for resource_type in selected_resource_types:
            try:
                resources[resource_type] = self.list_resource(
                    resource_type,
                    patient_id=selected_patient_id,
                    limit=limit_per_resource,
                )
            except ClientError as exc:
                errors[resource_type] = str(exc)
        result = {
            "patient_id": selected_patient_id,
            "resources": resources,
        }
        if errors:
            result["errors"] = errors
        return result


_clients: dict[tuple[bool], MychartClient] = {}


def get_client(require_auth: bool = True) -> MychartClient:
    """Get or create a MyChart client."""
    key = (require_auth,)
    if key not in _clients:
        _clients[key] = MychartClient(require_auth=require_auth)
    return _clients[key]
