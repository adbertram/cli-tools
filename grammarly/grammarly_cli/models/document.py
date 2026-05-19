"""Grammarly Document models for the docs command group.

Models for interacting with Grammarly's document storage API (dox.grammarly.com).
Uses cookie-based authentication from browser session.
"""
from typing import Optional, List
from pydantic import Field
from .base import CLIModel


class Document(CLIModel):
    """Grammarly document metadata.

    Represents a document from the dox.grammarly.com API.
    Note: API returns id as integer, we convert to string for consistency.
    """

    id: int = Field(description="Document ID")
    title: Optional[str] = Field(default=None, description="Document title")
    first_content: Optional[str] = Field(
        default=None, alias="first_content", description="First content snippet"
    )
    created_at: Optional[str] = Field(
        default=None, alias="created_at", description="Creation timestamp"
    )
    updated_at: Optional[str] = Field(
        default=None, alias="updated_at", description="Last modified timestamp"
    )
    size: Optional[int] = Field(default=None, description="Document size in bytes")
    errors: Optional[int] = Field(default=None, description="Error count")


class DocumentDetail(CLIModel):
    """Extended document details from coda.grammarly.com initLoad API."""

    id: int = Field(description="Document ID")
    title: Optional[str] = Field(default=None, description="Document title")
    content: Optional[str] = Field(default=None, description="Full document content")
    revision_id: Optional[str] = Field(
        default=None, alias="revisionId", description="Revision ID"
    )


def create_document(data: dict) -> Document:
    """Create Document from API response."""
    return Document(**data)


def create_document_list(data: list) -> List[Document]:
    """Create list of Documents from API response."""
    return [Document(**item) for item in data]
