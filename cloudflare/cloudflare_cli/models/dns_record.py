"""DNS Record models for Cloudflare CLI.

DNS records define how traffic is routed to your domain.
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import Field

from .base import CLIModel


class DNSRecordType(str, Enum):
    """Supported DNS record types."""

    A = "A"
    AAAA = "AAAA"
    CAA = "CAA"
    CERT = "CERT"
    CNAME = "CNAME"
    DNSKEY = "DNSKEY"
    DS = "DS"
    HTTPS = "HTTPS"
    LOC = "LOC"
    MX = "MX"
    NAPTR = "NAPTR"
    NS = "NS"
    PTR = "PTR"
    SMIMEA = "SMIMEA"
    SRV = "SRV"
    SSHFP = "SSHFP"
    SVCB = "SVCB"
    TLSA = "TLSA"
    TXT = "TXT"
    URI = "URI"


class DNSRecord(CLIModel):
    """DNS record model.

    Represents a Cloudflare DNS record for a zone.
    """

    # Read-only field: server-assigned
    id: str = Field(frozen=True)

    # Record type
    type: DNSRecordType

    # Record name (e.g., example.com, subdomain.example.com)
    name: str

    # Record content (IP address, hostname, text, etc.)
    content: str

    # TTL in seconds (1 = auto)
    ttl: int = 1

    # Whether proxied through Cloudflare (orange cloud)
    proxied: bool = False

    # Priority (for MX, SRV records)
    priority: Optional[int] = None

    # Optional comment
    comment: Optional[str] = None

    # Tags
    tags: list[str] = []

    # Timestamps (read-only: server-assigned)
    created_on: Optional[datetime] = Field(default=None, frozen=True)
    modified_on: Optional[datetime] = Field(default=None, frozen=True)

    # Zone info
    zone_id: Optional[str] = None
    zone_name: Optional[str] = None


def create_dns_record(data: dict) -> DNSRecord:
    """Create a DNSRecord model from API response data.

    Args:
        data: Raw dict from API response

    Returns:
        DNSRecord model instance

    Raises:
        ValidationError: If required fields are missing
    """
    return DNSRecord(**data)
