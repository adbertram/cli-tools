"""Persona models for Scrunch CLI."""
from typing import Optional

from .base import CLIModel


class Persona(CLIModel):
    """Persona model returned by the API."""

    id: int
    name: str
    description: Optional[str] = None


class CreatePersona(CLIModel):
    """Model for creating a new persona."""

    name: str
    description: str


class UpdatePersona(CLIModel):
    """Model for updating a persona."""

    name: Optional[str] = None
    description: Optional[str] = None


def create_persona(data: dict) -> Persona:
    """Create a Persona model from API response data."""
    return Persona(**data)
