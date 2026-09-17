"""Image utilities for ATA Blog publishing.

``upload_to_static_media`` writes a local image straight into the static
site's Cloudflare R2 media bucket under a content-addressed
``wp-content/uploads/publisher/`` key. It is what every local image referenced
by post markdown goes through.
"""
import hashlib
import json
import mimetypes
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..client import STATIC_MEDIA_BUCKET, STATIC_SITE_ORIGIN

# Content-addressed media the publisher owns outright. client.py stages the
# featured image under this same prefix (`_stage_static_post`), and the inline
# mirror step deliberately skips it (`_find_inline_static_media_urls`) because
# a publisher-owned key is already in R2 and has nothing to mirror from.
# Inline images uploaded here inherit that exclusion.
STATIC_MEDIA_PUBLISHER_PREFIX = "wp-content/uploads/publisher/"


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


def _run_cloudflare_json(args: List[str], label: str) -> Any:
    """Run one `cloudflare` CLI command and decode its JSON stdout."""
    result = subprocess.run(
        ["cloudflare", *args],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        diagnostic = (
            result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        )
        raise RuntimeError(f"{label} failed (exit {result.returncode}): {diagnostic}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} returned invalid JSON: {exc}") from exc


def static_media_object_key(image_path: Path) -> str:
    """Return the content-addressed R2 object key for one local image file.

    The key is the file's SHA-256 under the publisher prefix, so identical
    bytes always map to one object and re-running an upload is a no-op
    instead of creating a duplicate.
    """
    digest = hashlib.sha256()
    with Path(image_path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    suffix = Path(image_path).suffix.lower()
    if not suffix:
        raise RuntimeError(f"Image file has no extension: {image_path}")
    return f"{STATIC_MEDIA_PUBLISHER_PREFIX}{digest.hexdigest()}{suffix}"


def _existing_static_media_object(key: str) -> Optional[Dict[str, Any]]:
    """Return the R2 object already stored at this exact key, else None."""
    objects = _run_cloudflare_json(
        [
            "r2",
            "objects",
            "list",
            STATIC_MEDIA_BUCKET,
            "--prefix",
            key,
            "--limit",
            "2",
        ],
        "Static media lookup",
    )
    if not isinstance(objects, list):
        raise RuntimeError("Static media lookup did not return a JSON array")
    matches = [item for item in objects if item.get("key") == key]
    if len(matches) > 1:
        raise RuntimeError(f"Static media lookup returned duplicate keys for {key}")
    return matches[0] if matches else None


def upload_to_static_media(image_path: Path) -> Dict[str, Any]:
    """Upload one local image into the static site's R2 media bucket.

    The object lands at a content-addressed `wp-content/uploads/publisher/` key in
    the canonical media bucket, which the site's media edge serves directly, so
    the returned URL is public the moment the write verifies.

    There is one execution path: the object is either already present with the
    exact byte count (recovered) or it is written and re-read to prove it
    landed. Any failure raises; nothing degrades to another destination.

    Args:
        image_path: Path to the local image file

    Returns:
        Dict with 'key', 'url', 'size', and 'recovered'.

    Raises:
        RuntimeError on any lookup, upload, or verification failure.
    """
    image_path = Path(image_path)
    if not image_path.is_file():
        raise RuntimeError(f"Image file does not exist: {image_path}")
    content_type = mimetypes.guess_type(image_path.name)[0]
    if not content_type:
        raise RuntimeError(f"Could not determine image content type: {image_path}")

    key = static_media_object_key(image_path)
    existing = _existing_static_media_object(key)
    recovered = existing is not None
    if not recovered:
        _run_cloudflare_json(
            [
                "r2",
                "objects",
                "put",
                STATIC_MEDIA_BUCKET,
                key,
                "--file",
                str(image_path),
                "--content-type",
                content_type,
            ],
            "Static media upload",
        )
        existing = _existing_static_media_object(key)
        if existing is None:
            raise RuntimeError(
                f"Static media upload for {key} did not verify in R2 after upload"
            )

    local_size = image_path.stat().st_size
    try:
        stored_size = int(existing["size"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Static media object {key} has no valid size") from exc
    if stored_size != local_size:
        raise RuntimeError(
            f"Static media object {key} is {stored_size} bytes but the local "
            f"file is {local_size} bytes"
        )

    return {
        "key": key,
        "url": f"{STATIC_SITE_ORIGIN}/{key}",
        "size": stored_size,
        "recovered": recovered,
    }


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


def upload_local_images(
    markdown_content: str,
    base_dir: Path,
    verbose: bool = True,
) -> Tuple[str, int]:
    """
    Upload local images referenced by markdown to the static site's R2 media
    bucket and rewrite the markdown to point at the returned public URLs.

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
        print(f"Found {len(refs)} local image(s) to upload to static media")

    rewritten = markdown_content
    uploaded = 0
    for idx, (original_path, _alt_text, resolved_path) in enumerate(refs, 1):
        if verbose:
            print(f"  [{idx}/{len(refs)}] Uploading {resolved_path.name}...")

        media = upload_to_static_media(resolved_path)
        media_url = media["url"]

        if verbose:
            print(f"  [{idx}/{len(refs)}] Uploaded: {media_url}")

        # Replace the original path string (as it appears in the markdown)
        # with the returned public URL. The original path is unique within
        # seen_paths, so a plain str.replace is safe.
        rewritten = rewritten.replace(original_path, media_url)
        uploaded += 1

    return rewritten, uploaded
