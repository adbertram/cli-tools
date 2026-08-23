"""Chrome Web Store extension packaging."""
import fnmatch
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .client import ClientError
from .models.webstore import WebStorePackageResult


DEFAULT_PACKAGE_EXCLUDES = (
    ".DS_Store",
    ".*",
    ".*/**",
    ".env",
    ".env.*",
    ".git",
    ".git/**",
    ".github",
    ".github/**",
    ".chromium-profile",
    ".chromium-profile/**",
    ".venv",
    ".venv/**",
    "agent_workspaces",
    "agent_workspaces/**",
    "README.md",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "pyproject.toml",
    "uv.lock",
    "vitest.config.*",
    "playwright.config.*",
    "tsconfig.*",
    "node_modules",
    "node_modules/**",
    "_temp",
    "_temp/**",
    "tmp",
    "tmp/**",
    "temp",
    "temp/**",
    "__pycache__",
    "__pycache__/**",
    "tests",
    "tests/**",
    "plans",
    "plans/**",
    "dist",
    "dist/**",
    "build",
    "build/**",
    "coverage",
    "coverage/**",
    "playwright-report",
    "playwright-report/**",
    "test-results",
    "test-results/**",
    "store-assets",
    "store-assets/**",
    "__MACOSX",
    "__MACOSX/**",
    "*.pem",
)

REMOTE_SCRIPT_PATTERNS = (
    re.compile(r"<script\b[^>]*\bsrc=[\"']https?://", re.IGNORECASE),
    re.compile(r"\b(?:importScripts|import)\s*\(\s*[\"']https?://"),
)


def create_extension_package(
    extension_dir: Path,
    output_dir: Path,
    verify_commands: list[str],
    exclude_patterns: list[str],
) -> WebStorePackageResult:
    """Create a Chrome Web Store ZIP package for an unpacked extension."""
    extension_root = extension_dir.resolve()
    if not extension_root.is_dir():
        raise ClientError(f"Extension directory does not exist: {extension_dir}")

    manifest = read_manifest(extension_root)
    for verify_command in verify_commands:
        run_verify_command(verify_command, extension_root)

    package_files = discover_package_files(extension_root, exclude_patterns)
    assert_no_remote_hosted_scripts(extension_root, package_files)

    release_dir = resolve_output_dir(extension_root, output_dir)
    release_dir.mkdir(parents=True, exist_ok=True)
    zip_path = release_dir / get_release_zip_name(manifest)
    if zip_path.exists():
        zip_path.unlink()

    with ZipFile(zip_path, "w", ZIP_DEFLATED) as release_zip:
        for relative_file in package_files:
            release_zip.write(extension_root / relative_file, relative_file)

    return WebStorePackageResult(
        zip_path=str(zip_path),
        manifest_name=manifest["name"],
        manifest_version=manifest["version"],
        file_count=len(package_files),
        files=package_files,
    )


def read_manifest(extension_root: Path) -> dict:
    """Read and validate the extension manifest used for packaging."""
    manifest_path = extension_root / "manifest.json"
    if not manifest_path.is_file():
        raise ClientError(f"manifest.json not found in {extension_root}")

    manifest = json.loads(manifest_path.read_text())
    if manifest.get("manifest_version") != 3:
        raise ClientError("manifest.manifest_version must be 3")
    for field_name in ("name", "version"):
        if not isinstance(manifest.get(field_name), str) or len(manifest[field_name]) == 0:
            raise ClientError(f"manifest.{field_name} is required")

    parse_chrome_version(manifest["version"])
    return manifest


def discover_package_files(extension_root: Path, exclude_patterns: list[str]) -> list[str]:
    """Return sorted package files after applying Chrome Web Store exclusions."""
    all_patterns = tuple(DEFAULT_PACKAGE_EXCLUDES) + tuple(exclude_patterns)
    files = []
    for path in sorted(extension_root.rglob("*")):
        relative_path = path.relative_to(extension_root).as_posix()
        assert_safe_relative_path(relative_path)
        if is_excluded(relative_path, all_patterns):
            continue
        if path.is_symlink():
            raise ClientError(f"Package path is a symlink: {relative_path}")
        if path.is_file():
            files.append(relative_path)

    if "manifest.json" not in files:
        raise ClientError("manifest.json must be included at the package root")
    return files


def is_excluded(relative_path: str, patterns: tuple[str, ...]) -> bool:
    """Return whether a package-relative path is excluded by configured patterns."""
    return any(fnmatch.fnmatchcase(relative_path, pattern) for pattern in patterns)


def assert_no_remote_hosted_scripts(extension_root: Path, package_files: list[str]):
    """Reject remote hosted executable code in packaged JavaScript and HTML files."""
    for relative_file in package_files:
        if Path(relative_file).suffix not in (".html", ".js", ".mjs"):
            continue

        contents = (extension_root / relative_file).read_text()
        if REMOTE_SCRIPT_PATTERNS[0].search(contents):
            raise ClientError(f"Remote hosted script source found in {relative_file}")
        if REMOTE_SCRIPT_PATTERNS[1].search(contents):
            raise ClientError(f"Remote hosted script import found in {relative_file}")


def resolve_output_dir(extension_root: Path, output_dir: Path) -> Path:
    """Resolve package output relative to the extension root."""
    if output_dir.is_absolute():
        return output_dir
    return extension_root / output_dir


def get_release_zip_name(manifest: dict) -> str:
    """Build a deterministic release ZIP file name from manifest name and version."""
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", manifest["name"]).strip("-")
    if len(safe_name) == 0:
        raise ClientError("manifest.name does not contain a usable release file name")
    return f"{safe_name}-{manifest['version']}.zip"


def parse_chrome_version(version: str) -> list[int]:
    """Parse a Chrome extension version string."""
    parts = version.split(".")
    if len(parts) < 1 or len(parts) > 4:
        raise ClientError(f"Chrome version must have 1 to 4 numeric segments: {version}")

    parsed = []
    for part in parts:
        if re.fullmatch(r"0|[1-9][0-9]*", part) is None:
            raise ClientError(f"Chrome version segment must be a non-negative integer: {version}")
        value = int(part)
        if value > 65535:
            raise ClientError(f"Chrome version segment is out of range: {version}")
        parsed.append(value)

    return parsed


def run_verify_command(command: str, cwd: Path):
    """Run a repository verification command with stdout redirected away from CLI data output."""
    args = shlex.split(command)
    if len(args) == 0:
        raise ClientError("--verify-command must not be empty")
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if result.stdout:
        sys.stderr.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    if result.returncode != 0:
        raise ClientError(f"{command} failed with exit code {result.returncode}")


def assert_safe_relative_path(relative_path: str):
    """Validate a package-relative POSIX path."""
    if len(relative_path) == 0:
        raise ClientError("Package path must be a non-empty string")
    path = Path(relative_path)
    if path.is_absolute() or "\\" in relative_path:
        raise ClientError(f"Package path must be relative and POSIX-style: {relative_path}")
    normalized = Path(relative_path).as_posix()
    if normalized.startswith("../") or normalized == ".." or normalized != relative_path:
        raise ClientError(f"Unsafe package path: {relative_path}")
