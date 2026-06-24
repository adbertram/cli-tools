"""LinkedIn API client."""

import fnmatch
import random
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

import requests
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .config import get_config

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
CURRENT_MEMBER_PROFILE_URL = "https://api.linkedin.com/v2/me"
CURRENT_MEMBER_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
PERSON_URN_PREFIX = "urn:li:person:"
ORGANIZATION_URN_PREFIXES = ("urn:li:organization:", "urn:li:organizationBrand:")


def _timestamp_ms_to_iso(timestamp_ms: Optional[int]) -> Optional[str]:
    if timestamp_ms is None:
        return None
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).isoformat()


def _content_type(raw: dict) -> str:
    content = raw.get("content")
    if not content:
        return "text"
    if not isinstance(content, dict):
        raise ClientError("Expected 'content' to be an object.")
    if len(content) != 1:
        raise ClientError(f"Expected one LinkedIn content type, got {list(content.keys())}")
    return next(iter(content.keys()))


def normalize_post(raw: dict) -> dict:
    """Map one LinkedIn post to the public CLI record shape."""
    return {
        "id": raw["id"],
        "author": raw["author"],
        "commentary": raw.get("commentary", ""),
        "visibility": raw["visibility"],
        "lifecycle_state": raw["lifecycleState"],
        "feed_distribution": raw["distribution"]["feedDistribution"],
        "content_type": _content_type(raw),
        "is_reshare_disabled_by_author": raw["isReshareDisabledByAuthor"],
        "created_at": _timestamp_ms_to_iso(raw.get("createdAt")),
        "published_at": _timestamp_ms_to_iso(raw.get("publishedAt")),
        "last_modified_at": _timestamp_ms_to_iso(raw.get("lastModifiedAt")),
    }


class LinkedInClient:
    """Client for interacting with LinkedIn APIs used by this CLI."""

    def __init__(
        self,
        *,
        config=None,
        session: Optional[requests.sessions.Session] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = config or get_config()
        if not self.config.has_api_credentials():
            missing = self.config.get_missing_api_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'linkedin auth login' to authenticate."
            )
        self.base_url = self.config.base_url
        self.session = session or requests
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    def _headers(self, *, versioned: bool) -> dict:
        headers = {
            "Authorization": f"Bearer {self.config.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if versioned:
            headers["X-Restli-Protocol-Version"] = "2.0.0"
            headers["Linkedin-Version"] = self.config.linkedin_version
        return headers

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        return min(delay + random.uniform(-jitter_range, jitter_range), self.max_delay)

    def _is_retryable(
        self,
        response: Optional[requests.Response],
        exception: Optional[Exception],
    ) -> bool:
        if exception is not None:
            return isinstance(
                exception,
                (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError,
                ),
            )
        if response is not None:
            return response.status_code in RETRYABLE_STATUS_CODES
        return False

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def _extract_error_detail(self, response: requests.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return response.text[:500]
        if isinstance(body, dict):
            if "message" in body:
                return str(body["message"])
            if "error_description" in body:
                return str(body["error_description"])
            if "serviceErrorCode" in body:
                return f"{body['serviceErrorCode']}: {body.get('message', body)}"
        return str(body)[:500]

    def _describe_posts_operation(
        self,
        *,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        if path.startswith("/rest/posts/"):
            if method == "GET":
                return "get post"
            if method == "POST":
                return "update post"
            if method == "DELETE":
                return "delete post"
            return None
        if path != "/rest/posts":
            return None
        if method == "GET" and params and params.get("q") == "author":
            return "list posts by author"
        if method == "POST":
            return "create post"
        return None

    def _describe_posts_author_type(self, author: Optional[str]) -> Optional[str]:
        if author is None:
            return None
        if author.startswith(PERSON_URN_PREFIX):
            return "member"
        if author.startswith(ORGANIZATION_URN_PREFIXES):
            return "organization or showcase-page"
        return None

    def _posts_permission_error(
        self,
        *,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]],
        data: Optional[Dict[str, Any]],
        permission_author: Optional[str],
        response: requests.Response,
    ) -> Optional[str]:
        if response.status_code != 403:
            return None

        detail = self._extract_error_detail(response)
        if "Not enough permissions to access:" not in detail:
            return None

        path = urlparse(url).path
        operation = self._describe_posts_operation(method=method, path=path, params=params)
        if operation is None:
            return None

        author = permission_author
        if author is None and params is not None and isinstance(params.get("author"), str):
            author = params["author"]
        elif author is None and data is not None and isinstance(data.get("author"), str):
            author = data["author"]

        author_type = self._describe_posts_author_type(author)
        if author_type is None:
            return None

        if method == "GET" and author_type == "member":
            requirement = (
                "This LinkedIn Posts API operation requires scope `r_member_social`. "
                "LinkedIn's FAQ says `r_member_social` is closed and requires approved access. "
                "For export-style personal share history, LinkedIn documents the separate "
                "Member Data Portability `MEMBER_SHARE_INFO` snapshot domain behind "
                "`r_dma_portability_3rd_party` or `r_dma_portability_member`."
            )
            next_action = (
                "Next action: use a LinkedIn app that already has approved member-post read access, "
                "then re-run `linkedin auth login --force` with `LINKEDIN_SCOPES` including "
                "`r_member_social`, or stop using `linkedin user posts list` with a token limited to "
                "`w_member_social`. If you want the Data Portability route instead, use a LinkedIn "
                "app approved for Member Data Portability and implement/read from "
                "`/rest/memberSnapshotData?domain=MEMBER_SHARE_INFO`."
            )
        elif method == "GET":
            requirement = (
                "This LinkedIn Posts API operation requires scope `r_organization_social`. "
                "LinkedIn grants organization read scopes through Community Management API or "
                "Advertising API approval."
            )
            next_action = (
                "Next action: get approved organization access for your LinkedIn app, then re-run "
                "`linkedin auth login --force` with `LINKEDIN_SCOPES` including "
                "`r_organization_social`."
            )
        elif author_type == "member":
            requirement = (
                "This LinkedIn Posts API operation requires scope `w_member_social`."
            )
            next_action = (
                "Next action: re-run `linkedin auth login --force` with `LINKEDIN_SCOPES` including "
                "`w_member_social` for the member account you are posting as."
            )
        else:
            requirement = (
                "This LinkedIn Posts API operation requires scope `w_organization_social`. "
                "LinkedIn grants organization write scopes through Community Management API or "
                "Advertising API approval."
            )
            next_action = (
                "Next action: get approved organization access for your LinkedIn app, then re-run "
                "`linkedin auth login --force` with `LINKEDIN_SCOPES` including "
                "`w_organization_social`."
            )

        article = "an" if author_type.startswith("organization") else "a"
        return (
            f"LinkedIn denied `{operation}` for {article} {author_type} author (`{author}`). "
            f"{requirement} {next_action} LinkedIn detail: {detail}"
        )

    def _request(
        self,
        method: str,
        url: str,
        *,
        versioned: bool,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        permission_author: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        retry: bool = True,
    ) -> requests.Response:
        headers = self._headers(versioned=versioned)
        if extra_headers:
            headers.update(extra_headers)

        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=data,
                    params=params,
                )
                last_response = response
                if retry and self._is_retryable(response, None) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt, self._get_retry_after(response)))
                    continue
                break
            except requests.exceptions.RequestException as exc:
                last_exception = exc
                if retry and self._is_retryable(None, exc) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt))
                    continue
                break

        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed after {attempt + 1} attempts: {last_exception}")
        if last_response is None:
            raise ClientError("Request failed: no response received")
        if not last_response.ok:
            permission_error = self._posts_permission_error(
                method=method,
                url=url,
                params=params,
                data=data,
                permission_author=permission_author,
                response=last_response,
            )
            if permission_error is not None:
                raise ClientError(permission_error)
            raise ClientError(
                f"HTTP {last_response.status_code}: {self._extract_error_detail(last_response)}"
            )
        return last_response

    def _request_api(
        self,
        method: str,
        endpoint: str,
        *,
        versioned: bool = True,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        permission_author: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        retry: bool = True,
    ) -> requests.Response:
        url = f"{self.base_url}{endpoint}"
        return self._request(
            method,
            url,
            versioned=versioned,
            data=data,
            params=params,
            permission_author=permission_author,
            extra_headers=extra_headers,
            retry=retry,
        )

    def _invalidate_post_read_caches(self) -> None:
        """Remove cached post reads after a successful post mutation."""
        cache_dir = Path(self.config.storage_dir) / "cache"
        if not cache_dir.exists():
            return
        for prefix in ("list_posts_", "get_post_", "search_posts_"):
            for cache_file in cache_dir.glob(f"{prefix}*.json"):
                if cache_file.is_file():
                    cache_file.unlink()

    @cached
    def list_posts(
        self,
        *,
        author: str,
        limit: int = 10,
        start: int = 0,
        sort_by: str = "LAST_MODIFIED",
    ) -> List[dict]:
        response = self._request_api(
            "GET",
            "/posts",
            params={
                "q": "author",
                "author": author,
                "count": limit,
                "start": start,
                "sortBy": sort_by,
            },
            extra_headers={"X-RestLi-Method": "FINDER"},
        )
        body = response.json()
        elements = body["elements"]
        if not isinstance(elements, list):
            raise ClientError("Expected 'elements' to be a list.")
        return [normalize_post(item) for item in elements]

    @cached
    def get_post(
        self,
        *,
        post_urn: str,
        view_context: str = "AUTHOR",
        permission_author: Optional[str] = None,
    ) -> dict:
        encoded_urn = quote(post_urn, safe="")
        response = self._request_api(
            "GET",
            f"/posts/{encoded_urn}",
            params={"viewContext": view_context},
            permission_author=permission_author,
        )
        return normalize_post(response.json())

    @cached
    def search_posts(
        self,
        *,
        query: str,
        author: str,
        limit: int = 10,
    ) -> List[dict]:
        pattern = query.lower()
        if "*" not in pattern:
            pattern = f"*{pattern}*"
        results = []
        for post in self.list_posts(author=author, limit=limit):
            if any(fnmatch.fnmatch(str(value).lower(), pattern) for value in post.values()):
                results.append(post)
        return results[:limit]

    def create_post(
        self,
        *,
        commentary: str,
        author: str,
        visibility: str = "PUBLIC",
        feed_distribution: str = "MAIN_FEED",
        disable_reshare: bool = False,
    ) -> dict:
        payload = {
            "author": author,
            "commentary": commentary,
            "visibility": visibility,
            "distribution": {
                "feedDistribution": feed_distribution,
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": disable_reshare,
        }
        response = self._request_api("POST", "/posts", data=payload)
        post_urn = response.headers.get("x-restli-id") or response.headers.get("X-RestLi-Id")
        if not post_urn:
            raise ClientError("LinkedIn create response did not include x-restli-id.")
        self._invalidate_post_read_caches()
        return {
            "id": post_urn,
            "author": author,
            "commentary": commentary,
            "visibility": visibility,
            "lifecycle_state": "PUBLISHED",
            "feed_distribution": feed_distribution,
            "content_type": "text",
            "is_reshare_disabled_by_author": disable_reshare,
            "created": True,
        }

    def _member_urn_from_identity_response(self, *, url: str, key: str) -> str:
        response = self._request("GET", url, versioned=False)
        body = response.json()
        member_id = body.get(key)
        if not isinstance(member_id, str) or not member_id:
            raise ClientError(f"LinkedIn {url} response did not include a {key}.")
        return f"urn:li:person:{member_id}"

    @cached
    def get_current_member_urn(self) -> str:
        me_error_message: Optional[str] = None
        try:
            return self._member_urn_from_identity_response(
                url=CURRENT_MEMBER_PROFILE_URL,
                key="id",
            )
        except ClientError as me_error:
            if not str(me_error).startswith("HTTP 403:"):
                raise
            me_error_message = str(me_error)

        try:
            return self._member_urn_from_identity_response(
                url=CURRENT_MEMBER_USERINFO_URL,
                key="sub",
            )
        except ClientError as userinfo_error:
            raise ClientError(
                "LinkedIn could not resolve the authenticated member URN from /v2/me or /v2/userinfo. "
                "Pass --person urn:li:person:<id>, set LINKEDIN_PERSON_URN, enable the LinkedIn "
                "OpenID Connect product and re-run `linkedin auth login --force` with "
                "LINKEDIN_SCOPES including openid profile, or re-run `linkedin auth login --force` "
                "with LINKEDIN_SCOPES including r_liteprofile if your app is approved. "
                f"/v2/me error: {me_error_message}. /v2/userinfo error: {userinfo_error}."
            ) from userinfo_error

    def update_post(
        self,
        *,
        post_urn: str,
        commentary: str,
        permission_author: Optional[str] = None,
    ) -> dict:
        encoded_urn = quote(post_urn, safe="")
        payload = {
            "patch": {
                "$set": {
                    "commentary": commentary,
                }
            }
        }
        self._request_api(
            "POST",
            f"/posts/{encoded_urn}",
            data=payload,
            permission_author=permission_author,
            extra_headers={"X-RestLi-Method": "PARTIAL_UPDATE"},
        )
        self._invalidate_post_read_caches()
        return {
            "id": post_urn,
            "commentary": commentary,
            "updated": True,
        }

    def delete_post(self, *, post_urn: str, permission_author: Optional[str] = None) -> dict:
        encoded_urn = quote(post_urn, safe="")
        self._request_api(
            "DELETE",
            f"/posts/{encoded_urn}",
            permission_author=permission_author,
            extra_headers={"X-RestLi-Method": "DELETE"},
        )
        self._invalidate_post_read_caches()
        return {
            "id": post_urn,
            "deleted": True,
        }


def get_client(profile: Optional[str] = None) -> LinkedInClient:
    """Create a LinkedIn client for the requested auth profile."""
    return LinkedInClient(config=get_config(profile=profile))
