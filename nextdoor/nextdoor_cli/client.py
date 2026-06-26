"""Nextdoor GraphQL client.

Authentication is browser-based: ``nextdoor auth login`` drives a persistent
Chromium profile and the session lives in that profile (the single source of
truth). Data operations are GraphQL persisted-query POSTs that reuse the live
session cookies fetched from that profile via the shared ``BrowserAuthState``.

Nextdoor routes each persisted query as ``POST {base_url}/<operationName>``
(e.g. ``https://nextdoor.com/api/gql/getMe``); the operation name is part of
the path and the persisted-query hash travels in the request body.
"""

from typing import Dict, List, Optional

import requests

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.http_session import (
    BrowserAuthState,
    BrowserAuthStateError,
    DEFAULT_REQUESTS_BASE_DELAY,
    DEFAULT_REQUESTS_JITTER,
    DEFAULT_REQUESTS_MAX_DELAY,
    DEFAULT_REQUESTS_MAX_RETRIES,
    RequestsRetryPolicy,
    request_with_retry,
    required_path,
)

from .browser import NextdoorBrowser
from .config import (
    NEXTDOOR_ALLOWED_DOMAINS,
    NEXTDOOR_HOST,
    NEXTDOOR_ORIGIN,
    get_config,
)

# Persisted-query hashes for each operation. These travel in the request body;
# Nextdoor rotates them with frontend builds, so they are stored as data here.
PERSISTED_QUERIES = {
    "PersonalizedFeed": "50d786132cd0779d6c34b9e683ea5fcb82e9ff71866e6c8bd32f43c805c03ad8",
    "getMe": "17d16335240791a39640e8cebc220c3f84786668a46245176749d1e5e4eb21e1",
    "dashboardBadges": "f721ff14d106e321b4019f064e130331e5b73c091c3675b55866b3775b5cd738",
    "getDynamicSearchBarSuggestions": "9f6fba061346d5b4d18a328d6408787effcbf1121f6ecc73c60f22964c101aac",
}


# Each normalize function below owns BOTH the record shape it produces and the
# default table column order for that shape. main.py imports these column tuples
# so the display columns can never drift from the record fields. Shapes are
# derived from real captured Nextdoor GraphQL responses.
FEED_COLUMNS = ("id", "type", "title")
SEARCH_COLUMNS = ("suggestion",)
NOTIFICATION_COLUMNS = ("id", "label", "badges")


def _feed_item_title(raw: dict) -> Optional[str]:
    """Pull the human-readable title from a heterogeneous feed item.

    Title source is dispatched by ``feedItemType``: POST items carry it at
    ``post.subject``; PROMO (ad) items at ``promo.creative.sponsorName.text``.
    Any other item type has no documented title field, so the title is None
    (truthful — not a masked fallback to an unrelated field).
    """
    item_type = raw.get("feedItemType")
    if item_type == "POST":
        post = raw.get("post")
        return post.get("subject") if isinstance(post, dict) else None
    if item_type == "PROMO":
        promo = raw.get("promo")
        creative = promo.get("creative") if isinstance(promo, dict) else None
        sponsor = creative.get("sponsorName") if isinstance(creative, dict) else None
        return sponsor.get("text") if isinstance(sponsor, dict) else None
    return None


def normalize_feed_item(raw: dict) -> dict:
    """Map one PersonalizedFeed item to the public CLI record shape.

    Feed items are heterogeneous (POST, PROMO, ...). The stable identity is
    ``contentId`` and the kind is ``feedItemType``; the title is type-specific
    (see ``_feed_item_title``).
    """
    return {
        "id": raw.get("contentId"),
        "type": raw.get("feedItemType"),
        "title": _feed_item_title(raw),
    }


def normalize_search_suggestion(raw: str) -> dict:
    """Map one search-bar suggestion to the public CLI record shape.

    ``dynamicSearchBarSuggestions`` is a list of plain strings, so each
    suggestion is wrapped as a single-field record.
    """
    return {"suggestion": raw}


def normalize_notification(raw: dict) -> dict:
    """Map one dashboard badge/shortcut entry to the public CLI record shape.

    Shortcuts carry a stable ``type`` slug, a display ``title``, and a
    ``badges`` value (null when there are none) — the badges are the point of
    this command.
    """
    return {
        "id": raw.get("type"),
        "label": raw.get("title"),
        "badges": raw.get("badges"),
    }


def _is_login_wall(text: str) -> bool:
    """Detect Nextdoor's logged-out HTML landing/login page in a response body."""
    head = text[:2000].lower()
    return "<!doctype html" in head and ("log in" in head or "/login" in head)


def _optional_list(container: dict, key: str) -> list:
    """Read a list-valued collection that is allowed to be absent or empty.

    Absent means "no results" (a valid empty collection). A present value of
    the wrong type is a contract violation and fails loudly — no silent
    coercion.
    """
    if key not in container or container[key] is None:
        return []
    value = container[key]
    if not isinstance(value, list):
        raise ClientError(f"Expected '{key}' to be a list, got {type(value).__name__}.")
    return value


def _error_message(err) -> str:
    """Render one GraphQL error entry as a human-readable string."""
    if isinstance(err, dict) and isinstance(err.get("message"), str):
        return err["message"]
    return str(err)


class NextdoorClient:
    """Client for the Nextdoor GraphQL API using a browser-captured session."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_REQUESTS_MAX_RETRIES,
        base_delay: float = DEFAULT_REQUESTS_BASE_DELAY,
        max_delay: float = DEFAULT_REQUESTS_MAX_DELAY,
        jitter: float = DEFAULT_REQUESTS_JITTER,
    ):
        self.config = config or get_config()
        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            detail = f"Missing credentials: {', '.join(missing)}. " if missing else ""
            raise ClientError(
                f"{detail}No saved Nextdoor browser session. "
                "Run 'nextdoor auth login' to authenticate."
            )
        self.base_url = self.config.base_url
        self._retry_policy = RequestsRetryPolicy(
            max_retries=max_retries,
            base_delay=base_delay,
            max_delay=max_delay,
            jitter=jitter,
        )
        self._session: Optional[requests.Session] = None
        self._browser: Optional[NextdoorBrowser] = None

    # ---- Session / auth ----

    @property
    def browser(self) -> NextdoorBrowser:
        """The BrowserAutomation subclass that owns the persistent session.

        The persistent Chromium profile this browser manages is the single
        source of truth for the authenticated session that ``BrowserAuthState``
        reads its cookies from.
        """
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def _build_session(self) -> requests.Session:
        """Build a requests session carrying the live browser cookies + CSRF."""
        try:
            state = BrowserAuthState.from_config(self.config)
            cookies = state.cookies_for_host(
                NEXTDOOR_HOST,
                allowed_domains=NEXTDOOR_ALLOWED_DOMAINS,
            )
        except BrowserAuthStateError as exc:
            raise ClientError(
                f"Nextdoor browser session is missing or invalid ({exc}). "
                "Run 'nextdoor auth login --force' to refresh."
            ) from exc

        cookie_jar = {c.name: c.value for c in cookies}
        csrf = cookie_jar.get("csrftoken")

        session = requests.Session()
        session.cookies.update(cookie_jar)
        session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": NEXTDOOR_ORIGIN,
                "Referer": f"{NEXTDOOR_ORIGIN}/news_feed/",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            }
        )
        if csrf:
            session.headers["x-csrftoken"] = csrf
        return session

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = self._build_session()
        return self._session

    def close(self):
        if self._session is not None:
            self._session.close()
            self._session = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    # ---- GraphQL transport ----

    def _graphql(self, operation: str, variables: Optional[Dict] = None) -> Dict:
        """POST a persisted-query GraphQL operation and return its ``data`` object.

        Nextdoor routes the operation by path: ``{base_url}/<operation>``.
        """
        if operation not in PERSISTED_QUERIES:
            raise ClientError(f"Unknown Nextdoor GraphQL operation: {operation}")

        payload = {
            "operationName": operation,
            "variables": {} if variables is None else variables,
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": PERSISTED_QUERIES[operation],
                }
            },
        }
        url = f"{self.base_url}/{operation}"
        response = self._request("POST", url, json_body=payload)

        if response.status_code in (401, 403) or _is_login_wall(response.text):
            raise ClientError(
                "Nextdoor session is not authenticated (server returned the login "
                "page). Run 'nextdoor auth login --force' to refresh the session."
            )
        if not response.ok:
            raise ClientError(f"HTTP {response.status_code}: {response.text[:300]}")

        try:
            body = response.json()
        except ValueError as exc:
            raise ClientError(
                f"Nextdoor returned a non-JSON response for {operation}: {response.text[:200]}"
            ) from exc

        errors = _optional_list(body, "errors")
        if errors:
            messages = "; ".join(_error_message(err) for err in errors)
            if any(
                token in messages.lower()
                for token in ("auth", "login", "session", "unauthorized")
            ):
                raise ClientError(
                    f"Nextdoor session rejected the request ({messages}). "
                    "Run 'nextdoor auth login --force' to refresh the session."
                )
            raise ClientError(f"GraphQL error for {operation}: {messages}")

        data = body.get("data")
        if data is None:
            raise ClientError(f"Nextdoor returned no data for {operation}.")

        # Nextdoor answers a structurally-valid persisted query with HTTP 200 and
        # ``data.me == null`` when the session is not authenticated (it does NOT
        # return a 401/403 or a GraphQL error in this case). Treat an explicit
        # null ``me`` as the unauthenticated signal and fail loudly.
        if isinstance(data, dict) and "me" in data and data["me"] is None:
            raise ClientError(
                "Nextdoor session is not authenticated (server returned a null "
                "user). Run 'nextdoor auth login --force' to refresh the session."
            )
        return data

    def _request(self, method: str, url: str, json_body: Optional[Dict] = None) -> requests.Response:
        def send() -> requests.Response:
            return self.session.request(method, url, json=json_body)

        try:
            return request_with_retry(send, self._retry_policy)
        except requests.exceptions.RequestException as exc:
            raise ClientError(f"Nextdoor request failed after retries: {exc}") from exc

    # ---- Public operations ----

    @cached
    def get_feed(self, limit: int = 10) -> List[dict]:
        """Return personalized feed items (documented shape: id, type, title)."""
        variables = {
            "pagedCommentsMode": "FEED",
            "useEdgesV2": False,
            "includeModerationInfo": False,
            "mainFeedArgs": {
                "pageSize": limit,
                "nextPage": None,
                "supportedFeatures": {
                    "rollupTypes": ["CAROUSEL", "LIST", "GRID"],
                    "rollupItemTypes": [
                        "IMAGE_CARD",
                        "LIST_CARD",
                        "POST",
                        "PUBLISHER_DISCOVERY",
                        "ONBOARDING_CAROUSEL_CARD",
                        "LOCAL_EVENT_CARD",
                    ],
                    "numCommentsForNewsPosts": 2,
                    "isStickyCommentPreviewEnabled": False,
                },
                "sortOrder": "FOR_YOU",
            },
            "timeZone": "America/Chicago",
        }
        data = self._graphql("PersonalizedFeed", variables)
        feed = required_path(data, ["me", "personalizedFeed"], dict)
        items = _optional_list(feed, "feedItems")
        return [normalize_feed_item(item) for item in items]

    @cached
    def get_me(self) -> dict:
        """Return the current authenticated user object."""
        data = self._graphql("getMe")
        me = required_path(data, ["me"], dict)
        user = me.get("user")
        if not user:
            raise ClientError(
                "Nextdoor returned no user for getMe. The session is likely "
                "logged out. Run 'nextdoor auth login --force'."
            )
        return user

    @cached
    def get_notifications(self) -> List[dict]:
        """Return dashboard badge/shortcut entries (unread counts)."""
        data = self._graphql("dashboardBadges")
        me = required_path(data, ["me"], dict)
        shortcuts = _optional_list(me, "shortcuts")
        return [normalize_notification(item) for item in shortcuts]

    @cached
    def search(self, query: str) -> List[dict]:
        """Return dynamic search-bar suggestions for ``query``."""
        data = self._graphql("getDynamicSearchBarSuggestions", {"query": query})
        suggestions = _optional_list(data, "dynamicSearchBarSuggestions")
        return [normalize_search_suggestion(item) for item in suggestions]


_client: Optional[NextdoorClient] = None


def get_client() -> NextdoorClient:
    """Get or create the global Nextdoor client instance."""
    global _client
    if _client is None:
        _client = NextdoorClient()
    return _client
