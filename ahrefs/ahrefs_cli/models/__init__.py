"""Ahrefs CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Model Architecture:
- CLIModel: Base class with CLI-friendly configuration
- SiteAuditReport: Complete audit report with all sections
- Crawl: Individual crawl/audit instance (used for list commands)
- Issue, IssuesByCategory: Issue models
- OrphanPage, RedirectChain, DuplicateContent: Export data models
- OverviewMetrics: Health score and summary metrics
"""
from .base import CLIModel
from .item import (
    # Primary models
    SiteAuditReport,
    Crawl,
    Project,
    Issue,
    IssuesByCategory,
    OrphanPage,
    RedirectChain,
    DuplicateContent,
    OverviewMetrics,
    # Enums
    IssueSeverity,
    IssueCategory,
    CrawlStatus,
    # Factory functions
    create_issue,
    create_crawl,
    create_site_audit_report,
    # Aliases for template compatibility
    Item,
    ItemDetail,
    ItemStatus,
    ItemType,
    create_item,
    create_item_detail,
)

__all__ = [
    # Base
    "CLIModel",
    # Primary models
    "SiteAuditReport",
    "Crawl",
    "Project",
    "Issue",
    "IssuesByCategory",
    "OrphanPage",
    "RedirectChain",
    "DuplicateContent",
    "OverviewMetrics",
    # Enums
    "IssueSeverity",
    "IssueCategory",
    "CrawlStatus",
    # Factory functions
    "create_issue",
    "create_crawl",
    "create_site_audit_report",
    # Template compatibility aliases
    "Item",
    "ItemDetail",
    "ItemStatus",
    "ItemType",
    "create_item",
    "create_item_detail",
]
