"""Account models for Monarch CLI."""
from typing import Optional, List
from pydantic import Field
from .base import CLIModel


class Account(CLIModel):
    """Account model for list commands."""
    id: str = Field(frozen=True)
    name: str
    type: Optional[str] = None
    subtype: Optional[str] = None
    balance: float = 0.0
    institution: Optional[str] = None
    is_hidden: bool = False
    is_asset: bool = True
    last_updated: Optional[str] = None


class AccountDetail(CLIModel):
    """Detailed account model."""
    id: str = Field(frozen=True)
    name: str
    type: Optional[str] = None
    subtype: Optional[str] = None
    balance: float = 0.0
    available_balance: Optional[float] = None
    institution: Optional[str] = None
    institution_id: Optional[str] = None
    is_hidden: bool = False
    is_asset: bool = True
    last_updated: Optional[str] = Field(default=None, frozen=True)
    created_at: Optional[str] = Field(default=None, frozen=True)


class AccountHolding(CLIModel):
    """Security holding in a brokerage account."""
    id: str = Field(frozen=True)
    name: str
    ticker: Optional[str] = None
    quantity: float = 0.0
    price: float = 0.0
    value: float = 0.0
    cost_basis: Optional[float] = None


class BalanceHistory(CLIModel):
    """Balance history entry."""
    date: str
    balance: float
