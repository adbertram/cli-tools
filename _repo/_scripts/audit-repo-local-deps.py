#!/usr/bin/env python3
"""Audit cli-tools for repo-external references and retired shared-package paths."""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


REPO_ROOT = Path(__file__).resolve().parent.parent
SELF_PATH = Path(__file__).resolve()
PRUNE_DIRS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
}
RETIRED_SHARED_NAMES = (
    "-".join(("cli", "tools", "common")),
    "_".join(("cli", "tools", "common")),
)
RETIRED_SHARED_RE = re.compile(
    r"\b(" + "|".join(re.escape(name) for name in RETIRED_SHARED_NAMES) + r")\b"
)
RELATIVE_PATH_RE = re.compile(r"(?<![\w./-])((?:\.\./)+[A-Za-z0-9_./@-]+)")


@dataclass(frozen=True)
class Issue:
    category: str
    location: str
    detail: str


def _is_within_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT)
        return True
    except ValueError:
        return False


def _tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    files = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        files.append(REPO_ROOT / raw.decode())
    return sorted(files)


def _is_text_file(path: Path) -> bool:
    chunk = path.read_bytes()[:4096]
    return b"\0" not in chunk


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _add_issue(issues: set[Issue], category: str, path: Path, detail: str) -> None:
    issues.add(Issue(category=category, location=str(path.relative_to(REPO_ROOT)), detail=detail))


def _scan_text_file(path: Path, issues: set[Issue]) -> None:
    text = _read_text(path)
    rel = path.relative_to(REPO_ROOT)

    for match in RETIRED_SHARED_RE.finditer(text):
        _add_issue(
            issues,
            "retired_shared_reference",
            path,
            f"{rel}: contains obsolete shared-package reference `{match.group(1)}`",
        )

    for match in RELATIVE_PATH_RE.finditer(text):
        token = match.group(1)
        resolved = (path.parent / token).resolve(strict=False)
        if not _is_within_repo(resolved):
            _add_issue(
                issues,
                "relative_path_escapes_repo",
                path,
                f"{rel}: relative path `{token}` resolves outside repo to `{resolved}`",
            )


def _coerce_path_value(path: Path, raw: str) -> Path:
    if raw.startswith("file://"):
        parsed = urlparse(raw)
        if parsed.scheme != "file":
            raise ValueError(f"unsupported url `{raw}`")
        decoded = Path(unquote(parsed.path))
        return decoded if decoded.is_absolute() else (path.parent / decoded)
    candidate = Path(raw).expanduser()
    return candidate if candidate.is_absolute() else (path.parent / candidate)


def _walk_toml_paths(obj: Any, path: Path, issues: set[Issue], key_hint: str = "") -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            next_hint = f"{key_hint}.{key}" if key_hint else key
            if key in {"path", "editable"} and isinstance(value, str):
                resolved = _coerce_path_value(path, value).resolve(strict=False)
                if not _is_within_repo(resolved):
                    _add_issue(
                        issues,
                        "path_dependency_outside_repo",
                        path,
                        f"{path.relative_to(REPO_ROOT)}: `{next_hint} = {value}` resolves outside repo to `{resolved}`",
                    )
            elif key == "url" and isinstance(value, str) and value.startswith("file://"):
                resolved = _coerce_path_value(path, value).resolve(strict=False)
                if not _is_within_repo(resolved):
                    _add_issue(
                        issues,
                        "file_url_outside_repo",
                        path,
                        f"{path.relative_to(REPO_ROOT)}: `{next_hint} = {value}` resolves outside repo to `{resolved}`",
                    )
            _walk_toml_paths(value, path, issues, next_hint)
        return

    if isinstance(obj, list):
        for index, value in enumerate(obj):
            next_hint = f"{key_hint}[{index}]"
            _walk_toml_paths(value, path, issues, next_hint)


def _scan_toml_file(path: Path, issues: set[Issue]) -> None:
    data = tomllib.loads(_read_text(path))
    _walk_toml_paths(data, path, issues)


def _scan_filesystem_artifacts(issues: set[Issue]) -> None:
    retired_shared_dir = REPO_ROOT / RETIRED_SHARED_NAMES[0]
    if retired_shared_dir.exists():
        _add_issue(
            issues,
            "retired_shared_directory",
            retired_shared_dir,
            "repo contains retired shared-package directory",
        )

    for git_dir in REPO_ROOT.rglob(".git"):
        if git_dir == REPO_ROOT / ".git":
            continue
        _add_issue(
            issues,
            "nested_git_directory",
            git_dir,
            f"{git_dir.relative_to(REPO_ROOT)} is a nested git directory",
        )

    for link in REPO_ROOT.rglob("*"):
        if any(part in PRUNE_DIRS for part in link.parts):
            continue
        if not link.is_symlink():
            continue
        resolved = link.resolve(strict=False)
        if not _is_within_repo(resolved):
            _add_issue(
                issues,
                "symlink_points_outside_repo",
                link,
                f"{link.relative_to(REPO_ROOT)} resolves outside repo to `{resolved}`",
            )


def main() -> int:
    issues: set[Issue] = set()
    tracked_files = _tracked_files()

    for path in tracked_files:
        if not path.is_file() or not _is_text_file(path):
            continue
        if path.resolve() == SELF_PATH:
            continue
        _scan_text_file(path, issues)
        if path.name == "pyproject.toml" or path.name == "uv.lock":
            _scan_toml_file(path, issues)

    _scan_filesystem_artifacts(issues)

    if not issues:
        print("PASS: no repo-external path references or obsolete shared-package issues found")
        return 0

    print(f"FAIL: found {len(issues)} issue(s)")
    for issue in sorted(issues, key=lambda item: (item.category, item.location, item.detail)):
        print(f"- [{issue.category}] {issue.detail}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
