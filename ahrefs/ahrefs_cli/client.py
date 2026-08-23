"""Ahrefs client using browser automation and internal v4 API.

This client wraps AhrefsBrowser with site-specific methods for
Ahrefs Site Audit operations. Uses the internal v4 API endpoints
via fetch_json() for authenticated requests.
"""
import os
import random
import re
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Optional
from urllib.parse import quote

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.data_cache import cached

from .config import get_config
from .browser import AhrefsBrowser, BrowserAutomationError
from .cache import cache_exists, get_cached_report, save_cached_report
from .models import (
    Crawl,
    CrawlStatus,
    DomainOverview,
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
    TopPage,
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


# ==================== Site Explorer configuration ====================
#
# Site Explorer data is read from the authenticated Site Explorer SPA the same
# way site-audit reads the authenticated audit UI: navigate with the shared
# browser session, then extract from the rendered page. Ahrefs' Site Explorer
# has no public API on this account tier, so this mirrors the site-audit engine
# (browser/session handling, retry, @cached, output) rather than adding a new
# auth path.
#
# Live-validated against an authenticated session: the overview and top-pages
# page paths below, JS_EXTRACT_OVERVIEW, and the header-index-aware
# JS_EXTRACT_TOP_PAGES all return correct data headless once the browser
# presents the matched real-Chrome UA (see config.browser_user_agent). Ahrefs
# auto-appends the projectId to these target paths after navigation.

# Visible metric labels Ahrefs renders on the Site Explorer overview. Extraction
# anchors on this label text (case-insensitive) rather than obfuscated CSS
# classes, so it survives class-name churn.
SE_OVERVIEW_LABELS = {
    "domain_rating": ["Domain Rating", "DR"],
    "organic_traffic": ["Organic traffic", "Traffic"],
    "organic_keywords": ["Organic keywords", "Keywords"],
    "referring_domains": ["Referring domains", "Ref. domains", "Ref domains"],
    "backlinks": ["Backlinks"],
}

SE_OVERVIEW_PATH = "/site-explorer/overview?target={target}"
SE_TOP_PAGES_PATH = "/site-explorer/top-pages?target={target}"

# Extract label -> raw value text from the overview metric cards. Returns a flat
# object of {metric_key: raw_text | null}. Raises nothing; missing metrics are
# reported as null so the caller can decide whether the whole extraction failed.
JS_EXTRACT_OVERVIEW = r"""
(labelMap) => {
    const norm = (s) => (s || "").replace(/\s+/g, " ").trim();
    const isNumeric = (s) => /^[<>]?\s*\d[\d.,]*\s*[KMB%]?$/i.test(norm(s));
    const nodes = Array.from(document.querySelectorAll("body *"))
        .filter((el) => el.children.length === 0 && norm(el.textContent));

    const findValueFor = (labels) => {
        for (const el of nodes) {
            const text = norm(el.textContent);
            const matched = labels.some((label) => text.toLowerCase() === label.toLowerCase());
            if (!matched) continue;
            // Walk up a few ancestors and look for the first numeric-looking leaf.
            let scope = el;
            for (let depth = 0; depth < 4 && scope; depth++) {
                const leaves = Array.from(scope.querySelectorAll("*"))
                    .filter((n) => n.children.length === 0 && norm(n.textContent));
                for (const leaf of leaves) {
                    const val = norm(leaf.textContent);
                    if (leaf !== el && isNumeric(val)) return val;
                }
                scope = scope.parentElement;
            }
        }
        return null;
    };

    const out = {};
    for (const key of Object.keys(labelMap)) {
        out[key] = findValueFor(labelMap[key]);
    }
    return out;
}
"""

# Extract the top-pages table as [{url, traffic}]. Header-index-aware: the live
# table header order is URL, Page type, UR, Traffic, Value, Ref. domains,
# Keywords, ... so the first numeric cell in a row is UR, not Traffic. Read the
# header row, locate the column whose header text is "Traffic" (case-insensitive,
# trimmed), then read each data row's cell at that same column index.
JS_EXTRACT_TOP_PAGES = r"""
(limit) => {
    const norm = (s) => (s || "").replace(/\s+/g, " ").trim();
    const cellsOf = (row) =>
        Array.from(row.querySelectorAll(":scope > th, :scope > td, :scope > [role='columnheader'], :scope > [role='cell'], :scope > [role='gridcell']"));

    const rows = Array.from(document.querySelectorAll("tr, [role='row']"));

    // Find the Traffic column index from the header row.
    let trafficIndex = -1;
    for (const row of rows) {
        const cells = cellsOf(row);
        if (!cells.length) continue;
        const idx = cells.findIndex((c) => norm(c.textContent).toLowerCase() === "traffic");
        if (idx !== -1) { trafficIndex = idx; break; }
    }

    const out = [];
    for (const row of rows) {
        const link = row.querySelector("a[href^='http']");
        if (!link) continue;
        const url = norm(link.getAttribute("href"));
        if (!url) continue;
        const cells = cellsOf(row);
        let traffic = null;
        if (trafficIndex !== -1 && cells[trafficIndex]) {
            const val = norm(cells[trafficIndex].textContent);
            if (val) traffic = val;
        }
        out.push({ url, traffic });
        if (out.length >= limit) break;
    }
    return out;
}
"""


_METRIC_SUFFIXES = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


@contextmanager
def cache_disabled(active: bool) -> Iterator[None]:
    """Temporarily disable @cached reads/writes when ``active`` is True.

    Mirrors the CACHE_ENABLED toggle used by ``get_site_audit`` so a ``--refresh``
    flag forces a fresh fetch without permanently changing cache config.
    """
    if not active:
        yield
        return
    previous = os.environ.get("CACHE_ENABLED")
    os.environ["CACHE_ENABLED"] = "false"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("CACHE_ENABLED", None)
        else:
            os.environ["CACHE_ENABLED"] = previous


def _clean_metric_text(value: Optional[str]) -> Optional[str]:
    """Strip whitespace and comparison prefixes from a raw metric string."""
    if value is None:
        return None
    text = str(value).strip().lstrip("<>").strip()
    return text or None


def _parse_metric_float(value: Optional[str]) -> Optional[float]:
    """Parse a plain numeric metric (e.g. Domain Rating '72') to float."""
    text = _clean_metric_text(value)
    if text is None:
        return None
    text = text.rstrip("%").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _parse_metric_int(value: Optional[str]) -> Optional[int]:
    """Parse an abbreviated count metric ('1.2K', '3.4M', '45,678') to int."""
    text = _clean_metric_text(value)
    if text is None:
        return None
    text = text.replace(",", "").strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([KMB]?)", text, flags=re.IGNORECASE)
    if not match:
        return None
    number = float(match.group(1))
    suffix = match.group(2).lower()
    if suffix:
        number *= _METRIC_SUFFIXES[suffix]
    return int(round(number))


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

        with cache_disabled(refresh):
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

    # ==================== Site Explorer Methods ====================

    def _extract_from_page(self, path: str, js: str, js_arg: Any) -> Any:
        """Navigate to a Site Explorer page and run a DOM extraction script.

        Shared engine for the Site Explorer extractors: authenticate, navigate
        with the persistent session, wait for the SPA to settle, then evaluate
        ``js`` with ``js_arg`` and return the raw result.
        """
        self.ensure_authenticated()
        self.navigate(path)
        page = self.browser.get_page()
        # Best-effort settle: BrowserHarnessService exposes wait_for_network_idle
        # (returns False on timeout for SPAs that keep long-poll connections
        # open); a short fixed wait then lets late-rendered metric cards paint.
        page.wait_for_network_idle(timeout=20.0)
        page.wait_for_timeout(2000)
        return page.evaluate(js, js_arg)

    def _extract_overview(self, domain: str) -> Dict[str, Optional[str]]:
        """Navigate to the Site Explorer overview and extract raw metric text."""
        path = SE_OVERVIEW_PATH.format(target=quote(domain, safe=""))
        raw = self._extract_from_page(path, JS_EXTRACT_OVERVIEW, SE_OVERVIEW_LABELS)
        if not isinstance(raw, dict):
            raise ClientError(f"Unexpected overview extraction result: {raw!r}")
        return raw

    def _extract_top_pages(self, domain: str, limit: int) -> List[Dict[str, Optional[str]]]:
        """Navigate to the Site Explorer top-pages report and extract rows."""
        path = SE_TOP_PAGES_PATH.format(target=quote(domain, safe=""))
        rows = self._extract_from_page(path, JS_EXTRACT_TOP_PAGES, limit)
        if not isinstance(rows, list):
            raise ClientError(f"Unexpected top-pages extraction result: {rows!r}")
        return rows

    @cached
    def get_domain_overview(self, domain: str) -> DomainOverview:
        """Get Site Explorer overview metrics for a domain.

        Returns Domain Rating, estimated monthly organic traffic, ranking
        organic keywords, referring domains, and backlinks.

        Args:
            domain: Target domain (e.g. "example.com").

        Returns:
            DomainOverview model.
        """

        def fetch():
            return self._extract_overview(domain)

        raw = self._retry_fetch(fetch, operation_name="get_domain_overview")

        overview = DomainOverview(
            domain=domain,
            domain_rating=_parse_metric_float(raw.get("domain_rating")),
            organic_traffic=_parse_metric_int(raw.get("organic_traffic")),
            organic_keywords=_parse_metric_int(raw.get("organic_keywords")),
            referring_domains=_parse_metric_int(raw.get("referring_domains")),
            backlinks=_parse_metric_int(raw.get("backlinks")),
        )

        # Fail loudly if the extraction found none of the expected metrics — that
        # means the page structure changed, the session is not authenticated, or
        # the domain is invalid, not that every metric is genuinely zero.
        if all(
            getattr(overview, field) is None
            for field in ("domain_rating", "organic_traffic", "organic_keywords", "referring_domains", "backlinks")
        ):
            raise ClientError(
                "Could not extract any Site Explorer overview metrics for "
                f"'{domain}'. Verify the session is authenticated (ahrefs auth login) "
                "and the domain is valid."
            )

        return overview

    @cached
    def get_top_pages(self, domain: str, limit: int = 100) -> List[TopPage]:
        """Get top pages by organic traffic for a domain.

        Args:
            domain: Target domain (e.g. "example.com").
            limit: Maximum number of pages to read from the report.

        Returns:
            List of TopPage models (URL + estimated organic traffic per page).
        """

        def fetch():
            return self._extract_top_pages(domain, limit)

        rows = self._retry_fetch(fetch, operation_name="get_top_pages")

        pages = []
        for row in rows:
            url = (row.get("url") or "").strip()
            if not url:
                continue
            pages.append(TopPage(url=url, traffic=_parse_metric_int(row.get("traffic"))))
        return pages


# ==================== Module-level Singleton ====================

_client: Optional[AhrefsClient] = None


def get_client() -> AhrefsClient:
    """Get or create the global Ahrefs client instance."""
    global _client
    if _client is None:
        _client = AhrefsClient()
    return _client
