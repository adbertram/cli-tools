"""Configuration management for Gemini CLI."""
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Gemini CLI configuration (API key auth)."""

    DIST_NAME = "gemini-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
    CUSTOM_REQUIRED_FIELDS = ["GEMINI_API_KEY"]
    CUSTOM_ALL_FIELDS = ["GEMINI_API_KEY", "GEMINI_BIGQUERY_BILLING_TABLE"]
    CUSTOM_LOGIN_PROMPTS = [("GEMINI_API_KEY", "Gemini API key", True)]
    CUSTOM_SENSITIVE_FIELDS = ["GEMINI_API_KEY"]

    LOGIN_INSTRUCTIONS = (
        "To get your Gemini API key:\n"
        "  1. Go to https://aistudio.google.com/apikey\n"
        "  2. Create a new API key (or copy an existing one)\n"
        "  3. Paste the key below"
    )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    # ---- Compatibility shims for existing client.py code ----

    @property
    def api_key(self) -> Optional[str]:
        return self._get("GEMINI_API_KEY")

    @property
    def bigquery_billing_table(self) -> Optional[str]:
        """Get BigQuery billing export table ID (e.g. project.dataset.table)."""
        return self._get("GEMINI_BIGQUERY_BILLING_TABLE")

    def save_bigquery_billing_table(self, table_id: str):
        """Save BigQuery billing table ID to .env file."""
        self._set("GEMINI_BIGQUERY_BILLING_TABLE", table_id)

    def test_connection(self) -> Optional[dict]:
        """Verify the API key by listing available models."""
        from .client import GeminiClient, ClientError
        try:
            client = GeminiClient(config=self)
            models = client.list_models(limit=1)
            return {
                "api_test": "passed",
                "models_available": len(models),
            }
        except ClientError as e:
            return {"api_test": f"failed: {e}"}


_configs: dict = {}


def get_config(profile=None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
