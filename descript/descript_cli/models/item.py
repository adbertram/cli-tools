"""Project and Composition models for Descript CLI.

Represents Descript video projects and their compositions.
"""
from typing import List, Optional

from pydantic import Field

from .base import CLIModel


# ==================== Models ====================


class Owner(CLIModel):
    """Project owner information."""

    id: str = Field(frozen=True)
    email: str
    first_name: str
    last_name: str


class VideoAsset(CLIModel):
    """A video asset (raw recording) within a Descript project."""

    id: str = Field(frozen=True)
    name: str
    created_at: str = Field(frozen=True)
    source: str = ""


class ExportPlaylist(CLIModel):
    """Export playlist response from the MTS video_playlist endpoint."""

    url: str
    params: str
    end: int  # total duration in microseconds
    expiry: int
    fragment_starts: List[int] = []


class Composition(CLIModel):
    """A composition (timeline/sequence) within a Descript project."""

    id: str = Field(frozen=True)
    name: str
    duration: float
    media_type: str


class Project(CLIModel):
    """Descript project returned by list commands."""

    id: str = Field(frozen=True)
    name: str
    drive_id: str = Field(frozen=True)
    created_at: str = Field(frozen=True)
    last_viewed_at: Optional[str] = Field(default=None, frozen=True)
    last_updated_at: Optional[str] = Field(default=None, frozen=True)
    composition_count: int = 0
    owner: Optional[Owner] = None


class ProjectDetail(CLIModel):
    """Detailed project model with compositions."""

    id: str = Field(frozen=True)
    name: str
    drive_id: str = Field(frozen=True)
    created_at: str = Field(frozen=True)
    last_viewed_at: Optional[str] = Field(default=None, frozen=True)
    last_updated_at: Optional[str] = Field(default=None, frozen=True)
    composition_count: int = 0
    compositions: List[Composition] = []
    owner: Optional[Owner] = None
    permissions: Optional[dict] = None
    in_recordings_folder: Optional[bool] = None
    is_live_collab_enabled: Optional[bool] = None
    has_thumbnail: Optional[bool] = None
    requester_user_ownership_role: Optional[str] = None
    total_project_size_bytes: Optional[int] = None
    thumbnail_url: Optional[str] = None


# ==================== Factory Functions ====================


def create_project(data: dict) -> Project:
    """Create a Project model from API response data."""
    meta = data.get("recent_metadata", {})
    if "composition_count" in meta:
        data["composition_count"] = meta["composition_count"]

    return Project(**data)


def create_video_asset(data: dict) -> VideoAsset:
    """Create a VideoAsset model from API media_assets response data."""
    meta = data.get("metadata", {})
    return VideoAsset(
        id=data["id"],
        name=meta.get("default_display_name", "Unknown"),
        created_at=data.get("created_at", ""),
        source=meta.get("source", ""),
    )


def create_export_playlist(data: dict) -> ExportPlaylist:
    """Create an ExportPlaylist model from video_playlist response."""
    return ExportPlaylist(**data)


def create_project_detail(data: dict) -> ProjectDetail:
    """Create a ProjectDetail model from API response data."""
    meta = data.get("recent_metadata", {})
    if "composition_count" in meta:
        data["composition_count"] = meta["composition_count"]
    if "composition_summaries" in meta:
        data["compositions"] = [Composition(**c) for c in meta["composition_summaries"]]
    if "total_project_size_bytes" in meta:
        data["total_project_size_bytes"] = meta["total_project_size_bytes"]

    return ProjectDetail(**data)
