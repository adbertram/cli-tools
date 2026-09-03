"""ATA Blog wrapper client using subprocess-backed service CLIs."""
import fcntl
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen

from .config import get_config
from .static_release_bindings import (
    P11_RELEASE_MANIFEST_SHA256,
    STATIC_BASELINE_ORACLE_SHA256,
    STATIC_SCANNER_SHA256,
)
from .utils.notion_markdown import normalize_notion_markdown


NOTION_CONTENT_WRITE_TIMEOUT_SECONDS = 300

STATIC_REPOSITORY_ROOT = Path("/Users/adam/Dropbox/GitRepos/Agents/ATABlogger")
STATIC_SITE_ROOT = STATIC_REPOSITORY_ROOT / "static-site"
STATIC_RELEASE_ROOT = STATIC_REPOSITORY_ROOT / "agent_workspaces" / "static-cutover-release"
STATIC_RELEASE_MANIFEST = STATIC_SITE_ROOT / "dist" / "release-manifest.json"
STATIC_RELEASE_CONTRACT = STATIC_SITE_ROOT / "scripts" / "release_manifest.mjs"
STATIC_RELEASE_FIXTURE = (
    STATIC_SITE_ROOT / "tests" / "fixtures" / "release-contract" / "valid-interface-set.json"
)
STATIC_P05_HANDOFF = STATIC_REPOSITORY_ROOT / "agent_workspaces" / "p05_scope_v2" / "handoff.json"
STATIC_SCANNER = STATIC_REPOSITORY_ROOT / "scripts" / "validate-published-post.sh"
STATIC_SCANNER_HANDOFF = (
    STATIC_REPOSITORY_ROOT / "agent_workspaces" / "p13_scope_v2" / "handoff.json"
)
STATIC_WORKER_PROOF = STATIC_RELEASE_ROOT / "media-edge" / "direct-worker-proof.json"
STATIC_CHECKPOINT = STATIC_RELEASE_ROOT / "checkpoints" / "checkpoint-1.json"
STATIC_BUILD_TOKEN = STATIC_RELEASE_ROOT / "build-token.json"
STATIC_P05_HANDOFF_SHA256 = "d0c37f46f37ed2de88b4efbfa56cdce1d767bb2fa23e161946beccf887d00ce5"
HISTORICAL_P05_RELEASE_MANIFEST_SHA256 = (
    "884e3aadf4fb0179f9ac6dde883a8ed3862a685e45256731b099430e1b79a267"
)
STATIC_RELEASE_FIXTURE_SHA256 = "f218cd13d9508d83da954cf881a02180da55f3debd00a234cef34ee3165e2481"
HISTORICAL_P13_SCANNER_SHA256 = (
    "80fb16c457cf2ebbe829eb3592c5be7c40f5d2c2364fd664f126eb6bba14a6ad"
)
STATIC_SCANNER_HANDOFF_SHA256 = "76222b4cee8f832f5619d146cc35a5ab7ea15792ea7ede53fcf127995c6e7a57"
STATIC_WORKER_PROOF_SHA256 = "77ffce26940d282c6dd8bf3a5911d846eeb91b188be0b5e8ac95addeee213e80"
STATIC_SCANNER_REQUIRED_OPTIONS = [
    "--base-url",
    "--media-base-url",
    "--manifest",
    "--publisher-journal",
    "--scheduled-replay",
    "--deployment-metadata",
    "--expected-release-id",
    "--expected-contract-hash",
    "--expected-post-routes",
    "--deployment-id",
    "--deployment-sha256",
    "--worker-version",
    "--route-payload-sha256",
    "--expected-scanner-sha256",
]
# Author bound to first-time static stagings: Adam Bertram (authors.json id 2),
# the author the CLI's WordPress publishing account posts as.
STATIC_DEFAULT_AUTHOR_ID = 2

STATIC_PAGES_PROJECT = "ata-blog-static"
STATIC_PAGES_POLL_TIMEOUT_SECONDS = 300
STATIC_PAGES_POLL_INTERVAL_SECONDS = 2
STATIC_PAGES_READINESS_TIMEOUT_SECONDS = 120
STATIC_PAGES_READINESS_POLL_INTERVAL_SECONDS = 2
STATIC_PAGES_READINESS_STABLE_PROBES = 2
STATIC_PAGES_READINESS_ASSET_PATHS = (
    "/release-manifest.json",
    "/index.html",
)
STATIC_PAGES_PENDING_STATUSES = frozenset({"idle", "active"})
STATIC_PAGES_TERMINAL_FAILURE_STATUSES = frozenset({"failure", "canceled"})
STATIC_MEDIA_BUCKET = "ata-blog-media"
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
        and artifacts["scanner_result_sha256"] == EMPTY_SHA256
    )


def _file_sha256(path: Path) -> str:
    """Return a file's SHA-256 without loading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
    """Match the release manifest's exact static corpus membership hash."""
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
    """Wrapper client for wordpress and notion CLIs."""

    def __init__(self):
        self.config = get_config()
        self._wordpress_checked = False
        # Cache of {property_name: notion_type} from the live database schema.
        # Populated lazily by get_property_types() so a single CLI invocation
        # fetches the schema at most once.
        self._property_types_cache: Optional[Dict[str, str]] = None

        # Only check Notion CLI on init - WordPress is checked lazily when needed
        if not self.config.is_notion_available():
            raise ClientError("notion CLI not found. Install it first.")

    def _ensure_wordpress(self):
        """Lazily check WordPress CLI availability on first WordPress operation."""
        if not self._wordpress_checked:
            if not self.config.is_wordpress_available():
                raise ClientError("wordpress CLI not found. Install it first.")
            self._wordpress_checked = True

    def _run_wordpress(self, args: List[str], timeout: int = 60) -> subprocess.CompletedProcess:
        """Run a wordpress CLI command."""
        self._ensure_wordpress()
        cmd = ["wordpress"] + args
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise ClientError(f"wordpress error: {result.stderr.strip()}")
        return result

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
            Path("posts") / page_id / "featured_image.webp",
            Path("posts") / page_id / "featured_image.png",
            Path("posts") / page_id / "featured_image.jpg",
            Path("posts") / page_id / "featured_image.jpeg",
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
    def _prepare_wordpress_excerpt(excerpt: str) -> str:
        """Return a WordPress-safe SEO excerpt without mutating Notion metadata."""
        normalized = " ".join(str(excerpt).split())
        wordpress_limit = 300
        target_limit = 200

        if len(normalized) <= wordpress_limit:
            return normalized

        sentence_cutoffs = [
            normalized.rfind(mark, 0, target_limit + 1)
            for mark in (".", "!", "?")
        ]
        sentence_cutoff = max(sentence_cutoffs)
        if sentence_cutoff >= 150:
            return normalized[: sentence_cutoff + 1]

        cutoff = normalized.rfind(" ", 0, target_limit + 1)
        if cutoff < 150:
            cutoff = target_limit
        shortened = normalized[:cutoff].rstrip(" ,;:-")
        return shortened[:wordpress_limit]

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

    # WordPress passthrough methods
    def wordpress_auth_status(self) -> Dict[str, Any]:
        result = self._run_wordpress(["auth", "status"])
        return json.loads(result.stdout)

    def list_posts(self, limit: int = 100, filters: Optional[Dict] = None) -> List[Dict]:
        args = ["posts", "list", "--limit", str(limit)]
        if filters:
            filter_str = ",".join(f"{k}={v}" for k, v in filters.items())
            args.extend(["--filter", filter_str])
        result = self._run_wordpress(args)
        return json.loads(result.stdout)

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

    def resolve_category_by_name(self, name: str) -> int:
        """Find WordPress category ID by exact name match."""
        result = self._run_wordpress(["categories", "list"])
        categories = json.loads(result.stdout)
        for cat in categories:
            if cat.get("name", "").lower() == name.lower():
                return cat["id"]
        raise ClientError(f"Category not found: {name}")

    def resolve_tag_by_name(self, name: str) -> int:
        """Find WordPress tag ID by exact name match."""
        return self.resolve_tags_by_names([name])[0]

    def _resolve_tag_ids_from_filter(self, names: List[str]) -> Dict[str, int]:
        """Find tag IDs with per-name exact filters so deep tag catalogs work."""
        found: Dict[str, int] = {}
        for name in names:
            normalized_name = name.lower()
            result = self._run_wordpress([
                "tags", "list", "--filter", f"name:eq:{name}", "--limit", "1000"
            ])
            tags = json.loads(result.stdout)
            for tag in tags:
                tag_name = tag.get("name")
                if tag_name and tag_name.lower() == normalized_name:
                    found[normalized_name] = tag["id"]
                    break
        return found

    def resolve_tags_by_names(self, names: List[str]) -> List[int]:
        """Find WordPress tag IDs by exact name match, reporting all misses."""
        unique_names = list(dict.fromkeys(name.strip() for name in names if name.strip()))
        result = self._run_wordpress(["tags", "list", "--limit", "1000"])
        tags = json.loads(result.stdout)
        tags_by_name = {
            tag.get("name", "").lower(): tag["id"]
            for tag in tags
            if tag.get("name")
        }
        missing_after_bulk = [name for name in unique_names if name.lower() not in tags_by_name]
        if missing_after_bulk:
            tags_by_name.update(self._resolve_tag_ids_from_filter(missing_after_bulk))
        missing = [name for name in unique_names if name.lower() not in tags_by_name]
        if missing:
            raise ClientError(f"WordPress tag(s) not found: {', '.join(missing)}")
        return [tags_by_name[name.strip().lower()] for name in names if name.strip()]

    def check_duplicate_post(self, slug: str) -> bool:
        """Check if a WordPress post with this slug already exists."""
        result = self._run_wordpress(["posts", "list", "--filter", f"slug:eq:{slug}"])
        posts = json.loads(result.stdout)
        return len(posts) > 0

    # Kept as an override seam for tests; normal runs use the active CLI profile.
    _RESERVATION_DIR: Optional[Path] = None

    # Minimum lead time a returned slot must have over true UTC now. Acts as
    # a defense-in-depth guard independent of the timezone-correctness of the
    # code above it: if a future bug reintroduces a naive/local "now", this
    # still refuses to hand back a slot that isn't safely in the future.
    _MIN_SCHEDULE_LEAD = timedelta(minutes=30)

    def _schedule_reservation_dir(self) -> Path:
        """Return the active-profile schedule reservation directory."""
        if self._RESERVATION_DIR is not None:
            return self._RESERVATION_DIR
        return self.config.get_profile_data_dir() / "static-publisher" / "schedule-reservations"

    def _schedule_lock_path(self) -> Path:
        """Return the one lock serializing schedule reads and reservations."""
        return self._schedule_reservation_dir() / ".schedule.lock"

    def _read_schedule_reservations(self) -> List[datetime]:
        """Read pending reservations and reject corrupt reservation state."""
        times = []
        reservation_dir = self._schedule_reservation_dir()
        if not reservation_dir.exists():
            return times
        for f in reservation_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                expires = datetime.fromisoformat(data["expires"])
                slot = datetime.fromisoformat(data["slot"])
                if expires.tzinfo is None or slot.tzinfo is None:
                    f.unlink()
                    continue
                if expires < datetime.now(timezone.utc):
                    f.unlink()  # Expired reservation
                else:
                    times.append(slot.astimezone(timezone.utc))
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                raise ClientError(f"Corrupt schedule reservation {f}: {exc}") from exc
        return times

    def _create_schedule_reservation(self, slot: str) -> None:
        """Create one deterministic reservation while the schedule lock is held."""
        reservation_dir = self._schedule_reservation_dir()
        reservation_dir.mkdir(parents=True, exist_ok=True)
        reservation = {
            "slot": slot,
            "expires": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            "pid": os.getpid(),
        }
        slot_key = hashlib.sha256(slot.encode("utf-8")).hexdigest()
        path = reservation_dir / f"{slot_key}.json"
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise ClientError(f"Schedule slot is already reserved: {slot}") from exc
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_json_bytes(reservation) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())

    def clear_schedule_reservation(self) -> None:
        """Clear schedule reservations created by this process."""
        reservation_dir = self._schedule_reservation_dir()
        if reservation_dir.exists():
            with self._exclusive_publisher_lock(self._schedule_lock_path()):
                for path in reservation_dir.glob("*.json"):
                    document = self._load_required_json(path, "schedule reservation")
                    if document.get("pid") == os.getpid():
                        path.unlink()

    def _read_publisher_schedule_slots(self) -> List[datetime]:
        """Return future slots already committed to publisher runtime records."""
        runtime_root = self._publisher_runtime_root()
        if not runtime_root.exists():
            return []
        occupied: List[datetime] = []
        for path in sorted((runtime_root / "transactions").glob("*.runtime.json")):
            try:
                document = json.loads(path.read_text())
            except json.JSONDecodeError as exc:
                raise ClientError(f"Corrupt publisher runtime record {path}: {exc}") from exc
            slot = document.get("scheduled_date")
            if not slot:
                continue
            parsed = datetime.fromisoformat(slot.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ClientError(f"Publisher schedule is not UTC-aware: {path}")
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

    def _find_next_schedule_slot_unlocked(self) -> str:
        """
        Find next available publication slot respecting:
        - Max 2 posts per weekday
        - 4+ hour gap between posts
        - No weekends (roll to Monday)
        - Posts scheduled between 9am-5pm UTC only
        - Pending reservations from concurrent processes

        All arithmetic here is in UTC. The host machine's local timezone is
        never read: the wordpress CLI writes date_gmt (unambiguous UTC), so
        "now" must be true UTC now, not this process's local wall-clock time.

        Returns:
            ISO 8601 UTC datetime string with an explicit +00:00 offset
            (e.g., "2026-01-10T09:00:00+00:00").
        """
        occupied_times = self._read_publisher_schedule_slots()
        occupied_times.extend(self._read_schedule_reservations())

        # Start from true UTC now, round UP to the next hour boundary so the
        # slot is never earlier than "now" plus a full hour of lead time.
        now = datetime.now(timezone.utc)
        candidate = self._ceil_to_hour(now + timedelta(hours=1))

        # If before 9am, start at 9am
        if candidate.hour < 9:
            candidate = candidate.replace(hour=9)

        max_iterations = 100  # Safety limit
        for _ in range(max_iterations):
            # Skip weekends (5=Saturday, 6=Sunday)
            if candidate.weekday() >= 5:
                days_until_monday = 7 - candidate.weekday()
                candidate = (candidate + timedelta(days=days_until_monday)).replace(hour=9, minute=0)
                continue

            # Count posts on same day
            same_day = [t for t in occupied_times if t.date() == candidate.date()]
            if len(same_day) >= 2:
                candidate = (candidate + timedelta(days=1)).replace(hour=9, minute=0)
                continue

            # Check 4+ hour gap
            conflicts = [t for t in occupied_times if abs((t - candidate).total_seconds()) < 4 * 3600]
            if conflicts:
                candidate = candidate + timedelta(hours=4)
                # If pushed past reasonable hours (after 5pm), go to next day
                if candidate.hour >= 17:
                    candidate = (candidate + timedelta(days=1)).replace(hour=9, minute=0)
                continue

            # Defense-in-depth guard: refuse to hand back a slot that is not
            # genuinely, safely in the future relative to true UTC now, no
            # matter how "candidate" was derived above.
            if candidate < datetime.now(timezone.utc) + self._MIN_SCHEDULE_LEAD:
                candidate = self._ceil_to_hour(datetime.now(timezone.utc) + timedelta(hours=1))
                if candidate.hour < 9:
                    candidate = candidate.replace(hour=9)
                continue

            # Found valid slot - reserve it before returning
            slot = candidate.isoformat()
            self._create_schedule_reservation(slot)
            return slot

        raise ClientError("Could not find available schedule slot within iteration limit")

    def find_next_schedule_slot(self) -> str:
        """Atomically select and reserve the next available UTC schedule slot."""
        with self._exclusive_publisher_lock(self._schedule_lock_path()):
            return self._find_next_schedule_slot_unlocked()

    def _reserve_explicit_schedule_slot(self, value: str) -> str:
        """Validate and atomically reserve an explicit UTC-aware slot."""
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ClientError(f"--date is not valid ISO 8601: {value}") from exc
        if parsed.tzinfo is None:
            raise ClientError("--date must include a UTC offset")
        slot = parsed.astimezone(timezone.utc).isoformat()
        with self._exclusive_publisher_lock(self._schedule_lock_path()):
            occupied = self._read_publisher_schedule_slots()
            occupied.extend(self._read_schedule_reservations())
            if any(existing == parsed.astimezone(timezone.utc) for existing in occupied):
                raise ClientError(f"Schedule slot is already occupied: {slot}")
            self._create_schedule_reservation(slot)
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
            "scanner": transaction_root / f"{idempotency_key}.scanner.json",
            "replay": transaction_root / f"{idempotency_key}.scheduled-replay.json",
            "deployment_metadata": (
                transaction_root / f"{idempotency_key}.deployment-metadata.json"
            ),
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
        """Resolve Notion taxonomy names to WordPress term IDs via terms.json."""
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

    def _p05_gate_a_bindings(self) -> Dict[str, str]:
        """Load the current Gate A bindings while retaining the sealed oracle."""
        checkpoint = self._load_required_json(STATIC_CHECKPOINT, "Checkpoint 1")
        gate_a = checkpoint.get("gate_a")
        if (
            checkpoint.get("package_id") != "P06"
            or checkpoint.get("phase_id") != "P06.checkpoint_1"
            or checkpoint.get("checkpoint_id") != "CHECKPOINT_1"
            or checkpoint.get("status") != "PASS"
            or not isinstance(gate_a, dict)
            or gate_a.get("status") != "PASS"
        ):
            raise ClientError("Checkpoint 1 does not bind a passing Gate A")

        validation = self._run_checked_command(
            [
                "node",
                "--input-type=module",
                "--eval",
                (
                    "const contract=await import(process.argv[1]);"
                    "const result=await contract.validateProductionGateABaseline("
                    "contract.CURRENT_BASELINE_VALIDATOR_SHA256);"
                    "console.log(JSON.stringify(result));"
                ),
                STATIC_RELEASE_CONTRACT.as_uri(),
            ],
            timeout=60,
            label="current Gate A validation",
        )
        try:
            current_result = json.loads(validation.stdout)
        except json.JSONDecodeError as exc:
            raise ClientError(
                f"Current Gate A validator returned invalid JSON: {exc}"
            ) from exc
        gates = current_result.get("gates") if isinstance(current_result, dict) else None
        if (
            not isinstance(current_result, dict)
            or current_result.get("valid") is not True
            or not isinstance(gates, dict)
        ):
            raise ClientError("Current Gate A validation did not pass")

        # The checkpoint's gate_a.baseline_oracle_sha256 is the SEALED
        # pre-amendment value; the current oracle authority lives in the
        # mutable binding module (rebound whenever the baseline oracle is
        # legitimately amended, e.g. the 2026-09-01 corpus_audit reseal).
        binding_sources = {
            "expectedBaselineIndexSha256": None,
            "expectedBaselineOracleSha256": STATIC_BASELINE_ORACLE_SHA256,
        }
        for binding_name, gate_name in (
            ("expectedBaselineIndexSha256", "baseline"),
            ("expectedRedirectExportSha256", "redirect"),
            ("expectedMediaInventorySha256", "media"),
            ("expectedProvenanceLedgerSha256", "provenance"),
        ):
            gate = gates.get(gate_name)
            if not isinstance(gate, dict) or gate.get("status") != "pass":
                raise ClientError(f"Checkpoint 1 {gate_name} gate binding is invalid")
            binding_sources[binding_name] = gate.get("sha256")

        for binding_name, value in binding_sources.items():
            if not re.fullmatch(r"[0-9a-f]{64}", str(value)):
                raise ClientError(
                    f"Checkpoint 1 Gate A binding {binding_name} is not SHA-256"
                )
        return binding_sources

    def _load_static_release_manifest(self) -> Dict[str, Any]:
        """Bind historical handoffs and the current release/scanner authorities."""
        p05_handoff = self._load_required_json(STATIC_P05_HANDOFF, "P05 v2 handoff")
        actual_p05_handoff_hash = _file_sha256(STATIC_P05_HANDOFF)
        if actual_p05_handoff_hash != STATIC_P05_HANDOFF_SHA256:
            raise ClientError(
                "P05 v2 handoff bytes changed: "
                f"expected {STATIC_P05_HANDOFF_SHA256}, got {actual_p05_handoff_hash}"
            )
        p05_sources = p05_handoff.get("source_hashes")
        if (
            p05_handoff.get("package_id") != "P05-SCOPE-V2"
            or p05_handoff.get("phase_id")
            != "P05.release_interfaces.scope_amendment_v2"
            or p05_handoff.get("status") != "PASS"
            or not isinstance(p05_sources, dict)
            or p05_sources.get("static-site/scripts/release_manifest.mjs")
            != HISTORICAL_P05_RELEASE_MANIFEST_SHA256
            or p05_sources.get(
                "static-site/tests/fixtures/release-contract/valid-interface-set.json"
            )
            != STATIC_RELEASE_FIXTURE_SHA256
            or p05_handoff.get("release_contract_v2", {}).get("schema_version")
            != "ata-static-release/v2"
        ):
            raise ClientError("P05 v2 handoff does not bind the release contract")
        if (
            not STATIC_RELEASE_FIXTURE.is_file()
            or _file_sha256(STATIC_RELEASE_FIXTURE) != STATIC_RELEASE_FIXTURE_SHA256
        ):
            raise ClientError("P05 v2 release fixture bytes changed")
        if not STATIC_RELEASE_CONTRACT.is_file():
            raise ClientError(f"Final P11 release manifest is missing: {STATIC_RELEASE_CONTRACT}")
        actual_release_manifest_hash = _file_sha256(STATIC_RELEASE_CONTRACT)
        if actual_release_manifest_hash != P11_RELEASE_MANIFEST_SHA256:
            raise ClientError(
                "Final P11 release manifest bytes changed: "
                f"expected {P11_RELEASE_MANIFEST_SHA256}, "
                f"got {actual_release_manifest_hash}"
            )

        handoff = self._load_required_json(STATIC_SCANNER_HANDOFF, "P13 scanner handoff")
        actual_handoff_hash = _file_sha256(STATIC_SCANNER_HANDOFF)
        if actual_handoff_hash != STATIC_SCANNER_HANDOFF_SHA256:
            raise ClientError(
                "P13 scanner handoff bytes changed: "
                f"expected {STATIC_SCANNER_HANDOFF_SHA256}, got {actual_handoff_hash}"
            )
        p13_inputs = handoff.get("inputs")
        p13_sources = handoff.get("source_hashes")
        scanner_contract = handoff.get("scanner_contract")
        deployment_binding = (
            scanner_contract.get("deployment_binding")
            if isinstance(scanner_contract, dict)
            else None
        )
        if (
            handoff.get("package_id") != "P13-SCOPE-V2"
            or handoff.get("phase_id")
            != "P13.scanner_freeze.scope_amendment_v2"
            or handoff.get("status") != "PASS"
            or not isinstance(p13_inputs, dict)
            or p13_inputs.get("p05_scope_v2_handoff", {}).get("sha256")
            != STATIC_P05_HANDOFF_SHA256
            or not isinstance(p13_sources, dict)
            or p13_sources.get("scripts/validate-published-post.sh")
            != HISTORICAL_P13_SCANNER_SHA256
            or not isinstance(scanner_contract, dict)
            or scanner_contract.get("release_schema") != "ata-static-release/v2"
            or scanner_contract.get("required_options")
            != STATIC_SCANNER_REQUIRED_OPTIONS
            or not isinstance(deployment_binding, dict)
            or deployment_binding.get("static_identity_headers_required") is not False
            or deployment_binding.get("direct_media_worker_headers")
            != ["x-ata-worker-version", "x-ata-route-payload-sha256"]
        ):
            raise ClientError("P13 v2 handoff does not bind the historical scanner contract")
        manifest = self._load_required_json(STATIC_RELEASE_MANIFEST, "release manifest")
        if manifest.get("schema_version") != "ata-static-release/v2":
            raise ClientError("Release manifest schema is not ata-static-release/v2")
        release_id = manifest.get("release_id")
        contract_hash = manifest.get("contract_hash")
        scanner_hash = manifest.get("inputs", {}).get("scanner_implementation_sha256")
        if not isinstance(release_id, str) or not release_id:
            raise ClientError("Release manifest has no release_id")
        if not re.fullmatch(r"[0-9a-f]{64}", str(contract_hash)):
            raise ClientError("Release manifest contract_hash is not SHA-256")
        if scanner_hash != STATIC_SCANNER_SHA256:
            raise ClientError(
                "Release manifest scanner hash does not match current scanner authority: "
                f"expected {STATIC_SCANNER_SHA256}, got {scanner_hash}"
            )
        if not STATIC_SCANNER.is_file():
            raise ClientError(f"Current scanner is missing: {STATIC_SCANNER}")
        actual_scanner_hash = _file_sha256(STATIC_SCANNER)
        if actual_scanner_hash != STATIC_SCANNER_SHA256:
            raise ClientError(
                "Current scanner bytes changed: "
                f"expected {STATIC_SCANNER_SHA256}, got {actual_scanner_hash}"
            )
        gate_a_bindings = self._p05_gate_a_bindings()
        validation = self._run_checked_command(
            [
                "node",
                "--input-type=module",
                "--eval",
                (
                    "import {readFileSync} from 'node:fs';"
                    "const contract=await import(process.argv[1]);"
                    "const manifest=JSON.parse(readFileSync(process.argv[2],'utf8'));"
                    "const bindings=JSON.parse(process.argv[3]);"
                    "console.log(JSON.stringify(contract.validateReleaseManifest(manifest,bindings)));"
                ),
                STATIC_RELEASE_CONTRACT.as_uri(),
                str(STATIC_RELEASE_MANIFEST),
                json.dumps(gate_a_bindings, separators=(",", ":"), sort_keys=True),
            ],
            timeout=60,
            label="P05 release manifest validation",
        )
        try:
            validation_result = json.loads(validation.stdout)
        except json.JSONDecodeError as exc:
            raise ClientError(f"P05 release validator returned invalid JSON: {exc}") from exc
        if validation_result.get("valid") is not True:
            errors = validation_result.get("errors")
            detail = "; ".join(errors) if isinstance(errors, list) else str(errors)
            raise ClientError(f"P05 release manifest validation failed: {detail}")
        return manifest

    @staticmethod
    def _probe_static_worker_endpoint(
        endpoint: str,
        object_key: str,
        manifest: Dict[str, Any],
    ) -> None:
        """Require one direct Worker response with P13's exact identity headers."""
        request = Request(
            f"{endpoint.rstrip('/')}/{quote(object_key, safe='/')}",
            headers={
                "Accept": "*/*",
                "Connection": "close",
                "User-Agent": "ata-static-publisher/1",
            },
            method="HEAD",
        )
        try:
            with urlopen(request, timeout=10) as response:
                status = response.status
                worker_version = response.headers.get("x-ata-worker-version")
                route_hash = response.headers.get("x-ata-route-payload-sha256")
        except OSError as exc:
            raise ClientError(f"Direct Worker endpoint is unreachable: {exc}") from exc
        if status != 200:
            raise ClientError(f"Direct Worker endpoint returned HTTP {status}")
        if worker_version != manifest["worker"]["version"]:
            raise ClientError("Direct Worker version header does not match the release")
        if route_hash != manifest["worker"]["route_payload_sha256"]:
            raise ClientError("Direct Worker route payload header does not match the release")

    def _resolve_static_media_base_url(self, manifest: Dict[str, Any]) -> str:
        """Return a live, immutable, zero-production-route Worker endpoint."""
        proof = self._load_required_json(STATIC_WORKER_PROOF, "P12 direct Worker proof")
        actual_hash = _file_sha256(STATIC_WORKER_PROOF)
        if actual_hash != STATIC_WORKER_PROOF_SHA256:
            raise ClientError(
                "P12 direct Worker proof bytes changed: "
                f"expected {STATIC_WORKER_PROOF_SHA256}, got {actual_hash}"
            )
        completion = proof.get("completion")
        route = proof.get("route_safety_and_precedence")
        runtime = proof.get("worker_runtime")
        source = runtime.get("source") if isinstance(runtime, dict) else None
        deployment = runtime.get("deployment") if isinstance(runtime, dict) else None
        next_owner = proof.get("next_owner_contract")
        dependency_bindings = proof.get("dependency_bindings")
        binding = (
            dependency_bindings.get("media_edge_contract")
            if isinstance(dependency_bindings, dict)
            else None
        )
        if (
            proof.get("artifact_kind") != "static_cutover_direct_worker_proof"
            or proof.get("package_id") != "P12"
            or proof.get("phase_id") != "P12.direct_worker_proof"
            or proof.get("status") != "PASS"
            or not isinstance(completion, dict)
            or completion.get("gate_c2") != "GREEN"
            or completion.get("unresolved_blocker_count") != 0
            or not isinstance(route, dict)
            or route.get("status") != "PASS_ZERO_PRODUCTION_ROUTES"
            or route.get("target_worker_route_count") != 0
            or actual_hash != manifest["inputs"]["media_edge_proof_sha256"]
            or not isinstance(binding, dict)
            or not re.fullmatch(r"[0-9a-f]{64}", str(binding.get("sha256")))
        ):
            raise ClientError("P12 direct Worker proof is not a hash-current zero-route PASS")
        if (
            not isinstance(source, dict)
            or source.get("status") != "EXACT_MATCH"
            or source.get("local_sha256") != manifest["worker"]["script_sha256"]
            or source.get("remote_sha256") != manifest["worker"]["script_sha256"]
        ):
            raise ClientError("Worker source does not match the release manifest")
        if (
            not isinstance(deployment, dict)
            or deployment.get("status") != "ACTIVE_EXACT_VERSION"
            or deployment.get("version_id") != manifest["worker"]["version"]
            or not isinstance(next_owner, dict)
            or next_owner.get("worker_version_id") != manifest["worker"]["version"]
            or next_owner.get("pending_route_sha256")
            != manifest["worker"]["route_payload_sha256"]
        ):
            raise ClientError("Worker deployment identity does not match the release manifest")
        endpoint = runtime.get("direct_endpoint")
        parsed = urlparse(str(endpoint))
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.hostname.endswith(".workers.dev")
            or parsed.path not in ("", "/")
        ):
            raise ClientError("P12 proof has no direct HTTPS workers.dev endpoint")
        verification = proof.get("verification")
        direct_http = (
            verification.get("direct_http")
            if isinstance(verification, dict)
            else None
        )
        objects = direct_http.get("objects") if isinstance(direct_http, dict) else None
        first_object = objects[0] if isinstance(objects, list) and objects else None
        if (
            not isinstance(direct_http, dict)
            or direct_http.get("status") != "PASS"
            or not isinstance(first_object, dict)
            or first_object.get("status") != "PASS"
            or not isinstance(first_object.get("key"), str)
        ):
            raise ClientError("P12 proof has no passing direct Worker object probe")
        endpoint = str(endpoint).rstrip("/")
        self._probe_static_worker_endpoint(endpoint, first_object["key"], manifest)
        return endpoint

    @staticmethod
    def _find_named_value(value: Any, key: str) -> List[Any]:
        """Return every exact-key value in a nested JSON-compatible value."""
        found: List[Any] = []
        if isinstance(value, dict):
            for candidate_key, candidate_value in value.items():
                if candidate_key == key:
                    found.append(candidate_value)
                found.extend(AtaBlogClient._find_named_value(candidate_value, key))
        elif isinstance(value, list):
            for candidate in value:
                found.extend(AtaBlogClient._find_named_value(candidate, key))
        return found

    def _prior_pages_deployment_id(self) -> str:
        """Read the one Gate A prior Pages deployment identifier."""
        checkpoint = self._load_required_json(STATIC_CHECKPOINT, "Checkpoint 1")
        values = list(dict.fromkeys(self._find_named_value(checkpoint, "pages_deployment_id")))
        if len(values) != 1:
            raise ClientError(
                "Checkpoint 1 must contain exactly one pages_deployment_id; "
                f"found {len(values)}"
            )
        try:
            return str(uuid.UUID(str(values[0])))
        except ValueError as exc:
            raise ClientError("Checkpoint 1 pages_deployment_id is not a UUID") from exc

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
        title = str(article.get("Title") or article.get("title") or "Untitled")
        excerpt = " ".join(str(article.get("Excerpt") or "").split())
        replacements = {
            "notionPageId": json.dumps(page_id, ensure_ascii=False),
            "slug": json.dumps(slug, ensure_ascii=False),
            "title": json.dumps(title, ensure_ascii=False),
            "description": json.dumps(excerpt, ensure_ascii=False),
            "pubDate": publish_date,
            "modDate": publish_date,
            "featuredImage": json.dumps(image_url, ensure_ascii=False),
        }
        # The corpus loaders require authorId, categoryIds, tagIds, and wpId on
        # every post. A first-time post has no prior frontmatter and no
        # WordPress post yet (the classic WordPress leg runs after this
        # staging in dual-publish), so bind the author the CLI's WordPress
        # account publishes as, resolve real taxonomy IDs from the post's
        # Notion metadata against the static corpus terms, and stage wpId 0
        # until the classic leg creates the WordPress post.
        if not any(line.startswith("authorId:") for line in frontmatter):
            replacements["authorId"] = str(STATIC_DEFAULT_AUTHOR_ID)
        if not any(line.startswith("categoryIds:") for line in frontmatter):
            category_names = [
                name.strip()
                for name in str(article.get("Category") or "").split(",")
                if name.strip()
            ]
            replacements["categoryIds"] = json.dumps(
                self._resolve_static_term_ids("categories", category_names)
            )
        if not any(line.startswith("tagIds:") for line in frontmatter):
            tag_names = [
                name.strip()
                for name in str(article.get("Tags") or "").split(",")
                if name.strip()
            ]
            replacements["tagIds"] = json.dumps(
                self._resolve_static_term_ids("tags", tag_names)
            )
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
        """Return every WP-uploads URL referenced in a post body, excluding the featured-image path.

        The featured image is uploaded separately by `_upload_static_media` under
        a content-addressed `wp-content/uploads/publisher/{page_id}/...` key.
        Inline content images are referenced in post bodies as plain WordPress
        paths, e.g. `https://adamtheautomator.com/wp-content/uploads/2026/09/foo.png`.
        Those are never uploaded by the featured-image path, so this discovers
        every one of them so the caller can mirror it into R2 under the
        identical WordPress-shaped key.
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

    def _existing_static_inline_media_key(self, key: str) -> Optional[Dict[str, Any]]:
        """Return the R2 object for one exact WP-shaped key if it already exists, else None.

        Unlike the featured image's content-addressed key, a WP-shaped key has
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
        """Download one object from the live WordPress origin, retrying on transient failures.

        Mirrors static-site/scripts/migrate_wp_media.mjs's fetchWithRetry: retry
        with exponential backoff only on a 5xx/429/network error against this
        single WordPress origin; any other HTTP status fails immediately. This
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
                        f"{url}: HTTP {exc.code} fetching inline media from WordPress origin"
                    ) from exc
                last_error = exc
            except URLError as exc:
                last_error = exc
            if attempt < attempts:
                time.sleep(0.5 * (2 ** (attempt - 1)))
        raise ClientError(
            f"{url}: failed to fetch inline media from WordPress origin after "
            f"{attempts} attempts: {last_error}"
        )

    def _upload_static_inline_media(self, markdown_content: str) -> List[Dict[str, Any]]:
        """Mirror every inline WP-uploads image referenced in a post body into R2.

        For each referenced URL not already present in the bucket under its
        WordPress-shaped key, download the bytes from the live WordPress origin
        and upload them to R2 under that identical key, then re-verify presence
        and byte count before recording the receipt. Idempotent: a resumed run
        re-checks bucket presence per key and skips anything already uploaded.
        """
        receipts: List[Dict[str, Any]] = []
        for reference in self._find_inline_static_media_urls(markdown_content):
            key = reference["key"]
            url = reference["url"]
            existing = self._existing_static_inline_media_key(key)
            if existing is not None:
                receipts.append({"key": key, "url": url, "recovered": True, "object": existing})
                continue
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
                        "put",
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
            receipts.append({"key": key, "url": url, "recovered": False, "object": receipt})
        return receipts

    @staticmethod
    def _validate_recorded_static_media(runtime: Dict[str, Any]) -> None:
        """Require the persisted receipt before skipping a recorded media effect."""
        media = runtime.get("media")
        receipt = media.get("receipt") if isinstance(media, dict) else None
        inline = media.get("inline") if isinstance(media, dict) else None
        if (
            not isinstance(media, dict)
            or not isinstance(receipt, dict)
            or not receipt
            or not isinstance(receipt.get("key"), str)
            or not receipt["key"]
            or receipt["key"] != runtime.get("object_key")
            or media.get("image_url") != runtime.get("image_url")
            or not isinstance(inline, list)
            or any(
                not isinstance(item, dict) or not isinstance(item.get("key"), str) or not item["key"]
                for item in inline
            )
        ):
            raise ClientError("Corrupt publisher runtime: recorded media receipt is invalid")

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

    def _persist_static_deployment_metadata(
        self,
        deployment: Dict[str, Any],
        path: Path,
    ) -> Dict[str, Any]:
        """Persist the exact Pages metadata whose canonical hash P13 consumes."""
        metadata = deployment.get("deployment")
        if not isinstance(metadata, dict):
            raise ClientError("Pages preview receipt has no deployment metadata")
        actual_sha256 = _artifact_sha256(metadata)
        if deployment.get("deployment_sha256") != actual_sha256:
            raise ClientError("Pages preview deployment metadata hash mismatch")
        if path.exists():
            existing = self._load_required_json(path, "Pages deployment metadata")
            if existing != metadata:
                raise ClientError("Saved Pages deployment metadata does not match receipt")
        else:
            _atomic_write_json(path, metadata)
        return metadata

    @staticmethod
    def _scheduled_replay_document(journal: Dict[str, Any]) -> Dict[str, Any]:
        """Create P13's exact zero-effect replay input for this idempotency key."""
        evidence = {
            "idempotency_key": journal["idempotency"]["key"],
            "deployment_id": journal["artifacts"]["deployment_id"],
            "effects": journal["effects"],
        }
        return {
            "same_revision": True,
            "corpus_writes": 0,
            "builds": 0,
            "deployments": 0,
            "notion_updates": 0,
            "evidence_sha256": _artifact_sha256(evidence),
        }

    @staticmethod
    def _fetch_static_preview_asset(url: str, timeout: float) -> tuple[int, bytes]:
        """Fetch one immutable Pages asset without content encoding changes."""
        request = Request(
            url,
            headers={
                "Accept": "*/*",
                "Accept-Encoding": "identity",
                "Cache-Control": "no-cache",
                "Connection": "close",
                "User-Agent": "ata-static-publisher-readiness/1",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.status, response.read()
        except HTTPError as exc:
            return exc.code, exc.read()

    def _wait_for_static_preview_readiness(
        self,
        *,
        deployment: Dict[str, Any],
        deployment_sha256: str,
        fetcher: Optional[Callable[[str, float], tuple[int, bytes]]] = None,
        clock: Optional[Callable[[], float]] = None,
        sleeper: Optional[Callable[[float], None]] = None,
        emit: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Require stable exact bytes from the immutable deployment URL."""
        metadata = deployment.get("deployment")
        if not isinstance(metadata, dict):
            raise ClientError("Pages preview readiness has no deployment metadata")
        try:
            metadata_id = str(uuid.UUID(str(metadata["id"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise ClientError(
                "Pages preview readiness metadata has no UUID deployment id"
            ) from exc
        deployment_id = deployment.get("deployment_id")
        if metadata_id != deployment_id:
            raise ClientError(
                "Pages preview readiness deployment id mismatch: "
                f"expected {deployment_id}, got {metadata_id}"
            )
        deployment_url = str(deployment.get("deployment_url") or "").rstrip("/")
        metadata_url = str(metadata.get("url") or "").rstrip("/")
        if not deployment_url or metadata_url != deployment_url:
            raise ClientError("Pages preview readiness deployment URL identity mismatch")
        latest_stage = metadata.get("latest_stage")
        if not isinstance(latest_stage, dict) or latest_stage.get("status") != "success":
            raise ClientError(
                "Pages preview readiness requires latest_stage.status success"
            )
        if (
            deployment.get("deployment_sha256") != deployment_sha256
            or _artifact_sha256(metadata) != deployment_sha256
        ):
            raise ClientError("Pages preview readiness deployment metadata hash mismatch")

        files = metadata.get("files")
        if not isinstance(files, dict):
            raise ClientError("Pages preview readiness metadata has no files map")
        assets = []
        dist_root = STATIC_SITE_ROOT / "dist"
        for asset_path in STATIC_PAGES_READINESS_ASSET_PATHS:
            local_path = dist_root / asset_path.removeprefix("/")
            if local_path.is_symlink() or not local_path.is_file():
                raise ClientError(
                    f"Pages preview readiness local asset is missing: {local_path}"
                )
            expected_bytes = local_path.read_bytes()
            file_identifier = files.get(asset_path)
            if asset_path not in files or not re.fullmatch(
                r"[0-9a-f]{32}",
                str(file_identifier),
            ):
                raise ClientError(
                    "Pages preview readiness receipt has no valid file identifier for "
                    f"{asset_path}"
                )
            assets.append(
                (
                    asset_path,
                    expected_bytes,
                    hashlib.sha256(expected_bytes).hexdigest(),
                )
            )

        fetch = fetcher or self._fetch_static_preview_asset
        monotonic = clock or time.monotonic
        sleep = sleeper or time.sleep
        progress = emit or (
            lambda message: print(message, file=sys.stderr, flush=True)
        )
        deadline = monotonic() + STATIC_PAGES_READINESS_TIMEOUT_SECONDS
        stable_probes = 0
        probe_count = 0
        last_observations = ["no probes completed"]
        progress(
            "Pages preview readiness started: "
            f"deployment_id={deployment_id} url={deployment_url} "
            f"assets={','.join(path for path, _bytes, _sha in assets)} "
            f"stable_required={STATIC_PAGES_READINESS_STABLE_PROBES} "
            f"timeout_seconds={STATIC_PAGES_READINESS_TIMEOUT_SECONDS}"
        )
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise ClientError(
                    "Pages preview readiness timed out for exact deployment "
                    f"{deployment_id} after {STATIC_PAGES_READINESS_TIMEOUT_SECONDS} "
                    f"seconds and {probe_count} probes; last observations: "
                    f"{'; '.join(last_observations)}"
                )
            probe_count += 1
            round_ready = True
            observations = []
            for asset_path, expected_bytes, expected_sha256 in assets:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    round_ready = False
                    observations.append(f"{asset_path}:deadline-exhausted")
                    break
                asset_url = f"{deployment_url}{asset_path}"
                try:
                    status, body = fetch(asset_url, min(10.0, remaining))
                except OSError as exc:
                    round_ready = False
                    observations.append(f"{asset_path}:error={exc}")
                    continue
                actual_sha256 = hashlib.sha256(body).hexdigest()
                if status != 200:
                    round_ready = False
                    observations.append(f"{asset_path}:http={status}")
                elif body != expected_bytes:
                    round_ready = False
                    observations.append(
                        f"{asset_path}:sha256={actual_sha256},"
                        f"expected={expected_sha256}"
                    )
                else:
                    observations.append(
                        f"{asset_path}:http=200,sha256={actual_sha256}"
                    )
            last_observations = observations
            stable_probes = stable_probes + 1 if round_ready else 0
            progress(
                "Pages preview readiness probe: "
                f"deployment_id={deployment_id} probe={probe_count} "
                f"stable={stable_probes}/{STATIC_PAGES_READINESS_STABLE_PROBES} "
                f"observations={'; '.join(observations)}"
            )
            if stable_probes >= STATIC_PAGES_READINESS_STABLE_PROBES:
                progress(
                    "Pages preview readiness passed: "
                    f"deployment_id={deployment_id} probes={probe_count}"
                )
                return
            remaining = deadline - monotonic()
            if remaining > 0:
                sleep(min(STATIC_PAGES_READINESS_POLL_INTERVAL_SECONDS, remaining))

    def _run_static_scanner(
        self,
        *,
        manifest: Dict[str, Any],
        journal_path: Path,
        replay_path: Path,
        deployment_metadata_path: Path,
        scanner_path: Path,
        deployment: Dict[str, Any],
        deployment_sha256: str,
        media_base_url: str,
    ) -> Dict[str, Any]:
        """Invoke, never reimplement, the current hash-bound acceptance scanner."""
        self._wait_for_static_preview_readiness(
            deployment=deployment,
            deployment_sha256=deployment_sha256,
        )
        post_count = sum(
            route.get("kind") == "post"
            for route in manifest.get("routes", {}).get("current", [])
        )
        worker = manifest.get("worker", {})
        command = [
            str(STATIC_SCANNER),
            "--base-url",
            deployment["deployment_url"],
            "--media-base-url",
            media_base_url,
            "--manifest",
            str(STATIC_RELEASE_MANIFEST),
            "--publisher-journal",
            str(journal_path),
            "--scheduled-replay",
            str(replay_path),
            "--deployment-metadata",
            str(deployment_metadata_path),
            "--expected-release-id",
            manifest["release_id"],
            "--expected-contract-hash",
            manifest["contract_hash"],
            "--expected-post-routes",
            str(post_count),
            "--deployment-id",
            deployment["deployment_id"],
            "--deployment-sha256",
            deployment_sha256,
            "--worker-version",
            worker["version"],
            "--route-payload-sha256",
            worker["route_payload_sha256"],
            "--expected-scanner-sha256",
            STATIC_SCANNER_SHA256,
        ]
        # The acceptance scan probes every corpus route over the network
        # (1331+ posts); a full pass can exceed an hour, so allow four.
        result = subprocess.run(
            command,
            cwd=STATIC_REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            timeout=14400,
        )
        if not result.stdout.strip():
            diagnostic = result.stderr.strip() or "no diagnostic output"
            raise ClientError(
                "Current scanner returned no JSON result "
                f"(exit {result.returncode}): {diagnostic}"
            )
        try:
            scanner_result = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ClientError(f"Current scanner returned invalid JSON: {exc}") from exc
        self._validate_static_scanner_result(
            scanner_result,
            manifest=manifest,
            deployment=deployment,
            deployment_sha256=deployment_sha256,
            allow_rejected=True,
        )
        if result.returncode != scanner_result["exit_code"]:
            raise ClientError(
                "Current scanner process exit does not match its JSON result: "
                f"process={result.returncode}, result={scanner_result['exit_code']}"
            )
        _atomic_write_json(scanner_path, scanner_result)
        if scanner_result["passed"] is not True:
            diagnostic = result.stderr.strip() or "scanner reported rejection"
            raise ClientError(
                "Current scanner rejected the exact bound Pages preview "
                f"(exit {result.returncode}); result saved to {scanner_path}: "
                f"{diagnostic}"
            )
        return scanner_result

    @staticmethod
    def _validate_static_scanner_result(
        scanner_result: Dict[str, Any],
        *,
        manifest: Dict[str, Any],
        deployment: Dict[str, Any],
        deployment_sha256: str,
        allow_rejected: bool = False,
    ) -> None:
        """Validate the exact scanner result envelope and current identity bindings."""
        fields = {
            "schema_version", "passed", "exit_code", "release_ref",
            "deployment_ref", "scanner_implementation_sha256", "section_ids",
            "sections",
        }
        if not isinstance(scanner_result, dict) or set(scanner_result) != fields:
            raise ClientError("Current scanner result fields do not match the required contract")
        release_ref = {
            "release_id": manifest["release_id"],
            "contract_hash": manifest["contract_hash"],
        }
        worker = manifest["worker"]
        deployment_ref = {
            "deployment_id": deployment["deployment_id"],
            "deployment_sha256": deployment_sha256,
            "worker_version": worker["version"],
            "route_payload_sha256": worker["route_payload_sha256"],
        }
        section_ids = ["routes", "content-media", "vendor-publisher"]
        passed = scanner_result["passed"]
        exit_code = scanner_result["exit_code"]
        if (
            scanner_result["schema_version"] != "ata-static-scanner-result/v1"
            or scanner_result["release_ref"] != release_ref
            or scanner_result["deployment_ref"] != deployment_ref
            or scanner_result["scanner_implementation_sha256"] != STATIC_SCANNER_SHA256
            or scanner_result["section_ids"] != section_ids
            or not isinstance(scanner_result["sections"], list)
            or len(scanner_result["sections"]) != len(section_ids)
        ):
            raise ClientError("Current scanner result identity is corrupt or stale")
        if not (
            (passed is True and type(exit_code) is int and exit_code == 0)
            or (passed is False and type(exit_code) is int and exit_code == 1)
        ):
            raise ClientError("Current scanner result outcome is invalid")
        section_fields = {
            "schema_version", "section_id", "release_ref", "deployment_ref",
            "scanner_implementation_sha256", "checks", "failures",
        }
        failure_count = 0
        for expected_section_id, section in zip(
            section_ids,
            scanner_result["sections"],
        ):
            if (
                not isinstance(section, dict)
                or set(section) != section_fields
                or section["schema_version"] != "ata-static-acceptance-section/v1"
                or section["section_id"] != expected_section_id
                or section["release_ref"] != release_ref
                or section["deployment_ref"] != deployment_ref
                or section["scanner_implementation_sha256"] != STATIC_SCANNER_SHA256
                or not isinstance(section["checks"], list)
                or not isinstance(section["failures"], list)
            ):
                raise ClientError("Current scanner acceptance section is corrupt or stale")
            failure_count += len(section["failures"])
        if (passed is True and failure_count != 0) or (
            passed is False and failure_count == 0
        ):
            raise ClientError("Current scanner result failures do not match its outcome")
        if passed is False and not allow_rejected:
            raise ClientError("Current scanner did not accept the exact bound Pages preview")

    def _load_existing_scanner_result(
        self,
        path: Path,
        *,
        manifest: Dict[str, Any],
        deployment: Dict[str, Any],
        deployment_sha256: str,
    ) -> Optional[Dict[str, Any]]:
        """Reuse a durable accepted result after a crash before transition write."""
        if not path.exists():
            return None
        result = self._load_required_json(path, "scanner result")
        self._validate_static_scanner_result(
            result,
            manifest=manifest,
            deployment=deployment,
            deployment_sha256=deployment_sha256,
            allow_rejected=True,
        )
        if result["passed"] is False:
            return None
        return result

    def _promote_static_release(
        self,
        manifest: Dict[str, Any],
        deployment: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Refuse production promotion outside P20's hash-current Gate D journal."""
        gate_path = STATIC_RELEASE_ROOT / "cutover" / "gate-d.json"
        gate = self._load_required_json(gate_path, "Gate D approval")
        expected_ref = {
            "release_id": manifest["release_id"],
            "contract_hash": manifest["contract_hash"],
        }
        if gate.get("release_ref") != expected_ref:
            raise ClientError("Gate D release_ref is stale")
        pages = gate.get("pages_approval", {})
        uploads = gate.get("uploads_route_approval", {})
        if pages.get("approved") is not True or uploads.get("approved") is not True:
            raise ClientError("Gate D does not contain both required approvals")
        if pages.get("deployment_id") != deployment["deployment_id"]:
            raise ClientError("Gate D Pages approval is for a different deployment")
        raise ClientError(
            "Production promotion is owned by P20's cutover operator; "
            "the static publisher will not create a second Pages deployment"
        )

    def _post_promotion_validate(
        self,
        manifest: Dict[str, Any],
        deployment: Dict[str, Any],
    ) -> None:
        """P20 override seam for production validation after promotion."""
        raise ClientError("Post-promotion validation is owned by P20")

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
            ("deployed", "accepted"),
            ("accepted", "notion_updated"),
            ("notion_updated", "completed"),
            ("reserved", "failed"),
            ("staged", "failed"),
            ("built", "failed"),
            ("deployed", "failed"),
            ("accepted", "failed"),
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
            "artifacts": {"staged_corpus_sha256", "build_sha256", "deployment_id", "scanner_result_sha256"},
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
        for field in ("staged_corpus_sha256", "build_sha256", "scanner_result_sha256"):
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
            "reserved", "staged", "built", "deployed", "accepted",
            "notion_updated", "completed", "failed",
        }
        if journal["state"] not in allowed_states or not isinstance(journal["events"], list):
            raise ClientError("Corrupt publisher journal: invalid state or events")
        transitions = {
            "reserved->staged", "staged->built", "built->deployed",
            "deployed->accepted", "accepted->notion_updated",
            "notion_updated->completed", "reserved->failed", "staged->failed",
            "built->failed", "deployed->failed", "accepted->failed",
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
                "scanner_result_sha256": EMPTY_SHA256,
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
        slug = runtime["slug"]
        baseline = initial_effects or {field: 0 for field in journal["effects"]}
        invocation_effects = {
            field: 0 if replayed else max(0, value - baseline.get(field, 0))
            for field, value in journal["effects"].items()
        }
        return {
            "notion_page_id": journal["source"]["page_id"],
            "status": runtime["status"],
            "scheduled_date": runtime.get("scheduled_date"),
            "static_url": f"{deployment_url}/{slug}/",
            "deployment_id": journal["artifacts"]["deployment_id"],
            "deployment_url": deployment_url,
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
        if runtime.get("scanner_handoff_sha256") != STATIC_SCANNER_HANDOFF_SHA256:
            raise ClientError("Stale publisher runtime: P13 scanner handoff mismatch")
        media_base_url = runtime.get("media_base_url")
        parsed_media_url = urlparse(str(media_base_url))
        if (
            parsed_media_url.scheme != "https"
            or not parsed_media_url.hostname
            or not parsed_media_url.hostname.endswith(".workers.dev")
            or parsed_media_url.path not in ("", "/")
        ):
            raise ClientError("Corrupt publisher runtime: invalid media_base_url")
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
        if not STATIC_BUILD_TOKEN.is_file():
            raise ClientError(f"Required build token is missing: {STATIC_BUILD_TOKEN}")
        descriptor = os.open(STATIC_BUILD_TOKEN, os.O_RDWR)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ClientError("Global build token is already held") from exc
            with os.fdopen(os.dup(descriptor), "r", encoding="utf-8") as handle:
                try:
                    token = json.load(handle)
                except json.JSONDecodeError as exc:
                    raise ClientError(f"Corrupt build token {STATIC_BUILD_TOKEN}: {exc}") from exc
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
            "accepted": (
                "corpus_writes", "media_upload_sets", "builds", "deployments",
            ),
            "notion_updated": tuple(effects),
            "completed": tuple(effects),
        }
        if state in requirements and any(effects[field] != 1 for field in requirements[state]):
            raise ClientError(f"Corrupt publisher journal: effects do not support {state}")
        if state in {"deployed", "accepted", "notion_updated", "completed"}:
            try:
                uuid.UUID(str(artifacts["deployment_id"]))
            except ValueError as exc:
                raise ClientError("Corrupt publisher journal: deployed state has no UUID") from exc
        if state in {"accepted", "notion_updated", "completed"} and (
            artifacts["scanner_result_sha256"] == EMPTY_SHA256
        ):
            raise ClientError("Corrupt publisher journal: accepted state has no scanner result")

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
                    self._persist_static_deployment_metadata(
                        deployment,
                        paths["deployment_metadata"],
                    )
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
                    current_stage = "preview acceptance"
                    replay = self._scheduled_replay_document(journal)
                    _atomic_write_json(paths["replay"], replay)
                    scanner_result = self._load_existing_scanner_result(
                        paths["scanner"],
                        manifest=manifest,
                        deployment=deployment,
                        deployment_sha256=runtime["deployment_sha256"],
                    )
                    if scanner_result is None:
                        scanner_result = self._run_static_scanner(
                            manifest=manifest,
                            journal_path=paths["journal"],
                            replay_path=paths["replay"],
                            deployment_metadata_path=paths["deployment_metadata"],
                            scanner_path=paths["scanner"],
                            deployment=deployment,
                            deployment_sha256=runtime["deployment_sha256"],
                            media_base_url=runtime["media_base_url"],
                        )
                    journal["artifacts"]["scanner_result_sha256"] = _artifact_sha256(
                        scanner_result
                    )
                    self._transition_publisher_journal(
                        journal,
                        "accepted",
                        journal["artifacts"]["scanner_result_sha256"],
                        paths["journal"],
                    )

                if journal["state"] == "accepted":
                    public_base_url = deployment["deployment_url"]
                    if runtime["status"] == "publish":
                        current_stage = "promotion"
                        runtime["promotion"] = self._promote_static_release(
                            manifest, deployment
                        )
                        runtime["promotion_applied"] = True
                        _atomic_write_json(paths["runtime"], runtime)
                        current_stage = "post-promotion validation"
                        self._post_promotion_validate(manifest, deployment)
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
                    current_stage = "schedule cleanup"
                    self.clear_schedule_reservation()
                    _atomic_write_json(paths["runtime"], runtime)
                    replay = self._scheduled_replay_document(journal)
                    _atomic_write_json(paths["replay"], replay)
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
                    self._rollback_static_promotion(journal["prior_state"]["deployment_id"])
                except Exception as rollback_exc:
                    rollback_errors.append(f"production rollback: {rollback_exc}")
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
        slug: Optional[str],
        date: Optional[str],
        auto_schedule: bool,
        check_duplicates: bool,
        featured_image: Optional[str],
        force: bool,
    ) -> Dict[str, Any]:
        """Serialize source capture and transaction work for one Notion page."""
        with self._exclusive_publisher_lock(self._publisher_page_lock_path(page_id)):
            return self._publish_static_transaction_locked(
                page_id=page_id,
                status=status,
                slug=slug,
                date=date,
                auto_schedule=auto_schedule,
                check_duplicates=check_duplicates,
                featured_image=featured_image,
                force=force,
            )

    def _publish_static_transaction_locked(
        self,
        *,
        page_id: str,
        status: str,
        slug: Optional[str],
        date: Optional[str],
        auto_schedule: bool,
        check_duplicates: bool,
        featured_image: Optional[str],
        force: bool,
    ) -> Dict[str, Any]:
        """Run or resume the single journaled static publication transaction."""
        if status not in {"draft", "publish"}:
            raise ClientError("Static publish status must be draft or publish")
        if date and auto_schedule:
            raise ClientError("Use either --date or --auto-schedule, not both")
        if status == "publish":
            raise ClientError(
                "Production promotion is owned by P20 and requires its hash-current "
                "Gate D transaction; use --status draft for a P14 preview"
            )
        if date:
            try:
                parsed_date = datetime.fromisoformat(date.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ClientError(f"--date is not valid ISO 8601: {date}") from exc
            if parsed_date.tzinfo is None:
                raise ClientError("--date must include a UTC offset")

        article = self.get_article(page_id)
        title = str(article.get("Title") or article.get("title") or "Untitled")
        missing = [
            field for field in ("Keywords", "Category", "Tags", "Excerpt")
            if not article.get(field)
        ]
        if missing:
            raise ClientError(f"Missing required Notion fields: {', '.join(missing)}")
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
        final_slug = self._static_slug(title, slug)

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
                deployment = {
                    "deployment_id": runtime["deployment_id"],
                    "deployment_url": runtime["deployment_url"],
                    "deployment": runtime["deployment"],
                    "deployment_sha256": runtime["deployment_sha256"],
                }
                self._persist_static_deployment_metadata(
                    deployment,
                    paths["deployment_metadata"],
                )
                scanner_result = self._load_existing_scanner_result(
                    paths["scanner"],
                    manifest=manifest,
                    deployment=deployment,
                    deployment_sha256=runtime["deployment_sha256"],
                )
                if scanner_result is None or _artifact_sha256(scanner_result) != (
                    journal["artifacts"]["scanner_result_sha256"]
                ):
                    raise ClientError("Completed publisher journal has no bound P13 receipt")
                replay = self._scheduled_replay_document(journal)
                _atomic_write_json(paths["replay"], replay)
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
            media_base_url = self._resolve_static_media_base_url(manifest)
            if journal is None:
                runtime = {
                    "schema_version": "ata-static-publisher-runtime/v1",
                    "page_id": page_id,
                    "source_revision": source_revision,
                    "idempotency_key": idempotency_key,
                    "slug": final_slug,
                    "status": status,
                    "scheduled_date": None,
                    "publish_date": None,
                    "release_ref": unbound_release_ref,
                    "build_token_release_ref": release_ref,
                    "scanner_handoff_sha256": STATIC_SCANNER_HANDOFF_SHA256,
                    "media_base_url": media_base_url,
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
                if runtime.get("scanner_handoff_sha256") != STATIC_SCANNER_HANDOFF_SHA256:
                    raise ClientError("Stale publisher runtime: P13 scanner handoff mismatch")
                if runtime.get("media_base_url") != media_base_url:
                    raise ClientError("Stale publisher runtime: media_base_url mismatch")
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
                        prior_deployment_id = self._prior_pages_deployment_id()
                        journal = self._new_publisher_journal(
                            page_id=page_id,
                            source_revision=source_revision,
                            article=article,
                            manifest=manifest,
                            prior_deployment_id=prior_deployment_id,
                        )
                        _atomic_write_json(paths["journal"], journal)
                        current_stage = "schedule reservation"
                        scheduled_date = None
                        if auto_schedule:
                            scheduled_date = self.find_next_schedule_slot()
                        elif date:
                            scheduled_date = self._reserve_explicit_schedule_slot(date)
                        runtime["scheduled_date"] = scheduled_date
                        runtime["publish_date"] = (
                            scheduled_date
                            or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
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
                    self._persist_static_deployment_metadata(
                        deployment,
                        paths["deployment_metadata"],
                    )
                    self._transition_publisher_journal(
                        journal,
                        "deployed",
                        deployment,
                        paths["journal"],
                    )

                    current_stage = "preview acceptance"
                    replay = self._scheduled_replay_document(journal)
                    _atomic_write_json(paths["replay"], replay)
                    scanner_result = self._run_static_scanner(
                        manifest=manifest,
                        journal_path=paths["journal"],
                        replay_path=paths["replay"],
                        deployment_metadata_path=paths["deployment_metadata"],
                        scanner_path=paths["scanner"],
                        deployment=deployment,
                        deployment_sha256=runtime["deployment_sha256"],
                        media_base_url=runtime["media_base_url"],
                    )
                    journal["artifacts"]["scanner_result_sha256"] = _artifact_sha256(
                        scanner_result
                    )
                    self._transition_publisher_journal(
                        journal,
                        "accepted",
                        journal["artifacts"]["scanner_result_sha256"],
                        paths["journal"],
                    )

                    public_base_url = deployment["deployment_url"]
                    if status == "publish":
                        current_stage = "promotion"
                        promotion = self._promote_static_release(manifest, deployment)
                        runtime["promotion"] = promotion
                        runtime["promotion_applied"] = True
                        _atomic_write_json(paths["runtime"], runtime)
                        current_stage = "post-promotion validation"
                        self._post_promotion_validate(manifest, deployment)
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
                    current_stage = "schedule cleanup"
                    self.clear_schedule_reservation()
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
                            journal["prior_state"]["deployment_id"]
                        )
                    except Exception as rollback_exc:
                        rollback_errors.append(f"production rollback: {rollback_exc}")
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

    @staticmethod
    def _static_cutover_active() -> bool:
        """Return True only when the static-site cutover handoff artifacts exist.

        The static migration is considered active only when the P05/P13 v2
        handoffs are present. The built dist/release-manifest.json is
        deliberately NOT part of this check: it is a build OUTPUT that any
        crashed build deletes, and gating on it silently degraded dual-publish
        to WordPress-only (observed 2026-09-01, WP post 27238). With the
        handoffs present, a missing built manifest now fails the static leg
        loudly inside the transaction instead of skipping it silently.
        """
        return STATIC_P05_HANDOFF.is_file() and STATIC_SCANNER_HANDOFF.is_file()

    def publish_article(
        self,
        page_id: str,
        status: str = "draft",
        slug: Optional[str] = None,
        date: Optional[str] = None,
        auto_schedule: bool = False,
        check_duplicates: bool = True,
        featured_image: Optional[str] = None,
        force: bool = False,
        static_only: bool = False,
    ) -> Dict[str, Any]:
        """
        Publish a Notion article to WordPress.

        Dual-publish mode (2026-09-01 directive): when the static cutover
        artifacts are present (P05/P13 handoffs plus the integrated release
        manifest), publish through the journaled static-site transaction AND
        the classic WordPress path. static_only=True runs only the static
        transaction (for backfilling a post whose WordPress leg already ran);
        when the page already carries a WordPress publication, its Notion
        Status, Published URL, and Publish Date are restored after the static
        transaction so WordPress keeps owning the production Notion state. WordPress remains the visitor-facing
        production site until the Phase 5 DNS cutover, so the classic leg runs
        last and owns the final Notion state (Status, Published URL, Publish
        Date reflect WordPress). When the artifacts are absent, only the
        classic WordPress path runs.

        Args:
            page_id: Notion page ID
            status: WordPress status (draft, publish, future)
            slug: Optional custom URL slug (auto-generated from title if not provided)
            date: Optional schedule date (ISO 8601). If auto_schedule, this is ignored.
            auto_schedule: If True, automatically find next available slot
            check_duplicates: If True, error if slug already exists
            featured_image: Optional path to featured image file to upload and attach
            force: If True, skip the already-published check

        Returns the classic dict (wordpress_post, notion_page_id, schedule
        info, optional featured_image/schema status). In dual-publish mode the
        dict also carries "static_url" and the full static transaction result
        under "static_publish".
        """
        if static_only:
            if not self._static_cutover_active():
                raise ClientError(
                    "Static-only publish requires the static cutover handoff "
                    "artifacts"
                )
            prior_article = self.get_article(page_id)
            prior_state = {
                "status": prior_article.get("Status"),
                "published_url": prior_article.get("Published URL"),
                "publish_date": prior_article.get("Publish Date"),
            }
            static_result = self._publish_static_transaction(
                page_id=page_id,
                status="draft" if status == "publish" else status,
                slug=slug,
                date=date,
                auto_schedule=auto_schedule,
                check_duplicates=check_duplicates,
                featured_image=featured_image,
                force=force,
            )
            if prior_state["published_url"]:
                self.update_article(
                    page_id,
                    status=prior_state["status"],
                    properties={
                        "Published URL": prior_state["published_url"],
                        "Publish Date": prior_state["publish_date"],
                    },
                )
                static_result["notion_restored"] = prior_state
            return static_result
        if not self._static_cutover_active():
            return self._publish_article_classic(
                page_id=page_id,
                status=status,
                slug=slug,
                date=date,
                auto_schedule=auto_schedule,
                check_duplicates=check_duplicates,
                featured_image=featured_image,
                force=force,
            )
        # Static leg first: its journal requires the deployed->notion_updated
        # ->completed progression, so it writes an intermediate Notion state.
        # The classic leg then runs with force=True (the static leg just set
        # Published URL on purpose) and overwrites Notion with the production
        # WordPress URL, status, and publish date. A static-leg failure aborts
        # before WordPress is touched; a classic-leg failure after a static
        # deploy raises loudly with the static deployment already live on the
        # non-visitor-facing Pages project.
        # The static transaction refuses status="publish" (production
        # promotion of the static site is owned by P20), so an immediate
        # WordPress publish deploys the static content as a draft while the
        # classic leg owns the live status.
        static_status = "draft" if status == "publish" else status
        static_result = self._publish_static_transaction(
            page_id=page_id,
            status=static_status,
            slug=slug,
            date=date,
            auto_schedule=auto_schedule,
            check_duplicates=check_duplicates,
            featured_image=featured_image,
            force=force,
        )
        classic_result = self._publish_article_classic(
            page_id=page_id,
            status=status,
            slug=slug,
            date=date,
            auto_schedule=auto_schedule,
            check_duplicates=check_duplicates,
            featured_image=featured_image,
            force=True,
        )
        if "static_url" in static_result:
            classic_result["static_url"] = static_result["static_url"]
        classic_result["static_publish"] = static_result
        return classic_result

    def _publish_article_classic(
        self,
        page_id: str,
        status: str = "draft",
        slug: Optional[str] = None,
        date: Optional[str] = None,
        auto_schedule: bool = False,
        check_duplicates: bool = True,
        featured_image: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Classic WordPress publish path (pre-static-rewrite behavior).

        Args:
            page_id: Notion page ID
            status: WordPress status (draft, publish, future)
            slug: Optional custom URL slug (auto-generated from title if not provided)
            date: Optional schedule date (ISO 8601). If auto_schedule, this is ignored.
            auto_schedule: If True, automatically find next available slot
            check_duplicates: If True, error if slug already exists
            featured_image: Optional path to featured image file to upload and attach
            force: If True, skip the already-published check

        Returns dict with wordpress_post, notion_page_id, schedule info,
        and optional featured_image/schema status
        """
        warnings = []

        # 0. Validate featured image before doing anything (fail early)
        image_path = self._validate_featured_image(featured_image)

        # 1. Get article metadata from Notion
        article = self.get_article(page_id)

        # 1b. Check if already published (unless --force)
        if not force:
            published_url = article.get("Published URL")
            if published_url:
                raise ClientError(
                    f"Post already published at: {published_url}. "
                    f"Use --force to republish."
                )
        title = article.get("Title") or article.get("title") or "Untitled"

        # 2. Validate required fields
        keywords = article.get("Keywords", "")
        category_name = article.get("Category")
        tags_str = article.get("Tags", "")
        excerpt = article.get("Excerpt", "")

        missing = []
        if not keywords:
            missing.append("Keywords")
        if not category_name:
            missing.append("Category")
        if not tags_str:
            missing.append("Tags")
        if not excerpt:
            missing.append("Excerpt")

        if missing:
            raise ClientError(f"Missing required Notion fields: {', '.join(missing)}")

        # 2b. Read Schema Type from Notion (already fetched above)
        schema_type_raw = article.get("Schema Type", "")
        # Schema Type may be a comma-separated multi_select value
        if schema_type_raw:
            schema_type_str = schema_type_raw.split(",")[0].strip()
        else:
            schema_type_str = "Article"
            warnings.append("Schema Type missing in Notion, defaulting to 'Article'")

        # 3. Upload featured image before creating post (fail early)
        from .utils.images import upload_to_wordpress
        try:
            featured_image_result = upload_to_wordpress(image_path)
        except RuntimeError as e:
            raise ClientError(f"Featured image upload failed: {e}")
        if not featured_image_result.get("id"):
            raise ClientError("Featured image upload did not return a WordPress media ID")

        # 4. Generate slug (or use custom) and check for duplicates
        if slug:
            # Use provided custom slug - validate and clean it
            slug = re.sub(r'[^a-z0-9-]', '', slug.lower())[:50].rstrip('-')
        else:
            # Auto-generate slug from title
            # Stop words to remove from slugs (prepositions, articles, conjunctions)
            stop_words = {
                'a', 'an', 'the', 'and', 'or', 'but', 'nor', 'for', 'yet', 'so',
                'to', 'of', 'in', 'on', 'at', 'by', 'with', 'from', 'as', 'into',
                'through', 'during', 'before', 'after', 'above', 'below', 'between',
                'under', 'over', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
                'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
                'should', 'may', 'might', 'must', 'shall', 'can', 'your', 'you',
                'how', 'what', 'when', 'where', 'why', 'which', 'who', 'whom',
            }
            # Split title into words, filter out stop words
            words = title.lower().split()
            filtered_words = [w for w in words if w not in stop_words]
            # Clean each word (remove special chars)
            cleaned_words = [re.sub(r'[^a-z0-9]', '', w) for w in filtered_words]
            cleaned_words = [w for w in cleaned_words if w]  # Remove empty strings
            # Build slug by adding words until we hit 50 char limit
            slug_parts = []
            current_length = 0
            for word in cleaned_words:
                # +1 for the hyphen (except first word)
                addition = len(word) + (1 if slug_parts else 0)
                if current_length + addition <= 50:
                    slug_parts.append(word)
                    current_length += addition
                else:
                    break
            slug = '-'.join(slug_parts)
        if check_duplicates and self.check_duplicate_post(slug):
            raise ClientError(f"WordPress post with slug '{slug}' already exists")

        # 5. Resolve category and tags to IDs
        category_id = self.resolve_category_by_name(category_name)
        tag_names = [t.strip() for t in tags_str.split(",") if t.strip()]
        tag_ids = [self.resolve_tag_by_name(name) for name in tag_names]

        # 6. Determine schedule date
        effective_date = None
        effective_status = status
        if auto_schedule:
            effective_date = self.find_next_schedule_slot()
            effective_status = "future"
        elif date:
            effective_date = date
            effective_status = "future"

        # 7. Get content as markdown
        markdown_content = self.get_article_markdown(page_id)

        # 8. Process images - download from Notion, upload to WordPress
        from .utils.images import process_images_for_wordpress
        markdown_content = process_images_for_wordpress(
            markdown_content=markdown_content,
            article_slug=slug,
            verbose=True
        )

        # 9. Save to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(markdown_content)
            temp_path = f.name

        try:
            # 10. Build wordpress CLI command
            args = [
                "posts", "create",
                "--from-markdown", temp_path,
                "--title", title,
                "--slug", slug,
                "--status", effective_status,
                "--categories", str(category_id),
                "--tags", ",".join(str(t) for t in tag_ids),
                "--excerpt", excerpt,
                "--meta", f"rank_math_focus_keyword={keywords}",
            ]
            if effective_date:
                args.extend(["--date", effective_date])

            result = self._run_wordpress(args)
            post = json.loads(result.stdout)
            post_id = post.get("id")

            # 10b. Clear schedule reservation now that post is committed to WordPress
            if auto_schedule:
                self.clear_schedule_reservation()

            # 11. Attach featured image and apply schema in a single update call
            fi_status = {"attached": False}
            schema_status = {"type": schema_type_str, "applied": False}

            if featured_image_result or schema_type_str:
                update_args = ["posts", "update"]

                if featured_image_result:
                    update_args.extend(["--featured-media", str(featured_image_result["id"])])
                    fi_status["media_id"] = featured_image_result["id"]
                    fi_status["source_url"] = featured_image_result.get("source_url")

                # Build schema JSON
                from .commands.schema import _build_schema_json, SchemaType, ProficiencyLevel
                schema_type_map = {
                    "Article": SchemaType.ARTICLE,
                    "TechArticle": SchemaType.TECH_ARTICLE,
                    "Review": SchemaType.REVIEW,
                }
                schema_enum = schema_type_map.get(schema_type_str, SchemaType.ARTICLE)
                proficiency = ProficiencyLevel.INTERMEDIATE if schema_enum == SchemaType.TECH_ARTICLE else None
                schema_json = _build_schema_json(schema_type=schema_enum, proficiency=proficiency)
                update_args.extend(["--meta", f"rank_math_schemas={schema_json}"])
                update_args.append(str(post_id))

                update_result = self._run_wordpress(update_args)
                updated_post = json.loads(update_result.stdout)
                attached_media_id = int(updated_post.get("featured_media") or 0)
                expected_media_id = int(featured_image_result["id"])
                if attached_media_id != expected_media_id:
                    raise ClientError(
                        "Featured image attachment failed: "
                        f"post {post_id} has featured_media "
                        f"{attached_media_id}, expected {expected_media_id}"
                    )
                fi_status["attached"] = True
                schema_status["applied"] = True

            # 12. Update Notion with Published status and URL
            wp_url = post.get("link") or post.get("url", "")
            wp_edit_url = f"https://adamtheautomator.com/wp-admin/post.php?post={post_id}&action=edit"
            self._run_notion([
                "database", "page", "update", page_id,
                "--status", "Status:Published",
                "--url", f"Published URL:{wp_url}"
            ])

            result_dict = {
                "wordpress_post": post,
                "notion_page_id": page_id,
                "status": effective_status,
                "scheduled_date": effective_date,
                "wordpress_url": wp_url,
                "wordpress_edit_url": wp_edit_url,
                "warnings": warnings,
            }

            result_dict["featured_image"] = fi_status

            if schema_type_str:
                result_dict["schema"] = schema_status

            return result_dict
        finally:
            Path(temp_path).unlink(missing_ok=True)

    @staticmethod
    def _slug_from_url(url: str, required: bool = True) -> Optional[str]:
        """Derive a WordPress slug from a post URL.

        Handles trailing slashes and query/fragment suffixes. Raises if the
        URL has no usable path segment, unless required=False — a scheduled
        WordPress post carries a slugless ?p=<id> permalink until it goes
        live, and callers that only compare slugs pass required=False to get
        None instead of an error.
        """
        from urllib.parse import urlparse

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

        Returns one of: "notion_page", "wordpress_id", "wordpress_url",
        "slug". Detection is deterministic and fails fast for empty input.
        """
        import re

        value = identifier.strip()
        if not value:
            raise ClientError("Target identifier must not be empty")

        if value.lower().startswith(("http://", "https://")):
            return "wordpress_url"

        # Pure integer -> WordPress post ID.
        if value.isdigit():
            return "wordpress_id"

        # 32-hex Notion page ID, dashed or undashed.
        compact = value.replace("-", "")
        if len(compact) == 32 and re.fullmatch(r"[0-9a-fA-F]{32}", compact):
            return "notion_page"

        # Everything else is treated as a WordPress slug.
        return "slug"

    def _wordpress_post_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        """Return the WordPress post matching an exact slug, or None."""
        result = self._run_wordpress(
            ["posts", "list", "--filter", f"slug:eq:{slug}", "--limit", "2"]
        )
        posts = json.loads(result.stdout)
        if not posts:
            return None
        return posts[0]

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
        """Resolve an identifier to both the Notion page and WordPress post.

        Returns a dict:
            {
              "id_kind": "...",
              "notion_page": <article dict>,        # required, always resolved
              "wordpress_post": <post dict> | None, # None if WP side absent
            }

        Fails fast (ClientError) when the Notion page cannot be resolved. A
        missing WordPress post is returned as None (already absent), not an
        error, so the Notion reset can still proceed.
        """
        kind = self.detect_id_kind(identifier)

        notion_page: Optional[Dict[str, Any]] = None
        wordpress_post: Optional[Dict[str, Any]] = None

        if kind == "notion_page":
            notion_page = self.get_article(identifier)
            published_url = notion_page.get("Published URL")
            if published_url:
                slug = self._slug_from_url(published_url)
                wordpress_post = self._wordpress_post_by_slug(slug)
            # No Published URL -> WP post cannot be resolved; treat as absent.
        else:
            # WordPress-first kinds: resolve the WP post, then the Notion page
            # by matching its Published URL.
            if kind == "wordpress_id":
                result = self._run_wordpress(["posts", "get", identifier])
                wordpress_post = json.loads(result.stdout)
            elif kind == "wordpress_url":
                slug = self._slug_from_url(identifier)
                wordpress_post = self._wordpress_post_by_slug(slug)
            elif kind == "slug":
                wordpress_post = self._wordpress_post_by_slug(identifier)
            else:  # pragma: no cover - detect_id_kind enumerates all kinds
                raise ClientError(f"Unhandled identifier kind: {kind}")

            if not wordpress_post:
                raise ClientError(
                    f"Could not resolve a WordPress post from {identifier!r} "
                    f"(kind: {kind})"
                )

            wp_url = wordpress_post.get("link") or wordpress_post.get("url")
            if not wp_url:
                raise ClientError(
                    "Resolved WordPress post has no link/url; cannot match a "
                    "Notion page"
                )
            notion_page = self._notion_page_by_published_url(wp_url)

        if not notion_page:
            raise ClientError(
                f"Could not resolve a Notion page for {identifier!r} "
                f"(kind: {kind})"
            )

        return {
            "id_kind": kind,
            "notion_page": notion_page,
            "wordpress_post": wordpress_post,
        }

    def unpublish_article(
        self,
        identifier: str,
        status: str = "Draft",
        force: bool = False,
        keep_wordpress: bool = False,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Revert a published article: trash the WP post and reset Notion.

        Args:
            identifier: Notion page ID, WordPress post ID, URL, or slug.
            status: Notion status to set (validated against live statuses).
            force: Permanently delete the WordPress post instead of trashing.
            keep_wordpress: Skip the WordPress trash/delete step entirely.
            dry_run: Resolve and report planned changes without mutating.

        Returns the JSON summary described in the command docstring.
        """
        # Validate the target Notion status against the live schema before any
        # side effects (fail-fast, reusing the existing status path).
        valid_statuses = self.get_valid_statuses()
        if status not in valid_statuses:
            raise ClientError(
                f"Invalid status '{status}'. Valid statuses: "
                f"{', '.join(valid_statuses)}"
            )

        resolved = self.resolve_unpublish_target(identifier)
        notion_page = resolved["notion_page"]
        wordpress_post = resolved["wordpress_post"]
        page_id = notion_page.get("id")
        if not page_id:
            raise ClientError("Resolved Notion page is missing an id")

        cleared_fields = list(self.UNPUBLISH_ARTIFACT_FIELDS.keys())

        # Determine the WordPress action.
        if keep_wordpress:
            wp_action = "skipped"
            wp_post_id = wordpress_post.get("id") if wordpress_post else None
        elif not wordpress_post:
            wp_action = "already_absent"
            wp_post_id = None
        else:
            wp_post_id = wordpress_post.get("id")
            wp_status = wordpress_post.get("status")
            if wp_status == "trash":
                wp_action = "already_absent"
            else:
                wp_action = "deleted" if force else "trashed"

        if dry_run:
            return {
                "dry_run": True,
                "id_kind": resolved["id_kind"],
                "wordpress": {"post_id": wp_post_id, "action": wp_action},
                "notion": {
                    "page_id": page_id,
                    "status": status,
                    "cleared_fields": cleared_fields,
                },
            }

        # Execute WordPress trash/delete.
        if wp_action in ("trashed", "deleted"):
            delete_args = ["posts", "delete", str(wp_post_id)]
            if force:
                delete_args.append("--force")
            try:
                self._run_wordpress(delete_args)
            except ClientError as exc:
                # If the post is already gone, continue to the Notion reset.
                if "404" in str(exc) or "not found" in str(exc).lower():
                    wp_action = "already_absent"
                else:
                    raise

        # Reset Notion: status + data-driven artifact field clearing. The
        # property builder resolves each field's type from the live schema and
        # emits the correct typed null/empty or checkbox bool.
        self.update_article(
            page_id,
            status=status,
            properties=dict(self.UNPUBLISH_ARTIFACT_FIELDS),
        )

        return {
            "dry_run": False,
            "id_kind": resolved["id_kind"],
            "wordpress": {"post_id": wp_post_id, "action": wp_action},
            "notion": {
                "page_id": page_id,
                "status": status,
                "cleared_fields": cleared_fields,
            },
        }


_client: Optional[AtaBlogClient] = None


def get_client() -> AtaBlogClient:
    global _client
    if _client is None:
        _client = AtaBlogClient()
    return _client
