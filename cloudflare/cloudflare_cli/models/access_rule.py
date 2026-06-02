"""Access Rule models for Cloudflare CLI.

IP Access rules allow you to allowlist, block, and challenge traffic
based on the visitor's IP address, ASN, or country.
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import Field

from .base import CLIModel


class AccessRuleMode(str, Enum):
    """Action to apply to matched requests."""

    WHITELIST = "whitelist"
    BLOCK = "block"
    CHALLENGE = "challenge"
    JS_CHALLENGE = "js_challenge"
    MANAGED_CHALLENGE = "managed_challenge"


class ConfigurationTarget(str, Enum):
    """Target type for access rule configuration."""

    IP = "ip"
    IP_RANGE = "ip_range"
    ASN = "asn"
    COUNTRY = "country"
    IPV6 = "ipv6"


class AccessRuleConfiguration(CLIModel):
    """Configuration for an access rule.

    Defines what traffic to match.
    """

    target: ConfigurationTarget
    value: str


class AccessRuleScope(CLIModel):
    """Scope of an access rule.

    Defines where the rule applies.
    """

    id: str
    email: Optional[str] = None
    type: str  # user, zone, organization


class AccessRule(CLIModel):
    """IP Access rule model.

    Represents a Cloudflare IP Access rule that allows, blocks,
    or challenges traffic based on IP, ASN, or country.
    """

    # Read-only field: server-assigned
    id: str = Field(frozen=True)

    # Allowed modes for this rule
    allowed_modes: list[AccessRuleMode] = []

    # Configuration (what to match)
    configuration: AccessRuleConfiguration

    # Mode (action to take)
    mode: AccessRuleMode

    # Timestamps (read-only: server-assigned)
    created_on: Optional[datetime] = Field(default=None, frozen=True)
    modified_on: Optional[datetime] = Field(default=None, frozen=True)

    # Optional notes/description
    notes: Optional[str] = None

    # Scope of the rule
    scope: Optional[AccessRuleScope] = None


def create_access_rule(data: dict) -> AccessRule:
    """Create an AccessRule model from API response data.

    Args:
        data: Raw dict from API response

    Returns:
        AccessRule model instance

    Raises:
        ValidationError: If required fields are missing
    """
    return AccessRule(**data)
