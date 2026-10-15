"""Vues API client: HTTP against the Vues backend (api.evrgreen.ai) using the
Supabase session captured once at browser login.

Everything below the login step is plain HTTP. The Supabase session (access and
refresh tokens) is read out of the vues.app session cookie after Google/Apple
sign-in, saved as runtime auth state, and refreshed over HTTP against Supabase
GoTrue when it expires -- no browser is opened again.

Routes and envelopes come from the signed-in Vues clipper web app's own API
module and live calls (verified 2026-10-15):
  * base https://api.evrgreen.ai, version prefix /api/v1
  * success: {"status":"success","code":200,"message":...,"data":...}
  * errors:  {"status":"error","code":N,"message":"..."}
  * clipper routes: GET /users/me, /clipper/campaigns (offset/limit paging),
    /clipper/campaigns/{id or short_id}, POST /clipper/campaigns/{id}/apply,
    GET /clipper/bundle/accounts?grouped=true, GET /clipper/submissions
    (offset/limit/campaign_id), POST /clipper/submissions
    {campaign_id, post_links} then GET /clipper/submissions/batches/{batch_id},
    GET /clipper/balance and /clipper/stats.
  * organizations (a clipper only sees campaigns of orgs they belong to):
    GET /organizations/discoverable (offset/limit paging), GET /clipper/orgs,
    GET /clipper/applications, POST /organizations/{id}/apply {"message": str|null}
    (the web app's own "Join now" / "Send application" call, from its JS bundle).
There is no single-submission GET route (405), so `submission()` pages the list.
The brand-side /campaigns route answers 403 "Enterprise access required" for a
clipper, and /api/openapi.json answers 401 even with a valid session.
"""

import base64
import json
import random
import re
import time
from typing import List, Optional
from urllib.parse import urlsplit

import requests
from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError
from cli_tools_shared.exceptions import ClientError, CredentialError

from .config import SUPABASE_ANON_KEY, SUPABASE_REF, SUPABASE_URL, TOKEN_FIELDS, get_config

API_PREFIX = "/api/v1"
REQUEST_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
REFRESH_MARGIN = 60  # seconds before expiry to renew
PAGE_SIZE = 100  # the web app's own largest page
BATCH_POLL_ATTEMPTS = 90
BATCH_POLL_START = 0.8
BATCH_POLL_MAX = 5.0
PENDING_BATCH_STATUSES = {"queued", "processing"}
TIKTOK_PLATFORM = "TIKTOK"
APP_URL = "https://vues.app/clipper"
SESSION_COOKIE = f"sb-{SUPABASE_REF}-auth-token"
NO_ACCOUNT_HELP = (
    "If you have no Vues account yet, sign up free at https://vues.app/login with "
    "Google or Apple, link your TikTok account in the Vues app, then run "
    "`vues auth login` again."
)


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

    # ==================== Session parsing (login only) ====================

    @staticmethod
    def parse_supabase_session(items: List[dict], storage_key: str) -> dict:
        """Assemble the Supabase session from ``{"key", "value"}`` storage entries
        (the vues.app session cookies).

        Handles @supabase/ssr (``base64-`` prefixed base64url, possibly chunked
        across ``<key>.0``, ``<key>.1`` ...), supabase-js v2 (the session object
        stored directly) and gotrue-js v1 (wrapped under ``currentSession``)."""
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
                encoded = raw[len("base64-"):]
                raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8")
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

    # ==================== Session (HTTP) ====================

    def save_session(self, session: dict) -> None:
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
            # A rejected refresh token is dead for good; drop the saved session so
            # `auth status` reports it and `auth login` signs in again.
            for field in TOKEN_FIELDS:
                self.config._clear(field)
            raise CredentialError("Vues session expired and could not be refreshed: run `vues auth login`")
        data = response.json()
        access = data.get("access_token")
        new_refresh = data.get("refresh_token") or refresh_token
        if not isinstance(access, str) or not access:
            raise CredentialError("Vues session refresh returned no access token")
        expires_at = data.get("expires_at") or (int(time.time()) + int(data.get("expires_in") or 3600))
        self.save_session({"access_token": access, "refresh_token": new_refresh,
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

    def _data(self, method: str, path: str, params=None, body=None):
        """Call the API and return the ``data`` of its success envelope."""
        document = self._api(method, path, params=params, body=body)
        if not isinstance(document, dict) or "data" not in document:
            raise ClientError(f"Vues {method} {path} returned no data envelope")
        return document["data"]

    def _paged(self, path: str, limit: Optional[int], params: Optional[dict] = None) -> List[dict]:
        """Collect ``items`` across offset/limit pages until ``total`` or ``limit``."""
        if limit is not None and limit < 1:
            raise ClientError("--limit must be at least 1")
        rows: List[dict] = []
        while limit is None or len(rows) < limit:
            size = PAGE_SIZE if limit is None else min(PAGE_SIZE, limit - len(rows))
            page = self._data("GET", path, params={**(params or {}), "offset": len(rows), "limit": size})
            items = page.get("items") if isinstance(page, dict) else None
            if not isinstance(items, list):
                raise ClientError(f"Vues {path} returned no items list")
            rows.extend(items)
            if not items or len(rows) >= int(page.get("total") or 0):
                break
        return rows if limit is None else rows[:limit]

    # ==================== Account ====================

    def account(self) -> dict:
        user = self._data("GET", "/users/me")
        if not isinstance(user, dict) or not user.get("id"):
            raise ClientError("Vues /users/me returned no user")
        return user

    # ==================== Campaigns ====================

    def list_campaigns(self, limit: Optional[int] = 100) -> List[dict]:
        return self._paged("/clipper/campaigns", limit)

    def get_campaign(self, campaign_id: str) -> dict:
        """One campaign by its id or short_id."""
        return self._data("GET", f"/clipper/campaigns/{campaign_id}")

    def join_campaign(self, campaign_id: str, dry_run: bool) -> dict:
        campaign = self.get_campaign(campaign_id)
        path = f"/clipper/campaigns/{campaign['id']}/apply"
        request = {"method": "POST", "url": f"{self.base_url}{API_PREFIX}{path}", "body": {}}
        if dry_run:
            return {"status": "dry_run", "campaign_id": campaign["id"], "request": request}
        data = self._data("POST", path, body={})
        return {"status": "applied", "campaign_id": campaign["id"], "application": data}

    # ==================== Organizations ====================

    def _rows(self, path: str, limit: Optional[int]) -> List[dict]:
        rows = self._data("GET", path)
        if not isinstance(rows, list):
            raise ClientError(f"Vues {path} returned no list")
        return rows if limit is None else rows[:limit]

    def discoverable_organizations(self, limit: Optional[int] = 100) -> List[dict]:
        return self._paged("/organizations/discoverable", limit)

    def get_organization(self, org_id: str) -> dict:
        """One discoverable organization by its id or short_id."""
        org = next((row for row in self.discoverable_organizations(None) if org_id in (row.get("id"), row.get("short_id"))), None)
        if org is None:
            raise ClientError(f"Vues organization {org_id} is not in `vues organizations list`")
        return org

    def member_organizations(self, limit: Optional[int] = 100) -> List[dict]:
        return self._rows("/clipper/orgs", limit)

    def organization_applications(self, limit: Optional[int] = 100) -> List[dict]:
        return self._rows("/clipper/applications", limit)

    def join_organization(self, org_id: str, message: Optional[str], dry_run: bool) -> dict:
        """Join an auto-approve org or apply to a manual-approval one, once.

        Membership and existing applications are checked first; either returns
        ``status: existing`` and nothing is sent."""
        org = self.get_organization(org_id)
        if org.get("is_member") or any(org["id"] in (row.get("id"), row.get("organization_id")) for row in self.member_organizations(None)):
            return {"status": "existing", "reason": "member", "organization": org}
        application = next((row for row in self.organization_applications(None)
                            if (row.get("organization") or {}).get("id") == org["id"]), None)
        if application:
            return {"status": "existing", "reason": "application", "organization": org, "application": application}
        path = f"/organizations/{org['id']}/apply"
        body = {"message": (message or "").strip() or None}
        if dry_run:
            return {"status": "dry_run", "organization": org,
                    "request": {"method": "POST", "url": f"{self.base_url}{API_PREFIX}{path}", "body": body}}
        data = self._data("POST", path, body=body)
        return {"status": "joined" if org.get("auto_approve_applications") else "applied",
                "organization": org, "application": data}

    # ==================== Linked accounts ====================

    def social_accounts(self, limit: Optional[int] = 100) -> List[dict]:
        data = self._data("GET", "/clipper/bundle/accounts", params={"grouped": "true"})
        rows = data if isinstance(data, list) else data.get("connected") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise ClientError("Vues /clipper/bundle/accounts returned no connected accounts list")
        return rows if limit is None else rows[:limit]

    # ==================== Earnings ====================

    def earnings(self) -> dict:
        """Wallet balance (micro-dollars) and lifetime clipper stats, verbatim."""
        return {"balance": self._data("GET", "/clipper/balance"), "stats": self._data("GET", "/clipper/stats")}

    # ==================== Submissions ====================

    def submissions(self, campaign_id: Optional[str] = None, limit: Optional[int] = 100) -> List[dict]:
        params = {"campaign_id": self.get_campaign(campaign_id)["id"]} if campaign_id else None
        return self._paged("/clipper/submissions", limit, params)

    def submission(self, submission_id: str) -> dict:
        for row in self.submissions(limit=None):
            if str(row.get("id")) == submission_id:
                return row
        raise ClientError(f"Vues submission {submission_id} not found")

    def _existing_submission(self, campaign_uuid: str, post_video_id: str) -> Optional[dict]:
        rows = self._paged("/clipper/submissions", None, {"campaign_id": campaign_uuid})
        return next((row for row in rows if video_id(row.get("post_link")) == post_video_id), None)

    def _batch_result(self, batch: dict, post_link: str) -> Optional[dict]:
        results = batch.get("results") if isinstance(batch, dict) else None
        if not isinstance(results, list):
            raise ClientError("Vues submission batch returned no results")
        result = next((row for row in results if row.get("post_link") == post_link),
                      results[0] if len(results) == 1 else None)
        if result is None or result.get("status") in PENDING_BATCH_STATUSES:
            return None
        return result

    def create_submission(self, campaign_id: str, url: str, dry_run: bool) -> dict:
        canonical, _username, post_video_id = tiktok_post(url)
        campaign = self.get_campaign(campaign_id)
        if not campaign.get("submissions_enabled", True):
            raise ClientError(f"Vues campaign {campaign_id} is not accepting submissions")
        platforms = [str(p).upper() for p in campaign.get("supported_platforms") or []]
        if platforms and TIKTOK_PLATFORM not in platforms:
            raise ClientError(f"Vues campaign {campaign_id} accepts only {', '.join(platforms)}, not TikTok")
        existing = self._existing_submission(campaign["id"], post_video_id)
        if existing:
            return {"status": "existing", "submission": existing, "url": canonical}
        path = "/clipper/submissions"
        body = {"campaign_id": campaign["id"], "post_links": [canonical]}
        request = {"method": "POST", "url": f"{self.base_url}{API_PREFIX}{path}", "body": body}
        if dry_run:
            return {"status": "dry_run", "submission": None, "url": canonical, "request": request}
        batch = self._data("POST", path, body=body)
        result = self._batch_result(batch, canonical)
        delay = BATCH_POLL_START
        for _ in range(BATCH_POLL_ATTEMPTS):
            if result is not None:
                break
            time.sleep(delay)
            delay = min(delay * 1.3, BATCH_POLL_MAX)
            result = self._batch_result(self._data("GET", f"/clipper/submissions/batches/{batch['batch_id']}"),
                                        canonical)
        if result is None:
            raise ClientError(f"Vues submission batch {batch.get('batch_id')} is still processing; "
                              f"check `vues submissions list --campaign-id {campaign['id']}`")
        if result.get("status") != "created":
            raise ClientError(f"Vues rejected the submission: {result.get('detail') or result.get('status')}")
        return {"status": "created", "submission": self._existing_submission(campaign["id"], post_video_id) or result,
                "url": canonical, "batch_id": batch.get("batch_id")}


def save_browser_session(browser: BrowserAutomation, page) -> None:
    """Post-login hook for ``VuesBrowser``: save the signed-in Supabase session.

    Runs on the headed login page right after the person presses Enter. Opens
    the clipper app, requires the session cookie, saves its tokens for HTTP use
    and proves them with a live /users/me call."""
    page.goto(APP_URL)
    page.wait_for_timeout(2000)
    cookies = browser._get_auth_cookies(page.cookie_list())
    if not cookies:
        raise BrowserAutomationError(f"Vues is not signed in at {APP_URL}. {NO_ACCOUNT_HELP}")
    client = VuesClient(config=browser.config)
    client.save_session(VuesClient.parse_supabase_session(
        [{"key": cookie["name"], "value": cookie["value"]} for cookie in cookies], SESSION_COOKIE))
    try:
        client.account()
    except ClientError as exc:
        raise BrowserAutomationError(f"Signed in, but Vues has no creator account: {exc}. {NO_ACCOUNT_HELP}") from None


_client: Optional[VuesClient] = None


def get_client() -> VuesClient:
    global _client
    if _client is None:
        _client = VuesClient()
    return _client
