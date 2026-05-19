"""TwelveLabs CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Model Architecture:
- CLIModel: Base class with CLI-friendly configuration
- Index: Video index container
- Video: Video within an index
- Task: Upload/indexing task
- GenerateResponse: Text generation response

Usage:
    from .models import Index, Video, Task, create_index

    # Create from API response
    index = create_index(api_response)

    # Access typed fields
    print(index.index_name)
    print(index.video_count)

    # Serialize to JSON
    print_json(index)
"""
from .base import CLIModel
from .item import (
    # Index models
    Index,
    IndexDetail,
    IndexCreate,
    IndexStatus,
    # Video models
    Video,
    VideoDetail,
    VideoStatus,
    # Task models
    Task,
    TaskStatus,
    # Generate models
    GenerateResponse,
    # Factory functions
    create_index,
    create_index_detail,
    create_video,
    create_video_detail,
    create_task,
    create_generate_response,
)

__all__ = [
    # Base
    "CLIModel",
    # Index models
    "Index",
    "IndexDetail",
    "IndexCreate",
    "IndexStatus",
    # Video models
    "Video",
    "VideoDetail",
    "VideoStatus",
    # Task models
    "Task",
    "TaskStatus",
    # Generate models
    "GenerateResponse",
    # Factory functions
    "create_index",
    "create_index_detail",
    "create_video",
    "create_video_detail",
    "create_task",
    "create_generate_response",
]
