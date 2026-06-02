"""{{Name}} client using BrowserAutomation from cli_tools_shared."""

from typing import List, Optional

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .browser import {{Name}}Browser
from .config import get_config
from .parsers import normalize_item_detail, normalize_items


class {{Name}}Client:
    """Client that uses BrowserAutomation to drive {{Name}}."""

    def __init__(self):
        self.config = get_config()
        self._browser: Optional[{{Name}}Browser] = None

    def _get_browser(self) -> {{Name}}Browser:
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    @cached
    def search(self, query: str, limit: int = 100) -> List[dict]:
        """Search for items on {{Name}}."""
        raise NotImplementedError("Implement search for {{Name}}")

    @cached
    def get_item(self, item_id: str) -> dict:
        """Get details for a specific item."""
        raise NotImplementedError("Implement get_item for {{Name}}")

    @cached
    def list_items(self, limit: int = 100) -> List[dict]:
        """List items from {{Name}}."""
        raise NotImplementedError("Implement list_items for {{Name}}")


_client: Optional[{{Name}}Client] = None


def get_client() -> {{Name}}Client:
    """Get or create the global {{Name}} client instance."""
    global _client
    if _client is None:
        _client = {{Name}}Client()
    return _client
