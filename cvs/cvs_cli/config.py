"""Configuration management for CVS CLI."""
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    DIST_NAME = "cvs-cli"
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://www.cvs.com"
    ADDITIONAL_AUTH_FIELDS = ("API_KEY", "FINGERPRINT", "USERNAME", "PASSWORD")
    ADDITIONAL_SENSITIVE_AUTH_FIELDS = ("API_KEY", "FINGERPRINT", "USERNAME", "PASSWORD")
    BROWSER_SESSION_REQUIRES_API_TEST = True

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def api_key(self):
        return self._get("API_KEY")

    @property
    def fingerprint(self):
        return self._get("FINGERPRINT")

    def test_connection(self):
        """Test if the browser session can authorize CVS mcapi requests."""
        try:
            from .client import EXPERIENCE_IDS, get_client
            client = get_client(config=self)
            client._make_request(
                EXPERIENCE_IDS["PATIENTS"],
                refresh_on_unauthorized=False,
            )
            return {"api_test": "passed"}
        except Exception as e:
            return {"api_test": f"failed: {str(e)}"}

    def get_browser(self):
        from .browser import CvsBrowser
        return CvsBrowser(self)

    @property
    def storage_dir(self):
        return self.get_profile_data_dir()


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
