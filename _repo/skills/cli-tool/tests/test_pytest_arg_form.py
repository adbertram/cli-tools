"""test-cli-tool.sh must pass harness value options as --opt=value, never as two arguments."""
import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "test-cli-tool.sh"
VALUE_OPTIONS = ("--cli-name", "--cli-executable", "--profile", "--command")


def test_harness_value_options_use_equals_form():
    # pytest parses argv before the harness conftest registers these options, so a
    # space-separated value is read as a positional path; a value inside the target
    # CLI's checkout then loads that checkout's conftest.py in place of the harness one.
    pytest_arg_lines = [line for line in SCRIPT.read_text().splitlines() if "PYTEST_ARGS" in line]
    assert pytest_arg_lines
    for option in VALUE_OPTIONS:
        for line in pytest_arg_lines:
            assert not re.search(rf"{re.escape(option)}\s+\"", line), line
