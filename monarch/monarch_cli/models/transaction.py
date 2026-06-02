"""Transaction models for Monarch CLI."""
from typing import Optional, List
from pydantic import Field
from .base import CLIModel


class Transaction(CLIModel):
    """Transaction model for list commands."""
    id: str = Field(frozen=True)
    date: str
    amount: float
    merchant: Optional[str] = None
    raw_name: Optional[str] = None
    category: Optional[str] = None
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    is_pending: bool = False
    notes: Optional[str] = None
    needs_review: bool = False
    reviewed_at: Optional[str] = None


class TransactionDetail(CLIModel):
    """Detailed transaction model."""
    id: str = Field(frozen=True)
    date: str
    amount: float
    merchant: Optional[str] = None
    original_merchant: Optional[str] = None
    category: Optional[str] = None
    category_id: Optional[str] = None
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    is_pending: bool = False
    notes: Optional[str] = None
    tags: List[str] = []
    created_at: Optional[str] = Field(default=None, frozen=True)
    updated_at: Optional[str] = Field(default=None, frozen=True)


class RecurringTransaction(CLIModel):
    """Recurring transaction model."""
    id: str = Field(frozen=True)
    merchant: str
    amount: float
    frequency: Optional[str] = None
    next_date: Optional[str] = None
    category: Optional[str] = None
    account_name: Optional[str] = None
