"""Item-type mapping between BrickBuddy / CLI names and BrickLink ajax codes."""

from __future__ import annotations

TYPE_TO_AJAX: dict[str, str] = {
    "P": "P", "PART": "P", "PARTS": "P",
    "M": "M", "MINIFIG": "M", "MINIFIGS": "M",
    "S": "S", "SET": "S", "SETS": "S",
    "G": "G", "GEAR": "G",
    "B": "B", "BOOK": "B",
    "C": "C", "CATALOG": "C",
    "I": "I", "INSTRUCTION": "I", "INSTRUCTIONS": "I",
    "O": "O", "ORIGINAL_BOX": "O", "BOX": "O",
}

AJAX_TO_CANONICAL: dict[str, str] = {
    "P": "PART", "M": "MINIFIG", "S": "SET", "G": "GEAR",
    "B": "BOOK", "C": "CATALOG", "I": "INSTRUCTION", "O": "ORIGINAL_BOX",
}


def normalize_item_type(raw: str) -> str:
    key = (raw or "").strip().upper()
    if key not in TYPE_TO_AJAX:
        raise ValueError(
            f"Unknown item type {raw!r}. Expected one of: "
            + ", ".join(sorted(set(TYPE_TO_AJAX)))
        )
    return TYPE_TO_AJAX[key]


def canonical_item_type(raw: str) -> str:
    return AJAX_TO_CANONICAL[normalize_item_type(raw)]
