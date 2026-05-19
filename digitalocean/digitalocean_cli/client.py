"""DigitalOcean API client."""
import fnmatch
from typing import Any, Dict, List, Optional

import requests

from cli_tools_shared.exceptions import ClientError

from .config import get_config
from .models import Item, ItemDetail, create_item, create_item_detail


class DigitaloceanClient:
    """Client for the DigitalOcean droplets API surface."""

    def __init__(self):
        self.config = get_config()
        token = self.config.personal_access_token or self.config.access_token
        if not token:
            raise ClientError(
                "Missing credentials: personal_access_token. Run 'digitalocean auth login' to authenticate."
            )

        self.base_url = self.config.base_url.rstrip("/")
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run an API request and return the decoded JSON body."""
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                params=params,
                json=data,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise ClientError(f"Request failed: {exc}") from exc

        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            message = payload.get("message") or response.text or f"HTTP {response.status_code}"
            raise ClientError(message)

        try:
            return response.json()
        except ValueError as exc:
            raise ClientError("DigitalOcean returned a non-JSON response.") from exc

    def _normalize_droplet(self, droplet: Dict[str, Any], detailed: bool = False) -> Dict[str, Any]:
        """Map a DigitalOcean droplet payload to the CLI model."""
        public_ip = None
        for address in droplet.get("networks", {}).get("v4", []):
            if address.get("type") == "public":
                public_ip = address.get("ip_address")
                break

        payload = {
            "id": str(droplet["id"]),
            "name": droplet["name"],
            "status": droplet["status"],
            "region": droplet.get("region", {}).get("slug"),
            "ip_address": public_ip,
            "tags": droplet.get("tags", []),
            "memory": droplet.get("memory"),
            "vcpus": droplet.get("vcpus"),
            "disk": droplet.get("disk"),
        }
        if detailed:
            payload.update(
                {
                    "created_at": droplet.get("created_at"),
                    "size_slug": droplet.get("size_slug"),
                    "locked": droplet.get("locked"),
                    "features": droplet.get("features", []),
                    "image": droplet.get("image", {}).get("distribution"),
                    "metadata": {
                        "backup_ids": droplet.get("backup_ids", []),
                        "snapshot_ids": droplet.get("snapshot_ids", []),
                        "volume_ids": droplet.get("volume_ids", []),
                    },
                }
            )
        return payload

    def list_items(self, limit: int = 100, filters: Optional[List[str]] = None) -> List[Item]:
        """List droplets."""
        params = {"per_page": min(limit, 200)}
        payload = self._make_request("GET", "/droplets", params=params)
        droplets = payload.get("droplets", [])
        return [create_item(self._normalize_droplet(droplet)) for droplet in droplets[:limit]]

    def get_item(self, item_id: str) -> ItemDetail:
        """Get a specific droplet by ID."""
        payload = self._make_request("GET", f"/droplets/{item_id}")
        droplet = payload.get("droplet")
        if droplet is None:
            raise ClientError(f"Droplet {item_id} was not found in the API response.")
        return create_item_detail(self._normalize_droplet(droplet, detailed=True))

    def search_items(
        self,
        query: str,
        limit: int = 100,
        fields: Optional[List[str]] = None,
    ) -> List[Item]:
        """Search droplets client-side with wildcard matching."""
        pattern = query.lower()
        if "*" not in pattern:
            pattern = f"*{pattern}*"

        matches: List[Item] = []
        for item in self.list_items(limit=limit):
            item_data = item.model_dump()
            search_fields = fields or list(item_data.keys())
            values = [str(item_data.get(field, "")).lower() for field in search_fields]
            if any(fnmatch.fnmatch(value, pattern) for value in values):
                matches.append(item)
        return matches


_client: Optional[DigitaloceanClient] = None


def get_client() -> DigitaloceanClient:
    """Get or create the global DigitalOcean client."""
    global _client
    if _client is None:
        _client = DigitaloceanClient()
    return _client
