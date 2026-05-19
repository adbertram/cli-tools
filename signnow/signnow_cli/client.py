"""signNow developer metadata client."""

from typing import Optional

from .config import get_config
from .models.program import ProgramInfo


class SignnowClient:
    """Minimal client for verified signNow developer metadata."""

    PRODUCT_NAME = "signNow"
    RECORD_ID = "rec1g9fOjxl62uRNI"
    AIRTABLE_STATUS = "Approved"
    DOCS_URL = "https://www.signnow.com/developers"
    VERIFICATION_BASIS = "Official developer documentation"
    NOTES = "Created as an API CLI because the official signNow developer documentation was provided for this batch."

    def __init__(self):
        self.config = get_config()

    def get_program_info(self) -> ProgramInfo:
        """Return verified metadata for the official developer docs URL."""
        return ProgramInfo(
            cli_name="signnow",
            product_name=self.PRODUCT_NAME,
            record_id=self.RECORD_ID,
            airtable_status=self.AIRTABLE_STATUS,
            program_url=self.config.base_url,
            cli_type="api",
            auth_type="oauth",
            docs_url=self.DOCS_URL,
            verification_basis=self.VERIFICATION_BASIS,
            notes=self.NOTES,
        )


_client: Optional[SignnowClient] = None


def get_client() -> SignnowClient:
    """Get or create the global client instance."""
    global _client
    if _client is None:
        _client = SignnowClient()
    return _client
