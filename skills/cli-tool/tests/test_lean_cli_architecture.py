"""Lean CLI architecture checks.

The external Typer contract is the product surface. Internal models, helper
modules, dependencies, and browser subclasses are only allowed when they carry
their own weight.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import pytest


def _pkg_dir(cli_dir: Path, cli_name: str) -> Path:
    return cli_dir / f"{cli_name.replace('-', '_')}_cli"


def _iter_source_files(pkg_dir: Path):
    return (
        path
        for path in pkg_dir.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _dependency_name(spec: str) -> str:
    return re.split(r"[<>=!~ ;\[]", spec, maxsplit=1)[0].replace("_", "-").lower()


def _imports_module(tree: ast.AST, module_names: tuple[str, ...]) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if any(alias.name == name or alias.name.startswith(f"{name}.") for name in module_names):
                    return True
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if any(module == name or module.startswith(f"{name}.") for name in module_names):
                return True
    return False


def _is_docstring(node: ast.stmt) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def _has_typer_app(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Attribute) and func.attr == "Typer":
                return True
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call):
                    decorator_func = decorator.func
                    if isinstance(decorator_func, ast.Attribute) and decorator_func.attr == "command":
                        return True
    return False


def _is_command_credentials_assignment(node: ast.stmt) -> bool:
    if not isinstance(node, ast.Assign):
        return False
    return any(isinstance(target, ast.Name) and target.id == "COMMAND_CREDENTIALS" for target in node.targets)


def _is_future_import(node: ast.stmt) -> bool:
    return isinstance(node, ast.ImportFrom) and node.module == "__future__"


def _contains_call(node: ast.AST) -> bool:
    return any(isinstance(child, ast.Call) for child in ast.walk(node))


def _is_browser_automation_base(base: ast.expr) -> bool:
    if isinstance(base, ast.Name):
        return base.id == "BrowserAutomation"
    if isinstance(base, ast.Attribute):
        return base.attr == "BrowserAutomation"
    return False


def test_no_unused_direct_pydantic_dependency(cli_name, cli_dir, command_filter):
    """A CLI should not depend on pydantic unless its runtime code imports it."""
    if command_filter:
        pytest.skip("Skipping (command filter active)")

    pyproject = cli_dir / "pyproject.toml"
    if not pyproject.exists():
        pytest.skip("No pyproject.toml")

    dependencies = tomllib.loads(pyproject.read_text()).get("project", {}).get("dependencies", [])
    if "pydantic" not in {_dependency_name(spec) for spec in dependencies}:
        return

    pkg_dir = _pkg_dir(cli_dir, cli_name)
    uses_pydantic = any(
        _imports_module(ast.parse(path.read_text()), ("pydantic", "cli_tools_shared.models"))
        for path in _iter_source_files(pkg_dir)
    )
    if uses_pydantic:
        return

    pytest.fail(
        "pyproject.toml declares pydantic, but the CLI package does not import "
        "pydantic or cli_tools_shared.models.\n"
        "Fix: remove the direct pydantic dependency. Keep dependencies tied to "
        "runtime code that still exists."
    )


def test_command_credential_modules_are_metadata_only(cli_name, cli_dir, command_filter):
    """A command module that only exists for credentials must stay as metadata."""
    if command_filter:
        pytest.skip("Skipping (command filter active)")

    commands_dir = _pkg_dir(cli_dir, cli_name) / "commands"
    if not commands_dir.is_dir():
        return

    for path in sorted(commands_dir.glob("*.py")):
        if path.name == "__init__.py" or path.name.startswith("_"):
            continue
        tree = ast.parse(path.read_text())
        has_credentials = any(_is_command_credentials_assignment(node) for node in tree.body)
        if not has_credentials or _has_typer_app(tree):
            continue

        credentials_assignments = sum(1 for node in tree.body if _is_command_credentials_assignment(node))
        unexpected = [
            node
            for node in tree.body
            if not (_is_docstring(node) or _is_future_import(node) or _is_command_credentials_assignment(node))
        ]
        if credentials_assignments == 1 and not unexpected:
            continue

        pytest.fail(
            f"{path.relative_to(cli_dir)} has COMMAND_CREDENTIALS but no Typer app.\n"
            "Fix: keep metadata-only command modules to a module docstring plus "
            "one COMMAND_CREDENTIALS assignment, or move real command logic into "
            "the module and define a Typer app there."
        )


def test_package_init_has_no_runtime_work(cli_name, cli_dir, command_filter):
    """Package import must not run setup, warnings filters, or other side effects."""
    if command_filter:
        pytest.skip("Skipping (command filter active)")

    init_file = _pkg_dir(cli_dir, cli_name) / "__init__.py"
    if not init_file.exists():
        return

    tree = ast.parse(init_file.read_text())
    for node in tree.body:
        if _is_docstring(node) or isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and not _contains_call(node):
            continue
        pytest.fail(
            f"{init_file.relative_to(cli_dir)} performs runtime work at import time.\n"
            "Fix: keep package __init__.py to docstrings, imports, and static "
            "metadata assignments. Put executable setup in the command path."
        )


def test_browser_automation_subclasses_are_declarative(cli_name, cli_dir, command_filter):
    """Browser subclasses should declare shared hook constants, not reimplement auth."""
    if command_filter:
        pytest.skip("Skipping (command filter active)")

    browser_file = _pkg_dir(cli_dir, cli_name) / "browser.py"
    if not browser_file.exists():
        return

    tree = ast.parse(browser_file.read_text())
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(_is_browser_automation_base(base) for base in node.bases):
            continue

        unexpected = [
            stmt
            for stmt in node.body
            if not (_is_docstring(stmt) or isinstance(stmt, (ast.Assign, ast.AnnAssign)))
        ]
        if unexpected:
            pytest.fail(
                f"{browser_file.relative_to(cli_dir)} class {node.name} defines "
                "methods or nested code on top of BrowserAutomation.\n"
                "Fix: leave auth lifecycle behavior in cli_tools_shared and keep "
                "the subclass to declarative hook constants only."
            )
