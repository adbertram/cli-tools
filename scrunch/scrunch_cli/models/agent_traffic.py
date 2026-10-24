"""Agent traffic models for Scrunch CLI."""
from typing import Any, Dict, List, Optional

from .base import CLIModel


class AgentTrafficRow(CLIModel):
    """A single row of agent traffic data."""

    requests: Optional[int] = None
    date: Optional[str] = None
    site: Optional[str] = None
    path: Optional[str] = None
    agent_source: Optional[str] = None
    agent_type: Optional[str] = None


class AgentTrafficResponse(CLIModel):
    """Response wrapper for agent traffic data."""

    meta: Optional[Dict[str, Any]] = None
    data: List[Dict[str, Any]] = []


def create_agent_traffic_row(data: dict) -> AgentTrafficRow:
    """Create an AgentTrafficRow model from API response data."""
    return AgentTrafficRow(**data)
