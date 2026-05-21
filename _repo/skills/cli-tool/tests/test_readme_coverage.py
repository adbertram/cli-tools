"""README command documentation coverage tests (Section 11)."""

import pytest

from cli_test_utils import parse_help_commands


def test_readme_documents_all_command_groups(cli_name, cli_dir, help_cache, command_filter):
    """Assertion 48: README documents each command group."""
    if command_filter:
        pytest.skip("Skipping general documentation tests (command filter active)")

    readme_path = cli_dir / "README.md"

    if not readme_path.exists():
        pytest.skip("README.md not found")

    readme_content = readme_path.read_text().lower()

    # Get all command groups
    main_help = help_cache("")
    subgroups = parse_help_commands(main_help)

    missing = []
    for group in subgroups:
        if group.lower() not in readme_content:
            missing.append(group)

    if missing:
        pytest.fail(
            f"README missing documentation for command groups: {missing}. "
            f"Fix: Add examples for '{cli_name} {missing[0]}' to README.md"
        )
