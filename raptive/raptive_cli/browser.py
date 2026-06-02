"""Browser automation service for Raptive CLI.

Subclasses BrowserAutomation from cli_tools_shared for CDP-based login,
session persistence, and headless automation.
"""
from typing import Any

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError


class RaptiveBrowser(BrowserAutomation):
    """Raptive-specific browser automation."""

    LOGIN_URL = "https://dashboard.raptive.com"
    AUTH_CHECK_URL = "https://dashboard.raptive.com"
    AUTH_URL_PATTERN = r"/login|accounts\.google\.com"
    AUTH_SUCCESS_URL = r"/sites/"
    AUTH_STORAGE_KEY = "token"
    SESSION_NAME = "raptive"


def _raptive_fetch_json(self, url: str) -> Any:
    """Fetch JSON using page's session cookies."""
    page = self.get_page()
    return page.evaluate(
        """async (url) => {
            const r = await fetch(url, {credentials: 'include'});
            return r.ok ? r.json() : {_error: true, status: r.status};
        }""",
        url,
    )


# Backward compatibility aliases
RaptiveBrowser.fetch_json = _raptive_fetch_json
BrowserService = RaptiveBrowser
BrowserError = BrowserAutomationError
