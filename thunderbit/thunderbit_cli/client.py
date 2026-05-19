"""Thunderbit API client."""
from typing import Any, Dict, Optional

import requests

from cli_tools_shared.exceptions import ClientError

from .config import get_config
from .models import Item, ItemDetail, create_item, create_item_detail


class ThunderbitClient:
    """Client for the Thunderbit extraction API."""

    def __init__(self):
        self.config = get_config()
        token = self.config.api_key or self.config.access_token
        if not token:
            raise ClientError("Missing credentials: api_key. Run 'thunderbit auth login' to authenticate.")
        self.base_url = self.config.base_url.rstrip("/")
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

    def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run a Thunderbit API request and return the decoded payload."""
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                json=data,
                timeout=60,
            )
        except requests.RequestException as exc:
            raise ClientError(f"Request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ClientError("Thunderbit returned a non-JSON response.") from exc

        if response.status_code >= 400:
            message = payload.get("message") or response.text or f"HTTP {response.status_code}"
            raise ClientError(message)

        if not isinstance(payload, dict):
            raise ClientError("Thunderbit returned an unexpected response shape.")
        return payload

    def distill_url(self, url: str) -> Item:
        """Run the Thunderbit Markdown distillation endpoint."""
        payload = self._request("POST", "/distill", data={"url": url})
        return create_item(
            {
                "id": url,
                "name": url,
                "output_kind": "markdown",
                "metadata": payload,
            }
        )

    def extract_url(self, url: str, schema: Dict[str, Any]) -> ItemDetail:
        """Run the Thunderbit JSON extraction endpoint."""
        payload = self._request("POST", "/extract", data={"url": url, "schema": schema})
        return create_item_detail(
            {
                "id": url,
                "name": url,
                "output_kind": "json",
                "metadata": payload,
            }
        )


_client: Optional[ThunderbitClient] = None


def get_client() -> ThunderbitClient:
    """Get or create the global Thunderbit client."""
    global _client
    if _client is None:
        _client = ThunderbitClient()
    return _client
