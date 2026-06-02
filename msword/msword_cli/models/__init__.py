"""Msword CLI models."""
from .base import CLIModel
from .item import Comment, DocumentContent, ConvertedDocument, AddCommentResult

__all__ = [
    "CLIModel",
    "Comment",
    "DocumentContent",
    "ConvertedDocument",
    "AddCommentResult",
]
