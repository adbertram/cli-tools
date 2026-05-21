"""Validate that all CLI tools declare cli-tools-shared as a dependency.

Every CLI tool that imports cli_tools_shared must list it in pyproject.toml
dependencies. Without this, bundled n8n node packages fail at runtime with
ModuleNotFoundError.
"""
import subprocess
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[3]  # cli-tools/
SKIP_DIRS = {
    "_repo",
    ".git",
    "node_modules",
    "__pycache__",
}


def _find_cli_tools():
    """Find all CLI tool directories that have a pyproject.toml."""
    tools = []
    for d in sorted(TOOLS_DIR.iterdir()):
        if not d.is_dir() or d.name in SKIP_DIRS or d.name.startswith("."):
            continue
        if (d / "pyproject.toml").exists():
            tools.append(d)
    return tools


def _imports_cli_tools_shared(tool_dir: Path) -> bool:
    """Check if any .py file in the tool imports cli_tools_shared."""
    result = subprocess.run(
        ["grep", "-rq", "cli_tools_shared", "--include=*.py",
         "--exclude-dir=.venv", "--exclude-dir=__pycache__",
         "--exclude-dir=node_modules", str(tool_dir)],
        capture_output=True,
    )
    return result.returncode == 0


def _has_dependency(tool_dir: Path) -> bool:
    """Check if pyproject.toml lists cli-tools-shared as a dependency."""
    content = (tool_dir / "pyproject.toml").read_text()
    return "cli-tools-shared" in content or "cli_tools_shared" in content


@pytest.fixture(params=_find_cli_tools(), ids=lambda d: d.name)
def cli_tool(request):
    return request.param


def test_cli_tools_shared_dependency(cli_tool):
    """Every CLI tool that imports cli_tools_shared must declare it in pyproject.toml."""
    if not _imports_cli_tools_shared(cli_tool):
        pytest.skip(f"{cli_tool.name} does not import cli_tools_shared")

    assert _has_dependency(cli_tool), (
        f"{cli_tool.name}/pyproject.toml is missing cli-tools-shared dependency. "
        'Add "cli-tools-shared" to dependencies and map it to ../_repo/cli-tools-shared '
        "under [tool.uv.sources]."
    )
