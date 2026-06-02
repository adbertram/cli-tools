"""Documentation validation tests (Section 2)."""

import pytest
from pathlib import Path


def test_tool_in_cli_tools_md(cli_name, command_filter):
    """Tool must be listed in the repo-owned CLI tools inventory."""
    if command_filter:
        pytest.skip("Skipping general documentation tests (command filter active)")

    cli_tools_md = Path(__file__).resolve().parents[3] / "docs" / "cli_tools.md"
    assert cli_tools_md.exists(), f"{cli_tools_md} not found"

    content = cli_tools_md.read_text()

    # Check for table entry format: | `cli-name` | Description |
    table_entry_pattern = f"| `{cli_name}` |"
    assert table_entry_pattern in content, (
        f"CLI tool '{cli_name}' not in {cli_tools_md}. "
        f"Fix: Add table row '| `{cli_name}` | Description here |' to {cli_tools_md}"
    )


def test_readme_exists(cli_dir, command_filter):
    """Assertion 7: README.md exists."""
    if command_filter:
        pytest.skip("Skipping general documentation tests (command filter active)")

    readme = cli_dir / "README.md"
    assert readme.exists(), (
        f"README.md not found in {cli_dir}. "
        f"Fix: Create README.md documenting CLI usage and commands."
    )


def test_readme_has_commands_section(cli_dir, cli_name, command_filter):
    """Assertion 8: README documents commands."""
    if command_filter:
        pytest.skip("Skipping general documentation tests (command filter active)")

    readme = cli_dir / "README.md"
    if not readme.exists():
        pytest.skip("README.md not found")

    content = readme.read_text()
    content_lower = content.lower()

    # Check for various patterns that indicate command documentation
    has_commands_section = any([
        "## commands" in content_lower,
        "# commands" in content_lower,
        "## usage" in content_lower,
        "# usage" in content_lower,
    ])

    # Check for section headers containing "command" (e.g., "## Database Commands")
    has_command_subsections = "command" in content_lower and "##" in content

    # Check for CLI invocation examples in code blocks
    has_cli_examples = f"```\n{cli_name} " in content or f"```bash\n{cli_name} " in content

    assert has_commands_section or has_command_subsections or has_cli_examples, (
        f"README.md missing command documentation. "
        f"Fix: Add a '## Commands' section or document commands with examples. "
        f"Pattern: Section headers with 'Command' or code blocks showing '{cli_name} <command>'."
    )
