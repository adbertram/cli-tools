"""TikTok Content Posting API client."""
from __future__ import annotations

import mimetypes
import time
from pathlib import Path
from typing import Optional

import requests

from cli_tools_shared.exceptions import ClientError, CredentialError

from .config import get_config

MAX_VIDEO_BYTES = 4_000_000_000
MAX_SINGLE_CHUNK = 64_000_000
DEFAULT_MULTI_CHUNK = 10_000_000
MAX_CHUNKS = 1000
SUPPORTED_MIME_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}


def build_chunk_plan(video_size: int) -> tuple[int, list[tuple[int, int]]]:
    if video_size <= 0:
        raise ValueError("Video file must not be empty.")
    if video_size > MAX_VIDEO_BYTES:
        raise ValueError("TikTok Content Posting API supports videos up to 4 GB.")

    if video_size <= MAX_SINGLE_CHUNK:
        return video_size, [(0, video_size - 1)]

    chunk_size = DEFAULT_MULTI_CHUNK
    total_chunk_count = video_size // chunk_size
    if total_chunk_count > MAX_CHUNKS:
        raise ValueError("Video would require more than TikTok's 1000-chunk maximum.")

    ranges: list[tuple[int, int]] = []
    for index in range(total_chunk_count):
        start = index * chunk_size
        end = (
            start + chunk_size - 1
            if index < total_chunk_count - 1
            else video_size - 1
        )
        ranges.append((start, end))
    return chunk_size, ranges


class TikTokPostingClient:
    def __init__(self, config=None, session: Optional[requests.Session] = None):
        self.config = config or get_config()
        self.session = session or requests.Session()

    def _save_refreshed_token(self, payload: dict) -> None:
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token") or self.config.refresh_token
        if not access_token or not refresh_token:
            raise CredentialError("TikTok refresh response omitted required tokens.")
        expires_in = int(payload.get("expires_in") or 86400)
        self.config.save_tokens(
            access_token,
            refresh_token,
            str(time.time() + expires_in),
        )
        if payload.get("open_id"):
            self.config._set("OPEN_ID", str(payload["open_id"]))
        if payload.get("scope"):
            self.config._set("GRANTED_SCOPES", str(payload["scope"]))

    def _ensure_access_token(self) -> str:
        token = self.config.access_token
        if not token:
            raise CredentialError(
                "TikTok API access token is missing. Run tiktok auth login for the API profile."
            )

        expires_at = self.config.token_expires_at
        expired = False
        if expires_at:
            try:
                expired = float(expires_at) <= time.time() + 60
            except (TypeError, ValueError):
                expired = True

        if expired:
            if not self.config.refresh_token:
                raise CredentialError(
                    "TikTok access token expired and no refresh token is stored."
                )
            response = self.session.post(
                self.config.token_url,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "client_key": self.config.client_key,
                    "client_secret": self.config.client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": self.config.refresh_token,
                },
                timeout=30,
            )
            if not response.ok:
                raise CredentialError(
                    f"TikTok token refresh HTTP {response.status_code}: {response.text[:1000]}"
                )
            payload = response.json()
            if payload.get("error"):
                raise CredentialError(
                    "TikTok token refresh failed: "
                    + str(payload.get("error_description") or payload["error"])
                )
            self._save_refreshed_token(payload)
            token = self.config.access_token
        return token

    def _post_json(self, path: str, body: Optional[dict] = None) -> dict:
        token = self._ensure_access_token()
        response = self.session.post(
            f"{self.config.api_base_url}/{path.lstrip('/')}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json=body or {},
            timeout=60,
        )
        if not response.ok:
            raise ClientError(
                f"TikTok Content Posting API HTTP {response.status_code}: {response.text[:1000]}"
            )
        payload = response.json()
        error = payload.get("error") or {}
        if error.get("code") not in (None, "", "ok"):
            raise ClientError(
                f"TikTok Content Posting API error {error.get('code')}: "
                f"{error.get('message', '')}"
            )
        return payload

    def creator_info(self) -> dict:
        payload = self._post_json("/v2/post/publish/creator_info/query/")
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            raise ClientError("TikTok creator-info response did not contain an object.")
        return data

    def status(self, publish_id: str) -> dict:
        payload = self._post_json(
            "/v2/post/publish/status/fetch/",
            {"publish_id": publish_id},
        )
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            raise ClientError("TikTok status response did not contain an object.")
        return {"publish_id": publish_id, **data}

    @staticmethod
    def _mime_type(path: Path) -> str:
        mime = SUPPORTED_MIME_TYPES.get(path.suffix.lower())
        if not mime:
            guessed, _encoding = mimetypes.guess_type(path.name)
            mime = guessed if guessed in SUPPORTED_MIME_TYPES.values() else None
        if not mime:
            raise ClientError("TikTok local upload supports MP4, MOV, or WebM video files.")
        return mime

    def _upload_file(
        self,
        upload_url: str,
        path: Path,
        mime_type: str,
        ranges: list[tuple[int, int]],
    ) -> None:
        total = path.stat().st_size
        with path.open("rb") as fh:
            for index, (start, end) in enumerate(ranges):
                length = end - start + 1
                chunk = fh.read(length)
                if len(chunk) != length:
                    raise ClientError("Unexpected end of file while reading TikTok upload chunk.")
                response = self.session.put(
                    upload_url,
                    headers={
                        "Content-Type": mime_type,
                        "Content-Length": str(length),
                        "Content-Range": f"bytes {start}-{end}/{total}",
                    },
                    data=chunk,
                    timeout=300,
                )
                expected = 201 if index == len(ranges) - 1 else 206
                if response.status_code != expected:
                    raise ClientError(
                        f"TikTok upload chunk {index + 1}/{len(ranges)} returned "
                        f"HTTP {response.status_code}, expected {expected}: "
                        f"{response.text[:1000]}"
                    )

    def publish_video(
        self,
        file_path: Path,
        *,
        title: str = "",
        privacy_level: str = "SELF_ONLY",
        disable_comment: bool = False,
        disable_duet: bool = False,
        disable_stitch: bool = False,
        is_aigc: bool = False,
    ) -> dict:
        path = Path(file_path)
        if not path.is_file():
            raise ClientError(f"Video file not found: {path}")

        creator = self.creator_info()
        privacy_options = creator.get("privacy_level_options") or []
        if privacy_options and privacy_level not in privacy_options:
            raise ClientError(
                f"TikTok privacy level {privacy_level!r} is not available for this creator. "
                f"Available: {', '.join(privacy_options)}"
            )

        disable_comment = disable_comment or bool(creator.get("comment_disabled"))
        disable_duet = disable_duet or bool(creator.get("duet_disabled"))
        disable_stitch = disable_stitch or bool(creator.get("stitch_disabled"))

        size = path.stat().st_size
        chunk_size, ranges = build_chunk_plan(size)
        mime_type = self._mime_type(path)

        post_info = {
            "title": title,
            "privacy_level": privacy_level,
            "disable_comment": disable_comment,
            "disable_duet": disable_duet,
            "disable_stitch": disable_stitch,
        }
        if is_aigc:
            post_info["is_aigc"] = True

        payload = self._post_json(
            "/v2/post/publish/video/init/",
            {
                "post_info": post_info,
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": size,
                    "chunk_size": chunk_size,
                    "total_chunk_count": len(ranges),
                },
            },
        )
        data = payload.get("data") or {}
        publish_id = data.get("publish_id")
        upload_url = data.get("upload_url")
        if not publish_id or not upload_url:
            raise ClientError("TikTok Direct Post init response omitted publish_id or upload_url.")

        self._upload_file(upload_url, path, mime_type, ranges)
        return {**self.status(publish_id), "creator_username": creator.get("creator_username")}
