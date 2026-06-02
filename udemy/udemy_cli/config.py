"""Configuration management for Udemy CLI."""
from pathlib import Path
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.activity_log import get_activity_logger
from .browser import UDEMY_BROWSER_SESSION, UdemyBrowser

activity = get_activity_logger("udemy")


class Config(BaseConfig):

    DIST_NAME = "udemy-cli"
    CREDENTIAL_TYPES = [CredentialType.PERSONAL_ACCESS_TOKEN, CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://www.udemy.com/instructor-api/v1"
    ADDITIONAL_AUTH_FIELDS = ("USERNAME", "PASSWORD")
    ADDITIONAL_SENSITIVE_AUTH_FIELDS = ("USERNAME", "PASSWORD")
    LOGIN_INSTRUCTIONS = (
        "Create a Udemy Instructor API client before logging in:\n"
        "1. Open https://www.udemy.com/user/edit-api-clients/\n"
        "2. Create or open an API client and copy its bearer token.\n"
        "3. Paste the bearer token at the prompt below."
    )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def has_api_credentials(self) -> bool:
        """Check whether the Udemy bearer token is configured."""
        return bool(self.personal_access_token)

    @property
    def browser_session(self) -> str:
        """Return the playwright-cli session used for browser-backed commands."""
        session = self._get("BROWSER_SESSION")
        if session is None:
            return UDEMY_BROWSER_SESSION
        return session

    def get_browser(self):
        """Return the Udemy browser authentication helper."""
        return UdemyBrowser(self)

    def test_connection(self):
        """Verify the configured token can read instructor courses."""
        from .client import UdemyClient
        client = UdemyClient(config=self)
        client.list_courses(limit=1)
        return {"api_test": "passed", "method": "instructor_api"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        activity.info("Loading config profile=%s", profile or "default")
        _configs[key] = Config(profile=profile)
    return _configs[key]
