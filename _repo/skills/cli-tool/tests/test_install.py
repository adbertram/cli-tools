"""Installation and packaging tests (uv tool install)."""

import json
import os
import pytest
import re
import subprocess
import tomllib
from pathlib import Path

from cli_test_utils import run_cli_command, get_uv_tool_venv_dir


def _find_cli_tools_root(cli_dir: Path) -> Path | None:
    """Find the cli-tools repo root from a CLI directory."""
    for candidate in [cli_dir, *cli_dir.parents]:
        if (candidate / "_repo" / "cli-tools-shared").is_dir():
            return candidate
    return None


def test_uv_tool_registered(cli_name, cli_dir, command_filter):
    """CLI must be registered as a uv tool.

    uv tool install creates an isolated venv and symlink automatically.
    This replaces the old .venv directory check.
    """
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    result = subprocess.run(
        ["uv", "tool", "list"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, "Failed to run 'uv tool list'"

    # uv tool list output format: "package-name v0.1.0" per line
    assert cli_name in result.stdout or f"{cli_name}-cli" in result.stdout, (
        f"CLI '{cli_name}' not registered as a uv tool. "
        f"Fix: uv tool install -e {cli_dir} --force --refresh"
    )


def test_cli_installed_in_editable_mode(cli_name, cli_dir, command_filter):
    """Development mode: CLI should be installed as editable.

    This allows editing source code without reinstalling.
    Uses uv pip show within the uv tool's venv.
    """
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    uv_venv = get_uv_tool_venv_dir(cli_dir, cli_name)
    if uv_venv is None:
        pytest.skip(f"{cli_name} uv tool venv not found")

    # Package name variations to try
    package_names = [
        f"{cli_name}-cli",
        f"{cli_name}_cli".replace("-", "_"),
        cli_name.replace("-", "_"),
    ]

    result = None
    env = {"VIRTUAL_ENV": str(uv_venv)}

    for pkg_name in package_names:
        result = subprocess.run(
            ["uv", "pip", "show", pkg_name],
            capture_output=True, text=True,
            env={**subprocess.os.environ, **env}
        )
        if result.returncode == 0:
            break

    assert result is not None and result.returncode == 0, (
        f"CLI '{cli_name}' not found in uv tool venv. "
        f"Fix: uv tool install -e {cli_dir} --force --refresh"
    )
    assert "Editable project location:" in result.stdout, (
        f"CLI '{cli_name}' is installed but NOT as an editable install (-e). "
        f"Fix: uv tool install -e {cli_dir} --force --refresh"
    )


def test_cli_tools_shared_installed(cli_name, cli_dir, help_cache, test_config, command_filter):
    """All CLIs: cli-tools-shared package is installed in the tool's uv venv."""
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    uv_venv = get_uv_tool_venv_dir(cli_dir, cli_name)
    if uv_venv is None:
        pytest.skip(f"{cli_name} uv tool venv not found")

    env = {**subprocess.os.environ, "VIRTUAL_ENV": str(uv_venv)}
    result = subprocess.run(
        ["uv", "pip", "show", "cli-tools-shared"],
        capture_output=True, text=True,
        env=env
    )
    assert result.returncode == 0, (
        f"cli-tools-shared not installed in {cli_name}'s uv tool venv. "
        f"Fix: uv tool install -e {cli_dir} --force --refresh"
    )


def test_cli_tools_shared_uses_local_editable_repo_when_available(cli_name, cli_dir, command_filter):
    """Local development must execute against the live cli-tools-shared repo.

    CLI repos keep cli-tools-shared as a repo-local uv source so a fresh clone
    uses its sibling shared package instead of a stale external snapshot.
    """
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    pyproject = cli_dir / "pyproject.toml"
    if not pyproject.exists():
        pytest.skip(f"{cli_name} has no pyproject.toml")

    with open(pyproject, "rb") as f:
        data = tomllib.load(f)

    deps = data.get("project", {}).get("dependencies", [])
    if not any("cli-tools-shared" in dep for dep in deps):
        pytest.skip(f"{cli_name} does not depend on cli-tools-shared")

    cli_tools_root = _find_cli_tools_root(cli_dir)
    if cli_tools_root is None:
        pytest.skip(f"Could not locate cli-tools root for {cli_dir}")

    local_shared_dir = cli_tools_root / "_repo" / "cli-tools-shared"
    if not local_shared_dir.is_dir():
        pytest.skip(f"Local cli-tools-shared repo not found at {local_shared_dir}")

    uv_venv = get_uv_tool_venv_dir(cli_dir, cli_name)
    if uv_venv is None:
        pytest.skip(f"{cli_name} uv tool venv not found")

    env = {**subprocess.os.environ, "VIRTUAL_ENV": str(uv_venv)}
    result = subprocess.run(
        ["uv", "pip", "show", "cli-tools-shared"],
        capture_output=True, text=True,
        env=env
    )
    assert result.returncode == 0, (
        f"cli-tools-shared not installed in {cli_name}'s uv tool venv. "
        f"Fix: uv tool install -e {cli_dir} --force --refresh"
    )
    assert f"Editable project location: {local_shared_dir}" in result.stdout, (
        f"{cli_name} is not executing against the local cli-tools-shared repo.\n"
        f"Expected Editable project location: {local_shared_dir}\n"
        f"Actual uv pip show output:\n{result.stdout}\n"
        f"Fix: reinstall with install-cli-tool.sh so cli-tools-shared overlays "
        f"the local repo as an editable dependency."
    )


def test_cli_tools_shared_uses_repo_local_source(cli_name, cli_dir, command_filter):
    """cli-tools-shared dependency must resolve to the sibling repo package."""
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    pyproject = cli_dir / "pyproject.toml"
    if not pyproject.exists():
        pytest.skip(f"{cli_name} has no pyproject.toml")

    with open(pyproject, "rb") as f:
        data = tomllib.load(f)

    deps = data.get("project", {}).get("dependencies", [])

    # Find the cli-tools-shared dependency
    cts_dep = None
    for dep in deps:
        normalized = dep.lower().replace("-", "_").split("@")[0].split("[")[0]
        normalized = re.split(r"[>=<~!;]", normalized)[0].strip()
        if normalized == "cli_tools_shared":
            cts_dep = dep
            break

    if cts_dep is None:
        pytest.skip(f"{cli_name} does not depend on cli-tools-shared")

    assert cts_dep.strip() == "cli-tools-shared", (
        f"{cli_name}/pyproject.toml declares cli-tools-shared as '{cts_dep.strip()}'. "
        'Fix: use "cli-tools-shared" in dependencies.'
    )
    cli_tools_root = _find_cli_tools_root(cli_dir)
    if cli_tools_root is None:
        pytest.skip(f"Could not locate cli-tools root for {cli_dir}")

    expected_relative_path = os.path.relpath(
        cli_tools_root / "_repo" / "cli-tools-shared",
        cli_dir,
    )
    source = data.get("tool", {}).get("uv", {}).get("sources", {}).get("cli-tools-shared")
    assert source == {"path": expected_relative_path, "editable": True}, (
        f"{cli_name}/pyproject.toml must map cli-tools-shared to the local sibling package. "
        f"Fix: add [tool.uv.sources] cli-tools-shared = {{ path = {expected_relative_path!r}, editable = true }}."
    )


def test_dependencies_installed(cli_name, cli_dir, command_filter):
    """All pyproject.toml dependencies must be installed in the CLI's uv tool venv.

    Parses the dependencies list from pyproject.toml, normalizes package names,
    and verifies each is installed via uv pip list.
    """
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    pyproject = cli_dir / "pyproject.toml"
    if not pyproject.exists():
        pytest.skip(f"{cli_name} has no pyproject.toml")

    with open(pyproject, "rb") as f:
        data = tomllib.load(f)

    deps = data.get("project", {}).get("dependencies", [])
    if not deps:
        pytest.skip(f"{cli_name} has no declared dependencies")

    uv_venv = get_uv_tool_venv_dir(cli_dir, cli_name)
    if uv_venv is None:
        pytest.skip(f"{cli_name} uv tool venv not found")

    env = {**subprocess.os.environ, "VIRTUAL_ENV": str(uv_venv)}
    result = subprocess.run(
        ["uv", "pip", "list", "--format=json"],
        capture_output=True, text=True,
        env=env
    )
    if result.returncode != 0:
        pytest.skip("Could not list installed packages")

    installed = {
        pkg["name"].lower().replace("-", "_")
        for pkg in json.loads(result.stdout)
    }

    def normalize_dep(dep_str):
        name = dep_str.split("@")[0].strip()
        name = re.split(r"[\[>=<~!;]", name)[0].strip()
        return name.lower().replace("-", "_")

    missing = []
    for dep in deps:
        pkg_name = normalize_dep(dep)
        if not pkg_name:
            continue
        if pkg_name not in installed:
            missing.append(f"{pkg_name} (from: {dep.strip()})")

    assert not missing, (
        f"{cli_name} has {len(missing)} dependencies declared in pyproject.toml "
        f"but not installed in uv tool venv:\n"
        + "\n".join(f"  - {m}" for m in missing)
        + f"\nFix: uv tool install -e {cli_dir} --force --refresh"
    )


def test_launcher_shebang_points_to_uv_tool_python(cli_name, cli_dir, command_filter):
    """The ~/.local/bin/<cli_name> launcher must have a shebang pointing
    to the CLI's uv tool venv python (e.g.
    ``#!~/.local/share/uv/tools/<pkg>/bin/python3``).

    If the shebang points anywhere else (system python, homebrew python)
    the CLI will start with the wrong interpreter and fail at import time
    because its declared dependencies live in the uv tool venv, not the
    other interpreter's site-packages.

    This is also the one-and-only acceptable interpreter for
    manual/ad-hoc import testing of the CLI's modules:

        /Users/<user>/.local/share/uv/tools/<pkg>/bin/python3 -c "import <pkg_module>.main"

    Using any other python will produce misleading ImportError traces
    that have nothing to do with the CLI itself.
    """
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    launcher = Path.home() / ".local" / "bin" / cli_name
    if not launcher.exists():
        pytest.skip(f"{cli_name} launcher not found at {launcher}")

    uv_venv = get_uv_tool_venv_dir(cli_dir, cli_name)
    if uv_venv is None:
        pytest.skip(f"{cli_name} uv tool venv not found")

    expected_python = uv_venv / "bin" / "python"
    expected_python3 = uv_venv / "bin" / "python3"

    with open(launcher, "rb") as f:
        first_line = f.readline().decode("utf-8", errors="replace").rstrip("\n\r")

    assert first_line.startswith("#!"), (
        f"{cli_name} launcher at {launcher} has no shebang. "
        f"First line: {first_line!r}. "
        f"Fix: uv tool install -e {cli_dir} --force --refresh"
    )

    actual_interpreter = first_line[2:].split()[0] if len(first_line) > 2 else ""

    valid = actual_interpreter in (str(expected_python), str(expected_python3))
    assert valid, (
        f"{cli_name} launcher shebang points to the WRONG interpreter.\n"
        f"  Launcher:    {launcher}\n"
        f"  Shebang:     {first_line}\n"
        f"  Expected:    #!{expected_python} (or {expected_python3})\n"
        f"\n"
        f"This means the CLI will start with an interpreter that does NOT have "
        f"its declared dependencies installed, and will fail at import time.\n"
        f"\n"
        f"Fix: uv tool install -e {cli_dir} --force --refresh\n"
        f"\n"
        f"Reminder: when running manual import tests of this CLI, you MUST use "
        f"its own interpreter:\n"
        f"    {expected_python3} -c 'import {cli_name.replace('-', '_')}_cli.main'"
    )


def test_package_imports_cleanly(cli_name, cli_dir, command_filter):
    """The CLI package must import without errors in its uv tool venv.

    Attempts to import every .py module in the CLI package using the
    uv tool venv's Python.
    """
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    pkg_name = cli_name.replace("-", "_") + "_cli"
    pkg_dir = cli_dir / pkg_name
    if not pkg_dir.exists():
        pytest.skip(f"{cli_name} has no {pkg_name}/ package directory")

    uv_venv = get_uv_tool_venv_dir(cli_dir, cli_name)
    if uv_venv is None:
        pytest.skip(f"{cli_name} uv tool venv not found")

    venv_python = uv_venv / "bin" / "python"
    if not venv_python.exists():
        pytest.skip(f"{cli_name} uv tool venv has no python")

    modules = []
    for py_file in sorted(pkg_dir.rglob("*.py")):
        if "__pycache__" in str(py_file):
            continue
        rel = py_file.relative_to(cli_dir)
        mod_path = str(rel).replace("/", ".").removesuffix(".py")
        if mod_path.endswith(".__init__"):
            mod_path = mod_path.removesuffix(".__init__")
        modules.append(mod_path)

    if not modules:
        pytest.skip(f"{cli_name} has no Python modules")

    failures = []
    for mod in modules:
        result = subprocess.run(
            [str(venv_python), "-c", f"import {mod}"],
            capture_output=True, text=True,
            cwd=str(cli_dir),
            timeout=15
        )
        if result.returncode != 0:
            error = result.stderr.strip().split("\n")[-1]
            failures.append((mod, error))

    assert not failures, (
        f"{cli_name} has {len(failures)} modules that fail to import:\n"
        + "\n".join(f"  - {mod}: {err}" for mod, err in failures)
        + f"\nFix: uv tool install -e {cli_dir} --force --refresh"
    )


def test_underlying_cli_command_works(cli_name, cli_dir, command_filter):
    """Wrapper/browser CLIs: the underlying CLI_COMMAND must actually run.

    Reads CLI_COMMAND from .env or .env.example, resolves it via PATH,
    and runs it with --help to verify it's not a broken shim (stale pip
    script, missing module, etc.).
    """
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    # Find CLI_COMMAND from .env or .env.example
    cli_command = None
    for env_file in [cli_dir / ".env", cli_dir / ".env.example"]:
        if not env_file.exists():
            continue
        for line in env_file.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            if key.strip() == "CLI_COMMAND":
                cli_command = value.strip().strip("'\"")
                break
        if cli_command:
            break

    if not cli_command:
        pytest.skip(f"{cli_name} has no CLI_COMMAND (not a wrapper/browser CLI)")

    import shutil
    exe = shutil.which(cli_command)
    assert exe is not None, (
        f"{cli_name} declares CLI_COMMAND={cli_command} but '{cli_command}' "
        f"is not found in PATH. Fix: Install '{cli_command}' or update "
        f"CLI_COMMAND in {cli_name}/.env.example to the correct binary name."
    )

    result = subprocess.run(
        [exe, "--help"],
        capture_output=True, text=True, timeout=10
    )

    # Check for Python import errors (broken shim scripts)
    combined = result.stdout + result.stderr
    has_import_error = (
        "ModuleNotFoundError" in combined
        or "ImportError" in combined
        or "No module named" in combined
    )
    assert not has_import_error, (
        f"{cli_name} declares CLI_COMMAND={cli_command} but running "
        f"'{cli_command} --help' fails with an import error:\n"
        f"{combined.strip()[:500]}\n\n"
        f"Fix: The '{cli_command}' binary at {exe} is broken. Either "
        f"reinstall it or update CLI_COMMAND to the correct binary name."
    )

    assert result.returncode == 0, (
        f"{cli_name} declares CLI_COMMAND={cli_command} but running "
        f"'{cli_command} --help' exits with code {result.returncode}:\n"
        f"{combined.strip()[:500]}\n\n"
        f"Fix: Verify '{cli_command}' is properly installed and working."
    )


def test_env_example_has_base_url(cli_name, cli_dir, test_config, command_filter):
    """Assertion 8: .env.example must define BASE_URL when credential type requires it."""
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    no_auth_clis = test_config["exclusions"].get("no_auth_clis", [])
    if cli_name in no_auth_clis:
        pytest.skip(f"{cli_name} does not require authentication")

    env_example = cli_dir / ".env.example"
    if not env_example.exists():
        pytest.skip(f"{cli_name} has no .env.example file")

    uv_venv = get_uv_tool_venv_dir(cli_dir, cli_name)
    if uv_venv is None:
        pytest.skip(f"{cli_name} uv tool venv not found")

    venv_python = uv_venv / "bin" / "python"
    if venv_python.exists():
        result = subprocess.run(
            [str(venv_python), "-c",
             "from cli_tools_shared.credentials import CredentialType; "
             "import importlib, sys; "
             f"pkg = '{cli_name}'.replace('-', '_') + '_cli'; "
             "sys.path.insert(0, '.'); "
             "mod = importlib.import_module(pkg + '.config'); "
             "cfg = [c for c in vars(mod).values() "
             "       if isinstance(c, type) and hasattr(c, 'CREDENTIAL_TYPE')]; "
             "ct = cfg[0] if cfg else None; "
             "types = (ct.CREDENTIAL_TYPES if ct and getattr(ct, 'CREDENTIAL_TYPES', None) "
             "         else [ct.CREDENTIAL_TYPE] if ct and getattr(ct, 'CREDENTIAL_TYPE', None) "
             "         else []); "
             "fields = [f for t in types for f in t.all_fields]; "
             "print('BASE_URL' in fields)"],
            capture_output=True, text=True, cwd=str(cli_dir)
        )
        if result.returncode != 0:
            pytest.skip(f"{cli_name} does not use standard cli_tools_shared credentials")
        if result.stdout.strip() == "False":
            pytest.skip(f"{cli_name}'s credential type does not include BASE_URL")

    content = env_example.read_text()

    assert "BASE_URL=" in content, (
        f"{cli_name}/.env.example missing BASE_URL field. "
        f"Fix: Add 'BASE_URL=https://api.example.com/v1' to .env.example."
    )

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("BASE_URL="):
            value = stripped.split("=", 1)[1].strip().strip("'\"")
            assert value, (
                f"{cli_name}/.env.example has empty BASE_URL. "
                f"Fix: Set BASE_URL to the service's default API URL."
            )
            break
