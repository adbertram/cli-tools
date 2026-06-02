"""Regression tests for MissingPart.from_task_text and `task complete --match-*`."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from brickfreedom_cli.commands.task import app as task_app
from brickfreedom_cli.models import MissingPart, Platform, Task, TaskList, TaskResult


# ============================================================================
# MissingPart.from_task_text parser tests
# ============================================================================


def test_parse_new_format_with_color():
    """Canonical 'new format with color' branch."""
    text = (
        "Bricklink Order #30823995 missing 2 x 44126pb022 "
        "Slope, Curved 6 x 2 (in Black) at location E-0971"
    )
    parsed = MissingPart.from_task_text(1, text, completed=False)
    assert parsed is not None
    assert parsed.platform == Platform.BRICKLINK
    assert parsed.order_id == "30823995"
    assert parsed.quantity == 2
    assert parsed.item_number == "44126pb022"
    assert parsed.item_name == "Slope, Curved 6 x 2"
    assert parsed.color_name == "Black"
    assert parsed.location == "E-0971"
    assert parsed.completed is False


def test_parse_new_format_without_color():
    """New-format row that does not include `(in <color>)`."""
    text = (
        "Bricklink Order #30823995 missing 1 x 75270-1 "
        "Instruction Book at location F-INS"
    )
    parsed = MissingPart.from_task_text(2, text, completed=False)
    assert parsed is not None
    assert parsed.platform == Platform.BRICKLINK
    assert parsed.order_id == "30823995"
    assert parsed.quantity == 1
    assert parsed.item_number == "75270-1"
    assert parsed.item_name == "Instruction Book"
    assert parsed.color_name == ""
    assert parsed.location == "F-INS"


def test_parse_old_format_no_item_name_with_color():
    """Backward-compat old format: no item name, has `(in <color>)`."""
    text = "Brickowl Order #9444944 missing 1 x 3008 (in Light Aqua) at location C-0961"
    parsed = MissingPart.from_task_text(3, text, completed=False)
    assert parsed is not None
    assert parsed.platform == Platform.BRICKOWL
    assert parsed.order_id == "9444944"
    assert parsed.quantity == 1
    assert parsed.item_number == "3008"
    assert parsed.item_name is None
    assert parsed.color_name == "Light Aqua"
    assert parsed.location == "C-0961"


def test_parse_no_name_no_color_strips_trailing_null():
    """No-name / no-color branch: BF concatenates item_number with literal `null`."""
    text = "Brickowl Order #5311768 missing 1 x 75270-1null at location F-INS"
    parsed = MissingPart.from_task_text(4, text, completed=False)
    assert parsed is not None
    assert parsed.platform == Platform.BRICKOWL
    assert parsed.order_id == "5311768"
    assert parsed.quantity == 1
    # Trailing literal "null" stripped from item number.
    assert parsed.item_number == "75270-1"
    assert parsed.item_name is None
    assert parsed.color_name == ""
    assert parsed.location == "F-INS"


def test_parse_returns_none_for_unknown_format():
    parsed = MissingPart.from_task_text(5, "This is not a missing-part task at all", completed=False)
    assert parsed is None


def test_parse_no_name_no_color_strips_only_trailing_null_literal():
    """Strip the trailing literal 'null' suffix only — not a substring."""
    text = "Bricklink Order #1 missing 1 x 3001null at location B-1"
    parsed = MissingPart.from_task_text(6, text, completed=False)
    assert parsed is not None
    # Must be "3001" — not "300" (would indicate slicing too aggressively).
    assert parsed.item_number == "3001"
    assert parsed.item_name is None
    assert parsed.color_name == ""
    assert parsed.location == "B-1"


# ============================================================================
# `task complete --match-*` CliRunner tests
# ============================================================================


def _make_task_list(rows):
    """Helper: build a TaskList from (index, text, completed) tuples."""
    return TaskList(tasks=[Task(index=i, text=t, completed=c) for i, t, c in rows])


@pytest.fixture
def runner():
    return CliRunner()


def _build_fake_client(fake_list, complete_result=None):
    """Build a MagicMock client whose `list_tasks` returns `fake_list`."""
    client = MagicMock()
    client.list_tasks.return_value = fake_list
    if complete_result is None:
        complete_result = TaskResult(success=True, message="Task marked as complete")
    client.complete_task.return_value = complete_result
    return client


def test_complete_match_single_match_completes_resolved_index(runner):
    """Exactly one match → calls complete_task with the resolved index."""
    rows = [
        (1, "Bricklink Order #30823995 missing 1 x 75270-1 Instruction Book at location F-INS", False),
        (2, "Bricklink Order #99999999 missing 1 x 3001 (in Red) at location B-1", False),
    ]
    fake_list = _make_task_list(rows)
    client = _build_fake_client(
        fake_list,
        complete_result=TaskResult(success=True, message="Task 1 marked as complete"),
    )

    with patch("brickfreedom_cli.commands.task.get_client", return_value=client):
        result = runner.invoke(
            task_app,
            [
                "complete",
                "--match-platform", "bricklink",
                "--match-order-id", "30823995",
                "--match-item-number", "75270-1",
            ],
        )

    assert result.exit_code == 0, result.output + (result.stderr or "")
    client.list_tasks.assert_called_once()
    client.complete_task.assert_called_once_with(1)
    # JSON includes the resolved identity.
    assert '"index": 1' in result.stdout
    assert '"orderId": "30823995"' in result.stdout
    assert '"itemNumber": "75270-1"' in result.stdout


def test_complete_match_zero_matches_errors(runner):
    """Zero matches → non-zero exit + JSON error."""
    rows = [
        (1, "Bricklink Order #30823995 missing 1 x 75270-1 Instruction Book at location F-INS", False),
    ]
    fake_list = _make_task_list(rows)
    client = _build_fake_client(fake_list)

    with patch("brickfreedom_cli.commands.task.get_client", return_value=client):
        result = runner.invoke(
            task_app,
            [
                "complete",
                "--match-platform", "bricklink",
                "--match-order-id", "12345678",
                "--match-item-number", "3001",
            ],
        )

    assert result.exit_code != 0
    assert '"success": false' in result.stdout
    assert "no matching missing-part task" in result.stdout
    client.complete_task.assert_not_called()


def test_complete_match_multiple_matches_errors_and_lists_candidates(runner):
    """Two matches that differ only by quantity → ambiguous error listing both."""
    rows = [
        (1, "Bricklink Order #30823995 missing 1 x 3001 (in Red) at location B-1", False),
        (2, "Bricklink Order #30823995 missing 2 x 3001 (in Red) at location B-2", False),
    ]
    fake_list = _make_task_list(rows)
    client = _build_fake_client(fake_list)

    with patch("brickfreedom_cli.commands.task.get_client", return_value=client):
        result = runner.invoke(
            task_app,
            [
                "complete",
                "--match-platform", "bricklink",
                "--match-order-id", "30823995",
                "--match-item-number", "3001",
            ],
        )

    assert result.exit_code != 0
    assert "ambiguous match" in result.stdout
    assert '"matches"' in result.stdout
    client.complete_task.assert_not_called()


def test_complete_match_mixed_with_positional_errors(runner):
    """Mixing positional index with match flags is rejected fail-fast."""
    client = MagicMock()
    with patch("brickfreedom_cli.commands.task.get_client", return_value=client):
        result = runner.invoke(
            task_app,
            [
                "complete",
                "5",
                "--match-platform", "bricklink",
                "--match-order-id", "30823995",
                "--match-item-number", "75270-1",
            ],
        )

    assert result.exit_code != 0
    combined = (result.stdout or "") + (result.stderr or "")
    assert "cannot be combined" in combined
    client.complete_task.assert_not_called()


def test_complete_match_quantity_disambiguates(runner):
    """Adding --match-quantity narrows two-row match down to one."""
    rows = [
        (1, "Bricklink Order #30823995 missing 1 x 3001 (in Red) at location B-1", False),
        (2, "Bricklink Order #30823995 missing 2 x 3001 (in Red) at location B-2", False),
    ]
    fake_list = _make_task_list(rows)
    client = _build_fake_client(
        fake_list,
        complete_result=TaskResult(success=True, message="Task 2 marked as complete"),
    )

    with patch("brickfreedom_cli.commands.task.get_client", return_value=client):
        result = runner.invoke(
            task_app,
            [
                "complete",
                "--match-platform", "bricklink",
                "--match-order-id", "30823995",
                "--match-item-number", "3001",
                "--match-quantity", "2",
            ],
        )

    assert result.exit_code == 0, result.output
    client.complete_task.assert_called_once_with(2)
