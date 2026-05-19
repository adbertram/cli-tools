"""Configuration management for Thunderbit CLI."""
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    DIST_NAME = "thunderbit-cli"
    CREDENTIAL_TYPES = [CredentialType.API_KEY]
    DEFAULT_BASE_URL = "https://openapi.thunderbit.com/openapi/v1"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def test_connection(self) -> dict:
        """Expose a deterministic auth test surface without inventing an endpoint."""
        if not self.api_key:
            return {"api_test": "failed: missing api_key"}
        return {
            "api_test": (
                "failed: Thunderbit's verified public docs expose only POST extraction endpoints; "
                "no non-destructive auth probe was validated in this batch."
            )
        }


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
