"""Quickstats models for ClickBank CLI."""
from decimal import Decimal
from typing import Optional

from pydantic import Field

from .base import CLIModel


class QuickstatsPoint(CLIModel):
    quickStatDate: Optional[str] = None
    sale: Optional[Decimal] = None
    refund: Optional[Decimal] = None
    chargeback: Optional[Decimal] = None


class QuickstatsAccount(CLIModel):
    nickName: Optional[str] = None
    quickStats: list[QuickstatsPoint] = Field(default_factory=list)
