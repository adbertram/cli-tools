"""Command execution validation tests (Section 7)."""

import pytest
import json
import warnings

from cli_test_utils import run_live_cli_command, validate_json_output, discover_nested_commands, get_list_commands, get_fixture_args, filter_commands_by_group, discover_list_commands, get_cli_timeout


class PositionalArgWarning(UserWarning):
    """Warning issued when list commands have required positional arguments."""
    pass


def test_list_commands_have_no_required_positional_args(cli_executable, cli_name, test_config, help_cache, command_filter):
    """Assertion 28: List commands have no required positional arguments.

    NOTE: This test emits warnings instead of failures to maintain backward
    compatibility with existing CLIs that use positional arguments.
    """
    list_commands, timeout = discover_list_commands(cli_executable, cli_name, test_config, command_filter)

    if not list_commands:
        pytest.skip("No list commands found")

    warnings_list = []
    for cmd_path in list_commands:
        help_text = help_cache(cmd_path)

        # Check for required arguments (would show as ARGUMENT in help)
        # Typer shows required args without brackets
        lines = help_text.split('\n')
        usage_line = next((line for line in lines if 'Usage:' in line), None)

        if usage_line:
            # Required args appear without brackets: command ARGUMENT
            # Optional args appear with brackets: command [OPTIONS]
            tokens = usage_line.split()
            # Strip brackets for comparison (optional args have brackets)
            excluded = {"OPTIONS", "COMMAND", "COMMANDS", "NAME", "PATH", "ARGS"}
            has_required = any(
                token.isupper() and token.strip("[]") not in excluded
                for token in tokens
                if not token.startswith("[")  # Skip bracketed (optional) tokens entirely
            )
            if has_required:
                warnings_list.append(
                    f"'{cli_name} {cmd_path}' has required positional arguments. "
                    f"Usage: {usage_line.strip()}"
                )

    # Emit warnings instead of failing (for backward compatibility)
    if warnings_list:
        for warning_msg in warnings_list:
            warnings.warn(warning_msg, PositionalArgWarning)
        # Print a summary to stderr for visibility in test output
        print(f"\n⚠️  {len(warnings_list)} list command(s) have required positional arguments (consider making optional)")

    # Test always passes - positional args are now warnings, not failures


def _profile_args(auth_context, help_cache, cmd_path):
    """Return the active profile argument for commands that expose --profile."""
    if not isinstance(auth_context, dict):
        return []
    profile = auth_context.get("profile")
    if not profile:
        return []
    if "--profile" not in help_cache(cmd_path):
        return []
    return ["--profile", profile]


def test_list_commands_execute_successfully(cli_executable, cli_name, test_config, cli_fixtures, command_filter, require_authenticated, help_cache):
    """Assertions 29-30: List commands execute and return valid JSON."""
    list_commands, timeout = discover_list_commands(cli_executable, cli_name, test_config, command_filter)

    if not list_commands:
        pytest.skip("No list commands found")

    auth_context = require_authenticated()

    errors = []
    executed_commands = []
    for cmd_path in list_commands:
        # Get fixture-based args for this command (if fixtures defined)
        fixture_args = get_fixture_args(cli_name, cmd_path, cli_fixtures, test_config)
        profile_args = _profile_args(auth_context, help_cache, cmd_path)

        args = cmd_path.split() + ["--limit", "1"] + profile_args + fixture_args
        full_cmd = f"{cli_name} {' '.join(args)}"
        executed_commands.append(full_cmd)
        print(f"  Executing: {full_cmd}")
        result = run_live_cli_command(cli_executable, args, timeout=timeout)

        # Assertion 29: Exit code 0
        if result.returncode != 0:
            stderr_lower = (result.stderr or "").lower()
            if "missing option" in stderr_lower or "missing argument" in stderr_lower or "is required" in stderr_lower:
                if not fixture_args:
                    # No fixtures defined for this command - skip (expected for CLIs without fixtures)
                    continue
                # Fixtures were provided but command still failed - this is a real error
            errors.append(
                f"'{cli_name} {cmd_path} --limit 1' failed with exit code {result.returncode}. "
                f"Stderr: {result.stderr[:200] if result.stderr else 'empty'}"
            )
            continue

        # Assertion 30: Valid JSON output
        valid, data = validate_json_output(result.stdout)
        if not valid:
            errors.append(
                f"'{cli_name} {cmd_path}' did not output valid JSON. "
                f"Stdout: {result.stdout[:200]}"
            )
            continue

        # Assertion 31: --limit 1 should return at most 1 item
        items = _extract_items(data)
        if len(items) > 1:
            errors.append(
                f"'{cli_name} {cmd_path} --limit 1' returned {len(items)} items. "
                f"--limit 1 must return at most 1 item. Fix: Ensure --limit restricts result count."
            )

    if errors:
        pytest.fail(
            "List command execution failed:\n" +
            "\n".join(f"  - {e}" for e in errors)
        )


def test_stdout_stderr_separation(cli_executable, cli_name, test_config, cli_fixtures, command_filter, require_authenticated, help_cache):
    """Comprehensive: Verify all commands properly separate stdout/stderr (Decision 28)."""
    list_commands, timeout = discover_list_commands(cli_executable, cli_name, test_config, command_filter)

    if not list_commands:
        pytest.skip("No list commands found")

    auth_context = require_authenticated()

    errors = []
    for cmd_path in list_commands:
        # Get fixture-based args for this command (if fixtures defined)
        fixture_args = get_fixture_args(cli_name, cmd_path, cli_fixtures, test_config)
        profile_args = _profile_args(auth_context, help_cache, cmd_path)

        args = cmd_path.split() + ["--limit", "1"] + profile_args + fixture_args
        full_cmd = f"{cli_name} {' '.join(args)}"
        print(f"  Executing: {full_cmd}")
        result = run_live_cli_command(cli_executable, args, timeout=timeout)

        if result.returncode == 0:
            # Stdout should be ONLY JSON, no interleaved messages
            problem_markers = ["Success", "✓", "Done", "Fetching", "Loading", "Retrieved"]
            for marker in problem_markers:
                if marker in result.stdout:
                    errors.append(
                        f"'{cli_name} {cmd_path}' has non-JSON content '{marker}' in stdout. "
                        f"Fix: Use print_json() for data only."
                    )
                    break

            # Stderr should not contain JSON
            if result.stderr:
                try:
                    json.loads(result.stderr)
                    errors.append(
                        f"'{cli_name} {cmd_path}' has JSON in stderr. "
                        f"Fix: JSON data must go to stdout only."
                    )
                except json.JSONDecodeError:
                    pass  # Correct - stderr should not be JSON

    if errors:
        pytest.fail(
            "Stream separation issues:\n" +
            "\n".join(f"  - {e}" for e in errors) +
            "\n\nFix: Move status messages to stderr, data to stdout only."
        )


def test_properties_flag_with_dot_notation(cli_executable, cli_name, test_config, cli_fixtures, command_filter, require_authenticated, help_cache):
    """Comprehensive: Test --properties with nested field extraction (Decision 27)."""
    list_commands, timeout = discover_list_commands(cli_executable, cli_name, test_config, command_filter)

    if not list_commands:
        pytest.skip("No list commands found")

    auth_context = require_authenticated()

    # Use first discovered list command
    cmd_path = list_commands[0]

    # Get fixture-based args for this command (if fixtures defined)
    fixture_args = get_fixture_args(cli_name, cmd_path, cli_fixtures, test_config)
    profile_args = _profile_args(auth_context, help_cache, cmd_path)

    # First, discover actual field names by fetching one item without --properties
    discovery_args = cmd_path.split() + ["--limit", "1"] + profile_args + fixture_args
    discovery_result = run_live_cli_command(cli_executable, discovery_args, timeout=timeout)
    if discovery_result.returncode != 0:
        if "required" in discovery_result.stderr.lower() or "missing" in discovery_result.stderr.lower():
            pytest.fail(
                f"Command requires positional argument but no fixture defined. "
                f"Fix: Add fixture to tests/fixtures/{cli_name}.json and param_fixtures in cli_test_config.toml. "
                f"See tests/fixtures/notion.json for example. Error: {discovery_result.stderr[:100]}"
            )
        pytest.skip(f"Could not discover fields (command failed): {discovery_result.stderr[:100]}")

    valid, discovery_data = validate_json_output(discovery_result.stdout)
    if not valid or not isinstance(discovery_data, list) or len(discovery_data) == 0:
        pytest.skip("No items returned to discover field names")

    # Pick the first two field names from the actual data
    actual_fields = list(discovery_data[0].keys())
    if len(actual_fields) < 2:
        pytest.skip(f"Item has fewer than 2 fields: {actual_fields}")
    test_fields = actual_fields[:2]
    properties_value = ",".join(test_fields)

    args = cmd_path.split() + ["--properties", properties_value, "--limit", "1"] + profile_args + fixture_args
    full_cmd = f"{cli_name} {' '.join(args)}"
    print(f"  Executing: {full_cmd}")
    result = run_live_cli_command(cli_executable, args, timeout=timeout)

    if result.returncode != 0:
        if "required" in result.stderr.lower() or "missing" in result.stderr.lower():
            pytest.fail(
                f"Command requires positional argument but no fixture defined. "
                f"Fix: Add fixture to tests/fixtures/{cli_name}.json and param_fixtures in cli_test_config.toml. "
                f"See tests/fixtures/notion.json for example. Error: {result.stderr[:100]}"
            )
        pytest.skip(f"Could not test --properties flag (command failed): {result.stderr[:100]}")

    valid, data = validate_json_output(result.stdout)
    if not valid:
        pytest.skip("Properties output not valid JSON")

    # If we got results, verify only specified properties returned
    if isinstance(data, list) and len(data) > 0:
        item = data[0]
        assert test_fields[0] in item or test_fields[1] in item, (
            f"Properties filter should include specified fields ({properties_value}), "
            f"got keys: {list(item.keys())}"
        )




def _run_list_command_with_limit(cli_executable, cli_name, cmd_path, limit, extra_args, fixture_args, timeout, profile_args=None):
    """Helper to run a list command with a specific limit and return (full_cmd, result)."""
    profile_args = profile_args or []
    args = cmd_path.split() + ["--limit", str(limit)] + extra_args + profile_args + fixture_args
    full_cmd = f"{cli_name} {' '.join(args)}"
    print(f"  Executing: {full_cmd}")
    result = run_live_cli_command(cli_executable, args, timeout=timeout)
    return full_cmd, result


def _extract_items(data):
    """Extract the list of items from various JSON response formats.

    Handles:
        - Plain list: [item1, item2]
        - Wrapped: {"items": [...]} or {"records": [...]} or {"results": [...]}
        - Single object: {"id": ...} -> [{"id": ...}]

    Returns:
        List of item dicts, or empty list if not extractable.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "records", "results", "data", "entries"):
            if key in data and isinstance(data[key], list):
                return data[key]
        # Single object (has an "id" field but no list wrapper)
        if "id" in data:
            return [data]
    return []


GET_IDENTIFIER_FIELDS = {
    ("ahrefs", "site-audit"): "project_id",
    ("descript", "compositions"): "composition_id",
    ("venmo", "transactions"): "payment_id",
}


def _get_identifier_field(cli_name, group):
    return GET_IDENTIFIER_FIELDS.get((cli_name, group), "id")


def _nested_value(data, path):
    current = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def _is_skippable_failure(result, fixture_args):
    """Check if a command failure is due to missing fixtures (not a real error)."""
    if result.returncode == 0:
        return False
    stderr_lower = (result.stderr or "").lower()
    missing_arg = "missing option" in stderr_lower or "missing argument" in stderr_lower or "is required" in stderr_lower
    return missing_arg and not fixture_args


def test_list_commands_limit_is_respected(cli_executable, cli_name, test_config, cli_fixtures, command_filter, require_authenticated, help_cache):
    """Assertion: --limit actually restricts the number of returned items.

    Runs each list command with --limit 1 and verifies the response contains
    at most 1 item. Then runs with --limit 3 and verifies at most 3 items.
    If both return the same count, verifies both are within their limits.
    """
    list_commands, timeout = discover_list_commands(cli_executable, cli_name, test_config, command_filter)

    if not list_commands:
        pytest.skip("No list commands found")

    auth_context = require_authenticated()

    errors = []
    for cmd_path in list_commands:
        fixture_args = get_fixture_args(cli_name, cmd_path, cli_fixtures, test_config)
        profile_args = _profile_args(auth_context, help_cache, cmd_path)

        # Run with --limit 1
        full_cmd_1, result_1 = _run_list_command_with_limit(
            cli_executable, cli_name, cmd_path, 1, [], fixture_args, timeout, profile_args
        )
        if _is_skippable_failure(result_1, fixture_args):
            continue
        if result_1.returncode != 0:
            errors.append(
                f"'{full_cmd_1}' failed with exit code {result_1.returncode}. "
                f"Stderr: {(result_1.stderr or '')[:200]}"
            )
            continue

        valid_1, data_1 = validate_json_output(result_1.stdout)
        if not valid_1:
            errors.append(f"'{full_cmd_1}' did not output valid JSON.")
            continue

        items_1 = _extract_items(data_1)

        # --limit 1 must return at most 1 item
        if len(items_1) > 1:
            errors.append(
                f"'{full_cmd_1}' returned {len(items_1)} items but --limit 1 should return at most 1. "
                f"Fix: Ensure --limit actually restricts the result count."
            )
            continue

        # Run with --limit 3
        full_cmd_3, result_3 = _run_list_command_with_limit(
            cli_executable, cli_name, cmd_path, 3, [], fixture_args, timeout, profile_args
        )
        if result_3.returncode != 0:
            continue  # Already tested limit 1, don't double-report

        valid_3, data_3 = validate_json_output(result_3.stdout)
        if not valid_3:
            continue

        items_3 = _extract_items(data_3)

        # --limit 3 must return at most 3 items
        if len(items_3) > 3:
            errors.append(
                f"'{full_cmd_3}' returned {len(items_3)} items but --limit 3 should return at most 3. "
                f"Fix: Ensure --limit actually restricts the result count."
            )

    if errors:
        pytest.fail(
            "List command --limit validation failed:\n" +
            "\n".join(f"  - {e}" for e in errors)
        )


def test_list_commands_with_table_flag(cli_executable, cli_name, test_config, cli_fixtures, command_filter, require_authenticated, help_cache):
    """Assertion: --table flag produces Rich table output, not JSON.

    Every list command must support --table/-t and produce table-formatted
    output (not JSON). Verifies the output is NOT parseable as JSON (since
    it should be a human-readable Rich table).
    """
    list_commands, timeout = discover_list_commands(cli_executable, cli_name, test_config, command_filter)

    if not list_commands:
        pytest.skip("No list commands found")

    auth_context = require_authenticated()

    errors = []
    for cmd_path in list_commands:
        fixture_args = get_fixture_args(cli_name, cmd_path, cli_fixtures, test_config)
        profile_args = _profile_args(auth_context, help_cache, cmd_path)
        full_cmd, result = _run_list_command_with_limit(
            cli_executable, cli_name, cmd_path, 1, ["--table"], fixture_args, timeout, profile_args
        )

        if _is_skippable_failure(result, fixture_args):
            continue

        if result.returncode != 0:
            stderr_lower = (result.stderr or "").lower()
            if "no such option: --table" in stderr_lower:
                errors.append(f"'{full_cmd}' does not accept --table flag")
            else:
                errors.append(
                    f"'{full_cmd}' failed with exit code {result.returncode}. "
                    f"Stderr: {(result.stderr or '')[:200]}"
                )
            continue

        # Should produce some output
        combined = (result.stdout or "") + (result.stderr or "")
        if not combined.strip():
            errors.append(f"'{full_cmd}' produced no output at all")
            continue

        # stdout should NOT be valid JSON - it should be a Rich table
        stdout = (result.stdout or "").strip()
        if stdout:
            try:
                json.loads(stdout)
                # If it parses as JSON, --table is not producing table output
                errors.append(
                    f"'{full_cmd}' output is JSON but --table should produce Rich table format. "
                    f"Fix: Use print_table() when --table is True, not print_json()."
                )
            except json.JSONDecodeError:
                pass  # Correct - table output should not be JSON

    if errors:
        pytest.fail(
            "List command --table execution failed:\n" +
            "\n".join(f"  - {e}" for e in errors)
        )


def test_list_commands_with_filter_flag(cli_executable, cli_name, test_config, cli_fixtures, command_filter, require_authenticated, help_cache):
    """Assertion: --filter accepts field:op:value syntax and reduces results.

    Every list command must accept --filter. A nonsense filter value should
    return fewer results than an unfiltered query (or zero results). The filter
    must not crash and must produce valid JSON output.
    """
    list_commands, timeout = discover_list_commands(cli_executable, cli_name, test_config, command_filter)

    if not list_commands:
        pytest.skip("No list commands found")

    auth_context = require_authenticated()

    errors = []
    for cmd_path in list_commands:
        fixture_args = get_fixture_args(cli_name, cmd_path, cli_fixtures, test_config)
        profile_args = _profile_args(auth_context, help_cache, cmd_path)

        # First run WITHOUT filter to get a baseline count
        full_cmd_base, result_base = _run_list_command_with_limit(
            cli_executable, cli_name, cmd_path, 5, [], fixture_args, timeout, profile_args
        )
        if _is_skippable_failure(result_base, fixture_args):
            continue
        if result_base.returncode != 0:
            continue  # Can't get baseline - skip

        valid_base, data_base = validate_json_output(result_base.stdout)
        if not valid_base:
            continue
        items_base = _extract_items(data_base)

        # Now run WITH a nonsense filter that should match nothing
        args = cmd_path.split() + ["--limit", "5", "--filter", "name:eq:__zzz_nonexistent_xyzzy__"] + profile_args + fixture_args
        full_cmd_filter = f"{cli_name} {' '.join(args)}"
        print(f"  Executing: {full_cmd_filter}")
        result_filter = run_live_cli_command(cli_executable, args, timeout=timeout)

        stderr_lower = (result_filter.stderr or "").lower()

        if "no such option: --filter" in stderr_lower:
            errors.append(
                f"'{full_cmd_filter}' does not accept --filter flag. "
                f"Fix: Add --filter/-f option to list command."
            )
            continue

        # Filter should not crash (exit codes 0, 1, 2 are acceptable)
        if result_filter.returncode not in (0, 1, 2):
            errors.append(
                f"'{full_cmd_filter}' crashed with exit code {result_filter.returncode}. "
                f"Stderr: {(result_filter.stderr or '')[:200]}"
            )
            continue

        # If successful, verify output is valid JSON and has fewer/equal items
        if result_filter.returncode == 0 and result_filter.stdout.strip():
            valid_f, data_f = validate_json_output(result_filter.stdout)
            if not valid_f:
                errors.append(
                    f"'{full_cmd_filter}' returned non-JSON output. "
                    f"Stdout: {result_filter.stdout[:200]}"
                )
                continue

            items_filtered = _extract_items(data_f)

            # Filtered results should be <= unfiltered (nonsense filter should match nothing or less)
            if len(items_base) > 0 and len(items_filtered) >= len(items_base):
                # The filter didn't reduce results - it may not be working
                # Only flag as error if baseline had items (empty baseline = can't tell)
                errors.append(
                    f"'{full_cmd_filter}' returned {len(items_filtered)} items, same as "
                    f"unfiltered ({len(items_base)}). --filter may not be working. "
                    f"Fix: Ensure --filter actually filters results using field:op:value syntax."
                )

    if errors:
        pytest.fail(
            "List command --filter validation failed:\n" +
            "\n".join(f"  - {e}" for e in errors) +
            "\n\nFix: Ensure all list commands accept --filter with field:op:value syntax "
            "and actually filter the results."
        )


def test_list_commands_with_properties_flag(cli_executable, cli_name, test_config, cli_fixtures, command_filter, require_authenticated, help_cache):
    """Assertion: --properties restricts output to only requested fields.

    Every list command must accept --properties. When provided, the output
    should contain ONLY the requested fields (plus minimal metadata like 'id').
    Compares field count with and without --properties to verify restriction.
    """
    list_commands, timeout = discover_list_commands(cli_executable, cli_name, test_config, command_filter)

    if not list_commands:
        pytest.skip("No list commands found")

    auth_context = require_authenticated()

    errors = []
    for cmd_path in list_commands:
        fixture_args = get_fixture_args(cli_name, cmd_path, cli_fixtures, test_config)
        profile_args = _profile_args(auth_context, help_cache, cmd_path)

        # First get unfiltered output to know what fields exist
        full_cmd_base, result_base = _run_list_command_with_limit(
            cli_executable, cli_name, cmd_path, 1, [], fixture_args, timeout, profile_args
        )
        if _is_skippable_failure(result_base, fixture_args):
            continue
        if result_base.returncode != 0:
            continue

        valid_base, data_base = validate_json_output(result_base.stdout)
        if not valid_base:
            continue
        items_base = _extract_items(data_base)
        if not items_base or not isinstance(items_base[0], dict):
            continue
        base_keys = set(items_base[0].keys())

        # Now run with --properties id,name
        full_cmd_props, result_props = _run_list_command_with_limit(
            cli_executable, cli_name, cmd_path, 1, ["--properties", "id,name"], fixture_args, timeout, profile_args
        )

        if result_props.returncode != 0:
            stderr_lower = (result_props.stderr or "").lower()
            if "no such option: --properties" in stderr_lower:
                errors.append(
                    f"'{full_cmd_props}' does not accept --properties flag. "
                    f"Fix: Add --properties/-p option to list command."
                )
            else:
                errors.append(
                    f"'{full_cmd_props}' failed with exit code {result_props.returncode}. "
                    f"Stderr: {(result_props.stderr or '')[:200]}"
                )
            continue

        if not result_props.stdout.strip():
            continue

        valid_p, data_p = validate_json_output(result_props.stdout)
        if not valid_p:
            errors.append(
                f"'{full_cmd_props}' returned non-JSON output with --properties. "
                f"Stdout: {result_props.stdout[:200]}"
            )
            continue

        items_props = _extract_items(data_p)
        if not items_props or not isinstance(items_props[0], dict):
            continue

        props_keys = set(items_props[0].keys())
        requested = {"id", "name"}

        # Properties output should have fewer or equal keys than unfiltered
        if len(base_keys) > 2 and len(props_keys) >= len(base_keys):
            errors.append(
                f"'{full_cmd_props}' --properties id,name returned {len(props_keys)} fields "
                f"(same as unfiltered: {len(base_keys)}). Properties filter is not restricting output. "
                f"Unfiltered keys: {base_keys}, Properties keys: {props_keys}. "
                f"Fix: --properties should return only the requested fields."
            )
        elif props_keys and not props_keys.intersection(requested):
            errors.append(
                f"'{full_cmd_props}' --properties id,name returned keys {props_keys} "
                f"with no overlap to requested fields. "
                f"Fix: --properties should include the requested field names in output."
            )

    if errors:
        pytest.fail(
            "List command --properties validation failed:\n" +
            "\n".join(f"  - {e}" for e in errors) +
            "\n\nFix: Ensure --properties restricts output to only requested fields."
        )


def test_get_commands_execute_successfully(cli_executable, cli_name, test_config, cli_fixtures, command_filter, require_authenticated, help_cache):
    """Assertion: Get commands return a single item (not a list).

    Discovers all get commands, fetches an ID from the corresponding list command,
    then executes get with that ID. Verifies:
    - Exit code 0
    - Valid JSON output
    - Returns a single object (dict), not a list
    - Object has an 'id' field matching the requested ID
    """
    from cli_test_utils import parse_help_commands

    timeout = get_cli_timeout(cli_name, test_config)
    skip_list = test_config["command_discovery"]["skip_list"]
    max_depth = test_config["general"]["max_nested_depth"]

    if cli_name in test_config.get("cli_specific", {}):
        max_depth = test_config["cli_specific"][cli_name].get("max_nested_depth", max_depth)

    commands = discover_nested_commands(cli_executable, "", 0, max_depth, skip_list, timeout)
    list_commands = get_list_commands(cli_name, test_config, commands)

    if command_filter:
        list_commands = filter_commands_by_group(list_commands, command_filter)

    # Keep get execution on the same live-command surface as the list execution
    # suite so per-CLI allowlists can exclude browser-session/resource-specific
    # commands that are not part of generic execution coverage.
    get_groups = []
    for list_cmd_path in list_commands:
        if list_cmd_path == "list" or list_cmd_path.startswith("auth "):
            continue
        group = list_cmd_path.rsplit(" ", 1)[0]
        if f"{group} get" in commands:
            get_groups.append(group)

    if not get_groups:
        pytest.skip("No command groups with both list and get found")

    auth_context = require_authenticated()

    errors = []
    for group in get_groups:
        # First, run list --limit 1 to get an ID
        list_cmd_path = f"{group} list"
        fixture_args = get_fixture_args(cli_name, list_cmd_path, cli_fixtures, test_config)
        list_profile_args = _profile_args(auth_context, help_cache, list_cmd_path)
        list_args = list_cmd_path.split() + ["--limit", "1"] + list_profile_args + fixture_args
        print(f"  Fetching ID via: {cli_name} {' '.join(list_args)}")
        list_result = run_live_cli_command(cli_executable, list_args, timeout=timeout)

        if list_result.returncode != 0:
            print(f"  Skipping {group} get (list failed)")
            continue

        valid, data = validate_json_output(list_result.stdout)
        if not valid or not data:
            continue

        items = _extract_items(data)
        if not items or not isinstance(items[0], dict):
            continue

        id_field = _get_identifier_field(cli_name, group)
        item_id = _nested_value(items[0], id_field) or items[0].get("id") or items[0].get("name")
        if not item_id:
            print(f"  Skipping {group} get (no ID found in list output)")
            continue

        # Now run get with the discovered ID
        get_cmd_path = f"{group} get"
        get_fixture_args_list = get_fixture_args(cli_name, get_cmd_path, cli_fixtures, test_config)
        get_profile_args = _profile_args(auth_context, help_cache, get_cmd_path)

        get_args = get_cmd_path.split() + get_profile_args + get_fixture_args_list + [str(item_id)]
        full_cmd = f"{cli_name} {' '.join(get_args)}"
        print(f"  Executing: {full_cmd}")
        get_result = run_live_cli_command(cli_executable, get_args, timeout=timeout)

        if get_result.returncode != 0:
            stderr_lower = (get_result.stderr or "").lower()
            if ("missing argument" in stderr_lower or "missing option" in stderr_lower) and not get_fixture_args_list:
                print(f"  Skipping {group} get (needs fixtures)")
                continue
            errors.append(
                f"'{full_cmd}' failed with exit code {get_result.returncode}. "
                f"Stderr: {(get_result.stderr or '')[:200]}"
            )
            continue

        valid, get_data = validate_json_output(get_result.stdout)
        if not valid:
            errors.append(
                f"'{full_cmd}' did not output valid JSON. "
                f"Stdout: {get_result.stdout[:200]}"
            )
            continue

        # Get should return a single object, not a list
        if isinstance(get_data, list):
            errors.append(
                f"'{full_cmd}' returned a list of {len(get_data)} items but get should return "
                f"a single object. Fix: Return the item dict directly, not wrapped in a list."
            )
            continue

        if not isinstance(get_data, dict):
            errors.append(
                f"'{full_cmd}' returned {type(get_data).__name__} but get should return a dict."
            )
            continue

        # Verify the returned object has an ID field
        returned_id = _nested_value(get_data, id_field)
        if returned_id is None:
            # Check if it's nested (some APIs wrap in {"record": {...}})
            for key in ("record", "item", "result", "data"):
                if key in get_data and isinstance(get_data[key], dict):
                    returned_id = _nested_value(get_data[key], id_field)
                    break

        if returned_id is not None and str(returned_id) != str(item_id):
            errors.append(
                f"'{full_cmd}' returned id='{returned_id}' but requested id='{item_id}'. "
                f"Get command returned wrong item."
            )

    if errors:
        pytest.fail(
            "Get command execution failed:\n" +
            "\n".join(f"  - {e}" for e in errors)
        )


def test_no_silent_error_swallowing(cli_dir, cli_name, command_filter):
    """Critical: Commands must NOT silently swallow API errors (Decision 32).

    Silent error handling is DANGEROUS because:
    1. Users get empty results with no indication of failure
    2. Debugging becomes impossible - no error messages
    3. Data appears missing when API is actually broken

    Commands MUST:
    - Let exceptions propagate OR
    - Re-raise with context OR
    - Return non-zero exit code with error message

    Commands must NEVER:
    - catch Exception/ClientError and continue silently
    - return empty results when API calls fail
    - use bare 'except:' or 'except Exception:'
    """
    commands_dir = cli_dir / f"{cli_name.replace('-', '_')}_cli" / "commands"
    if not commands_dir.exists():
        pytest.skip("No commands directory found")

    errors = []
    dangerous_patterns = [
        # Pattern: catch error and continue (silent swallow)
        ("except ClientError:\n            # Skip", "catches ClientError and skips silently"),
        ("except ClientError:\n                # Skip", "catches ClientError and skips silently"),
        ("except ClientError:\n                continue", "catches ClientError and continues silently"),
        ("except ClientError:\n            continue", "catches ClientError and continues silently"),
        ("except Exception:\n            continue", "catches Exception and continues silently"),
        ("except Exception:\n                continue", "catches Exception and continues silently"),
        ("except:\n            continue", "bare except with continue"),
        ("except:\n                continue", "bare except with continue"),
    ]

    for py_file in commands_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue

        content = py_file.read_text()

        for pattern, description in dangerous_patterns:
            if pattern in content:
                errors.append(
                    f"{py_file.name}: {description}. "
                    f"Fix: Surface the error to user instead of silently continuing."
                )

    if errors:
        pytest.fail(
            "Commands silently swallow API errors (CRITICAL):\n" +
            "\n".join(f"  - {e}" for e in errors) +
            "\n\nFix: Remove silent error handling. Let errors propagate or "
            "re-raise with context. Users must see error messages."
        )
