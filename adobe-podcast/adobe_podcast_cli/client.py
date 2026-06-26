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
import uuid
from pathlib import Path
from typing import Optional

import requests
from cli_tools_shared import get_activity_logger
from cli_tools_shared.exceptions import ClientError

from .browser import AdobePodcastBrowser
from .config import get_config

_logger = get_activity_logger("adobe-podcast")

ADOBE_PODCAST_URL = "https://podcast.adobe.com/en/enhance"
API_KEY = "phonos-server-prod"
POLL_INTERVAL = 10      # seconds between status polls
POLL_TIMEOUT = 600      # 10-minute hard timeout for enhancement
EXPORT_TIMEOUT = 120    # 2-minute timeout for export URL
BROWSER_TOKEN_WAIT_MS = 30000   # max ms to poll for IMS SDK to initialize

DEFAULT_MAX_RETRIES = 5
DEFAULT_BASE_DELAY = 2.0
DEFAULT_MAX_DELAY = 60.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


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
            "X-Cookie-Settings": "C0001",
        })

    def _extract_token_from_browser(self) -> str:
        """Open headless browser against the saved profile, extract IMS token, cache it.

        Polls every 500ms for the Adobe IMS SDK to initialize (window.adobeIMS)
        instead of sleeping a fixed duration — the SDK loads asynchronously.
        """
        browser = self.config.get_browser()
        token = None
        try:
            page = browser.get_page(ADOBE_PODCAST_URL)
            elapsed_ms = 0
            poll_ms = 500
            while elapsed_ms < BROWSER_TOKEN_WAIT_MS:
                token = page.evaluate(
                    "window.adobeIMS?.getAccessToken?.()?.token ?? null"
                )
                if token:
                    break
                page.wait_for_timeout(poll_ms)
                elapsed_ms += poll_ms
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
        ts = int(time.time() * 1000)
        sep = "&" if "?" in endpoint else "?"
        resp = self._request(method, f"{self.base_url}{endpoint}{sep}time={ts}", **kwargs)
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
        # Use a plain requests.put (not the authenticated session) — S3 presigned URLs
        # carry auth in query params and reject any additional Authorization header.
        resp = requests.put(
            upload_url,
            headers=upload_headers,
            data=data,
            timeout=120,
        )
        if not resp.ok:
            raise ClientError(f"S3 upload failed: HTTP {resp.status_code}: {resp.text[:200]}")

    # ── Step 3: Submit enhancement job ───────────────────────────────────────

    def _create_track(self, signed_id: str, filename: str, model_version: str = "v1") -> dict:
        return self._api("POST", "/api/v1/enhance_speech_tracks", json={
            "id": str(uuid.uuid4()),
            "track_name": filename,
            "model_version": model_version,
            "signed_id": signed_id,
        })

    # ── Step 4: Poll until enhancement finishes ──────────────────────────────

    def _wait_for_track(self, track_id: str, on_progress=None) -> dict:
        deadline = time.time() + POLL_TIMEOUT
        while time.time() < deadline:
            try:
                track = self._api("GET", f"/api/v1/enhance_speech_tracks/{track_id}")
            except ClientError as exc:
                _logger.warning("Transient poll error (track %s): %s — retrying", track_id, exc)
                time.sleep(POLL_INTERVAL)
                continue
            if track.get("error_type") or track.get("failed_at"):
                raise ClientError(f"Enhancement failed: {track.get('error_type', 'unknown')}")
            if track.get("finished_processing_at"):
                return track
            if on_progress:
                on_progress(track.get("processing_progress", 0))
            time.sleep(POLL_INTERVAL)
        raise ClientError(f"Enhancement timed out after {POLL_TIMEOUT}s")

    # ── Step 5: Request WAV export ────────────────────────────────────────────

    def _create_export(self, track_id: str, enhanced_gain: float) -> dict:
        # v1 model uses a single strength percent (0–100); enhancement is always enabled.
        strength = int(round(enhanced_gain * 100))
        return self._api("POST", f"/api/v1/enhance_speech_tracks/{track_id}/exports", json={
            "strength": strength,
            "enhancement_enabled": True,
            "track_component": "full",
        })

    # ── Step 6: Poll until export download URL is ready ──────────────────────

    def _wait_for_export(self, track_id: str, export_id: str) -> dict:
        deadline = time.time() + EXPORT_TIMEOUT
        while time.time() < deadline:
            try:
                export = self._api("GET", f"/api/v1/enhance_speech_tracks/{track_id}/exports/{export_id}")
            except ClientError as exc:
                _logger.warning("Transient poll error (export %s): %s — retrying", export_id, exc)
                time.sleep(POLL_INTERVAL)
                continue
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

        _logger.info("enhance: start input=%s output=%s", input_path.name, output_path.name)
        try:
            upload_info = self._direct_upload(filename, content_type, len(data), checksum)
        except ClientError as e:
            raise ClientError(f"[step 1/7 direct-upload] {e}") from e
        signed_id = upload_info["signed_id"]
        direct = upload_info["direct_upload"]

        try:
            self._upload_to_s3(direct["url"], direct.get("headers", {}), data)
        except ClientError as e:
            raise ClientError(f"[step 2/7 s3-put] {e}") from e

        try:
            track = self._create_track(signed_id, filename)
        except ClientError as e:
            raise ClientError(f"[step 3/7 create-track] {e}") from e
        track_id = track["id"]

        try:
            track = self._wait_for_track(track_id, on_progress=on_progress)
        except ClientError as e:
            raise ClientError(f"[step 4/7 wait-for-track] {e}") from e

        try:
            export = self._create_export(track_id, enhanced_gain)
        except ClientError as e:
            raise ClientError(f"[step 5/7 create-export] {e}") from e
        export_id = export["id"]

        try:
            export = self._wait_for_export(track_id, export_id)
        except ClientError as e:
            raise ClientError(f"[step 6/7 wait-for-export] {e}") from e

        try:
            self._download(export["download_url"], output_path)
        except ClientError as e:
            raise ClientError(f"[step 7/7 download] {e}") from e

        result = {
            "track_id": track_id,
            "export_id": export_id,
            "input_file": str(input_path),
            "output_file": str(output_path),
            "enhanced_gain": enhanced_gain,
            "background_gain": background_gain,
            "isolated_gain": isolated_gain,
            "finished_at": track.get("finished_processing_at"),
        }
        _logger.info("enhance: complete track_id=%s output=%s", track_id, output_path.name)
        return result


_client: Optional[AdobePodcastClient] = None


def get_client() -> AdobePodcastClient:
    global _client
    if _client is None:
        _client = AdobePodcastClient()
    return _client
