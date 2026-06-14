"""Configuration management for MyChart CLI."""

from pathlib import Path

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError


class Config(BaseConfig):
    DIST_NAME = "mychart-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DEFAULT_BASE_URL = "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4"
    DEFAULT_FHIR_SCOPES = (
        "launch/patient openid fhirUser offline_access "
        "patient/Patient.read patient/AllergyIntolerance.read patient/Condition.read "
        "patient/MedicationRequest.read patient/Observation.read patient/Immunization.read "
        "patient/Appointment.read patient/DiagnosticReport.read patient/DocumentReference.read "
        "patient/Procedure.read patient/Encounter.read patient/CarePlan.read"
    )

    CUSTOM_REQUIRED_FIELDS = ["CLIENT_ID", "ACCESS_TOKEN"]
    CUSTOM_ALL_FIELDS = [
        "CLIENT_ID",
        "ACCESS_TOKEN",
        "REFRESH_TOKEN",
        "TOKEN_EXPIRES_AT",
        "REDIRECT_URI",
        "PATIENT_ID",
        "GRANTED_SCOPES",
    ]
    CUSTOM_LOGIN_PROMPTS = [
        ("CLIENT_ID", "Epic on FHIR client ID", False),
        ("REDIRECT_URI", "registered redirect URI", False),
    ]
    CUSTOM_EPHEMERAL_FIELDS = [
        "ACCESS_TOKEN",
        "REFRESH_TOKEN",
        "TOKEN_EXPIRES_AT",
        "PATIENT_ID",
        "GRANTED_SCOPES",
    ]
    CUSTOM_SENSITIVE_FIELDS = ["ACCESS_TOKEN", "REFRESH_TOKEN"]
    ROOT_CONFIG_FIELDS = ("FHIR_SCOPES",)

    OAUTH_AUTH_URL = "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/authorize"
    OAUTH_TOKEN_URL = "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token"
    OAUTH_REDIRECT_URI = "http://localhost:8765/callback"
    OAUTH_PKCE = True
    OAUTH_TOKEN_AUTH = "none"
    AUTH_SETUP_INSTRUCTIONS = (
        "Before logging in:\n"
        "  1. Register an Epic on FHIR patient-facing app at https://fhir.epic.com.\n"
        "  2. Use the non-production Client ID for the Epic sandbox.\n"
        "  3. Register a loopback redirect URI such as http://localhost:8765/callback."
    )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def storage_dir(self) -> Path:
        """Profile-aware storage directory for runtime state."""
        return self.get_profile_data_dir()

    @property
    def patient_id(self) -> str | None:
        return self._get("PATIENT_ID")

    @property
    def granted_scopes(self) -> str | None:
        return self._get("GRANTED_SCOPES")

    @property
    def fhir_scopes(self) -> list[str]:
        raw_scopes = self._get("FHIR_SCOPES") or self.DEFAULT_FHIR_SCOPES
        return [scope for scope in raw_scopes.split() if scope]

    @property
    def OAUTH_SCOPES(self) -> list[str]:
        return self.fhir_scopes

    @property
    def OAUTH_EXTRA_AUTH_PARAMS(self) -> dict:
        return {"aud": self.base_url}

    def has_credentials(self) -> bool:
        return bool(self.client_id and self.access_token)

    def get_missing_credentials(self) -> list[str]:
        missing = []
        if not self.client_id:
            missing.append("CLIENT_ID")
        if not self.access_token:
            missing.append("ACCESS_TOKEN")
        return missing

    def test_connection(self) -> dict:
        """Validate saved credentials with a live API call."""
        from .client import MychartClient

        try:
            patient = MychartClient(config=self).get_patient()
            return {
                "api_test": "passed",
                "patient_id": patient.get("id", self.patient_id or ""),
            }
        except ClientError as exc:
            return {"api_test": f"failed: {exc}"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
