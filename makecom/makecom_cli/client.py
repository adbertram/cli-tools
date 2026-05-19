"""Make.com client using shared browser session tooling."""

from typing import Optional

from cli_tools_shared.http_session import BrowserAuthState, BrowserAuthenticatedHttpClient

from .config import get_config
from .models.program import ProgramInfo


class MakecomClient:
    """Minimal client for verified affiliate-program metadata."""

    PRODUCT_NAME = "Make.com"
    RECORD_ID = "recnmtpz60wEicTlx"
    AIRTABLE_STATUS = "Researched"
    VERIFICATION_BASIS = "Airtable research record plus official affiliate page"
    NOTES = (
        "Created as a browser CLI because the task explicitly requested the "
        "non-shadowing makecom command for the Make.com affiliate program."
    )

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
                allowed_domains=["www.make.com", "make.com"],
                timeout=10,
            )
        return self._http_client

    def close(self):
        """Close the browser session if it was opened."""
        if self._browser_instance is not None:
            self.browser.close()
            self._browser_instance = None

    def get_program_info(self) -> ProgramInfo:
        """Return verified metadata for the official Make.com affiliate program."""
        return ProgramInfo(
            cli_name="makecom",
            product_name=self.PRODUCT_NAME,
            record_id=self.RECORD_ID,
            airtable_status=self.AIRTABLE_STATUS,
            program_url=self.config.base_url,
            cli_type="browser",
            auth_type="browser_session",
            docs_url="https://help.make.com/affiliate-program",
            verification_basis=self.VERIFICATION_BASIS,
            notes=self.NOTES,
        )


_client: Optional[MakecomClient] = None


def get_client() -> MakecomClient:
    """Get or create the global Makecom client instance."""
    global _client
    if _client is None:
        _client = MakecomClient()
    return _client
