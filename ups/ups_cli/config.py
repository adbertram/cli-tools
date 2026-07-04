"""Configuration management for UPS CLI."""

from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError


class Config(BaseConfig):
    """Configuration for UPS Pickup API client-credentials auth."""

    DIST_NAME = "ups-cli"
    CREDENTIAL_TYPES = [CredentialType.OAUTH]
    DEFAULT_BASE_URL = "https://onlinetools.ups.com/api"
    DEFAULT_TOKEN_BASE_URL = "https://onlinetools.ups.com"
    OAUTH_TOKEN_EXPIRES = False
    OAUTH_STATIC_REQUIRED_FIELDS = ("CLIENT_ID", "CLIENT_SECRET")
    CUSTOM_ALL_FIELDS = [
        "UPS_API_VERSION",
        "UPS_TRANSACTION_SRC",
        "UPS_ACCOUNT_NUMBER",
        "UPS_ACCOUNT_COUNTRY",
        "UPS_DEFAULT_COMPANY",
        "UPS_DEFAULT_CONTACT",
        "UPS_DEFAULT_STREET",
        "UPS_DEFAULT_CITY",
        "UPS_DEFAULT_STATE",
        "UPS_DEFAULT_POSTAL",
        "UPS_DEFAULT_COUNTRY",
        "UPS_DEFAULT_PHONE",
        "UPS_DEFAULT_RESIDENTIAL",
        "UPS_DEFAULT_PICKUP_POINT",
        "UPS_DEFAULT_SERVICE_CODE",
        "UPS_DEFAULT_CONTAINER_CODE",
        "UPS_DEFAULT_DESTINATION_COUNTRY",
        "UPS_DEFAULT_PAYMENT_METHOD",
        "UPS_DEFAULT_WEIGHT",
        "UPS_DEFAULT_WEIGHT_UNIT",
    ]
    ROOT_CONFIG_FIELDS = (
        "TOKEN_BASE_URL",
        "UPS_API_VERSION",
        "UPS_TRANSACTION_SRC",
        "UPS_ACCOUNT_NUMBER",
        "UPS_ACCOUNT_COUNTRY",
        "UPS_DEFAULT_COMPANY",
        "UPS_DEFAULT_CONTACT",
        "UPS_DEFAULT_STREET",
        "UPS_DEFAULT_CITY",
        "UPS_DEFAULT_STATE",
        "UPS_DEFAULT_POSTAL",
        "UPS_DEFAULT_COUNTRY",
        "UPS_DEFAULT_PHONE",
        "UPS_DEFAULT_RESIDENTIAL",
        "UPS_DEFAULT_PICKUP_POINT",
        "UPS_DEFAULT_SERVICE_CODE",
        "UPS_DEFAULT_CONTAINER_CODE",
        "UPS_DEFAULT_DESTINATION_COUNTRY",
        "UPS_DEFAULT_PAYMENT_METHOD",
        "UPS_DEFAULT_WEIGHT",
        "UPS_DEFAULT_WEIGHT_UNIT",
    )
    AUTH_SETUP_INSTRUCTIONS = (
        "Create UPS OAuth credentials in the UPS Developer Portal and enable the Pickup API. "
        "Use the Client ID and Client Secret from the application."
    )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def has_credentials(self) -> bool:
        """UPS client-credentials auth only needs client ID and secret."""
        return bool(self.client_id and self.client_secret)

    def get_missing_credentials(self) -> list:
        """Get missing static credential fields."""
        missing = []
        if not self.client_id:
            missing.append("CLIENT_ID")
        if not self.client_secret:
            missing.append("CLIENT_SECRET")
        return missing

    @property
    def token_base_url(self) -> str:
        return self._get("TOKEN_BASE_URL") or self.DEFAULT_TOKEN_BASE_URL

    @property
    def api_version(self) -> str:
        return self._get("UPS_API_VERSION") or "v2409"

    @property
    def transaction_src(self) -> str:
        return self._get("UPS_TRANSACTION_SRC") or "cli-tools"

    @property
    def account_number(self) -> Optional[str]:
        return self._get("UPS_ACCOUNT_NUMBER")

    @property
    def account_country(self) -> str:
        return self._get("UPS_ACCOUNT_COUNTRY") or "US"

    @property
    def default_company(self) -> Optional[str]:
        return self._get("UPS_DEFAULT_COMPANY")

    @property
    def default_contact(self) -> Optional[str]:
        return self._get("UPS_DEFAULT_CONTACT")

    @property
    def default_street(self) -> Optional[str]:
        return self._get("UPS_DEFAULT_STREET")

    @property
    def default_city(self) -> Optional[str]:
        return self._get("UPS_DEFAULT_CITY")

    @property
    def default_state(self) -> Optional[str]:
        return self._get("UPS_DEFAULT_STATE")

    @property
    def default_postal(self) -> Optional[str]:
        return self._get("UPS_DEFAULT_POSTAL")

    @property
    def default_country(self) -> str:
        return self._get("UPS_DEFAULT_COUNTRY") or "US"

    @property
    def default_phone(self) -> Optional[str]:
        return self._get("UPS_DEFAULT_PHONE")

    @property
    def default_residential(self) -> bool:
        return (self._get("UPS_DEFAULT_RESIDENTIAL") or "").lower() in ("true", "1", "yes", "y")

    @property
    def default_pickup_point(self) -> str:
        return self._get("UPS_DEFAULT_PICKUP_POINT") or "FRONT"

    @property
    def default_service_code(self) -> str:
        return self._get("UPS_DEFAULT_SERVICE_CODE") or "003"

    @property
    def default_container_code(self) -> str:
        return self._get("UPS_DEFAULT_CONTAINER_CODE") or "01"

    @property
    def default_destination_country(self) -> str:
        return self._get("UPS_DEFAULT_DESTINATION_COUNTRY") or "US"

    @property
    def default_payment_method(self) -> str:
        return self._get("UPS_DEFAULT_PAYMENT_METHOD") or "01"

    @property
    def default_weight(self) -> float:
        value = self._get("UPS_DEFAULT_WEIGHT") or "1"
        try:
            return float(value)
        except ValueError as exc:
            raise ClientError(f"UPS_DEFAULT_WEIGHT must be numeric, got {value!r}") from exc

    @property
    def default_weight_unit(self) -> str:
        return self._get("UPS_DEFAULT_WEIGHT_UNIT") or "LBS"

    def test_connection(self) -> dict:
        """Validate saved UPS credentials by requesting an OAuth token."""
        from .client import UpsClient

        try:
            return UpsClient(config=self, require_auth=False).test_auth()
        except ClientError as exc:
            return {"api_test": f"failed: {exc}"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
