"""OneDrive models for Microsoft Graph API responses.

Models based on Microsoft Graph API DriveItem resource:
https://learn.microsoft.com/en-us/graph/api/resources/driveitem

Model Design:
- Required fields have no default value
- Optional fields use Optional[Type] = None
- Read-only fields use Field(frozen=True)
- Factory functions handle API response mapping
"""
from enum import Enum
from typing import Dict, List, Optional, Any
from datetime import datetime

from pydantic import Field

from .base import CLIModel


# ==================== Enums ====================


class DriveType(str, Enum):
    """OneDrive drive types."""
    PERSONAL = "personal"
    BUSINESS = "business"
    DOCUMENT_LIBRARY = "documentLibrary"


class ItemType(str, Enum):
    """DriveItem types - file or folder."""
    FILE = "file"
    FOLDER = "folder"


# ==================== Drive Models ====================


class DriveQuota(CLIModel):
    """Drive storage quota information."""
    deleted: Optional[int] = None
    remaining: Optional[int] = None
    state: Optional[str] = None
    total: Optional[int] = None
    used: Optional[int] = None


class DriveOwner(CLIModel):
    """Drive owner identity."""
    display_name: Optional[str] = Field(default=None, alias="displayName")
    email: Optional[str] = None
    id: Optional[str] = None


class Drive(CLIModel):
    """OneDrive drive resource.

    Represents a OneDrive or SharePoint document library.
    https://learn.microsoft.com/en-us/graph/api/resources/drive
    """
    # Read-only identity
    id: str = Field(frozen=True)

    # Drive properties
    name: str
    drive_type: Optional[str] = Field(default=None, alias="driveType")
    description: Optional[str] = None

    # Quota info (optional)
    quota: Optional[DriveQuota] = None

    # Owner info (optional)
    owner: Optional[Dict[str, Any]] = None

    # Web URL
    web_url: Optional[str] = Field(default=None, alias="webUrl")

    # Timestamps
    created_date_time: Optional[str] = Field(default=None, alias="createdDateTime", frozen=True)
    last_modified_date_time: Optional[str] = Field(default=None, alias="lastModifiedDateTime", frozen=True)


# ==================== DriveItem Models ====================


class FileInfo(CLIModel):
    """File-specific properties."""
    mime_type: Optional[str] = Field(default=None, alias="mimeType")
    hashes: Optional[Dict[str, str]] = None


class FolderInfo(CLIModel):
    """Folder-specific properties."""
    child_count: Optional[int] = Field(default=None, alias="childCount")


class ParentReference(CLIModel):
    """Reference to parent folder."""
    drive_id: Optional[str] = Field(default=None, alias="driveId")
    drive_type: Optional[str] = Field(default=None, alias="driveType")
    id: Optional[str] = None
    name: Optional[str] = None
    path: Optional[str] = None


class DriveItem(CLIModel):
    """OneDrive item resource (file or folder).

    Represents a file or folder in OneDrive.
    https://learn.microsoft.com/en-us/graph/api/resources/driveitem
    """
    # Read-only identity
    id: str = Field(frozen=True)

    # Item properties
    name: str

    # Size in bytes
    size: Optional[int] = None

    # Parent reference
    parent_reference: Optional[ParentReference] = Field(default=None, alias="parentReference")

    # Type indicators (mutually exclusive)
    file: Optional[FileInfo] = None
    folder: Optional[FolderInfo] = None

    # Web URL for browser access
    web_url: Optional[str] = Field(default=None, alias="webUrl")

    # Download URL (only for files, may be None)
    download_url: Optional[str] = Field(default=None, alias="@microsoft.graph.downloadUrl")

    # Timestamps
    created_date_time: Optional[str] = Field(default=None, alias="createdDateTime", frozen=True)
    last_modified_date_time: Optional[str] = Field(default=None, alias="lastModifiedDateTime", frozen=True)

    # Identity of creator/modifier (optional)
    created_by: Optional[Dict[str, Any]] = Field(default=None, alias="createdBy", frozen=True)
    last_modified_by: Optional[Dict[str, Any]] = Field(default=None, alias="lastModifiedBy", frozen=True)

    # E-tag for optimistic concurrency
    e_tag: Optional[str] = Field(default=None, alias="eTag")
    c_tag: Optional[str] = Field(default=None, alias="cTag")

    @property
    def is_folder(self) -> bool:
        """Check if this item is a folder."""
        return self.folder is not None

    @property
    def is_file(self) -> bool:
        """Check if this item is a file."""
        return self.file is not None

    @property
    def item_type(self) -> str:
        """Get the item type as a string."""
        return "folder" if self.is_folder else "file"


class DriveItemDetail(DriveItem):
    """Detailed DriveItem with additional metadata.

    Extended model for single-item GET responses.
    """
    # Additional metadata
    description: Optional[str] = None

    # Sharing info (if shared)
    shared: Optional[Dict[str, Any]] = None

    # Permissions
    permissions: Optional[List[Dict[str, Any]]] = None

    # Thumbnails
    thumbnails: Optional[List[Dict[str, Any]]] = None


class UploadSession(CLIModel):
    """Upload session for resumable uploads.

    https://learn.microsoft.com/en-us/graph/api/driveitem-createuploadsession
    """
    upload_url: str = Field(alias="uploadUrl")
    expiration_date_time: Optional[str] = Field(default=None, alias="expirationDateTime")
    next_expected_ranges: Optional[List[str]] = Field(default=None, alias="nextExpectedRanges")


# ==================== Sharing Models ====================


class SharingLinkInfo(CLIModel):
    """Sharing link details within a Permission.

    https://learn.microsoft.com/en-us/graph/api/resources/sharinglink
    """
    type: Optional[str] = None  # view, edit, embed
    scope: Optional[str] = None  # anonymous, organization, users
    web_url: Optional[str] = Field(default=None, alias="webUrl")
    prevents_download: Optional[bool] = Field(default=None, alias="preventsDownload")


class Permission(CLIModel):
    """Permission resource representing sharing permissions.

    Returned by createLink API.
    https://learn.microsoft.com/en-us/graph/api/resources/permission
    """
    id: str = Field(frozen=True)

    # Sharing link info (present for link-based permissions)
    link: Optional[SharingLinkInfo] = None

    # Roles granted by this permission
    roles: Optional[List[str]] = None

    # Share ID for accessing via /shares endpoint
    share_id: Optional[str] = Field(default=None, alias="shareId")

    # Expiration datetime
    expiration_date_time: Optional[str] = Field(default=None, alias="expirationDateTime")

    # Whether permission has password
    has_password: Optional[bool] = Field(default=None, alias="hasPassword")

    # Granted to identity
    granted_to: Optional[Dict[str, Any]] = Field(default=None, alias="grantedTo")
    granted_to_identities: Optional[List[Dict[str, Any]]] = Field(default=None, alias="grantedToIdentities")


# ==================== Factory Functions ====================


def create_drive(data: dict) -> Drive:
    """Create a Drive model from API response.

    Args:
        data: Raw dict from Microsoft Graph API

    Returns:
        Drive model instance
    """
    return Drive(**data)


def create_drive_item(data: dict) -> DriveItem:
    """Create a DriveItem model from API response.

    Args:
        data: Raw dict from Microsoft Graph API

    Returns:
        DriveItem model instance
    """
    return DriveItem(**data)


def create_drive_item_detail(data: dict) -> DriveItemDetail:
    """Create a DriveItemDetail model from API response.

    Args:
        data: Raw dict from Microsoft Graph API

    Returns:
        DriveItemDetail model instance
    """
    return DriveItemDetail(**data)


def create_upload_session(data: dict) -> UploadSession:
    """Create an UploadSession model from API response.

    Args:
        data: Raw dict from Microsoft Graph API

    Returns:
        UploadSession model instance
    """
    return UploadSession(**data)


def create_permission(data: dict) -> Permission:
    """Create a Permission model from API response.

    Args:
        data: Raw dict from Microsoft Graph API

    Returns:
        Permission model instance
    """
    return Permission(**data)


# Legacy compatibility - keep Item/ItemDetail exports for base template
Item = DriveItem
ItemDetail = DriveItemDetail


def create_item(data: dict) -> DriveItem:
    """Legacy factory for compatibility."""
    return create_drive_item(data)


def create_item_detail(data: dict) -> DriveItemDetail:
    """Legacy factory for compatibility."""
    return create_drive_item_detail(data)
