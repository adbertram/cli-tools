"""Raptive CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Model Architecture:
- CLIModel: Base class with CLI-friendly configuration
- DashboardSummary: Summary metrics for dashboard
- EarningsOverview: Daily earnings data
- DeviceEarnings/DeviceTraffic: Device breakdowns
- TrafficSource: Traffic by source

Usage:
    from .models import DashboardSummary, EarningsOverview, TrafficSource

    # Create from API response
    summary = DashboardSummary(**api_data)

    # Serialize to JSON
    print_json(summary)
"""
from .base import CLIModel
from .item import (
    # Models
    DashboardSummary,
    DateBounds,
    EarningsOverview,
    DeviceEarnings,
    VideoEarnings,
    TrafficSource,
    DeviceTraffic,
    # Reports models
    PagePerformance,
    TrafficSourcePerformance,
    CountryPerformance,
    CategoryPerformance,
    BrandSafetyPage,
    AdNetworkEarnings,
    Site,
    # Enums
    DeviceType,
    # Factory functions
    create_dashboard_summary,
    create_earnings_overview,
    create_device_earnings,
    create_traffic_source,
    create_device_traffic,
)

__all__ = [
    # Base
    "CLIModel",
    # Models
    "DashboardSummary",
    "DateBounds",
    "EarningsOverview",
    "DeviceEarnings",
    "VideoEarnings",
    "TrafficSource",
    "DeviceTraffic",
    # Reports models
    "PagePerformance",
    "TrafficSourcePerformance",
    "CountryPerformance",
    "CategoryPerformance",
    "BrandSafetyPage",
    "AdNetworkEarnings",
    "Site",
    # Enums
    "DeviceType",
    # Factory functions
    "create_dashboard_summary",
    "create_earnings_overview",
    "create_device_earnings",
    "create_traffic_source",
    "create_device_traffic",
]
