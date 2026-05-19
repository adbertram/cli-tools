"""Finance models for Monarch CLI (budgets, cashflow, categories, tags, institutions)."""
from typing import Optional, List
from pydantic import Field
from .base import CLIModel


class Category(CLIModel):
    """Transaction category."""
    id: str = Field(frozen=True)
    name: str
    group: Optional[str] = None
    icon: Optional[str] = None


class CategoryGroup(CLIModel):
    """Category group."""
    id: str = Field(frozen=True)
    name: str
    categories: List[str] = []


class Tag(CLIModel):
    """Transaction tag."""
    id: str = Field(frozen=True)
    name: str
    color: Optional[str] = None


class Budget(CLIModel):
    """Budget model."""
    category_id: Optional[str] = None
    category_name: str
    budgeted: float = 0.0
    actual: float = 0.0
    remaining: float = 0.0


class CashflowSummary(CLIModel):
    """Cashflow summary."""
    income: float = 0.0
    expenses: float = 0.0
    savings: float = 0.0
    savings_rate: Optional[float] = None


class Institution(CLIModel):
    """Financial institution."""
    id: str = Field(frozen=True)
    name: str
    logo_url: Optional[str] = None
    status: Optional[str] = None
    last_update: Optional[str] = None
