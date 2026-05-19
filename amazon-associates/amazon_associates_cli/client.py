"""AmazonAssociates client using shared browser session tooling."""

from typing import Optional

from cli_tools_shared.http_session import BrowserAuthState, BrowserAuthenticatedHttpClient

from .config import get_config
from .models.program import ProgramInfo


class AmazonAssociatesClient:
    """Minimal client for verified program metadata."""

    PRODUCT_NAME = "Amazon Associates"
    RECORD_ID = "rec00EMRvXWcjSZGG"
    AIRTABLE_STATUS = "Researched"
    VERIFICATION_BASIS = "Official program page"
    NOTES = "Created as a browser CLI because no public API was verified from the official program URL during this batch."

    def __init__(self):
        self.config = get_config()
        self._browser_instance = None
        self._http_client: Optional[BrowserAuthenticatedHttpClient] = None

    @property
    def browser(self):
        """Return the BrowserAutomation subclass for future browser flows."""
        if self._browser_instance is None:
            self._browser_instance = self.config.get_browser()
        return self._browser_instance

    def _browser_http_client(self) -> BrowserAuthenticatedHttpClient:
        """Return shared browser-session HTTP support for compliance and future reads."""
        if self._http_client is None:
            self._http_client = BrowserAuthenticatedHttpClient(
                auth_state=BrowserAuthState.from_config(self.config),
                allowed_domains=["affiliate-program.amazon.com", "affiliate-program.amazon.com"],
                timeout=10,
            )
        return self._http_client

    def close(self):
        """Close the browser session if it was opened."""
        if self._browser_instance is not None:
            self._browser_instance.close()
            self._browser_instance = None

    def get_program_info(self) -> ProgramInfo:
        """Return verified metadata for the official program URL."""
        return ProgramInfo(
            cli_name="amazon-associates",
            product_name=self.PRODUCT_NAME,
            record_id=self.RECORD_ID,
            airtable_status=self.AIRTABLE_STATUS,
            program_url=self.config.base_url,
            cli_type="browser",
            auth_type="browser_session",
            docs_url=None,
            verification_basis=self.VERIFICATION_BASIS,
            notes=self.NOTES,
        )


_client: Optional[AmazonAssociatesClient] = None


def get_client() -> AmazonAssociatesClient:
    """Get or create the global AmazonAssociates client instance."""
    global _client
    if _client is None:
        _client = AmazonAssociatesClient()
    return _client
