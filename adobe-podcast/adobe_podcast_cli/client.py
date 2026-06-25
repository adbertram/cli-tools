"""Adobe Podcast Enhance API client.

Implements the 7-step enhancement pipeline:
  1. POST /rails/active_storage/direct_uploads  — get presigned S3 URL
  2. PUT <s3_url>                               — upload raw file to S3
  3. POST /api/v1/enhance_speech_tracks         — submit enhancement job
  4. GET  /api/v1/enhance_speech_tracks/{id}    — poll until finishedProcessingAt
  5. POST /api/v1/enhance_speech_tracks/{id}/exports — request WAV export
  6. GET  /api/v1/enhance_speech_tracks/{id}/exports/{export_id} — poll until download_url
  7. GET  <download_url>                        — download enhanced file

Auth: Adobe IMS Bearer token extracted via browser (window.adobeIMS.getAccessToken()),
cached in profile ACCESS_TOKEN env after first extraction. Static X-Api-Key also required.
"""

import base64
import hashlib
import mimetypes
import random
import time
from pathlib import Path
from typing import Optional

import requests
from cli_tools_shared.exceptions import ClientError

from .browser import AdobePodcastBrowser
from .config import get_config

ADOBE_PODCAST_URL = "https://podcast.adobe.com/en/enhance"
API_KEY = "phonos-server-prod"
POLL_INTERVAL = 5       # seconds between status polls
POLL_TIMEOUT = 600      # 10-minute hard timeout for enhancement
EXPORT_TIMEOUT = 120    # 2-minute timeout for export URL
BROWSER_TOKEN_WAIT_MS = 4000

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _md5_checksum(data: bytes) -> str:
    """Return base64-encoded MD5 checksum required by Rails Active Storage."""
    return base64.b64encode(hashlib.md5(data).digest()).decode()


def _detect_content_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


class AdobePodcastClient:
    """Client for the Adobe Podcast Enhance internal API."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = config or get_config()
        if not self.config.has_credentials():
            raise ClientError(
                "No saved session. Run 'adobe-podcast auth login' to authenticate."
            )
        self.base_url = self.config.base_url
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self._session = requests.Session()

        access_token = self.config.access_token or self._extract_token_from_browser()
        self._session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "X-Api-Key": API_KEY,
        })

    def _extract_token_from_browser(self) -> str:
        """Open headless browser against the saved profile, extract IMS token, cache it."""
        browser = self.config.get_browser()
        try:
            page = browser.get_page(ADOBE_PODCAST_URL)
            page.wait_for_timeout(BROWSER_TOKEN_WAIT_MS)
            token = page.evaluate(
                "window.adobeIMS?.getAccessToken?.()?.token ?? null"
            )
        finally:
            browser.close()
        if not token:
            raise ClientError(
                "Could not extract Adobe IMS access token. "
                "Run 'adobe-podcast auth login' to refresh the session."
            )
        self.config._set("ACCESS_TOKEN", token)
        return token

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        return min(delay + random.uniform(-jitter_range, jitter_range), self.max_delay)

    def _is_retryable(self, response: Optional[requests.Response], exc: Optional[Exception]) -> bool:
        if exc is not None:
            return isinstance(exc, (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ))
        return response is not None and response.status_code in RETRYABLE_STATUS_CODES

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        value = response.headers.get("Retry-After")
        try:
            return float(value) if value else None
        except ValueError:
            return None

    def _extract_error(self, response: requests.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return response.text[:500]
        if isinstance(body, dict):
            if isinstance(body.get("error"), dict):
                e = body["error"]
                return e.get("message") or e.get("code") or str(e)
            if "message" in body:
                return str(body["message"])
        return str(body)[:500]

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make a request with exponential retry. Returns the Response."""
        last_exc: Optional[Exception] = None
        last_resp: Optional[requests.Response] = None
        max_attempts = self.max_retries + 1

        for attempt in range(max_attempts):
            try:
                resp = self._session.request(method, url, **kwargs)
                last_resp = resp
                if self._is_retryable(resp, None) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt, self._get_retry_after(resp)))
                    continue
                break
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if self._is_retryable(None, exc) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt))
                    continue
                break

        if last_exc is not None and last_resp is None:
            raise ClientError(f"Request failed after {attempt + 1} attempt(s): {last_exc}")
        if last_resp is None:
            raise ClientError("Request failed: no response received")
        if not last_resp.ok:
            raise ClientError(f"HTTP {last_resp.status_code}: {self._extract_error(last_resp)}")
        return last_resp

    def _api(self, method: str, endpoint: str, **kwargs) -> dict:
        """Convenience wrapper for JSON API endpoints."""
        resp = self._request(method, f"{self.base_url}{endpoint}", **kwargs)
        if resp.status_code == 204:
            return {}
        return resp.json()

    # ── Step 1: Request presigned S3 upload URL ──────────────────────────────

    def _direct_upload(self, filename: str, content_type: str, byte_size: int, checksum: str) -> dict:
        return self._api("POST", "/rails/active_storage/direct_uploads", json={
            "blob": {
                "filename": filename,
                "content_type": content_type,
                "byte_size": byte_size,
                "checksum": checksum,
            }
        })

    # ── Step 2: PUT file bytes to S3 ─────────────────────────────────────────

    def _upload_to_s3(self, upload_url: str, upload_headers: dict, data: bytes) -> None:
        resp = self._request(
            "PUT", upload_url,
            headers={**upload_headers, "Content-Length": str(len(data))},
            data=data,
        )
        if resp.status_code not in (200, 204):
            raise ClientError(f"S3 upload failed: HTTP {resp.status_code}")

    # ── Step 3: Submit enhancement job ───────────────────────────────────────

    def _create_track(self, signed_id: str) -> dict:
        return self._api("POST", "/api/v1/enhance_speech_tracks", json={
            "enhance_speech_track": {
                "input_file_signed_id": signed_id,
                "use_case": "podcast",
            }
        })

    # ── Step 4: Poll until enhancement finishes ──────────────────────────────

    def _wait_for_track(self, track_id: str, on_progress=None) -> dict:
        deadline = time.time() + POLL_TIMEOUT
        while time.time() < deadline:
            track = self._api("GET", f"/api/v1/enhance_speech_tracks/{track_id}")
            if track.get("failedAt"):
                raise ClientError(f"Enhancement failed: {track.get('failureReason', 'unknown')}")
            if track.get("finishedProcessingAt"):
                return track
            if on_progress:
                on_progress(track.get("processingProgress", 0))
            time.sleep(POLL_INTERVAL)
        raise ClientError(f"Enhancement timed out after {POLL_TIMEOUT}s")

    # ── Step 5: Request WAV export ────────────────────────────────────────────

    def _create_export(
        self,
        track_id: str,
        enhanced_gain: float,
        background_gain: float,
        isolated_gain: float,
    ) -> dict:
        return self._api("POST", f"/api/v1/enhance_speech_tracks/{track_id}/exports", json={
            "export": {
                "format": "wav",
                "enhanced_gain": enhanced_gain,
                "background_gain": background_gain,
                "isolated_gain": isolated_gain,
            }
        })

    # ── Step 6: Poll until export download URL is ready ──────────────────────

    def _wait_for_export(self, track_id: str, export_id: str) -> dict:
        deadline = time.time() + EXPORT_TIMEOUT
        while time.time() < deadline:
            export = self._api("GET", f"/api/v1/enhance_speech_tracks/{track_id}/exports/{export_id}")
            if export.get("download_url"):
                return export
            time.sleep(POLL_INTERVAL)
        raise ClientError(f"Export URL timed out after {EXPORT_TIMEOUT}s")

    # ── Step 7: Download the enhanced file ───────────────────────────────────

    def _download(self, download_url: str, output_path: Path) -> None:
        resp = requests.get(download_url, stream=True, timeout=120)
        if not resp.ok:
            raise ClientError(f"Download failed: HTTP {resp.status_code}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=65536):
                fh.write(chunk)

    # ── Public entrypoint ─────────────────────────────────────────────────────

    def enhance(
        self,
        input_path: Path,
        output_path: Path,
        enhanced_gain: float = 1.0,
        background_gain: float = 0.0,
        isolated_gain: float = 1.0,
        on_progress=None,
    ) -> dict:
        """Run the full enhance pipeline and save result to output_path."""
        data = input_path.read_bytes()
        filename = input_path.name
        content_type = _detect_content_type(input_path)
        checksum = _md5_checksum(data)

        upload_info = self._direct_upload(filename, content_type, len(data), checksum)
        signed_id = upload_info["signed_id"]
        direct = upload_info["direct_upload"]

        self._upload_to_s3(direct["url"], direct.get("headers", {}), data)

        track = self._create_track(signed_id)
        track_id = track["id"]

        track = self._wait_for_track(track_id, on_progress=on_progress)

        export = self._create_export(track_id, enhanced_gain, background_gain, isolated_gain)
        export_id = export["id"]

        export = self._wait_for_export(track_id, export_id)

        self._download(export["download_url"], output_path)

        return {
            "track_id": track_id,
            "export_id": export_id,
            "input_file": str(input_path),
            "output_file": str(output_path),
            "enhanced_gain": enhanced_gain,
            "background_gain": background_gain,
            "isolated_gain": isolated_gain,
            "finished_at": track.get("finishedProcessingAt"),
        }


_client: Optional[AdobePodcastClient] = None


def get_client() -> AdobePodcastClient:
    global _client
    if _client is None:
        _client = AdobePodcastClient()
    return _client
