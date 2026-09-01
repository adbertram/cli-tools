"""Models for Msword CLI."""
from typing import List, Optional

from pydantic import Field

from .base import CLIModel


class Comment(CLIModel):
    """A comment extracted from a Word document."""

    id: str = Field(frozen=True)
    author: str
    date: Optional[str] = None
    text: str
    context: Optional[str] = None


class DocumentContent(CLIModel):
    """Text content from a Word document."""

    file: str
    paragraphs: int
    content: str


class ConvertedDocument(CLIModel):
    """Markdown-converted Word document."""

    file: str
    markdown: str
    messages: List[str] = []


class AddCommentResult(CLIModel):
    """Result of adding a comment to a Word document."""

    file: str
    comment_id: str = Field(frozen=True)
    author: str
    text: str
    reference_text: str


class TrackedEditApplied(CLIModel):
    """One batch edit applied as a w:ins/w:del tracked-change pair."""

    old_text: str
    new_text: str
    occurrence: int
    del_id: str = Field(frozen=True)
    ins_id: str = Field(frozen=True)


class EditTrackedChangesResult(CLIModel):
    """Result of applying a batch of tracked-change edits to a Word document."""

    file: str
    author: str
    edits_applied: int
    edits: List[TrackedEditApplied]
