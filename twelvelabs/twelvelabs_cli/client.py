"""TwelveLabs API client using the official Python SDK."""
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

from .config import get_config
from .models import (
    Index, IndexDetail, Video, VideoDetail, Task, GenerateResponse,
    create_index, create_video, create_task, TaskStatus
)


# Default wait configuration
DEFAULT_POLL_INTERVAL = 5  # seconds
DEFAULT_TIMEOUT = 600  # 10 minutes
SUPPORTED_PEGASUS_ENGINES = ("pegasus1.2", "pegasus1.5")


class ClientError(Exception):
    """Custom exception for TwelveLabs API errors."""
    pass


class TwelveLabsClient:
    """Client for interacting with TwelveLabs API via official SDK."""

    def __init__(self):
        """Initialize TwelveLabs client from configuration."""
        self.config = get_config()

        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'twelvelabs auth login' to authenticate."
            )

        # Import the SDK only when API commands need it; auth status uses direct HTTP.
        from twelvelabs import TwelveLabs

        self.client = TwelveLabs(api_key=self.config.api_key)

    # ==================== Index Methods ====================

    def list_indexes(self, limit: int = 100) -> List[Index]:
        """List all indexes.

        Args:
            limit: Maximum number of indexes to return

        Returns:
            List of Index models
        """
        try:
            indexes = []
            # SyncPager is an iterator - we can iterate directly
            pager = self.client.indexes.list(page_limit=min(limit, 50))  # API max is 50 per page
            for idx in pager:
                indexes.append(create_index({
                    "_id": idx.id,
                    "index_name": idx.index_name,
                    "engines": [{"engine_name": m.model_name, "engine_options": m.model_options} for m in (idx.models or [])],
                    "video_count": getattr(idx, 'video_count', 0) or 0,
                    "total_duration": getattr(idx, 'total_duration', 0.0) or 0.0,
                    "created_at": str(idx.created_at) if idx.created_at else None,
                    "updated_at": str(idx.updated_at) if idx.updated_at else None,
                }))
                if len(indexes) >= limit:
                    break
            return indexes[:limit]
        except Exception as e:
            raise ClientError(f"Failed to list indexes: {e}")

    def get_index(self, index_id: str) -> IndexDetail:
        """Get index details by ID.

        Args:
            index_id: The index ID

        Returns:
            IndexDetail model
        """
        try:
            idx = self.client.indexes.retrieve(index_id)
            return IndexDetail(
                id=idx.id,
                index_name=idx.index_name,
                engines=[{"engine_name": m.model_name, "engine_options": m.model_options} for m in (idx.models or [])],
                video_count=getattr(idx, 'video_count', 0) or 0,
                total_duration=getattr(idx, 'total_duration', 0.0) or 0.0,
                created_at=str(idx.created_at) if idx.created_at else None,
                updated_at=str(idx.updated_at) if idx.updated_at else None,
            )
        except Exception as e:
            raise ClientError(f"Failed to get index {index_id}: {e}")

    def create_index(
        self,
        name: str,
        engines: Optional[List[dict]] = None
    ) -> Index:
        """Create a new index.

        Args:
            name: Name for the index
            engines: List of engine configurations (default: pegasus1.5)

        Returns:
            Created Index model
        """
        if engines is None:
            engines = [{"engine_name": "pegasus1.5", "engine_options": ["visual", "audio"]}]

        try:
            # SDK expects 'models' parameter with IndexesCreateRequestModelsItem objects
            from twelvelabs.indexes.types.indexes_create_request_models_item import IndexesCreateRequestModelsItem
            models = [
                IndexesCreateRequestModelsItem(
                    model_name=e.get("engine_name", "pegasus1.5"),
                    model_options=e.get("engine_options", ["visual", "audio"])
                )
                for e in engines
            ]
            idx = self.client.indexes.create(
                index_name=name,
                models=models,
            )
            return Index(
                id=idx.id,
                index_name=name,
                engines=engines,
                video_count=0,
                total_duration=0.0,
            )
        except Exception as e:
            raise ClientError(f"Failed to create index '{name}': {e}")

    def delete_index(self, index_id: str) -> bool:
        """Delete an index.

        Args:
            index_id: The index ID to delete

        Returns:
            True if deleted successfully
        """
        try:
            self.client.indexes.delete(index_id)
            return True
        except Exception as e:
            raise ClientError(f"Failed to delete index {index_id}: {e}")

    # ==================== Video Methods ====================

    def list_videos(self, index_id: str, limit: int = 100) -> List[Video]:
        """List videos in an index.

        Args:
            index_id: The index ID
            limit: Maximum number of videos to return

        Returns:
            List of Video models
        """
        try:
            videos = []
            # SyncPager is an iterator - we can iterate directly
            pager = self.client.indexes.videos.list(index_id=index_id, page_limit=min(limit, 50))  # API max is 50 per page
            for vid in pager:
                # SDK now uses system_metadata instead of metadata
                # Handle both Pydantic model and dict for system_metadata and hls
                if hasattr(vid, 'system_metadata') and vid.system_metadata:
                    sys_meta = vid.system_metadata.model_dump() if hasattr(vid.system_metadata, 'model_dump') else vid.system_metadata
                else:
                    sys_meta = {}
                if hasattr(vid, 'hls') and vid.hls:
                    hls_data = vid.hls.model_dump() if hasattr(vid.hls, 'model_dump') else vid.hls
                else:
                    hls_data = None
                videos.append(create_video({
                    "_id": vid.id,
                    "index_id": index_id,
                    "metadata": sys_meta,  # Use system_metadata as metadata
                    "hls": hls_data,
                    "source": None,  # source no longer returned in list
                    "created_at": str(vid.created_at) if vid.created_at else None,
                    "updated_at": str(vid.updated_at) if hasattr(vid, 'updated_at') and vid.updated_at else None,
                }))
                if len(videos) >= limit:
                    break
            return videos[:limit]
        except Exception as e:
            raise ClientError(f"Failed to list videos in index {index_id}: {e}")

    def get_video(self, index_id: str, video_id: str) -> VideoDetail:
        """Get video details.

        Args:
            index_id: The index ID
            video_id: The video ID

        Returns:
            VideoDetail model
        """
        try:
            vid = self.client.indexes.videos.retrieve(index_id=index_id, id=video_id)
            return VideoDetail(
                id=vid.id,
                index_id=index_id,
                metadata=vid.metadata.model_dump() if vid.metadata else None,
                hls=vid.hls.model_dump() if hasattr(vid, 'hls') and vid.hls else None,
                source=vid.source.model_dump() if hasattr(vid, 'source') and vid.source else None,
                duration=getattr(vid, 'duration', None),
                created_at=str(vid.created_at) if vid.created_at else None,
                updated_at=str(vid.updated_at) if hasattr(vid, 'updated_at') and vid.updated_at else None,
            )
        except Exception as e:
            raise ClientError(f"Failed to get video {video_id}: {e}")

    def delete_video(self, index_id: str, video_id: str) -> bool:
        """Delete a video from an index.

        Args:
            index_id: The index ID
            video_id: The video ID to delete

        Returns:
            True if deleted successfully
        """
        try:
            self.client.indexes.videos.delete(index_id=index_id, id=video_id)
            return True
        except Exception as e:
            raise ClientError(f"Failed to delete video {video_id}: {e}")

    def find_video_by_filename(self, index_id: str, filename: str) -> Optional[Video]:
        """Find a video in an index by filename.

        Args:
            index_id: The index ID
            filename: The filename to search for

        Returns:
            Video model if found, None otherwise
        """
        videos = self.list_videos(index_id)
        for video in videos:
            if video.filename == filename:
                return video
        return None

    # ==================== Upload Methods ====================

    def upload_video(
        self,
        index_id: str,
        video_path: str,
        wait: bool = True,
        timeout: int = DEFAULT_TIMEOUT,
        check_duplicate: bool = True,
    ) -> Task:
        """Upload a video to an index.

        Args:
            index_id: The index ID to upload to
            video_path: Path to the video file
            wait: Whether to wait for indexing to complete
            timeout: Timeout in seconds for waiting
            check_duplicate: Whether to check for existing video with same filename

        Returns:
            Task model with upload status
        """
        video_path = Path(video_path)
        if not video_path.exists():
            raise ClientError(f"Video file not found: {video_path}")

        filename = video_path.name

        # Check for duplicate if requested
        if check_duplicate:
            existing = self.find_video_by_filename(index_id, filename)
            if existing:
                return Task(
                    id="existing",
                    index_id=index_id,
                    status=TaskStatus.READY,
                    video_id=existing.id,
                )

        try:
            # Create the upload task - open file and pass as file object
            with open(video_path, 'rb') as video_file:
                task = self.client.tasks.create(
                    index_id=index_id,
                    video_file=video_file,
                )

            task_model = Task(
                id=task.id,
                index_id=index_id,
                status=TaskStatus.PENDING,
                video_id=None,
            )

            if wait:
                return self.wait_for_task(task.id, timeout=timeout)

            return task_model

        except Exception as e:
            raise ClientError(f"Failed to upload video: {e}")

    def wait_for_task(
        self,
        task_id: str,
        timeout: int = DEFAULT_TIMEOUT,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
    ) -> Task:
        """Wait for a task to complete.

        Args:
            task_id: The task ID to wait for
            timeout: Maximum time to wait in seconds
            poll_interval: Time between status checks in seconds

        Returns:
            Task model with final status
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                task = self.client.tasks.retrieve(task_id)

                # Map SDK status to our enum
                status_map = {
                    "pending": TaskStatus.PENDING,
                    "indexing": TaskStatus.INDEXING,
                    "ready": TaskStatus.READY,
                    "failed": TaskStatus.FAILED,
                    "validating": TaskStatus.VALIDATING,
                }
                status = status_map.get(task.status, TaskStatus.PENDING)

                if status == TaskStatus.READY:
                    return Task(
                        id=task.id,
                        index_id=task.index_id,
                        status=status,
                        video_id=task.video_id,
                        estimated_time=getattr(task, 'estimated_time', None),
                        created_at=str(task.created_at) if task.created_at else None,
                    )

                if status == TaskStatus.FAILED:
                    raise ClientError(f"Task failed: {getattr(task, 'error', 'Unknown error')}")

                time.sleep(poll_interval)

            except ClientError:
                raise
            except Exception as e:
                raise ClientError(f"Failed to check task status: {e}")

        raise ClientError(f"Task timed out after {timeout} seconds")

    def get_task(self, task_id: str) -> Task:
        """Get task status.

        Args:
            task_id: The task ID

        Returns:
            Task model
        """
        try:
            task = self.client.tasks.retrieve(task_id)
            status_map = {
                "pending": TaskStatus.PENDING,
                "indexing": TaskStatus.INDEXING,
                "ready": TaskStatus.READY,
                "failed": TaskStatus.FAILED,
                "validating": TaskStatus.VALIDATING,
            }
            return Task(
                id=task.id,
                index_id=task.index_id,
                status=status_map.get(task.status, TaskStatus.PENDING),
                video_id=task.video_id,
                estimated_time=getattr(task, 'estimated_time', None),
                created_at=str(task.created_at) if task.created_at else None,
            )
        except Exception as e:
            raise ClientError(f"Failed to get task {task_id}: {e}")

    # ==================== Generate Methods ====================

    def _validate_pegasus_engine(self, engine: str) -> None:
        if engine not in SUPPORTED_PEGASUS_ENGINES:
            raise ClientError(
                f"Unsupported Pegasus engine '{engine}'. "
                f"Use one of: {', '.join(SUPPORTED_PEGASUS_ENGINES)}."
            )

    def get_video_asset_id(self, index_id: str, video_id: str) -> str:
        """Retrieve the source asset ID for an indexed video."""
        try:
            video = self.client.indexes.videos.retrieve(index_id=index_id, video_id=video_id)
            video_data = video.model_dump()
            if "asset_id" not in video_data:
                raise ClientError(
                    f"Indexed video {video_id} does not include asset_id. "
                    "Pegasus 1.5 analysis requires an asset_id from TwelveLabs."
                )
            asset_id = video_data["asset_id"]
            if not isinstance(asset_id, str) or asset_id.strip() == "":
                raise ClientError(
                    f"Indexed video {video_id} returned an invalid asset_id. "
                    "Pegasus 1.5 analysis requires a non-empty asset_id."
                )
            return asset_id
        except ClientError:
            raise
        except Exception as e:
            raise ClientError(f"Failed to retrieve asset ID for video {video_id}: {e}")

    def generate_text(
        self,
        video_id: str,
        prompt: str,
        temperature: Optional[float] = None,
        engine: str = "pegasus1.5",
        index_id: Optional[str] = None,
    ) -> str:
        """Generate text from an indexed video with a custom prompt.

        Args:
            video_id: The video ID to analyze
            prompt: The prompt for text generation
            temperature: Controls randomness (0.0=deterministic, 1.0=creative)
            engine: Pegasus engine to use for analysis
            index_id: Index ID required when engine is pegasus1.5

        Returns:
            Generated text string
        """
        try:
            self._validate_pegasus_engine(engine)

            # Build kwargs - only include temperature if specified
            kwargs = {
                "model_name": engine,
                "prompt": prompt,
            }
            if temperature is not None:
                kwargs["temperature"] = temperature

            if engine == "pegasus1.2":
                kwargs["video_id"] = video_id
            else:
                if index_id is None or index_id.strip() == "":
                    raise ClientError(
                        "Pegasus 1.5 requires index_id so the CLI can resolve "
                        "the indexed video's asset_id."
                    )
                from twelvelabs.types import VideoContext_AssetId

                kwargs["video"] = VideoContext_AssetId(
                    asset_id=self.get_video_asset_id(index_id=index_id, video_id=video_id)
                )

            # Use analyze method for custom prompts
            response = self.client.analyze(**kwargs)
            return response.data
        except ClientError:
            raise
        except Exception as e:
            raise ClientError(f"Failed to generate text: {e}")


# Module-level client instance - singleton pattern
_client: Optional[TwelveLabsClient] = None


def get_client() -> TwelveLabsClient:
    """Get or create the global TwelveLabs client instance."""
    global _client
    if _client is None:
        _client = TwelveLabsClient()
    return _client
