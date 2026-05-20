"""Get command validation tests (Section 8)."""

import pytest

from cli_test_utils import parse_help_commands


def test_groups_with_list_must_have_get(cli_name, test_config, help_cache, command_filter):
    """Assertions 31-32: Groups with list must have get (unless excluded)."""
    # Parse main help to get subgroups
    main_help = help_cache("")
    subgroups = parse_help_commands(main_help)

    # Remove auth and top-level utility commands
    subgroups = [g for g in subgroups if g != "auth"]

    # Filter to specific command group if specified
    if command_filter:
        subgroups = [g for g in subgroups if g == command_filter]
        if not subgroups:
            pytest.skip(f"Command group '{command_filter}' not found")

    excluded_from_get = test_config["exclusions"]["excluded_from_get_required"]

    errors = []
    for group in subgroups:
        group_commands = parse_help_commands(help_cache(group))
        has_list = "list" in group_commands
        has_get = "get" in group_commands

        if has_list and not has_get:
            if group not in excluded_from_get:
                errors.append(
                    f"'{cli_name} {group}' has list but missing get command. "
                    f"Fix: Add get command to {group} group: "
                    f"@app.command('get') with item ID argument."
                )

    if errors:
        pytest.fail(
            "List/Get pairing validation failed:\n" +
            "\n".join(f"  - {e}" for e in errors)
        )


def test_groups_with_get_must_have_list(cli_name, test_config, help_cache, command_filter):
    """Assertion 33: Groups with get must have list (unless excluded)."""
    main_help = help_cache("")
    subgroups = parse_help_commands(main_help)
    subgroups = [g for g in subgroups if g != "auth"]

    # Filter to specific command group if specified
    if command_filter:
        subgroups = [g for g in subgroups if g == command_filter]
        if not subgroups:
            pytest.skip(f"Command group '{command_filter}' not found")

    excluded_from_list = test_config["exclusions"]["excluded_from_list_required"]

    errors = []
    for group in subgroups:
        group_commands = parse_help_commands(help_cache(group))
        has_list = "list" in group_commands
        has_get = "get" in group_commands

        if has_get and not has_list:
            if group not in excluded_from_list:
                errors.append(
                    f"'{cli_name} {group}' has get but missing list command "
                    f"(users can't discover IDs). "
                    f"Fix: Add list command to {group} group to allow ID discovery."
                )

    if errors:
        pytest.fail(
            "Get/List pairing validation failed:\n" +
            "\n".join(f"  - {e}" for e in errors)
        )


def test_get_commands_have_table_flag(cli_name, test_config, help_cache, command_filter):
    """Assertion 34: All get commands have --table/-t flag."""
    main_help = help_cache("")
    subgroups = parse_help_commands(main_help)
    subgroups = [g for g in subgroups if g != "auth"]

    # Filter to specific command group if specified
    if command_filter:
        subgroups = [g for g in subgroups if g == command_filter]

    get_commands = []

    # Find all get commands
    for group in subgroups:
        group_commands = parse_help_commands(help_cache(group))
        if "get" in group_commands:
            get_commands.append(f"{group} get")

    # Check for top-level get (only if no command filter or filter matches)
    if not command_filter:
        if "get" in parse_help_commands(main_help):
            get_commands.append("get")

    if not get_commands:
        if command_filter:
            pytest.skip(f"No get commands under '{command_filter}'")
        else:
            pytest.skip("No get commands found")

    errors = []
    for cmd_path in get_commands:
        help_text = help_cache(cmd_path)
        if "--table" not in help_text and "-t" not in help_text:
            errors.append(
                f"'{cli_name} {cmd_path}' missing --table/-t flag."
            )

    if errors:
        pytest.fail(
            "Get command flag validation failed:\n" +
            "\n".join(f"  - {e}" for e in errors) +
            "\n\nFix: Add table parameter: "
            "table: bool = typer.Option(False, '--table', '-t', help='Display as table')"
        )
