"""Forbid pure re-export modules (filters.py, output.py) in CLI tools.

These files historically existed only to satisfy template-compliance checks. They
have no internal consumers — every caller can (and should) import directly from
``cli_tools_shared``. Carrying them adds line count, indirection, and stale
template-drift bugs without any value.

A file is "pure re-export" when every top-level statement is either a docstring,
an ``__all__`` assignment, or an import from ``cli_tools_shared``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

FORBIDDEN_REEXPORT_FILES = ["filters.py", "output.py"]
SHARED_LIB_PREFIXES = ("cli_tools_shared",)


def _is_pure_reexport(path: Path) -> bool:
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, ast.Assign):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "__all__":
                continue
            return False
        if isinstance(node, ast.ImportFrom):
            if node.module and any(node.module.startswith(prefix) for prefix in SHARED_LIB_PREFIXES):
                continue
            return False
        return False
    return True


@pytest.mark.parametrize("filename", FORBIDDEN_REEXPORT_FILES)
def test_no_pure_reexport_module(cli_name, cli_dir, command_filter, filename):
    """Pure re-export modules add zero value — delete the file and import from cli_tools_shared directly."""
    if command_filter:
        pytest.skip("Skipping (command filter active)")
    path = cli_dir / f"{cli_name.replace('-', '_')}_cli" / filename
    if not path.exists():
        return
    if _is_pure_reexport(path):
        pytest.fail(
            f"{path.relative_to(cli_dir)} only re-exports from cli_tools_shared.\n"
            f"Fix: delete {filename}. Any module that needs these symbols should import directly:\n"
            f"  from cli_tools_shared.filters import apply_filters, validate_filters, ...\n"
            f"  from cli_tools_shared.output import command, print_json, print_table, ..."
        )
