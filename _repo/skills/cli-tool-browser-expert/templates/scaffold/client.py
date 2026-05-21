"""Client for {{ServiceName}} browser automation.

The client uses BrowserAutomation.get_page() for all page interactions.
It NEVER calls is_authenticated(), login(), or does session management —
those are handled by the auth commands from cli_tools_shared.
"""

import logging

from cli_tools_shared.exceptions import ClientError

from .config import get_config

logger = logging.getLogger("{{cli_name}}.client")


class Client:
    """{{ServiceName}} browser automation client."""

    def __init__(self, config=None):
        self._config = config or get_config()
        self._browser = self._config.get_browser()

    def _get_page(self, url):
        """Get an authenticated page via BrowserAutomation.

        This opens a headless browser (or reuses existing), navigates to the URL,
        and returns the BrowserHarnessService instance for further interaction.

        Usage:
            page = self._get_page("https://site.com/dashboard")
            page.evaluate("document.title")
            page.locator("table").text_content()
        """
        return self._browser.get_page(url)

    def close(self):
        """Close the browser session."""
        self._browser.close()

    # === Domain methods go here ===
    # Each method uses self._get_page(url) to navigate and extract data.
    #
    # Example:
    # def list_items(self):
    #     page = self._get_page("https://site.com/items")
    #     # Parse page content...
    #     return items


# Module-level singleton
_client = None


def get_client(config=None) -> Client:
    """Get or create client singleton."""
    global _client
    if _client is None or config is not None:
        _client = Client(config)
    return _client
