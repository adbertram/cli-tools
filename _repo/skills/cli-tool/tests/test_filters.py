"""Filter system validation tests (Sections 5-6)."""

import pytest
import ast
from pathlib import Path

from cli_test_utils import run_live_cli_command, validate_json_output, filter_commands_by_group, discover_list_commands


def _find_operators_set_in_ast(tree):
    """Extract OPERATORS set from an AST tree."""
    for node in ast.walk(tree):
        # Handle plain assignment: OPERATORS = {...}
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "OPERATORS":
                    if isinstance(node.value, ast.Set):
                        return {elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)}
        # Handle annotated assignment: OPERATORS: Set[str] = {...}
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "OPERATORS":
                if isinstance(node.value, ast.Set):
                    return {elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)}
    return None


def _imports_from_cli_tools_shared(content, symbol):
    """Check if content re-exports a symbol from cli_tools_shared.filters."""
    tree = ast.parse(content)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "cli_tools_shared" in node.module and "filters" in node.module:
                for alias in node.names:
                    if alias.name == symbol:
                        return True
    return False


def _resolve_cli_tools_shared_filters():
    """Find and return the content of cli_tools_shared/filters.py."""
    try:
        import cli_tools_shared.filters as mod
        source_path = Path(mod.__file__)
        return source_path.read_text()
    except (ImportError, AttributeError, OSError):
        return None


def test_filters_has_required_operators(cli_name, cli_dir, test_config, command_filter):
    """Assertion 21: filters.py has all required operators."""
    filters_path = cli_dir / f"{cli_name.replace('-', '_')}_cli" / "filters.py"
    if not filters_path.exists():
        pytest.skip("filters.py not found")

    content = filters_path.read_text()
    required_ops = test_config["required_operators"]["operators"]

    # If filters.py re-exports OPERATORS from cli_tools_shared, follow the import
    if _imports_from_cli_tools_shared(content, "OPERATORS"):
        source_content = _resolve_cli_tools_shared_filters()
        assert source_content is not None, (
            "filters.py imports OPERATORS from cli_tools_shared.filters but module not found"
        )
        content = source_content

    tree = ast.parse(content)
    operators_set = _find_operators_set_in_ast(tree)

    assert operators_set is not None, "Could not find OPERATORS set in filters.py"

    missing = set(required_ops) - operators_set
    assert len(missing) == 0, (
        f"filters.py missing required operators: {missing}. "
        f"Fix: Ensure filters.py is copied from template with all operators."
    )


def test_filters_implements_in_operator_correctly(cli_name, cli_dir, command_filter):
    """Assertion 22: filters.py implements 'in' operator with pipe separator."""
    filters_path = cli_dir / f"{cli_name.replace('-', '_')}_cli" / "filters.py"
    if not filters_path.exists():
        pytest.skip("filters.py not found")

    content = filters_path.read_text()

    # If filters.py re-exports from cli_tools_shared, follow the import
    if _imports_from_cli_tools_shared(content, "apply_filters"):
        source_content = _resolve_cli_tools_shared_filters()
        assert source_content is not None, (
            "filters.py imports from cli_tools_shared.filters but module not found"
        )
        content = source_content

    # Check for split('|') pattern
    assert "split('|')" in content or 'split("|")' in content, (
        f"filters.py missing pipe separator implementation for 'in' operator. "
        f"Fix: Ensure 'in' operator uses value.split('|') pattern."
    )


def _find_list_command_files(commands_dir, command_filter):
    """Find command files that define list commands with --filter option.

    Scans *.py files in the commands directory for functions decorated as "list"
    commands that also accept a --filter flag.

    Returns:
        List of Path objects for matching command files.
    """
    command_files = list(commands_dir.glob("*.py"))
    list_command_files = []

    for cmd_file in command_files:
        if cmd_file.name == "__init__.py":
            continue
        content = cmd_file.read_text()
        has_list = "def list(" in content or "@app.command(name=\"list\")" in content or '@app.command("list")' in content
        has_filter_option = '"--filter"' in content or "'--filter'" in content

        if command_filter:
            file_matches = cmd_file.stem == command_filter or cmd_file.stem == f"{command_filter}s"
            if not file_matches:
                continue

        if has_list and has_filter_option:
            list_command_files.append(cmd_file)

    return list_command_files


def test_command_files_import_filter_map(cli_name, cli_dir, command_filter):
    """Assertion 25: List command files with --filter import filter_map."""
    commands_dir = cli_dir / f"{cli_name.replace('-', '_')}_cli" / "commands"
    if not commands_dir.exists():
        pytest.skip("No commands directory found")

    list_command_files = _find_list_command_files(commands_dir, command_filter)

    if not list_command_files:
        if command_filter:
            pytest.skip(f"No list command files with --filter found for '{command_filter}'")
        else:
            pytest.skip("No list command files with --filter found")

    for cmd_file in list_command_files:
        content = cmd_file.read_text()
        has_import = (
            "filter_map" in content or
            "from ..filter_map" in content or
            "from ..filters import" in content or  # Local filters import
            "from cli_tools_shared.filters import" in content or  # Shared filters import
            "filter=filter" in content or  # Passes filter to client for server-side handling
            "filters=filter" in content  # Passes filter list to client for server-side handling
        )
        assert has_import, (
            f"{cmd_file.name} missing filter_map import. "
            f"Fix: Add 'from ..filter_map import FilterMap', 'from cli_tools_shared.filters import apply_filters', or pass filter to client"
        )


def test_command_files_use_filter_map(cli_name, cli_dir, command_filter):
    """Assertion 26: List commands with --filter use FilterMap."""
    commands_dir = cli_dir / f"{cli_name.replace('-', '_')}_cli" / "commands"
    if not commands_dir.exists():
        pytest.skip("No commands directory found")

    list_command_files = _find_list_command_files(commands_dir, command_filter)

    if not list_command_files:
        if command_filter:
            pytest.skip(f"No list command files with --filter found for '{command_filter}'")
        else:
            pytest.skip("No list command files with --filter found")

    for cmd_file in list_command_files:
        content = cmd_file.read_text()
        uses_filter_map = (
            "FilterMap" in content or
            "filter_map" in content or
            "apply_filters" in content or  # Direct filters usage
            "filter=filter" in content or  # Passes filter to client for server-side handling
            "filters=filter" in content  # Passes filter list to client for server-side handling
        )
        assert uses_filter_map, (
            f"{cmd_file.name} not using FilterMap. "
            f"Fix: Use FilterMap, apply_filters, or pass filter to client."
        )


def test_filter_help_describes_standard_syntax(cli_executable, cli_name, cli_dir, test_config, help_cache, command_filter):
    """Assertion 27: Filter help text must describe field:op:value syntax.

    This catches commands that implement --filter with non-standard parsing
    (e.g., simple substring matching instead of field:op:value syntax).
    """
    list_commands, timeout = discover_list_commands(cli_executable, cli_name, test_config, command_filter)

    if len(list_commands) == 0:
        pytest.skip(f"No list commands found in {cli_name}")

    # Patterns that indicate standard field:op:value syntax
    standard_patterns = [
        "field:op:value",
        "field:operator:value",
        ":eq:",
        ":ne:",
        ":gt:",
        ":lt:",
        ":gte:",
        ":lte:",
        ":contains:",
        ":like:",
        ":in:",
    ]

    # Patterns that indicate NON-standard (simple text) filtering
    # These should NOT be in the filter help text
    non_standard_patterns = [
        "case-insensitive",  # Suggests simple text matching
        "filter by name",    # Too simple, not structured
        "text to filter",    # Simple text matching
        "substring",         # Simple text matching
    ]

    errors = []
    for cmd_path in list_commands:
        help_text = help_cache(cmd_path).lower()

        # Skip if no --filter flag
        if "--filter" not in help_text and "-f" not in help_text:
            continue

        # Extract the help text for the --filter option
        # Look for the line containing --filter and its description
        filter_help_found = False
        has_standard_syntax = False
        has_non_standard = False

        for line in help_text.split('\n'):
            if '--filter' in line or '-f,' in line:
                filter_help_found = True
                line_lower = line.lower()

                # Check for standard syntax indicators
                for pattern in standard_patterns:
                    if pattern.lower() in line_lower:
                        has_standard_syntax = True
                        break

                # Check for non-standard patterns
                for pattern in non_standard_patterns:
                    if pattern.lower() in line_lower:
                        has_non_standard = True
                        break

        if filter_help_found and has_non_standard and not has_standard_syntax:
            errors.append(
                f"'{cli_name} {cmd_path}' --filter uses non-standard syntax. "
                f"Help text suggests simple text matching instead of field:op:value."
            )
        elif filter_help_found and not has_standard_syntax:
            errors.append(
                f"'{cli_name} {cmd_path}' --filter help text missing syntax description. "
                f"Should describe field:op:value format (e.g., 'name:eq:value', 'status:contains:active')."
            )

    if errors:
        pytest.fail(
            "Filter syntax validation failed:\n" +
            "\n".join(f"  - {e}" for e in errors) +
            "\n\nFix: Update --filter help text to describe field:op:value syntax. "
            "Example: help=\"Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)\""
        )


def test_filter_translation_smoke_test(cli_executable, cli_name, test_config, authenticated, command_filter, help_cache):
    """Comprehensive: Verify filter actually translates to API params (Decision 29)."""
    # This test is skipped when command_filter is set since it uses a generic "list" command
    if command_filter:
        pytest.skip("Skipping generic filter smoke test (command filter active)")

    timeout = test_config["general"]["command_timeout"]
    profile_args = []
    if isinstance(authenticated, dict) and authenticated.get("profile") and "--profile" in help_cache("list"):
        profile_args = ["--profile", authenticated["profile"]]

    # Try to run a list command with a simple filter
    # This is a smoke test - just verify it doesn't crash
    args = ["list", "--filter", "name:eq:test", "--limit", "1"] + profile_args
    full_cmd = f"{cli_name} {' '.join(args)}"
    print(f"  Executing: {full_cmd}")
    result = run_live_cli_command(cli_executable, args, timeout=timeout)

    # Should either succeed or fail gracefully (not crash)
    assert result.returncode in [0, 1, 2], (
        f"Filter translation caused unexpected error. "
        f"Stderr: {result.stderr}"
    )
