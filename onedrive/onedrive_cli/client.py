"""OneDrive client using Microsoft Graph API with MSAL authentication.

Uses MSAL (Microsoft Authentication Library) to obtain access tokens for Microsoft Graph API.
Implements exponential backoff retry for transient errors.
Tokens are cached locally for persistence.
"""
import base64
import json
import os
import random
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, BinaryIO

import requests

from .models import (
    Drive,
    DriveItem,
    DriveItemDetail,
    UploadSession,
    Permission,
    create_drive,
    create_drive_item,
    create_drive_item_detail,
    create_upload_session,
    create_permission,
)
from . import msal_auth


# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 2.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_JITTER = 0.1  # 10% jitter

# HTTP status codes that trigger retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Microsoft Graph API base URL
GRAPH_API_BASE_URL = "https://graph.microsoft.com/v1.0"

# Upload size threshold (4MB)
SIMPLE_UPLOAD_MAX_SIZE = 4 * 1024 * 1024  # 4MB

# Resumable upload chunk size (320 KiB - recommended by Microsoft)
UPLOAD_CHUNK_SIZE = 320 * 1024  # 320 KiB


def encode_share_url(share_url: str) -> str:
    """Encode a sharing URL as a Microsoft Graph ``shares`` identifier."""
    encoded = base64.urlsafe_b64encode(share_url.encode("utf-8")).decode("ascii")
    return f"u!{encoded.rstrip('=')}"


class ClientError(Exception):
    """Custom exception for OneDrive API errors."""
    pass


def get_access_token() -> str:
    """
    Get access token using MSAL authentication.

    Returns:
        Access token string

    Raises:
        ClientError: If not authenticated or token retrieval fails
    """
    try:
        return msal_auth.get_access_token()
    except RuntimeError as e:
        raise ClientError(str(e))


class OneDriveClient:
    """Client for OneDrive via Microsoft Graph API with Azure CLI authentication."""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        """
        Initialize OneDrive client.

        Args:
            max_retries: Maximum number of retry attempts for transient errors (default: 3)
            base_delay: Base delay in seconds for exponential backoff (default: 2.0)
            max_delay: Maximum delay in seconds between retries (default: 30.0)
            jitter: Random jitter factor to prevent thundering herd (default: 0.1)
        """
        self.base_url = GRAPH_API_BASE_URL
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self._access_token: Optional[str] = None

    def _get_access_token(self) -> str:
        """Get or refresh access token using MSAL."""
        # MSAL handles token caching and refresh
        self._access_token = get_access_token()
        return self._access_token

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with current access token."""
        token = self._get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

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
        """Extract Retry-After header value from response."""
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return None

        try:
            return float(retry_after)
        except ValueError:
            return None

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
        stream: bool = False,
    ) -> Any:
        """
        Make an HTTP request to Microsoft Graph API with exponential retry.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: API endpoint path (e.g., "/me/drives")
            data: Request body data
            params: Query parameters
            retry: Whether to retry on transient errors (default: True)
            stream: Whether to stream the response (for downloads)

        Returns:
            Response JSON data or Response object (if stream=True)

        Raises:
            ClientError: If request fails after all retries
        """
        url = f"{self.base_url}{endpoint}"

        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None

        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                headers = self._get_headers()
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=data,
                    params=params,
                    stream=stream,
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

        # ``Response.ok`` is True for ANY status under 400, including 3xx
        # redirects that requests could not auto-follow (e.g. a redirect with
        # no ``Location`` header). Only a true 2xx is success; treat every
        # other status as an error so its body is never blindly parsed as JSON.
        is_success = 200 <= last_response.status_code < 300

        # Return response object for streaming
        if stream and is_success:
            return last_response

        if not is_success:
            # Try to get error details from response
            try:
                error_data = last_response.json()
                error_msg = (
                    error_data.get("error", {}).get("message")
                    or error_data.get("message")
                    or last_response.text
                )
            except ValueError:
                error_msg = last_response.text
            if not error_msg:
                error_msg = (
                    "empty response body with no error details "
                    f"(Location header: {last_response.headers.get('Location') or 'none'})"
                    if 300 <= last_response.status_code < 400
                    else "empty response body with no error details"
                )
            raise ClientError(f"API request failed ({last_response.status_code}): {error_msg}")

        # Handle empty response (204 No Content)
        if last_response.status_code == 204:
            return {}

        try:
            return last_response.json()
        except ValueError as exc:
            raise ClientError(
                f"Graph API returned a {last_response.status_code} response "
                f"with a body that could not be parsed as JSON: {exc}"
            )

    # ==================== Drive Methods ====================

    @staticmethod
    def _drives_endpoint(
        user: Optional[str] = None,
        site: Optional[str] = None,
        group: Optional[str] = None,
    ) -> str:
        """
        Build the drive-collection endpoint for exactly one requested scope.

        Args:
            user: User ID or userPrincipalName owning the drives
            site: SharePoint site ID, or "hostname:/sites/name" addressing
            group: Microsoft 365 group ID owning the drives

        Returns:
            Graph endpoint path for the drive collection

        Raises:
            ClientError: If more than one scope is requested
        """
        requested = {"--user": user, "--site": site, "--group": group}
        supplied = sorted(flag for flag, value in requested.items() if value)
        if len(supplied) > 1:
            raise ClientError(
                f"Choose one drive scope: {', '.join(supplied)} are mutually exclusive."
            )

        if user:
            return f"/users/{user}/drives"

        if group:
            return f"/groups/{group}/drives"

        if site:
            # "hostname:/sites/name" addressing needs its path segment closed
            # with a colon before the /drives suffix.
            if ":" in site:
                return f"/sites/{site.rstrip(':')}:/drives"
            return f"/sites/{site}/drives"

        return "/me/drives"

    def list_drives(
        self,
        limit: int = 100,
        user: Optional[str] = None,
        site: Optional[str] = None,
        group: Optional[str] = None,
    ) -> List[Drive]:
        """
        List the drives in one scope.

        Defaults to the signed-in user's own drives (``/me/drives``). Accounts
        with no provisioned OneDrive have none; use ``site``, ``user``, or
        ``group`` to reach a SharePoint document library or another principal's
        drives.

        Args:
            limit: Maximum number of drives to return (passed to API via $top)
            user: User ID or userPrincipalName owning the drives
            site: SharePoint site ID, or "hostname:/sites/name" addressing
            group: Microsoft 365 group ID owning the drives

        Returns:
            List of Drive models

        Raises:
            ClientError: If the request fails or the response has no collection
        """
        endpoint = self._drives_endpoint(user=user, site=site, group=group)
        response = self._make_request("GET", endpoint, params={"$top": limit})

        if "value" not in response:
            raise ClientError(
                f"Graph response for {endpoint} contains no 'value' collection: {response}"
            )

        return [create_drive(d) for d in response["value"]][:limit]

    def get_drive(self, drive_id: str) -> Drive:
        """
        Get a specific drive by ID.

        Args:
            drive_id: The drive ID

        Returns:
            Drive model
        """
        response = self._make_request("GET", f"/drives/{drive_id}")
        return create_drive(response)

    # ==================== DriveItem Methods ====================

    def _is_item_id(self, item_ref: str) -> bool:
        """
        Determine if item_ref is an ID or a path.

        IDs are alphanumeric strings without slashes.
        Paths contain "/" characters.

        Args:
            item_ref: Item reference (ID or path)

        Returns:
            True if item_ref is an ID, False if it's a path
        """
        return "/" not in item_ref

    def _build_item_endpoint(self, drive_id: str, item_ref: str, suffix: str = "") -> str:
        """
        Build the appropriate endpoint based on item reference type.

        Args:
            drive_id: The drive ID
            item_ref: Item reference (ID or path)
            suffix: Optional endpoint suffix (e.g., "/children", "/content")

        Returns:
            Full endpoint path
        """
        if self._is_item_id(item_ref):
            return f"/drives/{drive_id}/items/{item_ref}{suffix}"
        else:
            # Path-based - strip leading slash if present
            path = item_ref.lstrip("/")
            if path:
                return f"/drives/{drive_id}/root:/{path}:{suffix}"
            else:
                return f"/drives/{drive_id}/root{suffix}"

    def list_items(
        self,
        drive_id: str,
        path: Optional[str] = None,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[DriveItem]:
        """
        List items in a drive folder.

        Args:
            drive_id: The drive ID
            path: Optional folder path (default: root)
            limit: Maximum number of items to return
            filters: Optional filter strings (not currently used - Graph API has limited filtering)

        Returns:
            List of DriveItem models
        """
        params = {"$top": limit}

        if path:
            path = path.lstrip("/")
            endpoint = f"/drives/{drive_id}/root:/{path}:/children"
        else:
            endpoint = f"/drives/{drive_id}/root/children"

        response = self._make_request("GET", endpoint, params=params)

        raw_items = response.get("value", [])
        return [create_drive_item(item) for item in raw_items]

    def get_item(self, drive_id: str, item_ref: str) -> DriveItemDetail:
        """
        Get a specific item by ID or path.

        Args:
            drive_id: The drive ID
            item_ref: Item ID or path (e.g., "ABC123" or "/Documents/file.txt")

        Returns:
            DriveItemDetail model
        """
        endpoint = self._build_item_endpoint(drive_id, item_ref)
        response = self._make_request("GET", endpoint)
        return create_drive_item_detail(response)

    def delete_item(self, drive_id: str, item_ref: str) -> None:
        """
        Delete an item by ID or path.

        Args:
            drive_id: The drive ID
            item_ref: Item ID or path
        """
        endpoint = self._build_item_endpoint(drive_id, item_ref)
        self._make_request("DELETE", endpoint)

    def download_item(self, drive_id: str, item_ref: str, local_path: str) -> str:
        """
        Download an item to a local file.

        Args:
            drive_id: The drive ID
            item_ref: Item ID or path
            local_path: Local file path to save to

        Returns:
            Local file path
        """
        # Get item metadata to get download URL
        item = self.get_item(drive_id, item_ref)

        if item.folder:
            raise ClientError("Cannot download a folder. Use a file item.")

        # Get content endpoint
        endpoint = self._build_item_endpoint(drive_id, item_ref, "/content")

        # Make streaming request
        response = self._make_request("GET", endpoint, stream=True)
        return self._write_stream_to_file(response, local_path)

    def resolve_shared_item(self, share_url: str) -> DriveItemDetail:
        """Resolve a OneDrive or SharePoint sharing URL to drive-item metadata."""
        share_id = encode_share_url(share_url)
        response = self._make_request("GET", f"/shares/{share_id}/driveItem")
        return create_drive_item_detail(response)

    def download_shared_item(self, share_url: str, local_path: str) -> str:
        """Resolve a sharing URL and download its file content."""
        share_id = encode_share_url(share_url)
        item = self.resolve_shared_item(share_url)
        if item.folder:
            raise ClientError("Cannot download a folder. Use a file sharing URL.")

        response = self._make_request(
            "GET",
            f"/shares/{share_id}/driveItem/content",
            stream=True,
        )
        return self._write_stream_to_file(response, local_path)

    @staticmethod
    def _write_stream_to_file(response: requests.Response, local_path: str) -> str:
        """Write a streaming HTTP response to a local file."""
        local_path_obj = Path(local_path)
        local_path_obj.parent.mkdir(parents=True, exist_ok=True)

        with open(local_path_obj, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return str(local_path_obj)

    def upload_item(
        self,
        drive_id: str,
        local_path: str,
        remote_path: str,
    ) -> DriveItem:
        """
        Upload a file to OneDrive.

        Automatically selects simple upload for files < 4MB,
        resumable upload for larger files.

        Args:
            drive_id: The drive ID
            local_path: Local file path to upload
            remote_path: Remote path (e.g., "/Documents/file.txt")

        Returns:
            DriveItem model of the uploaded file
        """
        local_path_obj = Path(local_path)

        if not local_path_obj.exists():
            raise ClientError(f"Local file not found: {local_path}")

        if not local_path_obj.is_file():
            raise ClientError(f"Not a file: {local_path}")

        file_size = local_path_obj.stat().st_size

        if file_size < SIMPLE_UPLOAD_MAX_SIZE:
            return self._simple_upload(drive_id, local_path_obj, remote_path)
        else:
            return self._resumable_upload(drive_id, local_path_obj, remote_path, file_size)

    def _simple_upload(self, drive_id: str, local_path: Path, remote_path: str) -> DriveItem:
        """
        Upload a small file (< 4MB) using simple upload.

        Args:
            drive_id: The drive ID
            local_path: Local file path
            remote_path: Remote path

        Returns:
            DriveItem model
        """
        # Build endpoint - PUT to content
        remote_path = remote_path.lstrip("/")
        endpoint = f"/drives/{drive_id}/root:/{remote_path}:/content"
        url = f"{self.base_url}{endpoint}"

        with open(local_path, "rb") as f:
            content = f.read()

        headers = self._get_headers()
        headers["Content-Type"] = "application/octet-stream"

        response = requests.put(url, headers=headers, data=content)

        if not response.ok:
            try:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
            except Exception:
                error_msg = response.text
            raise ClientError(f"Upload failed ({response.status_code}): {error_msg}")

        return create_drive_item(response.json())

    def _resumable_upload(
        self,
        drive_id: str,
        local_path: Path,
        remote_path: str,
        file_size: int,
    ) -> DriveItem:
        """
        Upload a large file using resumable upload session.

        Args:
            drive_id: The drive ID
            local_path: Local file path
            remote_path: Remote path
            file_size: Total file size in bytes

        Returns:
            DriveItem model
        """
        # Create upload session
        remote_path = remote_path.lstrip("/")
        endpoint = f"/drives/{drive_id}/root:/{remote_path}:/createUploadSession"

        session_response = self._make_request("POST", endpoint, data={
            "item": {
                "@microsoft.graph.conflictBehavior": "replace"
            }
        })

        upload_session = create_upload_session(session_response)
        upload_url = upload_session.upload_url

        # Upload in chunks
        with open(local_path, "rb") as f:
            offset = 0

            while offset < file_size:
                chunk_size = min(UPLOAD_CHUNK_SIZE, file_size - offset)
                chunk = f.read(chunk_size)

                # Content-Range header format: bytes {start}-{end}/{total}
                end_byte = offset + chunk_size - 1
                headers = {
                    "Content-Length": str(chunk_size),
                    "Content-Range": f"bytes {offset}-{end_byte}/{file_size}",
                }

                response = requests.put(upload_url, headers=headers, data=chunk)

                if response.status_code == 202:
                    # Upload in progress - continue
                    offset += chunk_size
                elif response.status_code in (200, 201):
                    # Upload complete
                    return create_drive_item(response.json())
                else:
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("error", {}).get("message", response.text)
                    except Exception:
                        error_msg = response.text
                    raise ClientError(f"Chunk upload failed ({response.status_code}): {error_msg}")

                offset += chunk_size

        raise ClientError("Upload completed but no response received")

    def create_folder(
        self,
        drive_id: str,
        name: str,
        parent_path: Optional[str] = None,
        conflict_behavior: str = "fail",
    ) -> DriveItem:
        """
        Create a new folder in OneDrive.

        Args:
            drive_id: The drive ID
            name: Name of the new folder
            parent_path: Parent folder path (default: root)
            conflict_behavior: What to do if folder exists - "fail", "rename", or "replace"

        Returns:
            DriveItem model of the created folder
        """
        # Build endpoint based on parent path
        if parent_path:
            parent_path = parent_path.lstrip("/")
            endpoint = f"/drives/{drive_id}/root:/{parent_path}:/children"
        else:
            endpoint = f"/drives/{drive_id}/root/children"

        # Request body with folder facet
        data = {
            "name": name,
            "folder": {},
            "@microsoft.graph.conflictBehavior": conflict_behavior,
        }

        response = self._make_request("POST", endpoint, data=data)
        return create_drive_item(response)

    def get_folder_by_path(
        self,
        path: str,
        drive_id: Optional[str] = None,
    ) -> DriveItemDetail:
        """
        Get a folder by path, optionally specifying a drive.

        If drive_id is not provided, uses the user's default OneDrive drive.

        Args:
            path: Folder path (e.g., "Documents/Reports" or "/Documents/Reports")
            drive_id: Optional drive ID. If not provided, uses /me/drive.

        Returns:
            DriveItemDetail model

        Raises:
            ClientError: If folder not found (404) or other API error
        """
        # Normalize path - strip leading slash
        path = path.lstrip("/")

        if drive_id:
            # Use specific drive
            endpoint = f"/drives/{drive_id}/root:/{path}"
        else:
            # Use user's default OneDrive
            endpoint = f"/me/drive/root:/{path}"

        response = self._make_request("GET", endpoint)
        return create_drive_item_detail(response)

    def create_sharing_link(
        self,
        drive_id: str,
        item_id: str,
        link_type: str = "view",
        scope: Optional[str] = None,
        expiration: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Permission:
        """
        Create a sharing link for a drive item (file or folder).

        Args:
            drive_id: The drive ID
            item_id: The item ID to share
            link_type: Link type - "view" (read-only), "edit" (read-write), or "embed"
            scope: Link scope - "anonymous" (anyone), "organization" (org members only),
                   or "users" (specific people). If None, uses organization default.
            expiration: Optional ISO 8601 datetime string for link expiration
            password: Optional password for the sharing link (OneDrive Personal only)

        Returns:
            Permission model with sharing link details

        Raises:
            ClientError: If sharing link creation fails
        """
        endpoint = f"/drives/{drive_id}/items/{item_id}/createLink"

        data: Dict[str, Any] = {"type": link_type}

        if scope:
            data["scope"] = scope
        if expiration:
            data["expirationDateTime"] = expiration
        if password:
            data["password"] = password

        response = self._make_request("POST", endpoint, data=data)
        return create_permission(response)


    def invite_to_item(
        self,
        drive_id: str,
        item_id: str,
        recipients: List[str],
        roles: List[str],
        send_invitation: bool = True,
        message: Optional[str] = None,
        require_sign_in: bool = True,
        expiration: Optional[str] = None,
        password: Optional[str] = None,
    ) -> List[Permission]:
        """
        Send sharing invitations to specific people for a drive item.

        Args:
            drive_id: The drive ID
            item_id: The item ID to share
            recipients: List of email addresses to invite
            roles: List of roles to grant - "read" or "write"
            send_invitation: Whether to send email notification (default: True)
            message: Optional message to include in the email
            require_sign_in: Whether recipients must sign in (default: True)
            expiration: Optional ISO 8601 datetime for permission expiration
            password: Optional password for the sharing link

        Returns:
            List of Permission models for each recipient

        Raises:
            ClientError: If invitation fails
        """
        endpoint = f"/drives/{drive_id}/items/{item_id}/invite"

        # Build recipients array
        recipient_objects = [{"email": email} for email in recipients]

        data: Dict[str, Any] = {
            "recipients": recipient_objects,
            "roles": roles,
            "sendInvitation": send_invitation,
            "requireSignIn": require_sign_in,
        }

        if message:
            data["message"] = message
        if expiration:
            data["expirationDateTime"] = expiration
        if password:
            data["password"] = password

        response = self._make_request("POST", endpoint, data=data)

        # Response is {"value": [Permission, ...]}
        permissions = response.get("value", [])
        return [create_permission(p) for p in permissions]

    def list_permissions(
        self,
        drive_id: str,
        item_id: str,
    ) -> List[Permission]:
        """
        List all permissions (sharing links and direct shares) on an item.

        Args:
            drive_id: The drive ID
            item_id: The item ID

        Returns:
            List of Permission models

        Raises:
            ClientError: If request fails
        """
        endpoint = f"/drives/{drive_id}/items/{item_id}/permissions"
        response = self._make_request("GET", endpoint)
        permissions = response.get("value", [])
        return [create_permission(p) for p in permissions]

    def get_permission(
        self,
        drive_id: str,
        item_id: str,
        permission_id: str,
    ) -> Permission:
        """
        Get a specific permission by ID.

        Args:
            drive_id: The drive ID
            item_id: The item ID
            permission_id: The permission ID

        Returns:
            Permission model

        Raises:
            ClientError: If permission not found or request fails
        """
        endpoint = f"/drives/{drive_id}/items/{item_id}/permissions/{permission_id}"
        response = self._make_request("GET", endpoint)
        return create_permission(response)

    def update_permission(
        self,
        drive_id: str,
        item_id: str,
        permission_id: str,
        roles: Optional[List[str]] = None,
        expiration: Optional[str] = None,
    ) -> Permission:
        """
        Update a permission's roles or expiration.

        Args:
            drive_id: The drive ID
            item_id: The item ID
            permission_id: The permission ID to update
            roles: New roles - ["read"] or ["write"]
            expiration: New expiration datetime (ISO 8601) or None to remove

        Returns:
            Updated Permission model

        Raises:
            ClientError: If update fails
        """
        endpoint = f"/drives/{drive_id}/items/{item_id}/permissions/{permission_id}"

        data: Dict[str, Any] = {}
        if roles is not None:
            data["roles"] = roles
        if expiration is not None:
            data["expirationDateTime"] = expiration

        response = self._make_request("PATCH", endpoint, data=data)
        return create_permission(response)

    def delete_permission(
        self,
        drive_id: str,
        item_id: str,
        permission_id: str,
    ) -> None:
        """
        Delete a permission (sharing link or direct share).

        Args:
            drive_id: The drive ID
            item_id: The item ID
            permission_id: The permission ID to delete

        Raises:
            ClientError: If deletion fails
        """
        endpoint = f"/drives/{drive_id}/items/{item_id}/permissions/{permission_id}"
        self._make_request("DELETE", endpoint)


# Module-level client instance - singleton pattern
_client: Optional[OneDriveClient] = None


def get_client() -> OneDriveClient:
    """Get or create the global OneDrive client instance."""
    global _client
    if _client is None:
        _client = OneDriveClient()
    return _client
