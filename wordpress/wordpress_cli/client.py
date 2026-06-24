"""WordPress API client with automatic retry and Pydantic models."""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
import random
import time
import requests
from requests.auth import HTTPBasicAuth
from urllib.parse import quote, urlparse

from cli_tools_shared.exceptions import ClientError

from .config import get_config
from .models import (
    Post,
    PostDetail,
    Page,
    PageDetail,
    Media,
    Category,
    Tag,
    Plugin,
    create_post,
    create_post_detail,
    create_page,
    create_page_detail,
    create_media,
    create_category,
    create_tag,
    create_plugin,
)
from .wpcom import (
    acquire_wpcom_access_token,
    build_wpcom_missing_credentials_message,
    extract_wpcom_error_message,
    wpcom_response_indicates_invalid_token,
)


# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_JITTER = 0.1  # 10% jitter

# HTTP status codes that trigger retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# User agent for all requests
DEFAULT_USER_AGENT = "WordPressClient/1.0"
WPCOM_API_BASE_URL = "https://public-api.wordpress.com/rest/v1.1"
WPVULNERABILITY_API_BASE_URL = "https://api.wpvulnerability.com"
JETPACK_PLUGIN_MANAGEMENT_ERROR = (
    "Jetpack is not connected to a WordPress.com account that can manage plugins for this site. "
    "Connect the current WordPress admin user to WordPress.com through Jetpack before plugin updates can run."
)
WPCOM_PLUGIN_AUTHORIZATION_ERROR = (
    "WordPress.com denied plugin-management access for the configured WPCOM_SITE even though the "
    "WordPress.com token is present. This is not a missing-token state. Confirm the OAuth app is "
    "authorized by the same WordPress.com account that can manage plugins for the Jetpack-connected "
    "site, and confirm WPCOM_SITE identifies that exact site."
)


class WordPressClient:
    """Client for interacting with WordPress REST API with automatic retry."""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        """
        Initialize WordPress client from configuration.

        Args:
            max_retries: Maximum number of retry attempts for transient errors (default: 3)
            base_delay: Base delay in seconds for exponential backoff (default: 1.0)
            max_delay: Maximum delay in seconds between retries (default: 30.0)
            jitter: Random jitter factor to prevent thundering herd (default: 0.1)
        """
        self.config = get_config()

        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'wordpress auth login' to configure credentials."
            )

        self.base_url = self.config.base_url
        self.auth = HTTPBasicAuth(self.config.username, self.config.app_password)
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
        }

        # Retry configuration
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """
        Calculate delay before next retry using exponential backoff with jitter.

        Args:
            attempt: Current retry attempt number (0-indexed)
            retry_after: Optional Retry-After header value from server

        Returns:
            Delay in seconds before next retry
        """
        # Honor Retry-After header if present
        if retry_after is not None:
            return min(retry_after, self.max_delay)

        # Exponential backoff: base_delay * 2^attempt
        delay = self.base_delay * (2 ** attempt)

        # Add random jitter to prevent thundering herd
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)

        # Cap at max delay
        return min(delay, self.max_delay)

    def _is_retryable(self, response: Optional[requests.Response], exception: Optional[Exception]) -> bool:
        """
        Determine if a request should be retried.

        Args:
            response: Response object (if request completed)
            exception: Exception raised (if request failed)

        Returns:
            True if request should be retried
        """
        # Retry on connection errors
        if exception is not None:
            return isinstance(exception, (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ))

        # Retry on specific status codes
        if response is not None:
            return response.status_code in RETRYABLE_STATUS_CODES

        return False

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        """
        Extract Retry-After header value from response.

        Args:
            response: Response object

        Returns:
            Retry delay in seconds, or None if not present
        """
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return None

        try:
            # Try parsing as integer seconds
            return float(retry_after)
        except ValueError:
            # Could be HTTP-date format, but we'll skip that complexity
            return None

    @staticmethod
    def _clean_text(value: Any) -> Optional[str]:
        """Return the useful text from common WordPress raw/rendered fields."""
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            raw = value.get("raw")
            if isinstance(raw, str):
                return raw
            rendered = value.get("rendered")
            if isinstance(rendered, str):
                return rendered
        raise ClientError(f"Expected text field to be a string or dict, got {type(value)}")

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
        files: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        return_headers: bool = False,
        base_url: Optional[str] = None,
    ) -> Any:
        """
        Make an HTTP request to the WordPress API with exponential retry.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: API endpoint path (e.g., "/posts")
            data: Request body data
            params: Query parameters
            retry: Whether to retry on transient errors (default: True)
            files: Files to upload (for media uploads)
            headers: Additional headers to merge with defaults
            return_headers: If True, returns tuple of (json_data, response_headers)

        Returns:
            Response JSON data or dict (or tuple if return_headers=True)

        Raises:
            ClientError: If request fails after all retries
        """
        url = f"{(base_url or self.base_url).rstrip('/')}{endpoint}"

        # Merge headers
        request_headers = self.headers.copy()
        if headers:
            request_headers.update(headers)

        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None

        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                # Make the request
                if files:
                    # For file uploads, don't send JSON
                    response = requests.request(
                        method=method,
                        url=url,
                        headers=request_headers,
                        data=data,
                        files=files,
                        params=params,
                        auth=self.auth,
                    )
                else:
                    response = requests.request(
                        method=method,
                        url=url,
                        headers=request_headers,
                        json=data,
                        params=params,
                        auth=self.auth,
                    )
                last_response = response

                # Check if we should retry this response
                if retry and self._is_retryable(response, None) and attempt < self.max_retries:
                    retry_after = self._get_retry_after(response)
                    delay = self._calculate_retry_delay(attempt, retry_after)
                    time.sleep(delay)
                    continue

                # Success or non-retryable error - exit loop
                break

            except requests.exceptions.RequestException as e:
                last_exception = e
                # Check if we should retry this exception
                if retry and self._is_retryable(None, e) and attempt < self.max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    time.sleep(delay)
                    continue
                # Non-retryable exception or exhausted retries
                break

        # Handle the final result
        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed after {attempt + 1} attempts: {last_exception}")

        if last_response is None:
            raise ClientError("Request failed: no response received")

        if not last_response.ok:
            # Try to get error details from response
            try:
                error_data = last_response.json()
                error_msg = error_data.get("message") or error_data.get("error") or last_response.text
            except Exception:
                error_msg = last_response.text
            raise ClientError(f"API request failed ({last_response.status_code}): {error_msg}")

        # Handle empty response (204 No Content)
        if last_response.status_code == 204:
            if return_headers:
                return {}, dict(last_response.headers)
            return {}

        json_data = last_response.json()
        if return_headers:
            return json_data, dict(last_response.headers)
        return json_data

    def get_site_settings(self) -> dict:
        """Read site settings exposed through the authenticated WordPress REST API."""
        response = self._make_request("GET", "/settings")
        if not isinstance(response, dict):
            raise ClientError(f"Expected settings response to be a dict, got {type(response)}")
        return response

    def list_themes(self) -> List[dict]:
        """List installed WordPress themes from the authenticated REST API."""
        response = self._make_request("GET", "/themes")
        if not isinstance(response, list):
            raise ClientError(f"Expected theme list response to be a list, got {type(response)}")

        themes: List[dict] = []
        for raw_theme in response:
            if not isinstance(raw_theme, dict):
                raise ClientError(f"Expected theme entry to be a dict, got {type(raw_theme)}")
            stylesheet = raw_theme.get("stylesheet")
            version = raw_theme.get("version")
            status = raw_theme.get("status")
            if not isinstance(stylesheet, str) or not stylesheet:
                raise ClientError("Theme entry did not include a non-empty stylesheet")
            if not isinstance(version, str) or not version:
                raise ClientError(f"Theme {stylesheet} did not include a non-empty version")
            if not isinstance(status, str) or not status:
                raise ClientError(f"Theme {stylesheet} did not include a non-empty status")
            themes.append(
                {
                    "theme": stylesheet,
                    "name": self._clean_text(raw_theme.get("name")) or stylesheet,
                    "version": version,
                    "status": status,
                    "requires_wp": raw_theme.get("requires_wp"),
                    "requires_php": raw_theme.get("requires_php"),
                    "textdomain": raw_theme.get("textdomain"),
                }
            )
        return themes

    @staticmethod
    def _theme_identifier_values(theme: dict) -> List[str]:
        """Return exact identifiers users can discover from theme list output."""
        values = [theme["theme"], theme["name"]]
        textdomain = theme.get("textdomain")
        if textdomain:
            values.append(textdomain)
        return values

    def get_theme(self, theme: str) -> dict:
        """Get a specific theme by stylesheet, textdomain, or exact name."""
        if not theme or not theme.strip():
            raise ValueError("theme cannot be empty")

        normalized = theme.strip().casefold()
        matches = [
            installed
            for installed in self.list_themes()
            if normalized in {value.casefold() for value in self._theme_identifier_values(installed)}
        ]
        if not matches:
            raise ClientError(
                f"Theme not found: {theme}. Use a stylesheet, textdomain, or exact name from themes list."
            )
        if len(matches) > 1:
            match_names = ", ".join(sorted(match["theme"] for match in matches))
            raise ClientError(f"Theme identifier is ambiguous: {theme}. Matches: {match_names}")
        return matches[0]

    def _wp_json_base_url(self) -> str:
        suffix = "/wp/v2"
        base_url = self.base_url.rstrip("/")
        if not base_url.endswith(suffix):
            raise ClientError(f"Expected WordPress API base URL to end with {suffix}, got {self.base_url}")
        return base_url[: -len(suffix)]

    def _make_wpcom_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        retry_on_forbidden: bool = False,
        interactive_token_refresh: bool = True,
    ) -> Any:
        token = self.config.wpcom_access_token
        if not token:
            if not interactive_token_refresh:
                raise ClientError(
                    "WordPress.com access token is missing. Run `wordpress org token` interactively, "
                    "verify `wordpress org token status` reports ready true, then retry the command."
                )
            acquire_wpcom_access_token(self.config)
            token = self.config.wpcom_access_token
        if not token:
            raise ClientError("WordPress.com token acquisition did not save WPCOM_ACCESS_TOKEN")

        url = f"{WPCOM_API_BASE_URL}{endpoint}"
        response = self._dispatch_wpcom_request(method, url, token, data)

        if wpcom_response_indicates_invalid_token(response):
            self.config.clear_wpcom_access_token()
            if not interactive_token_refresh:
                raise ClientError(
                    "WordPress.com access token is invalid or expired. Run `wordpress org token` "
                    "interactively, verify `wordpress org token status` reports ready true, then retry the command."
                )
            acquire_wpcom_access_token(self.config)
            token = self.config.wpcom_access_token
            if not token:
                raise ClientError("WordPress.com token acquisition did not save WPCOM_ACCESS_TOKEN")
            response = self._dispatch_wpcom_request(method, url, token, data)

        if response.status_code == 403 and retry_on_forbidden:
            if not interactive_token_refresh:
                raise ClientError(WPCOM_PLUGIN_AUTHORIZATION_ERROR)
            self.config.clear_wpcom_access_token()
            acquire_wpcom_access_token(self.config)
            token = self.config.wpcom_access_token
            if not token:
                raise ClientError("WordPress.com token acquisition did not save WPCOM_ACCESS_TOKEN")
            response = self._dispatch_wpcom_request(method, url, token, data)
            if response.status_code == 403:
                raise ClientError(WPCOM_PLUGIN_AUTHORIZATION_ERROR)

        if not response.ok:
            error_msg = extract_wpcom_error_message(response)
            raise ClientError(f"WordPress.com API request failed ({response.status_code}): {error_msg}")

        return response.json()

    def _dispatch_wpcom_request(
        self,
        method: str,
        url: str,
        token: str,
        data: Optional[Dict] = None,
    ) -> requests.Response:
        return requests.request(
            method=method,
            url=url,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": DEFAULT_USER_AGENT,
            },
            json=data,
            timeout=60,
        )

    # ==================== Post Methods ====================

    def list_posts(
        self,
        limit: int = 10,
        filters: Optional[Dict[str, str]] = None,
    ) -> List[Post]:
        """
        List posts from WordPress with automatic pagination.

        Automatically handles pagination when limit > 100 (WordPress API max per_page).
        Makes multiple requests as needed to fetch up to the requested limit.

        Args:
            limit: Maximum number of posts to return (default: 10)
            filters: Optional filters (status, author, etc.)

        Returns:
            List of Post models
        """
        endpoint = "/posts"

        # WordPress REST API limits per_page to 100
        WP_MAX_PER_PAGE = 100

        all_posts: List[Post] = []
        page = 1
        remaining = limit

        while remaining > 0:
            # Request up to WP_MAX_PER_PAGE or remaining, whichever is smaller
            per_page = min(remaining, WP_MAX_PER_PAGE)

            params = {"per_page": per_page, "page": page}

            # Add filters if provided
            if filters:
                params.update(filters)

            response, headers = self._make_request("GET", endpoint, params=params, return_headers=True)

            # WordPress returns array directly
            if not isinstance(response, list):
                raise ClientError(f"Expected list response, got {type(response)}")

            # Convert to models and add to results
            posts = [create_post(post) for post in response]
            all_posts.extend(posts)

            # Check if we've exhausted available posts
            if len(posts) < per_page:
                # Got fewer than requested, no more pages
                break

            # Check total pages from headers (lowercase per requests library)
            total_pages = int(headers.get("x-wp-totalpages", 1))
            if page >= total_pages:
                break

            remaining -= len(posts)
            page += 1

        return all_posts

    def get_post(self, post_id: int, context: str = "view") -> PostDetail:
        """
        Get a specific post by ID.

        Uses include= query parameter instead of path ID because
        some WordPress hosts redirect /posts/{id} and strip the ID.

        Args:
            post_id: The post ID
            context: Request context - "view" for rendered HTML, "edit" for raw Gutenberg blocks

        Returns:
            PostDetail model with full details
        """
        endpoint = "/posts"
        params = {"include": str(post_id), "per_page": 1, "status": "any"}
        if context != "view":
            params["context"] = context
        response = self._make_request("GET", endpoint, params=params)

        if isinstance(response, list):
            if not response:
                raise ClientError(f"Post {post_id} not found")
            response = response[0]

        return create_post_detail(response, raw=(context == "edit"))

    def create_post(
        self,
        title: str,
        content: str,
        status: str = "draft",
        slug: Optional[str] = None,
        sponsored: bool = False,
        date: Optional[str] = None,
        categories: Optional[List[int]] = None,
        tags: Optional[List[int]] = None,
        excerpt: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> PostDetail:
        """
        Create a new WordPress post.

        Args:
            title: Post title
            content: Post content (HTML)
            status: Post status (publish, draft, pending, private, future)
            slug: Optional URL slug
            sponsored: If True, adds rel="sponsored nofollow" to all links (not yet implemented)
            date: Optional schedule date (ISO 8601 format, e.g., "2026-01-10T09:00:00")
            categories: Optional list of category IDs
            tags: Optional list of tag IDs
            excerpt: Optional post excerpt
            meta: Optional dict of custom field key-value pairs (e.g., for RankMath SEO)

        Returns:
            PostDetail model of created post
        """
        endpoint = "/posts"
        data = {
            "title": title,
            "content": content,
            "status": status,
        }

        if slug is not None:
            data["slug"] = slug
        if date is not None:
            data["date"] = date
        if categories is not None:
            data["categories"] = categories
        if tags is not None:
            data["tags"] = tags
        if excerpt is not None:
            data["excerpt"] = excerpt
        if meta is not None:
            data["meta"] = meta

        # Note: sponsored parameter is accepted but not yet implemented
        # When implemented, it should process content to add rel attributes to links
        # This will be done via utils module

        response = self._make_request("POST", endpoint, data=data)

        return create_post_detail(response)

    def update_post(self, post_id: int, fields: Dict[str, Any]) -> PostDetail:
        """
        Update an existing post.

        Args:
            post_id: The post ID
            fields: Dictionary of fields to update

        Returns:
            PostDetail model of updated post
        """
        if not fields:
            raise ValueError("fields cannot be empty when updating a post")

        endpoint = f"/posts/{post_id}"
        response = self._make_request("POST", endpoint, data=fields)

        return create_post_detail(response)

    def delete_post(self, post_id: int, force: bool = False) -> dict:
        """
        Delete a post.

        Args:
            post_id: The post ID
            force: If True, permanently delete. If False, move to trash.

        Returns:
            Dict with deletion result
        """
        endpoint = f"/posts/{post_id}"
        params = None
        if force:
            params = {"force": "true"}

        response = self._make_request("DELETE", endpoint, params=params)

        return response

    # Schedule reservation directory for preventing race conditions between
    # concurrent auto-schedule calls (e.g., parallel pipeline runs)
    _RESERVATION_DIR = Path.home() / ".cache" / "wordpress-cli" / "schedule-reservations"

    def _read_schedule_reservations(self) -> List[datetime]:
        """Read pending schedule reservations, cleaning up expired ones."""
        times = []
        if not self._RESERVATION_DIR.exists():
            return times
        for f in self._RESERVATION_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                expires = datetime.fromisoformat(data["expires"])
                if expires < datetime.now():
                    f.unlink()  # Expired reservation
                else:
                    times.append(datetime.fromisoformat(data["slot"]))
            except (json.JSONDecodeError, KeyError, ValueError):
                f.unlink()  # Corrupt reservation
        return times

    def _create_schedule_reservation(self, slot: str) -> None:
        """Create a temporary reservation for a schedule slot (expires in 10 min)."""
        self._RESERVATION_DIR.mkdir(parents=True, exist_ok=True)
        reservation = {
            "slot": slot,
            "expires": (datetime.now() + timedelta(minutes=10)).isoformat(),
            "pid": os.getpid(),
        }
        path = self._RESERVATION_DIR / f"{os.getpid()}_{int(time.time())}.json"
        path.write_text(json.dumps(reservation))

    def clear_schedule_reservation(self) -> None:
        """Clear schedule reservations created by this process."""
        if self._RESERVATION_DIR.exists():
            for f in self._RESERVATION_DIR.glob(f"{os.getpid()}_*.json"):
                f.unlink()

    def find_next_schedule_slot(self) -> str:
        """
        Find next available publication slot respecting scheduling rules.

        Rules:
        - Max 2 posts per weekday
        - 4+ hour gap between posts
        - No weekends (rolls to Monday)
        - Posts scheduled between 9am-5pm only
        - Pending reservations from concurrent processes

        Returns:
            ISO 8601 datetime string (e.g., "2026-01-10T09:00:00")
        """
        # Get scheduled posts (status=future)
        scheduled = self.list_posts(limit=100, filters={"status": "future"})

        # Get recently published posts (last 20 for gap checking)
        published = self.list_posts(limit=20, filters={"status": "publish"})

        # Parse dates from all posts
        occupied_times = []
        for post in scheduled + published:
            # Post model has date attribute
            date_str = getattr(post, "date", None)
            if date_str:
                try:
                    dt = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
                    occupied_times.append(dt.replace(tzinfo=None))
                except ValueError:
                    continue

        # Include pending reservations from concurrent processes
        occupied_times.extend(self._read_schedule_reservations())

        # Start from now, round UP to next hour to ensure future time
        now = datetime.now()
        candidate = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

        # If before 9am, start at 9am
        if candidate.hour < 9:
            candidate = candidate.replace(hour=9)

        max_iterations = 100  # Safety limit
        for _ in range(max_iterations):
            # Skip weekends (5=Saturday, 6=Sunday)
            if candidate.weekday() >= 5:
                days_until_monday = 7 - candidate.weekday()
                candidate = (candidate + timedelta(days=days_until_monday)).replace(hour=9, minute=0)
                continue

            # Count posts on same day
            same_day = [t for t in occupied_times if t.date() == candidate.date()]
            if len(same_day) >= 2:
                candidate = (candidate + timedelta(days=1)).replace(hour=9, minute=0)
                continue

            # Check 4+ hour gap
            conflicts = [t for t in occupied_times if abs((t - candidate).total_seconds()) < 4 * 3600]
            if conflicts:
                candidate = candidate + timedelta(hours=4)
                # If pushed past reasonable hours (after 5pm), go to next day
                if candidate.hour >= 17:
                    candidate = (candidate + timedelta(days=1)).replace(hour=9, minute=0)
                continue

            # Found valid slot - reserve it before returning
            slot = candidate.strftime("%Y-%m-%dT%H:%M:%S")
            self._create_schedule_reservation(slot)
            return slot

        raise ClientError("Could not find available schedule slot within iteration limit")

    # ==================== Page Methods ====================

    def list_pages(
        self,
        limit: int = 10,
        filters: Optional[Dict[str, str]] = None,
    ) -> List[Page]:
        """List pages from WordPress with automatic pagination."""
        endpoint = "/pages"
        WP_MAX_PER_PAGE = 100

        all_pages: List[Page] = []
        page = 1
        remaining = limit

        while remaining > 0:
            per_page = min(remaining, WP_MAX_PER_PAGE)
            params = {"per_page": per_page, "page": page}
            if filters:
                params.update(filters)

            response, headers = self._make_request("GET", endpoint, params=params, return_headers=True)

            if not isinstance(response, list):
                raise ClientError(f"Expected list response, got {type(response)}")

            pages_batch = [create_page(p) for p in response]
            all_pages.extend(pages_batch)

            if len(pages_batch) < per_page:
                break

            total_pages = int(headers.get("x-wp-totalpages", 1))
            if page >= total_pages:
                break

            remaining -= len(pages_batch)
            page += 1

        return all_pages

    def get_page(self, page_id: int, context: str = "view") -> PageDetail:
        """Get a specific page by ID.

        Uses include= query parameter (same pattern as get_post) because some
        WordPress hosts redirect /pages/{id} and strip the ID.

        Args:
            page_id: The page ID
            context: "view" for rendered HTML, "edit" for raw Gutenberg blocks
        """
        endpoint = "/pages"
        params = {"include": str(page_id), "per_page": 1, "status": "any"}
        if context != "view":
            params["context"] = context
        response = self._make_request("GET", endpoint, params=params)

        if isinstance(response, list):
            if not response:
                raise ClientError(f"Page {page_id} not found")
            response = response[0]

        return create_page_detail(response, raw=(context == "edit"))

    def create_page(
        self,
        title: str,
        content: str,
        status: str = "draft",
        slug: Optional[str] = None,
        date: Optional[str] = None,
        excerpt: Optional[str] = None,
        parent: Optional[int] = None,
        menu_order: Optional[int] = None,
        template: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> PageDetail:
        """Create a new WordPress page."""
        endpoint = "/pages"
        data = {
            "title": title,
            "content": content,
            "status": status,
        }

        if slug is not None:
            data["slug"] = slug
        if date is not None:
            data["date"] = date
        if excerpt is not None:
            data["excerpt"] = excerpt
        if parent is not None:
            data["parent"] = parent
        if menu_order is not None:
            data["menu_order"] = menu_order
        if template is not None:
            data["template"] = template
        if meta is not None:
            data["meta"] = meta

        response = self._make_request("POST", endpoint, data=data)
        return create_page_detail(response)

    def update_page(self, page_id: int, fields: Dict[str, Any]) -> PageDetail:
        """Update an existing page."""
        if not fields:
            raise ValueError("fields cannot be empty when updating a page")

        endpoint = f"/pages/{page_id}"
        response = self._make_request("POST", endpoint, data=fields)
        return create_page_detail(response)

    def delete_page(self, page_id: int, force: bool = False) -> dict:
        """Delete a page.

        Args:
            page_id: The page ID
            force: If True, permanently delete. If False, move to trash.
        """
        endpoint = f"/pages/{page_id}"
        params = None
        if force:
            params = {"force": "true"}

        response = self._make_request("DELETE", endpoint, params=params)
        return response

    # ==================== Navigation Menu Methods ====================

    def list_menus(self) -> List[dict]:
        """List WordPress navigation menus."""
        response = self._make_request("GET", "/menus", params={"per_page": 100})
        if not isinstance(response, list):
            raise ClientError(f"Expected menu list response to be a list, got {type(response)}")
        return response

    def get_menu(self, menu: str) -> dict:
        """Get a single navigation menu by ID, slug, or name."""
        menu_id = self.resolve_menu_id(menu=menu)
        response = self._make_request("GET", f"/menus/{menu_id}")
        if not isinstance(response, dict):
            raise ClientError(f"Expected menu response to be a dict, got {type(response)}")
        return response

    def list_menu_locations(self) -> dict:
        """List WordPress navigation menu locations."""
        response = self._make_request("GET", "/menu-locations")
        if not isinstance(response, dict):
            raise ClientError(f"Expected menu locations response to be a dict, got {type(response)}")
        return response

    def resolve_menu_id(self, *, menu: Optional[str] = None, location: Optional[str] = None) -> int:
        """Resolve a menu ID from a menu ID/slug/name or a theme location."""
        if bool(menu) == bool(location):
            raise ValueError("Provide exactly one of menu or location")

        if location is not None:
            locations = self.list_menu_locations()
            location_data = locations.get(location)
            if not isinstance(location_data, dict):
                raise ClientError(f"Menu location not found: {location}")
            menu_id = location_data.get("menu")
            if not isinstance(menu_id, int) or menu_id <= 0:
                raise ClientError(f"Menu location has no assigned menu: {location}")
            return menu_id

        assert menu is not None
        menu_identifier = menu.strip()
        if not menu_identifier:
            raise ValueError("menu cannot be empty")
        if menu_identifier.isdigit():
            return int(menu_identifier)

        normalized = menu_identifier.casefold()
        matches = [
            raw_menu
            for raw_menu in self.list_menus()
            if str(raw_menu.get("slug", "")).casefold() == normalized
            or str(raw_menu.get("name", "")).casefold() == normalized
        ]
        if not matches:
            raise ClientError(f"Menu not found: {menu}")
        if len(matches) > 1:
            names = ", ".join(sorted(str(match.get("name", match.get("id"))) for match in matches))
            raise ClientError(f"Menu identifier is ambiguous: {menu}. Matches: {names}")
        menu_id = matches[0].get("id")
        if not isinstance(menu_id, int):
            raise ClientError(f"Resolved menu did not include an integer id: {menu}")
        return menu_id

    def list_menu_items(self, menu_id: int, limit: int = 100) -> List[dict]:
        """List items in a navigation menu with automatic pagination."""
        if menu_id <= 0:
            raise ValueError("menu_id must be a positive integer")
        if limit <= 0:
            raise ValueError("limit must be a positive integer")

        all_items: List[dict] = []
        page = 1
        remaining = limit
        while remaining > 0:
            per_page = min(remaining, 100)
            response, headers = self._make_request(
                "GET",
                "/menu-items",
                params={
                    "menus": menu_id,
                    "per_page": per_page,
                    "page": page,
                    "orderby": "menu_order",
                    "order": "asc",
                },
                return_headers=True,
            )
            if not isinstance(response, list):
                raise ClientError(f"Expected menu item list response to be a list, got {type(response)}")
            all_items.extend(response)
            if len(response) < per_page:
                break
            total_pages = int(headers.get("x-wp-totalpages", 1))
            if page >= total_pages:
                break
            remaining -= len(response)
            page += 1
        return all_items

    def add_page_to_menu(
        self,
        *,
        page_id: int,
        menu_id: int,
        title: Optional[str] = None,
        menu_order: Optional[int] = None,
    ) -> dict:
        """Add a page to a navigation menu, returning an existing item when already present."""
        if page_id <= 0:
            raise ValueError("page_id must be a positive integer")
        if menu_id <= 0:
            raise ValueError("menu_id must be a positive integer")

        for item in self.list_menu_items(menu_id):
            if (
                item.get("type") == "post_type"
                and item.get("object") == "page"
                and item.get("object_id") == page_id
            ):
                return {"created": False, "menu_id": menu_id, "item": item}

        data: Dict[str, Any] = {
            "status": "publish",
            "type": "post_type",
            "object": "page",
            "object_id": page_id,
            "menus": menu_id,
            "parent": 0,
        }
        if title is not None:
            data["title"] = title
        if menu_order is not None:
            data["menu_order"] = menu_order

        item = self._make_request("POST", "/menu-items", data=data)
        if not isinstance(item, dict):
            raise ClientError(f"Expected created menu item response to be a dict, got {type(item)}")
        return {"created": True, "menu_id": menu_id, "item": item}

    # ==================== Media Methods ====================

    def upload_media(self, filename: str, data: bytes, content_type: str) -> Media:
        """
        Upload a media file to WordPress.

        Args:
            filename: Name of the file
            data: File content as bytes
            content_type: MIME type (e.g., "image/png")

        Returns:
            Media model of uploaded file
        """
        endpoint = "/media"

        # WordPress expects media upload as multipart/form-data
        # Use custom headers for this request
        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": content_type,
            "User-Agent": DEFAULT_USER_AGENT,
        }

        # For media upload, send raw bytes as data, not JSON
        url = f"{self.base_url}{endpoint}"
        response = requests.post(
            url,
            data=data,
            headers=headers,
            auth=self.auth,
        )

        if response.status_code not in (200, 201):
            raise ClientError(
                f"WordPress media upload failed ({response.status_code}): {response.text}"
            )

        response_data = response.json()
        return create_media(response_data)

    def list_media(
        self,
        limit: int = 100,
        filters: Optional[Dict[str, str]] = None,
    ) -> List[Media]:
        """
        List media items with automatic pagination.

        Automatically handles pagination when limit > 100 (WordPress API max per_page).
        Makes multiple requests as needed to fetch up to the requested limit.

        Args:
            limit: Maximum number of media items to return
            filters: Optional filters (mime_type, media_type, etc.)

        Returns:
            List of Media models
        """
        endpoint = "/media"

        # WordPress REST API limits per_page to 100
        WP_MAX_PER_PAGE = 100

        all_media: List[Media] = []
        page = 1
        remaining = limit

        while remaining > 0:
            # Request up to WP_MAX_PER_PAGE or remaining, whichever is smaller
            per_page = min(remaining, WP_MAX_PER_PAGE)

            params = {"per_page": per_page, "page": page}

            # Add filters if provided
            if filters:
                params.update(filters)

            response, headers = self._make_request("GET", endpoint, params=params, return_headers=True)

            # WordPress returns array directly
            if not isinstance(response, list):
                raise ClientError(f"Expected list response, got {type(response)}")

            # Convert to models and add to results
            media_items = [create_media(item) for item in response]
            all_media.extend(media_items)

            # Check if we've exhausted available media
            if len(media_items) < per_page:
                # Got fewer than requested, no more pages
                break

            # Check total pages from headers (lowercase per requests library)
            total_pages = int(headers.get("x-wp-totalpages", 1))
            if page >= total_pages:
                break

            remaining -= len(media_items)
            page += 1

        return all_media

    def get_media(self, media_id: int) -> Media:
        """
        Get a specific media item by ID.

        Args:
            media_id: The media ID

        Returns:
            Media model with details
        """
        endpoint = "/media"
        params = {"include": str(media_id), "per_page": 1}
        response = self._make_request("GET", endpoint, params=params)

        if isinstance(response, list):
            if not response:
                raise ClientError(f"Media {media_id} not found")
            response = response[0]

        return create_media(response)

    def delete_media(self, media_id: int, force: bool = False) -> dict:
        """
        Delete a media item.

        Args:
            media_id: The media ID
            force: If True, permanently delete. If False, move to trash.

        Returns:
            Dict with deletion result
        """
        endpoint = f"/media/{media_id}"
        params = None
        if force:
            params = {"force": "true"}

        response = self._make_request("DELETE", endpoint, params=params)

        return response

    # ==================== Category Methods ====================

    def list_categories(
        self,
        limit: int = 100,
        filters: Optional[Dict[str, str]] = None,
    ) -> List[Category]:
        """
        List categories from WordPress with automatic pagination.

        Automatically handles pagination when limit > 100 (WordPress API max per_page).
        Makes multiple requests as needed to fetch up to the requested limit.

        Args:
            limit: Maximum number of categories to return (default: 100)
            filters: Optional filters (search, parent, etc.)

        Returns:
            List of Category models
        """
        endpoint = "/categories"

        # WordPress REST API limits per_page to 100
        WP_MAX_PER_PAGE = 100

        all_categories: List[Category] = []
        page = 1
        remaining = limit

        while remaining > 0:
            # Request up to WP_MAX_PER_PAGE or remaining, whichever is smaller
            per_page = min(remaining, WP_MAX_PER_PAGE)

            params = {"per_page": per_page, "page": page}

            # Add filters if provided
            if filters:
                params.update(filters)

            response, headers = self._make_request("GET", endpoint, params=params, return_headers=True)

            # WordPress returns array directly
            if not isinstance(response, list):
                raise ClientError(f"Expected list response, got {type(response)}")

            # Convert to models and add to results
            categories = [create_category(cat) for cat in response]
            all_categories.extend(categories)

            # Check if we've exhausted available categories
            if len(categories) < per_page:
                # Got fewer than requested, no more pages
                break

            # Check total pages from headers (lowercase per requests library)
            total_pages = int(headers.get("x-wp-totalpages", 1))
            if page >= total_pages:
                break

            remaining -= len(categories)
            page += 1

        return all_categories

    def get_category(self, category_id: int) -> Category:
        """
        Get a specific category by ID.

        Args:
            category_id: The category ID

        Returns:
            Category model
        """
        endpoint = "/categories"
        params = {"include": str(category_id), "per_page": 1}
        response = self._make_request("GET", endpoint, params=params)

        if isinstance(response, list):
            if not response:
                raise ClientError(f"Category {category_id} not found")
            response = response[0]

        return create_category(response)

    def create_category(
        self,
        name: str,
        slug: Optional[str] = None,
        description: Optional[str] = None,
        parent: int = 0,
    ) -> Category:
        """
        Create a new WordPress category.

        Args:
            name: Category name
            slug: Optional URL slug
            description: Optional description
            parent: Parent category ID (0 for no parent)

        Returns:
            Category model of created category
        """
        endpoint = "/categories"
        data = {"name": name}

        if slug is not None:
            data["slug"] = slug
        if description is not None:
            data["description"] = description
        if parent != 0:
            data["parent"] = parent

        response = self._make_request("POST", endpoint, data=data)

        return create_category(response)

    def update_category(self, category_id: int, fields: Dict[str, Any]) -> Category:
        """
        Update an existing category.

        Args:
            category_id: The category ID
            fields: Dictionary of fields to update

        Returns:
            Category model of updated category
        """
        if not fields:
            raise ValueError("fields cannot be empty when updating a category")

        endpoint = f"/categories/{category_id}"
        response = self._make_request("POST", endpoint, data=fields)

        return create_category(response)

    def delete_category(self, category_id: int, force: bool = True) -> dict:
        """
        Delete a category.

        Args:
            category_id: The category ID
            force: Must be True for categories (no trash support)

        Returns:
            Dict with deletion result
        """
        endpoint = f"/categories/{category_id}"
        # Categories don't support trash, force must be true
        params = {"force": "true"}

        response = self._make_request("DELETE", endpoint, params=params)

        return response

    # ==================== Tag Methods ====================

    def list_tags(
        self,
        limit: int = 100,
        filters: Optional[Dict[str, str]] = None,
    ) -> List[Tag]:
        """
        List tags from WordPress with automatic pagination.

        Automatically handles pagination when limit > 100 (WordPress API max per_page).
        Makes multiple requests as needed to fetch up to the requested limit.

        Args:
            limit: Maximum number of tags to return (default: 100)
            filters: Optional filters (search, etc.)

        Returns:
            List of Tag models
        """
        endpoint = "/tags"

        # WordPress REST API limits per_page to 100
        WP_MAX_PER_PAGE = 100

        all_tags: List[Tag] = []
        page = 1
        remaining = limit

        while remaining > 0:
            # Request up to WP_MAX_PER_PAGE or remaining, whichever is smaller
            per_page = min(remaining, WP_MAX_PER_PAGE)

            params = {"per_page": per_page, "page": page}

            # Add filters if provided
            if filters:
                params.update(filters)

            response, headers = self._make_request("GET", endpoint, params=params, return_headers=True)

            # WordPress returns array directly
            if not isinstance(response, list):
                raise ClientError(f"Expected list response, got {type(response)}")

            # Convert to models and add to results
            tags = [create_tag(tag) for tag in response]
            all_tags.extend(tags)

            # Check if we've exhausted available tags
            if len(tags) < per_page:
                # Got fewer than requested, no more pages
                break

            # Check total pages from headers (lowercase per requests library)
            total_pages = int(headers.get("x-wp-totalpages", 1))
            if page >= total_pages:
                break

            remaining -= len(tags)
            page += 1

        return all_tags

    def get_tag(self, tag_id: int) -> Tag:
        """
        Get a specific tag by ID.

        Args:
            tag_id: The tag ID

        Returns:
            Tag model
        """
        endpoint = "/tags"
        params = {"include": str(tag_id), "per_page": 1}
        response = self._make_request("GET", endpoint, params=params)

        if isinstance(response, list):
            if not response:
                raise ClientError(f"Tag {tag_id} not found")
            response = response[0]

        return create_tag(response)

    def create_tag(
        self,
        name: str,
        slug: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Tag:
        """
        Create a new WordPress tag, or return the existing tag if it already exists.

        Args:
            name: Tag name
            slug: Optional URL slug
            description: Optional description

        Returns:
            Tag model of created or existing tag
        """
        endpoint = "/tags"
        data = {"name": name}

        if slug is not None:
            data["slug"] = slug
        if description is not None:
            data["description"] = description

        try:
            response = self._make_request("POST", endpoint, data=data)
            return create_tag(response)
        except ClientError as e:
            # Handle duplicate tag - WordPress returns 400 with "term_exists" error
            if "already exists" in str(e):
                # Search for existing tag by name
                existing = self.list_tags(limit=1, filters={"search": name})
                for tag in existing:
                    if tag.name.lower() == name.lower():
                        return tag
                # If exact match not found in search, try by slug
                slug_to_check = slug if slug else name.lower().replace(" ", "-")
                existing = self.list_tags(limit=100, filters={"slug": slug_to_check})
                for tag in existing:
                    if tag.slug == slug_to_check:
                        return tag
            # Re-raise if not a duplicate error or tag not found
            raise

    def update_tag(self, tag_id: int, fields: Dict[str, Any]) -> Tag:
        """
        Update an existing tag.

        Args:
            tag_id: The tag ID
            fields: Dictionary of fields to update

        Returns:
            Tag model of updated tag
        """
        if not fields:
            raise ValueError("fields cannot be empty when updating a tag")

        endpoint = f"/tags/{tag_id}"
        response = self._make_request("POST", endpoint, data=fields)

        return create_tag(response)

    def delete_tag(self, tag_id: int, force: bool = True) -> dict:
        """
        Delete a tag.

        Args:
            tag_id: The tag ID
            force: Must be True for tags (no trash support)

        Returns:
            Dict with deletion result
        """
        endpoint = f"/tags/{tag_id}"
        # Tags don't support trash, force must be true
        params = {"force": "true"}

        response = self._make_request("DELETE", endpoint, params=params)

        return response

    # ==================== Plugin Methods ====================

    def get_plugin_update_count(self) -> int:
        """
        Get the number of plugin updates WordPress currently reports.

        Returns:
            Count of plugin updates from the site's update subsystem.
        """
        response = self._make_request(
            "GET",
            "/jetpack/v4/updates/plugins",
            base_url=self._wp_json_base_url(),
        )

        if not isinstance(response, dict):
            raise ClientError(f"Expected plugin update count response to be a dict, got {type(response)}")
        count = response.get("count")
        if not isinstance(count, int):
            raise ClientError("Plugin update count response did not include an integer count")
        return count

    def _get_jetpack_connection_data(self) -> dict:
        response = self._make_request(
            "GET",
            "/jetpack/v4/connection/data",
            base_url=self._wp_json_base_url(),
        )
        if not isinstance(response, dict):
            raise ClientError(f"Expected Jetpack connection response to be a dict, got {type(response)}")
        return response

    @staticmethod
    def _normalize_site_identifier(value: str) -> str:
        if not isinstance(value, str):
            raise ClientError(f"Expected site identifier to be a string, got {type(value)}")
        normalized = value.strip().lower()
        if not normalized:
            raise ClientError("Site identifier cannot be empty")
        parsed = urlparse(normalized if "://" in normalized else f"https://{normalized}")
        host = parsed.netloc or parsed.path
        host = host.rstrip("/")
        if not host:
            raise ClientError(f"Could not normalize site identifier: {value}")
        return host

    def _get_wpcom_site_record(self, *, interactive_token_refresh: bool = True) -> dict:
        configured_site = self.config.wpcom_site
        if not configured_site:
            raise ClientError("Missing WordPress.com site identifier: WPCOM_SITE")
        normalized_configured_site = self._normalize_site_identifier(configured_site)

        response = self._make_wpcom_request(
            "GET",
            "/me/sites",
            interactive_token_refresh=interactive_token_refresh,
        )
        if not isinstance(response, dict):
            raise ClientError(f"Expected WordPress.com /me/sites response to be a dict, got {type(response)}")
        sites = response.get("sites")
        if not isinstance(sites, list):
            raise ClientError("WordPress.com /me/sites response did not include sites list")

        for site in sites:
            if not isinstance(site, dict):
                raise ClientError(f"Expected WordPress.com site entry to be a dict, got {type(site)}")
            for key in ("URL", "domain"):
                raw_value = site.get(key)
                if raw_value is None:
                    continue
                if not isinstance(raw_value, str):
                    raise ClientError(f"Expected WordPress.com site {key} to be a string, got {type(raw_value)}")
                if self._normalize_site_identifier(raw_value) == normalized_configured_site:
                    return site

        raise ClientError(JETPACK_PLUGIN_MANAGEMENT_ERROR)

    @staticmethod
    def _assert_wpcom_site_has_plugin_management_access(site: dict) -> None:
        capabilities = site.get("capabilities")
        if capabilities is None:
            return
        if not isinstance(capabilities, dict):
            raise ClientError("WordPress.com site record did not include capabilities dict")

        capability_names = [name for name in ("update_plugins", "manage_options") if name in capabilities]
        if not capability_names:
            return

        allowed = False
        for name in capability_names:
            value = capabilities.get(name)
            if not isinstance(value, bool):
                raise ClientError(f"WordPress.com site capabilities.{name} was not a boolean")
            if value:
                allowed = True
        if not allowed:
            raise ClientError(JETPACK_PLUGIN_MANAGEMENT_ERROR)

    def _assert_jetpack_plugin_management_connected(self, *, interactive_token_refresh: bool = True) -> None:
        connection = self._get_jetpack_connection_data()
        current_user = connection.get("currentUser")
        if not isinstance(current_user, dict):
            raise ClientError("Jetpack connection response did not include currentUser")
        is_connected = current_user.get("isConnected")
        if not isinstance(is_connected, bool):
            raise ClientError("Jetpack connection response did not include currentUser.isConnected boolean")
        if not is_connected:
            raise ClientError(JETPACK_PLUGIN_MANAGEMENT_ERROR)

        permissions = current_user.get("permissions")
        if not isinstance(permissions, dict):
            raise ClientError("Jetpack connection response did not include currentUser.permissions")
        manage_plugins = permissions.get("manage_plugins")
        if not isinstance(manage_plugins, bool):
            raise ClientError("Jetpack connection response did not include currentUser.permissions.manage_plugins boolean")
        if not manage_plugins:
            raise ClientError(JETPACK_PLUGIN_MANAGEMENT_ERROR)

        self._assert_wpcom_plugin_endpoint_access(
            interactive_token_refresh=interactive_token_refresh,
        )

    def _assert_wpcom_plugin_endpoint_access(self, *, interactive_token_refresh: bool = True) -> None:
        site = quote(self.config.wpcom_site, safe="")
        self._make_wpcom_request(
            "GET",
            f"/sites/{site}/plugins",
            retry_on_forbidden=True,
            interactive_token_refresh=interactive_token_refresh,
        )

    def get_wordpress_org_plugin_info(self, slug: str) -> dict:
        """
        Get public plugin metadata from WordPress.org.

        Args:
            slug: WordPress.org plugin slug.

        Returns:
            Dict with status and version data.
        """
        if not slug:
            raise ValueError("slug cannot be empty")

        response = requests.get(
            "https://api.wordpress.org/plugins/info/1.2/",
            headers={"Accept": "application/json", "User-Agent": DEFAULT_USER_AGENT},
            params={
                "action": "plugin_information",
                "request[slug]": slug,
                "request[fields][versions]": "0",
            },
            timeout=30,
        )

        if response.status_code not in {200, 404}:
            raise ClientError(f"WordPress.org plugin lookup failed for {slug} ({response.status_code}): {response.text}")

        data = response.json()
        if not isinstance(data, dict):
            raise ClientError(f"Expected WordPress.org plugin lookup response to be a dict, got {type(data)}")

        if response.status_code == 404:
            if data.get("error") == "closed":
                return {"status": "closed", "slug": slug}
            return {"status": "not_found", "slug": slug}

        version = data.get("version")
        if not isinstance(version, str) or not version:
            raise ClientError(f"WordPress.org plugin lookup for {slug} did not include a version")
        return {"status": "found", "slug": slug, "version": version}

    @staticmethod
    def _plugin_slug(plugin: Plugin) -> str:
        slug = plugin.plugin.split("/", 1)[0]
        if not slug:
            raise ClientError(f"Could not determine plugin slug from {plugin.plugin}")
        return slug

    def enrich_plugins_with_update_status(self, plugins: List[Plugin]) -> List[Plugin]:
        """
        Add latest-version and update-status metadata to plugins.

        Public WordPress.org plugins use the WordPress.org plugin API. Private
        plugins are marked current only when the site update subsystem reports
        no unresolved private updates.
        """
        update_count = self.get_plugin_update_count()
        public_results: Dict[str, dict] = {}
        public_available_count = 0

        for plugin in plugins:
            slug = self._plugin_slug(plugin)
            result = self.get_wordpress_org_plugin_info(slug)
            public_results[plugin.plugin] = result
            if result["status"] == "found" and plugin.version != result["version"]:
                public_available_count += 1

        unresolved_private_updates = update_count > public_available_count
        enriched_plugins: List[Plugin] = []
        for plugin in plugins:
            plugin_data = plugin.model_dump()
            result = public_results[plugin.plugin]

            if result["status"] == "found":
                latest_version = result["version"]
                plugin_data["latest_version"] = latest_version
                plugin_data["update_version"] = latest_version
                plugin_data["update_status"] = "current" if plugin.version == latest_version else "available"
                plugin_data["latest_version_source"] = "wordpress.org"
            elif result["status"] == "closed":
                plugin_data["latest_version"] = None
                plugin_data["update_version"] = None
                plugin_data["update_status"] = "closed"
                plugin_data["latest_version_source"] = "wordpress.org"
            elif unresolved_private_updates:
                plugin_data["latest_version"] = None
                plugin_data["update_version"] = None
                plugin_data["update_status"] = "unverified"
                plugin_data["latest_version_source"] = "site_update_check"
            else:
                plugin_data["latest_version"] = plugin.version
                plugin_data["update_version"] = plugin.version
                plugin_data["update_status"] = "current"
                plugin_data["latest_version_source"] = "site_update_check"

            enriched_plugins.append(create_plugin(plugin_data))

        return enriched_plugins

    def list_plugins(self, include_update_status: bool = False) -> List[Plugin]:
        """
        List all installed plugins.

        Args:
            include_update_status: Add latest-version and update-status metadata.

        Returns:
            List of Plugin models
        """
        endpoint = "/plugins"
        response = self._make_request("GET", endpoint)

        if not isinstance(response, list):
            raise ClientError(f"Expected list response, got {type(response)}")

        plugins = [create_plugin(p) for p in response]
        if include_update_status:
            return self.enrich_plugins_with_update_status(plugins)
        return plugins

    @staticmethod
    def _plugin_identifier_values(plugin: Plugin) -> List[str]:
        """Return exact identifiers users can discover from plugin list output."""
        values = [plugin.plugin, plugin.plugin.split("/", 1)[0], plugin.name]
        if plugin.textdomain:
            values.append(plugin.textdomain)
        return values

    def resolve_plugin_identifier(self, plugin: str) -> str:
        """
        Resolve a user-facing plugin identifier to the REST API plugin path.

        WordPress.com plugin detail endpoints require the full plugin path, but
        list output exposes several practical identifiers: plugin path, slug,
        name, and textdomain.
        """
        if not plugin or not plugin.strip():
            raise ValueError("plugin cannot be empty")

        normalized = plugin.strip().casefold()
        matches = [
            installed
            for installed in self.list_plugins()
            if normalized in {value.casefold() for value in self._plugin_identifier_values(installed)}
        ]

        if not matches:
            raise ClientError(
                f"Plugin not found: {plugin}. Use a plugin path, slug, textdomain, or exact name from plugins list."
            )
        if len(matches) > 1:
            match_names = ", ".join(sorted(match.plugin for match in matches))
            raise ClientError(f"Plugin identifier is ambiguous: {plugin}. Matches: {match_names}")

        return matches[0].plugin

    def get_plugin(self, plugin: str, include_update_status: bool = False) -> Plugin:
        """
        Get a specific plugin by its identifier.

        Args:
            plugin: Plugin identifier (e.g. "mailchimp-for-wp/mailchimp-for-wp")
            include_update_status: Add latest-version and update-status metadata.

        Returns:
            Plugin model
        """
        plugin_path = self.resolve_plugin_identifier(plugin)
        endpoint = f"/plugins/{plugin_path}"
        response = self._make_request("GET", endpoint)

        result = create_plugin(response)
        if include_update_status:
            return self.enrich_plugins_with_update_status([result])[0]
        return result

    def update_plugin(self, plugin: str, fields: Dict[str, Any]) -> Plugin:
        """
        Update plugin settings (status, auto_update).

        Args:
            plugin: Plugin identifier (e.g. "mailchimp-for-wp/mailchimp-for-wp")
            fields: Dictionary of fields to update (status, auto_update)

        Returns:
            Plugin model with updated settings
        """
        if not fields:
            raise ValueError("fields cannot be empty when updating a plugin")

        endpoint = f"/plugins/{plugin}"
        response = self._make_request("POST", endpoint, data=fields)

        return create_plugin(response)

    def delete_plugin(self, plugin: str) -> dict:
        """
        Delete (uninstall) a plugin. Plugin must be inactive first.

        Args:
            plugin: Plugin identifier (e.g. "mailchimp-for-wp/mailchimp-for-wp")

        Returns:
            Dict with deletion result
        """
        current = self.get_plugin(plugin)
        if current.status != "inactive":
            raise ClientError(f"Plugin {current.plugin} is {current.status}; deactivate it before deleting")

        endpoint = f"/plugins/{current.plugin}"
        try:
            response = self._make_request("DELETE", endpoint, retry=False)
        except ClientError as exc:
            message = str(exc)
            if "Could not fully remove the plugin" not in message:
                raise
            still_installed = [installed for installed in self.list_plugins() if installed.plugin == current.plugin]
            if still_installed:
                installed = still_installed[0]
                raise ClientError(
                    "Plugin deletion failed and readback confirms the plugin is still installed: "
                    f"plugin={installed.plugin}, status={installed.status}, version={installed.version}. "
                    f"API error: {message}"
                ) from exc
            return {
                "deleted": True,
                "plugin": current.plugin,
                "status": "absent_after_partial_delete_error",
                "api_error": message,
            }

        return response

    def install_plugin(self, slug: str, activate: bool = False) -> Plugin:
        """
        Install a plugin from wordpress.org.

        Args:
            slug: Plugin slug on wordpress.org (e.g. "mailchimp-for-wp")
            activate: If True, activate after installation

        Returns:
            Plugin model of installed plugin
        """
        endpoint = "/plugins"
        data = {"slug": slug, "status": "active" if activate else "inactive"}
        response = self._make_request("POST", endpoint, data=data)

        return create_plugin(response)

    def upgrade_plugin(self, plugin: str) -> Plugin:
        """
        Upgrade a plugin to its latest version.

        Uses Jetpack's native WordPress.com plugin update operation, which calls
        WordPress' plugin upgrader without deleting or reinstalling the plugin.

        Args:
            plugin: Plugin identifier (e.g. "mailchimp-for-wp/mailchimp-for-wp")

        Returns:
            Plugin model with updated version
        """
        missing_wpcom_credentials = self.config.get_missing_wpcom_credentials()
        if missing_wpcom_credentials:
            raise ClientError(build_wpcom_missing_credentials_message(missing_wpcom_credentials))

        current = self.get_plugin(plugin, include_update_status=True)
        if current.update_status != "available":
            raise ClientError(f"Plugin {plugin} does not have an available update")
        if not current.latest_version:
            raise ClientError(f"Plugin {plugin} does not have a known latest version")
        self._assert_jetpack_plugin_management_connected(interactive_token_refresh=False)

        site = quote(self.config.wpcom_site, safe="")
        plugin_id = quote(plugin, safe="")
        response = self._make_wpcom_request(
            "POST",
            f"/sites/{site}/plugins/{plugin_id}/update/",
            interactive_token_refresh=False,
        )
        if not isinstance(response, dict):
            raise ClientError(f"Expected WordPress.com plugin update response to be a dict, got {type(response)}")

        upgraded = self.get_plugin(plugin, include_update_status=True)
        if not upgraded.latest_version:
            raise ClientError(f"Plugin {plugin} did not report a latest version after update")
        if upgraded.version != upgraded.latest_version or upgraded.update_status != "current":
            raise ClientError(
                f"Plugin {plugin} update did not complete: "
                f"installed {upgraded.version}, latest {upgraded.latest_version}, status {upgraded.update_status}"
            )

        return upgraded

    # ==================== Maintenance Report Methods ====================

    @staticmethod
    def _version_numbers(value: str) -> List[int]:
        if not isinstance(value, str) or not value.strip():
            raise ClientError(f"Expected non-empty version string, got {value!r}")
        numbers = [int(part) for part in re.findall(r"\d+", value)]
        if not numbers:
            raise ClientError(f"Version string did not contain numeric components: {value}")
        return numbers

    @classmethod
    def _compare_versions(cls, installed: str, expected: str) -> int:
        installed_parts = cls._version_numbers(installed)
        expected_parts = cls._version_numbers(expected)
        width = max(len(installed_parts), len(expected_parts))
        installed_parts.extend([0] * (width - len(installed_parts)))
        expected_parts.extend([0] * (width - len(expected_parts)))
        if installed_parts < expected_parts:
            return -1
        if installed_parts > expected_parts:
            return 1
        return 0

    @staticmethod
    def _operator_matches(compare_result: int, operator: str) -> bool:
        normalized = operator.strip().lower()
        if normalized in {"lt", "<"}:
            return compare_result < 0
        if normalized in {"lte", "le", "<="}:
            return compare_result <= 0
        if normalized in {"gt", ">"}:
            return compare_result > 0
        if normalized in {"gte", "ge", ">="}:
            return compare_result >= 0
        if normalized in {"eq", "=", "=="}:
            return compare_result == 0
        raise ClientError(f"Unsupported vulnerability version operator: {operator}")

    @classmethod
    def vulnerability_affects_version(cls, installed_version: str, vulnerability: dict) -> bool:
        """Return whether a WPVulnerability record applies to an installed version."""
        operator_data = vulnerability.get("operator")
        if not isinstance(operator_data, dict):
            raise ClientError("Vulnerability record did not include operator data")

        checks: List[bool] = []
        for version_key, operator_key in (("min_version", "min_operator"), ("max_version", "max_operator")):
            expected_version = operator_data.get(version_key)
            operator = operator_data.get(operator_key)
            if expected_version is None and operator is None:
                continue
            if not isinstance(expected_version, str) or not expected_version:
                raise ClientError(f"Vulnerability operator did not include {version_key}")
            if not isinstance(operator, str) or not operator:
                raise ClientError(f"Vulnerability operator did not include {operator_key}")
            checks.append(cls._operator_matches(cls._compare_versions(installed_version, expected_version), operator))

        if checks:
            return all(checks)

        unfixed = operator_data.get("unfixed")
        if unfixed in {"1", 1, True}:
            return True
        raise ClientError("Vulnerability operator did not include a version range")

    def get_wpvulnerability_record(self, component_type: str, slug: str) -> dict:
        """Fetch a component record from the public WPVulnerability API."""
        if component_type not in {"plugin", "theme", "core"}:
            raise ValueError(f"Unsupported component type: {component_type}")
        if not slug or not slug.strip():
            raise ValueError("slug cannot be empty")

        url = f"{WPVULNERABILITY_API_BASE_URL}/{component_type}/{quote(slug.strip(), safe='')}"
        response = requests.get(
            url,
            headers={"Accept": "application/json", "User-Agent": DEFAULT_USER_AGENT},
            timeout=30,
        )

        if response.status_code == 404:
            return {
                "error": 1,
                "message": "Component was not found in WPVulnerability",
                "data": None,
                "updated": None,
            }
        if not response.ok:
            raise ClientError(f"WPVulnerability lookup failed for {component_type}:{slug} ({response.status_code}): {response.text}")

        data = response.json()
        if not isinstance(data, dict):
            raise ClientError(f"Expected WPVulnerability response to be a dict, got {type(data)}")
        if "data" not in data:
            raise ClientError("WPVulnerability response did not include data")
        return data

    @staticmethod
    def _vulnerability_severity(vulnerability: dict) -> Optional[str]:
        impact = vulnerability.get("impact")
        if not isinstance(impact, dict):
            return None
        for key in ("cvss3", "cvss"):
            score_data = impact.get(key)
            if isinstance(score_data, dict) and isinstance(score_data.get("severity"), str):
                return score_data["severity"]
        return None

    @staticmethod
    def _vulnerability_score(vulnerability: dict) -> Optional[str]:
        impact = vulnerability.get("impact")
        if not isinstance(impact, dict):
            return None
        for key in ("cvss3", "cvss"):
            score_data = impact.get(key)
            if isinstance(score_data, dict) and score_data.get("score") is not None:
                return str(score_data["score"])
        return None

    @classmethod
    def _summarize_vulnerability(cls, vulnerability: dict) -> dict:
        if not isinstance(vulnerability, dict):
            raise ClientError(f"Expected vulnerability entry to be a dict, got {type(vulnerability)}")
        uuid = vulnerability.get("uuid")
        name = vulnerability.get("name")
        if not isinstance(uuid, str) or not uuid:
            raise ClientError("Vulnerability entry did not include uuid")
        if not isinstance(name, str) or not name:
            raise ClientError("Vulnerability entry did not include name")
        source = vulnerability.get("source") or []
        if not isinstance(source, list):
            raise ClientError("Vulnerability source was not a list")
        source_ids = [
            item.get("id")
            for item in source
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
        ]
        return {
            "uuid": uuid,
            "name": name,
            "severity": cls._vulnerability_severity(vulnerability),
            "score": cls._vulnerability_score(vulnerability),
            "source_ids": source_ids,
        }

    def _scan_component(self, component_type: str, slug: str, name: str, installed_version: str, status: str) -> dict:
        record = self.get_wpvulnerability_record(component_type, slug)
        data = record.get("data")
        if data is None:
            return {
                "component_type": component_type,
                "slug": slug,
                "name": name,
                "installed_version": installed_version,
                "status": status,
                "database_status": "not_found",
                "affected_vulnerability_count": 0,
                "vulnerabilities": [],
            }
        if not isinstance(data, dict):
            raise ClientError(f"Expected WPVulnerability data to be a dict, got {type(data)}")

        vulnerability_entries = data.get("vulnerability") or []
        if not isinstance(vulnerability_entries, list):
            raise ClientError("WPVulnerability data.vulnerability was not a list")

        affected = [
            self._summarize_vulnerability(vulnerability)
            for vulnerability in vulnerability_entries
            if self.vulnerability_affects_version(installed_version, vulnerability)
        ]
        return {
            "component_type": component_type,
            "slug": slug,
            "name": name,
            "installed_version": installed_version,
            "status": status,
            "database_status": "found",
            "affected_vulnerability_count": len(affected),
            "vulnerabilities": affected,
        }

    def security_scan(self, active_only: bool = False) -> dict:
        """Scan installed plugins and themes against WPVulnerability."""
        plugins = self.list_plugins(include_update_status=True)
        themes = self.list_themes()
        settings = self.get_site_settings()

        plugin_results = []
        for plugin in plugins:
            if active_only and plugin.status != "active":
                continue
            plugin_results.append(
                self._scan_component(
                    "plugin",
                    self._plugin_slug(plugin),
                    plugin.name,
                    plugin.version,
                    plugin.status,
                )
            )

        theme_results = [
            self._scan_component("theme", theme["theme"], theme["name"], theme["version"], theme["status"])
            for theme in themes
        ]

        affected = [
            result
            for result in plugin_results + theme_results
            if result["affected_vulnerability_count"] > 0
        ]

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "source": {
                "name": "WPVulnerability",
                "url": WPVULNERABILITY_API_BASE_URL,
            },
            "site": {
                "title": settings.get("title"),
                "url": settings.get("url"),
            },
            "summary": {
                "plugins_checked": len(plugin_results),
                "themes_checked": len(theme_results),
                "affected_component_count": len(affected),
                "affected_vulnerability_count": sum(result["affected_vulnerability_count"] for result in affected),
                "core_status": "unavailable",
            },
            "core": {
                "status": "unavailable",
                "reason": "The authenticated WordPress REST endpoints used by this CLI do not expose the installed core version.",
            },
            "plugins": plugin_results,
            "themes": theme_results,
            "affected_components": affected,
        }

    def health_report(self) -> dict:
        """Build a structured WordPress maintenance health report."""
        plugins = self.list_plugins(include_update_status=True)
        themes = self.list_themes()
        settings = self.get_site_settings()
        plugin_records = [plugin.model_dump() for plugin in plugins]
        theme_records = themes

        updates_available = [
            plugin for plugin in plugin_records if plugin.get("update_status") == "available"
        ]
        closed_plugins = [
            plugin for plugin in plugin_records if plugin.get("update_status") == "closed"
        ]
        unverified_plugins = [
            plugin for plugin in plugin_records if plugin.get("update_status") == "unverified"
        ]

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "site": {
                "title": settings.get("title"),
                "url": settings.get("url"),
                "description": settings.get("description"),
                "timezone": settings.get("timezone"),
            },
            "wordpress": {
                "core_version": None,
                "status": "unavailable",
                "reason": "The authenticated WordPress REST endpoints used by this CLI do not expose the installed core version.",
            },
            "php": {
                "version": None,
                "status": "unavailable",
                "reason": "The authenticated WordPress REST endpoints used by this CLI do not expose PHP runtime version.",
            },
            "plugins": {
                "count": len(plugin_records),
                "active_count": sum(1 for plugin in plugin_records if plugin.get("status") == "active"),
                "inactive_count": sum(1 for plugin in plugin_records if plugin.get("status") == "inactive"),
                "updates_available_count": len(updates_available),
                "closed_count": len(closed_plugins),
                "unverified_count": len(unverified_plugins),
                "updates_available": updates_available,
                "closed": closed_plugins,
                "unverified": unverified_plugins,
                "items": plugin_records,
            },
            "themes": {
                "count": len(theme_records),
                "active": [theme for theme in theme_records if theme["status"] == "active"],
                "inactive": [theme for theme in theme_records if theme["status"] != "active"],
                "items": theme_records,
            },
        }


# Module-level client instance - singleton pattern
_client: Optional[WordPressClient] = None


def get_client() -> WordPressClient:
    """Get or create the global WordPress client instance."""
    global _client
    if _client is None:
        _client = WordPressClient()
    return _client
