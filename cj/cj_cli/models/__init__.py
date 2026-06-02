"""CJ CLI models.

Advertiser, Relationship, and ApplyResult are the public surface.  The
legacy ``Item``/``ItemDetail`` placeholders that shipped with the
scaffold have been removed -- they were generic stand-ins and never
mapped to anything CJ-specific.
"""

from .advertiser import (
    Advertiser,
    AdvertiserDetail,
    ApplyOutcome,
    ApplyResult,
    Relationship,
    RelationshipStatus,
    create_advertiser,
    create_advertiser_detail,
    create_relationship,
)
from .base import CLIModel
from .link import Link, create_link

__all__ = [
    "Advertiser",
    "AdvertiserDetail",
    "ApplyOutcome",
    "ApplyResult",
    "CLIModel",
    "Link",
    "Relationship",
    "RelationshipStatus",
    "create_advertiser",
    "create_advertiser_detail",
    "create_link",
    "create_relationship",
]
