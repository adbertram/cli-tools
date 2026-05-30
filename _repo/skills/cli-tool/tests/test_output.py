"""Output module validation tests (Section 10).

Tests that output.py imports standard functions from cli_tools_shared.output
and does not locally redefine them. CLI-specific helpers are allowed.
"""

import pytest
import json
from pathlib import Path

from cli_test_utils import run_live_cli_command, discover_list_commands, get_cli_timeout, get_fixture_args


# Standard functions that MUST come from cli_tools_shared.output, not local definitions
STANDARD_OUTPUT_FUNCTIONS = [
    "print_json",
    "print_table",
    "print_output",
    "print_error",
    "print_warning",
    "print_success",
    "print_info",
    "handle_error",
    "_format_cell_value",
    "_serialize_for_json",
]

STANDARD_OUTPUT_NAMES = [
    "console",
]


def _get_output_path(cli_dir, cli_name):
    return cli_dir / f"{cli_name.replace('-', '_')}_cli" / "output.py"


def _profile_args(auth_context, help_cache, cmd_path):
    if not isinstance(auth_context, dict):
        return []
    profile = auth_context.get("profile")
    if not profile:
        return []
    if "--profile" not in help_cache(cmd_path):
        return []
    return ["--profile", profile]


def test_output_imports_from_cli_tools_shared(cli_dir, cli_name, command_filter):
    """output.py must import standard functions from cli_tools_shared.output.

    All standard output functions (print_json, print_table, print_error, etc.)
    must be imported from cli_tools_shared.output rather than defined locally.
    This ensures all CLIs get shared functionality like cache_hit injection,
    Pydantic model serialization, and consistent error handling.
    """
    output_path = _get_output_path(cli_dir, cli_name)
    if not output_path.exists():
        pytest.skip("output.py not found")

    content = output_path.read_text()

    assert "from cli_tools_shared.output import" in content, (
        f"output.py does not import from cli_tools_shared.output. "
        f"Fix: Replace local function definitions with:\n"
        f"  from cli_tools_shared.output import (\n"
        f"      console, _format_cell_value, _serialize_for_json,\n"
        f"      print_json, print_table, print_output,\n"
        f"      print_error, print_warning, print_success, print_info,\n"
        f"      handle_error,\n"
        f"  )"
    )


def test_output_no_local_standard_functions(cli_dir, cli_name, command_filter):
    """output.py must NOT locally redefine standard output functions.

    Standard functions like print_json, print_table, handle_error etc. must
    come from cli_tools_shared.output. Local redefinitions cause divergence
    and miss shared features (cache_hit injection, model serialization).
    """
    output_path = _get_output_path(cli_dir, cli_name)
    if not output_path.exists():
        pytest.skip("output.py not found")

    content = output_path.read_text()

    # Only enforce once the CLI imports from cli_tools_shared.
    if "from cli_tools_shared.output import" not in content:
        pytest.skip("CLI not yet migrated to cli_tools_shared imports")

    locally_defined = []
    for func_name in STANDARD_OUTPUT_FUNCTIONS:
        if f"def {func_name}" in content:
            locally_defined.append(func_name)

    assert not locally_defined, (
        f"output.py locally redefines standard functions: {locally_defined}. "
        f"Fix: Remove local definitions and import from cli_tools_shared.output instead. "
        f"CLI-specific helpers should use different names."
    )


def test_output_imports_all_standard_functions(cli_dir, cli_name, command_filter):
    """output.py must import ALL standard output functions from cli_tools_shared.

    Every standard function must be available via the CLI's output.py so that
    command files can use ``from ..output import print_json`` etc.
    """
    output_path = _get_output_path(cli_dir, cli_name)
    if not output_path.exists():
        pytest.skip("output.py not found")

    content = output_path.read_text()

    if "from cli_tools_shared.output import" not in content:
        pytest.skip("CLI not yet migrated to cli_tools_shared imports")

    # Check that all standard names appear in the import block
    required = STANDARD_OUTPUT_FUNCTIONS + STANDARD_OUTPUT_NAMES
    missing = [name for name in required if name not in content]

    assert not missing, (
        f"output.py missing standard imports: {missing}. "
        f"Fix: Add missing names to the cli_tools_shared.output import statement."
    )


def test_print_table_execution_smoke_test(cli_executable, cli_name, test_config, authenticated, command_filter, cli_fixtures, help_cache):
    """Comprehensive: Verify print_table actually executes with --table flag (Decision 30)."""
    list_commands, timeout = discover_list_commands(cli_executable, cli_name, test_config, command_filter)

    if not list_commands:
        pytest.skip("No list commands found")

    # Use first discovered list command
    cmd_path = list_commands[0]

    # Get fixture-based args for this command (if fixtures defined)
    fixture_args = get_fixture_args(cli_name, cmd_path, cli_fixtures, test_config)
    profile_args = _profile_args(authenticated, help_cache, cmd_path)

    args = cmd_path.split() + profile_args + fixture_args + ["--table", "--limit", "1"]
    full_cmd = f"{cli_name} {' '.join(args)}"
    print(f"  Executing: {full_cmd}")
    result = run_live_cli_command(cli_executable, args, timeout=timeout)

    if result.returncode != 0:
        # Check if this is a missing fixture issue - this should FAIL, not skip
        if "required" in result.stderr.lower() or "missing" in result.stderr.lower():
            pytest.fail(
                f"Command requires positional argument but no fixture defined. "
                f"Fix: Add fixture to tests/fixtures/{cli_name}.json and param_fixtures in cli_test_config.toml. "
                f"See tests/fixtures/notion.json for example. Error: {result.stderr[:100]}"
            )
        pytest.skip(f"Could not test --table execution (command failed): {result.stderr[:100]}")

    # Should produce table output (not JSON), or "No data" if empty
    has_table_chars = "\u2502" in result.stdout or "\u2500" in result.stdout or "\u2503" in result.stdout
    is_empty_result = "No data" in result.stdout or result.stdout.strip() == ""
    assert has_table_chars or is_empty_result, (
        f"--table flag did not produce table output or empty result indicator. "
        f"Fix: Ensure print_table is called when table=True."
    )

    # Should NOT be valid JSON when --table used
    try:
        json.loads(result.stdout)
        pytest.fail(
            f"--table flag produced JSON instead of table. "
            f"Fix: Check if table parameter is used correctly in command logic."
        )
    except json.JSONDecodeError:
        pass  # Correct - table output is not JSON


def test_output_does_not_truncate_rows(cli_dir, cli_name, command_filter):
    """Assertion 48: print_table must not truncate rows - all data must be displayed.

    CLI tools must never truncate table output. Users rely on seeing ALL data
    when using --table flag. Row limits should only be applied at the API level
    via --limit flag, not at the display level.
    """
    output_path = _get_output_path(cli_dir, cli_name)
    if not output_path.exists():
        pytest.skip("output.py not found")

    content = output_path.read_text()

    # Check for row truncation patterns
    row_truncation_patterns = [
        "max_rows",
        "rows[:max",
        "rows[:limit",
        "data[:max",
        "items[:max",
        "[:max_display",
        "truncate_rows",
        "row_limit",
        "display_limit",
    ]

    found_patterns = [p for p in row_truncation_patterns if p in content]

    assert not found_patterns, (
        f"output.py appears to truncate table rows using: {found_patterns}. "
        f"Fix: Remove row truncation from print_table. Table output must show ALL rows. "
        f"Use --limit flag at API level to control data volume, not display truncation."
    )


def test_format_functions_have_truncate_parameter(cli_dir, cli_name, command_filter):
    """Assertion 49: format_*_for_display functions with truncation must have truncate parameter.

    Format functions that truncate values must have a truncate parameter that
    defaults to False. This allows:
    - JSON output: Full untruncated values (truncate=False)
    - Table output: Truncated values for display (truncate=True)

    Without this parameter, JSON output gets incorrectly truncated.

    Note: Only checks functions that actually contain truncation patterns ([:N] + "...").
    Functions without truncation don't need the parameter.
    """
    import re

    commands_dir = cli_dir / f"{cli_name.replace('-', '_')}_cli" / "commands"
    if not commands_dir.exists():
        pytest.skip("commands directory not found")

    # Pattern for truncation: [:N] followed by ... somewhere
    truncation_pattern = re.compile(r'\[:(\d+)\].*\.\.\.')

    # Find all format_*_for_display functions and check if they have truncation
    func_pattern = re.compile(
        r'def (format_\w+_for_display)\s*\(([^)]*)\):[^\n]*\n((?:(?:[ \t]+[^\n]*|[ \t]*)\n)*)',
        re.MULTILINE
    )

    issues = []
    for py_file in commands_dir.glob("*.py"):
        content = py_file.read_text()

        for match in func_pattern.finditer(content):
            func_name = match.group(1)
            params = match.group(2)
            func_body = match.group(3)

            # Only check functions that actually do truncation
            if truncation_pattern.search(func_body):
                # This function truncates - it MUST have truncate parameter
                if "truncate" not in params:
                    issues.append(f"{py_file.name}: {func_name}() has truncation but missing truncate parameter")

    if issues:
        pytest.fail(
            f"Format functions with truncation missing truncate parameter:\n" +
            "\n".join(f"  - {issue}" for issue in issues) +
            f"\n\nFix: Add 'truncate: bool = False' parameter to these functions. "
            f"Only truncate values when truncate=True (for table output)."
        )


def test_json_output_not_truncated(cli_dir, cli_name, command_filter):
    """Assertion 50: JSON output must never be truncated.

    When outputting JSON (default mode without --table), values must not be truncated.
    This test checks that format_*_for_display calls with truncate=True are ONLY used
    in table output paths, not shared paths that also produce JSON.

    Pattern to detect (BAD):
    - format_*_for_display(..., truncate=True) followed by BOTH print_table AND print_json
      using the SAME formatted variable (single code path for both outputs)

    Pattern that's OK:
    - if use_table: format_*(..., truncate=True); print_table()
      else: format_*(...); print_json()  # Separate format calls
    - format_*(..., truncate=use_table) followed by if/else  # Dynamic truncate
    """
    import re

    commands_dir = cli_dir / f"{cli_name.replace('-', '_')}_cli" / "commands"
    if not commands_dir.exists():
        pytest.skip("commands directory not found")

    issues = []

    for py_file in commands_dir.glob("*.py"):
        content = py_file.read_text()
        lines = content.split('\n')

        # Find format calls with truncate=True
        for i, line in enumerate(lines):
            if 'format_' in line and '_for_display' in line and 'truncate=True' in line:
                # Extract the variable being assigned
                var_match = re.search(r'(\w+)\s*=\s*\[?\s*format_', line)
                if not var_match:
                    continue
                var_name = var_match.group(1)

                # Check if this SAME variable is used for both print_table and print_json
                # without being reassigned
                found_table = False
                found_json = False
                reassigned = False

                for j in range(i+1, min(i+30, len(lines))):
                    check_line = lines[j]

                    # Check for reassignment of the variable
                    if f'{var_name} =' in check_line or f'{var_name}=' in check_line:
                        if 'format_' in check_line:
                            reassigned = True
                            break

                    # Check for print_table with this variable
                    if 'print_table' in check_line and var_name in check_line:
                        found_table = True

                    # Check for print_json with this variable
                    if 'print_json' in check_line and var_name in check_line:
                        found_json = True

                # Problem: same truncate=True variable used for both outputs
                if found_table and found_json and not reassigned:
                    issues.append(
                        f"{py_file.name}:{i+1}: format call with truncate=True "
                        f"variable '{var_name}' used for both table and JSON output"
                    )

    if issues:
        pytest.fail(
            f"JSON output may be truncated:\n" +
            "\n".join(f"  - {issue}" for issue in issues) +
            f"\n\nFix: Use separate format calls - truncate=True for table, truncate=False for JSON. "
            f"Or use truncate=use_table to dynamically set based on output mode."
        )


def test_no_unconditional_truncation_in_format_functions(cli_dir, cli_name, command_filter):
    """Assertion 51: Format functions must not have unconditional truncation.

    Format functions must only truncate when truncate=True. This test detects
    patterns like:
        if len(value) > N:
            value = value[:M] + "..."
    that occur OUTSIDE of 'if truncate:' blocks.

    Proper pattern:
        if truncate and len(value) > N:
            value = value[:M] + "..."
    """
    import re

    commands_dir = cli_dir / f"{cli_name.replace('-', '_')}_cli" / "commands"
    if not commands_dir.exists():
        pytest.skip("commands directory not found")

    # Pattern for truncation: [:N] + "..." where N is a number
    truncation_pattern = re.compile(r'\[:(\d+)\].*\.\.\.')

    # Pattern for function definitions
    func_pattern = re.compile(r'^def (format_\w+_for_display)\s*\([^)]*\):')

    issues = []

    for py_file in commands_dir.glob("*.py"):
        content = py_file.read_text()
        lines = content.split('\n')

        in_format_func = False
        func_name = None
        func_indent = 0

        for i, line in enumerate(lines):
            # Check for function start
            func_match = func_pattern.match(line)
            if func_match:
                in_format_func = True
                func_name = func_match.group(1)
                func_indent = len(line) - len(line.lstrip())
                continue

            # Check for function end (new function at same or lower indent)
            if in_format_func and line.strip() and not line.strip().startswith('#'):
                current_indent = len(line) - len(line.lstrip())
                if current_indent <= func_indent and line.strip().startswith('def '):
                    in_format_func = False
                    func_name = None

            # If in a format function, check for truncation
            if in_format_func and truncation_pattern.search(line):
                # Check if this line or preceding lines have 'if truncate'
                context_start = max(0, i - 5)
                context = '\n'.join(lines[context_start:i+1])

                if 'if truncate' not in context and 'truncate and' not in context:
                    # Unconditional truncation found
                    issues.append(
                        f"{py_file.name}:{i+1}: {func_name}() has unconditional truncation: "
                        f"{line.strip()[:60]}..."
                    )

    if issues:
        pytest.fail(
            f"Unconditional truncation in format functions:\n" +
            "\n".join(f"  - {issue}" for issue in issues) +
            f"\n\nFix: Change 'if len(x) > N:' to 'if truncate and len(x) > N:'"
        )
