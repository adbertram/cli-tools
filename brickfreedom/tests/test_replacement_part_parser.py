"""Regression tests for ReplacementPartTask.from_task_text and from_replacement_addition_text."""
from __future__ import annotations

from brickfreedom_cli.models import Platform, ReplacementPartTask


def test_parse_single_replacement_new_format():
    text = (
        "[REPLACEMENT] | Platform: bricklink | Customer: eightyproof/Grey Williams "
        "| Order: 31963910 | Part: 2412b Tile, Modified 1 x 2 Grille with Bottom Groove "
        "| Color: Black | Qty: 6 | Loc: C-0801"
    )
    parsed = ReplacementPartTask.from_task_text(1, text, completed=False)
    assert parsed is not None
    assert parsed.platform == Platform.BRICKLINK
    assert parsed.order_id == "31963910"
    assert parsed.item_no == "2412b"
    assert parsed.item_name == "Tile, Modified 1 x 2 Grille with Bottom Groove"
    assert parsed.color == "Black"
    assert parsed.qty == 6
    assert parsed.location == "C-0801"
    assert parsed.task_kind == "replacement"
    assert parsed.action_note is None

    # [REPLACEMENT] rows never match the addition parser.
    assert ReplacementPartTask.from_replacement_addition_text(1, text, completed=False) == []


def test_parse_single_replacement_legacy_format():
    text = "[REPLACEMENT] | Customer: Jane Doe | Order: 30176576 | Part: 3024 Plate 1 x 1 | Color: Red | Qty: 10"
    parsed = ReplacementPartTask.from_task_text(1, text, completed=False)
    assert parsed is not None
    assert parsed.platform == Platform.BRICKLINK
    assert parsed.item_no == "3024"
    assert parsed.qty == 10
    assert parsed.location is None


def test_parse_replacement_addition_multiple_items():
    """[REPLACEMENT/ADDITION] rows add items to an already-packed order and
    must not be silently dropped by the customer-replacement-part filter.
    """
    text = (
        "[REPLACEMENT/ADDITION] | Platform: bricklink | Customer: Portagemonkey/Chris Binkerd "
        "| Order: 31986649 | Add: 4625 Hinge Tile 1 x 4 (Tan, Loc C-0719, Qty 1), "
        "2335pb205 Flag 2 x 2 Square with Flat Edge with Striped Pink Heart Pattern (Sticker) "
        "(White, Loc G-0226, Qty 1) | Action: Add to packed order; customer owes $4.91 for "
        "additions (invoice before shipping)."
    )

    # The plain [REPLACEMENT] parser must not match this tag.
    assert ReplacementPartTask.from_task_text(1, text, completed=False) is None

    parsed = ReplacementPartTask.from_replacement_addition_text(1, text, completed=False)
    assert len(parsed) == 2

    first, second = parsed
    assert first.order_id == second.order_id == "31986649"
    assert first.platform == second.platform == Platform.BRICKLINK
    assert first.task_kind == second.task_kind == "replacement_addition"
    assert "customer owes $4.91" in first.action_note

    assert first.item_no == "4625"
    assert first.item_name == "Hinge Tile 1 x 4"
    assert first.color == "Tan"
    assert first.location == "C-0719"
    assert first.qty == 1

    # Second item's name contains its own parenthetical ("(Sticker)"); make sure
    # that doesn't get mistaken for the trailing (color, Loc, Qty) group, and
    # that the item number isn't swallowed by the preceding ", " separator.
    assert second.item_no == "2335pb205"
    assert second.item_name == (
        "Flag 2 x 2 Square with Flat Edge with Striped Pink Heart Pattern (Sticker)"
    )
    assert second.color == "White"
    assert second.location == "G-0226"
    assert second.qty == 1


def test_parse_replacement_addition_single_item():
    text = (
        "[REPLACEMENT/ADDITION] | Platform: brickowl | Customer: John Smith | Order: 2113029 "
        "| Add: 3001 Brick 2 x 4 (Red, Loc A-0001, Qty 2) | Action: Add to packed order."
    )
    parsed = ReplacementPartTask.from_replacement_addition_text(1, text, completed=False)
    assert len(parsed) == 1
    assert parsed[0].platform == Platform.BRICKOWL
    assert parsed[0].item_no == "3001"
    assert parsed[0].qty == 2


def test_parse_returns_none_or_empty_for_unrelated_text():
    text = "This is not a replacement task at all"
    assert ReplacementPartTask.from_task_text(1, text, completed=False) is None
    assert ReplacementPartTask.from_replacement_addition_text(1, text, completed=False) == []
