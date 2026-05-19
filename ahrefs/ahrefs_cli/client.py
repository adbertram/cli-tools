"""Ahrefs client using browser automation and internal v4 API.

This client wraps AhrefsBrowser with site-specific methods for
Ahrefs Site Audit operations. Uses the internal v4 API endpoints
via fetch_json() for authenticated requests.
"""
import random
import time
from typing import Any, Callable, Dict, List, Optional

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.data_cache import cached

from .config import get_config
from .browser import AhrefsBrowser, BrowserAutomationError
from .cache import cache_exists, get_cached_report, save_cached_report
from .models import (
    Crawl,
    DuplicateContent,
    Issue,
    IssueCategory,
    IssuesByCategory,
    IssueSeverity,
    OrphanPage,
    OverviewMetrics,
    Project,
    RedirectChain,
    SiteAuditReport,
    create_crawl,
    create_issue,
)


# V4 API Endpoints (POST requests)
V4_API_ENDPOINTS = {
    "saGetProject": "/v4/saGetProject",
    "saCrawls": "/v4/saCrawls",
    "saGetCrawl": "/v4/saGetCrawl",
    "saCharts": "/v4/saCharts",
    "saCrawlsHealthscore": "/v4/saCrawlsHealthscore",
    "saOverviewIssueCharts": "/v4/saOverviewIssueCharts",
    "saGetCountsByFilters": "/v4/saGetCountsByFilters",
    "saGetProjectIssues": "/v4/saGetProjectIssues",
    "saGetDiffsByIssues": "/v4/saGetDiffsByIssues",
    "saGetCountsByIssues": "/v4/saGetCountsByIssues",
    "saListSegmentFilters": "/v4/saListSegmentFilters",
}


class AhrefsClient:
    """Client for interacting with Ahrefs via browser automation and v4 API."""

    BASE_URL = "https://app.ahrefs.com"

    def __init__(self):
        """Initialize Ahrefs client."""
        self.config = get_config()
        self._browser: Optional[AhrefsBrowser] = None
        # Retry configuration
        self.max_retries = 3
        self.base_delay = 1.0
        self.max_delay = 30.0
        self.jitter = 0.5

    @property
    def browser(self) -> AhrefsBrowser:
        """Get or create browser service."""
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        """Close browser."""
        if self._browser:
            self._browser.close()
            self._browser = None

    # ==================== Retry Logic ====================

    def _calculate_retry_delay(
        self, attempt: int, retry_after: Optional[int] = None
    ) -> float:
        """Calculate retry delay with exponential backoff and jitter."""
        if retry_after is not None:
            return min(float(retry_after), self.max_delay)
        delay = self.base_delay * (2**attempt)
        delay += random.uniform(0, self.jitter)
        return min(delay, self.max_delay)

    def _retry_fetch(
        self,
        func: Callable,
        max_retries: Optional[int] = None,
        operation_name: str = "fetch",
    ) -> Any:
        """Execute a function with retry logic.

        Args:
            func: Function to execute
            max_retries: Max retry attempts (uses self.max_retries if None)
            operation_name: Name for error messages

        Returns:
            Result from func()

        Raises:
            ClientError: After all retries exhausted
        """
        retries = max_retries if max_retries is not None else self.max_retries

        for attempt in range(retries):
            try:
                result = func()
                # Check for API error response
                if isinstance(result, dict) and result.get("_error"):
                    status = result.get("status", "unknown")
                    raise ClientError(f"API returned status {status}")
                return result
            except Exception as e:
                if attempt < retries - 1:
                    delay = self._calculate_retry_delay(attempt)
                    time.sleep(delay)
                else:
                    raise ClientError(
                        f"{operation_name} failed after {retries} attempts: {e}"
                    )

    # ==================== Navigation & API Helpers ====================

    def _unwrap_api_response(self, result: Any) -> Dict[str, Any]:
        """Return the payload from Ahrefs' v4 response envelope."""
        if isinstance(result, dict) and result.get("_error"):
            status = result.get("status", "unknown")
            message = result.get("message", "")
            raise ClientError(f"API returned status {status}: {message}")

        if (
            isinstance(result, list)
            and len(result) == 2
            and result[0] == "Ok"
            and isinstance(result[1], dict)
        ):
            return result[1]

        if isinstance(result, list) and len(result) == 2 and result[0] == "Error":
            raise ClientError(f"API error: {result[1]}")

        raise ClientError(f"Unexpected API response: {result!r}")

    def ensure_authenticated(self, path: str = "/"):
        """Ensure user is authenticated before accessing a page."""
        self.browser.login()  # Idempotent
        url = f"{self.BASE_URL}{path}" if not path.startswith("http") else path
        page = self.browser.get_page()
        page.goto(url)

    def navigate(self, path: str):
        """Navigate to a path on Ahrefs."""
        url = f"{self.BASE_URL}{path}" if not path.startswith("http") else path
        page = self.browser.get_page()
        page.goto(url)

    def fetch_api(self, endpoint_name: str, payload: Dict[str, Any]) -> Any:
        """Make an authenticated POST request to an internal v4 API endpoint.

        Args:
            endpoint_name: Key from V4_API_ENDPOINTS dict
            payload: Request payload as dict

        Returns:
            JSON response from API

        Raises:
            ClientError: If endpoint unknown or request fails
        """
        if endpoint_name not in V4_API_ENDPOINTS:
            raise ClientError(f"Unknown API endpoint: {endpoint_name}")

        path = V4_API_ENDPOINTS[endpoint_name]
        url = f"{self.BASE_URL}{path}"

        # Ensure browser is initialized and we're on the site
        self.ensure_authenticated()

        # Use page.evaluate to make fetch request with session cookies
        page = self.browser.get_page()
        result = page.evaluate(
            """async ({url, payload}) => {
            const r = await fetch(url, {
                method: 'POST',
                headers: {'Content-Type': 'application/json; charset=utf-8'},
                credentials: 'include',
                body: JSON.stringify(payload)
            });
            return r.ok ? r.json() : {_error: true, status: r.status, message: await r.text()};
        }""",
            {"url": url, "payload": payload},
        )
        return self._unwrap_api_response(result)

    # ==================== Site Audit Methods ====================

    @cached
    def get_project(self, project_id: int) -> Project:
        """Get project details.

        Args:
            project_id: Ahrefs project ID

        Returns:
            Project model
        """

        def fetch():
            return self.fetch_api("saGetProject", {"project_id": str(project_id)})

        data = self._retry_fetch(fetch, operation_name="get_project")

        return Project(
            id=project_id,
            name=data.get("name", ""),
            domain=data.get("domain", data.get("target", "")),
            crawl_frequency=data.get("crawl_frequency"),
            last_crawl_date=data.get("last_crawl_date"),
        )

    @cached
    def list_crawls(self, project_id: int) -> List[Crawl]:
        """List all crawls/audits for a project.

        Args:
            project_id: Ahrefs project ID

        Returns:
            List of Crawl models, most recent first
        """

        def fetch():
            return self.fetch_api("saCrawls", {"project_id": str(project_id)})

        data = self._retry_fetch(fetch, operation_name="list_crawls")

        crawls = []
        for item in data.get("crawls", []):
            status_value = item.get("status", ["completed"])
            if isinstance(status_value, list):
                status_value = status_value[0] if status_value else "completed"
            timeframe = item.get("timeframe") or {}
            crawl = create_crawl(
                {
                    "id": str(item.get("crawlId", "")),
                    "project_id": project_id,
                    "crawl_date": item.get("finished") or timeframe.get("until", ""),
                    "status": str(status_value).lower(),
                    "pages_crawled": item.get("pages_crawled", 0),
                    "issues_found": item.get("issues_found", 0),
                    "health_score": item.get("health_score"),
                    "duration_seconds": None,
                }
            )
            crawls.append(crawl)

        return crawls

    @cached
    def get_crawl_details(self, project_id: int, crawl_id: str) -> Dict[str, Any]:
        """Get detailed information about a specific crawl.

        Args:
            project_id: Ahrefs project ID
            crawl_id: Specific crawl ID

        Returns:
            Raw crawl details dict
        """

        def fetch():
            return self.fetch_api(
                "saGetCrawl", {"project_id": str(project_id), "crawl_id": int(crawl_id)}
            )

        return self._retry_fetch(fetch, operation_name="get_crawl_details")

    @cached
    def get_overview_metrics(self, project_id: int) -> OverviewMetrics:
        """Get overview metrics for a project.

        Fetches from multiple API endpoints and combines results.

        Args:
            project_id: Ahrefs project ID

        Returns:
            OverviewMetrics model
        """
        raw_metrics = {}

        # Fetch health score
        try:

            def fetch_health():
                return self.fetch_api("saCrawlsHealthscore", {"project_id": str(project_id)})

            health_data = self._retry_fetch(fetch_health, operation_name="health_score")
            raw_metrics["health"] = health_data
        except ClientError:
            pass  # Continue with partial data

        # Fetch issue charts/overview
        try:

            def fetch_overview():
                return self.fetch_api("saOverviewIssueCharts", {"project_id": str(project_id)})

            overview_data = self._retry_fetch(
                fetch_overview, operation_name="overview_charts"
            )
            raw_metrics["overview"] = overview_data
        except ClientError:
            pass

        # Fetch counts
        try:

            def fetch_counts():
                return self.fetch_api("saGetCountsByFilters", {"project_id": str(project_id)})

            counts_data = self._retry_fetch(fetch_counts, operation_name="counts")
            raw_metrics["counts"] = counts_data
        except ClientError:
            pass

        # Fetch counts by issues
        try:

            def fetch_issue_counts():
                return self.fetch_api("saGetCountsByIssues", {"project_id": str(project_id)})

            issue_counts = self._retry_fetch(
                fetch_issue_counts, operation_name="issue_counts"
            )
            raw_metrics["issue_counts"] = issue_counts
        except ClientError:
            pass

        # Extract metrics from raw data
        health = raw_metrics.get("health", {})
        overview = raw_metrics.get("overview", {})
        counts = raw_metrics.get("counts", {})
        issue_counts = raw_metrics.get("issue_counts", {})

        return OverviewMetrics(
            health_score=health.get("score", health.get("health_score")),
            pages_crawled=counts.get("pages_crawled", counts.get("total_pages", 0)),
            total_issues=issue_counts.get("total", 0),
            errors_count=issue_counts.get("errors", 0),
            warnings_count=issue_counts.get("warnings", 0),
            notices_count=issue_counts.get("notices", 0),
            pages_with_issues=counts.get("pages_with_issues", 0),
            internal_urls=counts.get("internal_urls", 0),
            external_urls=counts.get("external_urls", 0),
            broken_links=counts.get("broken_links", 0),
            redirects=counts.get("redirects", 0),
            orphan_pages=counts.get("orphan_pages", 0),
            duplicate_content=counts.get("duplicate_content", 0),
            raw_metrics=raw_metrics,
        )

    @cached
    def get_project_issues(
        self, project_id: int, severity_filter: Optional[List[str]] = None
    ) -> IssuesByCategory:
        """Get all issues for a project, grouped by category.

        Args:
            project_id: Ahrefs project ID
            severity_filter: If provided, only include issues of these severities
                           (e.g., ["error", "warning"])

        Returns:
            IssuesByCategory model
        """
        if severity_filter is None:
            severity_filter = ["error", "warning"]  # Default: exclude info/notice

        def fetch():
            return self.fetch_api("saGetProjectIssues", {"project_id": str(project_id)})

        data = self._retry_fetch(fetch, operation_name="get_project_issues")

        # Group issues by category
        issues_by_cat = {cat.value: [] for cat in IssueCategory}

        for item in data.get("issues", data.get("items", [])):
            # Filter by severity
            severity = item.get("severity", "warning").lower()
            if severity not in severity_filter:
                continue

            issue = create_issue(item)
            cat_key = issue.category.value
            issues_by_cat[cat_key].append(issue)

        return IssuesByCategory(
            html=issues_by_cat.get("html", []),
            meta=issues_by_cat.get("meta", []),
            redirect=issues_by_cat.get("redirect", []),
            links=issues_by_cat.get("links", []),
            images=issues_by_cat.get("images", []),
            social=issues_by_cat.get("social", []),
            content=issues_by_cat.get("content", []),
            performance=issues_by_cat.get("performance", []),
            resources=issues_by_cat.get("resources", []),
            localization=issues_by_cat.get("localization", []),
            other=issues_by_cat.get("other", []),
        )

    def get_site_audit(
        self, project_id: int, refresh: bool = False
    ) -> SiteAuditReport:
        """Get complete site audit report for a project.

        Checks cache first unless refresh=True. Fetches all data from
        multiple API endpoints and combines into a unified report.

        Args:
            project_id: Ahrefs project ID
            refresh: If True, bypass cache and fetch fresh data

        Returns:
            SiteAuditReport model with all audit data
        """
        # Check cache first
        if not refresh and cache_exists(project_id):
            cached = get_cached_report(project_id)
            if cached:
                return cached

        errors = []
        crawl_date = ""
        crawl_id = ""
        domain = None

        # Get project info
        try:
            project = self.get_project(project_id)
            domain = project.domain
        except ClientError as e:
            errors.append(f"get_project: {e}")

        # Get crawls and latest crawl info
        try:
            crawls = self.list_crawls(project_id)
            if crawls:
                latest = crawls[0]  # Most recent first
                crawl_date = latest.crawl_date
                crawl_id = latest.id
        except ClientError as e:
            errors.append(f"list_crawls: {e}")

        # Get overview metrics
        try:
            overview = self.get_overview_metrics(project_id)
        except ClientError as e:
            errors.append(f"get_overview_metrics: {e}")
            overview = OverviewMetrics()

        # Get issues by category
        try:
            issues = self.get_project_issues(project_id)
        except ClientError as e:
            errors.append(f"get_project_issues: {e}")
            issues = IssuesByCategory()

        # Build the report
        report = SiteAuditReport(
            project_id=project_id,
            crawl_id=crawl_id,
            crawl_date=crawl_date,
            domain=domain,
            overview=overview,
            issues=issues,
            orphan_pages=[],  # TODO: Extract from API if available
            redirect_chains=[],  # TODO: Extract from API if available
            duplicate_content=[],  # TODO: Extract from API if available
            errors=errors,
        )

        # Cache the report
        save_cached_report(project_id, report)

        return report


# ==================== Module-level Singleton ====================

_client: Optional[AhrefsClient] = None


def get_client() -> AhrefsClient:
    """Get or create the global Ahrefs client instance."""
    global _client
    if _client is None:
        _client = AhrefsClient()
    return _client
