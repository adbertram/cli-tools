"""Dropbox API client using official SDK with automatic token management."""
from datetime import datetime
from typing import Optional, List, Dict, Any, BinaryIO
import dropbox
from dropbox import Dropbox, DropboxOAuth2FlowNoRedirect
from dropbox.files import (
    FileMetadata,
    FolderMetadata,
    DeletedMetadata,
    WriteMode,
    SearchMatchType,
)
from dropbox.exceptions import ApiError, AuthError

from .config import get_config


class ClientError(Exception):
    """Custom exception for Dropbox client errors."""
    pass


class DropboxClient:
    """Client for interacting with Dropbox API using official SDK."""

    def __init__(self, require_auth: bool = True):
        """Initialize Dropbox client from configuration.

        Args:
            require_auth: If True, raises error if not authenticated.
                         If False, allows initialization without auth for login flow.
        """
        self.config = get_config()
        self._dbx: Optional[Dropbox] = None

        if require_auth:
            if not self.config.has_credentials():
                missing = self.config.get_missing_credentials()
                raise ClientError(
                    f"Missing credentials: {', '.join(missing)}. "
                    "Run 'dropbox auth login' to authenticate."
                )
            self._init_client()

    def _init_client(self, timeout: int = 100):
        """Initialize the Dropbox client with current credentials.

        Args:
            timeout: Request timeout in seconds (default: 100)
        """
        if self.config.refresh_token and self.config.app_key:
            # Use refresh token for automatic token refresh
            self._dbx = Dropbox(
                oauth2_access_token=self.config.access_token,
                oauth2_refresh_token=self.config.refresh_token,
                app_key=self.config.app_key,
                app_secret=self.config.app_secret,
                timeout=timeout,
            )
        elif self.config.access_token:
            # Use access token directly (may expire)
            self._dbx = Dropbox(oauth2_access_token=self.config.access_token, timeout=timeout)
        else:
            raise ClientError("No valid authentication method available.")

    def set_timeout(self, timeout: int):
        """Reinitialize client with a different timeout."""
        self._init_client(timeout=timeout)

    @property
    def dbx(self) -> Dropbox:
        """Get the Dropbox client instance."""
        if self._dbx is None:
            raise ClientError("Client not initialized. Call _init_client() first.")
        return self._dbx

    def _handle_api_error(self, e: ApiError) -> None:
        """Convert Dropbox API error to ClientError."""
        error_msg = str(e.error) if hasattr(e, 'error') else str(e)
        raise ClientError(f"Dropbox API error: {error_msg}")

    def _handle_auth_error(self, e: AuthError) -> None:
        """Handle authentication errors."""
        raise ClientError(
            "Authentication failed. Please run 'dropbox auth login' to re-authenticate."
        )

    # ==================== OAuth Methods ====================

    def start_oauth_flow(self) -> tuple[DropboxOAuth2FlowNoRedirect, str]:
        """Start OAuth2 flow for CLI authentication.

        Returns:
            Tuple of (auth_flow, authorize_url)
        """
        if not self.config.app_key:
            raise ClientError(
                "DROPBOX_APP_KEY not configured. "
                "Create an app at https://www.dropbox.com/developers/apps "
                "and add your app key to .env"
            )

        auth_flow = DropboxOAuth2FlowNoRedirect(
            consumer_key=self.config.app_key,
            consumer_secret=self.config.app_secret,
            token_access_type='offline',  # Get refresh token
            use_pkce=True,  # Use PKCE for security
        )

        authorize_url = auth_flow.start()
        return auth_flow, authorize_url

    def finish_oauth_flow(self, auth_flow: DropboxOAuth2FlowNoRedirect, auth_code: str) -> dict:
        """Complete OAuth2 flow with authorization code.

        Args:
            auth_flow: The OAuth flow instance from start_oauth_flow()
            auth_code: The authorization code from user

        Returns:
            Dict with token information
        """
        try:
            result = auth_flow.finish(auth_code.strip())
        except Exception as e:
            raise ClientError(f"Failed to complete authorization: {e}")

        # Calculate expiration timestamp
        expires_at = None
        if result.expires_at:
            if isinstance(result.expires_at, datetime):
                expires_at = str(int(result.expires_at.timestamp()))
            else:
                expires_at = str(int(datetime.now().timestamp() + result.expires_at))

        # Save tokens
        self.config.save_tokens(
            access_token=result.access_token,
            refresh_token=result.refresh_token,
            expires_at=expires_at,
            account_id=result.account_id,
        )

        return {
            "access_token": result.access_token[:20] + "...",
            "refresh_token": result.refresh_token[:20] + "..." if result.refresh_token else None,
            "account_id": result.account_id,
            "expires_at": expires_at,
        }

    # ==================== Account Methods ====================

    def get_account(self) -> Dict[str, Any]:
        """Get current account information."""
        try:
            account = self.dbx.users_get_current_account()
            return {
                "account_id": account.account_id,
                "name": account.name.display_name,
                "email": account.email,
                "email_verified": account.email_verified,
                "country": account.country,
                "locale": account.locale,
                "account_type": account.account_type._tag,
                "profile_photo_url": account.profile_photo_url,
            }
        except AuthError as e:
            self._handle_auth_error(e)
        except ApiError as e:
            self._handle_api_error(e)

    def get_space_usage(self) -> Dict[str, Any]:
        """Get space usage information."""
        try:
            usage = self.dbx.users_get_space_usage()
            allocation = usage.allocation

            result = {
                "used": usage.used,
            }

            if allocation.is_individual():
                result["allocated"] = allocation.get_individual().allocated
            elif allocation.is_team():
                team = allocation.get_team()
                result["allocated"] = team.allocated
                result["team_used"] = team.used

            return result
        except AuthError as e:
            self._handle_auth_error(e)
        except ApiError as e:
            self._handle_api_error(e)

    # ==================== File Operations ====================

    def list_folder(
        self,
        path: str = "",
        recursive: bool = False,
        include_deleted: bool = False,
    ) -> List[Dict[str, Any]]:
        """List files and folders in a path.

        Args:
            path: Dropbox path (empty string for root)
            recursive: List recursively
            include_deleted: Include deleted files

        Returns:
            List of file/folder metadata dicts
        """
        # Normalize path - empty string for root, otherwise ensure leading slash
        if path and not path.startswith("/"):
            path = "/" + path
        if path == "/":
            path = ""

        try:
            result = self.dbx.files_list_folder(
                path,
                recursive=recursive,
                include_deleted=include_deleted,
            )

            entries = []
            while True:
                for entry in result.entries:
                    entries.append(self._metadata_to_dict(entry))

                if not result.has_more:
                    break
                result = self.dbx.files_list_folder_continue(result.cursor)

            return entries
        except AuthError as e:
            self._handle_auth_error(e)
        except ApiError as e:
            self._handle_api_error(e)

    def get_metadata(self, path: str) -> Dict[str, Any]:
        """Get metadata for a file or folder.

        Args:
            path: Dropbox path or id: reference

        Returns:
            File/folder metadata dict
        """
        if not path.startswith("/") and not path.startswith("id:"):
            path = "/" + path

        try:
            metadata = self.dbx.files_get_metadata(path)
            return self._metadata_to_dict(metadata)
        except AuthError as e:
            self._handle_auth_error(e)
        except ApiError as e:
            self._handle_api_error(e)

    def download_file(self, path: str, local_path: str) -> Dict[str, Any]:
        """Download a file from Dropbox.

        Args:
            path: Dropbox path
            local_path: Local file path to save to

        Returns:
            File metadata dict
        """
        if not path.startswith("/"):
            path = "/" + path

        try:
            metadata, response = self.dbx.files_download(path)
            with open(local_path, "wb") as f:
                f.write(response.content)
            return self._metadata_to_dict(metadata)
        except AuthError as e:
            self._handle_auth_error(e)
        except ApiError as e:
            self._handle_api_error(e)

    def upload_file(
        self,
        local_path: str,
        dropbox_path: str,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """Upload a file to Dropbox.

        Args:
            local_path: Local file path
            dropbox_path: Destination Dropbox path
            overwrite: If True, overwrite existing file

        Returns:
            File metadata dict
        """
        if not dropbox_path.startswith("/"):
            dropbox_path = "/" + dropbox_path

        mode = WriteMode.overwrite if overwrite else WriteMode.add

        try:
            with open(local_path, "rb") as f:
                metadata = self.dbx.files_upload(
                    f.read(),
                    dropbox_path,
                    mode=mode,
                )
            return self._metadata_to_dict(metadata)
        except AuthError as e:
            self._handle_auth_error(e)
        except ApiError as e:
            self._handle_api_error(e)

    def delete(self, path: str) -> Dict[str, Any]:
        """Delete a file or folder.

        Args:
            path: Dropbox path

        Returns:
            Deleted item metadata dict
        """
        if not path.startswith("/"):
            path = "/" + path

        try:
            metadata = self.dbx.files_delete_v2(path)
            return self._metadata_to_dict(metadata.metadata)
        except AuthError as e:
            self._handle_auth_error(e)
        except ApiError as e:
            self._handle_api_error(e)

    def create_folder(self, path: str) -> Dict[str, Any]:
        """Create a folder.

        Args:
            path: Dropbox path for new folder

        Returns:
            Folder metadata dict
        """
        if not path.startswith("/"):
            path = "/" + path

        try:
            result = self.dbx.files_create_folder_v2(path)
            return self._metadata_to_dict(result.metadata)
        except AuthError as e:
            self._handle_auth_error(e)
        except ApiError as e:
            self._handle_api_error(e)

    def move(self, from_path: str, to_path: str) -> Dict[str, Any]:
        """Move a file or folder.

        Args:
            from_path: Source Dropbox path
            to_path: Destination Dropbox path

        Returns:
            Moved item metadata dict
        """
        if not from_path.startswith("/"):
            from_path = "/" + from_path
        if not to_path.startswith("/"):
            to_path = "/" + to_path

        try:
            result = self.dbx.files_move_v2(from_path, to_path)
            return self._metadata_to_dict(result.metadata)
        except AuthError as e:
            self._handle_auth_error(e)
        except ApiError as e:
            self._handle_api_error(e)

    def copy(self, from_path: str, to_path: str) -> Dict[str, Any]:
        """Copy a file or folder.

        Args:
            from_path: Source Dropbox path
            to_path: Destination Dropbox path

        Returns:
            Copied item metadata dict
        """
        if not from_path.startswith("/"):
            from_path = "/" + from_path
        if not to_path.startswith("/"):
            to_path = "/" + to_path

        try:
            result = self.dbx.files_copy_v2(from_path, to_path)
            return self._metadata_to_dict(result.metadata)
        except AuthError as e:
            self._handle_auth_error(e)
        except ApiError as e:
            self._handle_api_error(e)

    def search(
        self,
        query: str,
        path: str = "",
        max_results: int = 100,
    ) -> List[Dict[str, Any]]:
        """Search for files and folders.

        Args:
            query: Search query
            path: Path to search within (empty for all)
            max_results: Maximum number of results

        Returns:
            List of matching file/folder metadata dicts
        """
        if path and not path.startswith("/"):
            path = "/" + path

        try:
            result = self.dbx.files_search_v2(query, options=dropbox.files.SearchOptions(
                path=path if path else None,
                max_results=max_results,
            ))

            entries = []
            for match in result.matches:
                if hasattr(match, 'metadata') and hasattr(match.metadata, 'get_metadata'):
                    entries.append(self._metadata_to_dict(match.metadata.get_metadata()))

            return entries
        except AuthError as e:
            self._handle_auth_error(e)
        except ApiError as e:
            self._handle_api_error(e)

    # ==================== Sharing Methods ====================

    def get_shared_link_metadata(self, url: str, path: Optional[str] = None) -> Dict[str, Any]:
        """Get metadata for a shared link.

        Args:
            url: Shared link URL
            path: Optional path within the shared folder

        Returns:
            Metadata dict for the shared link target
        """
        try:
            from dropbox.files import SharedLink
            shared_link = SharedLink(url=url)
            metadata = self.dbx.sharing_get_shared_link_metadata(url=url, path=path)
            return self._shared_metadata_to_dict(metadata)
        except AuthError as e:
            self._handle_auth_error(e)
        except ApiError as e:
            self._handle_api_error(e)

    def list_shared_folder_contents(self, url: str, path: str = "") -> List[Dict[str, Any]]:
        """List contents of a shared folder.

        Args:
            url: Shared folder link URL
            path: Path within the shared folder

        Returns:
            List of file/folder metadata dicts
        """
        try:
            from dropbox.files import SharedLink
            shared_link = SharedLink(url=url)

            # Get folder contents using the shared link
            result = self.dbx.files_list_folder(
                path=path,
                shared_link=shared_link,
            )

            entries = []
            while True:
                for entry in result.entries:
                    entries.append(self._metadata_to_dict(entry))

                if not result.has_more:
                    break
                result = self.dbx.files_list_folder_continue(result.cursor)

            return entries
        except AuthError as e:
            self._handle_auth_error(e)
        except ApiError as e:
            self._handle_api_error(e)

    def download_shared_folder(
        self,
        url: str,
        local_path: str,
        path: str = "",
        progress_callback: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """Download all contents of a shared folder.

        Args:
            url: Shared folder link URL
            local_path: Local directory to download to
            path: Path within the shared folder
            progress_callback: Optional callback(action, path) for progress updates

        Returns:
            Stats dict with files_downloaded, folders_created, total_bytes, errors
        """
        import os
        from dropbox.files import SharedLink

        stats = {
            "files_downloaded": 0,
            "folders_created": 0,
            "total_bytes": 0,
            "errors": [],
        }

        try:
            shared_link = SharedLink(url=url)

            # Create local directory
            os.makedirs(local_path, exist_ok=True)

            # Recursively download
            self._download_shared_folder_recursive(
                shared_link=shared_link,
                remote_path=path,
                local_path=local_path,
                stats=stats,
                progress_callback=progress_callback,
            )

            return stats
        except AuthError as e:
            self._handle_auth_error(e)
        except ApiError as e:
            self._handle_api_error(e)

    def _download_shared_folder_recursive(
        self,
        shared_link,
        remote_path: str,
        local_path: str,
        stats: Dict[str, Any],
        progress_callback: Optional[callable] = None,
    ):
        """Recursively download shared folder contents."""
        import os

        try:
            result = self.dbx.files_list_folder(
                path=remote_path,
                shared_link=shared_link,
            )

            while True:
                for entry in result.entries:
                    entry_name = entry.name
                    local_entry_path = os.path.join(local_path, entry_name)

                    if isinstance(entry, FolderMetadata):
                        # Create folder and recurse
                        os.makedirs(local_entry_path, exist_ok=True)
                        stats["folders_created"] += 1
                        if progress_callback:
                            progress_callback("folder", local_entry_path)

                        # Build remote path for subfolder
                        if remote_path:
                            sub_remote_path = f"{remote_path}/{entry_name}"
                        else:
                            sub_remote_path = f"/{entry_name}"

                        self._download_shared_folder_recursive(
                            shared_link=shared_link,
                            remote_path=sub_remote_path,
                            local_path=local_entry_path,
                            stats=stats,
                            progress_callback=progress_callback,
                        )
                    elif isinstance(entry, FileMetadata):
                        # Download file
                        try:
                            if progress_callback:
                                progress_callback("file", local_entry_path)

                            # Build remote path for file
                            if remote_path:
                                file_remote_path = f"{remote_path}/{entry_name}"
                            else:
                                file_remote_path = f"/{entry_name}"

                            try:
                                metadata, response = self.dbx.sharing_get_shared_link_file(
                                    url=shared_link.url,
                                    path=file_remote_path,
                                )
                                content = response.content
                            except Exception as e:
                                if "missing '.tag' key" not in str(e):
                                    raise
                                content = self._download_shared_link_file_content_raw(
                                    url=shared_link.url,
                                    path=file_remote_path,
                                )

                            with open(local_entry_path, "wb") as f:
                                f.write(content)

                            stats["files_downloaded"] += 1
                            stats["total_bytes"] += entry.size
                        except Exception as e:
                            stats["errors"].append({
                                "path": local_entry_path,
                                "error": str(e),
                            })

                if not result.has_more:
                    break
                result = self.dbx.files_list_folder_continue(result.cursor)

        except ApiError as e:
            stats["errors"].append({
                "path": remote_path,
                "error": str(e),
            })

    def _download_shared_link_file_content_raw(self, url: str, path: str) -> bytes:
        """Download shared-link file content without SDK metadata deserialization.

        Dropbox SDK 12.0.2 can fail to deserialize the download metadata header
        when Dropbox omits ``link_permissions.resolved_visibility['.tag']``.
        The content response is still valid, so this fallback calls the same
        content-download route and returns only the response body.
        """
        import json
        from dropbox import sharing
        from dropbox.dropbox_client import RouteErrorResult
        from dropbox.exceptions import ApiError
        from stone.backends.python_rsrc import stone_serializers

        route = sharing.get_shared_link_file
        arg = sharing.GetSharedLinkMetadataArg(url, path, None)
        serialized_arg = stone_serializers.json_encode(route.arg_type, arg)

        self.dbx.check_and_refresh_access_token()
        route_name = f"sharing/{route.name}"
        if route.version > 1:
            route_name += f"_v{route.version}"

        res = self.dbx.request_json_string_with_retry(
            route.attrs["host"] or "api",
            route_name,
            route.attrs["style"] or "rpc",
            serialized_arg,
            route.attrs["auth"],
            None,
            timeout=None,
        )

        if isinstance(res, RouteErrorResult):
            decoded = json.loads(res.obj_result)
            deserialized_error = stone_serializers.json_compat_obj_decode(
                route.error_type,
                decoded["error"],
                strict=False,
            )
            user_message = decoded.get("user_message")
            user_message_text = user_message and user_message.get("text")
            user_message_locale = user_message and user_message.get("locale")
            raise ApiError(
                res.request_id,
                deserialized_error,
                user_message_text,
                user_message_locale,
            )

        return res.http_resp.content

    def _shared_metadata_to_dict(self, metadata) -> Dict[str, Any]:
        """Convert shared link metadata to dictionary."""
        result = {
            "name": metadata.name,
            "path_lower": getattr(metadata, 'path_lower', None),
        }

        if isinstance(metadata, FileMetadata):
            result["type"] = "file"
            result["id"] = metadata.id
            result["size"] = metadata.size
            result["server_modified"] = str(metadata.server_modified) if metadata.server_modified else None
        elif isinstance(metadata, FolderMetadata):
            result["type"] = "folder"
            result["id"] = metadata.id

        return result

    # ==================== Version History Methods ====================

    def list_revisions(
        self,
        path: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """List file revisions/versions.

        Args:
            path: Dropbox path to the file
            limit: Maximum number of revisions to return

        Returns:
            List of revision metadata dicts
        """
        if not path.startswith("/"):
            path = "/" + path

        try:
            result = self.dbx.files_list_revisions(path, limit=limit)

            revisions = []
            for entry in result.entries:
                revisions.append({
                    "rev": entry.rev,
                    "name": entry.name,
                    "path_display": entry.path_display,
                    "path_lower": entry.path_lower,
                    "size": entry.size,
                    "server_modified": str(entry.server_modified) if entry.server_modified else None,
                    "client_modified": str(entry.client_modified) if entry.client_modified else None,
                    "is_downloadable": entry.is_downloadable,
                })

            return revisions
        except AuthError as e:
            self._handle_auth_error(e)
        except ApiError as e:
            self._handle_api_error(e)

    def restore_file(self, path: str, rev: str) -> Dict[str, Any]:
        """Restore a file to a previous revision.

        Args:
            path: Dropbox path to restore
            rev: Revision ID to restore to

        Returns:
            Restored file metadata dict
        """
        if not path.startswith("/"):
            path = "/" + path

        try:
            metadata = self.dbx.files_restore(path, rev)
            return self._metadata_to_dict(metadata)
        except AuthError as e:
            self._handle_auth_error(e)
        except ApiError as e:
            self._handle_api_error(e)

    def restore_deleted_folder(self, path: str) -> Dict[str, Any]:
        """Restore a deleted folder by restoring all its deleted files.

        Args:
            path: Dropbox path to the deleted folder

        Returns:
            Dict with restored files count and any errors
        """
        if not path.startswith("/"):
            path = "/" + path

        restored = []
        errors = []

        try:
            # List all deleted items in the folder recursively
            deleted_files = self._list_deleted_files(path)

            for file_info in deleted_files:
                file_path = file_info["path_display"]
                try:
                    # Get the last revision before deletion
                    revisions = self.list_revisions(file_path, limit=1)
                    if revisions:
                        rev = revisions[0]["rev"]
                        result = self.restore_file(file_path, rev)
                        restored.append(result)
                    else:
                        errors.append({"path": file_path, "error": "No revisions found"})
                except ApiError as e:
                    # Skip folders - they don't have revisions and are created automatically
                    if e.error.is_path() and e.error.get_path().is_not_file():
                        continue
                    errors.append({"path": file_path, "error": str(e)})
                except Exception as e:
                    errors.append({"path": file_path, "error": str(e)})

            return {
                "restored_count": len(restored),
                "error_count": len(errors),
                "restored": restored,
                "errors": errors,
            }
        except AuthError as e:
            self._handle_auth_error(e)
        except ApiError as e:
            self._handle_api_error(e)

    def _list_deleted_files(self, path: str) -> List[Dict[str, Any]]:
        """List all deleted files under a path recursively.

        Args:
            path: Dropbox path to search

        Returns:
            List of deleted file metadata dicts
        """
        deleted_files = []

        try:
            # Use list_folder with include_deleted to find deleted items
            result = self.dbx.files_list_folder(
                path,
                recursive=True,
                include_deleted=True,
            )

            while True:
                for entry in result.entries:
                    if isinstance(entry, DeletedMetadata):
                        # Check if it's a file by trying to get revisions
                        deleted_files.append({
                            "name": entry.name,
                            "path_lower": entry.path_lower,
                            "path_display": entry.path_display,
                            "type": "deleted",
                        })

                if not result.has_more:
                    break
                result = self.dbx.files_list_folder_continue(result.cursor)

            return deleted_files
        except ApiError as e:
            # If folder doesn't exist, try parent and filter
            if e.error.is_path() and e.error.get_path().is_not_found():
                # Try listing from parent with the deleted folder
                parent = "/".join(path.rstrip("/").split("/")[:-1]) or "/"
                folder_name = path.rstrip("/").split("/")[-1].lower()

                result = self.dbx.files_list_folder(
                    parent,
                    recursive=True,
                    include_deleted=True,
                )

                while True:
                    for entry in result.entries:
                        if isinstance(entry, DeletedMetadata):
                            # Check if path starts with our target folder
                            if entry.path_lower.startswith(path.lower() + "/") or entry.path_lower == path.lower():
                                deleted_files.append({
                                    "name": entry.name,
                                    "path_lower": entry.path_lower,
                                    "path_display": entry.path_display,
                                    "type": "deleted",
                                })

                    if not result.has_more:
                        break
                    result = self.dbx.files_list_folder_continue(result.cursor)

                return deleted_files
            raise

    # ==================== Helper Methods ====================

    def _metadata_to_dict(self, metadata) -> Dict[str, Any]:
        """Convert Dropbox metadata object to dictionary."""
        result = {
            "name": metadata.name,
            "path_lower": metadata.path_lower,
            "path_display": metadata.path_display,
        }

        if isinstance(metadata, FileMetadata):
            result["type"] = "file"
            result["id"] = metadata.id
            result["size"] = metadata.size
            result["client_modified"] = str(metadata.client_modified) if metadata.client_modified else None
            result["server_modified"] = str(metadata.server_modified) if metadata.server_modified else None
            result["rev"] = metadata.rev
            result["content_hash"] = metadata.content_hash
        elif isinstance(metadata, FolderMetadata):
            result["type"] = "folder"
            result["id"] = metadata.id
        elif isinstance(metadata, DeletedMetadata):
            result["type"] = "deleted"

        return result


# Module-level client instance - singleton pattern
_client: Optional[DropboxClient] = None


def get_client(require_auth: bool = True) -> DropboxClient:
    """Get or create the global Dropbox client instance."""
    global _client
    if _client is None:
        _client = DropboxClient(require_auth=require_auth)
    return _client


def reset_client():
    """Reset the global client instance (useful after authentication)."""
    global _client
    _client = None
