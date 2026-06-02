"""Leanpub API models."""
from typing import Any, Dict, List, Optional

from .base import CLIModel


class CurrentUser(CLIModel):
    """Authenticated Leanpub user."""

    username: str
    email: str


class BookSummary(CLIModel):
    """Leanpub book summary returned by /{slug}.json."""

    slug: str
    title: str
    subtitle: Optional[str] = None
    about_the_book: Optional[str] = None
    author_string: Optional[str] = None
    url: Optional[str] = None
    title_page_url: Optional[str] = None
    image: Optional[str] = None
    minimum_paid_price: Optional[float] = None
    minimum_price: Optional[float] = None
    suggested_price: Optional[float] = None
    page_count: Optional[int] = None
    page_count_published: Optional[int] = None
    word_count: Optional[int] = None
    word_count_published: Optional[int] = None
    total_copies_sold: Optional[int] = None
    total_revenue: Optional[float] = None
    last_published_at: Optional[str] = None
    meta_description: Optional[str] = None
    possible_reader_count: Optional[int] = None
    pdf_preview_url: Optional[str] = None
    epub_preview_url: Optional[str] = None
    mobi_preview_url: Optional[str] = None
    pdf_published_url: Optional[str] = None
    epub_published_url: Optional[str] = None
    mobi_published_url: Optional[str] = None


class RoyaltySummary(CLIModel):
    """Leanpub royalty summary returned by /{slug}/royalties.json."""

    total_royalties: float
    royalties_bundled: float
    royalties_unbundled: float
    last_week_royalties: float
    royalties_to_revenue_ratio: float
    total_revenue: float
    revenue_bundled: float
    revenue_unbundled: float
    total_copies_sold: int
    num_copies_sold_bundled: int
    num_copies_sold_unbundled: int


class AuthorBookStats(CLIModel):
    """Per-book author revenue and royalty stats."""

    slug: str
    title: str
    author_string: Optional[str] = None
    total_revenue: float
    revenue_bundled: float
    revenue_unbundled: float
    total_royalties: float
    royalties_bundled: float
    royalties_unbundled: float
    last_week_royalties: float
    royalties_to_revenue_ratio: float
    total_copies_sold: int
    num_copies_sold_bundled: int
    num_copies_sold_unbundled: int
    summary_total_revenue: Optional[float] = None
    summary: Dict[str, Any]
    royalties: Dict[str, Any]


class AuthorStatsSummary(CLIModel):
    """Aggregated author stats across multiple Leanpub books."""

    book_count: int
    total_revenue: float
    revenue_bundled: float
    revenue_unbundled: float
    total_royalties: float
    royalties_bundled: float
    royalties_unbundled: float
    last_week_royalties: float
    total_copies_sold: int
    num_copies_sold_bundled: int
    num_copies_sold_unbundled: int
    books: List[AuthorBookStats]


def create_current_user(data: dict) -> CurrentUser:
    """Create a CurrentUser model from API response data."""
    return CurrentUser(**data)


def create_book_summary(data: dict) -> BookSummary:
    """Create a BookSummary model from API response data."""
    return BookSummary(**data)


def create_royalty_summary(data: dict) -> RoyaltySummary:
    """Create a RoyaltySummary model from API response data."""
    return RoyaltySummary(**data)


def create_author_book_stats(
    summary: BookSummary,
    royalties: RoyaltySummary,
    raw_summary: Dict[str, Any],
    raw_royalties: Dict[str, Any],
) -> AuthorBookStats:
    """Create per-book author stats from summary and royalty responses."""
    return AuthorBookStats(
        slug=summary.slug,
        title=summary.title,
        author_string=summary.author_string,
        total_revenue=royalties.total_revenue,
        revenue_bundled=royalties.revenue_bundled,
        revenue_unbundled=royalties.revenue_unbundled,
        total_royalties=royalties.total_royalties,
        royalties_bundled=royalties.royalties_bundled,
        royalties_unbundled=royalties.royalties_unbundled,
        last_week_royalties=royalties.last_week_royalties,
        royalties_to_revenue_ratio=royalties.royalties_to_revenue_ratio,
        total_copies_sold=royalties.total_copies_sold,
        num_copies_sold_bundled=royalties.num_copies_sold_bundled,
        num_copies_sold_unbundled=royalties.num_copies_sold_unbundled,
        summary_total_revenue=summary.total_revenue,
        summary=raw_summary,
        royalties=raw_royalties,
    )
