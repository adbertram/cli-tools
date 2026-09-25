"""Facebook Graph API client for Pages and Reels publishing."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import requests

from cli_tools_shared.exceptions import ClientError, CredentialError

from .config import get_config


class FacebookGraphClient:
    """Use a user token to discover Pages and publish Page Reels."""

    def __init__(self, config=None, session: Optional[requests.Session] = None):
        self.config = config or get_config()
        if not self.config.access_token:
            raise CredentialError(
                "Facebook Graph API access token is missing. "
                "Run facebook auth login with the Graph API profile."
            )
        self.session = session or requests.Session()

    def _request(
        self,
        method: str,
        path_or_url: str,
        *,
        token: Optional[str] = None,
        params: Optional[dict] = None,
        data: Optional[dict] = None,
        timeout: int = 60,
    ) -> dict:
        url = (
            path_or_url
            if path_or_url.startswith("https://")
            else f"{self.config.graph_base_url}/{path_or_url.lstrip('/')}"
        )
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token or self.config.access_token}",
        }
        response = self.session.request(
            method,
            url,
            headers=headers,
            params=params,
            data=data,
            timeout=timeout,
        )
        if not response.ok:
            raise ClientError(
                f"Facebook Graph API HTTP {response.status_code}: {response.text[:1000]}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ClientError("Facebook Graph API returned a non-JSON response.") from exc
        if not isinstance(payload, dict):
            raise ClientError("Facebook Graph API returned a non-object response.")
        if payload.get("error"):
            raise ClientError(f"Facebook Graph API error: {payload['error']}")
        return payload

    def get_me(self) -> dict:
        return self._request("GET", "/me", params={"fields": "id,name"})

    @staticmethod
    def _public_page(raw: dict) -> dict:
        return {
            "id": raw.get("id"),
            "name": raw.get("name"),
            "tasks": raw.get("tasks") or [],
        }

    def list_pages(self, limit: int = 100) -> list[dict]:
        pages: list[dict] = []
        next_url: Optional[str] = None
        params = {"fields": "id,name,access_token,tasks", "limit": min(limit, 100)}
        while len(pages) < limit:
            payload = self._request(
                "GET",
                next_url or "/me/accounts",
                params=None if next_url else params,
            )
            for item in payload.get("data") or []:
                pages.append(self._public_page(item))
                if len(pages) >= limit:
                    break
            next_url = (payload.get("paging") or {}).get("next")
            if not next_url:
                break
        return pages[:limit]

    def _page_context(self, page_id: str) -> dict:
        payload = self._request(
            "GET",
            f"/{page_id}",
            params={"fields": "id,name,access_token"},
        )
        page_token = payload.get("access_token")
        if not page_token:
            raise ClientError(
                f"Facebook did not return a Page access token for page {page_id}. "
                "Verify pages_show_list/pages_manage_posts permissions and Page access."
            )
        return {
            "id": payload.get("id") or page_id,
            "name": payload.get("name"),
            "access_token": page_token,
        }

    def get_page(self, page_id: str) -> dict:
        return self._public_page(self._page_context(page_id))

    def get_reel_status(self, page_id: str, video_id: str) -> dict:
        page = self._page_context(page_id)
        payload = self._request(
            "GET",
            f"/{video_id}",
            token=page["access_token"],
            params={"fields": "id,status"},
        )
        return {
            "page_id": page["id"],
            "page_name": page["name"],
            "video_id": payload.get("id") or video_id,
            "status": payload.get("status"),
        }

    def delete_reel(self, page_id: str, video_id: str) -> dict:
        page = self._page_context(page_id)
        payload = self._request("DELETE", f"/{video_id}", token=page["access_token"])
        if payload.get("success") is not True:
            raise ClientError(f"Facebook did not confirm deletion of video {video_id}: {payload}")
        return {
            "page_id": page["id"],
            "page_name": page["name"],
            "video_id": video_id,
            "deleted": True,
        }

    def publish_reel(
        self,
        page_id: str,
        file_path: Path,
        *,
        title: str = "",
        description: str = "",
        draft: bool = False,
    ) -> dict:
        path = Path(file_path)
        if not path.is_file():
            raise ClientError(f"Video file not found: {path}")

        page = self._page_context(page_id)
        page_token = page["access_token"]

        start = self._request(
            "POST",
            "/me/video_reels",
            token=page_token,
            data={"upload_phase": "start"},
        )
        video_id = start.get("video_id")
        upload_url = start.get("upload_url")
        if not video_id or not upload_url:
            raise ClientError("Facebook Reels start response omitted video_id or upload_url.")

        video_state = "DRAFT" if draft else "PUBLISHED"
        # Name the created video in any later failure so callers can delete it.
        try:
            file_size = path.stat().st_size
            with path.open("rb") as fh:
                upload_response = self.session.post(
                    upload_url,
                    headers={
                        "Authorization": f"OAuth {page_token}",
                        "offset": "0",
                        "file_size": str(file_size),
                        "Content-Type": "application/octet-stream",
                    },
                    data=fh,
                    timeout=300,
                )
            if not upload_response.ok:
                raise ClientError(
                    f"Facebook Reels upload HTTP {upload_response.status_code}: "
                    f"{upload_response.text[:1000]}"
                )

            finish_data = {
                "upload_phase": "finish",
                "video_id": video_id,
                "video_state": video_state,
            }
            if title:
                finish_data["title"] = title
            if description:
                finish_data["description"] = description

            finish = self._request(
                "POST",
                "/me/video_reels",
                token=page_token,
                data=finish_data,
            )
            status = self._request(
                "GET",
                f"/{video_id}",
                token=page_token,
                params={"fields": "id,status"},
            )
        except (ClientError, requests.RequestException) as exc:
            raise ClientError(f"{exc} [video_id={video_id}]") from exc
        return {
            "page_id": page["id"],
            "page_name": page["name"],
            "video_id": video_id,
            "video_state": video_state,
            "published": not draft and bool(finish.get("success", True)),
            "status": status.get("status"),
        }
