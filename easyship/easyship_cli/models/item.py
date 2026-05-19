"""Easyship Public API models used by this CLI."""
from typing import Any, Optional

from pydantic import ConfigDict, Field

from .base import CLIModel


class Courier(CLIModel):
    """Courier summary returned by `GET /couriers`."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str = Field(frozen=True)
    umbrella_name: Optional[str] = None
    country_alpha2: Optional[str] = None
    auth_state: Optional[str] = None
    state: Optional[str] = None
    customer_reference_id: Optional[str] = None


class CourierDetail(Courier):
    """Courier detail returned by `GET /couriers/{courier_id}`."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class Account(CLIModel):
    """Account payload returned by `GET /account`."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: Optional[str] = Field(default=None, frozen=True)
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company_name: Optional[str] = None
    country_alpha2: Optional[str] = None
    raw: Optional[dict[str, Any]] = None


def create_courier(data: dict) -> Courier:
    """Create a Courier model from API response data."""
    normalized = dict(data)
    if "id" not in normalized:
        normalized["id"] = (
            normalized.get("easyship_courier_id")
            or normalized.get("courier_id")
            or normalized.get("customer_reference_id")
            or "unknown"
        )
    return Courier(**normalized)


def create_courier_detail(data: dict) -> CourierDetail:
    """Create a CourierDetail model from API response data."""
    normalized = dict(data)
    if "id" not in normalized:
        normalized["id"] = (
            normalized.get("easyship_courier_id")
            or normalized.get("courier_id")
            or normalized.get("customer_reference_id")
            or "unknown"
        )
    return CourierDetail(**normalized)


def create_account(data: dict) -> Account:
    """Create an Account model from API response data."""
    normalized = dict(data)
    normalized.setdefault("raw", dict(data))
    return Account(**normalized)
