"""Image processing utilities for Notion to WordPress publishing.

Downloads images from Notion CDN and uploads them to WordPress media library,
replacing Notion URLs with permanent WordPress URLs.
"""
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, List, Tuple
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError


# Notion CDN URL patterns
NOTION_URL_PATTERNS = [
    r"https://prod-files-secure\.s3\.us-west-2\.amazonaws\.com/",
    r"https://prod-files\.s3\.us-west-2\.amazonaws\.com/",
    r"https://www\.notion\.so/image/",
    r"https://s3\.us-west-2\.amazonaws\.com/secure\.notion-static\.com/",
]


def extract_image_urls(markdown: str) -> List[Tuple[str, str, str]]:
    """
    Extract image URLs from markdown content.

    Returns list of (full_match, alt_text, url) tuples.
    Handles both standard markdown and HTML img tags.
    """
    results = []

    # Match markdown image syntax: ![alt](url)
    md_pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
    for match in re.finditer(md_pattern, markdown):
        full_match = match.group(0)
        alt_text = match.group(1)
        url = match.group(2)
        results.append((full_match, alt_text, url))

    # Match HTML img tags: <img src="url" alt="alt"/>
    html_pattern = r'<img\s+[^>]*src=["\']([^"\']+)["\'][^>]*>'
    for match in re.finditer(html_pattern, markdown, re.IGNORECASE):
        full_match = match.group(0)
        url = match.group(1)
        # Try to extract alt from the tag
        alt_match = re.search(r'alt=["\']([^"\']*)["\']', full_match, re.IGNORECASE)
        alt_text = alt_match.group(1) if alt_match else ""
        results.append((full_match, alt_text, url))

    return results


def is_notion_url(url: str) -> bool:
    """Check if a URL is a Notion CDN URL that needs migration."""
    for pattern in NOTION_URL_PATTERNS:
        if re.match(pattern, url):
            return True
    return False


def get_image_extension(url: str, content_type: str = None) -> str:
    """
    Determine image file extension from URL or content type.

    Args:
        url: The image URL
        content_type: Optional MIME type from response headers

    Returns:
        File extension including dot (e.g., '.png', '.jpg')
    """
    # Try to get extension from URL path (before query params)
    url_path = url.split('?')[0]
    path_ext = Path(url_path).suffix.lower()
    if path_ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp']:
        return path_ext

    # Fall back to content type
    if content_type:
        content_type = content_type.lower()
        if 'png' in content_type:
            return '.png'
        if 'jpeg' in content_type or 'jpg' in content_type:
            return '.jpg'
        if 'gif' in content_type:
            return '.gif'
        if 'webp' in content_type:
            return '.webp'
        if 'svg' in content_type:
            return '.svg'

    # Default to png
    return '.png'


def download_image(url: str, temp_dir: Path, filename: str) -> Path:
    """
    Download an image from URL to temp directory.

    Args:
        url: The image URL
        temp_dir: Directory to save the image
        filename: Base filename (without extension)

    Returns:
        Path to downloaded file

    Raises:
        URLError, HTTPError on download failure
    """
    # Create request with user agent to avoid blocks
    request = Request(url, headers={'User-Agent': 'Mozilla/5.0 ATA-Blog-CLI/1.0'})

    with urlopen(request, timeout=30) as response:
        content_type = response.headers.get('Content-Type', '')
        ext = get_image_extension(url, content_type)

        file_path = temp_dir / f"{filename}{ext}"
        file_path.write_bytes(response.read())

        return file_path


def upload_to_wordpress(image_path: Path) -> dict:
    """
    Upload an image to WordPress media library.

    Args:
        image_path: Path to the local image file

    Returns:
        Dict with 'id' and 'source_url' from WordPress

    Raises:
        RuntimeError on upload failure
    """
    cmd = ["wordpress", "media", "upload", str(image_path)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if result.returncode != 0:
        raise RuntimeError(f"WordPress upload failed: {result.stderr.strip()}")

    # Parse the JSON output to get media info
    # The output includes info lines followed by multi-line JSON
    # Find the JSON block (starts with { and ends with })
    stdout = result.stdout.strip()
    json_start = stdout.find('{')
    json_end = stdout.rfind('}')

    if json_start != -1 and json_end != -1:
        json_str = stdout[json_start:json_end + 1]
        media = json.loads(json_str)
        return {
            'id': media.get('id'),
            'source_url': media.get('source_url')
        }

    raise RuntimeError(f"Could not parse WordPress upload response: {result.stdout}")


def is_remote_url(url: str) -> bool:
    """Return True if the URL is an absolute http/https URL."""
    return url.startswith("http://") or url.startswith("https://")


def find_local_image_refs(
    markdown: str,
    base_dir: Path,
) -> List[Tuple[str, str, Path]]:
    """
    Find image references whose paths resolve to existing local files.

    Resolves each non-remote path against base_dir. If the resolved file
    exists on disk, it is returned. Remote URLs (http/https) and missing
    paths are skipped.

    Args:
        markdown: Markdown content to scan
        base_dir: Directory to resolve relative paths against (typically the
            parent dir of the markdown file)

    Returns:
        List of (original_path_string, alt_text, resolved_absolute_path) tuples
        for each local image reference whose file exists on disk.
    """
    base_dir = Path(base_dir).resolve()
    results = []
    seen_paths = set()

    for _full_match, alt_text, url in extract_image_urls(markdown):
        if is_remote_url(url):
            continue

        # Resolve the path against the markdown file's directory.
        # Absolute filesystem paths resolve to themselves; relative paths
        # resolve against base_dir.
        candidate = Path(url)
        if not candidate.is_absolute():
            candidate = base_dir / candidate
        candidate = candidate.resolve()

        if not candidate.is_file():
            continue

        if url in seen_paths:
            continue
        seen_paths.add(url)

        results.append((url, alt_text, candidate))

    return results


def process_local_images_for_wordpress(
    markdown_content: str,
    base_dir: Path,
    verbose: bool = True,
) -> Tuple[str, int]:
    """
    Upload local images referenced by markdown to WordPress media and
    rewrite the markdown to point at the returned WordPress URLs.

    Local image refs are markdown `![alt](path)` or HTML `<img src="path">`
    whose path is NOT an http/https URL and which resolves to an existing
    file under base_dir. Remote URLs are left untouched.

    Args:
        markdown_content: The markdown content to transform
        base_dir: Directory to resolve relative paths against
        verbose: Whether to print progress messages

    Returns:
        Tuple of (rewritten_markdown, number_of_uploads).
    """
    refs = find_local_image_refs(markdown_content, base_dir)
    if not refs:
        return markdown_content, 0

    if verbose:
        print(f"Found {len(refs)} local image(s) to upload to WordPress")

    rewritten = markdown_content
    uploaded = 0
    for idx, (original_path, _alt_text, resolved_path) in enumerate(refs, 1):
        if verbose:
            print(f"  [{idx}/{len(refs)}] Uploading {resolved_path.name}...")

        media = upload_to_wordpress(resolved_path)
        wp_url = media.get("source_url")
        if not wp_url:
            raise RuntimeError(
                f"WordPress upload for {resolved_path} returned no source_url"
            )

        if verbose:
            print(f"  [{idx}/{len(refs)}] Uploaded: {wp_url}")

        # Replace the original path string (as it appears in the markdown)
        # with the returned WordPress URL. The original path is unique
        # within seen_paths, so a plain str.replace is safe.
        rewritten = rewritten.replace(original_path, wp_url)
        uploaded += 1

    return rewritten, uploaded


def process_images_for_wordpress(
    markdown_content: str,
    article_slug: str,
    verbose: bool = True
) -> str:
    """
    Process all Notion images in markdown and upload to WordPress.

    Extracts Notion CDN URLs from markdown, downloads each image,
    uploads to WordPress, and replaces URLs in content.

    Args:
        markdown_content: The markdown content with image references
        article_slug: Article slug for naming images (e.g., 'azure-functions-guide')
        verbose: Whether to print progress messages

    Returns:
        Updated markdown content with WordPress URLs
    """
    # Extract all images
    images = extract_image_urls(markdown_content)
    if not images:
        return markdown_content

    # Filter to Notion URLs only
    notion_images = [(full, alt, url) for full, alt, url in images if is_notion_url(url)]
    if not notion_images:
        return markdown_content

    if verbose:
        print(f"Found {len(notion_images)} Notion image(s) to migrate")

    # Create temp directory for downloads
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        url_mapping = {}  # old_url -> new_url

        for idx, (full_match, alt_text, url) in enumerate(notion_images, 1):
            filename = f"{article_slug}-{idx}"

            try:
                if verbose:
                    print(f"  [{idx}/{len(notion_images)}] Downloading: {filename}...")

                # Download image
                local_path = download_image(url, temp_path, filename)

                if verbose:
                    print(f"  [{idx}/{len(notion_images)}] Uploading to WordPress...")

                # Upload to WordPress
                media = upload_to_wordpress(local_path)
                wp_url = media['source_url']

                if verbose:
                    print(f"  [{idx}/{len(notion_images)}] Uploaded: {wp_url}")

                url_mapping[url] = wp_url

            except (URLError, HTTPError) as e:
                if verbose:
                    print(f"  [{idx}/{len(notion_images)}] Download failed: {e}")
                # Keep original URL on failure (graceful degradation)
                continue
            except RuntimeError as e:
                if verbose:
                    print(f"  [{idx}/{len(notion_images)}] Upload failed: {e}")
                # Keep original URL on failure
                continue

    # Replace URLs in content
    result = markdown_content
    for old_url, new_url in url_mapping.items():
        result = result.replace(old_url, new_url)

    if verbose and url_mapping:
        print(f"Migrated {len(url_mapping)} image(s) to WordPress")

    return result
