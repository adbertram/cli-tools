"""Item models for Moz CLI.

Moz API models for keyword research and SEO data.

Model Design Principles:
- Required fields have no default value (Pydantic enforces presence)
- Optional fields use Optional[Type] = None
- Use enums for fields with fixed value sets
- Create specific model subclasses for different entity types
- Use factory functions for polymorphic model creation

Read-Only Field Patterns (Pydantic native):
- Field(frozen=True): Immutable after model creation (raises error on assignment)
- Field(exclude=True): Excluded from model_dump() output
- Field(init=False): Excluded from __init__ (requires default value)
- Combine patterns as needed: Field(frozen=True, exclude=True)
"""
from enum import Enum
from typing import List, Optional

from pydantic import Field

from .base import CLIModel


# ==================== Enums ====================
# Define enums for fields with fixed value sets


class SearchIntentType(str, Enum):
    """Search intent classification types."""

    INFORMATIONAL = "informational"
    NAVIGATIONAL = "navigational"
    COMMERCIAL = "commercial"
    TRANSACTIONAL = "transactional"


# ==================== Models ====================


class KeywordMetrics(CLIModel):
    """Keyword metrics returned by list/get commands.

    Required fields:
    - keyword: The keyword itself
    - volume: Monthly search volume
    - difficulty: Keyword difficulty score (0-100)

    Optional fields:
    - ctr: Organic click-through rate estimate
    - priority: Moz priority score
    """

    keyword: str
    volume: Optional[int] = None
    difficulty: Optional[float] = None
    ctr: Optional[float] = None
    priority: Optional[float] = None


class KeywordDetail(CLIModel):
    """Detailed keyword model returned by get commands.

    Extends KeywordMetrics with additional detail fields.
    """

    keyword: str
    volume: Optional[int] = None
    difficulty: Optional[float] = None
    ctr: Optional[float] = None
    priority: Optional[float] = None
    intent: Optional[SearchIntentType] = None
    long_tail: Optional[bool] = None


class SuggestionKeyword(CLIModel):
    """Related keyword suggestions.

    Returned by suggestions command.
    """

    keyword: str
    volume: Optional[int] = None
    difficulty: Optional[float] = None
    related_to: Optional[str] = None


class IntentScore(CLIModel):
    """Individual intent score."""

    label: str
    score: float


class SearchIntent(CLIModel):
    """Search intent analysis for a keyword.

    Returned by intent command.
    Based on Moz API response structure.
    """

    keyword: str
    primary_intents: List[str] = Field(default_factory=list)
    all_intents: List[IntentScore] = Field(default_factory=list)

    @property
    def intent_type(self) -> Optional[str]:
        """Get the primary intent type."""
        return self.primary_intents[0] if self.primary_intents else None

    @property
    def confidence(self) -> Optional[float]:
        """Get the confidence score for the primary intent."""
        if self.primary_intents and self.all_intents:
            primary = self.primary_intents[0]
            for intent in self.all_intents:
                if intent.label == primary:
                    return intent.score
        return None


class RankingKeyword(CLIModel):
    """Keywords a URL ranks for.

    Returned by ranking command.
    """

    keyword: str
    position: Optional[int] = None
    # Moz returns volume as a float for ranking keywords (e.g. 10.537...).
    # KeywordMetrics returns volume as an int — these are separate API shapes.
    volume: Optional[float] = None
    difficulty: Optional[float] = None
    url: Optional[str] = None


# ==================== Factory Functions ====================
# Use factory functions for polymorphic model creation


def create_keyword_metrics(data: dict) -> KeywordMetrics:
    """Create a KeywordMetrics model from API response data.

    Args:
        data: Raw dict from API response

    Returns:
        KeywordMetrics model instance

    Raises:
        ValidationError: If required fields are missing
    """
    # Map API field name organic_ctr to model field ctr
    if "organic_ctr" in data:
        data["ctr"] = data.pop("organic_ctr")
    return KeywordMetrics(**data)


def create_keyword_detail(data: dict) -> KeywordDetail:
    """Create a KeywordDetail model from API response data.

    Args:
        data: Raw dict from API response

    Returns:
        KeywordDetail model instance

    Raises:
        ValidationError: If required fields are missing
    """
    return KeywordDetail(**data)


def create_suggestion_keyword(data: dict) -> SuggestionKeyword:
    """Create a SuggestionKeyword model from API response data.

    Args:
        data: Raw dict from API response

    Returns:
        SuggestionKeyword model instance

    Raises:
        ValidationError: If required fields are missing
    """
    return SuggestionKeyword(**data)


def create_search_intent(data: dict) -> SearchIntent:
    """Create a SearchIntent model from API response data.

    Args:
        data: Raw dict from API response

    Returns:
        SearchIntent model instance

    Raises:
        ValidationError: If required fields are missing
    """
    return SearchIntent(**data)


def create_ranking_keyword(data: dict) -> RankingKeyword:
    """Create a RankingKeyword model from API response data.

    Args:
        data: Raw dict from API response

    Returns:
        RankingKeyword model instance

    Raises:
        ValidationError: If required fields are missing
    """
    return RankingKeyword(**data)
