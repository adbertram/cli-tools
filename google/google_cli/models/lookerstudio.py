"""Looker Studio models."""
from enum import Enum
from typing import Optional, Union

from pydantic import Field

from .base import CLIModel


class LookerStudioAssetType(str, Enum):
    """Looker Studio asset type."""

    REPORT = "REPORT"
    DATA_SOURCE = "DATA_SOURCE"


class LookerStudioRole(str, Enum):
    """Looker Studio asset permission role."""

    VIEWER = "VIEWER"
    EDITOR = "EDITOR"
    OWNER = "OWNER"
    LINK_VIEWER = "LINK_VIEWER"
    LINK_EDITOR = "LINK_EDITOR"


class LookerStudioAsset(CLIModel):
    """Looker Studio asset."""

    asset_type: LookerStudioAssetType = Field(alias="assetType")
    name: str
    title: str
    trashed: Optional[bool] = None
    update_time: Optional[str] = Field(default=None, alias="updateTime")
    update_by_me_time: Optional[str] = Field(default=None, alias="updateByMeTime")
    owner: Optional[str] = None
    create_time: Optional[str] = Field(default=None, alias="createTime")
    last_view_by_me_time: Optional[str] = Field(default=None, alias="lastViewByMeTime")
    description: Optional[str] = None
    creator: Optional[str] = None


class LookerStudioPermissionMembers(CLIModel):
    """Members assigned to a Looker Studio permission role."""

    members: list[str]


class LookerStudioPermissions(CLIModel):
    """Looker Studio asset permissions."""

    permissions: dict[str, LookerStudioPermissionMembers]
    etag: Optional[str] = None


class LookerStudioDataSourceParameter(CLIModel):
    """Linking API data source parameter."""

    alias: str
    key: str
    value: Union[str, bool]


class LookerStudioReportLink(CLIModel):
    """Generated Looker Studio Linking API report URL."""

    report_id: str
    url: str
    embed: bool
    parameters: dict[str, str]
