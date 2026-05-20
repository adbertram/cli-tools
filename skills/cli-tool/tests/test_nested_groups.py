"""Nested command group validation tests (Section 9)."""

import pytest

from cli_test_utils import discover_nested_commands, parse_help_commands


def test_nested_groups_list_get_compliance(cli_executable, cli_name, test_config, help_cache, command_filter):
    """Assertions 35-37: Nested groups have list/get compliance."""
    skip_list = test_config["command_discovery"]["skip_list"]
    timeout = test_config["general"]["command_timeout"]
    max_depth = test_config["general"]["max_nested_depth"]

    if cli_name in test_config.get("cli_specific", {}):
        max_depth = test_config["cli_specific"][cli_name].get("max_nested_depth", max_depth)

    excluded_from_get = test_config["exclusions"]["excluded_from_get_required"]
    excluded_from_list = test_config["exclusions"]["excluded_from_list_required"]

    # Get main subgroups
    main_help = help_cache("")
    subgroups = parse_help_commands(main_help)
    subgroups = [g for g in subgroups if g != "auth"]

    # Filter to specific command group if specified
    if command_filter:
        subgroups = [g for g in subgroups if g == command_filter]
        if not subgroups:
            pytest.skip(f"Command group '{command_filter}' not found")

    issues = []

    for group in subgroups:
        # Discover nested commands starting from depth 1
        nested = discover_nested_commands(cli_executable, group, 1, max_depth, skip_list, timeout)

        # Filter to only nested groups (depth > 1)
        nested_groups = set()
        for cmd_path in nested:
            parts = cmd_path.split()
            if len(parts) >= 2:  # At least "group subgroup"
                # Get the parent group (everything except last command)
                parent = " ".join(parts[:-1])
                nested_groups.add(parent)

        for nested_group in nested_groups:
            group_commands = parse_help_commands(help_cache(nested_group))
            has_list = "list" in group_commands
            has_get = "get" in group_commands

            nested_name = nested_group.split()[-1]  # Last part only

            # Check list/get compliance
            if has_list and not has_get:
                if nested_name not in excluded_from_get:
                    issues.append(
                        f"Nested group '{nested_group}' has list but missing get. "
                        f"Fix: Add get command to nested group."
                    )

            if has_get and not has_list:
                if nested_name not in excluded_from_list:
                    issues.append(
                        f"Nested group '{nested_group}' has get but missing list. "
                        f"Fix: Add list command to nested group for ID discovery."
                    )

    if issues:
        pytest.fail(
            "Nested group compliance issues:\n" +
            "\n".join(f"  - {e}" for e in issues)
        )
