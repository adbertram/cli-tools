"""Cloudflare CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.
"""
from .base import CLIModel
from .zone import (
    Zone,
    ZoneDetail,
    ZoneStatus,
    create_zone,
    create_zone_detail,
)
from .purge_result import (
    PurgeResult,
    create_purge_result,
)
from .dns_record import (
    DNSRecord,
    DNSRecordType,
    create_dns_record,
)

__all__ = [
    # Base
    "CLIModel",
    # Zone models
    "Zone",
    "ZoneDetail",
    "ZoneStatus",
    "create_zone",
    "create_zone_detail",
    # Purge models
    "PurgeResult",
    "create_purge_result",
    # DNS models
    "DNSRecord",
    "DNSRecordType",
    "create_dns_record",
]
