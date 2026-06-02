"""Program metadata models for Rewarx CLI."""

from typing import Optional

from .base import CLIModel


class ProgramInfo(CLIModel):
    """Verified metadata for the Rewarx affiliate program CLI."""

    cli_name: str
    product_name: str
    record_id: str
    airtable_status: str
    program_url: str
    cli_type: str
    auth_type: str
    docs_url: Optional[str] = None
    verification_basis: str
    notes: Optional[str] = None
