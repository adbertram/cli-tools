"""ATA Blog wrapper client using subprocess-backed service CLIs."""
import fcntl
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .config import get_config
from .utils.notion_markdown import normalize_notion_markdown


NOTION_CONTENT_WRITE_TIMEOUT_SECONDS = 300

STATIC_REPOSITORY_ROOT = Path("/Users/adam/Dropbox/GitRepos/Agents/ATABlogger")
STATIC_SITE_ROOT = STATIC_REPOSITORY_ROOT / "static-site"
STATIC_RELEASE_MANIFEST = STATIC_SITE_ROOT / "dist" / "release-manifest.json"
# The static site's own record of every image and the resized variants its
# pages reference: the authority for which derivative keys an attachment owns.
STATIC_MEDIA_INVENTORY = STATIC_SITE_ROOT / "src" / "data" / "media_variants.json"
# Author bound to first-time static stagings: Adam Bertram (authors.json id 2).
STATIC_DEFAULT_AUTHOR_ID = 2

STATIC_PAGES_PROJECT = "ata-blog-static"
STATIC_PAGES_POLL_TIMEOUT_SECONDS = 300
STATIC_PAGES_POLL_INTERVAL_SECONDS = 2
STATIC_PAGES_PENDING_STATUSES = frozenset({"idle", "active"})
STATIC_PAGES_TERMINAL_FAILURE_STATUSES = frozenset({"failure", "canceled"})
STATIC_MEDIA_BUCKET = "ata-blog-media"
# Every image lives under this key prefix: the public media URL path the built
# pages reference.
_STATIC_MEDIA_KEY_PREFIX = "wp-content/uploads/"
STATIC_SITE_ORIGIN = "https://adamtheautomator.com"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
EMPTY_UUID = "00000000-0000-4000-8000-000000000000"
STATIC_BUILD_TOKEN_RELEASE_ID_STALE = "Build token release_id is stale"
STATIC_BUILD_TOKEN_CONTRACT_HASH_STALE = "Build token contract_hash is stale"
STATIC_BUILD_TOKEN_IDENTITY_ERRORS = frozenset(
    {
        STATIC_BUILD_TOKEN_RELEASE_ID_STALE,
        STATIC_BUILD_TOKEN_CONTRACT_HASH_STALE,
    }
)


def _canonical_json_bytes(value: Any) -> bytes:
    """Return P05's recursively-key-sorted RFC-8259 JSON encoding."""
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _artifact_sha256(value: Any) -> str:
    """Return the P05 canonical artifact hash for a JSON value."""
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


class _BuildTokenHandle:
    """The open, exclusively-locked build-token descriptor plus its contents.

    Kept as one object (not a bare fd) so a build performed while holding the
    lock can advance the token's release identity in place -- same inode,
    same lock -- instead of an out-of-band process being the only thing that
    can ever bring the token back in sync with the manifest it just produced.
    """

    __slots__ = ("descriptor", "token")

    def __init__(self, descriptor: int, token: Dict[str, Any]) -> None:
        self.descriptor = descriptor
        self.token = token


def _is_failed_unbuilt_publisher_journal(journal: Dict[str, Any]) -> bool:
    """Return whether a validated journal proves no build or later effect ran."""
    effects = journal["effects"]
    artifacts = journal["artifacts"]
    return (
        journal["state"] == "failed"
        and effects["corpus_writes"] == 0
        and effects["builds"] == 0
        and effects["deployments"] == 0
        and effects["notion_updates"] == 0
        and artifacts["build_sha256"] == EMPTY_SHA256
        and artifacts["deployment_id"] == journal["prior_state"]["deployment_id"]
    )


def _file_sha256(path: Path) -> str:
    """Return a file's SHA-256 without loading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# The time zone every naive timestamp in the static corpus is written in.
# src/lib/routes.js siteLocalIso resolves a corpus timestamp under this zone.
STATIC_SITE_TIME_ZONE = "America/Chicago"


def _corpus_wall_clock(instant: str) -> str:
    """Return one instant as the naive site-local wall clock the corpus stores.

    All 1,332 imported posts carry pubDate/modDate as a naive site-local wall
    clock, and the static site resolves a corpus timestamp under exactly that
    rule. Astro normalizes a YAML timestamp to UTC before a route ever sees it,
    which erases whatever offset the file carried, so a staged post written
    with a UTC offset came out of the resolver five or six hours later than it
    publishes. The only thing that had been correcting it was the harvested
    published-time override in static-site/src/data/post_seo.json -- a record
    that exists only for imported posts. A post the static site originates has
    no such record and never will, so it is staged in the corpus's own
    convention and needs no correction.
    """
    parsed = datetime.fromisoformat(instant.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ClientError(f"Static post publish date must carry a UTC offset: {instant}")
    local = parsed.astimezone(ZoneInfo(STATIC_SITE_TIME_ZONE))
    return local.replace(tzinfo=None, microsecond=0).isoformat()


def _image_pixel_size(path: Path) -> Tuple[int, int]:
    """Return one image file's real pixel width and height, read from its header.

    The static site's head needs og:image:width and og:image:height for every
    post. For an imported post those values were harvested from the live
    page; for a post the static site originates there is nothing to
    harvest, and the build never sees the image because the file goes straight
    to R2. This publisher is the only component that holds the bytes, so it
    measures them here and stages the result in the post's own frontmatter.

    Only the formats this publisher actually uploads are decoded. An
    unrecognized file raises instead of yielding a guessed size, because a wrong
    og:image dimension is a rendering defect on every social card the post ever
    produces.
    """
    header = path.read_bytes()[:64]
    if header[:8] == b"\x89PNG\r\n\x1a\n":
        if header[12:16] != b"IHDR":
            raise ClientError(f"PNG has no leading IHDR chunk: {path}")
        return (
            int.from_bytes(header[16:20], "big"),
            int.from_bytes(header[20:24], "big"),
        )
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        chunk = header[12:16]
        if chunk == b"VP8X":
            return (
                int.from_bytes(header[24:27], "little") + 1,
                int.from_bytes(header[27:30], "little") + 1,
            )
        if chunk == b"VP8 ":
            if header[23:26] != b"\x9d\x01\x2a":
                raise ClientError(f"Lossy WebP has no start code: {path}")
            return (
                int.from_bytes(header[26:28], "little") & 0x3FFF,
                int.from_bytes(header[28:30], "little") & 0x3FFF,
            )
        if chunk == b"VP8L":
            if header[20] != 0x2F:
                raise ClientError(f"Lossless WebP has no signature byte: {path}")
            bits = int.from_bytes(header[21:25], "little")
            return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        raise ClientError(f"Unsupported WebP chunk {chunk!r}: {path}")
    if header[:2] == b"\xff\xd8":
        return _jpeg_pixel_size(path)
    raise ClientError(f"Cannot measure the pixel size of {path}: unrecognized image format")


def _jpeg_pixel_size(path: Path) -> Tuple[int, int]:
    """Return a JPEG's pixel size from its first start-of-frame marker."""
    data = path.read_bytes()
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            raise ClientError(f"JPEG segment is not marker-aligned: {path}")
        marker = data[offset + 1]
        length = int.from_bytes(data[offset + 2 : offset + 4], "big")
        # SOF0-SOF15 carry the frame dimensions; DHT (C4), DAC (CC) and the
        # RSTn markers (D0-D7) share the C0-CF range and do not.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            return (
                int.from_bytes(data[offset + 7 : offset + 9], "big"),
                int.from_bytes(data[offset + 5 : offset + 7], "big"),
            )
        offset += 2 + length
    raise ClientError(f"JPEG has no start-of-frame segment: {path}")


def _file_md5(path: Path) -> str:
    """Return the R2 single-object ETag digest for one local file."""
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_sha256(root: Path) -> str:
    """Hash a tree deterministically from relative paths and file bytes."""
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def _static_corpus_sha256() -> str:
    """Match the release manifest's exact static corpus membership hash.

    This must stay byte-for-byte identical to ``release_manifest.mjs``'s
    ``hashCorpus()``: the same roots (``src/data/posts``, ``src/data/pages``,
    ``src/partials/pages``), the same fixed data files, and the same record
    join (``relative_path<TAB>file_sha256`` per file, sorted, then SHA-256 of
    the newline-terminated concatenation). The build itself does not write into
    these roots -- its markdown generation targets ``dist/`` -- so when this
    membership drifts from the JS side the staged hash can never equal the
    in-transaction build manifest's ``inputs.corpus_sha256`` and the static leg
    aborts (agent-issues#85). ``test_staged_corpus_hash_matches_release_manifest_hash_corpus``
    cross-checks the real JS hash against this function on one hermetic staged
    corpus so a future drift fails the suite instead of a live publish.
    """
    roots = (
        STATIC_SITE_ROOT / "src" / "data" / "posts",
        STATIC_SITE_ROOT / "src" / "data" / "pages",
        STATIC_SITE_ROOT / "src" / "partials" / "pages",
    )
    files = []
    for root in roots:
        if not root.is_dir():
            raise ClientError(f"Static corpus root is missing: {root}")
        for candidate in root.rglob("*"):
            if candidate.is_symlink():
                raise ClientError(f"Static corpus contains a symbolic link: {candidate}")
            if candidate.is_file():
                files.append(candidate)
            elif not candidate.is_dir():
                raise ClientError(f"Static corpus contains a non-regular input: {candidate}")
    for relative_path in (
        "src/data/authors.json",
        "src/data/terms.json",
        "src/data/redirects.json",
        "src/data/home_featured.json",
        "src/data/zero_post_authors.json",
        "src/data/post_seo.json",
        "src/data/page_seo.json",
        "src/data/archive_seo.json",
        # The guid each imported post carried at publish time. It is content,
        # not configuration: it decides what every feed emits as an item's
        # identity, so a change here changes the built output and must move the
        # corpus hash. Mirrors release_manifest.mjs hashCorpus() membership.
        "src/data/post_guids.json",
    ):
        candidate = STATIC_SITE_ROOT / relative_path
        if candidate.is_symlink() or not candidate.is_file():
            raise ClientError(f"Static corpus file is missing or non-regular: {candidate}")
        files.append(candidate)

    records = []
    for path in sorted(set(files)):
        if path.stat().st_size == 0:
            raise ClientError(f"Static corpus file is empty: {path}")
        relative_path = path.relative_to(STATIC_SITE_ROOT).as_posix()
        records.append(f"{relative_path}\t{_file_sha256(path)}")
    if not records:
        raise ClientError("Static corpus file membership is empty")
    records.sort()
    return hashlib.sha256(("\n".join(records) + "\n").encode("utf-8")).hexdigest()


def _atomic_write_json(path: Path, value: Any) -> None:
    """Atomically persist canonical JSON and fsync it before replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(_canonical_json_bytes(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _atomic_write_bytes(path: Path, value: bytes) -> None:
    """Atomically persist bytes and fsync them before replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


class ClientError(Exception):
    """Custom exception for ATA Blog wrapper errors."""
    pass


def _loads_notion_text_json(raw: str) -> Any:
    """Load Notion CLI JSON that may contain raw text control characters."""
    return json.loads(raw, strict=False)


class AtaBlogClient:
    """Client for the notion CLI and the static site publisher."""

    def __init__(self):
        self.config = get_config()
        # Cache of {property_name: notion_type} from the live database schema.
        # Populated lazily by get_property_types() so a single CLI invocation
        # fetches the schema at most once.
        self._property_types_cache: Optional[Dict[str, str]] = None
        # Cache of the static site's media inventory, read once per invocation
        # by the mirroring step that enumerates an attachment's size variants.
        self._static_media_inventory_cache: Optional[Dict[str, Any]] = None

        if not self.config.is_notion_available():
            raise ClientError("notion CLI not found. Install it first.")

    def _run_notion(self, args: List[str], timeout: int = 60) -> subprocess.CompletedProcess:
        """Run a notion CLI command."""
        cmd = ["notion"] + args
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            # notion CLI returns exit code 1 with "No pages found." which is not an error
            if "No pages found" in result.stdout:
                # Return empty array for list commands
                result.stdout = "[]"
                return result
            detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
            raise ClientError(
                f"notion command failed (exit {result.returncode}): {detail}; "
                f"command: notion {' '.join(args)}"
            )
        return result

    @staticmethod
    def _validate_featured_image(featured_image: Optional[str]) -> Path:
        """Validate the required local featured image before publishing."""
        if not featured_image:
            raise ClientError("Featured image is required for publishing. Run image-gen first.")

        image_path = Path(featured_image)
        if not image_path.exists():
            raise ClientError(f"Featured image not found: {featured_image}")
        if not image_path.is_file():
            raise ClientError(f"Featured image path is not a file: {featured_image}")
        if image_path.stat().st_size == 0:
            raise ClientError(f"Featured image file is empty: {featured_image}")

        allowed_extensions = {".webp", ".png", ".jpg", ".jpeg"}
        if image_path.suffix.lower() not in allowed_extensions:
            raise ClientError(
                "Featured image must be a WebP, PNG, or JPEG file: "
                f"{featured_image}"
            )

        return image_path.resolve()

    @staticmethod
    def _resolve_featured_image(page_id: str, featured_image: Optional[str]) -> Path:
        """Return an explicit or conventional pipeline featured image path."""
        if featured_image:
            return AtaBlogClient._validate_featured_image(featured_image)

        candidates = [
            STATIC_REPOSITORY_ROOT / "posts" / page_id / f"featured_image.{extension}"
            for extension in ("webp", "png", "jpg", "jpeg")
        ]
        for candidate in candidates:
            if candidate.exists():
                return AtaBlogClient._validate_featured_image(str(candidate))

        candidate_list = ", ".join(str(candidate) for candidate in candidates)
        raise ClientError(
            "Featured image is required for publishing. "
            "No conventional pipeline image was found. "
            f"Checked: {candidate_list}. "
            "Run image-gen first or pass --featured-image PATH."
        )

    @staticmethod
    def _require_publish_metadata(article: Dict[str, Any]) -> None:
        missing = [
            field for field in ("Keywords", "Category", "Tags", "Excerpt")
            if not article.get(field)
        ]
        if missing:
            raise ClientError(f"Missing required Notion fields: {', '.join(missing)}")

    @staticmethod
    def _notion_term_names(article: Dict[str, Any], field: str) -> List[str]:
        """Split one comma-separated Notion taxonomy field into term names."""
        return [
            name.strip()
            for name in str(article.get(field) or "").split(",")
            if name.strip()
        ]

    def _sponsored_tag_ids(self, article: Dict[str, Any], page_id: str) -> List[int]:
        """Return the Sponsored tag id for a Sponsored `Type`, else no ids."""
        if not article.get("Type"):
            raise ClientError(f"Notion page {page_id} has no Type")
        if not str(article["Type"]).startswith("Sponsored"):
            return []
        # corpus.py imports this module, so the name is imported here.
        from .corpus import SPONSORED_TAG_NAME

        return self._resolve_static_term_ids("tags", [SPONSORED_TAG_NAME])

    @staticmethod
    def _validate_publish_markdown(markdown_content: str) -> None:
        placeholder_lines = [
            f"line {line_number}: {line.strip()}"
            for line_number, line in enumerate(markdown_content.splitlines(), start=1)
            if "IMAGE_PLACEHOLDER" in line
        ]
        if placeholder_lines:
            raise ClientError(
                "IMAGE_PLACEHOLDER marker(s) remain in Notion article content. "
                "Run the image-gen phase before publishing.\n"
                + "\n".join(placeholder_lines)
            )

    # Notion article methods
    def list_articles(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Dict]:
        """List articles from Notion database.

        Args:
            status: Single status or pipe-separated statuses (e.g., "Draft" or "Draft|Review")
            limit: Maximum number of results
            filters: List of filter strings (field:op:value format)
        """
        args = ["database", "page", "list", "-d", self.config.notion_database_id, "--limit", str(limit)]
        if status:
            # Check if multiple statuses (contains |)
            if "|" in status:
                args.extend(["--filter", f"Status:in:{status}"])
            else:
                args.extend(["--filter", f"Status:eq:{status}"])

        # Pass through additional filters to notion CLI
        if filters:
            for f in filters:
                # Normalize 'contains' operator to 'ilike' with wildcards
                if ":contains:" in f.lower():
                    parts = f.split(":", 2)
                    if len(parts) == 3:
                        field, _, value = parts
                        f = f"{field}:ilike:%{value}%"
                args.extend(["--filter", f])

        result = self._run_notion(args)
        return _loads_notion_text_json(result.stdout)

    def get_article(self, page_id: str) -> Dict[str, Any]:
        result = self._run_notion(["database", "page", "get", page_id, "--include-blocks"])
        return json.loads(result.stdout)

    def get_article_markdown(self, page_id: str) -> str:
        """Get article content as markdown."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            temp_path = f.name

        try:
            self._run_notion([
                "database", "page", "get", page_id,
                "--include-blocks", "--markdown", "--out-file", temp_path
            ])
            markdown = Path(temp_path).read_text()
            if not markdown.strip():
                raise ClientError(
                    f"Notion page {page_id} has no readable content blocks. "
                    "The page is empty or the prior content sync did not persist; "
                    "re-run `ata-blog notion-page content set PAGE_ID --file PATH` "
                    "and verify this command again."
                )
            return markdown
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def get_article_comments(self, page_id: str, with_context: bool = True) -> List[Dict]:
        """Get comments on an article page.

        Args:
            page_id: Notion page ID
            with_context: Include parent block text as context (default: True)

        Returns:
            List of comment objects with text and context
        """
        args = ["comments", "list", "--page-id", page_id]
        if with_context:
            args.append("--with-context")
        result = self._run_notion(args)
        return json.loads(result.stdout)

    def create_article_comment(self, page_id: str, body: str) -> Dict[str, Any]:
        """Create a comment on an article page.

        Args:
            page_id: Notion page ID
            body: Comment text content

        Returns:
            Created comment object from the Notion API
        """
        if not body or not body.strip():
            raise ClientError("Comment body must not be empty")
        args = ["comments", "create", body, "--page-id", page_id]
        result = self._run_notion(args)
        return json.loads(result.stdout)

    def get_article_comment(self, comment_id: str) -> Dict[str, Any]:
        """Get a single comment by its Notion comment ID."""
        result = self._run_notion(["comments", "get", comment_id])
        return json.loads(result.stdout)

    # Boolean coercion table for checkbox properties (case-insensitive keys).
    # Code performs the lookup; this data stores the accepted spellings so a new
    # accepted token is a data change, not a control-flow change.
    _CHECKBOX_TRUE_VALUES = frozenset({"true", "yes", "1"})
    _CHECKBOX_FALSE_VALUES = frozenset({"false", "no", "0"})

    # Publication artifact fields cleared when an article is unpublished.
    # Data-driven: each entry maps a Notion property name to the reset value the
    # update path receives (empty string clears to the correct typed null/empty
    # resolved from the live schema; "false" resets a checkbox). Content,
    # Keywords, Tags, Category, Schema Type, Stage Date, and Post Performance
    # Snapshots are intentionally NOT listed so they stay intact.
    UNPUBLISH_ARTIFACT_FIELDS = {
        "Published URL": "",
        "X Post URL": "",
        "LinkedIn Post URL": "",
        "Publish Date": "",
        "Promoted": "false",
    }

    def get_property_types(self) -> Dict[str, str]:
        """Return {property_name: notion_type} from the live database schema.

        Fetched once per client instance via the same `notion database schema`
        path used by get_valid_statuses(), so property updates always reflect
        the real Notion schema rather than a hardcoded map.
        """
        if self._property_types_cache is None:
            result = self._run_notion(
                ["database", "schema", self.config.notion_database_id]
            )
            schema = json.loads(result.stdout)
            properties = schema.get("properties")
            if not isinstance(properties, dict) or not properties:
                raise ClientError(
                    "Notion database schema returned no properties; cannot map "
                    "property types"
                )
            self._property_types_cache = {
                name: meta.get("type")
                for name, meta in properties.items()
                if isinstance(meta, dict) and meta.get("type")
            }
        return self._property_types_cache

    def _coerce_checkbox(self, prop_name: str, prop_value: str) -> bool:
        """Coerce a string to a checkbox bool, failing fast on ambiguity."""
        normalized = prop_value.strip().lower()
        if normalized in self._CHECKBOX_TRUE_VALUES:
            return True
        if normalized in self._CHECKBOX_FALSE_VALUES:
            return False
        accepted = ", ".join(
            sorted(self._CHECKBOX_TRUE_VALUES | self._CHECKBOX_FALSE_VALUES)
        )
        raise ClientError(
            f"Cannot set checkbox property '{prop_name}': ambiguous boolean "
            f"value '{prop_value}'. Use one of: {accepted}."
        )

    def _build_notion_property(self, prop_name: str, prop_value: str) -> Any:
        """Build a raw Notion API property payload from the live schema type.

        Drives the payload shape from the property's Notion type (data-driven),
        handling both normal values and the empty-string "clear this property"
        case with the correct typed null/empty per Notion's API contract.
        """
        prop_types = self.get_property_types()
        prop_type = prop_types.get(prop_name)
        if prop_type is None:
            known = ", ".join(sorted(prop_types))
            raise ClientError(
                f"Unknown property '{prop_name}' for this Notion database. "
                f"Known properties: {known}"
            )

        is_empty = prop_value == ""

        # Checkbox is the one type with no meaningful empty state: an explicit
        # boolean is always required, so it is handled before the empty check.
        if prop_type == "checkbox":
            return {"checkbox": self._coerce_checkbox(prop_name, prop_value)}

        # Typed empty/null payloads per Notion API for the "clear" case.
        # Code reads this map; data defines what "empty" means per type.
        empty_payloads: Dict[str, Any] = {
            "title": {"title": []},
            "rich_text": {"rich_text": []},
            "multi_select": {"multi_select": []},
            "people": {"people": []},
            "relation": {"relation": []},
            "files": {"files": []},
            "url": {"url": None},
            "email": {"email": None},
            "phone_number": {"phone_number": None},
            "number": {"number": None},
            "select": {"select": None},
            "status": {"status": None},
            "date": {"date": None},
        }
        if is_empty:
            if prop_type not in empty_payloads:
                raise ClientError(
                    f"Cannot clear property '{prop_name}' of type '{prop_type}': "
                    "clearing this property type is not supported"
                )
            return empty_payloads[prop_type]

        # Non-empty typed payloads.
        if prop_type == "title":
            return {"title": [{"type": "text", "text": {"content": prop_value}}]}
        if prop_type == "rich_text":
            return {"rich_text": [{"type": "text", "text": {"content": prop_value}}]}
        if prop_type == "select":
            return {"select": {"name": prop_value}}
        if prop_type == "status":
            return {"status": {"name": prop_value}}
        if prop_type == "multi_select":
            values = [v.strip() for v in prop_value.split(",") if v.strip()]
            return {"multi_select": [{"name": v} for v in values]}
        if prop_type == "url":
            return {"url": prop_value}
        if prop_type == "email":
            return {"email": prop_value}
        if prop_type == "phone_number":
            return {"phone_number": prop_value}
        if prop_type == "number":
            try:
                number = float(prop_value)
            except ValueError as exc:
                raise ClientError(
                    f"Cannot set number property '{prop_name}': "
                    f"'{prop_value}' is not a number"
                ) from exc
            if number.is_integer():
                number = int(number)
            return {"number": number}
        if prop_type == "date":
            return {"date": {"start": prop_value}}

        raise ClientError(
            f"Cannot set property '{prop_name}' of type '{prop_type}': "
            "this property type is not supported for updates"
        )

    def update_article(
        self,
        page_id: str,
        status: Optional[str] = None,
        properties: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Update article properties in Notion.

        Args:
            page_id: Notion page ID
            status: New status value (will be prefixed with "Status:" if needed)
            properties: Dict of property updates in format {"PropertyName": "value"}

        Returns dict with updated page info
        """
        args = ["database", "page", "update", page_id]

        if status:
            # Auto-prefix "Status:" if not already present
            status_value = status if ":" in status else f"Status:{status}"
            args.extend(["--status", status_value])

        if properties:
            # Build one raw Notion API property payload per update, driven by the
            # live database schema type. This handles normal values, typed
            # nulls/empties (e.g. url:null, rich_text:[]) for the "clear"
            # case, and checkbox boolean coercion uniformly via --properties.
            raw_json_properties = {
                prop_name: self._build_notion_property(prop_name, prop_value)
                for prop_name, prop_value in properties.items()
            }
            args.extend(["--properties", json.dumps(raw_json_properties)])

        result = self._run_notion(args)
        return json.loads(result.stdout)

    DEFAULT_IDEA_TEMPLATE_ID = "2e05d9c8-5b2b-8065-8aca-e8da0e179b97"

    VALID_CATEGORIES = ("IT Ops", "Home Ops", "DevOps", "Cloud", "Information Security", "Ebook")

    def create_article(
        self,
        title: str,
        excerpt: str,
        category: str,
        keywords: Optional[str] = None,
        post_type: str = "Standard",
        status: Optional[str] = None,
        template_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new article in the Notion database.

        Args:
            title: Article title
            excerpt: Article description/synopsis
            category: Category (must be one of VALID_CATEGORIES)
            keywords: Optional comma-separated SEO keywords
            post_type: Post type (default: Standard)
            status: Optional status (defaults to Idea)
            template_id: Optional template ID (defaults to Standard ATA Tutorial AI-Created Idea)
        """
        if category not in self.VALID_CATEGORIES:
            raise ClientError(
                f"Invalid category '{category}'. Must be one of: {', '.join(self.VALID_CATEGORIES)}"
            )

        # NOTE: When --from-template is used, --select flags for Category/Type are
        # silently dropped by the notion CLI. Setting them via --properties JSON works.
        properties: Dict[str, Any] = {
            "Category": {"select": {"name": category}},
            "Type": {"select": {"name": post_type}},
            "Status": {"status": {"name": status or "Idea"}},
            "Excerpt": {"rich_text": [{"text": {"content": excerpt}}]},
        }
        if keywords:
            properties["Keywords"] = {"rich_text": [{"text": {"content": keywords}}]}

        args = [
            "database", "page", "create", self.config.notion_database_id,
            "--title", title,
            "--from-template", template_id or self.DEFAULT_IDEA_TEMPLATE_ID,
            "--properties", json.dumps(properties),
        ]
        result = self._run_notion(args)
        return json.loads(result.stdout)

    def set_article_content(self, page_id: str, file_path: str) -> Dict[str, Any]:
        """Replace article content with markdown from file and verify persistence."""
        source_markdown = Path(file_path).read_text(encoding="utf-8")
        if not source_markdown.strip():
            raise ClientError(f"Refusing to sync empty markdown file: {file_path}")
        result = self._run_notion_with_normalized_markdown_file(
            ["database", "page", "content", "set", page_id],
            file_path,
            timeout=NOTION_CONTENT_WRITE_TIMEOUT_SECONDS,
        )
        try:
            self.get_article_markdown(page_id)
        except ClientError as exc:
            raise ClientError(
                f"Content sync for Notion page {page_id} did not persist readable blocks: {exc}"
            ) from exc
        return json.loads(result.stdout) if result.stdout.strip() else {"success": True}

    def append_article_content(self, page_id: str, file_path: str) -> Dict[str, Any]:
        """Append markdown content to article."""
        result = self._run_notion_with_normalized_markdown_file(
            ["database", "page", "content", "append", page_id],
            file_path,
        )
        return json.loads(result.stdout) if result.stdout.strip() else {"success": True}

    def _run_notion_with_normalized_markdown_file(
        self,
        args: List[str],
        file_path: str,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess:
        """Run a Notion content command with API-compatible markdown."""

        original_path = Path(file_path)
        original_markdown = original_path.read_text(encoding="utf-8")
        normalized_markdown = normalize_notion_markdown(original_markdown)

        if normalized_markdown == original_markdown:
            return self._run_notion([*args, "--file", file_path], timeout=timeout)

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=original_path.suffix or ".md",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp.write(normalized_markdown)
            normalized_path = tmp.name

        try:
            return self._run_notion([*args, "--file", normalized_path], timeout=timeout)
        finally:
            Path(normalized_path).unlink(missing_ok=True)

    def search_articles(self, query: str, status: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Search articles by title."""
        args = ["database", "page", "list", "-d", self.config.notion_database_id, "--limit", str(limit)]
        # Use 'like' operator with wildcards for title search
        args.extend(["--filter", f"Title:like:%{query}%"])
        if status:
            # Check if multiple statuses (contains |)
            if "|" in status:
                args.extend(["--filter", f"Status:in:{status}"])
            else:
                args.extend(["--filter", f"Status:eq:{status}"])
        result = self._run_notion(args)
        return json.loads(result.stdout)

    def get_valid_statuses(self) -> List[str]:
        """Return live valid status names from the configured Notion database."""
        result = self._run_notion(["database", "schema", self.config.notion_database_id])
        schema = json.loads(result.stdout)
        status_property = schema.get("properties", {}).get("Status", {})
        if status_property.get("type") != "status":
            raise ClientError("Notion database schema does not contain a Status status property")

        options = status_property.get("options") or []
        statuses: List[str] = []
        for option in options:
            if isinstance(option, str):
                statuses.append(option)
            elif isinstance(option, dict) and option.get("name"):
                statuses.append(str(option["name"]))

        if not statuses:
            raise ClientError("Notion Status property has no options in the live database schema")
        return statuses

    # Minimum lead time a returned slot must have over true UTC now. Acts as
    # a defense-in-depth guard independent of the timezone-correctness of the
    # code above it: if a future bug reintroduces a naive/local "now", this
    # still refuses to hand back a slot that isn't safely in the future.
    _MIN_SCHEDULE_LEAD = timedelta(minutes=30)

    # Publishing window, in UTC hours. A slot is valid when its hour is in
    # [_SCHEDULE_WINDOW_START_HOUR, _SCHEDULE_WINDOW_END_HOUR): 09:00 is the
    # earliest slot of a weekday and 16:00 the latest, so nothing publishes at
    # or after 5pm UTC.
    _SCHEDULE_WINDOW_START_HOUR = 9
    _SCHEDULE_WINDOW_END_HOUR = 17

    def _schedule_lock_path(self) -> Path:
        """Return the one lock serializing slot reads, picks, and the Notion write."""
        return self._publisher_runtime_root() / "schedule.lock"

    def _read_scheduled_slots(self) -> List[datetime]:
        """Read occupied slots from the Notion pages in Status Scheduled."""
        limit = 100
        pages = self.list_articles(status="Scheduled", limit=limit)
        if len(pages) >= limit:
            raise ClientError(
                f"Scheduled page query reached the {limit}-page list limit; "
                "occupied slots cannot be read completely"
            )
        occupied: List[datetime] = []
        for page in pages:
            value = page["Publish Date"]
            if not value:
                raise ClientError(f"Scheduled Notion page {page['id']} has no Publish Date")
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ClientError(
                    f"Scheduled Notion page {page['id']} has a Publish Date that is "
                    f"not one ISO 8601 timestamp: {value}"
                ) from exc
            if parsed.tzinfo is None:
                raise ClientError(
                    f"Scheduled Notion page {page['id']} has a Publish Date "
                    f"without a UTC offset: {value}"
                )
            occupied.append(parsed.astimezone(timezone.utc))
        return occupied

    @staticmethod
    def _ceil_to_hour(value: datetime) -> datetime:
        """Round a datetime UP to the next hour boundary (never truncates past it).

        A value already exactly on the hour is returned unchanged; any other
        value rolls forward to the next hour. This guarantees the result is
        never earlier than the input, which "add 1 hour then truncate" does
        not guarantee once minutes/seconds/microseconds enter the picture.
        """
        truncated = value.replace(minute=0, second=0, microsecond=0)
        return truncated if truncated == value else truncated + timedelta(hours=1)

    @classmethod
    def _in_schedule_window(cls, value: datetime) -> bool:
        """Return True when the value's hour is inside the publishing window."""
        return cls._SCHEDULE_WINDOW_START_HOUR <= value.hour < cls._SCHEDULE_WINDOW_END_HOUR

    @classmethod
    def _next_window_start(cls, value: datetime) -> datetime:
        """Return the earliest window opening at or after an out-of-window value.

        Only called for values the window guard rejected, so the hour is either
        before the window opens (roll forward to today's opening) or at/after it
        closes (roll forward to tomorrow's opening). Weekend handling stays with
        the loop's weekend guard, which re-runs on the returned value.
        """
        day = value if value.hour < cls._SCHEDULE_WINDOW_START_HOUR else value + timedelta(days=1)
        return day.replace(
            hour=cls._SCHEDULE_WINDOW_START_HOUR,
            minute=0,
            second=0,
            microsecond=0,
        )

    @staticmethod
    def _parse_schedule_window(
        schedule_after: Optional[str], schedule_before: Optional[str],
    ) -> Optional[Tuple[datetime, datetime]]:
        """Parse an optional inclusive/exclusive, timezone-aware scheduling window."""
        if schedule_after is None and schedule_before is None:
            return None
        if schedule_after is None or schedule_before is None:
            raise ClientError("--schedule-after and --schedule-before must be supplied together")
        bounds = []
        for name, value in (("--schedule-after", schedule_after), ("--schedule-before", schedule_before)):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ClientError(f"{name} is not valid ISO 8601: {value}") from exc
            if parsed.tzinfo is None:
                raise ClientError(f"{name} must include a UTC offset")
            bounds.append(parsed.astimezone(timezone.utc))
        if bounds[0] >= bounds[1]:
            raise ClientError("--schedule-after must precede --schedule-before")
        return bounds[0], bounds[1]

    @staticmethod
    def _require_schedule_in_window(
        value: str, schedule_window: Optional[Tuple[datetime, datetime]],
    ) -> None:
        """Reject a slot outside the frozen [start, end) scheduling window."""
        if schedule_window is None:
            return
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ClientError(f"Schedule date is not valid ISO 8601: {value}") from exc
        if parsed.tzinfo is None:
            raise ClientError("Schedule date must include a UTC offset")
        if not schedule_window[0] <= parsed < schedule_window[1]:
            raise ClientError(f"Schedule date is outside the frozen scheduling window: {value}")

    def find_next_schedule_slot(
        self, schedule_window: Optional[Tuple[datetime, datetime]] = None,
    ) -> str:
        """
        Find next available publication slot respecting:
        - Max 2 posts per weekday
        - 4+ hour gap between posts
        - No weekends (roll to Monday)
        - Posts scheduled between 9am-5pm UTC only

        Takes no lock and writes nothing: _schedule_article holds the schedule
        lock across this read, the pick, and the Notion write.

        All arithmetic here is in UTC. The host machine's local timezone is
        never read: schedule slots are unambiguous UTC, so "now" must be true
        UTC now, not this process's local wall-clock time.

        Returns:
            ISO 8601 UTC datetime string with an explicit +00:00 offset
            (e.g., "2026-01-10T09:00:00+00:00").
        """
        occupied_times = self._read_scheduled_slots()

        # Start from true UTC now, round UP to the next hour boundary so the
        # slot is never earlier than "now" plus a full hour of lead time.
        now = datetime.now(timezone.utc)
        candidate = self._ceil_to_hour(now + timedelta(hours=1))
        if schedule_window is not None:
            candidate = max(candidate, self._ceil_to_hour(schedule_window[0]))

        max_iterations = 100  # Safety limit
        for _ in range(max_iterations):
            if schedule_window is not None and candidate >= schedule_window[1]:
                raise ClientError("No available schedule slot inside the frozen scheduling window")
            # Skip weekends (5=Saturday, 6=Sunday)
            if candidate.weekday() >= 5:
                days_until_monday = 7 - candidate.weekday()
                candidate = (candidate + timedelta(days=days_until_monday)).replace(
                    hour=self._SCHEDULE_WINDOW_START_HOUR, minute=0, second=0, microsecond=0
                )
                continue

            # Single publishing-window guard. Every candidate passes through
            # here before it can be accepted, whatever produced it: the initial
            # seed, a 4-hour conflict push that ran past 5pm or past midnight,
            # or the lead-time recovery below. Keeping the window in one place
            # is what stops an out-of-hours slot from slipping through.
            if not self._in_schedule_window(candidate):
                candidate = self._next_window_start(candidate)
                continue

            # Count posts on same day
            same_day = [t for t in occupied_times if t.date() == candidate.date()]
            if len(same_day) >= 2:
                candidate = (candidate + timedelta(days=1)).replace(
                    hour=self._SCHEDULE_WINDOW_START_HOUR, minute=0, second=0, microsecond=0
                )
                continue

            # Check 4+ hour gap
            conflicts = [t for t in occupied_times if abs((t - candidate).total_seconds()) < 4 * 3600]
            if conflicts:
                candidate = candidate + timedelta(hours=4)
                continue

            # Defense-in-depth guard: refuse to hand back a slot that is not
            # genuinely, safely in the future relative to true UTC now, no
            # matter how "candidate" was derived above.
            if candidate < datetime.now(timezone.utc) + self._MIN_SCHEDULE_LEAD:
                candidate = self._ceil_to_hour(datetime.now(timezone.utc) + timedelta(hours=1))
                continue

            slot = candidate.isoformat()
            self._require_schedule_in_window(slot, schedule_window)
            return slot

        raise ClientError("Could not find available schedule slot within iteration limit")

    @staticmethod
    def _parse_schedule_date(value: str) -> datetime:
        """Parse --date, rejecting anything but a UTC-offset-aware timestamp."""
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ClientError(f"--date is not valid ISO 8601: {value}") from exc
        if parsed.tzinfo is None:
            raise ClientError("--date must include a UTC offset")
        return parsed

    def _require_free_explicit_slot(
        self, value: str, schedule_window: Optional[Tuple[datetime, datetime]] = None,
    ) -> str:
        """Validate an explicit UTC-aware slot no Scheduled page occupies."""
        parsed = self._parse_schedule_date(value)
        slot = parsed.astimezone(timezone.utc).isoformat()
        self._require_schedule_in_window(slot, schedule_window)
        if parsed in self._read_scheduled_slots():
            raise ClientError(f"Schedule slot is already occupied: {slot}")
        return slot

    def _publisher_runtime_root(self) -> Path:
        """Return the active-profile directory that owns publisher state."""
        return self.config.get_profile_data_dir() / "static-publisher"

    @staticmethod
    def _publisher_idempotency_key(page_id: str, source_revision: str) -> str:
        """Implement P05 publisherIdempotencyKey's frozen byte encoding."""
        payload = f"{page_id}\n{source_revision}\n".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @contextmanager
    def _exclusive_publisher_lock(self, path: Path, *, blocking: bool = True):
        """Hold one process-transferable advisory lock for the context."""
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            try:
                fcntl.flock(descriptor, operation)
            except BlockingIOError as exc:
                raise ClientError(f"Publisher lock is already held: {path}") from exc
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _publisher_paths(self, page_id: str, idempotency_key: str) -> Dict[str, Path]:
        """Return all active-profile paths for one publisher transaction."""
        root = self._publisher_runtime_root()
        transaction_root = root / "transactions"
        return {
            "page_lock": self._publisher_page_lock_path(page_id),
            "build_lock": root / "locks" / "build.lock",
            "journal": transaction_root / f"{idempotency_key}.journal.json",
            "runtime": transaction_root / f"{idempotency_key}.runtime.json",
            "stage_plan": transaction_root / f"{idempotency_key}.stage-plan.json",
            "backup": transaction_root / f"{idempotency_key}.corpus-backup",
        }

    def _publisher_preview_paths(
        self,
        page_id: str,
        idempotency_key: str,
    ) -> Dict[str, Path]:
        """Return isolated sidecar paths for one hosted preview deployment."""
        root = self._publisher_runtime_root()
        preview_root = root / "previews"
        return {
            "page_lock": self._publisher_page_lock_path(page_id),
            "build_lock": root / "locks" / "build.lock",
            "runtime": preview_root / f"{idempotency_key}.runtime.json",
            "stage_plan": preview_root / f"{idempotency_key}.stage-plan.json",
            "backup": preview_root / f"{idempotency_key}.corpus-backup",
        }

    def _publisher_page_lock_path(self, page_id: str) -> Path:
        """Return a filesystem-safe lock path for one Notion page identity."""
        page_key = hashlib.sha256(page_id.encode("utf-8")).hexdigest()
        return self._publisher_runtime_root() / "locks" / f"page-{page_key}.lock"

    @staticmethod
    def _load_required_json(path: Path, label: str) -> Dict[str, Any]:
        """Load a required JSON object and fail clearly on corruption."""
        if not path.is_file():
            raise ClientError(f"Required {label} is missing: {path}")
        try:
            document = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise ClientError(f"Corrupt {label} {path}: {exc}") from exc
        if not isinstance(document, dict):
            raise ClientError(f"Invalid {label} {path}: expected a JSON object")
        return document

    def _resolve_static_term_ids(self, taxonomy: str, names: List[str]) -> List[int]:
        """Resolve Notion taxonomy names to static term IDs via terms.json."""
        if not names:
            raise ClientError(
                f"Cannot stage a static post without {taxonomy}: the Notion "
                "page has none set"
            )
        terms_path = STATIC_SITE_ROOT / "src" / "data" / "terms.json"
        terms = self._load_required_json(terms_path, "static corpus terms")
        entries = terms.get(taxonomy)
        if not isinstance(entries, list):
            raise ClientError(f"Static corpus terms has no {taxonomy} list")
        by_name = {
            str(entry.get("name", "")).casefold(): int(entry["id"])
            for entry in entries
            if isinstance(entry, dict) and entry.get("id") is not None
        }
        ids = []
        for name in names:
            key = name.casefold()
            if key not in by_name:
                raise ClientError(
                    f"Unknown static corpus {taxonomy} name: {name!r} "
                    f"(not present in {terms_path})"
                )
            ids.append(by_name[key])
        return ids

    def _load_static_release_manifest(self) -> Dict[str, Any]:
        """Load and shape-check the build's own release manifest."""
        manifest = self._load_required_json(STATIC_RELEASE_MANIFEST, "release manifest")
        if manifest.get("schema_version") != "ata-static-release/v2":
            raise ClientError("Release manifest schema is not ata-static-release/v2")
        release_id = manifest.get("release_id")
        contract_hash = manifest.get("contract_hash")
        if not isinstance(release_id, str) or not release_id:
            raise ClientError("Release manifest has no release_id")
        if not re.fullmatch(r"[0-9a-f]{64}", str(contract_hash)):
            raise ClientError("Release manifest contract_hash is not SHA-256")
        return manifest

    @staticmethod
    def _source_revision(
        article: Dict[str, Any],
        markdown_content: str,
        image_path: Path,
    ) -> str:
        """Hash only source inputs, excluding fields the transaction mutates."""
        excluded = {"Status", "Published URL", "Publish Date"}
        source_article = {
            key: value for key, value in article.items() if key not in excluded
        }
        digest = hashlib.sha256()
        digest.update(_canonical_json_bytes(source_article))
        digest.update(b"\n")
        digest.update(markdown_content.encode("utf-8"))
        digest.update(b"\n")
        digest.update(_file_sha256(image_path).encode("ascii"))
        return digest.hexdigest()

    @staticmethod
    def _static_slug(title: str, supplied_slug: Optional[str]) -> str:
        """Return the public command's deterministic root-level slug."""
        source = supplied_slug or title
        slug = re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-")[:50].rstrip("-")
        if not slug:
            raise ClientError("Could not derive a non-empty static post slug")
        return slug

    def _notion_slug(self, article: Dict[str, Any], page_id: str) -> Optional[str]:
        """Return the Notion `Slug` value, the one supplied-slug source."""
        if "Slug" not in article:
            raise ClientError(
                f"Notion page {page_id} has no 'Slug' property; add a rich_text "
                "property named Slug to the posts database"
            )
        value = str(article["Slug"] or "").strip()
        if not value:
            return None
        normalized = self._static_slug(value, None)
        if normalized != value:
            raise ClientError(
                f"Notion Slug '{value}' on page {page_id} is not a normalized slug; "
                f"the publisher would change it to '{normalized}'"
            )
        return value

    @staticmethod
    def _find_static_post(slug: str) -> Optional[Path]:
        """Find the unique corpus record for a slug."""
        post_root = STATIC_SITE_ROOT / "src" / "data" / "posts"
        matches = []
        marker = f'slug: "{slug}"'
        if post_root.exists():
            for path in post_root.glob("*.md"):
                head = path.read_text(errors="strict").split("---", 2)
                if len(head) >= 3 and marker in head[1].splitlines():
                    matches.append(path)
        if len(matches) > 1:
            raise ClientError(f"Static corpus contains duplicate slug '{slug}'")
        return matches[0] if matches else None

    @staticmethod
    def _find_static_post_by_notion_page_id(page_id: str) -> Optional[Path]:
        """Find the unique staged corpus record for a Notion page id.

        A staged (wpId 0) post's durable identity is its notionPageId, not
        its slug -- the slug is re-derived from the Notion page's title on
        every staging call and can legitimately change between two publish
        attempts for the same page (a title edit in Notion). Looking the
        existing record up only by slug (as `_find_static_post` does) misses
        that case: a slug change makes the lookup return None, so the
        caller treats an already-staged page as brand new and writes a
        second corpus file under the new slug, leaving two records with the
        same notionPageId/route id -- one live, one an orphaned duplicate.
        This lookup lets staging recognize "already staged under a
        different slug" and update that same file in place instead.
        """
        post_root = STATIC_SITE_ROOT / "src" / "data" / "posts"
        matches = []
        marker = f'notionPageId: "{page_id}"'
        if post_root.exists():
            for path in post_root.glob("*.md"):
                head = path.read_text(errors="strict").split("---", 2)
                if len(head) >= 3 and marker in head[1].splitlines():
                    matches.append(path)
        if len(matches) > 1:
            raise ClientError(f"Static corpus contains duplicate notionPageId '{page_id}'")
        return matches[0] if matches else None

    @staticmethod
    def _replace_frontmatter_value(frontmatter: List[str], key: str, value: str) -> None:
        """Replace or append one exact YAML frontmatter scalar."""
        prefix = f"{key}:"
        indexes = [index for index, line in enumerate(frontmatter) if line.startswith(prefix)]
        if len(indexes) > 1:
            raise ClientError(f"Static post frontmatter contains duplicate {key}")
        line = f"{key}: {value}"
        if indexes:
            frontmatter[indexes[0]] = line
        else:
            frontmatter.append(line)

    def _stage_static_article(
        self,
        *,
        page_id: str,
        slug: str,
        article: Dict[str, Any],
        markdown_content: str,
        image_path: Path,
        publish_date: str,
        paths: Dict[str, Path],
    ) -> Dict[str, Any]:
        """Write one deterministic corpus record and preserve its exact preimage."""
        sponsored_tag_ids = self._sponsored_tag_ids(article, page_id)
        post_root = STATIC_SITE_ROOT / "src" / "data" / "posts"
        post_root.mkdir(parents=True, exist_ok=True)
        # notionPageId is this record's durable identity; slug is a derived
        # display attribute that can change between staging attempts (a
        # Notion title edit). Prefer the identity lookup so a slug change
        # updates the existing staged file in place instead of creating a
        # second, duplicate-route-id file under the new slug.
        target = self._find_static_post_by_notion_page_id(page_id) or self._find_static_post(slug)
        if paths["backup"].exists():
            if target is None:
                target = post_root / f"notion-{page_id}-{slug}.md"
            original = paths["backup"].read_bytes()
            created = not original
            if not created:
                text = original.decode("utf-8")
                pieces = text.split("---", 2)
                if len(pieces) != 3 or pieces[0].strip():
                    raise ClientError(f"Static post backup has invalid frontmatter: {target}")
                frontmatter = pieces[1].strip("\n").splitlines()
            else:
                frontmatter = []
        elif target is None:
            target = post_root / f"notion-{page_id}-{slug}.md"
            original = b""
            created = True
            frontmatter: List[str] = []
        else:
            original = target.read_bytes()
            created = False
            text = original.decode("utf-8")
            pieces = text.split("---", 2)
            if len(pieces) != 3 or pieces[0].strip():
                raise ClientError(f"Static post has invalid frontmatter: {target}")
            frontmatter = pieces[1].strip("\n").splitlines()

        image_hash = _file_sha256(image_path)
        extension = image_path.suffix.lower()
        object_key = f"wp-content/uploads/publisher/{page_id}/{image_hash}{extension}"
        image_url = f"{STATIC_SITE_ORIGIN}/{object_key}"
        # The featured image's real pixel size, measured from this exact file.
        # The static build emits og:image:width/height and the JSON-LD
        # ImageObject dimensions for every post. A migrated post takes them
        # from src/data/post_seo.json, which was harvested once at import
        # and therefore only ever covers imported posts. A post the static
        # site originates has no such
        # record and never will, so its dimensions come from the image itself
        # -- and this publisher is the only component that holds the bytes,
        # because the file goes straight to R2 and the build never sees it.
        image_width, image_height = _image_pixel_size(image_path)
        title = str(article.get("Title") or article.get("title") or "Untitled")
        excerpt = " ".join(str(article.get("Excerpt") or "").split())
        replacements = {
            "notionPageId": json.dumps(page_id, ensure_ascii=False),
            "slug": json.dumps(slug, ensure_ascii=False),
            "title": json.dumps(title, ensure_ascii=False),
            "description": json.dumps(excerpt, ensure_ascii=False),
            "pubDate": _corpus_wall_clock(publish_date),
            "modDate": _corpus_wall_clock(publish_date),
            "featuredImage": json.dumps(image_url, ensure_ascii=False),
            "featuredImageWidth": str(image_width),
            "featuredImageHeight": str(image_height),
        }
        # The corpus loaders require authorId, categoryIds, tagIds, and wpId on
        # every post. A first-time post has no prior frontmatter, so bind
        # the default author, resolve real taxonomy IDs from the post's
        # Notion metadata against the static corpus terms, and stage wpId 0,
        # the corpus marker for a post the static site originated.
        if not any(line.startswith("authorId:") for line in frontmatter):
            replacements["authorId"] = str(STATIC_DEFAULT_AUTHOR_ID)
        if not any(line.startswith("categoryIds:") for line in frontmatter):
            replacements["categoryIds"] = json.dumps(
                self._resolve_static_term_ids(
                    "categories", self._notion_term_names(article, "Category")
                )
            )
        # A restaged record keeps its tagIds bytes; the line is rewritten only
        # when it is absent or the post's Type adds the Sponsored tag to it.
        tag_lines = [line for line in frontmatter if line.startswith("tagIds:")]
        if tag_lines:
            try:
                tag_ids = json.loads(tag_lines[0].split(":", 1)[1])
            except json.JSONDecodeError as exc:
                raise ClientError(f"Static post has an invalid tagIds line: {target}") from exc
        else:
            tag_ids = self._resolve_static_term_ids(
                "tags", self._notion_term_names(article, "Tags")
            )
        sponsored_ids = [term_id for term_id in sponsored_tag_ids if term_id not in tag_ids]
        if not tag_lines or sponsored_ids:
            replacements["tagIds"] = json.dumps(tag_ids + sponsored_ids)
        if not any(line.startswith("wpId:") for line in frontmatter):
            replacements["wpId"] = "0"
        for key, value in replacements.items():
            self._replace_frontmatter_value(frontmatter, key, value)
        rendered = (
            "---\n"
            + "\n".join(frontmatter)
            + "\n---\n"
            + markdown_content.strip()
            + "\n"
        ).encode("utf-8")
        _atomic_write_json(
            paths["stage_plan"],
            {"article_path": str(target), "created_article": created},
        )
        if not paths["backup"].exists():
            _atomic_write_bytes(paths["backup"], original)
        _atomic_write_bytes(target, rendered)
        return {
            "article_path": str(target),
            "created_article": created,
            "object_key": object_key,
            "image_url": image_url,
            "image_path": str(image_path),
            "corpus_sha256": _static_corpus_sha256(),
        }

    @staticmethod
    def _run_checked_command(
        command: List[str],
        *,
        cwd: Optional[Path] = None,
        timeout: int,
        label: str,
    ) -> subprocess.CompletedProcess:
        """Run one external command and expose its exact failure."""
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            diagnostic = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
            raise ClientError(f"{label} failed (exit {result.returncode}): {diagnostic}")
        return result

    @staticmethod
    def _parse_checked_command_json(
        result: subprocess.CompletedProcess,
        label: str,
    ) -> Any:
        """Decode one successful command's JSON stdout with its operation label."""
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ClientError(f"{label} returned invalid JSON: {exc}") from exc

    def _existing_static_media_receipt(
        self,
        stage: Dict[str, Any],
        image_path: Path,
    ) -> Optional[Dict[str, Any]]:
        """Recover a prior content-addressed R2 write by exact byte identity."""
        result = self._run_checked_command(
            [
                "cloudflare",
                "r2",
                "objects",
                "list",
                STATIC_MEDIA_BUCKET,
                "--prefix",
                stage["object_key"],
                "--limit",
                "2",
            ],
            timeout=300,
            label="Static media receipt lookup",
        )
        try:
            objects = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ClientError(f"Static media receipt lookup returned invalid JSON: {exc}") from exc
        if not isinstance(objects, list):
            raise ClientError("Static media receipt lookup did not return a JSON array")
        matches = [item for item in objects if item.get("key") == stage["object_key"]]
        if len(matches) > 1:
            raise ClientError("Static media receipt lookup returned duplicate exact keys")
        if not matches:
            return None
        existing = matches[0]
        try:
            size = int(existing["size"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ClientError("Static media receipt has no valid object size") from exc
        etag = str(existing.get("etag") or "").strip('"').lower()
        if size != image_path.stat().st_size or etag != _file_md5(image_path):
            raise ClientError(
                "Existing content-addressed media object does not match local bytes"
            )
        return {"key": stage["object_key"], "recovered": True, "object": existing}

    def _upload_static_media(self, stage: Dict[str, Any]) -> Dict[str, Any]:
        """Upload or recover one content-addressed image in the canonical R2 bucket."""
        image_path = Path(stage["image_path"])
        content_type = mimetypes.guess_type(image_path.name)[0]
        if not content_type:
            raise ClientError(f"Could not determine image content type: {image_path}")
        receipt = self._existing_static_media_receipt(stage, image_path)
        if receipt is None:
            result = self._run_checked_command(
                [
                    "cloudflare",
                    "r2",
                    "objects",
                    "put",
                    STATIC_MEDIA_BUCKET,
                    stage["object_key"],
                    "--file",
                    str(image_path),
                    "--content-type",
                    content_type,
                ],
                timeout=300,
                label="Static media upload",
            )
            try:
                receipt = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise ClientError(f"Static media upload returned invalid JSON: {exc}") from exc
            if not isinstance(receipt, dict):
                raise ClientError("Static media upload did not return a JSON object")
        return {"receipt": receipt, "image_url": stage["image_url"]}

    def _find_inline_static_media_urls(self, markdown_content: str) -> List[Dict[str, str]]:
        """Return every uploads-path URL referenced in a post body, excluding the featured-image path.

        The featured image is uploaded separately by `_upload_static_media` under
        a content-addressed `wp-content/uploads/publisher/{page_id}/...` key.
        Inline content images are referenced in post bodies as plain uploads
        paths, e.g. `https://adamtheautomator.com/wp-content/uploads/2026/09/foo.png`.
        Those are never uploaded by the featured-image path, so this discovers
        every one of them so the caller can mirror it into R2 under the
        identical uploads-path key.
        """
        origin = urlparse(STATIC_SITE_ORIGIN)
        found: Dict[str, str] = {}
        for match in re.finditer(r"https?://[^\s\"'<>()\[\]{},]+", markdown_content):
            parsed = urlparse(match.group(0))
            if parsed.scheme != origin.scheme or parsed.netloc != origin.netloc:
                continue
            if not parsed.path.startswith("/wp-content/uploads/"):
                continue
            if parsed.path.startswith("/wp-content/uploads/publisher/"):
                continue
            key = unquote(parsed.path.lstrip("/"))
            found.setdefault(key, f"{STATIC_SITE_ORIGIN}/{key}")
        return [{"key": key, "url": url} for key, url in sorted(found.items())]

    def _static_media_keys_for_reference(self, key: str) -> List[str]:
        """Return every bucket key belonging to the attachment that owns `key`.

        The mirroring step used to copy only the exact URL a post body
        referenced, so the responsive derivatives generated for each image
        (thumbnail, medium, medium_large, large, 1536x1536, 2048x2048, plus
        this theme's featured-small/featured-large) never reached R2 -- the
        2026-09-05 parity audit measured 112 missing derivative keys across 15
        attachments created since 2026-08-26. The built static site emits those
        variants in `srcset`, so every one of them has to be mirrored at its
        identical wp-content/uploads key.

        The size family is read from the static site's own media inventory,
        `src/data/media_variants.json`, which is the same record the site
        builds its `srcset` from, so it is exactly what the pages reference.

        The reference may itself be a derivative, so an attachment matches
        either by its own path or by declaring this filename among its
        variants.
        """
        inventory = self._static_media_inventory()
        relative = key[len(_STATIC_MEDIA_KEY_PREFIX):]
        filename = relative.rsplit("/", 1)[-1]
        directory = relative.rsplit("/", 1)[0] if "/" in relative else ""
        matches = [
            path
            for path, record in inventory.items()
            if path == relative
            or (
                path.rsplit("/", 1)[0] == directory
                and any(variant[0] == filename for variant in record.get("v", []))
            )
        ]
        if not matches:
            raise ClientError(
                f"No media inventory attachment publishes {key}. The static "
                "mirror cannot enumerate its size variants. An image added "
                "after the inventory was captured has no record yet: see "
                "adbertram/agent-issues#343."
            )
        if len(matches) > 1:
            raise ClientError(
                f"{key} is published by {len(matches)} media inventory attachments"
            )
        attachment = matches[0]
        attachment_directory = attachment.rsplit("/", 1)[0]
        variant_keys = [f"{_STATIC_MEDIA_KEY_PREFIX}{attachment}"] + [
            f"{_STATIC_MEDIA_KEY_PREFIX}{attachment_directory}/{variant[0]}"
            for variant in inventory[attachment].get("v", [])
        ]
        if key not in variant_keys:
            raise ClientError(
                f"Media inventory attachment {attachment!r} matched {key} but "
                "does not declare it among its own variant keys"
            )
        return sorted(dict.fromkeys(variant_keys))

    def _static_media_inventory(self) -> Dict[str, Any]:
        """Load the static site's media inventory once per publisher instance."""
        if self._static_media_inventory_cache is None:
            document = self._load_required_json(
                STATIC_MEDIA_INVENTORY, "static media inventory"
            )
            attachments = document.get("attachments")
            if not isinstance(attachments, dict) or not attachments:
                raise ClientError(
                    f"Static media inventory has no attachments: {STATIC_MEDIA_INVENTORY}"
                )
            self._static_media_inventory_cache = attachments
        return self._static_media_inventory_cache

    @staticmethod
    def _r2_put_subcommand(key: str) -> str:
        """Return the R2 upload subcommand that can represent this key.

        Cloudflare's REST edge WAF answers any object path containing a
        literal '..' with a 403 HTML challenge before R2 sees the request,
        even percent-encoded. Those keys have to go through the R2
        S3-compatible transport instead. Bucket *listing* is unaffected
        because the key travels as a `prefix` query parameter, not as a path
        segment, so `_existing_static_inline_media_key` needs no equivalent.
        """
        return "put-s3" if ".." in key else "put"

    def _existing_static_inline_media_key(self, key: str) -> Optional[Dict[str, Any]]:
        """Return the R2 object for one exact uploads-path key if it already exists, else None.

        Unlike the featured image's content-addressed key, an uploads-path key has
        no local source file to re-derive bytes from, so existence is proven by
        exact key presence in the bucket listing rather than by byte identity.
        """
        result = self._run_checked_command(
            [
                "cloudflare",
                "r2",
                "objects",
                "list",
                STATIC_MEDIA_BUCKET,
                "--prefix",
                key,
                "--limit",
                "2",
            ],
            timeout=300,
            label="Inline static media receipt lookup",
        )
        objects = self._parse_checked_command_json(result, "Inline static media receipt lookup")
        if not isinstance(objects, list):
            raise ClientError("Inline static media receipt lookup did not return a JSON array")
        matches = [item for item in objects if item.get("key") == key]
        if len(matches) > 1:
            raise ClientError("Inline static media receipt lookup returned duplicate exact keys")
        return matches[0] if matches else None

    @staticmethod
    def _fetch_static_origin_bytes(url: str, *, attempts: int = 5) -> Tuple[bytes, Optional[str]]:
        """Download one object from the live site origin, retrying on transient failures.

        Mirrors static-site/scripts/migrate_wp_media.mjs's fetchWithRetry: retry
        with exponential backoff only on a 5xx/429/network error against this
        single site origin; any other HTTP status fails immediately. This
        is a resilience retry against one fixed source, not a fallback to a
        different source.
        """
        last_error: Optional[BaseException] = None
        for attempt in range(1, attempts + 1):
            try:
                request = Request(
                    url, headers={"User-Agent": "ata-static-media-inline-backfill/1.0"}
                )
                with urlopen(request, timeout=60) as response:
                    data = response.read()
                    content_length = response.headers.get("Content-Length")
                    if content_length is not None and int(content_length) != len(data):
                        raise ClientError(
                            f"{url}: Content-Length {content_length} does not match "
                            f"downloaded byte count {len(data)}"
                        )
                    return data, response.headers.get("Content-Type")
            except HTTPError as exc:
                if exc.code < 500 and exc.code != 429:
                    raise ClientError(
                        f"{url}: HTTP {exc.code} fetching inline media from the site origin"
                    ) from exc
                last_error = exc
            except URLError as exc:
                last_error = exc
            if attempt < attempts:
                time.sleep(0.5 * (2 ** (attempt - 1)))
        raise ClientError(
            f"{url}: failed to fetch inline media from the site origin after "
            f"{attempts} attempts: {last_error}"
        )

    def _mirror_static_inline_media_key(self, key: str) -> Dict[str, Any]:
        """Mirror one uploads-path key into R2 and verify it landed.

        Idempotent: an already-present key is recorded as recovered without
        re-downloading or re-uploading anything.
        """
        url = f"{STATIC_SITE_ORIGIN}/{key}"
        existing = self._existing_static_inline_media_key(key)
        if existing is not None:
            return {"key": key, "url": url, "recovered": True, "object": existing}
        data, origin_content_type = self._fetch_static_origin_bytes(url)
        content_type = (
            origin_content_type.split(";")[0].strip()
            if origin_content_type
            else mimetypes.guess_type(key)[0]
        )
        if not content_type:
            raise ClientError(f"Could not determine content type for inline media: {url}")
        handle = tempfile.NamedTemporaryFile(suffix=Path(key).suffix, delete=False)
        try:
            handle.write(data)
            handle.close()
            temp_path = Path(handle.name)
            result = self._run_checked_command(
                [
                    "cloudflare",
                    "r2",
                    "objects",
                    self._r2_put_subcommand(key),
                    STATIC_MEDIA_BUCKET,
                    key,
                    "--file",
                    str(temp_path),
                    "--content-type",
                    content_type,
                ],
                timeout=300,
                label="Inline static media upload",
            )
            receipt = self._parse_checked_command_json(result, "Inline static media upload")
            if not isinstance(receipt, dict):
                raise ClientError("Inline static media upload did not return a JSON object")
        finally:
            Path(handle.name).unlink(missing_ok=True)
        verify = self._existing_static_inline_media_key(key)
        if verify is None or int(verify.get("size", -1)) != len(data):
            raise ClientError(
                f"Inline static media upload for {key} did not verify in R2 after upload"
            )
        return {"key": key, "url": url, "recovered": False, "object": receipt}

    def _upload_static_inline_media(self, markdown_content: str) -> List[Dict[str, Any]]:
        """Mirror every inline uploads-path image referenced in a post body into R2.

        A post body references one URL per image, but each attachment owns a
        family of resized derivatives and the built static site emits those
        variants in `srcset`. So each reference is expanded through the media
        inventory into the attachment's full key family,
        and every key in it is mirrored at its identical wp-content/uploads
        path. Mirroring only the referenced URL is the defect the 2026-09-05
        media parity audit measured as 112 missing derivative keys.

        For each key not already present in the bucket, the bytes are
        downloaded from the live site origin, uploaded to R2 under that
        identical key, then re-verified for presence and byte count before the
        receipt is recorded. Idempotent: a resumed run re-checks bucket
        presence per key and skips anything already uploaded.
        """
        receipts: List[Dict[str, Any]] = []
        mirrored: set = set()
        for reference in self._find_inline_static_media_urls(markdown_content):
            for key in self._static_media_keys_for_reference(reference["key"]):
                if key in mirrored:
                    continue
                mirrored.add(key)
                receipts.append(self._mirror_static_inline_media_key(key))
        return receipts

    @staticmethod
    def _validate_recorded_static_media(runtime: Dict[str, Any]) -> None:
        """Require the persisted receipt before skipping a recorded media effect.

        A record written before inline mirroring existed carries no `inline`
        key at all: that is a pre-`inline` record, not a corrupt one, and the
        media stage completes it with `_migrate_recorded_static_media` before
        the effect is accepted as recorded. An `inline` key that is *present*
        is always held to the receipt contract.
        """
        media = runtime.get("media")
        receipt = media.get("receipt") if isinstance(media, dict) else None
        inline = media.get("inline") if isinstance(media, dict) else None
        inline_is_valid = isinstance(inline, list) and all(
            isinstance(item, dict) and isinstance(item.get("key"), str) and item["key"]
            for item in inline
        )
        if (
            not isinstance(media, dict)
            or not isinstance(receipt, dict)
            or not receipt
            or not isinstance(receipt.get("key"), str)
            or not receipt["key"]
            or receipt["key"] != runtime.get("object_key")
            or media.get("image_url") != runtime.get("image_url")
            or ("inline" in media and not inline_is_valid)
        ):
            raise ClientError("Corrupt publisher runtime: recorded media receipt is invalid")

    @staticmethod
    def _recorded_static_media_predates_inline(runtime: Dict[str, Any]) -> bool:
        """Return whether the recorded media receipt predates inline mirroring.

        Only the featured image was uploaded then, so the record holds its
        receipt and `image_url` and nothing else.
        """
        media = runtime.get("media")
        return isinstance(media, dict) and bool(media) and "inline" not in media

    def _migrate_recorded_static_media(
        self,
        runtime: Dict[str, Any],
        markdown_content: str,
        runtime_path: Path,
    ) -> bool:
        """Complete a pre-`inline` recorded media effect with its inline receipts.

        Such a record cannot prove the post body's images ever reached the
        bucket -- the inline half did not exist when it was written -- so
        accepting the record as-is would publish a page whose inline images
        are missing. The migration re-runs the inline mirroring (idempotent
        per key) and writes the receipts back, leaving the featured image's
        own content-addressed receipt untouched.
        """
        if not self._recorded_static_media_predates_inline(runtime):
            return False
        media = dict(runtime["media"])
        media["inline"] = self._upload_static_inline_media(markdown_content)
        runtime["media"] = media
        _atomic_write_json(runtime_path, runtime)
        return True

    def _recover_static_build(
        self,
        expected_release_ref: Optional[Dict[str, str]],
        staged_corpus_sha256: str,
    ) -> Optional[Dict[str, Any]]:
        """Recover a completed build from its P05 manifest after a hard crash."""
        if not STATIC_RELEASE_MANIFEST.is_file():
            return None
        manifest = self._load_static_release_manifest()
        actual_release_ref = {
            "release_id": manifest["release_id"],
            "contract_hash": manifest["contract_hash"],
        }
        if manifest["inputs"].get("corpus_sha256") != staged_corpus_sha256:
            return None
        if expected_release_ref is not None and actual_release_ref != expected_release_ref:
            return None
        return {
            "build_sha256": _tree_sha256(STATIC_SITE_ROOT / "dist"),
            "manifest": manifest,
            "recovered": True,
        }

    def _run_static_build(
        self,
        expected_release_ref: Optional[Dict[str, str]],
        staged_corpus_sha256: str,
    ) -> Dict[str, Any]:
        """Run or recover the one locked, manifest-producing static build."""
        recovered = self._recover_static_build(
            expected_release_ref,
            staged_corpus_sha256,
        )
        if recovered is not None:
            return recovered
        self._run_checked_command(
            ["npm", "run", "build"],
            cwd=STATIC_SITE_ROOT,
            timeout=1800,
            label="Static site build",
        )
        if not STATIC_RELEASE_MANIFEST.is_file():
            raise ClientError(
                "Static build contract failed: npm run build must regenerate "
                "dist/release-manifest.json"
            )
        manifest = self._load_static_release_manifest()
        actual_release_ref = {
            "release_id": manifest["release_id"],
            "contract_hash": manifest["contract_hash"],
        }
        if expected_release_ref is not None and actual_release_ref != expected_release_ref:
            raise ClientError(
                "Build release identity drifted from the journal: "
                f"expected {expected_release_ref}, got {actual_release_ref}"
            )
        if manifest["inputs"].get("corpus_sha256") != staged_corpus_sha256:
            raise ClientError(
                "Build manifest corpus hash does not match the staged publisher corpus"
            )
        return {
            "build_sha256": _tree_sha256(STATIC_SITE_ROOT / "dist"),
            "manifest": manifest,
            "recovered": False,
        }

    def _bind_static_build_release(
        self,
        *,
        journal: Dict[str, Any],
        runtime: Dict[str, Any],
        build: Dict[str, Any],
        paths: Dict[str, Path],
    ) -> Dict[str, Any]:
        """Bind the first staged build identity, then keep it immutable."""
        manifest = build["manifest"]
        staged_corpus_sha256 = journal["artifacts"]["staged_corpus_sha256"]
        if manifest["inputs"].get("corpus_sha256") != staged_corpus_sha256:
            raise ClientError(
                "Build manifest corpus hash does not match the staged publisher corpus"
            )
        actual_release_ref = {
            "release_id": manifest["release_id"],
            "contract_hash": manifest["contract_hash"],
        }
        unbound_release_ref = {"release_id": None, "contract_hash": None}
        for label, release_ref in (
            ("journal", journal.get("release_ref")),
            ("runtime", runtime.get("release_ref")),
        ):
            if release_ref not in (unbound_release_ref, actual_release_ref):
                raise ClientError(
                    f"Static publisher cannot rebind {label} release identity: "
                    f"expected {release_ref}, got {actual_release_ref}"
                )

        journal["release_ref"] = actual_release_ref
        journal["artifacts"]["build_sha256"] = build["build_sha256"]
        _atomic_write_json(paths["journal"], journal)
        runtime["release_ref"] = actual_release_ref
        runtime["build_sha256"] = build["build_sha256"]
        _atomic_write_json(paths["runtime"], runtime)
        journal["effects"]["builds"] = 1
        _atomic_write_json(paths["journal"], journal)
        return manifest

    @staticmethod
    def _static_preview_receipt_state(
        payload: Dict[str, Any],
        *,
        branch: str,
        commit_hash: str,
        commit_message: str,
    ) -> tuple[str, str]:
        """Return one exact transaction receipt's deployment id and stage status."""
        trigger = payload.get("deployment_trigger")
        metadata = trigger.get("metadata") if isinstance(trigger, dict) else None
        latest_stage = payload.get("latest_stage")
        actual = {
            "environment": payload.get("environment"),
            "branch": metadata.get("branch") if isinstance(metadata, dict) else None,
            "commit_hash": (
                metadata.get("commit_hash") if isinstance(metadata, dict) else None
            ),
            "commit_message": (
                metadata.get("commit_message") if isinstance(metadata, dict) else None
            ),
        }
        expected = {
            "environment": "preview",
            "branch": branch,
            "commit_hash": commit_hash,
            "commit_message": commit_message,
        }
        if actual != expected:
            raise ClientError(
                "Pages preview receipt identity mismatch: "
                f"expected {json.dumps(expected, sort_keys=True)}, "
                f"got {json.dumps(actual, sort_keys=True)}"
            )
        try:
            deployment_id = str(uuid.UUID(str(payload["id"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise ClientError("Pages preview returned no UUID deployment id") from exc
        status = latest_stage.get("status") if isinstance(latest_stage, dict) else None
        valid_statuses = (
            {"success"}
            | STATIC_PAGES_PENDING_STATUSES
            | STATIC_PAGES_TERMINAL_FAILURE_STATUSES
        )
        if status not in valid_statuses:
            raise ClientError(
                "Pages preview returned unsupported latest_stage status: "
                f"{status!r}"
            )
        return deployment_id, status

    @staticmethod
    def _validate_static_preview_identity(
        payload: Dict[str, Any],
        *,
        branch: str,
        commit_hash: str,
        commit_message: str,
    ) -> str:
        """Require the exact successful Pages preview owned by this transaction."""
        deployment_id, status = AtaBlogClient._static_preview_receipt_state(
            payload,
            branch=branch,
            commit_hash=commit_hash,
            commit_message=commit_message,
        )
        if status != "success":
            raise ClientError(
                "Pages preview receipt identity mismatch: "
                f'expected status "success", got {status!r}'
            )
        return deployment_id

    @staticmethod
    def _normalize_static_preview_deployment(
        payload: Dict[str, Any],
        *,
        branch: str,
        commit_hash: str,
        commit_message: str,
    ) -> Dict[str, Any]:
        """Validate one exact successful preview deployment receipt."""
        deployment_id = AtaBlogClient._validate_static_preview_identity(
            payload,
            branch=branch,
            commit_hash=commit_hash,
            commit_message=commit_message,
        )
        short_id = payload.get("short_id")
        if short_id != deployment_id[:8]:
            raise ClientError("Pages preview short_id does not match deployment id")
        deployment_url = payload.get("url")
        parsed_url = urlparse(str(deployment_url))
        if (
            parsed_url.scheme != "https"
            or not parsed_url.hostname
            or parsed_url.hostname.split(".")[0] != short_id
            or parsed_url.path not in ("", "/")
        ):
            raise ClientError("Pages preview returned no HTTPS deployment URL")
        files = payload.get("files")
        if (
            not isinstance(files, dict)
            or not files
            or "/release-manifest.json" not in files
            or any(
                not isinstance(path, str)
                or not path.startswith("/")
                or not re.fullmatch(r"[0-9a-f]{32}", str(digest))
                for path, digest in files.items()
            )
        ):
            raise ClientError(
                "Pages preview returned no valid release-bound deployment files map"
            )
        return {
            "deployment_id": deployment_id,
            "deployment_url": deployment_url.rstrip("/"),
            "deployment": payload,
            "deployment_sha256": _artifact_sha256(payload),
        }

    def _wait_for_static_preview(
        self,
        deployment_id: str,
        *,
        branch: str,
        commit_hash: str,
        commit_message: str,
    ) -> Dict[str, Any]:
        """Hydrate one Pages deployment UUID until it succeeds or fails."""
        deadline = time.monotonic() + STATIC_PAGES_POLL_TIMEOUT_SECONDS
        observed_statuses = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                observed = " -> ".join(observed_statuses) or "none"
                raise ClientError(
                    f"Pages preview deployment {deployment_id} did not reach success "
                    f"within {STATIC_PAGES_POLL_TIMEOUT_SECONDS} seconds; "
                    f"observed statuses: {observed}"
                )
            result = self._run_checked_command(
                [
                    "cloudflare",
                    "pages",
                    "deployments",
                    "get",
                    STATIC_PAGES_PROJECT,
                    deployment_id,
                ],
                timeout=max(1, min(300, int(remaining))),
                label="Pages preview receipt fetch",
            )
            deployment = self._parse_checked_command_json(
                result,
                "Pages preview receipt fetch",
            )
            if not isinstance(deployment, dict):
                raise ClientError(
                    "Pages preview receipt fetch did not return a JSON object"
                )
            received_id, status = self._static_preview_receipt_state(
                deployment,
                branch=branch,
                commit_hash=commit_hash,
                commit_message=commit_message,
            )
            if received_id != deployment_id:
                raise ClientError(
                    "Pages preview receipt deployment id mismatch: "
                    f"expected {deployment_id}, got {received_id}"
                )
            observed_statuses.append(status)
            if status == "success":
                return self._normalize_static_preview_deployment(
                    deployment,
                    branch=branch,
                    commit_hash=commit_hash,
                    commit_message=commit_message,
                )
            if status in STATIC_PAGES_TERMINAL_FAILURE_STATUSES:
                raise ClientError(
                    f"Pages preview deployment {deployment_id} reached terminal "
                    f"status {status}; observed statuses: "
                    f"{' -> '.join(observed_statuses)}"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                continue
            time.sleep(min(STATIC_PAGES_POLL_INTERVAL_SECONDS, remaining))

    def _existing_static_preview(
        self,
        *,
        branch: str,
        commit_hash: str,
        commit_message: str,
    ) -> Optional[Dict[str, Any]]:
        """Recover one Pages preview by its exact transaction identity."""
        result = self._run_checked_command(
            [
                "cloudflare",
                "pages",
                "deployments",
                "list",
                STATIC_PAGES_PROJECT,
                "--env",
                "preview",
                "--limit",
                "100",
            ],
            timeout=300,
            label="Pages preview receipt lookup",
        )
        deployments = self._parse_checked_command_json(
            result,
            "Pages preview receipt lookup",
        )
        if not isinstance(deployments, list):
            raise ClientError("Pages preview receipt lookup did not return a JSON array")
        branch_matches = []
        for deployment in deployments:
            if not isinstance(deployment, dict):
                raise ClientError(
                    "Pages preview receipt lookup returned a non-object deployment"
                )
            trigger = deployment.get("deployment_trigger")
            metadata = trigger.get("metadata") if isinstance(trigger, dict) else None
            if isinstance(metadata, dict) and metadata.get("branch") == branch:
                branch_matches.append(deployment)
        if len(branch_matches) > 1:
            raise ClientError("Multiple Pages previews match the transaction branch")
        if not branch_matches:
            return None
        deployment_id, status = self._static_preview_receipt_state(
            branch_matches[0],
            branch=branch,
            commit_hash=commit_hash,
            commit_message=commit_message,
        )
        if status in STATIC_PAGES_TERMINAL_FAILURE_STATUSES:
            raise ClientError(
                f"Pages preview deployment {deployment_id} reached terminal status "
                f"{status}"
            )
        return self._wait_for_static_preview(
            deployment_id,
            branch=branch,
            commit_hash=commit_hash,
            commit_message=commit_message,
        )

    def _deploy_static_preview(
        self,
        idempotency_key: str,
        source_revision: str,
        release_id: str,
    ) -> Dict[str, Any]:
        """Create or recover the transaction's deterministic Pages preview.

        The branch identity includes the release id so a reseal between
        attempts (which changes the built manifest) gets a fresh deployment
        instead of recovering a stale preview that can never pass readiness.
        """
        branch = f"publisher-{idempotency_key[:16]}-{release_id[-8:]}"
        commit_hash = source_revision[:40]
        commit_message = f"ata-blog publisher {idempotency_key}"
        existing = self._existing_static_preview(
            branch=branch,
            commit_hash=commit_hash,
            commit_message=commit_message,
        )
        if existing is not None:
            return existing
        result = self._run_checked_command(
            [
                "cloudflare",
                "pages",
                "deployments",
                "create",
                STATIC_PAGES_PROJECT,
                "--directory",
                str(STATIC_SITE_ROOT / "dist"),
                "--branch",
                branch,
                "--commit-message",
                commit_message,
                "--commit-hash",
                commit_hash,
            ],
            timeout=1800,
            label="Pages preview upload",
        )
        payload = self._parse_checked_command_json(result, "Pages preview")
        if not isinstance(payload, dict):
            raise ClientError("Pages preview did not return a JSON object")
        deployment_id, status = self._static_preview_receipt_state(
            payload,
            branch=branch,
            commit_hash=commit_hash,
            commit_message=commit_message,
        )
        if status == "success":
            return self._normalize_static_preview_deployment(
                payload,
                branch=branch,
                commit_hash=commit_hash,
                commit_message=commit_message,
            )
        if status in STATIC_PAGES_TERMINAL_FAILURE_STATUSES:
            raise ClientError(
                f"Pages preview deployment {deployment_id} reached terminal status "
                f"{status}"
            )
        return self._wait_for_static_preview(
            deployment_id,
            branch=branch,
            commit_hash=commit_hash,
            commit_message=commit_message,
        )

    def _validate_static_deployment_metadata(
        self,
        deployment: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Confirm a Pages preview receipt's embedded metadata hash is self-consistent."""
        metadata = deployment.get("deployment")
        if not isinstance(metadata, dict):
            raise ClientError("Pages preview receipt has no deployment metadata")
        actual_sha256 = _artifact_sha256(metadata)
        if deployment.get("deployment_sha256") != actual_sha256:
            raise ClientError("Pages preview deployment metadata hash mismatch")
        return metadata

    def _current_production_deployment_id(self) -> str:
        """Read the live production deployment a failed promotion rolls back to."""
        result = self._run_checked_command(
            [
                "cloudflare",
                "pages",
                "deployments",
                "list",
                STATIC_PAGES_PROJECT,
                "--env",
                "production",
                "--limit",
                "1",
            ],
            timeout=300,
            label="Pages production deployment lookup",
        )
        deployments = self._parse_checked_command_json(
            result,
            "Pages production deployment lookup",
        )
        if (
            not isinstance(deployments, list)
            or len(deployments) != 1
            or not isinstance(deployments[0], dict)
        ):
            raise ClientError(
                "Pages production deployment lookup did not return exactly one "
                "deployment"
            )
        current = deployments[0]
        latest_stage = current.get("latest_stage")
        status = latest_stage.get("status") if isinstance(latest_stage, dict) else None
        if current.get("environment") != "production" or status != "success":
            raise ClientError(
                "Current Pages production deployment is not a successful "
                "production deployment"
            )
        try:
            return str(uuid.UUID(str(current["id"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise ClientError(
                "Current Pages production deployment has no UUID id"
            ) from exc

    @staticmethod
    def _static_promotion_receipt_state(
        payload: Dict[str, Any],
        *,
        commit_hash: str,
        commit_message: str,
    ) -> tuple[str, str]:
        """Return one exact production receipt's deployment id and stage status."""
        trigger = payload.get("deployment_trigger")
        metadata = trigger.get("metadata") if isinstance(trigger, dict) else None
        latest_stage = payload.get("latest_stage")
        actual = {
            "environment": payload.get("environment"),
            "commit_hash": (
                metadata.get("commit_hash") if isinstance(metadata, dict) else None
            ),
            "commit_message": (
                metadata.get("commit_message") if isinstance(metadata, dict) else None
            ),
        }
        expected = {
            "environment": "production",
            "commit_hash": commit_hash,
            "commit_message": commit_message,
        }
        if actual != expected:
            raise ClientError(
                "Pages production receipt identity mismatch: "
                f"expected {json.dumps(expected, sort_keys=True)}, "
                f"got {json.dumps(actual, sort_keys=True)}"
            )
        try:
            deployment_id = str(uuid.UUID(str(payload["id"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise ClientError(
                "Pages production promotion returned no UUID deployment id"
            ) from exc
        status = latest_stage.get("status") if isinstance(latest_stage, dict) else None
        valid_statuses = (
            {"success"}
            | STATIC_PAGES_PENDING_STATUSES
            | STATIC_PAGES_TERMINAL_FAILURE_STATUSES
        )
        if status not in valid_statuses:
            raise ClientError(
                "Pages production promotion returned unsupported latest_stage "
                f"status: {status!r}"
            )
        return deployment_id, status

    @staticmethod
    def _normalize_static_promotion_deployment(
        payload: Dict[str, Any],
        *,
        commit_hash: str,
        commit_message: str,
    ) -> Dict[str, Any]:
        """Validate one exact successful production deployment receipt."""
        deployment_id, status = AtaBlogClient._static_promotion_receipt_state(
            payload,
            commit_hash=commit_hash,
            commit_message=commit_message,
        )
        if status != "success":
            raise ClientError(
                "Pages production receipt identity mismatch: "
                f'expected status "success", got {status!r}'
            )
        files = payload.get("files")
        if (
            not isinstance(files, dict)
            or not files
            or "/release-manifest.json" not in files
            or any(
                not isinstance(path, str)
                or not path.startswith("/")
                or not re.fullmatch(r"[0-9a-f]{32}", str(digest))
                for path, digest in files.items()
            )
        ):
            raise ClientError(
                "Pages production promotion returned no valid release-bound "
                "deployment files map"
            )
        return {
            "deployment_id": deployment_id,
            "deployment": payload,
            "deployment_sha256": _artifact_sha256(payload),
        }

    def _wait_for_static_promotion(
        self,
        deployment_id: str,
        *,
        commit_hash: str,
        commit_message: str,
    ) -> Dict[str, Any]:
        """Hydrate one production deployment UUID until it succeeds or fails."""
        deadline = time.monotonic() + STATIC_PAGES_POLL_TIMEOUT_SECONDS
        observed_statuses = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                observed = " -> ".join(observed_statuses) or "none"
                raise ClientError(
                    f"Pages production deployment {deployment_id} did not reach "
                    f"success within {STATIC_PAGES_POLL_TIMEOUT_SECONDS} seconds; "
                    f"observed statuses: {observed}"
                )
            result = self._run_checked_command(
                [
                    "cloudflare",
                    "pages",
                    "deployments",
                    "get",
                    STATIC_PAGES_PROJECT,
                    deployment_id,
                ],
                timeout=max(1, min(300, int(remaining))),
                label="Pages production receipt fetch",
            )
            deployment = self._parse_checked_command_json(
                result,
                "Pages production receipt fetch",
            )
            if not isinstance(deployment, dict):
                raise ClientError(
                    "Pages production receipt fetch did not return a JSON object"
                )
            received_id, status = self._static_promotion_receipt_state(
                deployment,
                commit_hash=commit_hash,
                commit_message=commit_message,
            )
            if received_id != deployment_id:
                raise ClientError(
                    "Pages production receipt deployment id mismatch: "
                    f"expected {deployment_id}, got {received_id}"
                )
            observed_statuses.append(status)
            if status == "success":
                return self._normalize_static_promotion_deployment(
                    deployment,
                    commit_hash=commit_hash,
                    commit_message=commit_message,
                )
            if status in STATIC_PAGES_TERMINAL_FAILURE_STATUSES:
                raise ClientError(
                    f"Pages production deployment {deployment_id} reached terminal "
                    f"status {status}; observed statuses: "
                    f"{' -> '.join(observed_statuses)}"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                continue
            time.sleep(min(STATIC_PAGES_POLL_INTERVAL_SECONDS, remaining))

    def _existing_static_promotion(
        self,
        *,
        commit_hash: str,
        commit_message: str,
    ) -> Optional[Dict[str, Any]]:
        """Recover one production deployment by its exact transaction identity."""
        result = self._run_checked_command(
            [
                "cloudflare",
                "pages",
                "deployments",
                "list",
                STATIC_PAGES_PROJECT,
                "--env",
                "production",
                "--limit",
                "100",
            ],
            timeout=300,
            label="Pages production receipt lookup",
        )
        deployments = self._parse_checked_command_json(
            result,
            "Pages production receipt lookup",
        )
        if not isinstance(deployments, list):
            raise ClientError(
                "Pages production receipt lookup did not return a JSON array"
            )
        matches = []
        for deployment in deployments:
            if not isinstance(deployment, dict):
                raise ClientError(
                    "Pages production receipt lookup returned a non-object deployment"
                )
            trigger = deployment.get("deployment_trigger")
            metadata = trigger.get("metadata") if isinstance(trigger, dict) else None
            if (
                isinstance(metadata, dict)
                and metadata.get("commit_message") == commit_message
            ):
                matches.append(deployment)
        if len(matches) > 1:
            raise ClientError(
                "Multiple Pages production deployments match this transaction"
            )
        if not matches:
            return None
        deployment_id, status = self._static_promotion_receipt_state(
            matches[0],
            commit_hash=commit_hash,
            commit_message=commit_message,
        )
        if status in STATIC_PAGES_TERMINAL_FAILURE_STATUSES:
            raise ClientError(
                f"Pages production deployment {deployment_id} reached terminal "
                f"status {status}"
            )
        if status == "success":
            return self._normalize_static_promotion_deployment(
                matches[0],
                commit_hash=commit_hash,
                commit_message=commit_message,
            )
        return self._wait_for_static_promotion(
            deployment_id,
            commit_hash=commit_hash,
            commit_message=commit_message,
        )

    def _promote_static_release(
        self,
        manifest: Dict[str, Any],
        deployment: Dict[str, Any],
        *,
        journal: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Promote this transaction's build to the production deployment.

        The promotion re-uses the exact dist/ tree the bound preview was
        uploaded from (the global build lock is still held), and is
        recovered rather than repeated when a prior attempt already created
        it.
        """
        idempotency_key = journal["idempotency"]["key"]
        commit_hash = journal["source"]["source_revision"][:40]
        commit_message = f"ata-blog promotion {idempotency_key}"
        promoted = self._existing_static_promotion(
            commit_hash=commit_hash,
            commit_message=commit_message,
        )
        if promoted is None:
            result = self._run_checked_command(
                [
                    "cloudflare",
                    "pages",
                    "deployments",
                    "create",
                    STATIC_PAGES_PROJECT,
                    "--directory",
                    str(STATIC_SITE_ROOT / "dist"),
                    "--commit-message",
                    commit_message,
                    "--commit-hash",
                    commit_hash,
                ],
                timeout=1800,
                label="Pages production promotion",
            )
            payload = self._parse_checked_command_json(
                result,
                "Pages production promotion",
            )
            if not isinstance(payload, dict):
                raise ClientError(
                    "Pages production promotion did not return a JSON object"
                )
            promotion_id, status = self._static_promotion_receipt_state(
                payload,
                commit_hash=commit_hash,
                commit_message=commit_message,
            )
            if status in STATIC_PAGES_TERMINAL_FAILURE_STATUSES:
                raise ClientError(
                    f"Pages production deployment {promotion_id} reached terminal "
                    f"status {status}"
                )
            if status == "success":
                promoted = self._normalize_static_promotion_deployment(
                    payload,
                    commit_hash=commit_hash,
                    commit_message=commit_message,
                )
            else:
                promoted = self._wait_for_static_promotion(
                    promotion_id,
                    commit_hash=commit_hash,
                    commit_message=commit_message,
                )
        return {
            "promotion_id": promoted["deployment_id"],
            "promotion_sha256": promoted["deployment_sha256"],
            "preview_deployment_id": deployment["deployment_id"],
            "release_ref": {
                "release_id": manifest["release_id"],
                "contract_hash": manifest["contract_hash"],
            },
            "custom_domain": STATIC_SITE_ORIGIN,
        }

    def _apply_static_promotion(
        self,
        *,
        manifest: Dict[str, Any],
        deployment: Dict[str, Any],
        journal: Dict[str, Any],
        runtime: Dict[str, Any],
        paths: Dict[str, Path],
    ) -> None:
        """Record and perform this transaction's single production promotion.

        A resumed transaction whose runtime already carries the promotion does
        not create a second production deployment and does not re-read the
        rollback target, so replay stays effect-free.
        """
        if runtime.get("promotion_applied") is True:
            return
        if not runtime.get("prior_production_deployment_id"):
            runtime["prior_production_deployment_id"] = (
                self._current_production_deployment_id()
            )
            _atomic_write_json(paths["runtime"], runtime)
        runtime["promotion"] = self._promote_static_release(
            manifest,
            deployment,
            journal=journal,
        )
        runtime["promotion_applied"] = True
        runtime["promotion_rolled_back"] = False
        _atomic_write_json(paths["runtime"], runtime)

    def _rollback_static_promotion(self, prior_deployment_id: str) -> None:
        """Roll Pages back only when a production promotion was actually recorded."""
        self._run_checked_command(
            [
                "cloudflare",
                "pages",
                "deployments",
                "rollback",
                STATIC_PAGES_PROJECT,
                prior_deployment_id,
                "--force",
            ],
            timeout=1800,
            label="Pages production rollback",
        )

    @staticmethod
    def _journal_evidence(stage: str, value: Any) -> str:
        """Hash one transition's evidence deterministically."""
        return _artifact_sha256({"stage": stage, "value": value})

    def _transition_publisher_journal(
        self,
        journal: Dict[str, Any],
        target: str,
        evidence: Any,
        journal_path: Path,
    ) -> None:
        """Append one legal P05 transition and persist it atomically."""
        source = journal["state"]
        allowed = {
            ("reserved", "staged"),
            ("staged", "built"),
            ("built", "deployed"),
            ("deployed", "notion_updated"),
            ("notion_updated", "completed"),
            ("reserved", "failed"),
            ("staged", "failed"),
            ("built", "failed"),
            ("deployed", "failed"),
            ("notion_updated", "failed"),
            ("failed", "reserved"),
        }
        if (source, target) not in allowed:
            raise ClientError(f"Illegal publisher transition: {source}->{target}")
        journal["events"].append(
            {
                "sequence": len(journal["events"]) + 1,
                "from": source,
                "to": target,
                "evidence_sha256": self._journal_evidence(target, evidence),
            }
        )
        journal["state"] = target
        _atomic_write_json(journal_path, journal)

    def _validate_publisher_journal(
        self,
        journal: Dict[str, Any],
        manifest: Dict[str, Any],
        *,
        expected_page_id: str,
        expected_source_revision: str,
        allow_historical_release_ref: bool = False,
    ) -> None:
        """Fail closed on corruption or stale P05 publisher-journal state."""
        outer = {
            "schema_version", "journal_id", "release_ref", "idempotency",
            "source", "prior_state", "artifacts", "effects", "state", "events",
        }
        nested = {
            "release_ref": {"release_id", "contract_hash"},
            "idempotency": {"key"},
            "source": {"page_id", "source_revision"},
            "prior_state": {"corpus_sha256", "deployment_id", "notion_state_sha256"},
            "artifacts": {"staged_corpus_sha256", "build_sha256", "deployment_id"},
            "effects": {"corpus_writes", "media_upload_sets", "builds", "deployments", "notion_updates"},
        }
        if set(journal) != outer:
            raise ClientError("Corrupt publisher journal: top-level fields do not match P05")
        for field, fields in nested.items():
            if not isinstance(journal.get(field), dict) or set(journal[field]) != fields:
                raise ClientError(f"Corrupt publisher journal: {field} fields do not match P05")
        if journal["schema_version"] != "ata-static-publisher-journal/v1":
            raise ClientError("Corrupt publisher journal: invalid schema_version")
        release_ref = {
            "release_id": manifest["release_id"],
            "contract_hash": manifest["contract_hash"],
        }
        unbound_release_ref = {"release_id": None, "contract_hash": None}
        may_bind_first_build = (
            journal["effects"]["builds"] == 0
            and journal["state"] in {"reserved", "staged", "failed"}
        )
        legacy_unbuilt_failure = _is_failed_unbuilt_publisher_journal(journal)
        historical_release_ref = allow_historical_release_ref and (
            re.fullmatch(
                r"ata-static-[0-9a-f]{24}",
                str(journal["release_ref"]["release_id"]),
            )
            is not None
            and re.fullmatch(
                r"[0-9a-f]{64}",
                str(journal["release_ref"]["contract_hash"]),
            )
            is not None
        )
        if journal["release_ref"] == unbound_release_ref and not may_bind_first_build:
            raise ClientError(
                "Corrupt publisher journal: unbound release_ref after first build"
            )
        if journal["release_ref"] not in (release_ref, unbound_release_ref) and not (
            legacy_unbuilt_failure or historical_release_ref
        ):
            if allow_historical_release_ref:
                raise ClientError("Corrupt publisher journal: invalid historical release_ref")
            raise ClientError("Stale publisher journal: release_ref does not match current manifest")
        source = journal["source"]
        if source != {
            "page_id": expected_page_id,
            "source_revision": expected_source_revision,
        }:
            raise ClientError("Stale publisher journal: source does not match invocation")
        expected_key = self._publisher_idempotency_key(expected_page_id, expected_source_revision)
        if journal["idempotency"]["key"] != expected_key:
            raise ClientError("Corrupt publisher journal: idempotency key mismatch")
        for field in ("corpus_sha256", "notion_state_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", str(journal["prior_state"][field])):
                raise ClientError(f"Corrupt publisher journal: prior_state.{field}")
        for field in ("staged_corpus_sha256", "build_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", str(journal["artifacts"][field])):
                raise ClientError(f"Corrupt publisher journal: artifacts.{field}")
        for field in ("deployment_id",):
            for container in (journal["prior_state"], journal["artifacts"]):
                try:
                    uuid.UUID(str(container[field]))
                except ValueError as exc:
                    raise ClientError(f"Corrupt publisher journal: {field} is not UUID") from exc
        for field, count in journal["effects"].items():
            if count not in (0, 1):
                raise ClientError(f"Corrupt publisher journal: effects.{field} is not 0 or 1")
        effects = journal["effects"]
        if effects["builds"] == 0 and (
            effects["deployments"] != 0 or effects["notion_updates"] != 0
        ):
            raise ClientError(
                "Corrupt publisher journal: downstream effects exist before build"
            )
        if effects["deployments"] == 0 and effects["notion_updates"] != 0:
            raise ClientError(
                "Corrupt publisher journal: Notion effect exists before deployment"
            )
        allowed_states = {
            "reserved", "staged", "built", "deployed",
            "notion_updated", "completed", "failed",
        }
        if journal["state"] not in allowed_states or not isinstance(journal["events"], list):
            raise ClientError("Corrupt publisher journal: invalid state or events")
        transitions = {
            "reserved->staged", "staged->built", "built->deployed",
            "deployed->notion_updated",
            "notion_updated->completed", "reserved->failed", "staged->failed",
            "built->failed", "deployed->failed",
            "notion_updated->failed", "failed->reserved",
        }
        prior_to = None
        for index, event in enumerate(journal["events"], start=1):
            if not isinstance(event, dict) or set(event) != {"sequence", "from", "to", "evidence_sha256"}:
                raise ClientError("Corrupt publisher journal: invalid event fields")
            if event["sequence"] != index:
                raise ClientError("Corrupt publisher journal: non-contiguous event sequence")
            if index == 1:
                if event["from"] is not None or event["to"] != "reserved":
                    raise ClientError("Corrupt publisher journal: first event is not null->reserved")
            else:
                if event["from"] != prior_to or f"{event['from']}->{event['to']}" not in transitions:
                    raise ClientError("Corrupt publisher journal: illegal transition")
            if not re.fullmatch(r"[0-9a-f]{64}", str(event["evidence_sha256"])):
                raise ClientError("Corrupt publisher journal: invalid event evidence hash")
            prior_to = event["to"]
        if not journal["events"] or prior_to != journal["state"]:
            raise ClientError("Corrupt publisher journal: state does not match final event")
        if journal["state"] == "completed" and any(
            count != 1 for count in journal["effects"].values()
        ):
            raise ClientError("Corrupt publisher journal: completed effects are incomplete")

    def _new_publisher_journal(
        self,
        *,
        page_id: str,
        source_revision: str,
        article: Dict[str, Any],
        manifest: Dict[str, Any],
        prior_deployment_id: str,
    ) -> Dict[str, Any]:
        """Create the exact frozen P05 journal document."""
        key = self._publisher_idempotency_key(page_id, source_revision)
        prior_corpus = _static_corpus_sha256()
        release_ref = {"release_id": None, "contract_hash": None}
        reserved_evidence = {
            "idempotency_key": key,
            "prior_corpus_sha256": prior_corpus,
            "prior_deployment_id": prior_deployment_id,
        }
        return {
            "schema_version": "ata-static-publisher-journal/v1",
            "journal_id": f"publish-{page_id}",
            "release_ref": release_ref,
            "idempotency": {"key": key},
            "source": {"page_id": page_id, "source_revision": source_revision},
            "prior_state": {
                "corpus_sha256": prior_corpus,
                "deployment_id": prior_deployment_id,
                "notion_state_sha256": _artifact_sha256(article),
            },
            "artifacts": {
                "staged_corpus_sha256": prior_corpus,
                "build_sha256": EMPTY_SHA256,
                "deployment_id": prior_deployment_id,
            },
            "effects": {
                "corpus_writes": 0,
                "media_upload_sets": 0,
                "builds": 0,
                "deployments": 0,
                "notion_updates": 0,
            },
            "state": "reserved",
            "events": [
                {
                    "sequence": 1,
                    "from": None,
                    "to": "reserved",
                    "evidence_sha256": self._journal_evidence("reserved", reserved_evidence),
                }
            ],
        }

    def _restore_static_corpus(
        self,
        runtime: Dict[str, Any],
        journal: Dict[str, Any],
        paths: Dict[str, Path],
    ) -> None:
        """Restore the exact corpus preimage after a failed transaction."""
        article_path = runtime.get("article_path")
        if not article_path and paths["stage_plan"].is_file():
            plan = self._load_required_json(paths["stage_plan"], "publisher stage plan")
            article_path = plan.get("article_path")
            runtime["article_path"] = article_path
            runtime["created_article"] = plan.get("created_article")
        if not article_path or not paths["backup"].is_file():
            return
        target = Path(article_path)
        backup = paths["backup"].read_bytes()
        if runtime.get("created_article"):
            target.unlink(missing_ok=True)
        else:
            _atomic_write_bytes(target, backup)
        actual = _static_corpus_sha256()
        if actual != journal["prior_state"]["corpus_sha256"]:
            raise ClientError(
                "Corpus rollback hash mismatch: "
                f"expected {journal['prior_state']['corpus_sha256']}, got {actual}"
            )
        journal["effects"]["corpus_writes"] = 0
        runtime["corpus_rolled_back"] = True
        # The backup and stage-plan are a one-shot snapshot of the corpus
        # taken by the FIRST staging call this idempotency key ever made.
        # Once that write is rolled back, the snapshot is spent: a retry's
        # _stage_static_article must re-derive target/original/created from
        # the current filesystem via the live notionPageId/slug lookups,
        # not replay this stale capture. Leaving these files in place after
        # a successful rollback previously caused a real corpus file to be
        # deleted on a later retry: the backup was captured back when an
        # older lookup bug treated an already-staged page as brand new
        # (empty backup, created=True); after that bug was fixed, retries
        # kept trusting the poisoned empty backup instead of the live
        # lookup, so the rollback that followed a later, unrelated failure
        # deleted the real file instead of restoring it. Clearing both
        # files here forces every post-rollback retry to recapture the
        # truth fresh.
        paths["backup"].unlink(missing_ok=True)
        paths["stage_plan"].unlink(missing_ok=True)

    def _publisher_result(
        self,
        journal: Dict[str, Any],
        runtime: Dict[str, Any],
        paths: Dict[str, Path],
        *,
        replayed: bool,
        initial_effects: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """Return the stable public result for a completed transaction."""
        deployment_url = runtime["deployment_url"]
        promoted = runtime.get("promotion_applied") is True
        public_base_url = STATIC_SITE_ORIGIN if promoted else deployment_url
        slug = runtime["slug"]
        baseline = initial_effects or {field: 0 for field in journal["effects"]}
        invocation_effects = {
            field: 0 if replayed else max(0, value - baseline.get(field, 0))
            for field, value in journal["effects"].items()
        }
        return {
            "notion_page_id": journal["source"]["page_id"],
            "status": runtime["status"],
            "static_url": f"{public_base_url}/{slug}/",
            "deployment_id": journal["artifacts"]["deployment_id"],
            "deployment_url": deployment_url,
            "promoted": promoted,
            "release_ref": journal["release_ref"],
            "source_revision": journal["source"]["source_revision"],
            "idempotency_key": journal["idempotency"]["key"],
            "journal_path": str(paths["journal"]),
            "journal_state": journal["state"],
            "replayed": replayed,
            "effects": dict(journal["effects"]),
            "invocation_effects": invocation_effects,
            "warnings": [],
        }

    def _validate_publisher_runtime(
        self,
        runtime: Dict[str, Any],
        *,
        page_id: str,
        source_revision: str,
        idempotency_key: str,
        completed: bool,
    ) -> None:
        """Reject corrupt or stale transaction sidecar state."""
        if runtime.get("schema_version") != "ata-static-publisher-runtime/v1":
            raise ClientError("Corrupt publisher runtime: invalid schema_version")
        expected = {
            "page_id": page_id,
            "source_revision": source_revision,
            "idempotency_key": idempotency_key,
        }
        actual = {key: runtime.get(key) for key in expected}
        if actual != expected:
            raise ClientError("Stale publisher runtime: source identity mismatch")
        deployment = runtime.get("deployment")
        deployment_sha256 = runtime.get("deployment_sha256")
        if deployment is not None or deployment_sha256 is not None:
            if (
                not isinstance(deployment, dict)
                or not re.fullmatch(r"[0-9a-f]{64}", str(deployment_sha256))
                or _artifact_sha256(deployment) != deployment_sha256
            ):
                raise ClientError("Corrupt publisher runtime: deployment metadata mismatch")
        if completed:
            required = (
                "slug",
                "status",
                "deployment_id",
                "deployment_url",
                "deployment",
                "deployment_sha256",
                "publish_date",
            )
            missing = [field for field in required if not runtime.get(field)]
            if missing:
                raise ClientError(
                    "Corrupt completed publisher runtime: missing " + ", ".join(missing)
                )

    @contextmanager
    def _static_build_lock(
        self,
        paths: Dict[str, Path],
        *,
        token_release_ref: Optional[Dict[str, str]] = None,
    ):
        """Hold the global transferable token and the active-profile build lock.

        `token_release_ref` pins the token to one immutable, already-bound
        release (a transaction resuming its own earlier build must keep
        matching that exact release). Pass None when no build is bound yet --
        the check then re-reads the release manifest fresh, right here, while
        the lock is held, instead of trusting a snapshot the caller may have
        read minutes earlier through unrelated Notion/media I/O. That
        snapshot-age gap -- not a real conflicting build -- was the entire
        cause of routine 'Build token release_id is stale' failures: a build
        performed by any transaction now syncs the token in place (see
        _sync_build_token), so the only thing left for a fresh check to catch
        is a genuine anomaly, not the passage of time.
        """
        build_token_path = self._publisher_runtime_root() / "build-token.json"
        if not build_token_path.is_file():
            raise ClientError(f"Required build token is missing: {build_token_path}")
        descriptor = os.open(build_token_path, os.O_RDWR)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ClientError("Global build token is already held") from exc
            with os.fdopen(os.dup(descriptor), "r", encoding="utf-8") as handle:
                try:
                    token = json.load(handle)
                except json.JSONDecodeError as exc:
                    raise ClientError(f"Corrupt build token {build_token_path}: {exc}") from exc
            if not isinstance(token, dict):
                raise ClientError("Invalid build token: expected a JSON object")
            if token.get("holder") != "root-coordinator" or token.get("released_at") is not None:
                raise ClientError("Build token is not currently held by root-coordinator")
            if token_release_ref is not None:
                expected_token_release_ref = token_release_ref
            else:
                current_manifest = self._load_static_release_manifest()
                expected_token_release_ref = {
                    "release_id": current_manifest["release_id"],
                    "contract_hash": current_manifest["contract_hash"],
                }
            if token.get("release_id") != expected_token_release_ref["release_id"]:
                raise ClientError(STATIC_BUILD_TOKEN_RELEASE_ID_STALE)
            if token.get("contract_hash") != expected_token_release_ref["contract_hash"]:
                raise ClientError(STATIC_BUILD_TOKEN_CONTRACT_HASH_STALE)
            if not re.fullmatch(r"[0-9a-f]{64}", str(token.get("build_sha256"))):
                raise ClientError("Build token has no bound build_sha256")
            with self._exclusive_publisher_lock(paths["build_lock"], blocking=False):
                yield _BuildTokenHandle(descriptor, token)
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    @staticmethod
    def _sync_build_token(
        handle: "_BuildTokenHandle",
        build: Dict[str, Any],
        *,
        runtime: Dict[str, Any],
        paths: Dict[str, Path],
    ) -> None:
        """Advance the held token, then the runtime's belief about it, in that order.

        The token is the single authority a fresh publish call trusts for
        'what release is currently valid to build against'. A build performed
        while holding this exact token is, by definition, the new authority --
        so the coordinator that just ran it must record that fact here, in the
        same locked critical section, instead of requiring a human to manually
        re-issue the token before the next publish call can proceed.

        The token write (direct to the locked fd) happens first and is
        immediately durable. Only once it has landed do we persist
        runtime["build_token_release_ref"] to match. A crash between the two
        leaves the runtime believing the token is still whatever it was
        before this call -- which is still true, since the token write above
        is what makes it false -- so a retry's staleness check keeps
        comparing against reality either way instead of a value that raced
        ahead of (or fell behind) the file it describes.
        """
        manifest = build["manifest"]
        release_ref = {
            "release_id": manifest["release_id"],
            "contract_hash": manifest["contract_hash"],
        }
        token = dict(handle.token)
        if (
            token.get("release_id") != release_ref["release_id"]
            or token.get("contract_hash") != release_ref["contract_hash"]
            or token.get("build_sha256") != build["build_sha256"]
        ):
            token["release_id"] = release_ref["release_id"]
            token["contract_hash"] = release_ref["contract_hash"]
            token["build_sha256"] = build["build_sha256"]
            token["release"] = {
                **release_ref,
                "build_sha256": build["build_sha256"],
                "deployment_id": None,
            }
            journal = list(token.get("journal") or [])
            journal.append(
                {
                    "sequence": (journal[-1]["sequence"] + 1) if journal else 1,
                    "event": "release_synced",
                    "holder": "root-coordinator",
                    "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "reason": (
                        "root-coordinator advanced the held token to the release it "
                        "just built, closing the window between reading the prior "
                        "release manifest and acquiring the build lock."
                    ),
                    "release_id": release_ref["release_id"],
                    "contract_hash": release_ref["contract_hash"],
                    "build_sha256": build["build_sha256"],
                }
            )
            token["journal"] = journal
            payload = _canonical_json_bytes(token) + b"\n"
            os.lseek(handle.descriptor, 0, os.SEEK_SET)
            os.write(handle.descriptor, payload)
            os.ftruncate(handle.descriptor, len(payload))
            os.fsync(handle.descriptor)
            handle.token = token
        runtime["build_token_release_ref"] = release_ref
        _atomic_write_json(paths["runtime"], runtime)

    def _load_existing_publisher_journal(
        self,
        path: Path,
        manifest: Dict[str, Any],
        page_id: str,
        source_revision: str,
    ) -> Optional[Dict[str, Any]]:
        """Load and strictly validate an existing same-revision journal."""
        if not path.exists():
            return None
        journal = self._load_required_json(path, "publisher journal")
        self._validate_publisher_journal(
            journal,
            manifest,
            expected_page_id=page_id,
            expected_source_revision=source_revision,
        )
        return journal

    def _reject_competing_publisher_revision(
        self,
        *,
        manifest: Dict[str, Any],
        page_id: str,
        idempotency_key: str,
    ) -> None:
        """Reject a different revision while its page transaction is active."""
        transaction_root = self._publisher_runtime_root() / "transactions"
        if not transaction_root.exists():
            return
        for path in sorted(transaction_root.glob("*.journal.json")):
            if path.name == f"{idempotency_key}.journal.json":
                continue
            document = self._load_required_json(path, "publisher journal")
            source = document.get("source")
            if not isinstance(source, dict) or source.get("page_id") != page_id:
                continue
            revision = source.get("source_revision")
            if not isinstance(revision, str):
                raise ClientError(f"Corrupt competing publisher journal: {path}")
            failed = document.get("state") == "failed"
            self._validate_publisher_journal(
                document,
                manifest,
                expected_page_id=page_id,
                expected_source_revision=revision,
                allow_historical_release_ref=failed,
            )
            if failed:
                key = document["idempotency"]["key"]
                if path.name != f"{key}.journal.json":
                    raise ClientError(f"Corrupt competing publisher journal: {path}")
                runtime_path = path.with_name(f"{key}.runtime.json")
                runtime = self._load_required_json(
                    runtime_path,
                    "competing publisher runtime",
                )
                self._validate_publisher_runtime(
                    runtime,
                    page_id=page_id,
                    source_revision=revision,
                    idempotency_key=key,
                    completed=False,
                )
                effects = document["effects"]
                no_effects = all(count == 0 for count in effects.values())
                rollback_proven = (
                    effects["corpus_writes"] == 0
                    and effects["notion_updates"] == 0
                    and (
                        no_effects
                        or runtime.get("corpus_rolled_back") is True
                    )
                    and runtime.get("rollback_error") in (None, "")
                    and not runtime.get("promotion_applied")
                    and runtime.get("release_ref") == document["release_ref"]
                    and isinstance(runtime.get("failure_stage"), str)
                    and bool(runtime["failure_stage"])
                    and isinstance(runtime.get("failure_message"), str)
                    and bool(runtime["failure_message"])
                )
                if not rollback_proven:
                    raise ClientError(
                        f"Failed competing publisher revision has unproven effects: {path}"
                    )
                if effects["media_upload_sets"] == 1:
                    self._validate_recorded_static_media(runtime)
                if effects["builds"] == 1 and runtime.get("build_sha256") != (
                    document["artifacts"]["build_sha256"]
                ):
                    raise ClientError(
                        f"Failed competing publisher revision has unproven effects: {path}"
                    )
                if effects["deployments"] == 1 and (
                    runtime.get("deployment_id")
                    != document["artifacts"]["deployment_id"]
                    or not isinstance(runtime.get("deployment"), dict)
                    or not runtime.get("deployment_sha256")
                ):
                    raise ClientError(
                        f"Failed competing publisher revision has unproven effects: {path}"
                    )
                continue
            if document["state"] != "completed":
                raise ClientError(
                    "Competing publisher revision is active for page "
                    f"{page_id}: {revision}"
                )

    @staticmethod
    def _notion_publish_state_matches(
        article: Dict[str, Any],
        *,
        published_url: str,
        publish_date: str,
    ) -> bool:
        """Return whether the final Notion mutation already committed."""
        status = article.get("Status")
        if isinstance(status, dict):
            status = status.get("name")
        actual_date = article.get("Publish Date")
        if isinstance(actual_date, dict):
            actual_date = actual_date.get("start")
        return (
            status == "Published"
            and article.get("Published URL") == published_url
            and actual_date == publish_date
        )

    @staticmethod
    def _assert_resume_effects(journal: Dict[str, Any]) -> None:
        """Reject state/effect combinations that cannot arise from the P05 graph."""
        effects = journal["effects"]
        artifacts = journal["artifacts"]
        state = journal["state"]
        requirements = {
            "staged": ("corpus_writes", "media_upload_sets"),
            "built": ("corpus_writes", "media_upload_sets", "builds"),
            "deployed": (
                "corpus_writes", "media_upload_sets", "builds", "deployments",
            ),
            "notion_updated": tuple(effects),
            "completed": tuple(effects),
        }
        if state in requirements and any(effects[field] != 1 for field in requirements[state]):
            raise ClientError(f"Corrupt publisher journal: effects do not support {state}")
        if state in {"deployed", "notion_updated", "completed"}:
            try:
                uuid.UUID(str(artifacts["deployment_id"]))
            except ValueError as exc:
                raise ClientError("Corrupt publisher journal: deployed state has no UUID") from exc

    def _resume_active_static_transaction(
        self,
        *,
        page_id: str,
        article: Dict[str, Any],
        markdown_content: str,
        image_path: Path,
        manifest: Dict[str, Any],
        journal: Dict[str, Any],
        runtime: Dict[str, Any],
        paths: Dict[str, Path],
    ) -> Dict[str, Any]:
        """Resume one legal nonterminal P05 state without repeating receipts."""
        self._assert_resume_effects(journal)
        initial_effects = dict(journal["effects"])
        release_ref = journal["release_ref"]
        unbound_release_ref = {"release_id": None, "contract_hash": None}
        current_stage = "build-lock acquisition"
        try:
            with self._static_build_lock(
                paths,
                token_release_ref=(
                    None
                    if release_ref == unbound_release_ref
                    else runtime["build_token_release_ref"]
                ),
            ) as build_token_handle:
                if journal["state"] == "reserved":
                    if journal["effects"]["corpus_writes"] == 0:
                        current_stage = "staging"
                        stage = self._stage_static_article(
                            page_id=page_id,
                            slug=runtime["slug"],
                            article=article,
                            markdown_content=markdown_content,
                            image_path=image_path,
                            publish_date=runtime["publish_date"],
                            paths=paths,
                        )
                        runtime.update(stage)
                        runtime["corpus_rolled_back"] = False
                        journal["artifacts"]["staged_corpus_sha256"] = stage["corpus_sha256"]
                        journal["effects"]["corpus_writes"] = 1
                        _atomic_write_json(paths["runtime"], runtime)
                        _atomic_write_json(paths["journal"], journal)
                    else:
                        stage = runtime
                    if journal["effects"]["media_upload_sets"] == 0:
                        current_stage = "media"
                        media = self._upload_static_media(stage)
                        media["inline"] = self._upload_static_inline_media(markdown_content)
                        runtime["media"] = media
                        journal["effects"]["media_upload_sets"] = 1
                        _atomic_write_json(paths["runtime"], runtime)
                        _atomic_write_json(paths["journal"], journal)
                    else:
                        current_stage = "media"
                        self._migrate_recorded_static_media(
                            runtime, markdown_content, paths["runtime"]
                        )
                        self._validate_recorded_static_media(runtime)
                    self._transition_publisher_journal(
                        journal,
                        "staged",
                        journal["artifacts"]["staged_corpus_sha256"],
                        paths["journal"],
                    )

                if journal["state"] == "staged":
                    current_stage = "build"
                    if journal["effects"]["builds"] == 0:
                        expected_build_release_ref = (
                            None if release_ref == unbound_release_ref else release_ref
                        )
                        build = self._run_static_build(
                            expected_build_release_ref,
                            journal["artifacts"]["staged_corpus_sha256"],
                        )
                        manifest = self._bind_static_build_release(
                            journal=journal,
                            runtime=runtime,
                            build=build,
                            paths=paths,
                        )
                        self._sync_build_token(
                            build_token_handle, build, runtime=runtime, paths=paths
                        )
                    self._transition_publisher_journal(
                        journal,
                        "built",
                        journal["artifacts"]["build_sha256"],
                        paths["journal"],
                    )

                if journal["state"] == "built":
                    current_stage = "preview upload"
                    if journal["effects"]["deployments"] == 0:
                        deployment = self._deploy_static_preview(
                            journal["idempotency"]["key"],
                            journal["source"]["source_revision"],
                            journal["release_ref"]["release_id"],
                        )
                        runtime.update(deployment)
                        journal["artifacts"]["deployment_id"] = deployment["deployment_id"]
                        journal["effects"]["deployments"] = 1
                        _atomic_write_json(paths["runtime"], runtime)
                        _atomic_write_json(paths["journal"], journal)
                    else:
                        deployment = {
                            "deployment_id": runtime["deployment_id"],
                            "deployment_url": runtime["deployment_url"],
                            "deployment": runtime["deployment"],
                            "deployment_sha256": runtime["deployment_sha256"],
                        }
                    self._validate_static_deployment_metadata(deployment)
                    self._transition_publisher_journal(
                        journal, "deployed", deployment, paths["journal"]
                    )

                deployment = {
                    "deployment_id": runtime["deployment_id"],
                    "deployment_url": runtime["deployment_url"],
                    "deployment": runtime["deployment"],
                    "deployment_sha256": runtime["deployment_sha256"],
                }
                if journal["state"] == "deployed":
                    public_base_url = deployment["deployment_url"]
                    if runtime["status"] == "publish":
                        current_stage = "promotion"
                        self._apply_static_promotion(
                            manifest=manifest,
                            deployment=deployment,
                            journal=journal,
                            runtime=runtime,
                            paths=paths,
                        )
                        public_base_url = STATIC_SITE_ORIGIN
                    current_stage = "Notion update"
                    public_url = f"{public_base_url}/{runtime['slug']}/"
                    if not self._notion_publish_state_matches(
                        article,
                        published_url=public_url,
                        publish_date=runtime["publish_date"],
                    ):
                        self.update_article(
                            page_id,
                            status="Published",
                            properties={
                                "Published URL": public_url,
                                "Publish Date": runtime["publish_date"],
                            },
                        )
                    runtime["published_url"] = public_url
                    journal["effects"]["notion_updates"] = 1
                    _atomic_write_json(paths["runtime"], runtime)
                    _atomic_write_json(paths["journal"], journal)
                    self._transition_publisher_journal(
                        journal,
                        "notion_updated",
                        {"url": public_url, "publish_date": runtime["publish_date"]},
                        paths["journal"],
                    )

                if journal["state"] == "notion_updated":
                    _atomic_write_json(paths["runtime"], runtime)
                    self._transition_publisher_journal(
                        journal, "completed", journal["effects"], paths["journal"]
                    )
                return self._publisher_result(
                    journal,
                    runtime,
                    paths,
                    replayed=False,
                    initial_effects=initial_effects,
                )
        except Exception as exc:
            failure = exc if isinstance(exc, ClientError) else ClientError(str(exc))
            runtime["failure_stage"] = current_stage
            runtime["failure_message"] = str(failure)
            if journal["effects"]["notion_updates"] == 1:
                _atomic_write_json(paths["runtime"], runtime)
                raise ClientError(
                    "Static publisher committed Notion but journal finalization failed; "
                    "rerun the same revision to reconcile"
                ) from failure
            if journal["state"] != "failed":
                self._transition_publisher_journal(
                    journal,
                    "failed",
                    {"stage": current_stage, "message": str(failure)},
                    paths["journal"],
                )
            rollback_errors = []
            if runtime.get("promotion_applied"):
                try:
                    self._rollback_static_promotion(
                        runtime["prior_production_deployment_id"]
                    )
                except Exception as rollback_exc:
                    rollback_errors.append(f"production rollback: {rollback_exc}")
                else:
                    runtime["promotion_applied"] = False
                    runtime["promotion_rolled_back"] = True
            try:
                self._restore_static_corpus(runtime, journal, paths)
            except Exception as rollback_exc:
                rollback_errors.append(f"corpus rollback: {rollback_exc}")
            runtime["rollback_error"] = "; ".join(rollback_errors) or None
            _atomic_write_json(paths["runtime"], runtime)
            _atomic_write_json(paths["journal"], journal)
            if rollback_errors:
                raise ClientError(
                    f"Static publisher failed during {current_stage}: {failure}; "
                    f"rollback failed: {runtime['rollback_error']}"
                ) from failure
            raise ClientError(
                f"Static publisher failed during {current_stage}: {failure}"
            ) from failure

    def _publish_static_transaction(
        self,
        *,
        page_id: str,
        status: str,
        check_duplicates: bool,
        featured_image: Optional[str],
        force: bool,
    ) -> Dict[str, Any]:
        """Serialize source capture and transaction work for one Notion page."""
        with self._exclusive_publisher_lock(self._publisher_page_lock_path(page_id)):
            return self._publish_static_transaction_locked(
                page_id=page_id,
                status=status,
                check_duplicates=check_duplicates,
                featured_image=featured_image,
                force=force,
            )

    def _publish_static_transaction_locked(
        self,
        *,
        page_id: str,
        status: str,
        check_duplicates: bool,
        featured_image: Optional[str],
        force: bool,
    ) -> Dict[str, Any]:
        """Run or resume the single journaled static publication transaction."""
        article = self.get_article(page_id)
        title = str(article.get("Title") or article.get("title") or "Untitled")
        self._require_publish_metadata(article)
        markdown_content = self.get_article_markdown(page_id)
        self._validate_publish_markdown(markdown_content)
        image_path = self._resolve_featured_image(page_id, featured_image)
        source_revision = self._source_revision(article, markdown_content, image_path)
        idempotency_key = self._publisher_idempotency_key(page_id, source_revision)
        paths = self._publisher_paths(page_id, idempotency_key)
        manifest = self._load_static_release_manifest()
        release_ref = {
            "release_id": manifest["release_id"],
            "contract_hash": manifest["contract_hash"],
        }
        unbound_release_ref = {"release_id": None, "contract_hash": None}
        final_slug = self._static_slug(title, self._notion_slug(article, page_id))

        with nullcontext():
            journal = self._load_existing_publisher_journal(
                paths["journal"], manifest, page_id, source_revision
            )
            if journal and journal["state"] == "completed":
                runtime = self._load_required_json(paths["runtime"], "publisher runtime")
                self._validate_publisher_runtime(
                    runtime,
                    page_id=page_id,
                    source_revision=source_revision,
                    idempotency_key=idempotency_key,
                    completed=True,
                )
                return self._publisher_result(journal, runtime, paths, replayed=True)

            self._reject_competing_publisher_revision(
                manifest=manifest,
                page_id=page_id,
                idempotency_key=idempotency_key,
            )
            if journal is None:
                if not force and article.get("Published URL"):
                    raise ClientError(
                        f"Post already published at: {article['Published URL']}. "
                        "Use --force to republish."
                    )
                existing_post = self._find_static_post(final_slug)
                article_url_slug = None
                if article.get("Published URL"):
                    article_url_slug = self._slug_from_url(
                        str(article["Published URL"]), required=False
                    )
                if (
                    check_duplicates
                    and existing_post is not None
                    and article_url_slug != final_slug
                    and not force
                ):
                    raise ClientError(
                        f"Static post with slug '{final_slug}' already exists"
                    )
            if journal is None:
                runtime = {
                    "schema_version": "ata-static-publisher-runtime/v1",
                    "page_id": page_id,
                    "source_revision": source_revision,
                    "idempotency_key": idempotency_key,
                    "slug": final_slug,
                    "status": status,
                    "publish_date": None,
                    "release_ref": unbound_release_ref,
                    "build_token_release_ref": release_ref,
                    "failure_stage": None,
                    "failure_message": None,
                    "rollback_error": None,
                }
            else:
                runtime = self._load_required_json(paths["runtime"], "publisher runtime")
                self._validate_publisher_runtime(
                    runtime,
                    page_id=page_id,
                    source_revision=source_revision,
                    idempotency_key=idempotency_key,
                    completed=False,
                )
                may_bind_first_build = (
                    journal["effects"]["builds"] == 0
                    and journal["state"] in {"reserved", "staged", "failed"}
                )
                journal_release_ref = journal["release_ref"]
                runtime_release_ref = runtime.get("release_ref")
                if may_bind_first_build:
                    first_build_was_journaled = (
                        journal_release_ref != unbound_release_ref
                        and journal["artifacts"]["build_sha256"] != EMPTY_SHA256
                    )
                    failed_unbuilt_candidate = (
                        _is_failed_unbuilt_publisher_journal(journal)
                        and journal["events"][-1]["from"] == "staged"
                        and journal["events"][-1]["to"] == "failed"
                        and journal["effects"]["media_upload_sets"] == 1
                        and (
                            runtime.get("failure_stage") == "build"
                            or (
                                runtime.get("failure_stage")
                                == "build-lock acquisition"
                                and runtime.get("failure_message")
                                in STATIC_BUILD_TOKEN_IDENTITY_ERRORS
                            )
                        )
                        and runtime.get("corpus_rolled_back") is True
                        and runtime.get("rollback_error") in (None, "")
                        and not runtime.get("build_sha256")
                        and runtime.get("corpus_sha256")
                        == journal["artifacts"]["staged_corpus_sha256"]
                        and runtime_release_ref == journal_release_ref
                    )
                    if failed_unbuilt_candidate:
                        self._validate_recorded_static_media(runtime)
                        current_prior_corpus = _static_corpus_sha256()
                        legacy_prior_corpus = _tree_sha256(
                            STATIC_SITE_ROOT / "src" / "data" / "posts"
                        )
                        recorded_prior_corpus = journal["prior_state"]["corpus_sha256"]
                        if recorded_prior_corpus == legacy_prior_corpus:
                            journal["prior_state"][
                                "corpus_sha256"
                            ] = current_prior_corpus
                            journal["artifacts"][
                                "staged_corpus_sha256"
                            ] = current_prior_corpus
                            runtime["corpus_sha256"] = current_prior_corpus
                            _atomic_write_json(paths["journal"], journal)
                            _atomic_write_json(paths["runtime"], runtime)
                        elif recorded_prior_corpus != current_prior_corpus:
                            raise ClientError(
                                "Stale publisher journal: rolled-back corpus hash mismatch"
                            )
                    if journal_release_ref == unbound_release_ref:
                        if runtime_release_ref != unbound_release_ref:
                            raise ClientError(
                                "Stale publisher runtime: release_ref mismatch"
                            )
                        if failed_unbuilt_candidate:
                            runtime["build_token_release_ref"] = release_ref
                            _atomic_write_json(paths["runtime"], runtime)
                    elif first_build_was_journaled:
                        if runtime_release_ref not in (
                            journal_release_ref,
                            unbound_release_ref,
                        ):
                            raise ClientError(
                                "Stale publisher runtime: release_ref mismatch"
                            )
                    elif failed_unbuilt_candidate:
                        journal["release_ref"] = unbound_release_ref
                        runtime["release_ref"] = unbound_release_ref
                        runtime["build_token_release_ref"] = release_ref
                        _atomic_write_json(paths["journal"], journal)
                        _atomic_write_json(paths["runtime"], runtime)
                    else:
                        raise ClientError(
                            "Corrupt publisher transaction: unproven first-build binding"
                        )
                    token_release_ref = runtime.get("build_token_release_ref")
                    if token_release_ref is None:
                        token_release_ref = release_ref
                    runtime["build_token_release_ref"] = token_release_ref
                    _atomic_write_json(paths["runtime"], runtime)
                elif runtime_release_ref != journal["release_ref"]:
                    raise ClientError("Stale publisher runtime: release_ref mismatch")
                elif runtime.get("build_token_release_ref") is None:
                    runtime["build_token_release_ref"] = release_ref
                    _atomic_write_json(paths["runtime"], runtime)
                token_release_ref = runtime.get("build_token_release_ref")
                if (
                    not isinstance(token_release_ref, dict)
                    or set(token_release_ref) != {"release_id", "contract_hash"}
                    or not isinstance(token_release_ref["release_id"], str)
                    or not token_release_ref["release_id"]
                    or not re.fullmatch(
                        r"[0-9a-f]{64}",
                        str(token_release_ref["contract_hash"]),
                    )
                ):
                    raise ClientError(
                        "Corrupt publisher runtime: invalid build_token_release_ref"
                    )
                if runtime.get("slug") != final_slug or runtime.get("status") != status:
                    raise ClientError("Retry options do not match the existing publisher runtime")
                if journal["state"] != "failed":
                    return self._resume_active_static_transaction(
                        page_id=page_id,
                        article=article,
                        markdown_content=markdown_content,
                        image_path=image_path,
                        manifest=manifest,
                        journal=journal,
                        runtime=runtime,
                        paths=paths,
                    )

            current_stage = "build-lock acquisition"
            try:
                with self._static_build_lock(
                    paths,
                    token_release_ref=(
                        None
                        if journal is None or journal["release_ref"] == unbound_release_ref
                        else runtime["build_token_release_ref"]
                    ),
                ) as build_token_handle:
                    if journal is None:
                        current_stage = "transaction reservation"
                        prior_deployment_id = EMPTY_UUID
                        journal = self._new_publisher_journal(
                            page_id=page_id,
                            source_revision=source_revision,
                            article=article,
                            manifest=manifest,
                            prior_deployment_id=prior_deployment_id,
                        )
                        _atomic_write_json(paths["journal"], journal)
                        runtime["publish_date"] = (
                            datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                        )
                        _atomic_write_json(paths["runtime"], runtime)
                    else:
                        self._transition_publisher_journal(
                            journal,
                            "reserved",
                            {"retry": True, "failure_stage": runtime.get("failure_stage")},
                            paths["journal"],
                        )
                    if journal["effects"]["corpus_writes"] == 0:
                        current_stage = "staging"
                        stage = self._stage_static_article(
                            page_id=page_id,
                            slug=final_slug,
                            article=article,
                            markdown_content=markdown_content,
                            image_path=image_path,
                            publish_date=runtime["publish_date"],
                            paths=paths,
                        )
                        runtime.update(stage)
                        runtime["corpus_rolled_back"] = False
                        journal["artifacts"]["staged_corpus_sha256"] = stage["corpus_sha256"]
                        journal["effects"]["corpus_writes"] = 1
                        _atomic_write_json(paths["runtime"], runtime)
                        _atomic_write_json(paths["journal"], journal)
                    else:
                        stage = runtime

                    if journal["effects"]["media_upload_sets"] == 0:
                        current_stage = "media"
                        media = self._upload_static_media(stage)
                        media["inline"] = self._upload_static_inline_media(markdown_content)
                        runtime["media"] = media
                        journal["effects"]["media_upload_sets"] = 1
                        _atomic_write_json(paths["runtime"], runtime)
                        _atomic_write_json(paths["journal"], journal)
                    else:
                        current_stage = "media"
                        self._migrate_recorded_static_media(
                            runtime, markdown_content, paths["runtime"]
                        )
                        self._validate_recorded_static_media(runtime)
                    self._transition_publisher_journal(
                        journal,
                        "staged",
                        {
                            "corpus_sha256": journal["artifacts"]["staged_corpus_sha256"],
                            "media_upload_sets": journal["effects"]["media_upload_sets"],
                        },
                        paths["journal"],
                    )

                    if journal["effects"]["builds"] == 0:
                        current_stage = "build"
                        expected_build_release_ref = (
                            None
                            if journal["release_ref"] == unbound_release_ref
                            else journal["release_ref"]
                        )
                        build = self._run_static_build(
                            expected_build_release_ref,
                            journal["artifacts"]["staged_corpus_sha256"],
                        )
                        manifest = self._bind_static_build_release(
                            journal=journal,
                            runtime=runtime,
                            build=build,
                            paths=paths,
                        )
                        self._sync_build_token(
                            build_token_handle, build, runtime=runtime, paths=paths
                        )
                    self._transition_publisher_journal(
                        journal,
                        "built",
                        journal["artifacts"]["build_sha256"],
                        paths["journal"],
                    )

                    if journal["effects"]["deployments"] == 0:
                        current_stage = "preview upload"
                        deployment = self._deploy_static_preview(
                            idempotency_key,
                            source_revision,
                            journal["release_ref"]["release_id"],
                        )
                        runtime.update(deployment)
                        journal["artifacts"]["deployment_id"] = deployment["deployment_id"]
                        journal["effects"]["deployments"] = 1
                        _atomic_write_json(paths["runtime"], runtime)
                        _atomic_write_json(paths["journal"], journal)
                    else:
                        deployment = {
                            "deployment_id": runtime["deployment_id"],
                            "deployment_url": runtime["deployment_url"],
                            "deployment": runtime["deployment"],
                            "deployment_sha256": runtime["deployment_sha256"],
                        }
                    self._validate_static_deployment_metadata(deployment)
                    self._transition_publisher_journal(
                        journal,
                        "deployed",
                        deployment,
                        paths["journal"],
                    )

                    public_base_url = deployment["deployment_url"]
                    if status == "publish":
                        current_stage = "promotion"
                        self._apply_static_promotion(
                            manifest=manifest,
                            deployment=deployment,
                            journal=journal,
                            runtime=runtime,
                            paths=paths,
                        )
                        public_base_url = STATIC_SITE_ORIGIN

                    current_stage = "Notion update"
                    public_url = f"{public_base_url}/{final_slug}/"
                    self.update_article(
                        page_id,
                        status="Published",
                        properties={
                            "Published URL": public_url,
                            "Publish Date": runtime["publish_date"],
                        },
                    )
                    runtime["published_url"] = public_url
                    journal["effects"]["notion_updates"] = 1
                    _atomic_write_json(paths["runtime"], runtime)
                    _atomic_write_json(paths["journal"], journal)
                    self._transition_publisher_journal(
                        journal,
                        "notion_updated",
                        {
                            "url": public_url,
                            "publish_date": runtime["publish_date"],
                        },
                        paths["journal"],
                    )
                    _atomic_write_json(paths["runtime"], runtime)
                    self._transition_publisher_journal(
                        journal,
                        "completed",
                        journal["effects"],
                        paths["journal"],
                    )
                    return self._publisher_result(journal, runtime, paths, replayed=False)
            except Exception as exc:
                failure = exc if isinstance(exc, ClientError) else ClientError(str(exc))
                if journal is None:
                    raise ClientError(
                        f"Static publisher failed during {current_stage}: {failure}"
                    ) from failure
                runtime["failure_stage"] = current_stage
                runtime["failure_message"] = str(failure)
                if journal["effects"]["notion_updates"] == 1:
                    _atomic_write_json(paths["runtime"], runtime)
                    raise ClientError(
                        "Static publisher committed Notion but journal finalization failed; "
                        "rerun the same revision to reconcile"
                    ) from failure
                if journal["state"] != "failed":
                    self._transition_publisher_journal(
                        journal,
                        "failed",
                        {"stage": current_stage, "message": str(failure)},
                        paths["journal"],
                    )
                rollback_errors = []
                if runtime.get("promotion_applied"):
                    try:
                        self._rollback_static_promotion(
                            runtime["prior_production_deployment_id"]
                        )
                    except Exception as rollback_exc:
                        rollback_errors.append(f"production rollback: {rollback_exc}")
                    else:
                        runtime["promotion_applied"] = False
                        runtime["promotion_rolled_back"] = True
                try:
                    self._restore_static_corpus(runtime, journal, paths)
                except Exception as rollback_exc:
                    rollback_errors.append(f"corpus rollback: {rollback_exc}")
                if rollback_errors:
                    runtime["rollback_error"] = "; ".join(rollback_errors)
                _atomic_write_json(paths["runtime"], runtime)
                _atomic_write_json(paths["journal"], journal)
                if rollback_errors:
                    raise ClientError(
                        f"Static publisher failed during {current_stage}: {failure}; "
                        f"rollback failed: {runtime['rollback_error']}"
                    ) from failure
                raise ClientError(
                    f"Static publisher failed during {current_stage}: {failure}"
                ) from failure

    def _preview_static_transaction(
        self,
        *,
        page_id: str,
        check_duplicates: bool,
        featured_image: Optional[str],
        force: bool,
    ) -> Dict[str, Any]:
        """Deploy a hosted Pages preview without publishing or mutating Notion."""
        with self._exclusive_publisher_lock(self._publisher_page_lock_path(page_id)):
            return self._preview_static_transaction_locked(
                page_id=page_id,
                check_duplicates=check_duplicates,
                featured_image=featured_image,
                force=force,
            )

    def _preview_static_transaction_locked(
        self,
        *,
        page_id: str,
        check_duplicates: bool,
        featured_image: Optional[str],
        force: bool,
    ) -> Dict[str, Any]:
        """Build and deploy one reversible Cloudflare Pages preview.

        The source post is staged into the static corpus only while the global
        build token is held. After the preview deployment succeeds (or fails),
        the exact corpus preimage is restored and the restored corpus is built
        again before the lock is released. No Notion property is written.
        """
        article = self.get_article(page_id)
        title = str(article.get("Title") or article.get("title") or "Untitled")
        self._require_publish_metadata(article)
        markdown_content = self.get_article_markdown(page_id)
        self._validate_publish_markdown(markdown_content)
        image_path = self._resolve_featured_image(page_id, featured_image)
        source_revision = self._source_revision(article, markdown_content, image_path)
        idempotency_key = self._publisher_idempotency_key(page_id, source_revision)
        paths = self._publisher_preview_paths(page_id, idempotency_key)
        paths["runtime"].parent.mkdir(parents=True, exist_ok=True)
        final_slug = self._static_slug(title, self._notion_slug(article, page_id))

        manifest = self._load_static_release_manifest()
        self._reject_competing_publisher_revision(
            manifest=manifest,
            page_id=page_id,
            idempotency_key=idempotency_key,
        )
        publisher_paths = self._publisher_paths(page_id, idempotency_key)
        if publisher_paths["journal"].is_file():
            current_journal = self._load_existing_publisher_journal(
                publisher_paths["journal"],
                manifest,
                page_id,
                source_revision,
            )
            if current_journal is not None and current_journal["state"] != "completed":
                raise ClientError(
                    "Cannot deploy preview while the same-revision publisher "
                    "transaction is incomplete"
                )

        if not force and article.get("Published URL"):
            raise ClientError(
                f"Post already published at: {article['Published URL']}. "
                "Use --force to preview the current source anyway."
            )
        existing_post = self._find_static_post(final_slug)
        article_url_slug = None
        if article.get("Published URL"):
            article_url_slug = self._slug_from_url(
                str(article["Published URL"]), required=False
            )
        if (
            check_duplicates
            and existing_post is not None
            and article_url_slug != final_slug
            and not force
        ):
            raise ClientError(f"Static post with slug '{final_slug}' already exists")

        prior_corpus_sha256 = _static_corpus_sha256()
        runtime = {
            "schema_version": "ata-static-preview-runtime/v1",
            "page_id": page_id,
            "source_revision": source_revision,
            "idempotency_key": idempotency_key,
            "slug": final_slug,
            "status": "preview",
            "publish_date": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "failure_stage": None,
            "failure_message": None,
            "rollback_error": None,
            "corpus_restored": False,
        }
        rollback_state = {
            "prior_state": {"corpus_sha256": prior_corpus_sha256},
            "effects": {"corpus_writes": 0},
        }
        _atomic_write_json(paths["runtime"], runtime)

        current_stage = "build-lock acquisition"
        failure: Optional[ClientError] = None
        cleanup_errors: List[str] = []
        deployment: Optional[Dict[str, Any]] = None
        preview_release_ref: Optional[Dict[str, str]] = None
        staging_attempted = False

        try:
            with self._static_build_lock(paths, token_release_ref=None) as build_token_handle:
                try:
                    current_stage = "staging"
                    staging_attempted = True
                    stage = self._stage_static_article(
                        page_id=page_id,
                        slug=final_slug,
                        article=article,
                        markdown_content=markdown_content,
                        image_path=image_path,
                        publish_date=runtime["publish_date"],
                        paths=paths,
                    )
                    rollback_state["effects"]["corpus_writes"] = 1
                    runtime.update(stage)
                    _atomic_write_json(paths["runtime"], runtime)

                    current_stage = "media"
                    media = self._upload_static_media(stage)
                    media["inline"] = self._upload_static_inline_media(markdown_content)
                    runtime["media"] = media
                    _atomic_write_json(paths["runtime"], runtime)

                    current_stage = "build"
                    build = self._run_static_build(None, stage["corpus_sha256"])
                    preview_release_ref = {
                        "release_id": build["manifest"]["release_id"],
                        "contract_hash": build["manifest"]["contract_hash"],
                    }
                    runtime["preview_release_ref"] = preview_release_ref
                    runtime["preview_build_sha256"] = build["build_sha256"]
                    self._sync_build_token(
                        build_token_handle,
                        build,
                        runtime=runtime,
                        paths=paths,
                    )

                    current_stage = "preview upload"
                    deployment = self._deploy_static_preview(
                        idempotency_key,
                        source_revision,
                        preview_release_ref["release_id"],
                    )
                    self._validate_static_deployment_metadata(deployment)
                    runtime.update(deployment)
                    _atomic_write_json(paths["runtime"], runtime)
                except Exception as exc:
                    failure = exc if isinstance(exc, ClientError) else ClientError(str(exc))
                    runtime["failure_stage"] = current_stage
                    runtime["failure_message"] = str(failure)
                    _atomic_write_json(paths["runtime"], runtime)
                finally:
                    if staging_attempted:
                        try:
                            current_stage = "corpus restore"
                            self._restore_static_corpus(runtime, rollback_state, paths)
                            actual_corpus_sha256 = _static_corpus_sha256()
                            if actual_corpus_sha256 != prior_corpus_sha256:
                                raise ClientError(
                                    "Preview corpus restore hash mismatch: "
                                    f"expected {prior_corpus_sha256}, got {actual_corpus_sha256}"
                                )
                            runtime["corpus_restored"] = True
                            _atomic_write_json(paths["runtime"], runtime)
                        except Exception as exc:
                            cleanup_errors.append(f"corpus restore: {exc}")

                        if runtime.get("corpus_restored") is True:
                            try:
                                current_stage = "restored corpus build"
                                restored_build = self._run_static_build(
                                    None,
                                    prior_corpus_sha256,
                                )
                                runtime["restored_release_ref"] = {
                                    "release_id": restored_build["manifest"]["release_id"],
                                    "contract_hash": restored_build["manifest"]["contract_hash"],
                                }
                                runtime["restored_build_sha256"] = restored_build[
                                    "build_sha256"
                                ]
                                self._sync_build_token(
                                    build_token_handle,
                                    restored_build,
                                    runtime=runtime,
                                    paths=paths,
                                )
                                _atomic_write_json(paths["runtime"], runtime)
                            except Exception as exc:
                                cleanup_errors.append(f"restored corpus build: {exc}")
        except Exception as exc:
            if failure is None:
                failure = exc if isinstance(exc, ClientError) else ClientError(str(exc))

        if cleanup_errors:
            runtime["rollback_error"] = "; ".join(cleanup_errors)
            _atomic_write_json(paths["runtime"], runtime)
            if failure is not None:
                raise ClientError(
                    f"Static preview failed during {runtime.get('failure_stage') or current_stage}: "
                    f"{failure}; preview cleanup failed: {runtime['rollback_error']}"
                ) from failure
            raise ClientError(
                "Static preview deployed but cleanup failed: "
                f"{runtime['rollback_error']}"
            )

        if failure is not None:
            raise ClientError(
                f"Static preview failed during {runtime.get('failure_stage') or current_stage}: "
                f"{failure}"
            ) from failure
        if deployment is None or preview_release_ref is None:
            raise ClientError("Static preview completed without a deployment receipt")

        preview_url = f"{deployment['deployment_url']}/{final_slug}/"
        runtime["preview_url"] = preview_url
        runtime["completed_at"] = (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        )
        _atomic_write_json(paths["runtime"], runtime)
        return {
            "notion_page_id": page_id,
            "status": "preview",
            "preview_url": preview_url,
            "static_url": preview_url,
            "deployment_id": deployment["deployment_id"],
            "deployment_url": deployment["deployment_url"],
            "promoted": False,
            "release_ref": preview_release_ref,
            "source_revision": source_revision,
            "idempotency_key": idempotency_key,
            "notion_updated": False,
            "corpus_restored": True,
            "warnings": [],
        }

    def _schedule_article(
        self,
        *,
        page_id: str,
        status: str,
        date: Optional[str],
        auto_schedule: bool,
        check_duplicates: bool,
        schedule_window: Optional[Tuple[datetime, datetime]],
    ) -> Dict[str, Any]:
        """Validate a post, then write Status=Scheduled and its Publish Date.

        Nothing is staged, uploaded, built, deployed, or journaled here: the
        due publisher's `--status publish` run does all of that later, without
        flags, so every gate it cannot satisfy itself is enforced now.
        """
        if date is not None and auto_schedule:
            raise ClientError("Use either --date or --auto-schedule, not both")
        if status in {"publish", "preview"}:
            raise ClientError(
                f"--status {status} cannot be combined with --date or --auto-schedule: "
                "scheduling never deploys or promotes"
            )
        if date is not None:
            self._parse_schedule_date(date)

        # One lock across page read -> read-slots -> pick -> Notion write. The
        # Scheduled page is the durable record of both facts a second scheduler
        # needs: this page is no longer Ready to Publish, and its slot is taken.
        with self._exclusive_publisher_lock(self._schedule_lock_path()):
            article = self.get_article(page_id)
            if article.get("Status") != "Ready to Publish":
                raise ClientError(
                    f"Notion page {page_id} must be 'Ready to Publish' to be scheduled; "
                    f"current status is '{article.get('Status')}'"
                )
            if not article.get("Title"):
                raise ClientError(f"Notion page {page_id} has no Title")
            self._require_publish_metadata(article)
            self._validate_publish_markdown(self.get_article_markdown(page_id))
            self._resolve_featured_image(page_id, None)
            self._resolve_static_term_ids(
                "categories", self._notion_term_names(article, "Category")
            )
            self._resolve_static_term_ids("tags", self._notion_term_names(article, "Tags"))
            self._sponsored_tag_ids(article, page_id)
            final_slug = self._static_slug(
                str(article["Title"]), self._notion_slug(article, page_id)
            )
            if check_duplicates and self._find_static_post(final_slug) is not None:
                raise ClientError(f"Static post with slug '{final_slug}' already exists")
            if auto_schedule:
                slot = self.find_next_schedule_slot(schedule_window)
            else:
                slot = self._require_free_explicit_slot(date, schedule_window)
            self.update_article(page_id, status="Scheduled", properties={"Publish Date": slot})
        return {
            "notion_page_id": page_id,
            "status": "Scheduled",
            "scheduled_date": slot,
            "slug": final_slug,
        }

    def publish_article(
        self,
        page_id: str,
        status: str = "draft",
        date: Optional[str] = None,
        auto_schedule: bool = False,
        check_duplicates: bool = True,
        featured_image: Optional[str] = None,
        force: bool = False,
        schedule_after: Optional[str] = None,
        schedule_before: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Schedule a Notion article, or publish it to the static site.

        With date or auto_schedule this only schedules: it validates the post
        and sets Status=Scheduled plus Publish Date. status="preview" stages,
        builds, and deploys a hosted Cloudflare Pages preview, then restores
        the local corpus without writing Notion. The remaining static path
        preserves the existing draft/publish transaction behavior; publish
        additionally promotes the candidate to production.
        The URL slug is the page's Notion `Slug`, or derived from its title
        when that property is empty.

        Args:
            page_id: Notion page ID
            status: draft, preview, or publish
            date: Schedule-only: explicit slot (ISO 8601 with a UTC offset)
            auto_schedule: Schedule-only: pick the next available slot
            check_duplicates: If True, error if slug already exists
            featured_image: Optional path to featured image file to upload and attach
            force: If True, skip the already-published check
            schedule_after: Inclusive bound for the scheduled slot
            schedule_before: Exclusive bound for the scheduled slot

        Returns the schedule result (status "Scheduled", scheduled_date, slug)
        or the static transaction result dict (static_url, deployment_id,
        promoted, journal state, effects).
        """
        if status not in {"draft", "preview", "publish"}:
            raise ClientError(
                "Static publish status must be draft, preview, or publish"
            )
        schedule_window = self._parse_schedule_window(schedule_after, schedule_before)
        # An empty --date (an unset shell variable) is still a schedule request:
        # it must fail as a bad date, never fall through to a promotion.
        if date is not None or auto_schedule:
            if featured_image:
                raise ClientError(
                    "--featured-image cannot be used when scheduling: the due publisher "
                    "runs without flags and reads posts/<page-id>/featured_image.*"
                )
            return self._schedule_article(
                page_id=page_id,
                status=status,
                date=date,
                auto_schedule=auto_schedule,
                check_duplicates=check_duplicates,
                schedule_window=schedule_window,
            )
        if schedule_window is not None:
            raise ClientError(
                "--schedule-after/--schedule-before require --auto-schedule or --date"
            )
        if status == "preview":
            return self._preview_static_transaction(
                page_id=page_id,
                check_duplicates=check_duplicates,
                featured_image=featured_image,
                force=force,
            )
        return self._publish_static_transaction(
            page_id=page_id,
            status=status,
            check_duplicates=check_duplicates,
            featured_image=featured_image,
            force=force,
        )

    @staticmethod
    def _slug_from_url(url: str, required: bool = True) -> Optional[str]:
        """Derive a post slug from a post URL.

        Handles trailing slashes and query/fragment suffixes. Raises if the
        URL has no usable path segment, unless required=False -- callers that
        only compare slugs pass required=False to get None instead of an
        error.
        """
        path = urlparse(url).path.strip("/")
        if not path:
            if required:
                raise ClientError(f"Cannot derive a slug from URL: {url!r}")
            return None
        # The slug is the last non-empty path segment.
        return path.split("/")[-1]

    @staticmethod
    def detect_id_kind(identifier: str) -> str:
        """Classify an unpublish target identifier.

        Returns one of: "notion_page", "url", "slug". Detection is
        deterministic and fails fast for empty input.
        """
        value = identifier.strip()
        if not value:
            raise ClientError("Target identifier must not be empty")

        if value.lower().startswith(("http://", "https://")):
            return "url"

        # 32-hex Notion page ID, dashed or undashed.
        compact = value.replace("-", "")
        if len(compact) == 32 and re.fullmatch(r"[0-9a-fA-F]{32}", compact):
            return "notion_page"

        # Everything else is treated as a static post slug.
        return "slug"

    @staticmethod
    def _compact_page_id(page_id: str) -> str:
        """Return the undashed lowercase page id the static corpus records."""
        return page_id.replace("-", "").lower()

    def _notion_page_by_published_url(self, url: str) -> Optional[Dict[str, Any]]:
        """Return the ATA Notion page whose Published URL matches, or None."""
        result = self._run_notion(
            [
                "database", "page", "list",
                "-d", self.config.notion_database_id,
                "--filter", f"Published URL:eq:{url}",
                "--limit", "2",
            ]
        )
        pages = _loads_notion_text_json(result.stdout)
        if not pages:
            return None
        return pages[0]

    def resolve_unpublish_target(self, identifier: str) -> Dict[str, Any]:
        """Resolve an identifier to both the Notion page and the static post.

        Returns a dict:
            {
              "id_kind": "...",
              "notion_page": <article dict>,   # required, always resolved
              "static_post": <Path> | None,    # None if absent from the corpus
              "slug": <str> | None,
            }

        Fails fast (ClientError) when the Notion page cannot be resolved. A
        Notion page with no corpus record resolves its static post as None
        (already absent), so the Notion reset can still proceed.
        """
        kind = self.detect_id_kind(identifier)

        if kind == "notion_page":
            notion_page = self.get_article(identifier)
            page_id = self._compact_page_id(str(notion_page.get("id") or identifier))
            published_url = notion_page.get("Published URL")
            slug = self._slug_from_url(published_url) if published_url else None
            # A post the static site originated is bound to its Notion page
            # id; an imported post carries no page id and is bound by slug.
            static_post = self._find_static_post_by_notion_page_id(page_id)
            if static_post is None and slug:
                static_post = self._find_static_post(slug)
        else:
            slug = self._slug_from_url(identifier) if kind == "url" else identifier.strip()
            static_post = self._find_static_post(slug)
            if static_post is None:
                raise ClientError(
                    f"Could not resolve a static post from {identifier!r} (kind: {kind})"
                )
            notion_page = self._notion_page_by_published_url(
                f"{STATIC_SITE_ORIGIN}/{slug}/"
            )

        if not notion_page:
            raise ClientError(
                f"Could not resolve a Notion page for {identifier!r} "
                f"(kind: {kind})"
            )

        return {
            "id_kind": kind,
            "notion_page": notion_page,
            "static_post": static_post,
            "slug": slug,
        }

    def _unpublish_paths(self, idempotency_key: str) -> Dict[str, Path]:
        """Return the active-profile paths for one unpublish transaction."""
        root = self._publisher_runtime_root()
        return {
            "build_lock": root / "locks" / "build.lock",
            "runtime": root / "unpublish" / f"{idempotency_key}.runtime.json",
            "backup": root / "unpublish" / f"{idempotency_key}.corpus-backup",
        }

    def _page_publisher_journals(self, page_id: str) -> List[Tuple[Path, Dict[str, Any]]]:
        """Return every publisher journal recorded for one Notion page."""
        transaction_root = self._publisher_runtime_root() / "transactions"
        journals = []
        if transaction_root.exists():
            for path in sorted(transaction_root.glob("*.journal.json")):
                document = self._load_required_json(path, "publisher journal")
                source = document.get("source")
                if not isinstance(source, dict) or not isinstance(source.get("page_id"), str):
                    raise ClientError(f"Corrupt publisher journal: {path}")
                if self._compact_page_id(source["page_id"]) == page_id:
                    journals.append((path, document))
        return journals

    def _retire_publisher_transactions(self, page_id: str) -> List[str]:
        """Move a page's finished publish transactions out of the replay path.

        A completed journal makes `publish` replay its recorded result for the
        same source revision. Once the post is removed from the site that
        result is no longer true, so the records move aside and a later
        publish of the same revision runs a real transaction.
        """
        retired_root = (
            self._publisher_runtime_root()
            / "unpublished"
            / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        )
        retired = []
        for journal_path, _document in self._page_publisher_journals(page_id):
            key = journal_path.name[: -len(".journal.json")]
            for transaction_file in sorted(journal_path.parent.glob(f"{key}.*")):
                retired_root.mkdir(parents=True, exist_ok=True)
                destination = retired_root / transaction_file.name
                os.replace(transaction_file, destination)
                retired.append(str(destination))
        return retired

    def _unpublish_static_transaction(
        self,
        *,
        page_id: str,
        static_post: Path,
        status: str,
    ) -> Dict[str, Any]:
        """Remove one post from the static site, then reset its Notion page.

        The corpus record is deleted and the site goes through the same
        build, preview deployment, and production promotion a publish uses.
        Any failure before the Notion reset commits rolls production back to
        the prior deployment and restores the exact corpus record.
        """
        original = static_post.read_bytes()
        source_revision = hashlib.sha256(
            b"unpublish\n" + hashlib.sha256(original).hexdigest().encode("ascii")
        ).hexdigest()
        idempotency_key = self._publisher_idempotency_key(page_id, source_revision)
        paths = self._unpublish_paths(idempotency_key)
        journal = {
            "idempotency": {"key": idempotency_key},
            "source": {"page_id": page_id, "source_revision": source_revision},
        }
        runtime: Dict[str, Any] = {
            "schema_version": "ata-static-unpublish-runtime/v1",
            "page_id": page_id,
            "source_revision": source_revision,
            "idempotency_key": idempotency_key,
            "article_path": str(static_post),
            "failure_stage": None,
            "failure_message": None,
            "rollback_error": None,
        }

        with self._exclusive_publisher_lock(self._publisher_page_lock_path(page_id)):
            for journal_path, document in self._page_publisher_journals(page_id):
                if document.get("state") not in {"completed", "failed"}:
                    raise ClientError(
                        f"A publisher transaction is still active for page {page_id}: "
                        f"{journal_path}"
                    )
            current_stage = "build-lock acquisition"
            prior_corpus_sha256 = _static_corpus_sha256()
            try:
                with self._static_build_lock(paths) as build_token_handle:
                    current_stage = "corpus removal"
                    _atomic_write_bytes(paths["backup"], original)
                    static_post.unlink()
                    runtime["corpus_sha256"] = _static_corpus_sha256()
                    _atomic_write_json(paths["runtime"], runtime)

                    current_stage = "build"
                    build = self._run_static_build(None, runtime["corpus_sha256"])
                    manifest = build["manifest"]
                    runtime["release_ref"] = {
                        "release_id": manifest["release_id"],
                        "contract_hash": manifest["contract_hash"],
                    }
                    runtime["build_sha256"] = build["build_sha256"]
                    self._sync_build_token(
                        build_token_handle, build, runtime=runtime, paths=paths
                    )

                    current_stage = "preview upload"
                    deployment = self._deploy_static_preview(
                        idempotency_key,
                        source_revision,
                        manifest["release_id"],
                    )
                    self._validate_static_deployment_metadata(deployment)
                    runtime.update(deployment)
                    _atomic_write_json(paths["runtime"], runtime)

                    current_stage = "promotion"
                    self._apply_static_promotion(
                        manifest=manifest,
                        deployment=deployment,
                        journal=journal,
                        runtime=runtime,
                        paths=paths,
                    )

                    current_stage = "Notion update"
                    self.update_article(
                        page_id,
                        status=status,
                        properties=dict(self.UNPUBLISH_ARTIFACT_FIELDS),
                    )
            except Exception as exc:
                failure = exc if isinstance(exc, ClientError) else ClientError(str(exc))
                runtime["failure_stage"] = current_stage
                runtime["failure_message"] = str(failure)
                rollback_errors = []
                if runtime.get("promotion_applied"):
                    try:
                        self._rollback_static_promotion(
                            runtime["prior_production_deployment_id"]
                        )
                    except Exception as rollback_exc:
                        rollback_errors.append(f"production rollback: {rollback_exc}")
                    else:
                        runtime["promotion_applied"] = False
                        runtime["promotion_rolled_back"] = True
                try:
                    if paths["backup"].is_file() and not static_post.exists():
                        _atomic_write_bytes(static_post, paths["backup"].read_bytes())
                    restored_corpus_sha256 = _static_corpus_sha256()
                    if restored_corpus_sha256 != prior_corpus_sha256:
                        raise ClientError(
                            "Corpus rollback hash mismatch: "
                            f"expected {prior_corpus_sha256}, got {restored_corpus_sha256}"
                        )
                except Exception as rollback_exc:
                    rollback_errors.append(f"corpus rollback: {rollback_exc}")
                if rollback_errors:
                    runtime["rollback_error"] = "; ".join(rollback_errors)
                _atomic_write_json(paths["runtime"], runtime)
                if rollback_errors:
                    raise ClientError(
                        f"Static unpublish failed during {current_stage}: {failure}; "
                        f"rollback failed: {runtime['rollback_error']}"
                    ) from failure
                raise ClientError(
                    f"Static unpublish failed during {current_stage}: {failure}"
                ) from failure

            retired = self._retire_publisher_transactions(page_id)
            _atomic_write_json(paths["runtime"], runtime)

        return {
            "deployment_id": runtime["deployment_id"],
            "promotion_id": runtime["promotion"]["promotion_id"],
            "release_ref": runtime["release_ref"],
            "backup_path": str(paths["backup"]),
            "retired_transactions": retired,
        }

    def unpublish_article(
        self,
        identifier: str,
        status: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Revert an article: unschedule it, or remove it from the static site.

        Args:
            identifier: Notion page ID, post URL, or slug.
            status: Notion status to set (validated against live statuses).
                When omitted, a Scheduled page returns to Ready to Publish
                and any other page to Draft.
            dry_run: Resolve and report planned changes without mutating.

        Returns the JSON summary described in the command docstring.
        """
        # Resolution only reads; the target status depends on the page it finds.
        resolved = self.resolve_unpublish_target(identifier)
        notion_page = resolved["notion_page"]
        static_post = resolved["static_post"]
        if status is None:
            status = (
                "Ready to Publish" if notion_page.get("Status") == "Scheduled" else "Draft"
            )
        # Validate the target Notion status against the live schema before any
        # side effects (fail-fast, reusing the existing status path).
        valid_statuses = self.get_valid_statuses()
        if status not in valid_statuses:
            raise ClientError(
                f"Invalid status '{status}'. Valid statuses: "
                f"{', '.join(valid_statuses)}"
            )
        if not notion_page.get("id"):
            raise ClientError("Resolved Notion page is missing an id")
        page_id = self._compact_page_id(str(notion_page["id"]))

        summary = {
            "dry_run": dry_run,
            "id_kind": resolved["id_kind"],
            "static": {
                "slug": resolved["slug"],
                "article_path": str(static_post) if static_post else None,
                "action": "removed" if static_post else "already_absent",
            },
            "notion": {
                "page_id": page_id,
                "status": status,
                "cleared_fields": list(self.UNPUBLISH_ARTIFACT_FIELDS.keys()),
            },
        }
        if dry_run:
            return summary

        if static_post is None:
            # Nothing on the site to remove: reset Notion through the
            # data-driven artifact fields. The property builder resolves each
            # field's type from the live schema.
            self.update_article(
                page_id,
                status=status,
                properties=dict(self.UNPUBLISH_ARTIFACT_FIELDS),
            )
            return summary

        summary["static"].update(
            self._unpublish_static_transaction(
                page_id=page_id,
                static_post=static_post,
                status=status,
            )
        )
        return summary


_client: Optional[AtaBlogClient] = None


def get_client() -> AtaBlogClient:
    global _client
    if _client is None:
        _client = AtaBlogClient()
    return _client
