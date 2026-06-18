"""Generated skill usage.json freshness tests."""

import json
from pathlib import Path

import pytest

from cli_test_utils import (
    discover_nested_commands,
    extract_usage_command_paths,
    extract_usage_command_parameters,
    leaf_command_paths,
    parse_help_commands,
    parse_help_parameters,
)


def _usage_json_paths(cli_name):
    return [
        Path(__file__).resolve().parents[3] / "skills" / f"{cli_name}-cli" / "usage.json",
    ]


def test_usage_command_paths_extract_nested_tree():
    """usage.json command extraction preserves nested command paths."""
    usage = {
        "commands": {
            "analytics": {
                "commands": {
                    "report": {},
                    "top-pages": {},
                    "traffic": {},
                }
            },
            "auth": {"commands": {"login": {}, "status": {}}},
        }
    }

    assert extract_usage_command_paths(usage) == {
        "analytics",
        "analytics report",
        "analytics top-pages",
        "analytics traffic",
        "auth",
        "auth login",
        "auth status",
    }


def test_usage_command_parameters_extract_nested_tree():
    """usage.json parameter extraction preserves nested command params."""
    usage = {
        "commands": {
            "analytics": {
                "commands": {
                    "report": {
                        "arguments": [
                            {"name": "property_id", "type": "TEXT", "required": True, "help": "GA4 property ID"}
                        ],
                        "options": [
                            {
                                "name": "--limit",
                                "type": "INTEGER",
                                "required": False,
                                "help": "Maximum rows",
                                "short": "-l",
                                "default": "10",
                            }
                        ],
                    }
                }
            }
        }
    }

    assert extract_usage_command_parameters(usage) == {
        "analytics": {"arguments": [], "options": []},
        "analytics report": {
            "arguments": [
                {"name": "property_id", "type": "TEXT", "required": True, "help": "GA4 property ID"}
            ],
            "options": [
                {
                    "name": "--limit",
                    "type": "INTEGER",
                    "required": False,
                    "help": "Maximum rows",
                    "short": "-l",
                    "default": "10",
                }
            ],
        },
    }


def test_help_parameters_parse_rich_sections():
    """Live help parameter parsing matches usage.json parameter records."""
    help_text = """
╭─ Arguments ───────────────────────────────────────────────────────────────╮
│ *    property_id      TEXT     GA4 property ID [required]                 │
╰───────────────────────────────────────────────────────────────────────────╯
╭─ Options ─────────────────────────────────────────────────────────────────╮
│ --limit            -l      INTEGER  Maximum rows [default: 10]            │
│ --profile                  TEXT     Profile name [env var: PROFILE]       │
│ --credential-type,--credential  -c  TEXT     Credential type              │
│ --table            -t               Display as table                      │
│ --help                              Show this message and exit.           │
╰───────────────────────────────────────────────────────────────────────────╯
"""

    assert parse_help_parameters(help_text) == {
        "arguments": [
            {"name": "property_id", "type": "TEXT", "required": True, "help": "GA4 property ID"}
        ],
        "options": [
            {
                "name": "--limit",
                "type": "INTEGER",
                "required": False,
                "help": "Maximum rows",
                "short": "-l",
                "default": "10",
            },
            {
                "name": "--profile",
                "type": "TEXT",
                "required": False,
                "help": "Profile name",
                "env_var": "PROFILE",
            },
            {
                "name": "--credential-type",
                "type": "TEXT",
                "required": False,
                "help": "Credential type",
                "short": "-c",
            },
            {
                "name": "--table",
                "type": "bool",
                "required": False,
                "help": "Display as table",
                "short": "-t",
            },
        ],
    }


def test_usage_json_matches_installed_command_tree(
    cli_executable,
    cli_name,
    test_config,
    command_filter,
    help_cache,
):
    """Generated usage.json must match the installed CLI command tree."""
    skip_list = test_config["command_discovery"]["skip_list"]
    timeout = test_config["general"]["command_timeout"]
    max_depth = test_config["general"]["max_nested_depth"]
    if cli_name in test_config.get("cli_specific", {}):
        max_depth = test_config["cli_specific"][cli_name].get("max_nested_depth", max_depth)

    if command_filter:
        main_commands = set(parse_help_commands(help_cache("")))
        if command_filter not in main_commands:
            pytest.skip(f"Command group '{command_filter}' not found")
        live_paths = {command_filter}
        live_paths.update(
            discover_nested_commands(
                cli_executable,
                command_filter,
                depth=1,
                max_depth=max_depth,
                skip_list=skip_list,
                timeout=timeout,
            )
        )
    else:
        live_paths = set(
            discover_nested_commands(
                cli_executable,
                "",
                depth=0,
                max_depth=max_depth,
                skip_list=skip_list,
                timeout=timeout,
            )
        )

    for usage_json in _usage_json_paths(cli_name):
        if not usage_json.exists():
            pytest.skip(f"usage.json not found at {usage_json}")

        usage = json.loads(usage_json.read_text())
        usage_paths = extract_usage_command_paths(usage)

        if command_filter:
            usage_paths = {
                path for path in usage_paths
                if path == command_filter or path.startswith(f"{command_filter} ")
            }

        missing = sorted(live_paths - usage_paths)
        stale = sorted(usage_paths - live_paths)

        assert not missing and not stale, (
            f"{usage_json} is stale for installed '{cli_name}' command tree. "
            f"Missing live commands: {missing}. Stale documented commands: {stale}. "
            f"Fix: regenerate or update usage.json from live '{cli_name} --help' output."
        )

        if not command_filter:
            live_leaf_count = len(leaf_command_paths(live_paths))
            assert usage.get("total_commands") == live_leaf_count, (
                f"{usage_json} total_commands is stale. "
                f"Expected {live_leaf_count}, found {usage.get('total_commands')}. "
                f"Fix: regenerate usage.json from live '{cli_name} --help' output."
            )


def test_usage_json_matches_installed_command_parameters(
    cli_executable,
    cli_name,
    test_config,
    command_filter,
    help_cache,
):
    """Generated usage.json must match live arguments and options for each command."""
    skip_list = test_config["command_discovery"]["skip_list"]
    timeout = test_config["general"]["command_timeout"]
    max_depth = test_config["general"]["max_nested_depth"]
    if cli_name in test_config.get("cli_specific", {}):
        max_depth = test_config["cli_specific"][cli_name].get("max_nested_depth", max_depth)

    if command_filter:
        main_commands = set(parse_help_commands(help_cache("")))
        if command_filter not in main_commands:
            pytest.skip(f"Command group '{command_filter}' not found")
        live_paths = {command_filter}
        live_paths.update(
            discover_nested_commands(
                cli_executable,
                command_filter,
                depth=1,
                max_depth=max_depth,
                skip_list=skip_list,
                timeout=timeout,
            )
        )
    else:
        live_paths = set(
            discover_nested_commands(
                cli_executable,
                "",
                depth=0,
                max_depth=max_depth,
                skip_list=skip_list,
                timeout=timeout,
            )
        )

    def without_shared_profile_option(parameters):
        return {
            "arguments": parameters["arguments"],
            "options": [
                option for option in parameters["options"]
                if option.get("name") != "--profile"
            ],
        }

    live_parameters = {
        path: without_shared_profile_option(parse_help_parameters(help_cache(path)))
        for path in sorted(live_paths)
    }

    for usage_json in _usage_json_paths(cli_name):
        if not usage_json.exists():
            pytest.skip(f"usage.json not found at {usage_json}")

        usage = json.loads(usage_json.read_text())
        usage_parameters = {
            path: without_shared_profile_option(parameters)
            for path, parameters in extract_usage_command_parameters(usage).items()
        }

        if command_filter:
            usage_parameters = {
                path: parameters for path, parameters in usage_parameters.items()
                if path == command_filter or path.startswith(f"{command_filter} ")
            }

        mismatches = {}
        for path, expected in live_parameters.items():
            actual = usage_parameters.get(path)
            if actual != expected:
                mismatches[path] = {"expected": expected, "actual": actual}

        assert not mismatches, (
            f"{usage_json} has stale command parameters for installed '{cli_name}'. "
            f"Mismatches: {json.dumps(mismatches, indent=2, sort_keys=True)}. "
            f"Fix: regenerate usage.json from live '{cli_name} --help' output."
        )
