"""Validate the canonical schema of `<cli> auth status` stdout."""

from __future__ import annotations

import pytest

from auth_status_schema import parse_and_validate_stdout
from cli_test_utils import run_cli_command


def _has_subcommand(help_text: str, name: str) -> bool:
    return any(name in line.split() for line in help_text.splitlines() if name in line)


def test_auth_status_schema(cli_executable, cli_name, help_cache, command_filter):
    """Auth status stdout must parse as a single JSON doc matching the canonical schema."""
    if command_filter:
        pytest.skip("Skipping (command filter active)")
    root_help = help_cache("")
    if not _has_subcommand(root_help, "auth"):
        pytest.skip(f"{cli_name} has no auth subcommand")
    auth_help = help_cache("auth")
    if not _has_subcommand(auth_help, "status"):
        pytest.skip(f"{cli_name} has no 'auth status' subcommand")

    result = run_cli_command(cli_executable, ["auth", "status"])

    assert result.returncode == 0, f"'{cli_name} auth status' exited {result.returncode}: {result.stderr[:300]}"

    _, errors = parse_and_validate_stdout(result.stdout)
    if errors and errors[0].startswith("stdout is not a single valid JSON document:"):
        pytest.fail(
            f"'{cli_name} auth status' {errors[0]} "
            f"(stream-separation violation).\nstdout: {result.stdout[:300]}"
        )

    assert not errors, "auth status schema violations:\n  - " + "\n  - ".join(errors)
