"""Ahrefs client using browser automation and internal v4 API.

This client wraps AhrefsBrowser with site-specific methods for
Ahrefs Site Audit operations. Uses the internal v4 API endpoints
via fetch_json() for authenticated requests.
"""
import os
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
    CrawlStatus,
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

        if isinstance(result, list) and len(result) == 2 and result[0] == "Error":
            raise ClientError(f"API error: {result[1]}")

        if (
            isinstance(result, list)
            and len(result) == 2
            and result[0] == "Ok"
        ):
            return result[1]

        if isinstance(result, list):
            return result

        raise ClientError(f"Unexpected API response: {result!r}")

    @staticmethod
    def _select_report_crawl(crawls: List[Crawl]) -> Optional[Crawl]:
        """Pick the newest crawl that can back a report.

        Ahrefs still lists failed crawls in project history, but the overview
        and issue endpoints need the latest crawl with usable report data.
        Prefer the newest crawl that is not marked failed; otherwise fall back
        to the newest crawl so callers still get the best available context.
        """
        if not crawls:
            return None
        for crawl in crawls:
            if crawl.status != CrawlStatus.FAILED:
                return crawl
        return crawls[0]

    @staticmethod
    def _build_timestamp_context(crawls: List[Crawl], target_crawl_id: str) -> Optional[Dict[str, Optional[str]]]:
        """Build the timestamp payload Ahrefs overview endpoints now require."""
        if not crawls or not target_crawl_id:
            return None

        target_index = next(
            (index for index, crawl in enumerate(crawls) if crawl.id == target_crawl_id),
            None,
        )
        if target_index is None:
            return None

        target = crawls[target_index]
        if not target.crawl_date:
            return None

        compare_with = None
        for crawl in crawls[target_index + 1 :]:
            if crawl.crawl_date:
                compare_with = crawl.crawl_date
                break
        if compare_with is None:
            compare_with = target.crawl_date

        return {
            "timestamp": target.crawl_date,
            "compare_with": compare_with,
        }

    def _build_healthscore_timestamps(
        self,
        crawls: List[Crawl],
        target_crawl_id: str,
        limit: int = 10,
    ) -> List[List[Any]]:
        """Build the timestamp series Ahrefs healthscore endpoint expects."""
        context = self._build_timestamp_context(crawls, target_crawl_id)
        if context is None:
            return []

        target_index = next(
            (index for index, crawl in enumerate(crawls) if crawl.id == target_crawl_id),
            0,
        )
        usable_crawls = [crawl for crawl in crawls[target_index:] if crawl.crawl_date][:limit]
        if not usable_crawls:
            return []

        payload: List[List[Any]] = []
        for index, crawl in enumerate(usable_crawls):
            compare_with = (
                usable_crawls[index + 1].crawl_date
                if index + 1 < len(usable_crawls)
                else crawl.crawl_date
            )
            payload.append(
                [
                    crawl.crawl_date,
                    {
                        "timestamp": crawl.crawl_date,
                        "compare_with": compare_with,
                    },
                ]
            )
        return payload

    @staticmethod
    def _extract_markdown_text(value: Any) -> Optional[str]:
        if isinstance(value, list) and len(value) >= 2 and value[0] == "Markdown":
            return value[1]
        if isinstance(value, str):
            return value
        return None

    @staticmethod
    def _map_issue_category(raw_type: Optional[str]) -> IssueCategory:
        if not raw_type:
            return IssueCategory.OTHER

        normalized = raw_type.lower()
        if "html" in normalized:
            return IssueCategory.HTML
        if "meta" in normalized:
            return IssueCategory.META
        if "redirect" in normalized:
            return IssueCategory.REDIRECT
        if "link" in normalized:
            return IssueCategory.LINKS
        if "image" in normalized:
            return IssueCategory.IMAGES
        if "social" in normalized:
            return IssueCategory.SOCIAL
        if "content" in normalized or "quality" in normalized:
            return IssueCategory.CONTENT
        if "performance" in normalized or "speed" in normalized:
            return IssueCategory.PERFORMANCE
        if "resource" in normalized or "javascript" in normalized or "css" in normalized:
            return IssueCategory.RESOURCES
        if "lang" in normalized or "locale" in normalized or "hreflang" in normalized:
            return IssueCategory.LOCALIZATION
        return IssueCategory.OTHER

    @staticmethod
    def _map_issue_severity(raw_level: Optional[str]) -> IssueSeverity:
        if not raw_level:
            return IssueSeverity.WARNING

        normalized = raw_level.lower()
        if normalized in {"critical", "error", "errors", "very_bad"}:
            return IssueSeverity.ERROR
        if normalized in {"warning", "warnings", "neutral"}:
            return IssueSeverity.WARNING
        if normalized in {"notice", "notices"}:
            return IssueSeverity.NOTICE
        if normalized in {"info", "informational"}:
            return IssueSeverity.INFO
        return IssueSeverity.WARNING

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
    def get_overview_metrics(
        self,
        project_id: int,
        crawls: Optional[List[Crawl]] = None,
        target_crawl: Optional[Crawl] = None,
    ) -> OverviewMetrics:
        """Get overview metrics for a project.

        Fetches from multiple API endpoints and combines results.

        Args:
            project_id: Ahrefs project ID

        Returns:
            OverviewMetrics model
        """
        if crawls is None:
            crawls = self.list_crawls(project_id)
        if target_crawl is None:
            target_crawl = self._select_report_crawl(crawls)
        if target_crawl is None:
            return OverviewMetrics()

        raw_metrics = {}
        timestamp_context = self._build_timestamp_context(crawls, target_crawl.id)
        if timestamp_context is None:
            return OverviewMetrics()

        # Latest crawl details now expose the most reliable summary counts.
        try:
            raw_metrics["crawl"] = self.get_crawl_details(project_id, target_crawl.id)
        except ClientError:
            raw_metrics["crawl"] = {}

        try:
            def fetch_health():
                return self.fetch_api(
                    "saCrawlsHealthscore",
                    {
                        "project_id": str(project_id),
                        "global_filter_id": None,
                        "timestamps": self._build_healthscore_timestamps(crawls, target_crawl.id),
                    },
                )

            raw_metrics["health"] = self._retry_fetch(fetch_health, operation_name="health_score")
        except ClientError:
            raw_metrics["health"] = {}

        try:
            def fetch_overview():
                return self.fetch_api(
                    "saOverviewIssueCharts",
                    {
                        "project_id": str(project_id),
                        "timestamp": timestamp_context,
                        "global_filter_id": None,
                    },
                )

            raw_metrics["overview"] = self._retry_fetch(
                fetch_overview, operation_name="overview_charts"
            )
        except ClientError:
            raw_metrics["overview"] = []

        crawl_counts = raw_metrics.get("crawl", {}).get("counts", {})
        charts = raw_metrics.get("overview") or []

        issues_chart = next(
            (chart for chart in charts if chart.get("id") == "issues-types"),
            {},
        )
        issue_buckets = issues_chart.get("buckets", [])
        bucket_counts = {
            bucket.get("key"): bucket.get("count", 0)
            for bucket in issue_buckets
        }

        health_scores = raw_metrics.get("health", {}).get("healthscores", [])
        health_score = None
        for timestamp, score in health_scores:
            if timestamp == target_crawl.crawl_date:
                health_score = score
                break
        if health_score is None and health_scores:
            health_score = health_scores[0][1]

        return OverviewMetrics(
            health_score=health_score,
            pages_crawled=crawl_counts.get("crawled", 0),
            total_issues=issues_chart.get("total", 0),
            errors_count=bucket_counts.get("critical", 0),
            warnings_count=bucket_counts.get("warning", 0),
            notices_count=bucket_counts.get("notice", 0),
            internal_urls=crawl_counts.get("total_requests_internal", 0),
            external_urls=crawl_counts.get("total_requests_external", 0),
            raw_metrics=raw_metrics,
        )

    @cached
    def get_project_issues(
        self,
        project_id: int,
        severity_filter: Optional[List[str]] = None,
        crawls: Optional[List[Crawl]] = None,
        target_crawl: Optional[Crawl] = None,
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
        if crawls is None:
            crawls = self.list_crawls(project_id)
        if target_crawl is None:
            target_crawl = self._select_report_crawl(crawls)
        if target_crawl is None:
            return IssuesByCategory()

        timestamp_context = self._build_timestamp_context(crawls, target_crawl.id)
        if timestamp_context is None:
            return IssuesByCategory()

        def fetch():
            return self.fetch_api(
                "saGetProjectIssues",
                {
                    "project_id": str(project_id),
                    "timestamp": timestamp_context,
                    "global_filter_id": None,
                },
            )

        data = self._retry_fetch(fetch, operation_name="get_project_issues")

        # Group issues by category
        issues_by_cat = {cat.value: [] for cat in IssueCategory}

        if isinstance(data, dict):
            items = data.get("issues", data.get("items", []))
        elif isinstance(data, list):
            items = data
        else:
            items = []

        for item in items:
            issue_payload = item.get("issue", {})
            props = issue_payload.get("props", {})
            raw_level = ((props.get("level") or ["warning"])[0] or "warning")
            severity = self._map_issue_severity(raw_level)
            if severity.value not in severity_filter:
                continue

            issue = create_issue(
                {
                    "id": issue_payload.get("issue_id", ""),
                    "title": props.get("name", "Unknown issue"),
                    "category": self._map_issue_category(((props.get("typ") or [None])[0])),
                    "severity": severity.value,
                    "description": self._extract_markdown_text(props.get("description")),
                    "count": item.get("count", 0),
                }
            )
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
            if cached and not cached.errors:
                return cached

        previous_cache_enabled = os.environ.get("CACHE_ENABLED")
        if refresh:
            os.environ["CACHE_ENABLED"] = "false"

        try:
            errors = []
            crawl_date = ""
            crawl_id = ""
            domain = None
            crawls: List[Crawl] = []
            report_crawl: Optional[Crawl] = None

            # Get project info
            try:
                project = self.get_project(project_id)
                domain = project.domain
            except ClientError as e:
                errors.append(f"get_project: {e}")

            # Get crawls and latest crawl info
            try:
                crawls = self.list_crawls(project_id)
                report_crawl = self._select_report_crawl(crawls)
                if report_crawl:
                    crawl_date = report_crawl.crawl_date
                    crawl_id = report_crawl.id
            except ClientError as e:
                errors.append(f"list_crawls: {e}")

            # Get overview metrics
            try:
                overview = self.get_overview_metrics(
                    project_id,
                    crawls=crawls,
                    target_crawl=report_crawl,
                )
            except ClientError as e:
                errors.append(f"get_overview_metrics: {e}")
                overview = OverviewMetrics()

            # Get issues by category
            try:
                issues = self.get_project_issues(
                    project_id,
                    crawls=crawls,
                    target_crawl=report_crawl,
                )
            except ClientError as e:
                errors.append(f"get_project_issues: {e}")
                issues = IssuesByCategory()
        finally:
            if refresh:
                if previous_cache_enabled is None:
                    os.environ.pop("CACHE_ENABLED", None)
                else:
                    os.environ["CACHE_ENABLED"] = previous_cache_enabled

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
        if not errors:
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
