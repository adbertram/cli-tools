"""Configuration management for LinkedIn CLI."""

from datetime import UTC, datetime
from pathlib import Path

import requests

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType

DEFAULT_LINKEDIN_SCOPES = "w_member_social"
DEFAULT_LINKEDIN_VERSION = "202604"
TOKEN_INTROSPECTION_URL = "https://www.linkedin.com/oauth/v2/introspectToken"


def _epoch_seconds_to_iso(epoch_seconds: int) -> str:
    return datetime.fromtimestamp(epoch_seconds, tz=UTC).isoformat()


class Config(BaseConfig):
    """Configuration manager for LinkedIn API access."""

    DIST_NAME = "linkedin-cli"
    CREDENTIAL_TYPES = [CredentialType.OAUTH_AUTHORIZATION_CODE]
    CUSTOM_ALL_FIELDS = [
        "LINKEDIN_SCOPES",
        "LINKEDIN_VERSION",
        "LINKEDIN_PAGE_URN",
        "LINKEDIN_PERSON_URN",
    ]
    DEFAULT_BASE_URL = "https://api.linkedin.com/rest"

    OAUTH_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
    OAUTH_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
    OAUTH_TOKEN_AUTH = "body"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def storage_dir(self) -> Path:
        return self.get_profile_data_dir()

    @property
    def OAUTH_SCOPES(self) -> list[str]:
        raw = self._get("LINKEDIN_SCOPES") or DEFAULT_LINKEDIN_SCOPES
        return [scope for scope in raw.split() if scope]

    @property
    def linkedin_version(self) -> str:
        return self._get("LINKEDIN_VERSION") or DEFAULT_LINKEDIN_VERSION

    @property
    def linkedin_page_urn(self) -> str | None:
        return self._get("LINKEDIN_PAGE_URN")

    @property
    def linkedin_person_urn(self) -> str | None:
        return self._get("LINKEDIN_PERSON_URN")

    def has_api_credentials(self) -> bool:
        return all(self._get(field) for field in CredentialType.OAUTH_AUTHORIZATION_CODE.required_fields)

    def get_missing_api_credentials(self) -> list[str]:
        return [
            field
            for field in CredentialType.OAUTH_AUTHORIZATION_CODE.required_fields
            if not self._get(field)
        ]

    def test_connection(self) -> dict:
        """Validate the saved OAuth token with LinkedIn token introspection."""
        if not self.has_api_credentials():
            missing = ", ".join(self.get_missing_api_credentials())
            return {"api_test": f"failed: missing {missing}"}

        response = requests.post(
            TOKEN_INTROSPECTION_URL,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "token": self.access_token,
            },
            timeout=30,
        )
        if not response.ok:
            return {"api_test": f"failed: HTTP {response.status_code}: {response.text[:500]}"}

        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Expected token introspection response to be an object.")
        if payload.get("active") is not True:
            status = payload.get("status")
            if status:
                return {"api_test": f"failed: token is not active ({status})"}
            return {"api_test": "failed: token is not active"}

        result = {"api_test": "passed"}
        status = payload.get("status")
        if status:
            result["token_status"] = status
        auth_type = payload.get("auth_type")
        if auth_type:
            result["auth_type"] = auth_type
        scope = payload.get("scope")
        if scope:
            result["scopes"] = [item for item in str(scope).split(",") if item]
        expires_at = payload.get("expires_at")
        if expires_at is not None:
            if not isinstance(expires_at, int):
                raise ValueError("Expected 'expires_at' to be an integer.")
            result["expires_at"] = _epoch_seconds_to_iso(expires_at)
        return result


def get_config(profile=None):
    return Config(profile=profile)
