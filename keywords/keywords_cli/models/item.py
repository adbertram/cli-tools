"""Suggestion models for Keywords CLI.

Models for autocomplete suggestions from search engines.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from .base import CLIModel


class Source(str, Enum):
    """Supported autocomplete sources."""

    GOOGLE = "google"
    YOUTUBE = "youtube"
    BING = "bing"
    AMAZON = "amazon"
    DUCKDUCKGO = "ddg"


class SuggestionResult(CLIModel):
    """Result from querying autocomplete suggestions for a single source."""

    query: str
    source: Source
    suggestions: List[str]
    count: int


class RecursiveSuggestion(CLIModel):
    """A suggestion that may have child suggestions from recursive querying."""

    text: str
    children: List[RecursiveSuggestion] = []


class RecursiveSuggestionResult(CLIModel):
    """Result from recursive querying of autocomplete suggestions."""

    query: str
    source: Source
    depth: int
    suggestions: List[RecursiveSuggestion]
    total_count: int


class SuggestionRow(CLIModel):
    """Flattened suggestion row for table display."""

    source: str
    suggestion: str


class RecursiveSuggestionRow(CLIModel):
    """Flattened recursive suggestion row for table display."""

    source: str
    depth: int
    parent: str
    suggestion: str


def create_suggestion_result(query: str, source: Source, suggestions: List[str]) -> SuggestionResult:
    """Create a SuggestionResult from query parameters and suggestions.

    Args:
        query: Original search query
        source: Source that produced suggestions
        suggestions: List of suggestion strings

    Returns:
        SuggestionResult model instance
    """
    return SuggestionResult(
        query=query,
        source=source,
        suggestions=suggestions,
        count=len(suggestions),
    )


def flatten_recursive_suggestions(
    suggestions: List[RecursiveSuggestion],
    source: str,
    parent: str = "",
    current_depth: int = 0,
) -> List[RecursiveSuggestionRow]:
    """Flatten recursive suggestions into rows for table display.

    Args:
        suggestions: List of recursive suggestions
        source: Source name
        parent: Parent query text
        current_depth: Current recursion depth

    Returns:
        List of flattened rows
    """
    rows = []
    for suggestion in suggestions:
        rows.append(
            RecursiveSuggestionRow(
                source=source,
                depth=current_depth,
                parent=parent,
                suggestion=suggestion.text,
            )
        )
        if suggestion.children:
            rows.extend(
                flatten_recursive_suggestions(
                    suggestion.children,
                    source,
                    parent=suggestion.text,
                    current_depth=current_depth + 1,
                )
            )
    return rows
