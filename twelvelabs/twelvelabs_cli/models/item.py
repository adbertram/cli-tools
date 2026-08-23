"""TwelveLabs models for CLI.

Defines Pydantic models for TwelveLabs API entities:
- Index: Video index container
- Video: Video within an index
- Task: Video upload/indexing task
- GenerateResponse: Text generation response
"""
from enum import Enum
from typing import List, Optional
from datetime import datetime

from pydantic import Field

from .base import CLIModel


# ==================== Enums ====================


class IndexStatus(str, Enum):
    """Status values for indexes."""
    ACTIVE = "active"
    CREATING = "creating"
    INDEXING = "indexing"
    DELETING = "deleting"


class TaskStatus(str, Enum):
    """Status values for indexing tasks."""
    PENDING = "pending"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"
    VALIDATING = "validating"


class VideoStatus(str, Enum):
    """Status values for videos."""
    READY = "ready"
    INDEXING = "indexing"
    PENDING = "pending"
    FAILED = "failed"


# ==================== Index Models ====================


class Index(CLIModel):
    """TwelveLabs Index model - container for videos.

    An index is a container that holds videos and enables
    searching and generating text from those videos.
    """
    # Read-only: server-assigned
    id: str = Field(frozen=True, alias="_id")

    # Required fields
    index_name: str

    # Optional fields
    engines: List[dict] = []
    video_count: int = 0
    total_duration: float = 0.0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class IndexDetail(Index):
    """Detailed index model with additional fields."""
    pass


class IndexCreate(CLIModel):
    """Model for creating a new index."""
    index_name: str
    engines: List[dict] = Field(default_factory=lambda: [
        {"engine_name": "pegasus1.5", "engine_options": ["visual", "audio"]}
    ])


# ==================== Video Models ====================


class Video(CLIModel):
    """TwelveLabs Video model - video within an index."""
    # Read-only: server-assigned
    id: str = Field(frozen=True, alias="_id")

    # Required fields
    index_id: str

    # Optional fields
    metadata: Optional[dict] = None
    hls: Optional[dict] = None
    source: Optional[dict] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @property
    def filename(self) -> Optional[str]:
        """Extract filename from metadata or source."""
        if self.metadata and "filename" in self.metadata:
            return self.metadata["filename"]
        if self.source and "name" in self.source:
            return self.source["name"]
        return None


class VideoDetail(Video):
    """Detailed video model with additional fields."""
    duration: Optional[float] = None


# ==================== Task Models ====================


class Task(CLIModel):
    """TwelveLabs Task model - video upload/indexing task."""
    # Read-only: server-assigned
    id: str = Field(frozen=True, alias="_id")

    # Required fields
    index_id: str
    status: TaskStatus = TaskStatus.PENDING

    # Optional fields
    video_id: Optional[str] = None
    estimated_time: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    # Metadata from upload
    metadata: Optional[dict] = None
    hls: Optional[dict] = None


# ==================== Generate Models ====================


class GenerateResponse(CLIModel):
    """Response from text generation."""
    id: Optional[str] = None
    data: Optional[str] = None  # The generated text


# ==================== Factory Functions ====================


def create_index(data: dict) -> Index:
    """Create an Index model from API response data."""
    return Index(**data)


def create_index_detail(data: dict) -> IndexDetail:
    """Create an IndexDetail model from API response data."""
    return IndexDetail(**data)


def create_video(data: dict) -> Video:
    """Create a Video model from API response data."""
    return Video(**data)


def create_video_detail(data: dict) -> VideoDetail:
    """Create a VideoDetail model from API response data."""
    return VideoDetail(**data)


def create_task(data: dict) -> Task:
    """Create a Task model from API response data."""
    return Task(**data)


def create_generate_response(data: dict) -> GenerateResponse:
    """Create a GenerateResponse model from API response data."""
    return GenerateResponse(**data)
