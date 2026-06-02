"""Image caching and downloading for Facebook Marketplace listings."""
from pathlib import Path
from typing import List, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from .config import get_config


def _item_dir(item_id: str) -> Path:
    return get_config().cache_dir / item_id


def get_cached_image_paths(item_id: str) -> List[str]:
    """Return sorted list of cached image paths for an item."""
    d = _item_dir(item_id)
    if not d.is_dir():
        return []
    return sorted(str(f) for f in d.iterdir() if f.is_file())


def _get_extension(url: str, content_type: Optional[str] = None) -> str:
    """Determine file extension from URL or content type."""
    url_path = url.split("?")[0]
    ext = Path(url_path).suffix.lower()
    if ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
        return ext
    if content_type:
        ct = content_type.lower()
        if "jpeg" in ct or "jpg" in ct:
            return ".jpg"
        if "png" in ct:
            return ".png"
        if "gif" in ct:
            return ".gif"
        if "webp" in ct:
            return ".webp"
    return ".jpg"


def download_images(item_id: str, image_urls: List[str]) -> List[str]:
    """Download images to cache/{item_id}/ and return local paths.

    Skips URLs that fail to download.
    """
    d = _item_dir(item_id)
    d.mkdir(parents=True, exist_ok=True)

    paths: List[str] = []
    for idx, url in enumerate(image_urls, 1):
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(request, timeout=15) as response:
                content_type = response.headers.get("Content-Type", "")
                ext = _get_extension(url, content_type)
                file_path = d / f"{idx}{ext}"
                file_path.write_bytes(response.read())
                paths.append(str(file_path))
        except (URLError, HTTPError, OSError):
            continue

    return paths
