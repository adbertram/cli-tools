"""Enforce Notion's per-block size limits on outgoing block payloads.

Notion's API rejects any request whose blocks violate these hard limits:

- A single ``rich_text`` ``text.content`` value may not exceed 2000 characters
  (``body.children[N].<type>.rich_text[M].text.content.length should be <= 2000``).
- A ``rich_text`` array may hold at most 100 elements.

The CLI already chunks at the 100-block-per-request level, but a single
oversize paragraph (or any other rich_text block) would still be rejected
mid-upload. Because ``content set`` clears the page *before* uploading, that
rejection used to destroy the page's existing content.

This module transforms blocks so every emitted block is uploadable:

1. Any ``type: "text"`` rich_text segment whose content exceeds 2000 chars is
   split into multiple <= 2000-char segments. Splitting prefers whitespace/word
   boundaries near the limit and falls back to a hard character split only when a
   single token is itself longer than the limit. Annotations and links are
   preserved on every resulting segment. Concatenating the split segments
   reproduces the original content exactly.
2. If splitting pushes a block's rich_text array past 100 elements, the block is
   cloned into sibling blocks of the same type, each carrying at most 100
   segments and all of the original type-specific metadata (language, checked,
   color, is_toggleable, ...). Children stay attached to the final sibling so
   they are not duplicated.
3. The transform recurses into nested children (both block-level ``children`` and
   the API-2025-09-03 ``<type>.children`` location) and into ``table_row`` cells.

Non-``text`` rich_text elements (mentions, equations) carry no ``text.content``
field and pass through untouched.
"""
from __future__ import annotations

import copy
from typing import Dict, List, Optional

from .output import chunk_text_on_boundaries

# Notion API hard limits.
MAX_RICH_TEXT_CONTENT = 2000
MAX_RICH_TEXT_ELEMENTS = 100


def find_oversize_rich_text(
    blocks: List[Dict],
    max_length: int = MAX_RICH_TEXT_CONTENT,
    _path: str = "blocks",
) -> Optional[str]:
    """Return a human-readable location of the first oversize rich_text segment.

    Returns ``None`` when every ``type: "text"`` rich_text ``text.content`` in
    ``blocks`` (recursively, including children and table_row cells) is within
    ``max_length``. Used as a pre-flight guard before any destructive page
    operation: if this returns non-None, the payload is NOT safe to upload and
    the page must not be cleared.
    """
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        block_type = block.get("type", "")
        block_body = block.get(block_type)
        here = f"{_path}[{index}].{block_type}" if block_type else f"{_path}[{index}]"

        if isinstance(block_body, dict):
            rt_key = _rich_text_key(block_body)
            if rt_key is not None:
                oversize = _first_oversize_segment(
                    block_body[rt_key], max_length, f"{here}.{rt_key}"
                )
                if oversize is not None:
                    return oversize

        # table_row cells
        if block_type == "table_row":
            row = block.get("table_row")
            if isinstance(row, dict) and isinstance(row.get("cells"), list):
                for cell_idx, cell in enumerate(row["cells"]):
                    if isinstance(cell, list):
                        oversize = _first_oversize_segment(
                            cell, max_length, f"{here}.cells[{cell_idx}]"
                        )
                        if oversize is not None:
                            return oversize

        holder = _children_holder(block)
        if holder is not None:
            oversize = find_oversize_rich_text(
                holder["children"], max_length, f"{here}.children"
            )
            if oversize is not None:
                return oversize

    return None


def _first_oversize_segment(
    rich_text: List[Dict],
    max_length: int,
    path: str,
) -> Optional[str]:
    """Return a description of the first oversize text segment, or None."""
    for seg_idx, segment in enumerate(rich_text):
        if not isinstance(segment, dict):
            continue
        if segment.get("type", "text") != "text":
            continue
        text_obj = segment.get("text")
        if not isinstance(text_obj, dict):
            continue
        content = text_obj.get("content", "")
        if isinstance(content, str) and len(content) > max_length:
            return f"{path}[{seg_idx}].text.content is {len(content)} chars (limit {max_length})"
    return None


def _split_rich_text_segment(segment: Dict, max_length: int) -> List[Dict]:
    """Split one rich_text element so each piece's text.content fits the limit.

    Only ``type: "text"`` segments with an oversize ``text.content`` are split.
    Every resulting segment is a deep copy that preserves annotations and the
    link object. Non-text segments (or already-small ones) are returned as a
    single-item list unchanged.
    """
    # Mentions / equations have no text.content to bound.
    if segment.get("type", "text") != "text":
        return [segment]

    text_obj = segment.get("text")
    if not isinstance(text_obj, dict):
        return [segment]

    content = text_obj.get("content", "")
    if not isinstance(content, str) or len(content) <= max_length:
        return [segment]

    # Prose paragraphs/headings/list items break best on any whitespace.
    pieces = chunk_text_on_boundaries(content, max_length, boundary="whitespace")
    result: List[Dict] = []
    for piece in pieces:
        new_segment = copy.deepcopy(segment)
        new_segment["text"]["content"] = piece
        result.append(new_segment)
    return result


def _normalize_rich_text_array(rich_text: List[Dict], max_length: int) -> List[Dict]:
    """Return a rich_text array where no text.content exceeds ``max_length``.

    May grow the array length; callers that must respect the 100-element array
    limit are responsible for splitting the owning block into siblings.
    """
    normalized: List[Dict] = []
    for segment in rich_text:
        if isinstance(segment, dict):
            normalized.extend(_split_rich_text_segment(segment, max_length))
        else:
            normalized.append(segment)
    return normalized


def _rich_text_key(block_body: Dict) -> Optional[str]:
    """Return the key holding a block's rich_text array, if any.

    Most blocks use ``rich_text``; the legacy ``text`` key is also honored.
    """
    if isinstance(block_body.get("rich_text"), list):
        return "rich_text"
    if isinstance(block_body.get("text"), list):
        return "text"
    return None


def _children_holder(block: Dict) -> Optional[Dict]:
    """Return the dict that holds this block's ``children`` list, or None.

    Children live either at the block level (``block["children"]``) or, under
    API 2025-09-03+, inside the type-specific object (``block[type]["children"]``).
    """
    block_type = block.get("type", "")
    type_data = block.get(block_type)
    if isinstance(type_data, dict) and isinstance(type_data.get("children"), list):
        return type_data
    if isinstance(block.get("children"), list):
        return block
    return None


def _normalize_table_cells(block: Dict, max_length: int) -> None:
    """Split oversize text inside table_row cells in place.

    A table_row's ``cells`` is a list of rich_text arrays. Each cell is bounded
    independently. Cells are not overflowed into new rows (a >100-segment cell is
    implausible and has no sibling-row semantics), but every cell segment is kept
    within the per-segment content limit.
    """
    if block.get("type") != "table_row":
        return
    row = block.get("table_row")
    if not isinstance(row, dict):
        return
    cells = row.get("cells")
    if not isinstance(cells, list):
        return
    row["cells"] = [
        _normalize_rich_text_array(cell, max_length) if isinstance(cell, list) else cell
        for cell in cells
    ]


def _split_block_on_element_limit(
    block: Dict,
    max_elements: int,
) -> List[Dict]:
    """Split a single (already content-normalized) block on the 100-element cap.

    If the block's rich_text array holds more than ``max_elements`` segments,
    clone the block into sibling blocks of the same type, each holding at most
    ``max_elements`` segments and all original type-specific metadata. Children
    are kept only on the final sibling so they are not duplicated.

    Returns the list of blocks to emit in place of the original (length 1 when no
    split is needed).
    """
    block_type = block.get("type", "")
    block_body = block.get(block_type)
    if not isinstance(block_body, dict):
        return [block]

    rt_key = _rich_text_key(block_body)
    if rt_key is None:
        return [block]

    rich_text = block_body[rt_key]
    if len(rich_text) <= max_elements:
        return [block]

    groups = [
        rich_text[i:i + max_elements]
        for i in range(0, len(rich_text), max_elements)
    ]

    siblings: List[Dict] = []
    last_idx = len(groups) - 1
    for idx, group in enumerate(groups):
        sibling = copy.deepcopy(block)
        sibling_body = sibling[block_type]
        sibling_body[rt_key] = group
        if idx != last_idx:
            # Keep children only on the final sibling to avoid duplicating them.
            sibling_body.pop("children", None)
            sibling.pop("children", None)
        siblings.append(sibling)
    return siblings


def enforce_block_limits(
    blocks: List[Dict],
    max_length: int = MAX_RICH_TEXT_CONTENT,
    max_elements: int = MAX_RICH_TEXT_ELEMENTS,
) -> List[Dict]:
    """Return a new block list that satisfies Notion's per-block size limits.

    The input is not mutated. Every emitted block is uploadable: no rich_text
    ``text.content`` exceeds ``max_length`` and no rich_text array exceeds
    ``max_elements`` elements. Oversize content is split on word boundaries and,
    when necessary, overflowed into sibling blocks of the same type. Nested
    children and table_row cells are normalized recursively.

    This is a pure, deterministic transform with no I/O. It runs before any
    destructive page operation so an oversize block can never reach the network
    after the page has been cleared.
    """
    result: List[Dict] = []

    for original in blocks:
        if not isinstance(original, dict):
            result.append(original)
            continue

        block = copy.deepcopy(original)
        block_type = block.get("type", "")
        block_body = block.get(block_type)

        # 1. Normalize this block's own rich_text content length.
        if isinstance(block_body, dict):
            rt_key = _rich_text_key(block_body)
            if rt_key is not None:
                block_body[rt_key] = _normalize_rich_text_array(
                    block_body[rt_key], max_length
                )

        # 2. Normalize table_row cells.
        _normalize_table_cells(block, max_length)

        # 3. Recurse into children before splitting on the element cap, so
        #    children are normalized exactly once and stay with their block.
        holder = _children_holder(block)
        if holder is not None:
            holder["children"] = enforce_block_limits(
                holder["children"], max_length, max_elements
            )

        # 4. Split this block on the 100-element rich_text cap if needed.
        result.extend(_split_block_on_element_limit(block, max_elements))

    return result
