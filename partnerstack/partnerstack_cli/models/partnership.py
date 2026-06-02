"""Partnership models for PartnerStack CLI."""
from typing import Any, Dict, Optional

from pydantic import ConfigDict, Field, model_validator

from .base import CLIModel


class Partnership(CLIModel):
    """A partnership returned by GET /api/v2/partnerships.

    Partnerships use ``key`` as the canonical identifier. We mirror it onto
    ``id`` and synthesize ``name`` from the embedded company name to keep CLI
    behavior uniform across resources (rewards, marketplace, partnerships).
    """

    model_config = ConfigDict(extra="allow")

    id: str = Field(validation_alias="key", frozen=True)
    key: str = Field(frozen=True)
    name: Optional[str] = None
    status: Optional[str] = None
    claimed: Optional[bool] = None
    is_archived: Optional[bool] = None
    has_sub_id: Optional[bool] = None
    company: Optional[Dict[str, Any]] = None
    group: Optional[Dict[str, Any]] = None
    link: Optional[Dict[str, Any]] = None
    offers: Optional[Any] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _populate_name(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("name") is None:
            company = data.get("company")
            if isinstance(company, dict) and company.get("name"):
                data = {**data, "name": company["name"]}
        return data


def create_partnership(data: Dict[str, Any]) -> Partnership:
    """Create a Partnership model from API response data."""
    return Partnership(**data)
