"""Query models for Scrunch CLI."""
from typing import Any, Dict, List, Optional

from .base import CLIModel


class QueryResult(CLIModel):
    """A single row of query results with aggregated metrics."""

    # Dimensions (all optional since they depend on the query)
    date: Optional[str] = None
    date_week: Optional[str] = None
    date_month: Optional[str] = None
    date_quarter: Optional[str] = None
    date_year: Optional[str] = None
    prompt_id: Optional[int] = None
    prompt: Optional[str] = None
    persona_id: Optional[int] = None
    persona_name: Optional[str] = None
    ai_platform: Optional[str] = None
    ai_platform_search_enabled: Optional[bool] = None
    tag: Optional[str] = None
    source_url: Optional[str] = None
    source_type: Optional[str] = None
    competitor_id: Optional[int] = None
    competitor_name: Optional[str] = None
    branded: Optional[bool] = None
    stage: Optional[str] = None
    prompt_topic: Optional[str] = None
    country: Optional[str] = None

    # Metrics (all optional since they depend on the fields requested)
    responses: Optional[int] = None
    brand_presence_percentage: Optional[float] = None
    brand_position_score: Optional[float] = None
    brand_sentiment_score: Optional[float] = None
    competitor_presence_percentage: Optional[float] = None
    competitor_position_score: Optional[float] = None
    competitor_sentiment_score: Optional[float] = None


class QueryResponse(CLIModel):
    """Response wrapper for query results."""

    total: Optional[int] = None
    offset: Optional[int] = None
    limit: Optional[int] = None
    items: List[Dict[str, Any]] = []
    metadata: Optional[dict] = None


def create_query_result(data: dict) -> QueryResult:
    """Create a QueryResult model from API response data."""
    return QueryResult(**data)
