"""Nextdoor API client."""

import os
import random
import time
from typing import Dict, List, Optional

import requests
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .config import get_config

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def normalize_item(raw: dict) -> dict:
    """Map one API item to the public CLI record shape."""
    return {
        "id": raw["id"],
        "name": raw["name"],
        "status": raw["status"],
    }


def normalize_item_detail(raw: dict) -> dict:
    """Map one API detail response to the public CLI record shape."""
    return normalize_item(raw)


class NextdoorClient:
    """Client for interacting with Nextdoor API."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = config or get_config()
        credential_types = list(getattr(self.config, "CREDENTIAL_TYPES", []))
        has_browser_session = CredentialType.BROWSER_SESSION in credential_types
        has_non_browser_auth = any(ct != CredentialType.BROWSER_SESSION for ct in credential_types)

        if has_browser_session and has_non_browser_auth:
            if not hasattr(self.config, "has_api_credentials"):
                raise ClientError(
                    "Config.has_api_credentials() is required when API credentials are combined "
                    "with browser_session."
                )
            authenticated = self.config.has_api_credentials()
        else:
            authenticated = self.config.has_credentials()

        if not authenticated:
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'nextdoor auth login' to authenticate."
            )
        self.base_url = self.config.base_url
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self._update_headers()

    def _update_headers(self):
        self.headers = {
            "Accept": "application/json", 
            "Content-Type": "application/json",
            "Origin": "https://nextdoor.com",
            "Referer": "https://nextdoor.com/",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
        }
        self.cookies = {}
        
        cookie_b64 = os.getenv("BROWSER_SESSION_COOKIE_B64")
        if cookie_b64:
            import base64
            try:
                cookie_str = base64.b64decode(cookie_b64).decode()
                self.headers["Cookie"] = cookie_str
            except Exception:
                pass
                
        csrf = os.getenv("BROWSER_SESSION_CSRF")
        if csrf:
            self.headers["x-csrftoken"] = csrf
                
        if self.config.access_token:
            self.headers["Authorization"] = f"Bearer {self.config.access_token}"
        elif self.config.personal_access_token:
            self.headers["Authorization"] = f"Bearer {self.config.personal_access_token}"
        elif self.config.api_key:
            self.headers["Authorization"] = f"Bearer {self.config.api_key}"

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
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            error = body["error"]
            return error.get("message") or error.get("code") or str(error)
        if isinstance(body, dict) and "message" in body:
            return str(body["message"])
        return str(body)[:500]

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
    ) -> Dict:
        url = f"{self.base_url}{endpoint}"
        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                response = requests.request(method, url, headers=self.headers, cookies=self.cookies, json=data, params=params)
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
            raise ClientError(f"HTTP {last_response.status_code}: {self._extract_error_detail(last_response)}")
        if last_response.status_code == 204:
            return {}
        return last_response.json()

    @cached
    def get_feed(self, limit: int = 10) -> List[dict]:
        payload = {
            "operationName": "PersonalizedFeed",
            "variables": {
                "pagedCommentsMode": "FEED",
                "useEdgesV2": False,
                "includeModerationInfo": False,
                "mainFeedArgs": {
                    "pageSize": limit,
                    "nextPage": None,
                    "supportedFeatures": {
                        "rollupTypes": ["CAROUSEL", "LIST", "GRID"],
                        "rollupItemTypes": ["IMAGE_CARD", "LIST_CARD", "POST", "PUBLISHER_DISCOVERY", "ONBOARDING_CAROUSEL_CARD", "LOCAL_EVENT_CARD"],
                        "numCommentsForNewsPosts": 2,
                        "isStickyCommentPreviewEnabled": False
                    },
                    "sortOrder": "FOR_YOU"
                },
                "timeZone": "America/Chicago"
            },
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": "50d786132cd0779d6c34b9e683ea5fcb82e9ff71866e6c8bd32f43c805c03ad8"
                }
            }
        }
        res = self._make_request("POST", "/PersonalizedFeed", data=payload)
        items = res.get("data", {}).get("me", {}).get("personalizedFeed", {}).get("feedItems", [])
        # Each item is wrapped in an 'edge' format if useEdgesV2 is False? No, usually it's just items.
        # But we'll just return the items themselves!
        return items

    @cached
    def get_me(self) -> dict:
        payload = {
            "operationName": "getMe",
            "variables": {},
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": "17d16335240791a39640e8cebc220c3f84786668a46245176749d1e5e4eb21e1"
                }
            }
        }
        res = self._make_request("POST", "/getMe", data=payload)
        return res.get("data", {}).get("me", {}).get("user", {})

    @cached
    def get_notifications(self) -> List[dict]:
        payload = {
            "operationName": "dashboardBadges",
            "variables": {},
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": "f721ff14d106e321b4019f064e130331e5b73c091c3675b55866b3775b5cd738"
                }
            }
        }
        res = self._make_request("POST", "/dashboardBadges", data=payload)
        return res.get("data", {}).get("me", {}).get("shortcuts", [])

    @cached
    def search(self, query: str) -> List[dict]:
        payload = {
            "operationName": "getDynamicSearchBarSuggestions",
            "variables": {"query": query},
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": "9f6fba061346d5b4d18a328d6408787effcbf1121f6ecc73c60f22964c101aac"
                }
            }
        }
        res = self._make_request("POST", "/getDynamicSearchBarSuggestions", data=payload)
        suggestions = res.get("data", {}).get("dynamicSearchBarSuggestions", [])
        return suggestions


_client: Optional[NextdoorClient] = None


def get_client() -> NextdoorClient:
    """Get or create the global Nextdoor client instance."""
    global _client
    if _client is None:
        _client = NextdoorClient()
    return _client
