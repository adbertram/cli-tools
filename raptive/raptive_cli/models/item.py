"""Raptive data models for CLI.

Models for dashboard, earnings, and traffic data from the Raptive Publisher API.
"""
from enum import Enum
from typing import List, Optional

from pydantic import Field

from .base import CLIModel


# ==================== Enums ====================


class DeviceType(str, Enum):
    """Device types for traffic/earnings breakdown."""
    DESKTOP = "Desktop"
    MOBILE = "Mobile"
    TABLET = "Tablet"


# ==================== Dashboard Models ====================


class DashboardSummary(CLIModel):
    """Summary metrics from the dashboard."""

    start_date: str
    end_date: str
    earnings: float
    rpm: Optional[float] = None
    page_rpm: Optional[float] = None
    sessions: Optional[int] = None
    pageviews: Optional[int] = None


class DateBounds(CLIModel):
    """Date bounds for available data."""

    earliest_date: str
    latest_date: str


# ==================== Earnings Models ====================


class EarningsOverview(CLIModel):
    """Daily earnings data point."""

    date: str
    earnings: float
    sessions: Optional[int] = None
    pageviews: Optional[int] = None
    rpm: Optional[float] = None
    page_rpm: Optional[float] = None


class DeviceEarnings(CLIModel):
    """Earnings breakdown by device type."""

    device: DeviceType
    earnings: float
    rpm: Optional[float] = None
    sessions: Optional[int] = None
    pageviews: Optional[int] = None


class VideoEarnings(CLIModel):
    """Video earnings summary."""

    start_date: str
    end_date: str
    earnings: float
    player_type: Optional[str] = None


# ==================== Traffic Models ====================


class TrafficSource(CLIModel):
    """Traffic by source."""

    start_date: str
    end_date: str
    source: str
    sessions: int
    earnings: Optional[float] = None
    rpm: Optional[float] = None


class DeviceTraffic(CLIModel):
    """Traffic breakdown by device type."""

    device: DeviceType
    sessions: int
    pageviews: Optional[int] = None
    pages_per_session: Optional[float] = None


# ==================== Reports Models ====================


class PagePerformance(CLIModel):
    """Page-level performance metrics."""

    start_date: str
    end_date: str
    page_url: Optional[str] = None
    pageviews: int
    earnings: float
    rpm: float
    impressions: Optional[int] = None
    cpm: Optional[float] = None
    viewability: Optional[float] = None
    impressions_per_pageview: Optional[float] = None
    author: Optional[str] = None
    modified_date: Optional[str] = None


class TrafficSourcePerformance(CLIModel):
    """Traffic source performance metrics."""

    start_date: str
    end_date: str
    traffic_source: str
    earnings: float
    pageviews: int
    sessions: int
    rpm: float
    rps: float
    pps: float


class CountryPerformance(CLIModel):
    """Country-level performance metrics."""

    start_date: str
    end_date: str
    country: str
    earnings: float
    pageviews: int
    sessions: int
    rpm: float
    rps: float
    impressions: Optional[int] = None
    cpm: Optional[float] = None
    impressions_per_pageview: Optional[float] = None


class CategoryPerformance(CLIModel):
    """Category-level performance metrics."""

    start_date: str
    end_date: str
    category: str
    earnings: float
    pageviews: int
    sessions: int
    rpm: float
    rps: float
    cpm: Optional[float] = None
    num_posts: Optional[int] = None


class BrandSafetyPage(CLIModel):
    """Brand safety assessment for a page."""

    pagepath: str
    date: str
    pageviews: int
    rpm: float
    cpm: float
    # Safety ratings (normal, low, medium, high)
    alc: str  # Alcohol
    adt: str  # Adult
    dlm: str  # Debated sensitive social issues
    drg: str  # Drugs
    hat: str  # Hate speech
    off: str  # Offensive
    sam: str  # Spam
    vio: str  # Violence
    nr: str   # Not rated


class AdNetworkEarnings(CLIModel):
    """Earnings by ad network source."""

    ad_network: str
    year: int
    month: int
    earnings: float


# ==================== Site Models ====================


class Site(CLIModel):
    """Raptive site information."""

    id: str = Field(frozen=True)
    name: str
    url: Optional[str] = None
    status: Optional[str] = None


# ==================== Factory Functions ====================


def create_dashboard_summary(data: dict) -> DashboardSummary:
    """Create a DashboardSummary from API response data."""
    return DashboardSummary(**data)


def create_earnings_overview(data: dict) -> EarningsOverview:
    """Create an EarningsOverview from API response data."""
    return EarningsOverview(**data)


def create_device_earnings(data: dict) -> DeviceEarnings:
    """Create a DeviceEarnings from API response data."""
    return DeviceEarnings(**data)


def create_traffic_source(data: dict) -> TrafficSource:
    """Create a TrafficSource from API response data."""
    return TrafficSource(**data)


def create_device_traffic(data: dict) -> DeviceTraffic:
    """Create a DeviceTraffic from API response data."""
    return DeviceTraffic(**data)
