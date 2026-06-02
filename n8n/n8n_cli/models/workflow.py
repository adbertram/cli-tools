"""Workflow models for n8n API responses."""
from typing import Any, Dict, List, Optional
from pydantic import Field
from .base import CLIModel


class Workflow(CLIModel):
    """Workflow summary returned by list endpoint."""
    id: str
    name: str
    active: bool
    createdAt: str = ""
    updatedAt: str = ""
    versionId: Optional[str] = None


class WorkflowDetail(CLIModel):
    """Full workflow detail returned by get endpoint."""
    id: str
    name: str
    active: bool
    createdAt: str = ""
    updatedAt: str = ""
    versionId: Optional[str] = None
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    connections: Dict[str, Any] = Field(default_factory=dict)
    settings: Dict[str, Any] = Field(default_factory=dict)
    tags: List[Dict[str, Any]] = Field(default_factory=list)
