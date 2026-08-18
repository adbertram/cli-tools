"""Local Markdown image discovery and upload for Notion block conversion.

Every command that turns Markdown into Notion blocks must run its content
through :func:`process_markdown_images` BEFORE any page mutation and pass the
resulting mapping into ``text_to_blocks(content, image_uploads=...)``. Without
that mapping, ``text_to_blocks`` has no file_upload ID for a local path and
stores the raw ``![alt](path)`` line as a paragraph instead of an image block.

Scope contract (kept identical to ``text_to_blocks``):
- Only a line whose ENTIRE stripped content is ``![alt](src)`` becomes an image
  block, so only those lines are scanned here.
- Lines inside a fenced code block are code, never images.
- ``http://`` / ``https://`` srcs become external image blocks; no upload.
- A src carrying a URI-style scheme that is not http(s) (a pipeline marker such
  as ``IMAGE_PLACEHOLDER: …``) is not a filesystem path; it is left alone and
  stored as a verbatim paragraph by ``text_to_blocks``.
- Anything else IS a filesystem path. It must exist, must be a supported image
  type, and must upload. Any failure raises before the caller mutates the page.
"""

import re
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

import typer

from .output import print_error, print_info

# Image file extensions Notion accepts through the File Upload API.
SUPPORTED_IMAGE_EXTENSIONS = {
    '.gif', '.heic', '.jpeg', '.jpg', '.png', '.svg', '.tif', '.tiff', '.webp', '.ico'
}

# A whole line that is exactly one Markdown image, matching the image branch of
# text_to_blocks (which tests the fully stripped line).
_IMAGE_LINE_PATTERN = re.compile(r'^!\[([^\]]*)\]\(([^)]+)\)$')

# A URI-style scheme prefix (``http:``, ``data:``, ``IMAGE_PLACEHOLDER:``). A src
# carrying one is a marker or remote reference, never a local filesystem path.
_SCHEME_PATTERN = re.compile(r'^[A-Za-z][A-Za-z0-9+._-]*:')


def is_local_image_src(src: str) -> bool:
    """Return True when ``src`` must be resolved and uploaded as a local file."""
    return _SCHEME_PATTERN.match(src) is None


def iter_image_lines(content: str) -> Iterator[Tuple[str, str]]:
    """Yield ``(line, src)`` for every Markdown line that becomes an image block.

    Mirrors ``text_to_blocks``: fenced code content is skipped, and only a line
    that is entirely one ``![alt](src)`` is an image.
    """
    in_fence = False
    for line in content.split('\n'):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _IMAGE_LINE_PATTERN.match(stripped)
        if match:
            yield stripped, match.group(2)


def resolve_image_path(src: str, source_file: Optional[str]) -> Path:
    """Resolve a local image src against the Markdown file that referenced it."""
    if source_file:
        return Path(source_file).parent / src
    return Path(src)


def process_markdown_images(
    content: str,
    source_file: Optional[str],
    client,
) -> Dict[str, str]:
    """Upload every local image referenced by ``content`` and map src -> upload ID.

    Args:
        content: Markdown content to scan.
        source_file: Path to the file the Markdown came from, used to resolve
            relative image srcs. ``None`` resolves them against the process CWD.
        client: Notion client used to upload files.

    Returns:
        Mapping of the ORIGINAL markdown src to its Notion file_upload ID, ready
        for ``text_to_blocks(content, image_uploads=...)``.

    Raises:
        typer.Exit: A referenced local image is missing or is an unsupported
            image type. Raised before the caller performs any page mutation.
        Exception: Propagated from ``client.upload_file`` when an upload fails.
    """
    image_uploads: Dict[str, str] = {}
    missing: List[str] = []
    unsupported: List[str] = []

    for line, src in iter_image_lines(content):
        if not is_local_image_src(src):
            # http(s) URL, or a non-filesystem marker stored verbatim.
            continue
        if src in image_uploads:
            continue

        resolved = resolve_image_path(src, source_file)
        if not resolved.is_file():
            missing.append(f"{line} -> {resolved}")
            continue

        extension = resolved.suffix.lower()
        if extension not in SUPPORTED_IMAGE_EXTENSIONS:
            unsupported.append(f"{line} -> {resolved} ({extension or 'no extension'})")
            continue

        print_info(f"Uploading image: {resolved.name}...")
        image_uploads[src] = client.upload_file(str(resolved))

    if missing or unsupported:
        # Report every bad reference at once so one run fixes them all, and stop
        # before the caller clears, deletes, or writes anything.
        if missing:
            print_error(
                "Local image file(s) referenced by the markdown do not exist:\n  "
                + "\n  ".join(missing)
            )
        if unsupported:
            print_error(
                "Local image file(s) use a type Notion cannot upload "
                f"(supported: {', '.join(sorted(SUPPORTED_IMAGE_EXTENSIONS))}):\n  "
                + "\n  ".join(unsupported)
            )
        raise typer.Exit(1)

    return image_uploads
