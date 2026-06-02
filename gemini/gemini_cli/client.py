"""Gemini API client using Google's official SDK."""
import os
import sys
import time
from typing import Optional, List, Dict, Any, TypeVar, Callable
from pathlib import Path
from google import genai
from google.genai import types
from google.genai import errors as genai_errors

from .config import get_config
from .usage import record_usage

_RATE_LIMIT_DELAYS = [30, 60, 120, 240]
_FILES_LIST_TIMEOUT_MS = 25_000
_MODELS_LIST_TIMEOUT_MS = 25_000
T = TypeVar("T")


def _retry_on_rate_limit(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Call fn with retry on HTTP 429 rate limit errors.

    Retries with exponential backoff delays of 30s, 60s, 120s, 240s.
    Only retries on 429 status codes; all other errors propagate immediately.

    Args:
        fn: Callable to invoke
        *args, **kwargs: Passed through to fn

    Returns:
        Return value of fn

    Raises:
        Original exception after retries are exhausted, or immediately for non-429 errors
    """
    for attempt, delay in enumerate(_RATE_LIMIT_DELAYS):
        try:
            return fn(*args, **kwargs)
        except genai_errors.APIError as e:
            if e.code != 429:
                raise
            print(
                f"Rate limit hit, retrying in {delay}s... (attempt {attempt + 1}/{len(_RATE_LIMIT_DELAYS)})",
                file=sys.stderr,
            )
            time.sleep(delay)

    # Final attempt after all retries - let any exception propagate
    return fn(*args, **kwargs)


def _record_response_usage(
    response,
    model: str,
    operation: str = "generate",
    config=None,
) -> None:
    """Record usage from a response's usage_metadata."""
    if response.usage_metadata:
        meta = response.usage_metadata
        record_usage(
            model=model,
            prompt_tokens=meta.prompt_token_count or 0,
            completion_tokens=meta.candidates_token_count or 0,
            total_tokens=meta.total_token_count or 0,
            cached_tokens=meta.cached_content_token_count or 0,
            operation=operation,
            config=config,
        )


class ClientError(Exception):
    """Custom exception for Gemini API errors."""
    pass


class GeminiClient:
    """Client for interacting with Google Gemini API."""

    def __init__(self, config=None):
        """Initialize Gemini client from configuration."""
        self.config = config or get_config()

        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Set GEMINI_API_KEY environment variable or add it to .env file."
            )

        # Initialize the Google Gemini client
        self.client = genai.Client(api_key=self.config.api_key)

    # ==================== File Operations ====================

    def upload_file(self, file_path: str) -> types.File:
        """
        Upload a file to Gemini Files API.

        Args:
            file_path: Path to the file to upload

        Returns:
            File object with metadata

        Raises:
            ClientError: If upload fails
        """
        try:
            file_path_obj = Path(file_path)
            if not file_path_obj.exists():
                raise ClientError(f"File not found: {file_path}")

            uploaded_file = _retry_on_rate_limit(self.client.files.upload, file=file_path)
            return uploaded_file
        except Exception as e:
            raise ClientError(f"Failed to upload file: {e}")

    def wait_for_file_processing(self, file_name: str, timeout: int = 300) -> types.File:
        """
        Wait for uploaded file to be processed.

        Args:
            file_name: Name of the uploaded file
            timeout: Maximum seconds to wait (default: 300)

        Returns:
            Processed File object

        Raises:
            ClientError: If processing fails or times out
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            file_obj = _retry_on_rate_limit(self.client.files.get, name=file_name)
            if file_obj.state and file_obj.state.name == "ACTIVE":
                return file_obj
            if file_obj.state and file_obj.state.name == "FAILED":
                raise ClientError(f"File processing failed: {file_obj.state}")
            time.sleep(5)
        raise ClientError(f"File processing timed out after {timeout} seconds")

    def list_files(self, limit: int = 100) -> List[types.File]:
        """
        List uploaded files up to the requested limit.

        Returns:
            List of File objects
        """
        try:
            page_size = min(limit, 100)
            pager = self.client.files.list(
                config={
                    "page_size": page_size,
                    "http_options": {"timeout": _FILES_LIST_TIMEOUT_MS},
                }
            )
            files = list(pager.page)

            while len(files) < limit:
                try:
                    next_page = pager.next_page()
                except IndexError:
                    break
                files.extend(next_page[: limit - len(files)])

            return files
        except Exception as e:
            raise ClientError(f"Failed to list files: {e}")

    def get_file(self, file_name: str) -> types.File:
        """
        Get file metadata by name.

        Args:
            file_name: Name of the file

        Returns:
            File object

        Raises:
            ClientError: If file not found
        """
        try:
            return _retry_on_rate_limit(self.client.files.get, name=file_name)
        except Exception as e:
            raise ClientError(f"Failed to get file: {e}")

    def delete_file(self, file_name: str):
        """
        Delete an uploaded file.

        Args:
            file_name: Name of the file to delete

        Raises:
            ClientError: If deletion fails
        """
        try:
            _retry_on_rate_limit(self.client.files.delete, name=file_name)
        except Exception as e:
            raise ClientError(f"Failed to delete file: {e}")

    # ==================== Content Generation ====================

    def generate_content(
        self,
        prompt: str,
        model: str = "gemini-3.1-pro-preview",
        file_refs: Optional[List[types.File]] = None,
        operation: str = "generate",
        response_schema: Optional[Dict[str, Any]] = None,
        video_fps: Optional[float] = None
    ) -> str:
        """
        Generate content using Gemini API.

        Args:
            prompt: Text prompt for generation
            model: Model to use (default: gemini-3.1-pro-preview)
            file_refs: Optional list of File objects to include
            operation: Operation type for usage tracking
            response_schema: Optional JSON schema for structured output
            video_fps: Optional FPS for video files (applied to first video file)

        Returns:
            Generated text response

        Raises:
            ClientError: If generation fails
        """
        try:
            contents = []
            if file_refs:
                for file_ref in file_refs:
                    # Check if this is a video file and we have FPS setting
                    is_video = file_ref.mime_type and file_ref.mime_type.startswith('video/')
                    if is_video and video_fps is not None:
                        # Create a Part with video_metadata for FPS
                        part = types.Part(
                            file_data=types.FileData(
                                file_uri=file_ref.uri,
                                mime_type=file_ref.mime_type
                            ),
                            video_metadata=types.VideoMetadata(fps=video_fps)
                        )
                        contents.append(part)
                    else:
                        contents.append(file_ref)
            contents.append(prompt)

            # Build config for structured output if schema provided
            config = None
            if response_schema:
                config = types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=response_schema
                )

            response = _retry_on_rate_limit(
                self.client.models.generate_content,
                model=model,
                contents=contents,
                config=config,
            )

            # Record usage
            _record_response_usage(response, model, operation, self.config)

            # Extract text parts directly to avoid warning about non-text parts (e.g., thought_signature)
            text_parts = [
                part.text for part in response.candidates[0].content.parts
                if hasattr(part, 'text') and part.text
            ]
            return ''.join(text_parts)
        except Exception as e:
            raise ClientError(f"Failed to generate content: {e}")

    def analyze_video(
        self,
        video_path: str,
        prompt: str,
        model: str = "gemini-3.1-pro-preview",
        auto_wait: bool = True,
        additional_files: Optional[List[str]] = None,
        response_schema: Optional[Dict[str, Any]] = None,
        fps: Optional[float] = None
    ) -> str:
        """
        Upload and analyze a video file.

        Args:
            video_path: Path to video file
            prompt: Analysis prompt
            model: Model to use (default: gemini-3.1-pro-preview)
            auto_wait: Wait for file processing before analysis (default: True)
            additional_files: Optional list of additional file paths to include
            response_schema: Optional JSON schema for structured output
            fps: Frames per second for video sampling (default: 1 FPS by Gemini).
                 Use higher values (2-5) for fast-action or sync detection.
                 Use lower values (<1) for long static videos.

        Returns:
            Analysis response text

        Raises:
            ClientError: If analysis fails
        """
        # Check file size
        file_size = os.path.getsize(video_path)
        file_size_mb = file_size / (1024 * 1024)

        # Upload additional files first if provided
        uploaded_additional = []
        if additional_files:
            for file_path in additional_files:
                path_obj = Path(file_path)
                if not path_obj.exists():
                    raise ClientError(f"Additional file not found: {file_path}")
                uploaded = self.upload_file(file_path)
                if auto_wait:
                    uploaded = self.wait_for_file_processing(uploaded.name)
                uploaded_additional.append(uploaded)

        # For files < 20MB and no additional files, use inline upload
        if file_size_mb < 20 and not additional_files:
            try:
                with open(video_path, 'rb') as f:
                    video_bytes = f.read()

                # Build config for structured output if schema provided
                config = None
                if response_schema:
                    config = types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=response_schema
                    )

                # Build video part with optional FPS metadata
                video_part = types.Part(
                    inline_data=types.Blob(
                        data=video_bytes,
                        mime_type='video/mp4'
                    )
                )
                if fps is not None:
                    video_part.video_metadata = types.VideoMetadata(fps=fps)

                response = _retry_on_rate_limit(
                    self.client.models.generate_content,
                    model=model,
                    contents=[
                        video_part,
                        types.Part(text=prompt)
                    ],
                    config=config,
                )

                # Record usage
                _record_response_usage(response, model, "video_analyze", self.config)

                # Extract text parts directly to avoid warning about non-text parts (e.g., thought_signature)
                text_parts = [
                    part.text for part in response.candidates[0].content.parts
                    if hasattr(part, 'text') and part.text
                ]
                return ''.join(text_parts)
            except Exception as e:
                raise ClientError(f"Failed to analyze video inline: {e}")

        # For larger files or when additional files present, use Files API
        uploaded_file = self.upload_file(video_path)

        if auto_wait:
            uploaded_file = self.wait_for_file_processing(uploaded_file.name)

        # Combine video + additional files
        all_files = [uploaded_file] + uploaded_additional
        return self.generate_content(
            prompt, model, all_files,
            operation="video_analyze",
            response_schema=response_schema,
            video_fps=fps
        )

    # ==================== Image Generation ====================

    def generate_image(
        self,
        prompt: str,
        model: str = "gemini-3-pro-image-preview",
        aspect_ratio: str = "16:9",
        image_size: str = "2K",
        use_search: bool = False,
        input_images: Optional[List[Path]] = None,
    ) -> Dict[str, Any]:
        """
        Generate an image using Gemini image generation models.

        Args:
            prompt: Text prompt describing the image to generate
            model: Model to use (default: gemini-3-pro-image-preview aka Nano Banana Pro)
            aspect_ratio: Aspect ratio (1:1, 16:9, 9:16, 4:3, 3:4)
            image_size: Output size (1K, 2K, 4K)
            use_search: Enable Google Search grounding for real-time data
            input_images: Optional list of reference image paths for image editing /
                multi-image composition. Only supported by Nano Banana models
                (gemini-3-pro-image-preview, gemini-2.5-flash-image).

        Returns:
            Dict with 'image_data' (base64), 'mime_type', and 'text' (if any)

        Raises:
            ClientError: If generation fails
        """
        try:
            # Build configuration
            tools = []
            if use_search:
                tools.append({"google_search": {}})

            config = types.GenerateContentConfig(
                image_config=types.ImageConfig(
                    aspect_ratio=aspect_ratio,
                    image_size=image_size
                )
            )
            if tools:
                config.tools = tools

            # Build contents list. For image-editing / reference-image flows,
            # reference images are passed as inline_data Parts alongside the prompt.
            contents: List[Any] = []
            if input_images:
                import mimetypes
                for img_path in input_images:
                    if not img_path.exists():
                        raise ClientError(f"Input image not found: {img_path}")
                    mime, _ = mimetypes.guess_type(str(img_path))
                    if not mime or not mime.startswith("image/"):
                        # Default to png if unknown; Gemini requires an image mime.
                        mime = "image/png"
                    contents.append(
                        types.Part(
                            inline_data=types.Blob(
                                mime_type=mime,
                                data=img_path.read_bytes(),
                            )
                        )
                    )
            contents.append(prompt)

            response = _retry_on_rate_limit(
                self.client.models.generate_content,
                model=model,
                contents=contents,
                config=config,
            )

            # Record usage
            _record_response_usage(response, model, "image_generate", self.config)

            # Extract results
            result = {
                "text": None,
                "images": []
            }

            for part in response.candidates[0].content.parts:
                if hasattr(part, 'text') and part.text:
                    result["text"] = part.text
                elif hasattr(part, 'inline_data') and part.inline_data:
                    result["images"].append({
                        "data": part.inline_data.data,
                        "mime_type": part.inline_data.mime_type
                    })

            if not result["images"]:
                raise ClientError("No image was generated in the response")

            return result
        except Exception as e:
            raise ClientError(f"Failed to generate image: {e}")

    # ==================== Model Operations ====================

    def list_models(self, limit: int = 100) -> List[Any]:
        """
        List available Gemini models up to the requested limit.

        Returns:
            List of available models
        """
        try:
            page_size = min(limit, 100)
            pager = _retry_on_rate_limit(
                self.client.models.list,
                config={
                    "page_size": page_size,
                    "http_options": {"timeout": _MODELS_LIST_TIMEOUT_MS},
                },
            )
            models = list(pager.page)

            while len(models) < limit:
                try:
                    next_page = pager.next_page()
                except IndexError:
                    break
                models.extend(next_page[: limit - len(models)])

            return models
        except Exception as e:
            raise ClientError(f"Failed to list models: {e}")


# Module-level client instance - singleton pattern
_client: Optional[GeminiClient] = None


def get_client() -> GeminiClient:
    """Get or create the global Gemini client instance."""
    global _client
    if _client is None:
        _client = GeminiClient()
    return _client
