"""Raptive client making publisher-API calls from the dashboard page.

The browser login persists the dashboard session. Every API call runs inside
that dashboard page so it carries the AWS WAF token the page earned.
"""
import json
from typing import Dict, List, Optional, Any

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .config import get_config
from .models import (
    DashboardSummary,
    DateBounds,
    EarningsOverview,
    DeviceEarnings,
    TrafficSource,
    DeviceTraffic,
    DeviceType,
    PagePerformance,
    TrafficSourcePerformance,
    CountryPerformance,
    CategoryPerformance,
    BrandSafetyPage,
    AdNetworkEarnings,
)
from .dates import parse_period


class RaptiveClient:
    """Client for interacting with Raptive via browser auth and API calls."""

    BASE_URL = "https://dashboard.raptive.com"
    API_BASE_URL = "https://publisher-api.raptive.com"

    def __init__(self, config=None):
        """Initialize Raptive client.

        Args:
            config: Optional Config instance. If not provided, uses get_config().
        """
        self.config = config or get_config()
        # Override with config values
        self.BASE_URL = self.config.base_url
        self.API_BASE_URL = self.config.api_base_url

    @property
    def site_id(self) -> str:
        """Get the site ID from config or raise error."""
        site_id = self.config.site_id
        if not site_id:
            raise ClientError(
                "Site ID not configured. Set SITE_ID in .env file."
            )
        return site_id

    # ==================== API Helpers ====================

    # Runs inside the dashboard page. publisher-api sits behind AWS WAF: a
    # request without a valid aws-waf-token gets a 202 challenge, so it must
    # go through the dashboard's own AwsWafIntegration.fetch, which attaches
    # the token minted by the page's silent WAF challenge. The Bearer token is
    # the dashboard's localStorage `token`, exactly as the dashboard sends it.
    _FETCH_JS = """async ([url, waitMs]) => {
        const deadline = Date.now() + waitMs;
        while (!window.AwsWafIntegration) {
            if (Date.now() > deadline) {
                return {error: 'AWS WAF integration never loaded on the dashboard page: '
                    + (document.body ? document.body.innerText.slice(0, 200) : '')};
            }
            await new Promise(r => setTimeout(r, 250));
        }
        const token = localStorage.getItem('token');
        if (!token) return {error: 'no_token'};
        try {
            const r = await window.AwsWafIntegration.fetch(url, {
                headers: {Authorization: 'Bearer ' + token, Accept: 'application/json'},
            });
            return {status: r.status, body: await r.text()};
        } catch (e) {
            return {error: String(e)};
        }
    }"""
    _WAF_WAIT_MS = 30000

    _MAX_PAGE_SIZE = 500  # publisher-api rejects page[size] > 500 with HTTP 400

    def _fetch(self, page, endpoint: str) -> Any:
        """Run one publisher-API GET inside the dashboard page; return parsed JSON."""
        url = f"{self.API_BASE_URL}{endpoint}"
        result = page.evaluate(self._FETCH_JS, [url, self._WAF_WAIT_MS])
        if not isinstance(result, dict):
            raise ClientError(f"API request failed for {endpoint}: no result from dashboard page")
        if result.get("error") == "no_token":
            raise ClientError("No JWT token found in saved browser auth state. Run 'raptive auth login' again.")
        if "error" in result:
            raise ClientError(f"API request failed for {endpoint}: {result['error']}")
        status = result["status"]
        if status == 401:
            raise ClientError("Session expired. Run 'raptive auth login' again.")
        if status != 200:
            raise ClientError(
                f"API request failed for {endpoint}: HTTP {status} returned for {url}: {result['body'][:300]}"
            )
        try:
            return json.loads(result["body"])
        except json.JSONDecodeError as exc:
            raise ClientError(f"API returned invalid JSON for {endpoint}.") from exc

    def _api_call(self, endpoint: str) -> Any:
        """Call one publisher-API endpoint from the authenticated dashboard page."""
        browser = self.config.get_browser()
        try:
            return self._fetch(browser.get_page(self.BASE_URL), endpoint)
        finally:
            browser.close()

    def _api_pages(self, endpoint: str, limit: int) -> List[Dict[str, Any]]:
        """Collect up to ``limit`` ``data`` records across page[number] pages.

        ``endpoint`` must already carry a query string.
        """
        size = min(limit, self._MAX_PAGE_SIZE)
        records: List[Dict[str, Any]] = []
        number = 1
        browser = self.config.get_browser()
        try:
            page = browser.get_page(self.BASE_URL)
            while number is not None and len(records) < limit:
                data = self._fetch(page, f"{endpoint}&page[size]={size}&page[number]={number}")
                records.extend(data["data"])
                number = data["meta"]["page"]["next"]
        finally:
            browser.close()
        return records[:limit]

    # ==================== Dashboard Methods ====================

    @cached
    def get_dashboard_summary(
        self,
        start_date: str,
        end_date: str,
    ) -> DashboardSummary:
        """Get dashboard summary metrics for a date range."""
        endpoint = f"/api/v2/sites/{self.site_id}/dashboard/summary/{start_date}/{end_date}"
        data = self._api_call(endpoint)

        return DashboardSummary(
            start_date=start_date,
            end_date=end_date,
            earnings=data.get("earnings", 0),
            rpm=data.get("rpm"),
            page_rpm=data.get("pageRpm"),
            sessions=data.get("sessions"),
            pageviews=data.get("pageviews"),
        )

    @cached
    def get_date_bounds(self) -> DateBounds:
        """Get the date bounds for available data."""
        endpoint = f"/api/v2/sites/{self.site_id}/dashboard/dateBounds"
        data = self._api_call(endpoint)
        try:
            # Analytics (pageview) bounds: the range every report can cover.
            bounds = data["data"]["analyticsDateBounds"]["range"]
            return DateBounds(earliest_date=bounds["startDate"], latest_date=bounds["endDate"])
        except (KeyError, TypeError) as exc:
            raise ClientError(f"Unexpected dateBounds response shape: missing {exc}") from exc

    # ==================== Earnings Methods ====================

    @cached
    def get_earnings_overview(
        self,
        start_date: str,
        end_date: str,
        aggregation: str = "daily",
    ) -> List[EarningsOverview]:
        """Get detailed earnings data for a date range."""
        endpoint = f"/api/v2/sites/{self.site_id}/earnings/overview/{start_date}/{end_date}?aggregationPeriod={aggregation}"
        data = self._api_call(endpoint)

        results = []
        for item in data.get("data", []):
            results.append(EarningsOverview(
                date=item.get("date", ""),
                earnings=item.get("earnings", 0),
                sessions=item.get("sessions"),
                pageviews=item.get("pageviews"),
                rpm=item.get("rpm"),
                page_rpm=item.get("pageRpm"),
            ))

        return results

    @cached
    def get_device_earnings(self) -> List[DeviceEarnings]:
        """Get earnings breakdown by device type."""
        endpoint = f"/api/v2/sites/{self.site_id}/dashboard/byDevice"
        data = self._api_call(endpoint)

        results = []
        for item in data:
            device_type = item.get("type", "Unknown")
            results.append(DeviceEarnings(
                device=DeviceType(device_type),
                earnings=item.get("earnings", 0),
                rpm=item.get("rpm"),
                sessions=item.get("sessions"),
                pageviews=item.get("pageviews"),
            ))

        return results

    # ==================== Traffic Methods ====================

    @cached
    def get_traffic_sources(self) -> List[TrafficSource]:
        """Get traffic breakdown by source."""
        start_date, end_date = parse_period("last30d")

        endpoint = f"/api/v2/sites/{self.site_id}/dashboard/trafficBySource"
        data = self._api_call(endpoint)

        results = []
        for item in data:
            results.append(TrafficSource(
                start_date=start_date,
                end_date=end_date,
                source=item.get("source", "unknown"),
                sessions=item.get("sessions", 0),
                earnings=item.get("earnings"),
                rpm=item.get("rpm"),
            ))

        return results

    @cached
    def get_device_traffic(self) -> List[DeviceTraffic]:
        """Get traffic breakdown by device type."""
        endpoint = f"/api/v2/sites/{self.site_id}/dashboard/byDevice"
        data = self._api_call(endpoint)

        results = []
        for item in data:
            device_type = item.get("type", "Unknown")
            sessions = item.get("sessions", 0)
            pageviews = item.get("pageviews", 0)
            pps = pageviews / sessions if sessions > 0 else None
            results.append(DeviceTraffic(
                device=DeviceType(device_type),
                sessions=sessions,
                pageviews=pageviews,
                pages_per_session=pps,
            ))

        return results

    # ==================== Reports Methods ====================

    @cached
    def get_page_performance(
        self,
        start_date: str,
        end_date: str,
        limit: int = 50,
        min_pageviews: Optional[int] = None,
        max_pageviews: Optional[int] = None,
        min_rpm: Optional[float] = None,
        max_rpm: Optional[float] = None,
        search: Optional[str] = None,
    ) -> List[PagePerformance]:
        """Get performance metrics by page."""
        endpoint = f"/api/v2/sites/{self.site_id}/reports/rpmByPage/{start_date}/{end_date}?sort=-pageviews"

        if min_pageviews is not None:
            endpoint += f"&filter[pageviews][min]={min_pageviews}"
        if max_pageviews is not None:
            endpoint += f"&filter[pageviews][max]={max_pageviews}"
        if min_rpm is not None:
            endpoint += f"&filter[rpm][min]={min_rpm}"
        if max_rpm is not None:
            endpoint += f"&filter[rpm][max]={max_rpm}"
        if search:
            endpoint += f"&filter[pagePath]=~{search}"

        results = []
        for item in self._api_pages(endpoint, limit):
            cpm = item.get("cpm", {})
            viewability = item.get("viewability", {})
            ipp = item.get("impressionsPerPageview", {})

            results.append(PagePerformance(
                start_date=start_date,
                end_date=end_date,
                page_url=item.get("pageUrl"),
                pageviews=item.get("pageviews", 0),
                earnings=item.get("earnings", 0),
                rpm=item.get("rpm", 0),
                impressions=item.get("impressions"),
                cpm=cpm.get("value") if isinstance(cpm, dict) else cpm,
                viewability=viewability.get("value") if isinstance(viewability, dict) else viewability,
                impressions_per_pageview=ipp.get("value") if isinstance(ipp, dict) else ipp,
                author=item.get("author"),
                modified_date=item.get("modifiedDate"),
            ))

        return results

    @cached
    def get_traffic_source_performance(
        self,
        start_date: str,
        end_date: str,
    ) -> List[TrafficSourcePerformance]:
        """Get performance metrics by traffic source."""
        endpoint = f"/api/v2/sites/{self.site_id}/reports/rpmByTraffic/{start_date}/{end_date}"
        data = self._api_call(endpoint)

        results = []
        for item in data.get("data", []):
            results.append(TrafficSourcePerformance(
                start_date=start_date,
                end_date=end_date,
                traffic_source=item.get("trafficSource", "unknown"),
                earnings=item.get("earnings", 0),
                pageviews=item.get("pageviews", 0),
                sessions=item.get("sessions", 0),
                rpm=item.get("rpm", 0),
                rps=item.get("rps", 0),
                pps=item.get("pps", 0),
            ))

        return results

    @cached
    def get_country_performance(
        self,
        start_date: str,
        end_date: str,
    ) -> List[CountryPerformance]:
        """Get performance metrics by country."""
        endpoint = f"/api/v2/sites/{self.site_id}/reports/byCountry/{start_date}/{end_date}"
        data = self._api_call(endpoint)

        results = []
        for item in data.get("data", []):
            results.append(CountryPerformance(
                start_date=start_date,
                end_date=end_date,
                country=item.get("country", "unknown"),
                earnings=item.get("earnings", 0),
                pageviews=item.get("pageviews", 0),
                sessions=item.get("sessions", 0),
                rpm=item.get("rpm", 0),
                rps=item.get("rps", 0),
                impressions=item.get("impressions"),
                cpm=item.get("cpm"),
                impressions_per_pageview=item.get("impressionsPerPageview"),
            ))

        return results

    @cached
    def get_category_performance(
        self,
        start_date: str,
        end_date: str,
    ) -> List[CategoryPerformance]:
        """Get performance metrics by category."""
        endpoint = f"/api/v2/sites/{self.site_id}/reports/byCategory/{start_date}/{end_date}"
        data = self._api_call(endpoint)

        results = []
        for item in data.get("data", []):
            results.append(CategoryPerformance(
                start_date=start_date,
                end_date=end_date,
                category=item.get("category", "unknown"),
                earnings=item.get("earnings", 0),
                pageviews=item.get("pageviews", 0),
                sessions=item.get("sessions", 0),
                rpm=item.get("rpm", 0),
                rps=item.get("rps", 0),
                cpm=item.get("cpm"),
                num_posts=item.get("numPosts"),
            ))

        return results

    @cached
    def get_brand_safety(
        self,
        limit: int = 50,
    ) -> List[BrandSafetyPage]:
        """Get brand safety assessments for pages."""
        rating_filters = "&".join(
            f"filter[!normal]={rating}"
            for rating in ("alc", "adt", "drg", "hat", "dlm", "off", "vio")
        )
        endpoint = (
            f"/api/v2/sites/{self.site_id}/brandSafetyByUrl?"
            f"{rating_filters}&filter[hasRating]=true&sort=-pageviews"
        )

        results = []
        for item in self._api_pages(endpoint, limit):
            results.append(BrandSafetyPage(
                pagepath=item.get("pagePath", ""),
                date=item.get("date", ""),
                pageviews=item.get("pageviews", 0),
                rpm=item.get("rpm", 0),
                cpm=item.get("cpm", 0),
                alc=item.get("alc", "normal"),
                adt=item.get("adt", "normal"),
                dlm=item.get("dlm", "normal"),
                drg=item.get("drg", "normal"),
                hat=item.get("hat", "normal"),
                off=item.get("off", "normal"),
                sam=item.get("sam", "normal"),
                vio=item.get("vio", "normal"),
                nr=item.get("nr", "normal"),
            ))

        return results

    @cached
    def get_ad_network_earnings(self) -> List[AdNetworkEarnings]:
        """Get earnings breakdown by ad network source."""
        endpoint = f"/api/v2/sites/{self.site_id}/earnings/byAdNetworkSource"
        data = self._api_call(endpoint)

        results = []
        for item in data.get("data", []):
            results.append(AdNetworkEarnings(
                ad_network=item.get("adNetwork", "unknown"),
                year=item.get("year", 0),
                month=item.get("month", 0),
                earnings=item.get("earnings", 0),
            ))

        return results


# ==================== Module-level Singleton ====================

_client: Optional[RaptiveClient] = None


def get_client() -> RaptiveClient:
    """Get or create the global Raptive client instance."""
    global _client
    if _client is None:
        _client = RaptiveClient()
    return _client
