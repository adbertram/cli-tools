"""Vues API client: HTTP against the Vues backend (api.evrgreen.ai) using the
Supabase session captured once at browser login.

Everything below the login step is plain HTTP. The Supabase session (access and
refresh tokens) is read out of the browser's localStorage after Google/Apple
sign-in, saved as runtime auth state, and refreshed over HTTP against Supabase
GoTrue when it expires -- no browser is opened again.

Routes and the error envelope come from the Vues web app bundle and live calls
(verified 2026-10-14):
  * base https://api.evrgreen.ai, version prefix /api/v1
  * errors: {"status":"error","code":N,"message":"..."}
  * confirmed routes: GET /users/me, /organizations, /organizations/{id},
    /campaigns, /campaigns/{id} -- all require the Supabase bearer token.
The linked-account, submission and earnings routes are not exposed to the public
site or its downloadable bundle (they load only inside the signed-in app), so
those commands resolve their exact path from the backend's own authenticated
OpenAPI document at runtime rather than hard-coding a guessed path.
"""

import base64
import json
import random
import re
import time
from typing import List, Optional
from urllib.parse import urlsplit

import requests
from cli_tools_shared.exceptions import ClientError, CredentialError

from .config import SUPABASE_ANON_KEY, SUPABASE_URL, TOKEN_FIELDS, get_config

API_PREFIX = "/api/v1"
REQUEST_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
REFRESH_MARGIN = 60  # seconds before expiry to renew
SPEC_PATH = f"{API_PREFIX}/openapi.json"
OPENAPI_PATHS = ("/openapi.json", "/api/openapi.json", SPEC_PATH)

VUES_ORIGIN = "https://vues.app"
TIKTOK = "tiktok"
# Candidate words that identify each resource's operation in the OpenAPI spec.
RESOURCE_KEYWORDS = {
    "social_accounts": ("social-account", "social_account", "socialaccount", "account",
                        "connection", "channel"),
    "submissions": ("submission", "clip", "post", "content", "video"),
    "earnings": ("earning", "balance", "payout", "wallet", "withdraw"),
    "join": ("join", "enroll", "member", "apply", "participate"),
}


def tiktok_post(url: str) -> tuple:
    """Return (canonical URL, username, video id) for a full TikTok post URL."""
    parsed = urlsplit(url.strip())
    match = re.fullmatch(r"/@([A-Za-z0-9_.]{1,24})/video/([0-9]+)/?", parsed.path)
    if parsed.scheme != "https" or parsed.netloc not in ("www.tiktok.com", "tiktok.com") or not match:
        raise ClientError("--url must be a full https://www.tiktok.com/@<user>/video/<id> post URL")
    return f"https://www.tiktok.com/@{match[1].lower()}/video/{match[2]}", match[1].lower(), match[2]


def video_id(url) -> Optional[str]:
    match = re.search(r"/video/([0-9]+)", url) if isinstance(url, str) else None
    return match[1] if match else None


def _as_list(document, keys=("data", "items", "results", "campaigns", "submissions", "accounts")):
    """Extract a list from a bare list or a common list-envelope, without
    inventing field names beyond the envelope keys the API might use."""
    if isinstance(document, list):
        return document
    if isinstance(document, dict):
        for key in keys:
            value = document.get(key)
            if isinstance(value, list):
                return value
    raise ClientError("Vues response did not contain a list")


class VuesClient:
    """Client for the Vues backend, authenticated with the captured Supabase session."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = config or get_config()
        self.base_url = self.config.base_url.rstrip("/")
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self._spec = None

    # ==================== Session capture (login only) ====================

    @staticmethod
    def parse_supabase_session(items: List[dict], storage_key: str) -> dict:
        """Assemble the Supabase session from one or more localStorage entries.

        Handles supabase-js v2 (the session object stored directly), gotrue-js v1
        (wrapped under ``currentSession``) and supabase-ssr (``base64-`` prefixed,
        possibly chunked across ``<key>.0``, ``<key>.1`` ...)."""
        parts = {}
        for item in items or []:
            name = item.get("key", "")
            if name == storage_key:
                parts[-1] = item.get("value", "")
            elif name.startswith(storage_key + "."):
                suffix = name[len(storage_key) + 1:]
                if suffix.isdigit():
                    parts[int(suffix)] = item.get("value", "")
        if not parts:
            raise CredentialError("No Vues session found in the browser: run `vues auth login`")
        raw = "".join(parts[index] for index in sorted(parts))
        if raw.startswith("base64-"):
            try:
                raw = base64.b64decode(raw[len("base64-"):] + "==").decode("utf-8")
            except (ValueError, UnicodeDecodeError) as exc:
                raise CredentialError(f"Vues session is not decodable: {exc}") from None
        try:
            parsed = json.loads(raw)
        except ValueError as exc:
            raise CredentialError(f"Vues session is not valid JSON: {exc}") from None
        session = parsed.get("currentSession") if isinstance(parsed, dict) and "currentSession" in parsed else parsed
        if not isinstance(session, dict):
            raise CredentialError("Vues session has an unexpected shape")
        access = session.get("access_token")
        refresh = session.get("refresh_token")
        expires_at = session.get("expires_at") or (parsed.get("expiresAt") if isinstance(parsed, dict) else None)
        if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
            raise CredentialError("Vues session is missing its tokens: run `vues auth login`")
        return {"access_token": access, "refresh_token": refresh,
                "expires_at": str(int(expires_at)) if expires_at else ""}

    def capture_session(self, browser) -> None:
        """Read the Supabase session out of the logged-in browser and save it."""
        page = browser.get_page(VUES_ORIGIN)
        items = page.localstorage_get(VUES_ORIGIN)
        storage_key = browser.AUTH_STORAGE_KEY
        self._save_session(self.parse_supabase_session(items, storage_key))

    # ==================== Session (HTTP) ====================

    def _save_session(self, session: dict) -> None:
        self.config._set("SUPABASE_ACCESS_TOKEN", session["access_token"])
        self.config._set("SUPABASE_REFRESH_TOKEN", session["refresh_token"])
        self.config._set("SUPABASE_EXPIRES_AT", session.get("expires_at") or "")

    def _tokens(self) -> dict:
        return {field: (self.config._get(field) or None) for field in TOKEN_FIELDS}

    @staticmethod
    def _expired(expires_at: Optional[str]) -> bool:
        if not expires_at:
            return True
        try:
            return int(float(expires_at)) - REFRESH_MARGIN <= int(time.time())
        except (TypeError, ValueError):
            return True

    def _refresh(self, refresh_token: str) -> str:
        response = requests.post(
            f"{SUPABASE_URL}/auth/v1/token",
            params={"grant_type": "refresh_token"},
            headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
            json={"refresh_token": refresh_token},
            timeout=REQUEST_TIMEOUT,
        )
        if not response.ok:
            raise CredentialError("Vues session expired and could not be refreshed: run `vues auth login`")
        data = response.json()
        access = data.get("access_token")
        new_refresh = data.get("refresh_token") or refresh_token
        if not isinstance(access, str) or not access:
            raise CredentialError("Vues session refresh returned no access token")
        expires_at = data.get("expires_at") or (int(time.time()) + int(data.get("expires_in") or 3600))
        self._save_session({"access_token": access, "refresh_token": new_refresh,
                            "expires_at": str(int(expires_at))})
        return access

    def _access_token(self) -> str:
        tokens = self._tokens()
        if not tokens["SUPABASE_REFRESH_TOKEN"]:
            raise CredentialError("Not signed in to Vues: run `vues auth login`")
        if tokens["SUPABASE_ACCESS_TOKEN"] and not self._expired(tokens["SUPABASE_EXPIRES_AT"]):
            return tokens["SUPABASE_ACCESS_TOKEN"]
        return self._refresh(tokens["SUPABASE_REFRESH_TOKEN"])

    # ==================== Transport ====================

    def _retry_delay(self, attempt: int, retry_after: Optional[float]) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        delay = self.base_delay * (2 ** attempt)
        span = delay * self.jitter
        return min(delay + random.uniform(-span, span), self.max_delay)

    def _send(self, method: str, url: str, params=None, body=None, token=None) -> requests.Response:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            headers["Content-Type"] = "application/json"
        retries = self.max_retries if method == "GET" else 0
        response = error = None
        for attempt in range(retries + 1):
            response = error = None
            try:
                response = requests.request(method, url, headers=headers, params=params,
                                            json=body, timeout=REQUEST_TIMEOUT)
            except requests.exceptions.RequestException as exc:
                error = exc
            retryable = error is not None or (response is not None and response.status_code in RETRYABLE_STATUS_CODES)
            if attempt < retries and retryable:
                retry_after = None
                if response is not None:
                    try:
                        retry_after = float(response.headers["Retry-After"])
                    except (KeyError, ValueError):
                        retry_after = None
                time.sleep(self._retry_delay(attempt, retry_after))
                continue
            break
        if response is None:
            raise ClientError(f"{method} {url} failed: {error}")
        return response

    @staticmethod
    def _document(response: requests.Response):
        try:
            document = response.json()
        except ValueError as exc:
            if not response.ok:
                raise ClientError(f"Vues HTTP {response.status_code}: {response.text[:300]}") from exc
            raise ClientError(f"Vues returned a non-JSON response: {exc}") from exc
        if not response.ok:
            message = document.get("message") if isinstance(document, dict) else None
            detail = document.get("detail") if isinstance(document, dict) else None
            raise ClientError(f"Vues HTTP {response.status_code}: {message or detail or document}")
        return document

    def _api(self, method: str, path: str, params=None, body=None):
        token = self._access_token()
        url = f"{self.base_url}{API_PREFIX}{path}"
        response = self._send(method, url, params=params, body=body, token=token)
        if response.status_code == 401:
            # Access token may have been revoked mid-flight; refresh once and retry.
            token = self._refresh(self._tokens()["SUPABASE_REFRESH_TOKEN"])
            response = self._send(method, url, params=params, body=body, token=token)
        return self._document(response)

    # ==================== OpenAPI self-discovery ====================

    def _openapi(self) -> dict:
        if self._spec is not None:
            return self._spec
        token = self._access_token()
        last = None
        for candidate in OPENAPI_PATHS:
            response = self._send("GET", f"{self.base_url}{candidate}", token=token)
            if response.ok:
                try:
                    document = response.json()
                except ValueError:
                    continue
                if isinstance(document, dict) and isinstance(document.get("paths"), dict):
                    self._spec = document
                    return document
            last = response.status_code
        raise ClientError(f"Vues OpenAPI document was not reachable (last status {last})")

    def resolve(self, resource: str, verb: str) -> str:
        """Return the concrete API path (relative to /api/v1) for a resource
        operation, discovered from the backend's own OpenAPI document."""
        keywords = RESOURCE_KEYWORDS[resource]
        spec_paths = self._openapi()["paths"]
        matches = []
        for raw_path, methods in spec_paths.items():
            if not raw_path.startswith(API_PREFIX) or not isinstance(methods, dict):
                continue
            rel = raw_path[len(API_PREFIX):]
            templated = "{" in rel
            for http_method, operation in methods.items():
                hay = f"{rel} {json.dumps(operation.get('tags') or [])} {operation.get('operationId') or ''}".lower()
                if not any(word in hay for word in keywords):
                    continue
                if verb == "create" and http_method.upper() != "POST":
                    continue
                if verb in ("list", "get") and http_method.upper() != "GET":
                    continue
                if verb == "list" and templated:
                    continue
                if verb == "get" and not templated:
                    continue
                score = sum(rel.lower().count(word) for word in keywords) + len(rel)
                matches.append((score, rel))
        if not matches:
            raise ClientError(
                f"Could not resolve the Vues '{resource}' {verb} endpoint from the API's OpenAPI "
                f"document; run `vues auth status` and report the available operations."
            )
        matches.sort(key=lambda row: (-row[0], row[1]))
        return matches[0][1]

    # ==================== Account ====================

    def account(self) -> dict:
        user = self._api("GET", "/users/me")
        if isinstance(user, dict) and isinstance(user.get("data"), dict):
            user = user["data"]
        if not isinstance(user, dict) or not user.get("id"):
            raise ClientError("Vues /users/me returned no user")
        return user

    # ==================== Campaigns ====================

    def list_campaigns(self, limit: Optional[int] = 100) -> List[dict]:
        if limit is not None and limit < 1:
            raise ClientError("--limit must be at least 1")
        rows = _as_list(self._api("GET", "/campaigns"))
        return rows if limit is None else rows[:limit]

    def get_campaign(self, campaign_id: str) -> dict:
        document = self._api("GET", f"/campaigns/{campaign_id}")
        return document["data"] if isinstance(document, dict) and isinstance(document.get("data"), dict) else document

    def join_campaign(self, campaign_id: str, dry_run: bool) -> dict:
        path = self.resolve("join", "create").replace("{id}", campaign_id).replace("{campaign_id}", campaign_id)
        request = {"method": "POST", "url": f"{self.base_url}{API_PREFIX}{path}"}
        if dry_run:
            return {"status": "dry_run", "campaign_id": campaign_id, "request": request}
        data = self._api("POST", path)
        return {"status": "applied", "campaign_id": campaign_id, "application": data}

    # ==================== Linked accounts ====================

    def social_accounts(self, limit: Optional[int] = 100) -> List[dict]:
        rows = _as_list(self._api("GET", self.resolve("social_accounts", "list")))
        return rows if limit is None else rows[:limit]

    # ==================== Earnings ====================

    def earnings(self) -> dict:
        document = self._api("GET", self.resolve("earnings", "list"))
        return document["data"] if isinstance(document, dict) and isinstance(document.get("data"), dict) else document

    # ==================== Submissions ====================

    def submissions(self, campaign_id: Optional[str] = None, limit: Optional[int] = 100) -> List[dict]:
        params = {"campaign_id": campaign_id} if campaign_id else None
        rows = _as_list(self._api("GET", self.resolve("submissions", "list"), params=params))
        if campaign_id:
            rows = [row for row in rows if str(row.get("campaign_id") or row.get("campaignId") or "") == campaign_id]
        return rows if limit is None else rows[:limit]

    def submission(self, submission_id: str) -> dict:
        path = self.resolve("submissions", "get").replace("{id}", submission_id).replace(
            "{submission_id}", submission_id)
        document = self._api("GET", path)
        return document["data"] if isinstance(document, dict) and isinstance(document.get("data"), dict) else document

    def _existing_submission(self, campaign_id: str, post_video_id: str) -> Optional[dict]:
        for row in self.submissions(campaign_id, limit=None):
            url = row.get("post_url") or row.get("postUrl") or row.get("video_url") or row.get("url")
            if video_id(url) == post_video_id:
                return row
        return None

    def create_submission(self, campaign_id: str, url: str, dry_run: bool) -> dict:
        canonical, _username, post_video_id = tiktok_post(url)
        existing = self._existing_submission(campaign_id, post_video_id)
        if existing:
            return {"status": "existing", "submission": existing, "url": canonical}
        path = self.resolve("submissions", "create")
        body = {"campaign_id": campaign_id, "url": canonical}
        request = {"method": "POST", "url": f"{self.base_url}{API_PREFIX}{path}", "body": body}
        if dry_run:
            return {"status": "dry_run", "submission": None, "url": canonical, "request": request}
        try:
            data = self._api("POST", path, body=body)
        except ClientError as exc:
            # A write can commit yet fail in transit; look before reporting failure.
            found = self._existing_submission(campaign_id, post_video_id)
            if found:
                return {"status": "created", "submission": found, "url": canonical}
            raise ClientError(f"Vues submission failed: {exc}") from None
        return {"status": "created", "submission": self._existing_submission(campaign_id, post_video_id) or data,
                "url": canonical, "response": data}


_client: Optional[VuesClient] = None


def get_client() -> VuesClient:
    global _client
    if _client is None:
        _client = VuesClient()
    return _client
