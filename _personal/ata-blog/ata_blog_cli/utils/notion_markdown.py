"""Markdown normalization for Notion API compatibility."""

from __future__ import annotations


def normalize_notion_markdown(markdown_content: str) -> str:
    """Normalize markdown before it is submitted to Notion."""

    lines = markdown_content.splitlines(keepends=True)
    normalized_lines: list[str] = []
    in_fence = False

    for line in lines:
        stripped = line.lstrip(" \t")
        indent = line[: len(line) - len(stripped)]

        if stripped.startswith("```"):
            if not in_fence:
                fence_tail = stripped[3:].strip()
                if fence_tail.lower() == "text":
                    newline = ""
                    if line.endswith("\r\n"):
                        newline = "\r\n"
                    elif line.endswith("\n"):
                        newline = "\n"
                    normalized_lines.append(f"{indent}```plain text{newline}")
                    in_fence = True
                    continue
                in_fence = True
            else:
                in_fence = False

        normalized_lines.append(line)

    return "".join(normalized_lines)

