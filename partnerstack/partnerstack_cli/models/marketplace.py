"""Marketplace program models for PartnerStack CLI."""
from typing import Any, Dict, List, Optional

from pydantic import ConfigDict, Field, model_validator

from .base import CLIModel


class MarketplaceProgram(CLIModel):
    """A program returned by GET /api/v2/marketplace/programs.

    The PartnerStack API uses ``company_key`` as the path-param identifier on
    GET /api/v2/marketplace/programs/{company_key}, but the actual JSON the
    list endpoint returns surfaces that identifier under ``key`` (with a
    separate numeric ``id``). To keep CLI output uniform with the rewards
    model, we expose the ``key`` value as ``id`` on the model — that is the
    string a caller can pass to ``marketplace get``. The API's numeric ``id``
    is preserved on the model under ``numeric_id``.
    """

    model_config = ConfigDict(extra="allow")

    id: str = Field(frozen=True)
    key: str = Field(frozen=True)
    numeric_id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[List[str]] = None
    country: Optional[str] = None
    website: Optional[str] = None
    logo: Optional[str] = None
    has_sub_ids: Optional[bool] = None
    offers: Optional[List[Dict[str, Any]]] = None
    promotions: Optional[List[Dict[str, Any]]] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_identifiers(cls, data: Any) -> Any:
        """Force `id` to always equal the API's `key` (the company_key)."""
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        # Move the API's numeric id (if any) onto numeric_id so it isn't lost.
        if "numeric_id" not in normalized and isinstance(normalized.get("id"), int):
            normalized["numeric_id"] = normalized["id"]
        # Always force id := key.
        if "key" in normalized and normalized["key"]:
            normalized["id"] = normalized["key"]
        return normalized


def create_marketplace_program(data: Dict[str, Any]) -> MarketplaceProgram:
    """Create a MarketplaceProgram from API response data."""
    return MarketplaceProgram(**data)
