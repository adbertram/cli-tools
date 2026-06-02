"""Slack API client with automatic token management."""
import json
import warnings
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

warnings.filterwarnings("ignore", module="urllib3")

import requests

from .config import get_config
from cli_tools_shared.data_cache import cached
from cli_tools_shared.filters import validate_filters, FilterValidationError


# Load API operations token requirements from JSON
_API_OPERATIONS: Optional[Dict[str, str]] = None


def _load_api_operations() -> Dict[str, str]:
    """Load API operations to token type mapping from JSON file."""
    global _API_OPERATIONS
    if _API_OPERATIONS is None:
        json_path = Path(__file__).resolve().parent / "api_operations.json"
        with open(json_path, "r") as f:
            data = json.load(f)
        _API_OPERATIONS = data.get("operations", {})
    return _API_OPERATIONS


def get_api_type_for_endpoint(endpoint: str) -> str:
    """Get the required API type for a given endpoint.

    Args:
        endpoint: The Slack API endpoint (e.g., "saved.list")

    Returns:
        The API type: "bot", "user", or "session"
    """
    operations = _load_api_operations()
    return operations.get(endpoint, ApiType.BOT)


class ClientError(Exception):
    """Custom exception for Slack API errors."""
    pass


class ApiType:
    """API type constants for token selection.

    Different Slack APIs require different token types:
    - BOT: Works with any token - prefers bot (xoxb) from OAuth app
    - USER: Requires user context (user or session token)
    - SESSION: Requires session token (xoxc) for internal/undocumented APIs
    """
    BOT = "bot"            # Works with bot, user, or session token (prefers bot)
    USER = "user"          # Requires user token (xoxp or xoxc)
    SESSION = "session"    # Requires session token (xoxc only)


class SlackClient:
    """Client for interacting with Slack API.

    Uses the profile-based configuration from BaseConfig.
    """

    def __init__(self, profile: Optional[str] = None):
        """
        Initialize Slack client from configuration.

        Args:
            profile: Optional profile name. If None, uses the default profile.
        """
        self.config = get_config(profile=profile)
        self._access_token = self.config._get("ACCESS_TOKEN")
        self._refresh_token = self.config._get("REFRESH_TOKEN")  # 'd' cookie

        if not self._access_token:
            raise ClientError(
                "Missing ACCESS_TOKEN. Run 'slack auth login' to authenticate."
            )

        self.base_url = self.config.base_url
        self._update_headers()
        self._update_cookies()

    def _update_headers(self, token: Optional[str] = None):
        """Update request headers with current credentials."""
        token = token or self._access_token
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def _update_cookies(self, token: Optional[str] = None):
        """Update cookies for xoxc token authentication."""
        self.cookies = {}
        token = token or self._access_token

        # Only set 'd' cookie for xoxc session tokens
        if token and token.startswith("xoxc-") and self._refresh_token:
            self.cookies["d"] = self._refresh_token

    def _get_token_for_api(self, api_type: str = ApiType.BOT) -> Optional[str]:
        """Get the appropriate token for the specified API type.

        With single-profile model, we always use ACCESS_TOKEN.
        The api_type parameter is kept for API compatibility but currently
        we don't support multiple token types per profile.
        """
        return self._access_token

    def has_token_for_api(self, api_type: str = ApiType.BOT) -> bool:
        """Check if a suitable token is available for the specified API type."""
        return bool(self._access_token)

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        files: Optional[Dict] = None,
        api_type: Optional[str] = None,
        form_data: Optional[Dict] = None,
    ) -> Dict:
        """
        Make an HTTP request to the Slack API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: API endpoint path (e.g., "/conversations.list")
            data: Request body data (sent as JSON)
            params: Query parameters
            files: Files to upload
            api_type: Type of API for token selection.
            form_data: Form-encoded body data (sent as application/x-www-form-urlencoded)

        Returns:
            Response JSON data

        Raises:
            ClientError: If request fails
        """
        url = f"{self.base_url}/{endpoint}" if not endpoint.startswith('/') else f"{self.base_url}{endpoint}"

        # Auto-detect api_type from endpoint if not explicitly provided
        if api_type is None:
            api_type = get_api_type_for_endpoint(endpoint)

        # Get the token
        token = self._get_token_for_api(api_type)
        if not token:
            raise ClientError(
                f"No token available. Run 'slack auth login' to authenticate."
            )

        # Update headers and cookies for this specific token
        self._update_headers(token)
        self._update_cookies(token)

        request_kwargs = {
            "method": method,
            "url": url,
            "headers": self.headers,
        }

        # Include cookies for xoxc token authentication
        if self.cookies:
            request_kwargs["cookies"] = self.cookies

        if files:
            # For file uploads, use multipart form encoding
            headers_copy = self.headers.copy()
            headers_copy.pop("Content-Type", None)
            request_kwargs["headers"] = headers_copy
            request_kwargs["data"] = data
            request_kwargs["files"] = files
        elif form_data:
            # Send as application/x-www-form-urlencoded (required by some endpoints)
            headers_copy = self.headers.copy()
            headers_copy.pop("Content-Type", None)
            request_kwargs["headers"] = headers_copy
            request_kwargs["data"] = form_data
        elif data:
            request_kwargs["json"] = data
        else:
            request_kwargs["params"] = params

        # Make the request
        response = requests.request(**request_kwargs)

        if not response.ok:
            try:
                error_data = response.json()
                error_msg = error_data.get("error") or error_data.get("message") or response.text
            except Exception:
                error_msg = response.text
            raise ClientError(f"API request failed ({response.status_code}): {error_msg}")

        # Handle empty response (204 No Content)
        if response.status_code == 204:
            return {"ok": True}

        result = response.json()

        # Slack API always returns {"ok": true/false}
        if not result.get("ok"):
            error_msg = result.get("error", "Unknown error")
            raise ClientError(f"Slack API error: {error_msg}")

        return result

    # ==================== Workspace Methods ====================

    def auth_test(self) -> Dict:
        """Test authentication and get workspace info."""
        return self._make_request("GET", "auth.test")

    @cached
    def get_current_user_id(self) -> str:
        """Get the current authenticated user's ID."""
        auth = self.auth_test()
        return auth.get("user_id", "")

    @cached
    def get_client_counts(self) -> Dict:
        """Get unread counts for all channels, DMs, and threads."""
        data = {
            "thread_counts_by_channel": True,
            "org_wide_aware": True,
            "include_file_channels": True,
        }
        return self._make_request("POST", "client.counts", data=data)

    @cached
    def get_team_info(self) -> Dict:
        """Get information about the current workspace."""
        return self._make_request("GET", "team.info")

    # ==================== Channel/Conversation Methods ====================

    @cached
    def list_channels(
        self,
        limit: int = 100,
        cursor: Optional[str] = None,
        types: Optional[str] = "public_channel,private_channel",
        exclude_archived: bool = True,
    ) -> Dict:
        """List channels in the workspace."""
        token = self._access_token
        if token and token.startswith("xoxc-"):
            params = {
                "limit": min(limit, 1000),
                "types": types,
            }
            if cursor:
                params["cursor"] = cursor
            result = self._make_request("GET", "users.conversations", params=params)

            if exclude_archived and result.get("ok") and result.get("channels"):
                result["channels"] = [
                    ch for ch in result["channels"]
                    if not ch.get("is_archived", False)
                ]
            return result

        params = {
            "limit": min(limit, 1000),
            "types": types,
            "exclude_archived": exclude_archived,
        }
        if cursor:
            params["cursor"] = cursor
        return self._make_request("GET", "conversations.list", params=params)

    @cached
    def get_channel_info(self, channel_id: str) -> Dict:
        """Get information about a specific channel."""
        return self._make_request("GET", "conversations.info", params={"channel": channel_id})

    def create_channel(self, name: str, is_private: bool = False) -> Dict:
        """Create a new channel."""
        data = {"name": name, "is_private": is_private}
        return self._make_request("POST", "conversations.create", data=data)

    def archive_channel(self, channel_id: str) -> Dict:
        """Archive a channel."""
        return self._make_request("POST", "conversations.archive", data={"channel": channel_id})

    def join_channel(self, channel_id: str) -> Dict:
        """Join a channel."""
        return self._make_request("POST", "conversations.join", data={"channel": channel_id})

    def leave_channel(self, channel_id: str) -> Dict:
        """Leave a channel."""
        return self._make_request("POST", "conversations.leave", data={"channel": channel_id})

    @cached
    def get_channel_members(
        self,
        channel_id: str,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> Dict:
        """Get members of a channel."""
        params = {"channel": channel_id, "limit": min(limit, 1000)}
        if cursor:
            params["cursor"] = cursor
        return self._make_request("GET", "conversations.members", params=params)

    # ==================== Message Methods ====================

    def send_message(
        self,
        channel: str,
        text: str,
        thread_ts: Optional[str] = None,
        username: Optional[str] = None,
    ) -> Dict:
        """Send a message to a channel."""
        data = {"channel": channel, "text": text}
        if thread_ts:
            data["thread_ts"] = thread_ts
        if username:
            data["username"] = username

        return self._make_request("POST", "chat.postMessage", data=data)

    @cached
    def get_message_history(
        self,
        channel: str,
        limit: int = 100,
        cursor: Optional[str] = None,
        oldest: Optional[str] = None,
        latest: Optional[str] = None,
        inclusive: bool = False,
    ) -> Dict:
        """Get message history for a channel."""
        params = {"channel": channel, "limit": min(limit, 1000)}
        if cursor:
            params["cursor"] = cursor
        if oldest:
            params["oldest"] = oldest
        if latest:
            params["latest"] = latest
        if inclusive:
            params["inclusive"] = "true"

        return self._make_request("GET", "conversations.history", params=params)

    @cached
    def search_messages(self, query: str, count: int = 20, page: int = 1) -> Dict:
        """Search messages in the workspace."""
        params = {
            "query": query,
            "count": min(count, 100),
            "page": page,
        }
        return self._make_request("GET", "search.messages", params=params)

    def delete_message(self, channel: str, ts: str) -> Dict:
        """Delete a message."""
        data = {"channel": channel, "ts": ts}
        return self._make_request("POST", "chat.delete", data=data)

    @cached
    def get_thread_replies(
        self,
        channel: str,
        thread_ts: str,
        limit: int = 100,
        cursor: Optional[str] = None,
        oldest: Optional[str] = None,
        latest: Optional[str] = None,
        inclusive: bool = False,
    ) -> Dict:
        """Get replies in a thread."""
        params = {
            "channel": channel,
            "ts": thread_ts,
            "limit": min(limit, 1000),
        }
        if cursor:
            params["cursor"] = cursor
        if oldest:
            params["oldest"] = oldest
        if latest:
            params["latest"] = latest
        if inclusive:
            params["inclusive"] = "true"

        return self._make_request("GET", "conversations.replies", params=params)

    # ==================== Direct Message Methods ====================

    def open_dm(self, user_id: str) -> Dict:
        """Open or resume a direct message channel with a user."""
        return self._make_request("POST", "conversations.open", data={"users": user_id})

    @cached
    def list_dms(
        self,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> Dict:
        """List direct message channels."""
        return self.list_channels(limit=limit, cursor=cursor, types="im", exclude_archived=False)

    @cached
    def list_group_dms(
        self,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> Dict:
        """List group direct message (MPIM) channels."""
        return self.list_channels(limit=limit, cursor=cursor, types="mpim", exclude_archived=False)

    def lookup_user_by_email(self, email: str) -> Dict:
        """Look up a user by their email address."""
        return self._make_request("GET", "users.lookupByEmail", params={"email": email})

    # ==================== User Methods ====================

    @cached
    def list_users(self, limit: int = 100, cursor: Optional[str] = None) -> Dict:
        """List users in the workspace."""
        params = {"limit": min(limit, 1000)}
        if cursor:
            params["cursor"] = cursor

        return self._make_request("GET", "users.list", params=params)

    @cached
    def get_user_info(self, user_id: str) -> Dict:
        """Get information about a specific user."""
        return self._make_request("GET", "users.info", params={"user": user_id})

    def set_user_status(
        self,
        status_text: str,
        status_emoji: str = "",
        status_expiration: Optional[int] = None,
    ) -> Dict:
        """Set the user's status."""
        profile = {
            "status_text": status_text,
            "status_emoji": status_emoji,
        }
        if status_expiration:
            profile["status_expiration"] = status_expiration

        import json
        data = {"profile": json.dumps(profile)}
        return self._make_request("POST", "users.profile.set", data=data)

    def set_user_photo(self, image_path: Path) -> Dict:
        """Set the authenticated user's profile photo."""
        if not image_path.is_file():
            raise ClientError(f"Profile image not found: {image_path}")

        with image_path.open("rb") as image_file:
            files = {"image": (image_path.name, image_file, "image/png")}
            return self._make_request("POST", "users.setPhoto", files=files)

    # ==================== File Methods ====================

    @cached
    def list_files(
        self,
        channel: Optional[str] = None,
        user: Optional[str] = None,
        types: Optional[str] = None,
        ts_from: Optional[str] = None,
        ts_to: Optional[str] = None,
        count: int = 100,
        page: int = 1,
    ) -> Dict:
        """List files in the workspace."""
        params = {"count": min(count, 1000), "page": page}
        if channel:
            params["channel"] = channel
        if user:
            params["user"] = user
        if types:
            params["types"] = types
        if ts_from:
            params["ts_from"] = ts_from
        if ts_to:
            params["ts_to"] = ts_to

        return self._make_request("GET", "files.list", params=params)

    def upload_file(
        self,
        file_path: str,
        channels: Optional[str] = None,
        title: Optional[str] = None,
        initial_comment: Optional[str] = None,
    ) -> Dict:
        """Upload a file to Slack using the 3-step external upload flow.

        Steps:
        1. files.getUploadURLExternal - get a pre-signed upload URL
        2. POST file content to that URL
        3. files.completeUploadExternal - finalize and share the file
        """
        import os

        file_size = os.path.getsize(file_path)
        filename = os.path.basename(file_path)

        # Step 1: Get upload URL (this endpoint requires form-encoded data)
        url_response = self._make_request(
            "POST",
            "files.getUploadURLExternal",
            form_data={"filename": filename, "length": file_size},
        )
        upload_url = url_response["upload_url"]
        file_id = url_response["file_id"]

        # Step 2: Upload file content to the pre-signed URL
        with open(file_path, "rb") as f:
            upload_resp = requests.post(
                upload_url,
                data=f,
                headers={"Content-Type": "application/octet-stream"},
            )
            if not upload_resp.ok:
                raise ClientError(
                    f"File upload to pre-signed URL failed ({upload_resp.status_code}): {upload_resp.text}"
                )

        # Step 3: Complete the upload and share to channel(s)
        complete_data: Dict[str, Any] = {
            "files": [{"id": file_id, "title": title or filename}],
        }
        if channels:
            # The API accepts channel_id for a single channel, or channels for multiple
            if "," in channels:
                complete_data["channels"] = channels
            else:
                complete_data["channel_id"] = channels
        if initial_comment:
            complete_data["initial_comment"] = initial_comment

        complete_response = self._make_request(
            "POST",
            "files.completeUploadExternal",
            data=complete_data,
        )

        # Return a response shaped like the old files.upload for compatibility
        files_list = complete_response.get("files", [])
        file_info = files_list[0] if files_list else {"id": file_id, "title": title or filename}
        return {"ok": True, "file": file_info}

    @cached
    def get_file_info(self, file_id: str) -> Dict:
        """Get information about a file."""
        return self._make_request("GET", "files.info", params={"file": file_id})

    def delete_file(self, file_id: str) -> Dict:
        """Delete a file."""
        return self._make_request("POST", "files.delete", data={"file": file_id})

    def download_file(self, file_id: str, output_path: str) -> Dict:
        """Download a file from Slack."""
        file_info = self.get_file_info(file_id)
        file_data = file_info.get("file", {})

        download_url = file_data.get("url_private_download") or file_data.get("url_private")

        if not download_url:
            raise ClientError(f"No download URL available for file {file_id}")

        request_kwargs = {
            "method": "GET",
            "url": download_url,
            "headers": {"Authorization": self.headers.get("Authorization", "")},
            "stream": True,
        }

        if self.cookies:
            request_kwargs["cookies"] = self.cookies

        response = requests.request(**request_kwargs)

        if not response.ok:
            raise ClientError(f"Failed to download file: {response.status_code} {response.reason}")

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return {
            "ok": True,
            "file_id": file_id,
            "name": file_data.get("name"),
            "path": output_path,
            "size": file_data.get("size", 0),
        }

    # ==================== Canvas Methods ====================

    @cached
    def list_canvases(
        self,
        channel: Optional[str] = None,
        count: int = 100,
        page: int = 1,
    ) -> Dict:
        """List canvases in the workspace or channel."""
        params = {"types": "canvas", "count": min(count, 1000), "page": page}
        if channel:
            params["channel"] = channel

        return self._make_request("GET", "files.list", params=params)

    def test_auth(self) -> Dict:
        """Test browser session authentication and return status."""
        browser = self.config.get_browser()
        try:
            is_auth = browser.is_authenticated()
            result = {
                "authenticated": is_auth,
                "url": self.base_url,
                "details": {},
            }
            if is_auth and self._access_token:
                # Verify the token works
                try:
                    auth_data = self.auth_test()
                    result["details"] = {
                        "team": auth_data.get("team"),
                        "user": auth_data.get("user"),
                        "url": auth_data.get("url"),
                    }
                except Exception:
                    pass
            return result
        finally:
            try:
                browser.close()
            except Exception:
                pass

    @cached
    def get_canvas_sections(
        self,
        canvas_id: str,
        section_types: Optional[List[str]] = None,
        contains_text: Optional[str] = None,
    ) -> Dict:
        """Look up sections in a canvas."""
        criteria = {}
        if section_types:
            criteria["section_types"] = section_types
        if contains_text:
            criteria["contains_text"] = contains_text

        if not criteria:
            criteria["section_types"] = ["any_header"]

        import json
        data = {
            "canvas_id": canvas_id,
            "criteria": json.dumps(criteria),
        }
        return self._make_request("POST", "canvases.sections.lookup", data=data)

    # ==================== Saved Items / Reminders Methods ====================

    def list_saved(self) -> Dict:
        """List all saved items (Later) for the authenticated user.

        This is the API that powers Slack's "Later" feature.
        Returns reminders and saved messages.
        """
        return self._make_request("POST", "saved.list")

    def add_saved(
        self,
        channel: str,
        ts: str,
        date_due: Optional[int] = None,
    ) -> Dict:
        """Save a message for later (add to Slack's "Later" feature).

        Args:
            channel: The channel ID containing the message
            ts: The message timestamp to save
            date_due: Optional Unix timestamp for when to be reminded
        """
        data = {
            "item_id": channel,
            "ts": ts,
            "item_type": "message",
        }
        if date_due:
            data["date_due"] = date_due
        return self._make_request("POST", "saved.add", data=data)

    def list_reminders(self) -> Dict:
        """List all reminders created by or for the authenticated user."""
        return self._make_request("GET", "reminders.list")

    def complete_reminder(self, reminder_id: str) -> Dict:
        """Mark a reminder as complete."""
        return self._make_request("POST", "reminders.complete", data={"reminder": reminder_id})

    def delete_reminder(self, reminder_id: str) -> Dict:
        """Delete a reminder."""
        return self._make_request("POST", "reminders.delete", data={"reminder": reminder_id})


# Module-level client instance - singleton pattern
_client: Optional[SlackClient] = None
_global_profile: Optional[str] = None


def set_global_profile(profile: Optional[str]) -> None:
    """Set the global profile used by get_client() when no explicit profile is given.

    Called by the top-level --profile CLI option so all subcommands
    automatically use the specified profile.
    """
    global _global_profile, _client
    _global_profile = profile
    # Reset cached client so it picks up the new profile
    _client = None


def get_client(profile: Optional[str] = None) -> SlackClient:
    """Get or create the Slack client instance."""
    global _client
    effective_profile = profile if profile is not None else _global_profile
    if effective_profile is not None:
        if profile is not None:
            # Explicit per-call profile: always create fresh client
            return SlackClient(profile=effective_profile)
        # Global profile: use singleton
        if _client is None:
            _client = SlackClient(profile=effective_profile)
        return _client
    if _client is None:
        _client = SlackClient()
    return _client


def reset_client():
    """Reset the global client instance."""
    global _client
    _client = None


# Compatibility functions for old workspace-based code
def get_client_for_workspace_id(workspace_id: Optional[str] = None) -> SlackClient:
    """Get a Slack client.

    Compatibility function. With single-profile model, workspace_id is ignored.
    The client always uses the current profile's credentials.
    """
    return get_client()


def get_all_workspace_clients() -> List[SlackClient]:
    """Get clients for all configured workspaces.

    Compatibility function. With single-profile model, returns a list
    containing only the current profile's client.
    """
    try:
        return [get_client()]
    except ClientError:
        return []
