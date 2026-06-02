"""Single-module ``models/`` and ``commands/`` directories must be flattened.

A directory that contains only ``__init__.py`` plus exactly one ``.py`` module
serves no organisational purpose — it just adds an extra level of indirection
and an empty ``__init__.py``. Flatten it into a top-level module instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FLATTEN_TARGETS = ("models", "commands")


def _single_module_directory(directory: Path) -> Path | None:
    if not directory.is_dir():
        return None
    py_files = [p for p in directory.glob("*.py") if p.name != "__init__.py"]
    if len(py_files) == 1:
        return py_files[0]
    return None


@pytest.mark.parametrize("sub_dir", FLATTEN_TARGETS)
def test_no_single_module_directory(cli_name, cli_dir, command_filter, sub_dir):
    """A single-module subdirectory must be flattened into a top-level module."""
    if command_filter:
        pytest.skip("Skipping (command filter active)")
    pkg_dir = cli_dir / f"{cli_name.replace('-', '_')}_cli"
    target = pkg_dir / sub_dir
    only_module = _single_module_directory(target)
    if only_module is None:
        return
    pytest.fail(
        f"{target.relative_to(cli_dir)}/ contains only one module ({only_module.name}).\n"
        f"Fix: move the contents of {only_module.relative_to(cli_dir)} into "
        f"{pkg_dir.name}/{sub_dir}.py and delete the {sub_dir}/ directory.\n"
        f"Update any '{pkg_dir.name}.{sub_dir}.{only_module.stem}' imports to "
        f"'{pkg_dir.name}.{sub_dir}'."
    )
