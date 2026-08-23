"""Unit coverage for JSON root-shape helpers used by live verification scripts."""

from __future__ import annotations

from cli_test_utils import (
    describe_json_top_level,
    require_json_array_output,
    validate_json_output,
)


def test_validate_json_output_preserves_array_root():
    valid, payload = validate_json_output('[{"id": "line-1"}]')

    assert valid is True
    assert payload == [{"id": "line-1"}]


def test_require_json_array_output_accepts_array_before_slicing():
    valid, rows, error = require_json_array_output(
        '[{"id": "line-1"}, {"id": "line-2"}]',
        command="amazon orders match",
    )

    assert valid is True
    assert rows[:1] == [{"id": "line-1"}]
    assert error == ""


def test_require_json_array_output_rejects_object_before_slicing():
    valid, rows, error = require_json_array_output(
        '{"matches": [{"id": "line-1"}], "count": 1}',
        command="amazon orders match",
    )

    assert valid is False
    assert rows is None
    assert error == (
        "amazon orders match expected top-level JSON array before slicing, "
        "got object keys=[count, matches]"
    )


def test_describe_json_top_level_reports_scalars():
    assert describe_json_top_level(None) == "null"
    assert describe_json_top_level("value") == "str"
