"""Site Audit models for Ahrefs CLI.

Model Design:
- SiteAuditReport: Complete audit report with all sections
- Crawl: Individual crawl/audit instance
- Issue: Single issue with category and severity
- IssuesByCategory: Issues grouped by category
- OrphanPage: Page without internal links
- RedirectChain: Chain of redirects preserving hierarchy
- OverviewMetrics: Health score and summary metrics
"""
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import Field

from .base import CLIModel


# ==================== Enums ====================


class IssueSeverity(str, Enum):
    """Severity levels for issues."""

    ERROR = "error"
    WARNING = "warning"
    NOTICE = "notice"
    INFO = "info"


class IssueCategory(str, Enum):
    """Issue category types from Ahrefs."""

    HTML = "html"
    META = "meta"
    REDIRECT = "redirect"
    LINKS = "links"
    IMAGES = "images"
    SOCIAL = "social"
    CONTENT = "content"
    PERFORMANCE = "performance"
    RESOURCES = "resources"
    LOCALIZATION = "localization"
    OTHER = "other"


class CrawlStatus(str, Enum):
    """Status of a crawl."""

    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"
    FAILED = "failed"
    QUEUED = "queued"


# ==================== Models ====================


class Issue(CLIModel):
    """Single issue from site audit."""

    id: str = Field(frozen=True)
    title: str
    category: IssueCategory
    severity: IssueSeverity
    url: Optional[str] = None
    description: Optional[str] = None
    count: int = 1
    affected_urls: List[str] = []


class IssuesByCategory(CLIModel):
    """Issues grouped by category (HTML, meta, etc.)."""

    html: List[Issue] = []
    meta: List[Issue] = []
    redirect: List[Issue] = []
    links: List[Issue] = []
    images: List[Issue] = []
    social: List[Issue] = []
    content: List[Issue] = []
    performance: List[Issue] = []
    resources: List[Issue] = []
    localization: List[Issue] = []
    other: List[Issue] = []


class OrphanPage(CLIModel):
    """Orphan page without internal links."""

    url: str
    title: Optional[str] = None
    http_code: Optional[int] = None
    size_bytes: Optional[int] = None
    word_count: Optional[int] = None
    inlinks: int = 0
    outlinks: int = 0
    external_links: int = 0
    crawl_depth: Optional[int] = None


class RedirectChain(CLIModel):
    """Redirect chain preserving hierarchical structure."""

    chain: List[str]  # [url1, url2, url3] showing redirect path
    source_url: str
    final_url: str
    chain_length: int
    http_codes: List[int] = []


class DuplicateContent(CLIModel):
    """Duplicate content issue."""

    url: str
    duplicate_of: str
    similarity: Optional[float] = None
    title: Optional[str] = None
    content_hash: Optional[str] = None


class OverviewMetrics(CLIModel):
    """Overview metrics from site audit."""

    health_score: Optional[float] = None
    pages_crawled: int = 0
    total_issues: int = 0
    errors_count: int = 0
    warnings_count: int = 0
    notices_count: int = 0
    pages_with_issues: int = 0
    internal_urls: int = 0
    external_urls: int = 0
    broken_links: int = 0
    redirects: int = 0
    orphan_pages: int = 0
    duplicate_content: int = 0
    raw_metrics: Dict[str, Any] = {}


class Crawl(CLIModel):
    """Individual crawl/audit instance."""

    id: str = Field(frozen=True)
    project_id: int = Field(frozen=True)
    status: CrawlStatus = CrawlStatus.COMPLETED
    crawl_date: str
    pages_crawled: int = 0
    issues_found: int = 0
    health_score: Optional[float] = None
    duration_seconds: Optional[int] = None


class Project(CLIModel):
    """Ahrefs project/site."""

    id: int = Field(frozen=True)
    name: str
    domain: str
    crawl_frequency: Optional[str] = None
    last_crawl_date: Optional[str] = None


class SiteAuditReport(CLIModel):
    """Complete site audit report with all sections.

    This is the main model returned by `site-audit get` command.
    Contains all audit data in a unified structure.
    """

    project_id: int = Field(frozen=True)
    crawl_id: str = Field(frozen=True)
    crawl_date: str
    domain: Optional[str] = None

    # Overview metrics
    overview: OverviewMetrics

    # Issues by category (errors/warnings only)
    issues: IssuesByCategory

    # Specific export data
    orphan_pages: List[OrphanPage] = []
    redirect_chains: List[RedirectChain] = []
    duplicate_content: List[DuplicateContent] = []

    # Errors during fetch (for partial data recovery)
    errors: List[str] = []


# ==================== Factory Functions ====================


def create_issue(data: dict) -> Issue:
    """Create an Issue from API response data."""
    # Map category string to enum
    category_str = data.get("category", "other").lower()
    try:
        category = IssueCategory(category_str)
    except ValueError:
        category = IssueCategory.OTHER

    # Map severity string to enum
    severity_str = data.get("severity", "warning").lower()
    try:
        severity = IssueSeverity(severity_str)
    except ValueError:
        severity = IssueSeverity.WARNING

    return Issue(
        id=data.get("id", str(hash(data.get("title", "")))),
        title=data.get("title", "Unknown issue"),
        category=category,
        severity=severity,
        url=data.get("url"),
        description=data.get("description"),
        count=data.get("count", 1),
        affected_urls=data.get("affected_urls", []),
    )


def create_crawl(data: dict) -> Crawl:
    """Create a Crawl from API response data."""
    status_str = data.get("status", "completed").lower()
    try:
        status = CrawlStatus(status_str)
    except ValueError:
        status = CrawlStatus.COMPLETED

    return Crawl(
        id=str(data.get("id", "")),
        project_id=data.get("project_id", data.get("project", 0)),
        status=status,
        crawl_date=data.get("crawl_date", data.get("date", "")),
        pages_crawled=data.get("pages_crawled", 0),
        issues_found=data.get("issues_found", 0),
        health_score=data.get("health_score"),
        duration_seconds=data.get("duration_seconds"),
    )


def create_site_audit_report(
    project_id: int,
    crawl_id: str,
    crawl_date: str,
    overview: OverviewMetrics,
    issues: IssuesByCategory,
    orphan_pages: Optional[List[OrphanPage]] = None,
    redirect_chains: Optional[List[RedirectChain]] = None,
    duplicate_content: Optional[List[DuplicateContent]] = None,
    domain: Optional[str] = None,
    errors: Optional[List[str]] = None,
) -> SiteAuditReport:
    """Create a SiteAuditReport from collected data."""
    return SiteAuditReport(
        project_id=project_id,
        crawl_id=crawl_id,
        crawl_date=crawl_date,
        domain=domain,
        overview=overview,
        issues=issues,
        orphan_pages=orphan_pages or [],
        redirect_chains=redirect_chains or [],
        duplicate_content=duplicate_content or [],
        errors=errors or [],
    )


# Aliases for backward compatibility with template
Item = Crawl
ItemDetail = SiteAuditReport
ItemStatus = CrawlStatus
ItemType = IssueCategory
create_item = create_crawl
create_item_detail = lambda data: SiteAuditReport(**data)
