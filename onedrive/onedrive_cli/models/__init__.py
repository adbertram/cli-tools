"""OneDrive CLI models.

Models for Microsoft Graph API OneDrive resources including drives and drive items.

Model Architecture:
- CLIModel: Base class with CLI-friendly configuration
- Drive: OneDrive drive resource
- DriveItem: File or folder in OneDrive
- DriveItemDetail: Extended item model with additional metadata
- UploadSession: Resumable upload session

Usage:
    from .models import Drive, DriveItem, create_drive, create_drive_item

    # Create from API response
    drive = create_drive(api_response)
    item = create_drive_item(item_response)

    # Access typed fields
    print(drive.name)
    print(item.size)
"""
from .base import CLIModel
from .item import (
    # Drive models
    Drive,
    DriveQuota,
    DriveOwner,
    # DriveItem models
    DriveItem,
    DriveItemDetail,
    FileInfo,
    FolderInfo,
    ParentReference,
    UploadSession,
    # Sharing models
    SharingLinkInfo,
    Permission,
    # Enums
    DriveType,
    ItemType,
    # Factory functions
    create_drive,
    create_drive_item,
    create_drive_item_detail,
    create_upload_session,
    create_permission,
    # Legacy compatibility
    Item,
    ItemDetail,
    create_item,
    create_item_detail,
)

__all__ = [
    # Base
    "CLIModel",
    # Drive models
    "Drive",
    "DriveQuota",
    "DriveOwner",
    # DriveItem models
    "DriveItem",
    "DriveItemDetail",
    "FileInfo",
    "FolderInfo",
    "ParentReference",
    "UploadSession",
    # Sharing models
    "SharingLinkInfo",
    "Permission",
    # Enums
    "DriveType",
    "ItemType",
    # Factory functions
    "create_drive",
    "create_drive_item",
    "create_drive_item_detail",
    "create_upload_session",
    "create_permission",
    # Legacy compatibility
    "Item",
    "ItemDetail",
    "create_item",
    "create_item_detail",
]
