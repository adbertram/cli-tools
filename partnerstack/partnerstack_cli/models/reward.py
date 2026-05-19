"""Reward models for PartnerStack CLI."""
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import ConfigDict, Field

from .base import CLIModel


class PaymentStatus(str, Enum):
    """Payment status values documented by PartnerStack."""

    AVAILABLE = "available"
    IN_TRANSIT = "in_transit"
    WITHDRAWN = "withdrawn"
    PAID_EXTERNALLY = "paid_externally"
    EXPIRED = "expired"
    FAILED = "failed"
    MERGING = "merging"


class PartnerStackObject(CLIModel):
    """Nested PartnerStack object that preserves API-provided fields."""

    model_config = ConfigDict(extra="allow")


class Company(PartnerStackObject):
    id: int
    key: str
    name: str


class Customer(PartnerStackObject):
    created_at: Optional[int] = None
    email: Optional[str] = None
    key: Optional[str] = None
    name: Optional[str] = None
    shared_id: Optional[str] = None
    sub_ids: List[str]
    updated_at: Optional[int] = None


class RewardSource(PartnerStackObject):
    key: Optional[str] = None
    type: Optional[str] = None


class RewardTransaction(PartnerStackObject):
    amount: Optional[int] = None
    amount_usd: Optional[int] = None
    archived: Optional[bool] = None
    category_key: Optional[str] = None
    created_at: Optional[int] = None
    currency: Optional[str] = None
    product_key: Optional[str] = None
    updated_at: Optional[int] = None


class Reward(CLIModel):
    """PartnerStack reward returned by the Partner API."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(validation_alias="key", frozen=True)
    name: str = Field(validation_alias="description")
    key: str = Field(frozen=True)
    amount: int
    company: Company
    created_at: int
    currency: str
    customer: Customer
    description: str
    partnership_key: str
    payment_status: PaymentStatus
    reward_status: str
    source: RewardSource
    transaction: RewardTransaction
    updated_at: int
    withdrawn: bool
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None
    creation_source: Optional[str] = None
    decline_reason: Optional[str] = None
    payment_date: Optional[int] = None
    payout_id: Optional[int] = None


def create_reward(data: Dict[str, Any]) -> Reward:
    """Create a Reward model from API response data."""
    return Reward(**data)
