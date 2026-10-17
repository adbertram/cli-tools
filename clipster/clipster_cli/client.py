"""Clipster API client: public campaign catalog plus the authenticated creator app API.

Endpoints, bodies and headers come from the www.clipster.gg web app bundle and
live calls against api.clipster.gg (verified 2026-10-14).
"""

import fcntl
import json
import os
import random
import re
import shutil
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urlsplit

import requests
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError, CredentialError
from cli_tools_shared.output import print_info
from dotenv import dotenv_values

from . import __version__
from .config import TOKEN_FIELDS, get_config

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

CAMPAIGNS_ENDPOINT = "/campaigns/public"
PAGE_SIZE = 100
APP_PAGE_SIZE = 20  # the web app's own page size for creator lists
REQUEST_TIMEOUT = 30
CAMPAIGN_WEB_URL = "https://www.clipster.gg/discover?openedCampaignId=%s"
# The API answers Python's default User-Agent with HTTP 403 (measured 2026-10-14).
USER_AGENT = f"clipster-cli/{__version__}"
CATALOG_CACHE_TTL = 300

USER_KIND = "Creator"
TIKTOK = "SOCIAL_MEDIA_PLATFORM_TIKTOK"
PROFILE_URLS = {"tiktok": "https://www.tiktok.com/@%s"}
REFRESH_MARGIN = timedelta(minutes=5)

PASSCODE_SENDER = "no-reply@clipster.gg"
PASSCODE_PATTERN = re.compile(r"code \(OTP\) is (\d{6})")
PASSCODE_TIMEOUT = 120
PASSCODE_POLL_SECONDS = 3


def normalize_campaign(raw: dict) -> dict:
    """Return the API row unchanged plus the campaign's web page URL."""
    if not isinstance(raw, dict) or "id" not in raw:
        raise ClientError("Clipster campaign row has no id")
    return {**raw, "web_url": CAMPAIGN_WEB_URL % raw["id"]}


def tiktok_post(url: str) -> tuple:
    """Return (canonical URL, username, video id) for a full TikTok post URL."""
    parsed = urlsplit(url.strip())
    match = re.fullmatch(r"/@([A-Za-z0-9_.]{1,24})/video/([0-9]+)/?", parsed.path)
    if parsed.scheme != "https" or parsed.netloc not in ("www.tiktok.com", "tiktok.com") or not match:
        raise ClientError("--url must be a full https://www.tiktok.com/@<user>/video/<id> post URL")
    username, video_id = match[1].lower(), match[2]
    return f"https://www.tiktok.com/@{username}/video/{video_id}", username, video_id


def video_id(url) -> Optional[str]:
    match = re.search(r"/video/([0-9]+)", url) if isinstance(url, str) else None
    return match[1] if match else None


def _expired(stamp: Optional[str], margin: timedelta = timedelta(0)) -> bool:
    if not stamp:
        return True
    try:
        moment = datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", stamp).replace("Z", "+00:00"))
    except ValueError:
        return True
    return moment - margin <= datetime.now(timezone.utc)


def _google(*args: str) -> str:
    """Run the `google` CLI (Gmail access goes through it, never the raw Gmail API)."""
    if shutil.which("google") is None:
        raise CredentialError("The `google` CLI is required to read the Clipster passcode email")
    result = subprocess.run(["google", *args], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise CredentialError(f"google {' '.join(args[:2])} failed: {result.stderr.strip()[:300]}")
    return result.stdout


class ClipsterClient:
    """Client for Clipster's public catalog and authenticated creator API."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = config or get_config()
        self.base_url = self.config.base_url
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        # X-Fee-Model matches the web app; it selects the current fee model in money fields.
        self.headers = {"Accept": "application/json", "User-Agent": USER_AGENT, "X-Fee-Model": "v2"}

    # ==================== Transport ====================

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        return min(delay + random.uniform(-jitter_range, jitter_range), self.max_delay)

    def _is_retryable(self, response: Optional[requests.Response], exception: Optional[Exception]) -> bool:
        if exception is not None:
            return isinstance(
                exception,
                (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError,
                ),
            )
        return response is not None and response.status_code in RETRYABLE_STATUS_CODES

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        try:
            return float(response.headers["Retry-After"])
        except (KeyError, ValueError):
            return None

    def _send(self, method: str, endpoint: str, params=None, body=None, token=None) -> requests.Response:
        """Send one request; only GETs are retried, so a write is never repeated."""
        url = f"{self.base_url}{endpoint}"
        headers = dict(self.headers)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        retries = self.max_retries if method == "GET" else 0
        response: Optional[requests.Response] = None
        error: Optional[Exception] = None
        for attempt in range(retries + 1):
            response, error = None, None
            try:
                response = requests.request(method, url, headers=headers, params=params, json=body,
                                            timeout=REQUEST_TIMEOUT)
            except requests.exceptions.RequestException as exc:
                error = exc
            if attempt < retries and self._is_retryable(response, error):
                retry_after = self._get_retry_after(response) if response is not None else None
                time.sleep(self._calculate_retry_delay(attempt, retry_after))
                continue
            break
        if response is None:
            raise ClientError(f"{method} {endpoint} failed: {error}")
        return response

    @staticmethod
    def _document(response: requests.Response):
        try:
            document = response.json()
        except ValueError as exc:
            if not response.ok:
                raise ClientError(f"HTTP {response.status_code}: {response.text[:500]}") from exc
            raise ClientError(f"Clipster returned a non-JSON response: {exc}") from exc
        if not response.ok:
            error = document.get("error") if isinstance(document, dict) else None
            if isinstance(error, dict):
                raise ClientError(f"HTTP {response.status_code} {error.get('code')}: {error.get('message')}")
            raise ClientError(f"HTTP {response.status_code}: {response.text[:500]}")
        return document

    def _get_json(self, endpoint: str, params: dict) -> dict:
        """Public, unauthenticated GET."""
        return self._document(self._send("GET", endpoint, params=params))

    # ==================== Session ====================

    def _tokens(self) -> dict:
        """Read the saved session fresh from the profile file (another process may have rotated it)."""
        values = dotenv_values(self.config.env_file_path) if self.config.env_file_path.exists() else {}
        return {name: values.get(name) or None for name in TOKEN_FIELDS}

    def _save_session(self, data: dict) -> str:
        fields = {"ACCESS_TOKEN": "access_token", "REFRESH_TOKEN": "refresh_token",
                  "TOKEN_EXPIRES_AT": "expires_at", "REFRESH_EXPIRES_AT": "refresh_expires_at"}
        if not isinstance(data, dict) or not all(isinstance(data.get(key), str) and data[key] for key in fields.values()):
            raise CredentialError("Clipster session response is missing tokens")
        for name, key in fields.items():
            self.config._set(name, data[key])
        os.chmod(self.config.env_file_path, 0o600)
        return data["access_token"]

    @contextmanager
    def _auth_lock(self):
        """Serialize refresh and login across processes; refresh tokens are single-use."""
        path = self.config.get_profile_data_dir() / "auth.lock"
        with open(path, "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _email(self) -> str:
        email = self.config._get("EMAIL")
        if not email:
            raise CredentialError("No Clipster account email saved: run `clipster auth login`")
        return email

    def _passcode_ids(self, email: str) -> set:
        query = f'from:{PASSCODE_SENDER} to:{email} subject:"One-Time Passcode"'
        rows = json.loads(_google("gmail", "search", query, "--limit", "10", "--properties", "id"))
        return {row["id"] for row in rows}

    def _wait_for_passcode(self, email: str, known: set) -> str:
        deadline = time.monotonic() + PASSCODE_TIMEOUT
        while time.monotonic() < deadline:
            time.sleep(PASSCODE_POLL_SECONDS)
            for message_id in self._passcode_ids(email) - known:
                match = PASSCODE_PATTERN.search(json.loads(_google("gmail", "read", message_id)).get("body", ""))
                if match:
                    return match[1]
        raise CredentialError(f"No Clipster passcode email reached Gmail within {PASSCODE_TIMEOUT}s")

    def login(self) -> str:
        """Email passcode login: request a code, read it from Gmail, exchange it for tokens."""
        with self._auth_lock():
            return self._login()

    def _login(self) -> str:
        email = self._email()
        known = self._passcode_ids(email)
        started = self._document(self._send("POST", "/auth/initialize", body={"email": email, "user_kind": USER_KIND}))
        auth_id = (started.get("data") or {}).get("auth_id")
        if not auth_id:
            raise CredentialError("Clipster did not return an auth_id for the passcode request")
        print_info(f"Passcode requested for {email}; reading it from Gmail")
        code = self._wait_for_passcode(email, known)
        finished = self._document(self._send("POST", "/auth/finalize", body={"auth_id": auth_id, "code": code}))
        data = finished.get("data") or {}
        if data.get("account_type") != "creator":
            raise CredentialError(f"{email} is not a Clipster creator account (account_type={data.get('account_type')})")
        return self._save_session(data)

    def _renew(self, stale_token: Optional[str], allow_login: bool) -> str:
        """Return a usable access token: another process's, a refreshed one, or (if allowed) a new login."""
        with self._auth_lock():
            tokens = self._tokens()
            if tokens["ACCESS_TOKEN"] and tokens["ACCESS_TOKEN"] != stale_token \
                    and not _expired(tokens["TOKEN_EXPIRES_AT"], REFRESH_MARGIN):
                return tokens["ACCESS_TOKEN"]
            if tokens["REFRESH_TOKEN"] and not _expired(tokens["REFRESH_EXPIRES_AT"]):
                response = self._send("POST", "/auth/refresh", body={"refresh_token": tokens["REFRESH_TOKEN"]})
                if response.ok:
                    return self._save_session(self._document(response).get("data"))
                if response.status_code not in (400, 401):
                    self._document(response)  # raises: transient failure, keep the session
            if not allow_login:
                raise CredentialError("Clipster session expired and could not be refreshed: run `clipster auth login`")
            return self._login()

    def _authed(self, method: str, endpoint: str, params=None, body=None, allow_login: bool = True):
        tokens = self._tokens()
        token = tokens["ACCESS_TOKEN"]
        if not token or _expired(tokens["TOKEN_EXPIRES_AT"], REFRESH_MARGIN):
            token = self._renew(token, allow_login)
        response = self._send(method, endpoint, params=params, body=body, token=token)
        if response.status_code == 401:
            response = self._send(method, endpoint, params=params, body=body,
                                  token=self._renew(token, allow_login))
        return self._document(response)

    def _data(self, endpoint: str, params=None, allow_login: bool = True):
        return self._authed("GET", endpoint, params=params, allow_login=allow_login).get("data")

    @staticmethod
    def _paginate(get, key: str, limit: Optional[int], page_size: int) -> List[dict]:
        """Read `data.<key>` pages until `limit` rows are collected or the last page is read."""
        if limit is not None and limit < 1:
            raise ClientError("--limit must be at least 1")
        rows: List[dict] = []
        page, total_pages = 1, 1
        while page <= total_pages and (limit is None or len(rows) < limit):
            document = get({"page": page, "limit": page_size})
            data = document.get("data") if isinstance(document, dict) else None
            found = data.get(key) if isinstance(data, dict) else None
            if not isinstance(found, list):
                raise ClientError(f"Clipster {key} list did not return a list")
            rows += found
            try:
                total_pages = int(((document.get("metadata") or {}).get("pagination") or {}).get("total_pages") or 0)
            except (TypeError, ValueError) as exc:
                raise ClientError(f"Clipster pagination total_pages is not a number: {exc}") from exc
            page += 1
        return rows if limit is None else rows[:limit]

    def _pages(self, endpoint: str, key: str, limit: Optional[int], params=None) -> List[dict]:
        return self._paginate(lambda paging: self._authed("GET", endpoint, params={**(params or {}), **paging}),
                              key, limit, APP_PAGE_SIZE)

    # ==================== Public catalog ====================

    @cached(ttl=CATALOG_CACHE_TTL)
    def list_campaigns(self, limit: Optional[int] = PAGE_SIZE) -> List[dict]:
        page_size = PAGE_SIZE if limit is None else min(max(limit, 1), PAGE_SIZE)
        rows = self._paginate(lambda paging: self._get_json(CAMPAIGNS_ENDPOINT, paging), "campaigns", limit, page_size)
        return [normalize_campaign(row) for row in rows]

    # ==================== Creator account ====================

    def account(self, allow_login: bool = True) -> dict:
        data = self._data("/auth/identify", allow_login=allow_login) or {}
        user = data.get("user")
        if not isinstance(user, dict) or not user.get("id") or not user.get("email"):
            raise ClientError("Clipster /auth/identify returned no user")
        return {**user, **{key: value for key, value in data.items() if key != "user"}}

    def social_accounts(self) -> List[dict]:
        document = self._authed("GET", "/accounts")
        pagination = (document.get("metadata") or {}).get("pagination") or {}
        if not isinstance(document.get("data"), list):
            raise ClientError("Clipster /accounts did not return a list")
        if int(pagination.get("total_pages") or 0) > 1:
            raise ClientError("Clipster /accounts returned more than one page; paging is not supported")
        return document["data"]

    def social_account(self, account_id: str) -> dict:
        """Clipster has no single-account route; find it in the linked-account list."""
        for row in self.social_accounts():
            if row.get("account_id") == account_id:
                return row
        raise ClientError(f"Linked account not found: {account_id}")

    def account_posts(self, account_id: str) -> List[dict]:
        """Recent posts Clipster read from a linked account (what the web app's post picker shows)."""
        rows = self._data(f"/accounts/{account_id}/posts")
        if not isinstance(rows, list):
            raise ClientError("Clipster account posts did not return a list")
        return rows

    def _write(self, endpoint: str, body: dict, dry_run: bool):
        if dry_run:
            return {"status": "dry_run", "request": {"method": "POST", "url": f"{self.base_url}{endpoint}", "body": body}}
        return self._authed("POST", endpoint, body=body).get("data")

    def link_social_account(self, platform: str, username: str, dry_run: bool) -> dict:
        """Start bio-code linking; the code goes in the account bio before `verify`."""
        if platform not in PROFILE_URLS:
            raise ClientError(f"--platform must be one of: {', '.join(PROFILE_URLS)}")
        return self._write("/accounts/initialize", {"profile_url": PROFILE_URLS[platform] % username.lstrip("@")}, dry_run)

    def verify_social_account(self, link_id: str, dry_run: bool) -> dict:
        return self._write("/accounts/finalize", {"link_id": link_id}, dry_run)

    def earnings(self) -> dict:
        return {**(self._data("/balance") or {}), **(self._data("/users/statistics") or {})}

    def transactions(self, limit: Optional[int]) -> List[dict]:
        return self._pages("/balance/transactions", "transactions", limit)

    # ==================== Campaigns ====================

    def get_campaign(self, campaign_id: str) -> dict:
        """Authenticated detail plus this account's eligibility (the web app's application state)."""
        row = normalize_campaign(self._data(f"/campaigns/{campaign_id}"))
        return {**row, "account_eligibility": self._data(f"/campaigns/{campaign_id}/account-eligibility")}

    def join_campaign(self, campaign_id: str, dry_run: bool) -> dict:
        """Open campaigns need no join; application-only campaigns take an application."""
        campaign = self.get_campaign(campaign_id)
        application = (campaign["account_eligibility"] or {}).get("application")
        if not campaign.get("is_application_only"):
            return {"status": "not_required", "campaign_id": campaign_id, "application": application}
        if application:
            return {"status": "existing", "campaign_id": campaign_id, "application": application}
        if dry_run:
            return {"status": "dry_run", "campaign_id": campaign_id,
                    "request": {"method": "POST", "url": f"{self.base_url}/campaigns/{campaign_id}/applications"}}
        data = self._authed("POST", f"/campaigns/{campaign_id}/applications").get("data")
        return {"status": "applied", "campaign_id": campaign_id, "application": data}

    # ==================== Submissions ====================

    def submissions(self, campaign_id: Optional[str] = None, limit: Optional[int] = PAGE_SIZE) -> List[dict]:
        params = {"campaign_id": campaign_id} if campaign_id else None
        return self._pages("/submissions/submission-requests", "submissions_with_requests", limit, params)

    def submission(self, submission_id: str) -> dict:
        return self._data(f"/submissions/submission-requests/{submission_id}")

    def _existing_submission(self, campaign_id: str, post_video_id: str) -> Optional[dict]:
        for row in self.submissions(campaign_id, limit=None):
            if row.get("campaign_id") == campaign_id and video_id(row.get("post_url")) == post_video_id:
                return row
        return None

    def _submission_blocker(self, campaign: dict, username: str) -> Optional[str]:
        """Return why Clipster would refuse this submission, or None."""
        accounts = [row for row in self.social_accounts()
                    if row.get("platform") == TIKTOK and str(row.get("username", "")).lower() == username]
        if not accounts:
            return f"tiktok_account_not_linked: @{username}"
        eligibility = campaign.get("account_eligibility") or {}
        if campaign.get("status") != "CAMPAIGN_STATUS_ACTIVE":
            return f"campaign_not_active: {campaign.get('status')}"
        if campaign.get("disable_dashboard_submissions"):
            return "campaign_submissions_closed"
        if TIKTOK not in (campaign.get("allowed_platforms") or []):
            return "campaign_does_not_accept_tiktok"
        if campaign.get("is_application_only") and (eligibility.get("application") or {}).get("status") != "APPROVED":
            return "campaign_application_not_approved: run `clipster campaigns join`"
        checked = [row for row in eligibility.get("accounts") or [] if row.get("account_id") == accounts[0]["account_id"]]
        if not checked or checked[0].get("eligible") is not True:
            return f"account_not_eligible: @{username}"
        return None

    def create_submission(self, campaign_id: str, url: str, dry_run: bool) -> dict:
        canonical, username, post_video_id = tiktok_post(url)
        existing = self._existing_submission(campaign_id, post_video_id)
        if existing:
            return {"status": "existing", "submission": existing, "url": canonical}
        blocker = self._submission_blocker(self.get_campaign(campaign_id), username)
        if blocker:
            raise ClientError(f"Submission refused before sending: {blocker}")
        endpoint = f"/campaigns/{campaign_id}/submissions-async"
        body = {"campaign_id": campaign_id, "content_list": [{"content_url": canonical}]}
        if dry_run:
            return {"status": "dry_run", "submission": None, "url": canonical,
                    "request": {"method": "POST", "url": f"{self.base_url}{endpoint}", "body": body}}
        try:
            response = self._authed("POST", endpoint, body=body)
        except ClientError as exc:
            # A write can commit and still fail in transit; look before reporting failure.
            found = self._existing_submission(campaign_id, post_video_id)
            if found:
                return {"status": "created", "submission": found, "url": canonical}
            raise ClientError(f"Submission failed: {exc}") from exc
        return {"status": "created", "submission": self._existing_submission(campaign_id, post_video_id),
                "url": canonical, "response": response.get("data")}


_client: Optional[ClipsterClient] = None


def get_client() -> ClipsterClient:
    """Get or create the global Clipster client instance."""
    global _client
    if _client is None:
        _client = ClipsterClient()
    return _client
