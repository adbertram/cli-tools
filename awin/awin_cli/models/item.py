"""Awin entity models.

Models for Awin publisher API resources: publishers and programmes.
"""
from typing import List, Optional

from pydantic import Field

from .base import CLIModel


class Publisher(CLIModel):
    """An Awin publisher account the authenticated user has access to.

    Returned by GET /accounts (in the ``accounts`` array). Each entry
    carries the account id, name, type (publisher | advertiser), and the
    user's role on that account.
    """

    accountId: int = Field(frozen=True)
    accountName: Optional[str] = None
    accountType: Optional[str] = None
    userRole: Optional[str] = None


class Programme(CLIModel):
    """An advertiser programme on Awin.

    Returned by GET /publishers/{publisherId}/programmes. Awin's response
    contains a mix of scalars and structured objects -- ``validDomains``
    is an array of ``{"domain": "..."}`` objects, ``primaryRegion`` is an
    object, etc. We keep them as raw dicts/lists so the model never
    rejects valid Awin payloads.
    """

    id: int = Field(frozen=True)
    name: Optional[str] = None
    displayUrl: Optional[str] = None
    logoUrl: Optional[str] = None
    description: Optional[str] = None
    currencyCode: Optional[str] = None
    primaryRegion: Optional[dict] = None
    validDomains: Optional[List[dict]] = None
    primarySector: Optional[str] = None
    status: Optional[str] = None


def create_publisher(data: dict) -> Publisher:
    return Publisher(**data)


def create_programme(data: dict) -> Programme:
    return Programme(**data)
