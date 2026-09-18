#!/usr/bin/env python3
"""Refresh the root README tool catalog from current CLI tool folders.

Invoked by refresh_readme.sh with two positional arguments:

    refresh_readme.py <repo-root> <check-only>

where <check-only> is "1" to only verify that README.md is current (exit 1 when
it is not) and "0" to rewrite README.md in place.
"""

from __future__ import annotations

import re
import sys
import tempfile
import tomllib
from pathlib import Path


CATEGORY_HEADER = "## Tool Catalog"
NEXT_HEADER = "## Operating Standards"
UNCATEGORIZED = "Uncategorized"
EXCLUDED_PACKAGE_DIRS = {"cli-tools-shared"}


def markdown_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def canonical_command(folder: str, scripts: dict[str, str]) -> str:
    """Pick a single catalog command for a tool that may ship several aliases.

    A tool may legitimately define more than one console-script alias (for
    example gemini defines both ``gemini`` and ``gemini-api``, both pointing at
    ``gemini_cli.main:app``). Prefer the alias whose name matches the tool
    folder, then the shortest alias, then the first alphabetically, so the
    choice is deterministic regardless of table ordering.
    """
    if not scripts:
        raise ValueError("tool must define at least one project script")
    if folder in scripts:
        return folder
    return min(sorted(scripts), key=lambda name: (len(name), name))


def read_tool_metadata(root: Path) -> dict[str, dict[str, str]]:
    tools: dict[str, dict[str, str]] = {}
    for pyproject in sorted(root.glob("*/pyproject.toml")):
        folder = pyproject.parent.name
        if folder.startswith("_") or folder in EXCLUDED_PACKAGE_DIRS:
            continue

        data = tomllib.loads(pyproject.read_text())
        project = data["project"]
        scripts = project["scripts"]
        if not scripts:
            raise ValueError(f"{folder}/pyproject.toml must define at least one project script")

        command = canonical_command(folder, scripts)
        description = project["description"]
        tools[folder] = {
            "command": command,
            "description": markdown_escape(description),
        }
    return tools


def parse_existing_catalog(readme: str) -> tuple[list[str], dict[str, str], dict[str, str]]:
    categories: list[str] = []
    tool_categories: dict[str, str] = {}
    existing_rows: dict[str, str] = {}
    current_category: str | None = None

    for line in readme.splitlines():
        category_match = re.match(r"^### (.+)$", line)
        if category_match:
            current_category = category_match.group(1)
            if current_category not in categories:
                categories.append(current_category)
            continue

        row_match = re.match(r"^\| \[`([^`]+)`\]\([^)]+\) \| `[^`]+` \| .* \| .* \|$", line)
        if row_match and current_category:
            tool = row_match.group(1)
            existing_rows[tool] = line
            tool_categories[tool] = current_category

    return categories, tool_categories, existing_rows


def make_row(folder: str, metadata: dict[str, str], existing_rows: dict[str, str]) -> str:
    existing = existing_rows.get(folder)
    if existing:
        return existing

    command = markdown_escape(metadata["command"])
    description = metadata["description"]
    return (
        f"| [`{folder}`]({folder}/) | `{command}` | {description} | "
        "Uncategorized; update README.md with the correct command areas. |"
    )


def build_catalog(readme: str, tools: dict[str, dict[str, str]]) -> str:
    categories, tool_categories, existing_rows = parse_existing_catalog(readme)
    if UNCATEGORIZED not in categories:
        categories.append(UNCATEGORIZED)

    grouped: dict[str, list[str]] = {category: [] for category in categories}
    for folder in sorted(tools):
        category = tool_categories.get(folder, UNCATEGORIZED)
        grouped.setdefault(category, []).append(folder)

    lines = [CATEGORY_HEADER, ""]
    for category in categories:
        folders = grouped.get(category, [])
        if not folders:
            continue

        lines.extend(
            [
                f"### {category}",
                "",
                "| Tool | Command | What it does | Main command areas |",
                "| --- | --- | --- | --- |",
            ]
        )
        for folder in folders:
            lines.append(make_row(folder, tools[folder], existing_rows))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n\n"


def replace_catalog(readme: str, catalog: str) -> str:
    start = readme.index(f"{CATEGORY_HEADER}\n")
    end = readme.index(f"{NEXT_HEADER}\n", start)
    return readme[:start] + catalog + readme[end:]


def replace_count(readme: str, count: int) -> str:
    pattern = r"^- \d+ active CLI packages\.$"
    replacement = f"- {count} active CLI packages."
    updated, replacements = re.subn(pattern, replacement, readme, count=1, flags=re.MULTILINE)
    if replacements != 1:
        raise ValueError("README.md active CLI package count line was not found exactly once")
    return updated


def write_if_changed(path: Path, content: str, check_only: bool) -> int:
    original = path.read_text()
    if content == original:
        print("README.md is current")
        return 0

    if check_only:
        print("README.md is not current", file=sys.stderr)
        return 1

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(content)
        temp_path = Path(tmp.name)
    temp_path.replace(path)
    print("README.md refreshed")
    return 0


def main() -> int:
    root = Path(sys.argv[1])
    check_only = sys.argv[2] == "1"
    readme_path = root / "README.md"
    readme = readme_path.read_text()
    tools = read_tool_metadata(root)
    readme = replace_count(readme, len(tools))
    readme = replace_catalog(readme, build_catalog(readme, tools))
    return write_if_changed(readme_path, readme, check_only)


if __name__ == "__main__":
    raise SystemExit(main())
