"""Advertiser, relationship, and apply-result models for CJ CLI.

Model layout mirrors the data flowing back from the CJ Advertiser
Lookup REST API (``advertiser-lookup.api.cj.com/v2/advertiser-lookup``)
plus the synthetic result types produced by the browser-driven apply
flow.

Fields use ``Optional[...] = None`` for everything the API may omit.
We intentionally do NOT default missing strings to empty strings -- a
``None`` value preserves the fact that the API did not return the
field, which matters for downstream filtering and reporting.
"""

from enum import Enum
from typing import List, Optional

from pydantic import Field

from .base import CLIModel


# ==================== Enums ====================


class RelationshipStatus(str, Enum):
    """CJ publisher-to-advertiser relationship status.

    Values match the strings accepted by the
    ``advertiser-lookup`` query parameter ``advertiser-ids`` (when used
    as a status keyword) and the values reported in the response's
    ``<relationship-status>`` element.
    """

    JOINED = "joined"
    NOT_JOINED = "notjoined"
    PENDING = "pending"
    DECLINED = "declined"


class ApplyOutcome(str, Enum):
    """Result of a bulk/single apply request."""

    APPLIED = "applied"          # We submitted the application now.
    ALREADY_JOINED = "already_joined"  # Existing relationship: joined.
    ALREADY_PENDING = "already_pending"  # Existing relationship: pending.
    DECLINED = "declined"        # CJ previously declined this advertiser.
    FAILED = "failed"            # Submission attempted but failed.
    SKIPPED = "skipped"          # Pre-flight check skipped the apply.


# ==================== Models ====================


class Advertiser(CLIModel):
    """Compact advertiser/program record returned by list/search commands.

    Maps to a single ``<advertiser>`` element from the
    advertiser-lookup v2 response.

    ``network_rank`` and the two EPC fields are stored as raw strings: CJ
    returns sentinel values like ``"New"`` (for newly listed programs) and
    ``"N/A"`` (for advertisers without enough data to compute EPC) in the
    same elements that otherwise carry numbers. Coercing to int/float here
    crashes the entire response with ``ValueError`` — see bug 1 ("Google
    Cloud" search) and bug 3 (relationships list --status notjoined). The
    string form preserves CJ's actual semantics and downstream callers can
    parse on demand.
    """

    advertiser_id: str = Field(frozen=True)
    advertiser_name: str
    program_url: Optional[str] = None
    relationship_status: Optional[RelationshipStatus] = None
    network_rank: Optional[str] = None
    primary_category: Optional[str] = None
    seven_day_epc: Optional[str] = None
    three_month_epc: Optional[str] = None


class AdvertiserDetail(CLIModel):
    """Full advertiser record returned by ``cj advertisers get``."""

    advertiser_id: str = Field(frozen=True)
    advertiser_name: str
    account_status: Optional[str] = None
    program_url: Optional[str] = None
    relationship_status: Optional[RelationshipStatus] = None
    mobile_tracking_certified: Optional[bool] = None
    cookieless_tracking_enabled: Optional[bool] = None
    network_rank: Optional[str] = None
    primary_category: Optional[str] = None
    secondary_categories: List[str] = []
    performance_incentives: Optional[bool] = None
    seven_day_epc: Optional[str] = None
    three_month_epc: Optional[str] = None
    language: Optional[str] = None
    actions: List[dict] = []
    link_types: List[str] = []


class Relationship(CLIModel):
    """Publisher relationship row returned by ``cj relationships list``."""

    advertiser_id: str = Field(frozen=True)
    advertiser_name: str
    relationship_status: RelationshipStatus
    program_url: Optional[str] = None
    network_rank: Optional[str] = None


class ApplyResult(CLIModel):
    """Outcome of an apply request for a single advertiser."""

    advertiser_id: str = Field(frozen=True)
    outcome: ApplyOutcome
    detail: Optional[str] = None
    screenshot_path: Optional[str] = None


# ==================== Factory functions ====================


def _to_optional_int(value) -> Optional[int]:
    if value in (None, "", "null"):
        return None
    return int(value)


def _to_optional_float(value) -> Optional[float]:
    if value in (None, "", "null"):
        return None
    return float(value)


def _to_optional_text(value) -> Optional[str]:
    """Preserve CJ's raw response for fields that may carry sentinel strings.

    CJ surfaces ``"New"`` in ``<network-rank>`` and ``"N/A"`` in the EPC
    elements for advertisers that don't yet have a numeric value. Coercing
    these to int/float crashes the whole response. We keep the string and
    let downstream callers decide how to render or parse it.
    """
    if value in (None, "", "null"):
        return None
    return str(value).strip() or None


def _to_optional_bool(value) -> Optional[bool]:
    if value in (None, "", "null"):
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "y", "1"}


def _to_optional_status(value) -> Optional[RelationshipStatus]:
    if value in (None, "", "null"):
        return None
    normalized = str(value).strip().lower().replace(" ", "").replace("-", "")
    aliases = {
        "joined": RelationshipStatus.JOINED,
        "notjoined": RelationshipStatus.NOT_JOINED,
        "not_joined": RelationshipStatus.NOT_JOINED,
        "pending": RelationshipStatus.PENDING,
        "declined": RelationshipStatus.DECLINED,
    }
    if normalized not in aliases:
        raise ValueError(f"Unknown CJ relationship status: {value!r}")
    return aliases[normalized]


def create_advertiser(data: dict) -> Advertiser:
    """Build an :class:`Advertiser` from a parsed advertiser-lookup row."""
    return Advertiser(
        advertiser_id=str(data["advertiser_id"]),
        advertiser_name=str(data["advertiser_name"]),
        program_url=data.get("program_url"),
        relationship_status=_to_optional_status(data.get("relationship_status")),
        network_rank=_to_optional_text(data.get("network_rank")),
        primary_category=data.get("primary_category"),
        seven_day_epc=_to_optional_text(data.get("seven_day_epc")),
        three_month_epc=_to_optional_text(data.get("three_month_epc")),
    )


def create_advertiser_detail(data: dict) -> AdvertiserDetail:
    """Build an :class:`AdvertiserDetail` from a parsed advertiser-lookup row."""
    return AdvertiserDetail(
        advertiser_id=str(data["advertiser_id"]),
        advertiser_name=str(data["advertiser_name"]),
        account_status=data.get("account_status"),
        program_url=data.get("program_url"),
        relationship_status=_to_optional_status(data.get("relationship_status")),
        mobile_tracking_certified=_to_optional_bool(data.get("mobile_tracking_certified")),
        cookieless_tracking_enabled=_to_optional_bool(data.get("cookieless_tracking_enabled")),
        network_rank=_to_optional_text(data.get("network_rank")),
        primary_category=data.get("primary_category"),
        secondary_categories=list(data.get("secondary_categories") or []),
        performance_incentives=_to_optional_bool(data.get("performance_incentives")),
        seven_day_epc=_to_optional_text(data.get("seven_day_epc")),
        three_month_epc=_to_optional_text(data.get("three_month_epc")),
        language=data.get("language"),
        actions=list(data.get("actions") or []),
        link_types=list(data.get("link_types") or []),
    )


def create_relationship(data: dict) -> Relationship:
    """Build a :class:`Relationship` from a parsed advertiser-lookup row."""
    status = _to_optional_status(data.get("relationship_status"))
    if status is None:
        raise ValueError(
            f"Advertiser {data.get('advertiser_id')!r} has no "
            "relationship-status -- expected one of joined/notjoined/pending/declined."
        )
    return Relationship(
        advertiser_id=str(data["advertiser_id"]),
        advertiser_name=str(data["advertiser_name"]),
        relationship_status=status,
        program_url=data.get("program_url"),
        network_rank=_to_optional_text(data.get("network_rank")),
    )
