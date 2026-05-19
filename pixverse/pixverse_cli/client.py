"""PixVerse API client."""
import uuid
from typing import Any, Dict, Optional

import requests

from cli_tools_shared.exceptions import ClientError

from .config import get_config
from .models import Item, ItemDetail, create_item, create_item_detail


class PixverseClient:
    """Client for the PixVerse video generation API."""

    def __init__(self):
        self.config = get_config()
        if not self.config.api_key:
            raise ClientError("Missing credentials: api_key. Run 'pixverse auth login' to authenticate.")
        self.base_url = self.config.base_url.rstrip("/")

    def _headers(self) -> Dict[str, str]:
        """Build per-request headers for PixVerse."""
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "API-KEY": self.config.api_key,
            "Ai-trace-id": str(uuid.uuid4()),
        }

    def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run a PixVerse request and return the Resp payload."""
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self._headers(),
                json=data,
                timeout=60,
            )
        except requests.RequestException as exc:
            raise ClientError(f"Request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ClientError("PixVerse returned a non-JSON response.") from exc

        if response.status_code >= 400:
            message = payload.get("ErrMsg") or response.text or f"HTTP {response.status_code}"
            raise ClientError(message)

        if payload.get("ErrCode") != 0:
            raise ClientError(payload.get("ErrMsg") or "PixVerse request failed.")

        resp = payload.get("Resp")
        if not isinstance(resp, dict):
            raise ClientError("PixVerse response did not include an object-valued Resp payload.")
        return resp

    def generate_text_video(
        self,
        prompt: str,
        model: Optional[str] = None,
        duration: Optional[int] = None,
        quality: Optional[str] = None,
    ) -> Item:
        """Submit a text-to-video generation request."""
        body: Dict[str, Any] = {"prompt": prompt}
        if model is not None:
            body["model"] = model
        if duration is not None:
            body["duration"] = duration
        if quality is not None:
            body["quality"] = quality

        resp = self._request("POST", "/video/text/generate", data=body)
        video_id = resp.get("video_id")
        if video_id is None:
            raise ClientError("PixVerse response did not include video_id.")
        return create_item(
            {
                "id": str(video_id),
                "name": prompt,
                "operation": "text-to-video",
                "model": model,
                "duration": duration,
                "quality": quality,
                "metadata": resp,
            }
        )

    def get_item(self, item_id: str) -> ItemDetail:
        """Get the current status payload for a PixVerse video generation."""
        resp = self._request("GET", f"/video/result/{item_id}")
        status_code = resp.get("status")
        if status_code is None:
            raise ClientError("PixVerse status response did not include status.")
        return create_item_detail(
            {
                "id": str(item_id),
                "name": f"video:{item_id}",
                "operation": "status",
                "status_code": int(status_code),
                "metadata": resp,
            }
        )


_client: Optional[PixverseClient] = None


def get_client() -> PixverseClient:
    """Get or create the global PixVerse client."""
    global _client
    if _client is None:
        _client = PixverseClient()
    return _client
