"""Earnings models for ATA Blog CLI.

Models for Raptive ad earnings and revenue data.
"""
from typing import Optional
from .base import CLIModel


class PostEarnings(CLIModel):
    """Earnings data for a single post/page.

    Maps to Raptive earnings by-page response fields with WordPress enrichment.
    """
    page_url: Optional[str] = None
    pageviews: int
    earnings: float
    rpm: float
    impressions: int
    cpm: float
    viewability: float
    impressions_per_pageview: float
    start_date: str
    end_date: str
    author: Optional[str] = None
    modified_date: Optional[str] = None
    # Enriched from WordPress
    publish_date: Optional[str] = None
    earnings_per_day: Optional[float] = None


def create_post_earnings(data: dict) -> PostEarnings:
    """Factory function to create PostEarnings from raptive CLI output.

    Args:
        data: Dict from raptive earnings by-page output

    Returns:
        PostEarnings model instance
    """
    return PostEarnings(**data)
