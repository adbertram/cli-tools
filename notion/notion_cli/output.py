"""Output formatting helpers.

Re-exports standard output functions from cli_tools_shared.output.
CLI-specific helpers defined below.

Stream Usage:
    stdout (fd 1) -> Data only (JSON, tables) - via print_json(), print_table()
    stderr (fd 2) -> Messages only - via print_error(), print_warning(), print_success(), print_info()
"""

from cli_tools_shared.output import (  # noqa: F401
    console,
    _format_cell_value,
    _serialize_for_json,
    print_json,
    print_table,
    print_output,
    print_error,
    print_warning,
    print_success,
    print_info,
    handle_error,
)
from typing import Any, Dict, List, Optional
import re


# --- CLI-specific helpers ---


def extract_property_value(prop: Dict) -> Any:
    """
    Extract the value from a Notion property object.

    Args:
        prop: Notion property object

    Returns:
        Extracted value
    """
    prop_type = prop.get("type", "")

    if prop_type == "title":
        title_arr = prop.get("title", [])
        return "".join(t.get("plain_text", "") for t in title_arr)

    elif prop_type == "rich_text":
        text_arr = prop.get("rich_text", [])
        return "".join(t.get("plain_text", "") for t in text_arr)

    elif prop_type == "number":
        return prop.get("number")

    elif prop_type == "select":
        select = prop.get("select")
        return select.get("name") if select else None

    elif prop_type == "multi_select":
        options = prop.get("multi_select", [])
        return ", ".join(o.get("name", "") for o in options)

    elif prop_type == "status":
        status = prop.get("status")
        return status.get("name") if status else None

    elif prop_type == "date":
        date = prop.get("date")
        if date:
            start = date.get("start", "")
            end = date.get("end")
            return f"{start} - {end}" if end else start
        return None

    elif prop_type == "checkbox":
        return prop.get("checkbox", False)

    elif prop_type == "url":
        return prop.get("url")

    elif prop_type == "email":
        return prop.get("email")

    elif prop_type == "phone_number":
        return prop.get("phone_number")

    elif prop_type == "people":
        people = prop.get("people", [])
        return ", ".join(p.get("name", p.get("id", "")) for p in people)

    elif prop_type == "relation":
        relations = prop.get("relation", [])
        return ", ".join(r.get("id", "") for r in relations)

    elif prop_type == "formula":
        formula = prop.get("formula", {})
        formula_type = formula.get("type", "")
        return formula.get(formula_type)

    elif prop_type == "rollup":
        rollup = prop.get("rollup", {})
        rollup_type = rollup.get("type", "")
        return rollup.get(rollup_type)

    elif prop_type == "created_time":
        return prop.get("created_time")

    elif prop_type == "last_edited_time":
        return prop.get("last_edited_time")

    elif prop_type == "created_by":
        user = prop.get("created_by", {})
        return user.get("name", user.get("id", ""))

    elif prop_type == "last_edited_by":
        user = prop.get("last_edited_by", {})
        return user.get("name", user.get("id", ""))

    return None


def extract_rich_text(rich_text_array: List[Dict]) -> str:
    """
    Extract plain text from a rich_text array, preserving basic formatting.

    Args:
        rich_text_array: Array of rich_text objects

    Returns:
        Formatted text string with control characters removed
    """
    import re

    result = []
    for item in rich_text_array:
        text = item.get("plain_text", "")

        # Remove control characters (except newlines and tabs)
        # Keep: \n (10), \t (9), \r (13)
        # Remove: all other control characters (0-8, 11-12, 14-31)
        text = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F]', '', text)

        annotations = item.get("annotations", {})

        # Apply markdown formatting based on annotations
        if annotations.get("code"):
            text = f"`{text}`"
        if annotations.get("bold"):
            text = f"**{text}**"
        if annotations.get("italic"):
            text = f"*{text}*"
        if annotations.get("strikethrough"):
            text = f"~~{text}~~"

        # Handle links
        href = item.get("href")
        if href and not annotations.get("code"):
            text = f"[{text}]({href})"

        result.append(text)

    return "".join(result)


def block_to_markdown(block: Dict, indent_level: int = 0, list_number: int = 0) -> str:
    """
    Convert a Notion block to markdown.

    Args:
        block: Notion block object
        indent_level: Current indentation level for nested blocks
        list_number: Sequential number for numbered list items (1-based)

    Returns:
        Markdown string representation of the block
    """
    block_type = block.get("type", "")
    indent = "  " * indent_level
    lines = []

    if block_type == "paragraph":
        text = extract_rich_text(block.get("paragraph", {}).get("rich_text", []))
        lines.append(f"{indent}{text}")

    elif block_type == "heading_1":
        body = block.get("heading_1", {})
        text = extract_rich_text(body.get("rich_text", []))
        marker = "▶ " if body.get("is_toggleable") else ""
        lines.append(f"{indent}# {marker}{text}")

    elif block_type == "heading_2":
        body = block.get("heading_2", {})
        text = extract_rich_text(body.get("rich_text", []))
        marker = "▶ " if body.get("is_toggleable") else ""
        lines.append(f"{indent}## {marker}{text}")

    elif block_type == "heading_3":
        body = block.get("heading_3", {})
        text = extract_rich_text(body.get("rich_text", []))
        marker = "▶ " if body.get("is_toggleable") else ""
        lines.append(f"{indent}### {marker}{text}")

    elif block_type == "bulleted_list_item":
        text = extract_rich_text(block.get("bulleted_list_item", {}).get("rich_text", []))
        lines.append(f"{indent}- {text}")

    elif block_type == "numbered_list_item":
        text = extract_rich_text(block.get("numbered_list_item", {}).get("rich_text", []))
        num = list_number if list_number > 0 else 1
        lines.append(f"{indent}{num}. {text}")

    elif block_type == "to_do":
        todo = block.get("to_do", {})
        text = extract_rich_text(todo.get("rich_text", []))
        checked = "x" if todo.get("checked", False) else " "
        lines.append(f"{indent}- [{checked}] {text}")

    elif block_type == "toggle":
        text = extract_rich_text(block.get("toggle", {}).get("rich_text", []))
        lines.append(f"{indent}**{text}**")

    elif block_type == "quote":
        text = extract_rich_text(block.get("quote", {}).get("rich_text", []))
        lines.append(f"{indent}> {text}")

    elif block_type == "callout":
        callout = block.get("callout", {})
        text = extract_rich_text(callout.get("rich_text", []))
        icon = callout.get("icon") or {}
        emoji = icon.get("emoji", "") if icon.get("type") == "emoji" else ""
        lines.append(f"{indent}> {emoji} {text}")

    elif block_type == "code":
        code = block.get("code", {})
        text = extract_rich_text(code.get("rich_text", []))
        language = code.get("language", "")
        lines.append(f"{indent}```{language}")
        lines.append(text)
        lines.append(f"{indent}```")

    elif block_type == "divider":
        lines.append(f"{indent}---")

    elif block_type == "image":
        image = block.get("image", {})
        image_type = image.get("type", "")
        url = ""
        if image_type == "external":
            url = image.get("external", {}).get("url", "")
        elif image_type == "file":
            url = image.get("file", {}).get("url", "")
        caption = extract_rich_text(image.get("caption", []))
        lines.append(f"{indent}![{caption}]({url})")

    elif block_type == "bookmark":
        url = block.get("bookmark", {}).get("url", "")
        caption = extract_rich_text(block.get("bookmark", {}).get("caption", []))
        if caption:
            lines.append(f"{indent}<!-- notion-bookmark: {url} caption={caption} -->")
        else:
            lines.append(f"{indent}<!-- notion-bookmark: {url} -->")

    elif block_type == "link_preview":
        url = block.get("link_preview", {}).get("url", "")
        lines.append(f"{indent}<!-- notion-link_preview: {url} -->")

    elif block_type == "table":
        # Process table with its row children
        table_data = block.get("table", {})
        has_column_header = table_data.get("has_column_header", False)
        table_width = table_data.get("table_width", 0)
        children = block.get("children", [])

        for i, child in enumerate(children):
            if child.get("type") == "table_row":
                cells = child.get("table_row", {}).get("cells", [])
                row_text = " | ".join(extract_rich_text(cell) for cell in cells)
                lines.append(f"{indent}| {row_text} |")

                # Add separator after header row
                if i == 0 and has_column_header:
                    separator = " | ".join("---" for _ in cells)
                    lines.append(f"{indent}| {separator} |")

        # Return early - we've already processed children
        return "\n".join(lines)

    elif block_type == "table_row":
        # Standalone table_row (shouldn't normally happen, but handle it)
        cells = block.get("table_row", {}).get("cells", [])
        row_text = " | ".join(extract_rich_text(cell) for cell in cells)
        lines.append(f"{indent}| {row_text} |")

    elif block_type == "child_page":
        title = block.get("child_page", {}).get("title", "Untitled")
        lines.append(f"{indent}[📄 {title}]")

    elif block_type == "child_database":
        title = block.get("child_database", {}).get("title", "Untitled")
        lines.append(f"{indent}[📊 {title}]")

    elif block_type == "embed":
        url = block.get("embed", {}).get("url", "")
        lines.append(f"{indent}<!-- notion-embed: {url} -->")

    elif block_type == "video":
        video = block.get("video", {})
        video_type = video.get("type", "")
        url = ""
        if video_type == "external":
            url = video.get("external", {}).get("url", "")
        elif video_type == "file":
            url = video.get("file", {}).get("url", "")
        lines.append(f"{indent}<!-- notion-video: {url} -->")

    elif block_type == "file":
        file_block = block.get("file", {})
        file_type = file_block.get("type", "")
        url = ""
        if file_type == "external":
            url = file_block.get("external", {}).get("url", "")
        elif file_type == "file":
            url = file_block.get("file", {}).get("url", "")
        caption = extract_rich_text(file_block.get("caption", []))
        if caption:
            lines.append(f"{indent}<!-- notion-file: {url} caption={caption} -->")
        else:
            lines.append(f"{indent}<!-- notion-file: {url} -->")

    elif block_type == "pdf":
        pdf = block.get("pdf", {})
        pdf_type = pdf.get("type", "")
        url = ""
        if pdf_type == "external":
            url = pdf.get("external", {}).get("url", "")
        elif pdf_type == "file":
            url = pdf.get("file", {}).get("url", "")
        lines.append(f"{indent}<!-- notion-pdf: {url} -->")

    elif block_type == "equation":
        expression = block.get("equation", {}).get("expression", "")
        lines.append(f"{indent}$${expression}$$")

    elif block_type == "synced_block":
        # Synced blocks contain children
        pass

    elif block_type == "column_list":
        # Column lists contain column children
        pass

    elif block_type == "column":
        # Columns contain children
        pass

    # Process nested children if present
    children = block.get("children", [])
    if children:
        child_list_counter = 0
        for child in children:
            if child.get("type") == "numbered_list_item":
                child_list_counter += 1
            else:
                child_list_counter = 0
            child_md = block_to_markdown(child, indent_level + 1, list_number=child_list_counter)
            if child_md:
                lines.append(child_md)


    return "\n".join(lines)


def blocks_to_markdown(blocks: List[Dict]) -> str:
    """
    Convert a list of Notion blocks to markdown.

    Args:
        blocks: List of Notion block objects

    Returns:
        Markdown string
    """
    lines = []
    list_counter = 0
    for block in blocks:
        if block.get("type") == "numbered_list_item":
            list_counter += 1
        else:
            list_counter = 0
        md = block_to_markdown(block, list_number=list_counter)
        if md:
            lines.append(md)
    return "\n\n".join(lines)


def text_to_rich_text(text: str, inherited_annotations: Dict = None) -> List[Dict]:
    """
    Convert markdown text to Notion rich_text array with formatting.

    Supports:
    - **bold** or __bold__
    - *italic* or _italic_
    - `code`
    - [link text](url)
    - ***bold italic***
    - Nested formatting (e.g., ***text with [link](url)***

    Args:
        text: Markdown text string
        inherited_annotations: Annotations to apply to all elements (for recursive calls)

    Returns:
        Notion rich_text array with annotations
    """
    import re

    if not text:
        return []

    if inherited_annotations is None:
        inherited_annotations = {}

    rich_text = []

    def apply_annotations(item: Dict, new_annotations: Dict) -> Dict:
        """Apply annotations to a rich_text item, merging with inherited."""
        merged = {**inherited_annotations, **new_annotations}
        # Only include non-empty annotations
        if merged:
            existing = item.get("annotations", {})
            item["annotations"] = {**existing, **merged}
        return item

    def process_inner(inner_text: str, annotations: Dict) -> List[Dict]:
        """Recursively process inner text with inherited annotations."""
        merged_annotations = {**inherited_annotations, **annotations}
        return text_to_rich_text(inner_text, merged_annotations)

    # Pattern to match markdown inline elements
    # Order matters: longer patterns first
    pattern = re.compile(
        r'(\*\*\*(.+?)\*\*\*)'  # Bold italic ***text***
        r'|(\*\*(.+?)\*\*)'     # Bold **text**
        r'|(__(.+?)__)'         # Bold __text__
        r'|(\*(.+?)\*)'         # Italic *text*
        r'|(_([^_]+)_)'         # Italic _text_
        r'|(`([^`]+)`)'         # Code `text`
        r'|(\[([^\]]+)\]\(([^)]+)\))'  # Link [text](url)
    )

    last_end = 0
    for match in pattern.finditer(text):
        # Add plain text before match
        if match.start() > last_end:
            plain = text[last_end:match.start()]
            if plain:
                item = {"type": "text", "text": {"content": plain}}
                if inherited_annotations:
                    item["annotations"] = {**inherited_annotations}
                rich_text.append(item)

        # Determine which group matched
        if match.group(2):  # Bold italic ***text***
            # Recursively process inner content
            inner_items = process_inner(match.group(2), {"bold": True, "italic": True})
            rich_text.extend(inner_items)
        elif match.group(4):  # Bold **text**
            inner_items = process_inner(match.group(4), {"bold": True})
            rich_text.extend(inner_items)
        elif match.group(6):  # Bold __text__
            inner_items = process_inner(match.group(6), {"bold": True})
            rich_text.extend(inner_items)
        elif match.group(8):  # Italic *text*
            inner_items = process_inner(match.group(8), {"italic": True})
            rich_text.extend(inner_items)
        elif match.group(10):  # Italic _text_
            inner_items = process_inner(match.group(10), {"italic": True})
            rich_text.extend(inner_items)
        elif match.group(12):  # Code `text`
            # Code blocks don't recurse - content is literal
            item = {
                "type": "text",
                "text": {"content": match.group(12)},
                "annotations": {**inherited_annotations, "code": True}
            }
            rich_text.append(item)
        elif match.group(14):  # Link [text](url)
            item = {
                "type": "text",
                "text": {"content": match.group(14), "link": {"url": match.group(15)}}
            }
            if inherited_annotations:
                item["annotations"] = {**inherited_annotations}
            rich_text.append(item)

        last_end = match.end()

    # Add remaining plain text
    if last_end < len(text):
        remaining = text[last_end:]
        if remaining:
            item = {"type": "text", "text": {"content": remaining}}
            if inherited_annotations:
                item["annotations"] = {**inherited_annotations}
            rich_text.append(item)

    # If no matches found, return plain text with inherited annotations
    if not rich_text:
        item = {"type": "text", "text": {"content": text}}
        if inherited_annotations:
            item["annotations"] = {**inherited_annotations}
        return [item]

    return rich_text


def _chunk_code_content(content: str, max_length: int = 2000) -> List[str]:
    """
    Split code block content into chunks of at most max_length characters.

    Notion concatenates rich_text segments directly (no separator), so
    the chunks must reconstruct the original content when joined. This
    function splits at newline boundaries when possible, falling back to
    hard character splits for lines that exceed max_length on their own.

    Args:
        content: The full code block text
        max_length: Maximum characters per chunk (Notion API limit is 2000)

    Returns:
        List of text chunks, each <= max_length characters, whose
        concatenation equals the original content
    """
    if len(content) <= max_length:
        return [content]

    chunks = []
    pos = 0
    total = len(content)

    while pos < total:
        # If the remainder fits in one chunk, take it all
        if total - pos <= max_length:
            chunks.append(content[pos:])
            break

        # Find the best split point within [pos, pos + max_length)
        end = pos + max_length

        # Look for the last newline within the allowed window
        split_at = content.rfind("\n", pos, end)

        if split_at > pos:
            # Split after the newline (include it in this chunk)
            chunks.append(content[pos:split_at + 1])
            pos = split_at + 1
        else:
            # No newline found in window -- hard split at max_length
            chunks.append(content[pos:end])
            pos = end

    return chunks


def text_to_blocks(
    text: str,
    image_uploads: Optional[Dict[str, str]] = None,
    is_toggleable: bool = False,
) -> List[Dict]:
    """
    Convert text/markdown to Notion block objects with nested list support.

    Supports:
    - Paragraphs (blank line separated)
    - Headings (# ## ###)
    - Bulleted lists (- or *) with nesting via indentation
    - Numbered lists (1. 2. etc) with nesting via indentation
    - Code blocks (```)
    - Blockquotes (>)
    - Horizontal rules (---)
    - Todo items (- [ ] or - [x])
    - Tables (| col1 | col2 |)
    - Images (![alt](url) or ![alt](local_path))
    - Inline formatting: **bold**, *italic*, `code`, [links](url)

    Args:
        text: Text or markdown content
        image_uploads: Optional mapping of local file paths to Notion file_upload IDs.
                      When provided, local image paths will use file_upload blocks.
        is_toggleable: If True, every emitted heading_1/heading_2/heading_3 block
                      will be created as a toggle heading (the right-arrow that
                      collapses the content underneath in the Notion UI).

    Returns:
        List of Notion block objects
    """
    import re

    def get_indent_level(line: str) -> int:
        """Calculate indentation level (each 2 spaces or 1 tab = 1 level)."""
        spaces = len(line) - len(line.lstrip())
        # Count tabs as 2 spaces worth
        tabs = line.count('\t')
        spaces = spaces - tabs + (tabs * 2)
        return spaces // 2

    def parse_list_item(line: str, stripped: str) -> Optional[Dict]:
        """Parse a line as a list item, returns block dict or None."""
        # Todo item (checked)
        if re.match(r'^[-*]\s*\[x\]\s+', stripped, re.IGNORECASE):
            text_content = re.sub(r'^[-*]\s*\[x\]\s+', '', stripped, flags=re.IGNORECASE)
            return {
                "object": "block",
                "type": "to_do",
                "to_do": {
                    "rich_text": text_to_rich_text(text_content),
                    "checked": True,
                }
            }

        # Todo item (unchecked)
        if re.match(r'^[-*]\s*\[\s?\]\s+', stripped):
            text_content = re.sub(r'^[-*]\s*\[\s?\]\s+', '', stripped)
            return {
                "object": "block",
                "type": "to_do",
                "to_do": {
                    "rich_text": text_to_rich_text(text_content),
                    "checked": False,
                }
            }

        # Bulleted list
        if stripped.startswith("- ") or stripped.startswith("* "):
            return {
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": text_to_rich_text(stripped[2:]),
                }
            }

        # Numbered list
        match = re.match(r'^(\d+)\.\s+(.+)$', stripped)
        if match:
            return {
                "object": "block",
                "type": "numbered_list_item",
                "numbered_list_item": {
                    "rich_text": text_to_rich_text(match.group(2)),
                }
            }

        return None

    def is_list_item(stripped: str) -> bool:
        """Check if a line is any type of list item."""
        if stripped.startswith("- ") or stripped.startswith("* "):
            return True
        if re.match(r'^[-*]\s*\[[ x]\]\s+', stripped, re.IGNORECASE):
            return True
        if re.match(r'^\d+\.\s+', stripped):
            return True
        return False

    def create_code_block(language: str, code_content: str) -> Dict:
        code_chunks = _chunk_code_content(code_content)
        return {
            "object": "block",
            "type": "code",
            "code": {
                "rich_text": [
                    {"type": "text", "text": {"content": chunk}}
                    for chunk in code_chunks
                ],
                "language": language,
            }
        }

    def parse_code_block(start_idx: int) -> tuple:
        opening_line = lines[start_idx]
        opening_indent = opening_line[:len(opening_line) - len(opening_line.lstrip())]
        language = opening_line.strip()[3:].strip() or "plain text"
        code_lines = []
        i = start_idx + 1

        while i < len(lines) and not lines[i].strip().startswith("```"):
            code_line = lines[i]
            if opening_indent and code_line.startswith(opening_indent):
                code_line = code_line[len(opening_indent):]
            code_lines.append(code_line)
            i += 1

        return create_code_block(language, "\n".join(code_lines)), min(i + 1, len(lines))

    def collect_nested_children(lines: List[str], start_idx: int, parent_indent: int) -> tuple:
        """
        Collect all nested children under a parent list item.
        Returns (children_blocks, next_index).
        """
        children = []
        i = start_idx

        while i < len(lines):
            line = lines[i]
            if not line.strip():
                i += 1
                continue

            current_indent = get_indent_level(line)
            stripped = line.strip()

            # If we're back to parent level or less, stop collecting
            if current_indent <= parent_indent:
                break

            if stripped.startswith("```"):
                block, i = parse_code_block(i)
                children.append(block)
                continue

            # Parse this line as a list item
            block = parse_list_item(line, stripped)
            if block:
                # Check for nested children under this item
                if i + 1 < len(lines):
                    nested_children, i = collect_nested_children(lines, i + 1, current_indent)
                    if nested_children:
                        block_type = block["type"]
                        block[block_type]["children"] = nested_children
                else:
                    i += 1
                children.append(block)
            else:
                # Non-list content as child (paragraph)
                children.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": text_to_rich_text(stripped),
                    }
                })
                i += 1

        return children, i

    blocks = []
    lines = text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            i += 1
            continue

        # Code block
        if stripped.startswith("```"):
            block, i = parse_code_block(i)
            blocks.append(block)
            continue

        # Heading 1
        if stripped.startswith("# ") and not stripped.startswith("## "):
            heading_body = {"rich_text": text_to_rich_text(stripped[2:])}
            if is_toggleable:
                heading_body["is_toggleable"] = True
            blocks.append({
                "object": "block",
                "type": "heading_1",
                "heading_1": heading_body,
            })
            i += 1
            continue

        # Heading 2
        if stripped.startswith("## ") and not stripped.startswith("### "):
            heading_body = {"rich_text": text_to_rich_text(stripped[3:])}
            if is_toggleable:
                heading_body["is_toggleable"] = True
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": heading_body,
            })
            i += 1
            continue

        # Heading 3
        if stripped.startswith("### "):
            heading_body = {"rich_text": text_to_rich_text(stripped[4:])}
            if is_toggleable:
                heading_body["is_toggleable"] = True
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": heading_body,
            })
            i += 1
            continue

        # Table (lines starting with |)
        if stripped.startswith("|") and "|" in stripped[1:]:
            table_rows = []
            has_header = False

            # Collect all table rows
            while i < len(lines):
                row_line = lines[i].strip()
                if not row_line.startswith("|"):
                    break

                # Check if this is a separator row (| --- | --- |)
                if re.match(r'^\|[\s\-:]+\|', row_line) and '---' in row_line:
                    has_header = True
                    i += 1
                    continue

                # Parse cells from row
                # Remove leading/trailing pipes and split
                cells_text = row_line.strip("|")
                cells = [cell.strip() for cell in cells_text.split("|")]

                table_rows.append(cells)
                i += 1

            # Build Notion table block
            if table_rows:
                table_width = max(len(row) for row in table_rows)

                # Normalize rows to same width
                normalized_rows = []
                for row in table_rows:
                    while len(row) < table_width:
                        row.append("")
                    normalized_rows.append(row)

                # Create table block with children
                table_children = []
                for row in normalized_rows:
                    table_children.append({
                        "object": "block",
                        "type": "table_row",
                        "table_row": {
                            "cells": [text_to_rich_text(cell) for cell in row]
                        }
                    })

                blocks.append({
                    "object": "block",
                    "type": "table",
                    "table": {
                        "table_width": table_width,
                        "has_column_header": has_header,
                        "has_row_header": False,
                        "children": table_children
                    }
                })
            continue

        # List items (with nested children support)
        current_indent = get_indent_level(line)
        if is_list_item(stripped) and current_indent == 0:
            block = parse_list_item(line, stripped)
            if block:
                # Check for nested children
                if i + 1 < len(lines):
                    nested_children, i = collect_nested_children(lines, i + 1, current_indent)
                    if nested_children:
                        block_type = block["type"]
                        block[block_type]["children"] = nested_children
                else:
                    i += 1
                blocks.append(block)
                continue

        # Blockquote
        if stripped.startswith("> "):
            blocks.append({
                "object": "block",
                "type": "quote",
                "quote": {
                    "rich_text": text_to_rich_text(stripped[2:]),
                }
            })
            i += 1
            continue

        # Horizontal rule
        if stripped in ("---", "***", "___"):
            blocks.append({
                "object": "block",
                "type": "divider",
                "divider": {}
            })
            i += 1
            continue

        # Image ![alt](url)
        image_match = re.match(r'^!\[([^\]]*)\]\(([^)]+)\)$', stripped)
        if image_match:
            alt_text = image_match.group(1)
            image_path = image_match.group(2)

            # Build caption if alt text provided
            caption = []
            if alt_text:
                caption = [{"type": "text", "text": {"content": alt_text}}]

            # Check if this is a URL or local path
            if image_path.startswith(('http://', 'https://')):
                # External URL
                blocks.append({
                    "object": "block",
                    "type": "image",
                    "image": {
                        "type": "external",
                        "external": {"url": image_path},
                        "caption": caption,
                    }
                })
            elif image_uploads and image_path in image_uploads:
                # Local file that was uploaded - use file_upload type
                file_upload_id = image_uploads[image_path]
                blocks.append({
                    "object": "block",
                    "type": "image",
                    "image": {
                        "type": "file_upload",
                        "file_upload": {"id": file_upload_id},
                        "caption": caption,
                    }
                })
            else:
                # Local path without upload - treat as paragraph (will show as broken)
                # The command layer should handle uploads before calling this
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": f"[Image: {image_path}]"}}],
                    }
                })
            i += 1
            continue

        # Notion block markers (<!-- notion-TYPE: URL -->) — round-trip safe
        notion_marker = re.match(
            r'^<!-- notion-(embed|video|bookmark|link_preview|file|pdf): (.+?) -->$',
            stripped
        )
        if notion_marker:
            marker_type = notion_marker.group(1)
            marker_body = notion_marker.group(2)

            # Parse optional caption: "URL caption=CAPTION" or just "URL"
            caption_match = re.match(r'^(.+?)\s+caption=(.+)$', marker_body)
            if caption_match:
                marker_url = caption_match.group(1)
                marker_caption = caption_match.group(2)
            else:
                marker_url = marker_body
                marker_caption = None

            if marker_type == "embed":
                blocks.append({
                    "object": "block",
                    "type": "embed",
                    "embed": {"url": marker_url}
                })
            elif marker_type == "video":
                blocks.append({
                    "object": "block",
                    "type": "video",
                    "video": {
                        "type": "external",
                        "external": {"url": marker_url},
                    }
                })
            elif marker_type == "bookmark":
                bm_block = {
                    "object": "block",
                    "type": "bookmark",
                    "bookmark": {"url": marker_url}
                }
                if marker_caption:
                    bm_block["bookmark"]["caption"] = [
                        {"type": "text", "text": {"content": marker_caption}}
                    ]
                blocks.append(bm_block)
            elif marker_type == "link_preview":
                blocks.append({
                    "object": "block",
                    "type": "link_preview",
                    "link_preview": {"url": marker_url}
                })
            elif marker_type == "file":
                file_block = {
                    "object": "block",
                    "type": "file",
                    "file": {
                        "type": "external",
                        "external": {"url": marker_url},
                    }
                }
                if marker_caption:
                    file_block["file"]["caption"] = [
                        {"type": "text", "text": {"content": marker_caption}}
                    ]
                blocks.append(file_block)
            elif marker_type == "pdf":
                blocks.append({
                    "object": "block",
                    "type": "pdf",
                    "pdf": {
                        "type": "external",
                        "external": {"url": marker_url},
                    }
                })
            i += 1
            continue

        # Legacy empty-URL patterns: [Embed: ](), [Video](), [PDF]() — silently drop
        legacy_empty = re.match(r'^\[(Embed:\s*|Video|PDF|File)\]\(\s*\)$', stripped)
        if legacy_empty:
            i += 1
            continue

        # Legacy embed pattern: [Embed: URL](URL) — reconstruct as embed block
        legacy_embed = re.match(r'^\[Embed:\s*([^\]]*)\]\(([^)]+)\)$', stripped)
        if legacy_embed:
            embed_url = legacy_embed.group(2)
            blocks.append({
                "object": "block",
                "type": "embed",
                "embed": {"url": embed_url}
            })
            i += 1
            continue

        # Legacy video pattern: [Video](URL) — skip to avoid data loss
        legacy_video = re.match(r'^\[Video\]\(([^)]+)\)$', stripped)
        if legacy_video:
            blocks.append({
                "object": "block",
                "type": "video",
                "video": {
                    "type": "external",
                    "external": {"url": legacy_video.group(1)},
                }
            })
            i += 1
            continue

        # Legacy PDF pattern: [PDF](URL) — skip to avoid data loss
        legacy_pdf = re.match(r'^\[PDF\]\(([^)]+)\)$', stripped)
        if legacy_pdf:
            blocks.append({
                "object": "block",
                "type": "pdf",
                "pdf": {
                    "type": "external",
                    "external": {"url": legacy_pdf.group(1)},
                }
            })
            i += 1
            continue

        # Regular paragraph
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": text_to_rich_text(stripped),
            }
        })
        i += 1

    return blocks


def format_page_for_display(page: Dict, properties_to_show: Optional[List[str]] = None) -> Dict:
    """
    Format a Notion page for display.

    Args:
        page: Raw page from Notion API
        properties_to_show: Optional list of property names to include

    Returns:
        Simplified page record for display
    """
    result = {
        "id": page.get("id", ""),
        "url": page.get("url", ""),
    }

    properties = page.get("properties", {})

    for prop_name, prop_value in properties.items():
        if properties_to_show and prop_name not in properties_to_show:
            continue
        result[prop_name] = extract_property_value(prop_value)

    return result
