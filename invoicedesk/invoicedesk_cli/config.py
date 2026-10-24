"""Configuration management for Invoicedesk CLI."""

from cli_tools_shared.config import BaseConfig, config_for, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError


class Config(BaseConfig):
    DIST_NAME = "invoicedesk-cli"
    CREDENTIAL_TYPES = [CredentialType.API_KEY]
    DEFAULT_BASE_URL = "https://invoice-desk.adamtheautomator.workers.dev"
    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def default_terms(self):
        from .client import InvoicedeskClient
        settings = InvoicedeskClient(config=self)._make_request("GET", "/api/settings")
        if "payment_instructions" not in settings:
            raise ClientError("Settings lack payment_instructions")
        return settings["payment_instructions"]

    def test_connection(self) -> dict:
        """Validate saved credentials with a live API call."""
        from .client import InvoicedeskClient

        try:
            InvoicedeskClient(config=self)._make_request("GET", "/api/clients")
            return {"api_test": "passed"}
        except ClientError as exc:
            return {"api_test": f"failed: {exc}"}


_configs = {}


def get_config(profile=None):
    return config_for(Config, profile, _configs)
