"""Moz CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Model Architecture:
- CLIModel: Base class with CLI-friendly configuration
- KeywordMetrics: Base model for keyword metrics
- KeywordDetail: Detailed model with intent and metadata
- SuggestionKeyword: Model for keyword suggestions
- SearchIntent: Model for search intent analysis
- RankingKeyword: Model for ranking keywords

Read-Only Fields:
- Use Field(frozen=True) for immutable fields
- Use Field(exclude=True) to exclude from model_dump()
- Use Field(init=False) to exclude from __init__

Usage:
    from .models import KeywordMetrics, SearchIntent, create_keyword_metrics

    # Create from API response
    keyword = create_keyword_metrics(api_response)

    # Access typed fields
    print(keyword.keyword)
    print(keyword.volume)

    # Serialize to JSON
    print_json(keyword)
"""
from .base import CLIModel
from .item import (
    # Models
    KeywordMetrics,
    KeywordDetail,
    SuggestionKeyword,
    IntentScore,
    SearchIntent,
    RankingKeyword,
    # Enums
    SearchIntentType,
    # Factory functions
    create_keyword_metrics,
    create_keyword_detail,
    create_suggestion_keyword,
    create_search_intent,
    create_ranking_keyword,
)

__all__ = [
    # Base
    "CLIModel",
    # Models
    "KeywordMetrics",
    "KeywordDetail",
    "SuggestionKeyword",
    "IntentScore",
    "SearchIntent",
    "RankingKeyword",
    # Enums
    "SearchIntentType",
    # Factory functions
    "create_keyword_metrics",
    "create_keyword_detail",
    "create_suggestion_keyword",
    "create_search_intent",
    "create_ranking_keyword",
]
