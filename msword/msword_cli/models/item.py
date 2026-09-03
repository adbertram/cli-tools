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
    """One batch edit applied as a w:del plus one or more w:ins elements.

    ``ins_id`` is the first inserted-content wrapper's id. When ``new_text``
    contains a paragraph break ("\\n\\n"), the replacement spans more than
    one ``w:p`` and additional w:ins ids are allocated: one more
    inserted-content wrapper per extra paragraph, plus one inserted
    paragraph-mark per new break. Those extra ids are listed in
    ``extra_ins_ids``, empty for a single-paragraph replacement.
    """

    old_text: str
    new_text: str
    occurrence: int
    del_id: str = Field(frozen=True)
    ins_id: str = Field(frozen=True)
    extra_ins_ids: List[str] = Field(default_factory=list, frozen=True)


class EditTrackedChangesResult(CLIModel):
    """Result of applying a batch of tracked-change edits to a Word document."""

    file: str
    author: str
    edits_applied: int
    edits: List[TrackedEditApplied]
