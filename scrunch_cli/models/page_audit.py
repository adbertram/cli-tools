"""Page audit models for Scrunch CLI."""
from typing import Any, Dict, List, Optional

from .base import CLIModel


class PageAuditRecord(CLIModel):
    """Page audit record returned by the API."""

    id: Optional[int] = None
    url: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    results: Optional[List[dict]] = None
    metadata: Optional[dict] = None


class CreatePageAudit(CLIModel):
    """Model for creating a new page audit."""

    url: str


class PageTestListing(CLIModel):
    """Page test listing returned by the API."""

    id: Optional[int] = None
    page_audit_id: Optional[int] = None
    status: Optional[str] = None
    results: Optional[List[dict]] = None
    metadata: Optional[dict] = None


class PageTestResponse(CLIModel):
    """Page test response with detailed results."""

    id: Optional[int] = None
    page_audit_id: Optional[int] = None
    status: Optional[str] = None
    results: Optional[List[dict]] = None
    metadata: Optional[dict] = None


def create_page_audit(data: dict) -> PageAuditRecord:
    """Create a PageAuditRecord model from API response data."""
    return PageAuditRecord(**data)
