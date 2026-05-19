"""Pydantic models for 10Web websites and subdomain checks."""

from typing import Optional

from pydantic import Field

from .base import CLIModel


class Website(CLIModel):
    """Website summary returned by `websites list`."""

    id: int = Field(frozen=True)
    name: str
    site_url: Optional[str] = None
    admin_url: Optional[str] = None
    site_title: Optional[str] = None
    website_hash: Optional[str] = None
    type: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class WebsiteDetail(CLIModel):
    """Website instance details returned by `websites get`."""

    website_id: int = Field(frozen=True)
    status: str
    ip: Optional[str] = None
    location: Optional[str] = None
    region: Optional[str] = None


class SubdomainCheckResult(CLIModel):
    """Subdomain availability result."""

    status: str
    message: str


def create_website(data: dict) -> Website:
    """Create a website summary model from an API payload."""
    return Website(**data)


def create_website_detail(data: dict) -> WebsiteDetail:
    """Create a website detail model from an API payload."""
    return WebsiteDetail(**data)


def create_subdomain_check_result(data: dict) -> SubdomainCheckResult:
    """Create a subdomain check result model from an API payload."""
    return SubdomainCheckResult(**data)
