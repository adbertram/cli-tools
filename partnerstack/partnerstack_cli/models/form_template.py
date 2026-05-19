"""Form template models for PartnerStack CLI.

Wraps responses from GET /api/v2/form-templates. The PartnerStack reference
documents the endpoint as the source of application-form schemas — the
``fields``/``schema`` payload describes the dynamic ``meta`` object that
POST /api/v2/applications expects for a given ``group``.

The full response schema is not exhaustively documented, so this model accepts
extra fields. The canonical identifier returned by PartnerStack form-template
objects is ``key``; we mirror it onto ``id`` for parity with other resources
(marketplace, partnerships) so CLI output keeps the same shape across groups.
"""
from typing import Any, Dict, Optional

from pydantic import ConfigDict, Field, model_validator

from .base import CLIModel


class FormTemplate(CLIModel):
    """A form template returned by GET /api/v2/form-templates.

    The form-template payload defines the dynamic field set required by a
    given program/group for ``POST /api/v2/applications``. PartnerStack does
    not fully document the response shape; we surface the commonly-present
    identifiers and metadata and preserve everything else under extras.
    """

    model_config = ConfigDict(extra="allow")

    id: Optional[str] = Field(default=None, frozen=True)
    key: Optional[str] = Field(default=None, frozen=True)
    name: Optional[str] = None
    group: Optional[str] = None
    target_type: Optional[str] = None
    mold_keys: Optional[Any] = None
    fields: Optional[Any] = None
    schema_: Optional[Any] = Field(default=None, alias="schema")
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _mirror_key_onto_id(cls, data: Any) -> Any:
        """Mirror the API's ``key`` value onto ``id`` for CLI parity."""
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if normalized.get("id") is None and normalized.get("key"):
            normalized["id"] = normalized["key"]
        return normalized


def create_form_template(data: Dict[str, Any]) -> FormTemplate:
    """Create a FormTemplate model from API response data."""
    return FormTemplate(**data)
