"""10Web API client."""

from typing import Any, Dict, List, Optional

import requests

from cli_tools_shared.exceptions import ClientError

from .config import get_config
from .filters import apply_filters, apply_limit, validate_filters
from .models import (
    SubdomainCheckResult,
    Website,
    WebsiteDetail,
    create_subdomain_check_result,
    create_website,
    create_website_detail,
)


class TenwebClient:
    """Client for the documented 10Web API."""

    def __init__(self):
        self.config = get_config()
        api_key = self.config.api_key
        if not api_key:
            raise ClientError("Missing credentials: api_key. Run 'tenweb auth login' to authenticate.")

        self.base_url = self.config.base_url.rstrip("/")
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": api_key,
        }

    def _make_request(
        self,
        method: str,
        endpoint: str,
        *,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run an API request and return the decoded JSON body."""
        url = f"{self.base_url}{endpoint}"

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                json=data,
                params=params,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise ClientError(f"Request failed: {exc}") from exc

        if response.status_code >= 400:
            message = response.text or f"HTTP {response.status_code}"
            try:
                payload = response.json()
            except ValueError:
                payload = None

            if isinstance(payload, dict):
                message = (
                    payload.get("message")
                    or payload.get("error")
                    or payload.get("msg")
                    or message
                )
            raise ClientError(message)

        try:
            return response.json()
        except ValueError as exc:
            raise ClientError("10Web returned a non-JSON response.") from exc

    def list_websites(self, limit: int = 100, filters: Optional[List[str]] = None) -> List[Website]:
        """List websites available to the current account."""
        validate_filters(filters or [])
        payload = self._make_request("GET", "/v1/account/websites")
        websites = payload.get("data")
        if not isinstance(websites, list):
            raise ClientError("10Web returned an invalid websites list payload.")

        rows = [self._normalize_website(website) for website in websites]
        if filters:
            rows = apply_filters(rows, filters)
        return [create_website(row) for row in apply_limit(rows, limit)]

    def get_website(self, website_id: int) -> WebsiteDetail:
        """Get instance details for a website."""
        payload = self._make_request("GET", f"/v1/hosting/websites/{website_id}/instance-info")
        status = payload.get("status")
        data = payload.get("data")
        if not isinstance(status, str) or not isinstance(data, dict):
            raise ClientError("10Web returned an invalid website detail payload.")

        return create_website_detail(
            {
                "website_id": website_id,
                "status": status,
                "ip": data.get("ip"),
                "location": data.get("location"),
                "region": data.get("region"),
            }
        )

    def check_subdomain(self, subdomain: str) -> SubdomainCheckResult:
        """Check whether a subdomain is available."""
        payload = self._make_request(
            "POST",
            "/v1/hosting/websites/subdomain/check",
            data={"subdomain": subdomain},
        )
        status = payload.get("status")
        message = payload.get("message")
        if not isinstance(status, str) or not isinstance(message, str):
            raise ClientError("10Web returned an invalid subdomain check payload.")
        return create_subdomain_check_result({"status": status, "message": message})

    @staticmethod
    def _normalize_website(website: Dict[str, Any]) -> Dict[str, Any]:
        """Map the account websites payload to the CLI model."""
        return {
            "id": website.get("id"),
            "name": website.get("name"),
            "site_url": website.get("site_url"),
            "admin_url": website.get("admin_url"),
            "site_title": website.get("site_title"),
            "website_hash": website.get("website_hash"),
            "type": website.get("type"),
            "created_at": website.get("created_at"),
            "updated_at": website.get("updated_at"),
        }


_client: Optional[TenwebClient] = None


def get_client() -> TenwebClient:
    """Get or create the global 10Web client."""
    global _client
    if _client is None:
        _client = TenwebClient()
    return _client
