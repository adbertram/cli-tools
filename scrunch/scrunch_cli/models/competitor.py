"""Competitor models for Scrunch CLI."""
from typing import List, Optional

from .base import CLIModel


class Competitor(CLIModel):
    """Competitor model returned by the API."""

    id: int
    name: str
    alternative_names: List[str] = []
    websites: List[str] = []


class CreateCompetitor(CLIModel):
    """Model for creating a new competitor."""

    name: str
    alternative_names: Optional[List[str]] = None
    websites: Optional[List[str]] = None


class UpdateCompetitor(CLIModel):
    """Model for updating a competitor."""

    name: Optional[str] = None
    alternative_names: Optional[List[str]] = None
    websites: Optional[List[str]] = None


def create_competitor(data: dict) -> Competitor:
    """Create a Competitor model from API response data."""
    return Competitor(**data)
