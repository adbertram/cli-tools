"""Keywords CLI models.

Models for autocomplete suggestions from search engines.
"""
from .base import CLIModel
from .item import (
    # Models
    SuggestionResult,
    SuggestionRow,
    RecursiveSuggestion,
    RecursiveSuggestionResult,
    RecursiveSuggestionRow,
    # Enums
    Source,
    # Factory functions
    create_suggestion_result,
    flatten_recursive_suggestions,
)

__all__ = [
    # Base
    "CLIModel",
    # Models
    "SuggestionResult",
    "SuggestionRow",
    "RecursiveSuggestion",
    "RecursiveSuggestionResult",
    "RecursiveSuggestionRow",
    # Enums
    "Source",
    # Factory functions
    "create_suggestion_result",
    "flatten_recursive_suggestions",
]
