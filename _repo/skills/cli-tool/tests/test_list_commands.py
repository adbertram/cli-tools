"""List command validation tests (Section 4)."""

import pytest

from cli_test_utils import discover_nested_commands, get_list_commands, filter_commands_by_group


def test_list_commands_have_required_flags(cli_executable, cli_name, test_config, help_cache, command_filter):
    """Assertions 16-19: All list commands have required flags."""
    skip_list = test_config["command_discovery"]["skip_list"]
    timeout = test_config["general"]["command_timeout"]
    max_depth = test_config["general"]["max_nested_depth"]

    # Get CLI-specific max_depth if exists
    if cli_name in test_config.get("cli_specific", {}):
        max_depth = test_config["cli_specific"][cli_name].get("max_nested_depth", max_depth)

    # Discover all command paths
    commands = discover_nested_commands(cli_executable, "", 0, max_depth, skip_list, timeout)

    # Get list commands (CLI-specific or standard pattern)
    list_commands = get_list_commands(cli_name, test_config, commands)

    # Filter to specific command group if specified
    if command_filter:
        list_commands = filter_commands_by_group(list_commands, command_filter)
        if not list_commands:
            pytest.skip(f"No list commands under '{command_filter}'")

    if len(list_commands) == 0:
        pytest.skip(f"No list commands found in {cli_name}")

    errors = []
    for cmd_path in list_commands:
        help_text = help_cache(cmd_path)

        # Assertion 16: --table/-t flag
        if "--table" not in help_text and "-t" not in help_text:
            errors.append(f"'{cli_name} {cmd_path}' missing --table/-t flag")

        # Assertion 17: --limit/-l flag
        if "--limit" not in help_text and "-l" not in help_text:
            errors.append(f"'{cli_name} {cmd_path}' missing --limit/-l flag")

        # Assertion 18: --filter/-f flag (not required for search commands)
        is_search_command = "search" in cmd_path.lower()
        if not is_search_command and "--filter" not in help_text and "-f" not in help_text:
            errors.append(f"'{cli_name} {cmd_path}' missing --filter/-f flag")

        # Assertion 19: --properties/-p flag
        if "--properties" not in help_text and "-p" not in help_text:
            errors.append(f"'{cli_name} {cmd_path}' missing --properties/-p flag")

    if errors:
        pytest.fail(
            "List command flag validation failed:\n" +
            "\n".join(f"  - {e}" for e in errors) +
            "\n\nFix: Add required flags to list commands: "
            "--table/-t, --limit/-l, --filter/-f, --properties/-p"
        )
