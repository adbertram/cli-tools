"""Supported file types for Gemini API."""
from pathlib import Path
from typing import Optional

# Supported MIME types by category
# Source: https://firebase.google.com/docs/ai-logic/input-file-requirements

SUPPORTED_IMAGE_TYPES = {
    "image/png": [".png"],
    "image/jpeg": [".jpg", ".jpeg"],
    "image/webp": [".webp"],
}

SUPPORTED_VIDEO_TYPES = {
    "video/x-flv": [".flv"],
    "video/quicktime": [".mov"],
    "video/mpeg": [".mpeg"],
    "video/mpegps": [".mpegps"],
    "video/mpg": [".mpg"],
    "video/mp4": [".mp4"],
    "video/webm": [".webm"],
    "video/wmv": [".wmv"],
    "video/3gpp": [".3gp", ".3gpp"],
}

SUPPORTED_AUDIO_TYPES = {
    "audio/aac": [".aac"],
    "audio/flac": [".flac"],
    "audio/mp3": [".mp3"],
    "audio/m4a": [".m4a"],
    "audio/mpeg": [".mpeg", ".mpga"],
    "audio/mpga": [".mpga"],
    "audio/mp4": [".mp4", ".m4a"],
    "audio/opus": [".opus"],
    "audio/pcm": [".pcm"],
    "audio/wav": [".wav"],
    "audio/webm": [".webm"],
}

SUPPORTED_DOCUMENT_TYPES = {
    "application/pdf": [".pdf"],
    "text/plain": [".txt", ".text", ".md", ".csv", ".json", ".xml", ".html", ".css", ".js", ".py"],
}

# Combine all supported types
ALL_SUPPORTED_TYPES = {
    **SUPPORTED_IMAGE_TYPES,
    **SUPPORTED_VIDEO_TYPES,
    **SUPPORTED_AUDIO_TYPES,
    **SUPPORTED_DOCUMENT_TYPES,
}

# Build extension to MIME type mapping
EXTENSION_TO_MIME: dict[str, str] = {}
for mime_type, extensions in ALL_SUPPORTED_TYPES.items():
    for ext in extensions:
        # Only set if not already set (prefer more specific mappings)
        if ext not in EXTENSION_TO_MIME:
            EXTENSION_TO_MIME[ext] = mime_type


def get_mime_type(file_path: Path) -> Optional[str]:
    """Get MIME type for a file based on extension."""
    ext = file_path.suffix.lower()
    return EXTENSION_TO_MIME.get(ext)


def is_supported_file(file_path: Path) -> bool:
    """Check if file type is supported by Gemini API."""
    return get_mime_type(file_path) is not None


def get_supported_extensions() -> list[str]:
    """Get list of all supported file extensions."""
    return sorted(set(EXTENSION_TO_MIME.keys()))


def get_file_category(file_path: Path) -> Optional[str]:
    """Get the category of a file (image, video, audio, document)."""
    mime_type = get_mime_type(file_path)
    if not mime_type:
        return None

    if mime_type in SUPPORTED_IMAGE_TYPES:
        return "image"
    elif mime_type in SUPPORTED_VIDEO_TYPES:
        return "video"
    elif mime_type in SUPPORTED_AUDIO_TYPES:
        return "audio"
    elif mime_type in SUPPORTED_DOCUMENT_TYPES:
        return "document"
    return None


class UnsupportedFileTypeError(Exception):
    """Raised when a file type is not supported."""

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.extension = file_path.suffix.lower()
        supported = ", ".join(get_supported_extensions())
        super().__init__(
            f"Unsupported file type '{self.extension}' for file: {file_path.name}\n"
            f"Supported extensions: {supported}"
        )
