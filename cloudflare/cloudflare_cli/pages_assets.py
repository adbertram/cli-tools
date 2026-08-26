"""Local asset preparation for Cloudflare Pages direct-upload deployments.

Implements the file-discovery and hashing half of the direct-upload protocol
mirrored from wrangler 4.125.0 (src/pages/validate.ts, src/pages/hash.ts,
src/pages/upload.ts inside wrangler-dist/cli.js):

- Per-file hash: ``blake3(base64(content) + extension_without_dot).hexdigest()[:32]``
  (byte-for-byte verified against the blake3-wasm build bundled in wrangler).
- Ignore rules: root-level ``_worker.js``/``_redirects``/``_headers``/
  ``_routes.json``/``functions``/``.wrangler``, plus ``.DS_Store``,
  ``node_modules``, and ``.git`` at any depth; symlinks are skipped.
- Limits: files over 25 MiB are rejected (Pages hard cap); upload batches hold
  at most 40 MiB of payload or 2000 files, largest files first.

Also implements the Advanced Mode worker-script half of the protocol
(`read_worker_script`): a root-level `_worker.js` is excluded from the static
asset manifest above (it is not a static file — Cloudflare routes every
request to it once it exists) and is instead uploaded as a separate
"_worker.bundle" multipart part built by `client.build_worker_bundle`. Only a
single self-contained `_worker.js` file is supported; a `_worker.js/`
directory or a `functions/` directory (Pages Functions) both require
wrangler's esbuild bundling step, which this CLI does not implement, and are
rejected with a clear error instead of being silently ignored.

No network access happens in this module; API calls live in client.py.
"""
import base64
import mimetypes
import re
from pathlib import Path
from typing import Dict, List, Optional

import blake3

from cli_tools_shared.exceptions import ClientError

# Pages rejects any single asset above 25 MiB (wrangler MAX_ASSET_SIZE).
MAX_ASSET_SIZE = 25 * 1024 * 1024
# Upload batches mirror wrangler's buckets: <=40 MiB total bytes and <=2000
# files per POST /pages/assets/upload call.
MAX_BUCKET_SIZE = 40 * 1024 * 1024
MAX_BUCKET_FILE_COUNT = 2000
# Fallback deployment file-count limit when the upload token carries no
# max_file_count_allowed claim (wrangler MAX_ASSET_COUNT_DEFAULT).
DEFAULT_FILE_COUNT_LIMIT = 20000

# Root-only ignores (minimatch patterns without a ** prefix match exactly one
# path segment relative to the deploy directory).
IGNORED_ROOT_ONLY = {"_worker.js", "_redirects", "_headers", "_routes.json", "functions", ".wrangler"}
# Any-depth ignores matched on path segment / basename.
IGNORED_ANY_DEPTH_SEGMENTS = {"node_modules", ".git"}
IGNORED_BASENAMES = {".DS_Store"}

# Common web MIME overrides aligned with the mime-db table wrangler ships
# (npm mime@3). Python's stdlib mimetypes varies by OS, so key web types are
# pinned here; anything else falls back to stdlib, then octet-stream.
_MIME_OVERRIDES = {
    "avif": "image/avif",
    "bmp": "image/bmp",
    "css": "text/css",
    "csv": "text/csv",
    "gif": "image/gif",
    "gz": "application/gzip",
    "htm": "text/html",
    "html": "text/html",
    "ico": "image/x-icon",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "js": "application/javascript",
    "json": "application/json",
    "map": "application/json",
    "md": "text/markdown",
    "mjs": "application/javascript",
    "mp3": "audio/mpeg",
    "mp4": "video/mp4",
    "ogg": "audio/ogg",
    "otf": "font/otf",
    "pdf": "application/pdf",
    "png": "image/png",
    "rss": "application/rss+xml",
    "svg": "image/svg+xml",
    "ttf": "font/ttf",
    "txt": "text/plain",
    "wasm": "application/wasm",
    "wav": "audio/wav",
    "webm": "video/webm",
    "webmanifest": "application/manifest+json",
    "webp": "image/webp",
    "woff": "font/woff",
    "woff2": "font/woff2",
    "xml": "text/xml",
    "zip": "application/zip",
}


def guess_content_type(name: str) -> str:
    """Return the upload metadata content type for a file name."""
    basename = name.rsplit("/", 1)[-1]
    ext = basename.rsplit(".", 1)[-1].lower() if "." in basename else ""
    if ext in _MIME_OVERRIDES:
        return _MIME_OVERRIDES[ext]
    guessed = mimetypes.guess_type(basename)[0]
    return guessed or "application/octet-stream"


def hash_file(path: Path) -> str:
    """Hash a file exactly like wrangler's pages hashFile.

    The hash covers base64(content) with the extension (without dot)
    concatenated, truncated to 32 hex chars. Verified byte-parity against the
    blake3-wasm build bundled in wrangler 4.125.0.
    """
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    ext = path.suffix[1:] if path.suffix else ""
    return blake3.blake3((b64 + ext).encode("utf-8")).hexdigest()[:32]


def _is_ignored(rel_posix: str) -> bool:
    """Apply wrangler's minimatch IGNORE_LIST to one relative posix path."""
    if rel_posix in IGNORED_ROOT_ONLY:
        return True
    if rel_posix.rsplit("/", 1)[-1] in IGNORED_BASENAMES:
        return True
    segments = set(rel_posix.split("/"))
    return bool(segments & IGNORED_ANY_DEPTH_SEGMENTS)


def collect_files(directory: Path) -> List[Dict]:
    """Walk a directory and return uploadable asset records.

    Each record is {"path" (absolute), "rel" (posix relative), "size",
    "content_type", "hash"} sorted by relative path for deterministic output.

    Raises ClientError for a missing directory, an empty tree, or any file
    over MAX_ASSET_SIZE.
    """
    root = directory.resolve()
    if not root.is_dir():
        raise ClientError(f"Deployment directory does not exist or is not a directory: {root}")

    assets: List[Dict] = []

    def walk(current: Path) -> None:
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError as e:
            raise ClientError(f"Cannot read directory {current}: {e}")
        for entry in entries:
            if entry.is_symlink():
                continue
            rel = entry.relative_to(root).as_posix()
            if _is_ignored(rel):
                continue
            if entry.is_dir():
                walk(entry)
                continue
            size = entry.stat().st_size
            if size > MAX_ASSET_SIZE:
                raise ClientError(
                    f"Cloudflare Pages only supports files up to "
                    f"{MAX_ASSET_SIZE // (1024 * 1024)} MiB: "
                    f"{rel} is {size} bytes"
                )
            assets.append(
                {
                    "path": str(entry),
                    "rel": rel,
                    "size": size,
                    "content_type": guess_content_type(rel),
                    "hash": hash_file(entry),
                }
            )

    walk(root)

    if not assets:
        raise ClientError(f"No uploadable files found in directory: {root}")
    return assets


def bucket_files(assets: List[Dict]) -> List[List[Dict]]:
    """Group assets into bounded upload batches (largest first).

    Mirrors wrangler's bucketing intent: every batch stays within both
    MAX_BUCKET_SIZE bytes and MAX_BUCKET_FILE_COUNT files.
    """
    ordered = sorted(assets, key=lambda f: f["size"], reverse=True)
    buckets: List[List[Dict]] = []
    current: List[Dict] = []
    current_size = 0
    for asset in ordered:
        if current and (
            current_size + asset["size"] > MAX_BUCKET_SIZE
            or len(current) >= MAX_BUCKET_FILE_COUNT
        ):
            buckets.append(current)
            current = []
            current_size = 0
        current.append(asset)
        current_size += asset["size"]
    if current:
        buckets.append(current)
    return buckets


def build_upload_payload(assets: List[Dict]) -> List[Dict]:
    """Build the JSON body for one POST /pages/assets/upload batch."""
    payload = []
    for asset in assets:
        data = Path(asset["path"]).read_bytes()
        payload.append(
            {
                "key": asset["hash"],
                "value": base64.b64encode(data).decode("ascii"),
                "metadata": {"contentType": asset["content_type"]},
                "base64": True,
            }
        )
    return payload


def build_manifest(assets: List[Dict]) -> Dict[str, str]:
    """Build the deployment manifest: {"/" + rel_path: hash}."""
    return {f"/{asset['rel']}": asset["hash"] for asset in assets}


# --- Advanced Mode worker script (_worker.js) ------------------------------
# Mirrors the relevant slice of wrangler's config-less deploy path
# (src/api/pages/deploy.ts): a root _worker.js activates "Advanced Mode",
# where Cloudflare routes every request to the worker instead of serving
# static assets/applying _headers/_redirects directly. wrangler bundles
# _worker.js with esbuild by default; this CLI does not implement a bundler,
# so it only supports a single self-contained _worker.js file with no
# external imports (wrangler's own `--no-bundle` shape), matching Adam's own
# scoping decision to prioritize _worker.js and explicitly reject
# `functions/` rather than silently ignore it.

WORKER_SCRIPT_FILENAME = "_worker.js"
FUNCTIONS_DIRNAME = "functions"
# Content type for the worker's ES module part in the nested "_worker.bundle"
# multipart body (moduleTypeMimeType.esm in wrangler's
# create-worker-upload-form.ts).
WORKER_MODULE_CONTENT_TYPE = "application/javascript+module"

# Matches an import/re-export specifier or a dynamic import() call. Mirrors
# the intent of wrangler's blockWorkerJsImports esbuild plugin
# (src/pages/functions/buildWorker.ts checkRawWorker): a raw, unbundled
# _worker.js can only resolve `node:*`/`cloudflare:*` built-ins at runtime, so
# any other import would fail once deployed. This is a source-level
# heuristic, not a real JS parser -- it exists to fail loudly before deploy
# rather than to catch every possible import syntax.
_IMPORT_SPECIFIER_PATTERN = re.compile(
    r"""(?:^|[;\s{}()])import\s*(?:[\w$*{}\s,]+from\s*)?['"]([^'"]+)['"]"""
    r"""|(?:^|[;\s{}()])export\s+(?:[\w$*{}\s,]+from\s*)?['"]([^'"]+)['"]"""
    r"""|\bimport\s*\(\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)

_ALLOWED_IMPORT_PREFIXES = ("node:", "cloudflare:")


def _check_worker_script_imports(script_path: str, content: str) -> None:
    """Reject a _worker.js that imports another module.

    Raises:
        ClientError: naming the first disallowed import specifier found.
    """
    for match in _IMPORT_SPECIFIER_PATTERN.finditer(content):
        specifier = next(g for g in match.groups() if g is not None)
        if specifier.startswith(_ALLOWED_IMPORT_PREFIXES):
            continue
        raise ClientError(
            f"{script_path} is not being bundled by this CLI but it is "
            f"importing from '{specifier}'.\nThis will throw an error if "
            "deployed.\nBundle the Worker into a single self-contained file "
            "before deploying (this CLI does not implement esbuild bundling), "
            "or deploy with `npx wrangler pages deploy` instead."
        )


def read_worker_script(directory: Path) -> Optional[Dict]:
    """Read a root-level `_worker.js` for Cloudflare Pages Advanced Mode.

    Returns:
        None when no `_worker.js` exists at the deploy directory root (plain
        static-asset deployment; unchanged behavior).
        Otherwise a dict: {"filename": "_worker.js", "content": bytes,
        "routes_json": Optional[str]}. `routes_json` carries the raw text of
        a root `_routes.json` file, which wrangler only uploads as its own
        part when a worker is present (an unbundled static site has no
        Functions/Worker layer for custom routes to affect).

    Raises:
        ClientError: `_worker.js` is a directory (multi-file Advanced Mode,
            which requires wrangler's esbuild bundling), a `functions/`
            directory exists with no `_worker.js` (Pages Functions, which
            also requires esbuild bundling), or `_worker.js` imports another
            module (see `_check_worker_script_imports`).
    """
    root = directory.resolve()
    worker_path = root / WORKER_SCRIPT_FILENAME
    functions_path = root / FUNCTIONS_DIRNAME

    if worker_path.is_dir():
        raise ClientError(
            f"{worker_path} is a directory (multi-file Cloudflare Pages "
            "Advanced Mode). This CLI only supports a single-file _worker.js "
            "and does not implement wrangler's esbuild bundling step. Bundle "
            "it into one file first, or deploy with `npx wrangler pages "
            "deploy` instead."
        )

    if not worker_path.is_file():
        if functions_path.is_dir():
            raise ClientError(
                f"{functions_path} exists but no _worker.js was found at the "
                "deploy directory root. Cloudflare Pages Functions require "
                "wrangler's esbuild bundling step, which this CLI does not "
                "implement. Bundle functions/ into a single _worker.js "
                "first, or deploy with `npx wrangler pages deploy` instead."
            )
        return None

    content = worker_path.read_text(encoding="utf-8")
    _check_worker_script_imports(str(worker_path), content)

    routes_path = root / "_routes.json"
    routes_json = routes_path.read_text(encoding="utf-8") if routes_path.is_file() else None

    return {
        "filename": WORKER_SCRIPT_FILENAME,
        "content": content.encode("utf-8"),
        "routes_json": routes_json,
    }
