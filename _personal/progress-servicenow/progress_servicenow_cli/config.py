"""Configuration management for Progress ServiceNow CLI."""

from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for Progress ServiceNow browser-session auth.

    The Progress Entra account credentials are NOT stored here. They live in
    the managed LastPass entry named by
    ``ProgressServiceNowBrowser.LASTPASS_ENTRY`` and are read at sign-in time,
    so there is exactly one source for them. A second copy in the profile
    ``.env`` would silently go stale — which is what happened before: the saved
    ``PASSWORD`` held the account name, so ``auth status`` reported saved
    credentials that could not sign in.
    """

    DIST_NAME = "progress-servicenow-cli"
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://progress1.service-now.com/esc"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def get_browser(self):
        """Return a cached ServiceNow browser automation instance."""
        if not hasattr(self, "_browser_instance") or self._browser_instance is None:
            from .browser import ProgressServiceNowBrowser

            self._browser_instance = ProgressServiceNowBrowser(self)
        return self._browser_instance

    def test_connection(self) -> dict:
        """Verify the saved ServiceNow browser session."""
        browser = self.get_browser()
        try:
            result = browser.is_authenticated()
            if result:
                return {
                    "api_test": "passed",
                    "browser_session": "authenticated",
                }
            return {
                "api_test": "failed: not authenticated",
                "browser_session": "not authenticated",
            }
        except Exception as exc:
            return {"api_test": f"failed: {exc}"}
        finally:
            try:
                browser.close()
            except Exception:
                pass


_config: Optional[Config] = None


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create the config instance."""
    global _config
    if _config is None or profile is not None:
        _config = Config(profile=profile)
    return _config
