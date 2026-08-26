"""Every third-party module cloudflare_cli imports must be declared in pyproject.toml.

Regression guard for the 2026-08-25 R2 migration incident: ``commands/r2.py``
imported ``boto3``/``botocore`` at module import time and ``main.py`` imported
that module unconditionally, but ``pyproject.toml`` never declared boto3. The
package only worked because boto3 had been installed into the uv tool venv out
of band. ``uv tool install -e ... --force --refresh`` rebuilds that venv from
this manifest, so the next ``install-cli-tool.sh --force-refresh cloudflare``
dropped boto3, botocore, jmespath, python-dateutil, s3transfer and six, and
every ``cloudflare`` invocation died with ``ModuleNotFoundError: No module
named 'boto3'`` before argument parsing.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

CLI_DIR = Path(__file__).resolve().parents[1]
PACKAGE_DIR = CLI_DIR / "cloudflare_cli"
PYPROJECT = CLI_DIR / "pyproject.toml"

# Top-level import name -> distribution name, for the cases where they differ.
IMPORT_TO_DISTRIBUTION = {
    "botocore": "boto3",
    "browser_harness": "cli-tools-shared",
    "cli_tools_shared": "cli-tools-shared",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "PIL": "pillow",
    "yaml": "pyyaml",
}


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _declared_distributions() -> set[str]:
    data = tomllib.loads(PYPROJECT.read_text())
    requirements = data["project"]["dependencies"]
    return {_normalize(re.split(r"[<>=!~\[; ]", req)[0]) for req in requirements}


def _imported_top_level_modules() -> dict[str, Path]:
    """Map each absolute top-level import in cloudflare_cli to a source file."""
    found: dict[str, Path] = {}
    for source in sorted(PACKAGE_DIR.rglob("*.py")):
        if "__pycache__" in source.parts:
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level or not node.module:
                    continue  # relative import inside cloudflare_cli
                modules = [node.module.split(".")[0]]
            else:
                continue
            for module in modules:
                found.setdefault(module, source)
    return found


def test_third_party_imports_are_declared_dependencies():
    declared = _declared_distributions()
    undeclared: list[str] = []

    for module, source in sorted(_imported_top_level_modules().items()):
        if module in sys.stdlib_module_names or module == "cloudflare_cli":
            continue
        distribution = _normalize(IMPORT_TO_DISTRIBUTION.get(module, module))
        if distribution not in declared:
            undeclared.append(
                f"{module} (imported by {source.relative_to(CLI_DIR)}) "
                f"-> distribution {distribution!r}"
            )

    assert not undeclared, (
        "cloudflare_cli imports modules that pyproject.toml does not declare:\n  "
        + "\n  ".join(undeclared)
        + "\nAdd them to [project].dependencies. An undeclared runtime import "
        "survives only until the uv tool venv is rebuilt, then every command "
        "fails with ModuleNotFoundError."
    )


def test_boto3_is_declared_for_r2_commands():
    """Pin the specific regression: r2.py's boto3 import must stay declared."""
    assert "import boto3" in (PACKAGE_DIR / "commands" / "r2.py").read_text()
    assert "boto3" in _declared_distributions()
