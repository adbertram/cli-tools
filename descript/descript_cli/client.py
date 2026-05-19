"""Descript API client with automatic JWT token refresh from running app."""
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import random

import requests

from .config import get_config
from .models import (
    Composition,
    ExportPlaylist,
    Project,
    ProjectDetail,
    VideoAsset,
    create_export_playlist,
    create_project,
    create_project_detail,
    create_video_asset,
)


# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1

# HTTP status codes that trigger retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

class ClientError(Exception):
    """Custom exception for Descript API errors."""
    pass


class DescriptClient:
    """Client for Descript API with automatic JWT refresh from running app."""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
        config=None,
    ):
        """Initialize Descript client.

        Args:
            max_retries: Maximum number of retry attempts (default: 3)
            base_delay: Base delay in seconds for exponential backoff (default: 1.0)
            max_delay: Maximum delay in seconds between retries (default: 30.0)
            jitter: Random jitter factor (default: 0.1)
        """
        self.config = config or get_config()
        self.base_url = self.config.base_url

        # Retry configuration
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

        # Cache for drive IDs
        self._drive_ids: Optional[List[str]] = None

    @property
    def token_cache_file(self) -> Path:
        return self.config.get_profile_data_dir() / "token.json"

    def _get_cached_token(self) -> Optional[Dict]:
        """Get cached JWT token if it exists and is not expired.

        Returns:
            Token dict with 'jwt' and 'expires_at' keys, or None if expired/missing
        """
        token_cache_file = self.token_cache_file
        if not token_cache_file.exists():
            return None

        try:
            with open(token_cache_file) as f:
                data = json.load(f)

            expires_at = data.get("expires_at", 0)
            # Consider expired if less than 60 seconds remaining
            if datetime.now().timestamp() > (expires_at - 60):
                return None

            return data
        except Exception:
            return None

    def _save_token_cache(self, jwt: str, expires_at: float):
        """Save JWT to cache file.

        Args:
            jwt: JWT token string
            expires_at: Unix timestamp when token expires
        """
        token_cache_file = self.token_cache_file
        token_cache_file.parent.mkdir(parents=True, exist_ok=True)
        token_cache_file.chmod(0o600) if token_cache_file.exists() else None

        cache_data = {
            "jwt": jwt,
            "expires_at": expires_at,
            "cached_at": datetime.now().timestamp(),
        }

        with open(token_cache_file, "w") as f:
            json.dump(cache_data, f)

        token_cache_file.chmod(0o600)

    def _extract_jwt_from_app(self) -> Optional[str]:
        """Extract JWT from running Descript app via Chrome DevTools Protocol.

        Connects to the Descript Electron app's CDP endpoint on port 9222,
        finds the main page target, and extracts the stytch_session_jwt cookie.

        Requires Descript to be running with --remote-debugging-port=9222.

        Returns:
            JWT token string, or None if extraction fails
        """
        import http.client
        import json as json_module
        import websocket

        CDP_PORT = 9222

        try:
            # Step 1: Get CDP targets
            conn = http.client.HTTPConnection("127.0.0.1", CDP_PORT, timeout=5)
            conn.request("GET", "/json")
            response = conn.getresponse()

            if response.status != 200:
                return None

            targets = json_module.loads(response.read().decode())
            conn.close()

            # Step 2: Find the main Descript page target
            page_target = None
            for target in targets:
                if (target.get("type") == "page" and
                    "Descript" in target.get("title", "") and
                    "stripe" not in target.get("title", "")):
                    page_target = target
                    break

            if not page_target:
                return None

            ws_url = page_target.get("webSocketDebuggerUrl")
            if not ws_url:
                return None

            # Step 3: Connect via WebSocket and extract cookies
            ws = websocket.create_connection(ws_url, timeout=5)
            ws.send(json_module.dumps({
                "id": 1,
                "method": "Network.getCookies",
                "params": {"urls": ["https://web.descript.com"]},
            }))

            result = json_module.loads(ws.recv())
            ws.close()

            if not result.get("result", {}).get("cookies"):
                return None

            # Step 4: Find the stytch_session_jwt cookie
            for cookie in result["result"]["cookies"]:
                if cookie["name"] == "stytch_session_jwt":
                    jwt = cookie["value"]
                    # Cache with 4-minute TTL (1-minute safety margin on 5-minute expiry)
                    self._save_token_cache(jwt, datetime.now().timestamp() + 240)
                    return jwt

            return None

        except Exception:
            return None

    def _get_jwt(self) -> str:
        """Get valid JWT token, refreshing from app if needed.

        Returns:
            JWT token string

        Raises:
            ClientError: If token cannot be obtained
        """
        # Try cached token first
        cached = self._get_cached_token()
        if cached:
            return cached["jwt"]

        # Try extracting from running app
        jwt = self._extract_jwt_from_app()
        if jwt:
            return jwt

        # App not running or extraction failed
        raise ClientError(
            "Failed to get authentication token.\n\n"
            "Descript must be running to authenticate.\n"
            "Start Descript and try again, or run: descript auth login"
        )

    def _update_headers(self) -> Dict[str, str]:
        """Get request headers with current JWT.

        Returns:
            Headers dict with Authorization header
        """
        jwt = self._get_jwt()
        return {
            "Authorization": f"Bearer {jwt}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """Calculate delay before next retry using exponential backoff.

        Args:
            attempt: Current retry attempt number (0-indexed)
            retry_after: Optional Retry-After header value from server

        Returns:
            Delay in seconds
        """
        if retry_after is not None:
            return min(retry_after, self.max_delay)

        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)
        return min(delay, self.max_delay)

    def _is_retryable(self, response: Optional[requests.Response], exception: Optional[Exception]) -> bool:
        """Check if a request should be retried.

        Args:
            response: Response object if request completed
            exception: Exception raised if request failed

        Returns:
            True if request should be retried
        """
        if exception is not None:
            return isinstance(exception, (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ))

        if response is not None:
            return response.status_code in RETRYABLE_STATUS_CODES

        return False

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        """Extract Retry-After header value from response.

        Args:
            response: Response object

        Returns:
            Retry delay in seconds, or None
        """
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return None

        try:
            return float(retry_after)
        except ValueError:
            return None

    def _extract_error_detail(self, response: requests.Response) -> str:
        """Extract error message from HTTP error response.

        Args:
            response: Response object

        Returns:
            Error message string
        """
        try:
            error_body = response.json()

            if "error" in error_body:
                err = error_body["error"]
                if isinstance(err, dict):
                    return err.get("message") or str(err)
                return str(err)

            if "message" in error_body:
                return error_body["message"]

            return str(error_body)[:500]
        except Exception:
            return response.text[:500] if response.text else "Unknown error"

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
    ) -> Dict:
        """Make an HTTP request to Descript API with exponential retry.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint path
            data: Request body data
            params: Query parameters
            retry: Whether to retry on transient errors

        Returns:
            Response JSON data

        Raises:
            ClientError: If request fails after all retries
        """
        url = f"{self.base_url}{endpoint}"

        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None

        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                # Get fresh headers with JWT on each attempt (in case token refreshed)
                headers = self._update_headers()

                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=data,
                    params=params,
                )
                last_response = response

                # Check if we should retry
                if retry and self._is_retryable(response, None) and attempt < self.max_retries:
                    retry_after = self._get_retry_after(response)
                    delay = self._calculate_retry_delay(attempt, retry_after)
                    time.sleep(delay)
                    continue

                break

            except requests.exceptions.RequestException as e:
                last_exception = e
                if retry and self._is_retryable(None, e) and attempt < self.max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    time.sleep(delay)
                    continue
                break

        # Handle final result
        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed after {attempt + 1} attempts: {last_exception}")

        if last_response is None:
            raise ClientError("Request failed: no response received")

        if not last_response.ok:
            error_msg = self._extract_error_detail(last_response)
            raise ClientError(f"HTTP {last_response.status_code}: {error_msg}")

        if last_response.status_code == 204:
            return {}

        return last_response.json()

    # ==================== API Methods ====================

    def get_drive_ids(self) -> List[str]:
        """Get user's drive IDs.

        Returns:
            List of drive ID strings
        """
        if self._drive_ids is not None:
            return self._drive_ids

        response = self._make_request("GET", "/v2/users/me/driveIds")
        self._drive_ids = response if isinstance(response, list) else []
        return self._drive_ids

    def list_projects(self, limit: int = 50) -> List[Project]:
        """List user's projects.

        Args:
            limit: Maximum number of projects to return (default: 50)

        Returns:
            List of Project models
        """
        drive_ids = self.get_drive_ids()
        if not drive_ids:
            raise ClientError("No drives found")

        # Use first drive (most common case)
        drive_id = drive_ids[0]

        params = {
            "filter": "recent",
            "sub_filter": "all",
            "sort": "last_viewed",
            "sort_direction": "desc",
            "limit": limit,
        }

        response = self._make_request(
            "GET",
            f"/v2/drives/{drive_id}/projects/paginated",
            params=params,
        )

        # Extract projects list
        raw_projects = response.get("projects", [])
        return [create_project(p) for p in raw_projects]

    def get_project(self, project_id: str) -> ProjectDetail:
        """Get a project's details including compositions.

        Args:
            project_id: Project UUID

        Returns:
            ProjectDetail model with compositions
        """
        response = self._make_request("GET", f"/v2/projects/{project_id}")
        return create_project_detail(response)

    def list_compositions(self, project_id: str) -> List[Composition]:
        """List compositions in a project.

        Args:
            project_id: Project UUID

        Returns:
            List of Composition models
        """
        detail = self.get_project(project_id)
        return detail.compositions

    def list_video_assets(self, project_id: str) -> List[VideoAsset]:
        """List video assets (raw recordings) in a project.

        Args:
            project_id: Project UUID

        Returns:
            List of VideoAsset models sorted by creation date
        """
        response = self._make_request(
            "GET",
            f"/v2/projects/{project_id}/media_assets",
            params={"include_artifacts": "true"},
        )
        assets = response.get("data", [])
        video_assets = [
            create_video_asset(a)
            for a in assets
            if a.get("metadata", {}).get("type") == "video"
        ]
        video_assets.sort(key=lambda a: a.created_at)
        return video_assets

    def get_export_playlist(
        self,
        project_id: str,
        asset_id: str,
        fmt: str = "mp4",
        fps: int = 30,
        width: int = 1920,
        height: int = 1080,
    ) -> ExportPlaylist:
        """Get export playlist for a video asset.

        Args:
            project_id: Project UUID
            asset_id: Video asset UUID
            fmt: Export format (default: mp4)
            fps: Frames per second (default: 30)
            width: Max width (default: 1920)
            height: Max height (default: 1080)

        Returns:
            ExportPlaylist with download URL and segment info
        """
        body = {
            "accept_codecs": ["h264"],
            "effects": [],
            "format": fmt,
            "fps": fps,
            "mode": "export",
            "max_width": width,
            "max_height": height,
        }
        response = self._make_request(
            "POST",
            f"/v2/mts/{project_id}/asset/{asset_id}/video_playlist",
            data=body,
        )
        return create_export_playlist(response)

    def download_export(
        self,
        playlist: ExportPlaylist,
        output_path: str,
        progress_callback=None,
    ) -> str:
        """Download an exported video from its playlist segments.

        Args:
            playlist: ExportPlaylist from get_export_playlist
            output_path: Path to write the MP4 file
            progress_callback: Optional callable(downloaded_bytes, segment_index, total_segments)

        Returns:
            Output file path
        """
        from pathlib import Path

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        segments = playlist.fragment_starts
        total = len(segments)

        with open(output, "wb") as f:
            for i, start in enumerate(segments):
                # End is next segment start, or total duration for last segment
                end = segments[i + 1] if i + 1 < total else playlist.end
                url = f"{playlist.url}?{playlist.params}&start={start}&end={end}"

                resp = requests.get(url, timeout=60)
                resp.raise_for_status()
                f.write(resp.content)

                if progress_callback:
                    progress_callback(f.tell(), i + 1, total)

        return str(output)


# Module-level client instance
_client: Optional[DescriptClient] = None


def get_client() -> DescriptClient:
    """Get or create the global Descript client instance."""
    global _client
    if _client is None:
        _client = DescriptClient()
    return _client
