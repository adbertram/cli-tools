"""Basic setup and availability tests (Section 1)."""

import pytest
import subprocess
from pathlib import Path

from cli_test_utils import run_cli_command


def test_tool_directory_exists(cli_dir, command_filter):
    """Assertion 1: Tool directory exists."""
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")
    assert cli_dir.exists(), (
        f"CLI tool directory not found at {cli_dir}. "
        f"Verify tool is installed in cli-tools repository."
    )


def test_cli_command_available_in_path(cli_name, cli_dir, command_filter):
    """Assertion 2: CLI command is available in PATH.

    This test verifies the CLI can be run by name from any shell without
    activating a virtual environment. This is required for agent harnesses and
    other automation to use the CLI.

    The CLI should be accessible via symlink in ~/.local/bin or similar.
    """
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    import os

    # First check if CLI exists in ~/.local/bin (prerequisite)
    cli_executable = Path.home() / ".local" / "bin" / cli_name
    # On Windows, uv installs executables with .exe extension
    if not cli_executable.exists():
        cli_executable = cli_executable.with_suffix(".exe")
    assert cli_executable.exists(), (
        f"CLI executable '{cli_name}' not found at {cli_executable}. "
        f"Fix: uv tool install -e {cli_dir} --force --refresh"
    )

    # Create a clean environment without any venv paths
    # This simulates what an agent harness or a fresh terminal would see
    clean_env = os.environ.copy()

    # Remove any venv-related paths from PATH
    path_parts = clean_env.get("PATH", "").split(":")
    clean_path = ":".join(
        p for p in path_parts
        if "/venv/" not in p and "/.venv/" not in p
    )
    clean_env["PATH"] = clean_path

    # Remove VIRTUAL_ENV if set
    clean_env.pop("VIRTUAL_ENV", None)

    # Find bash executable (handles both Unix /bin/bash and Windows Git Bash)
    import shutil
    bash_path = shutil.which("bash")
    if not bash_path:
        bash_path = "/bin/bash"

    # Check if CLI is accessible in clean PATH
    result = subprocess.run(
        [bash_path, "-c", f"command -v {cli_name}"],
        capture_output=True,
        text=True,
        timeout=10,
        env=clean_env
    )
    assert result.returncode == 0, (
        f"CLI '{cli_name}' not found in PATH. "
        f"Fix: ln -sf {cli_executable} ~/.local/bin/{cli_name}"
    )

    # Verify the CLI actually runs from PATH
    result = subprocess.run(
        [bash_path, "-c", f"{cli_name} --help"],
        capture_output=True,
        text=True,
        timeout=30,
        env=clean_env
    )
    assert result.returncode == 0, (
        f"CLI '{cli_name}' found in PATH but failed to run (exit code {result.returncode}). "
        f"stderr: {result.stderr[:200] if result.stderr else 'none'}"
    )


def test_cli_world_invocable(cli_name, cli_dir, command_filter):
    """Assertion 2b: CLI is invocable via PATH symlink.

    Verifies a symlink exists in ~/.local/bin pointing to the CLI's venv binary.
    """
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    import os

    cli_binary = Path.home() / ".local" / "bin" / cli_name

    # Check executable exists in ~/.local/bin (symlink on Unix, .exe on Windows)
    user_symlink = Path.home() / ".local" / "bin" / cli_name
    user_exe = user_symlink.with_suffix(".exe")
    assert user_symlink.exists() or user_symlink.is_symlink() or user_exe.exists(), (
        f"No symlink found for {cli_name} in ~/.local/bin. "
        f"Fix: uv tool install -e {cli_dir} --force --refresh"
    )

    # Verify the symlink points to the right place (Unix only)
    if user_symlink.is_symlink():
        target = os.readlink(str(user_symlink))
        assert cli_name in target, (
            f"{user_symlink} symlink points to unexpected target: {target}"
        )


def test_help_flag_works(cli_executable, cli_name, command_filter):
    """Assertion 3: --help flag works."""
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")
    result = run_cli_command(cli_executable, ["--help"])
    assert result.returncode == 0, (
        f"'{cli_name} --help' failed with exit code {result.returncode}. "
        f"Fix: Check CLI installation and Typer configuration."
    )
    assert len(result.stdout) > 0, "Help output is empty"


def test_version_flag_works(cli_executable, cli_name, command_filter):
    """Assertion 4: --version flag works."""
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")
    result = run_cli_command(cli_executable, ["--version"])
    assert result.returncode == 0, (
        f"'{cli_name} --version' failed with exit code {result.returncode}. "
        f"Fix: Add --version option to CLI or check Typer version configuration."
    )


def test_no_args_shows_help(cli_executable, cli_name, command_filter):
    """Assertion 5: Running CLI with no args shows help."""
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")
    result = run_cli_command(cli_executable, [])
    # Typer shows help on no args (exit code 0 or 2)
    assert result.returncode in [0, 2], (
        f"'{cli_name}' with no args failed unexpectedly (exit code {result.returncode})"
    )
    assert "Usage:" in result.stdout or "Commands:" in result.stdout, (
        "No args should display help text with 'Usage:' or 'Commands:'"
    )


def test_pyproject_includes_cli_tools_shared(cli_name, cli_dir, command_filter):
    """pyproject.toml must declare cli-tools-shared as a dependency.

    Without this, bundled n8n node packages fail at runtime with
    ModuleNotFoundError because pip won't install the transitive dependency.
    """
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    pyproject = cli_dir / "pyproject.toml"
    if not pyproject.exists():
        pytest.skip(f"{cli_name} has no pyproject.toml")

    content = pyproject.read_text()

    # Check if code actually imports cli_tools_shared
    pkg_name = cli_name.replace("-", "_") + "_cli"
    pkg_dir = cli_dir / pkg_name
    if not pkg_dir.exists():
        pytest.skip(f"{cli_name} has no {pkg_name}/ package directory")

    imports_shared = False
    for py_file in pkg_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            text = py_file.read_text()
            if "from cli_tools_shared" in text or "import cli_tools_shared" in text:
                imports_shared = True
                break
        except (OSError, UnicodeDecodeError):
            continue

    if not imports_shared:
        pytest.skip(f"{cli_name} does not import cli_tools_shared")

    assert "cli-tools-shared" in content or "cli_tools_shared" in content, (
        f"{cli_name}/pyproject.toml is missing cli-tools-shared dependency. "
        'Fix: Add "cli-tools-shared" to dependencies and a '
        '[tool.uv.sources] cli-tools-shared path entry in pyproject.toml'
    )


def test_no_runtime_agent_dirs(cli_name, cli_dir, command_filter):
    """CLI tool directories must not contain runtime agent metadata."""
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    forbidden_dirs = [".agents", ".claude", ".codex", ".gemini"]
    forbidden_files = ["AGENTS.md", "CLAUDE.md", "GEMINI.md"]
    present_dirs = [name for name in forbidden_dirs if (cli_dir / name).exists()]
    present_files = [name for name in forbidden_files if (cli_dir / name).exists()]

    assert not present_dirs, (
        f"CLI tool '{cli_name}' contains forbidden runtime agent folders: {', '.join(present_dirs)}. "
        "Fix: remove runtime agent folders from the tool directory; service skills belong under "
        "cli-tools/_repo/skills/<tool>-cli."
    )
    assert not present_files, (
        f"CLI tool '{cli_name}' contains forbidden runtime agent files: {', '.join(present_files)}. "
        "Fix: remove runtime agent files from the tool directory; service skills belong under "
        "cli-tools/_repo/skills/<tool>-cli."
    )


def test_repo_gitignore_covers_cli_source_artifacts(cli_tools_root, command_filter):
    """Assertion 7a2: repo root .gitignore covers generated CLI source artifacts."""
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    gitignore = cli_tools_root / ".gitignore"
    assert gitignore.exists(), (
        f"Repo root .gitignore not found at {gitignore}. "
        "Fix: create a root .gitignore covering CLI source artifacts."
    )

    content = gitignore.read_text()
    required_patterns = {
        ".venv": ".venv/",
        "__pycache__": "__pycache__/",
        ".env": ".env",
        "scripts/*.log": "scripts/*.log",
    }
    missing = [
        desc for keyword, desc in required_patterns.items()
        if keyword not in content
    ]
    assert not missing, (
        "Repo root .gitignore is missing required CLI artifact patterns: "
        f"{', '.join(missing)}. "
        f"Fix: Add these to {gitignore}"
    )


def test_repo_root_is_only_source_visible_gitignore(cli_tools_root, command_filter):
    """Assertion 7a3: source-visible .gitignore policy is centralized at repo root."""
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    generated_dirs = {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "venv",
    }
    visible_gitignores = sorted(
        path.relative_to(cli_tools_root).as_posix()
        for path in cli_tools_root.rglob(".gitignore")
        if not any(
            part in generated_dirs
            for part in path.relative_to(cli_tools_root).parts[:-1]
        )
    )

    assert visible_gitignores == [".gitignore"], (
        "Only the repo root .gitignore should exist in source directories. "
        f"Found: {visible_gitignores}. "
        "Fix: remove child .gitignore files and put ignore rules in the repo root .gitignore."
    )


def _is_wrapper_tool(cli_dir, cli_name):
    """Return True if tool has cache_support=False (wrapper tool)."""
    pkg_name = cli_name.replace("-", "_") + "_cli"
    main_py = cli_dir / pkg_name / "main.py"
    if not main_py.exists():
        return False
    return "cache_support=False" in main_py.read_text()


def test_uses_create_app_pattern(cli_name, cli_dir, command_filter):
    """main.py must use create_app from cli_tools_shared."""
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    pkg_name = cli_name.replace("-", "_") + "_cli"
    main_py = cli_dir / pkg_name / "main.py"
    if not main_py.exists():
        pytest.skip(f"{cli_name} has no {pkg_name}/main.py")

    content = main_py.read_text()
    assert "create_app" in content and "from cli_tools_shared" in content, (
        f"{cli_name} main.py must use create_app from cli_tools_shared. "
        f"Fix: Replace manual typer.Typer() + callback with create_app()."
    )


def test_uses_run_app_pattern(cli_name, cli_dir, command_filter):
    """main.py must use run_app from cli_tools_shared."""
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    pkg_name = cli_name.replace("-", "_") + "_cli"
    main_py = cli_dir / pkg_name / "main.py"
    if not main_py.exists():
        pytest.skip(f"{cli_name} has no {pkg_name}/main.py")

    content = main_py.read_text()
    assert "run_app" in content, (
        f"{cli_name} main.py must use run_app from cli_tools_shared. "
        f"Fix: Replace manual try/except in main() with run_app(app)."
    )


def test_no_cache_flag_works(cli_executable, cli_name, cli_dir, command_filter):
    """--no-cache flag works for tools with cache support."""
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")
    if _is_wrapper_tool(cli_dir, cli_name):
        pytest.skip(f"{cli_name} is a wrapper tool (cache_support=False)")

    result = run_cli_command(cli_executable, ["--no-cache", "--help"])
    assert result.returncode == 0, (
        f"'{cli_name} --no-cache --help' failed (exit code {result.returncode}). "
        f"Fix: Ensure create_app is called with cache_support=True (default)."
    )


def test_cache_subcommand_exists(cli_executable, cli_name, cli_dir, command_filter):
    """cache subcommand exists for tools with cache support and get_config."""
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")
    if _is_wrapper_tool(cli_dir, cli_name):
        pytest.skip(f"{cli_name} is a wrapper tool (cache_support=False)")

    # cache subcommand requires get_config for storage_dir
    pkg_name = cli_name.replace("-", "_") + "_cli"
    main_py = cli_dir / pkg_name / "main.py"
    if main_py.exists() and "get_config" not in main_py.read_text():
        pytest.skip(f"{cli_name} has no get_config (cache subcommand not applicable)")

    result = run_cli_command(cli_executable, ["cache", "--help"])
    assert result.returncode == 0, (
        f"'{cli_name} cache --help' failed (exit code {result.returncode}). "
        f"Fix: Register cache commands with app.add_typer(create_cache_app(get_config), name='cache')."
    )


def test_has_cli_tool_skill(cli_name, command_filter):
    """CLI tool must have a corresponding repo-owned CLI tool skill.

    Every CLI tool needs a skill at cli-tools/_repo/skills/<name>-cli/ with at least
    SKILL.md and usage.json, created via the create-cli-tool-skill skill.
    Runtime-specific skill entries should symlink to that repo-owned folder.
    """
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    skill_dir = Path(__file__).resolve().parents[3] / "skills" / f"{cli_name}-cli"

    assert skill_dir.exists(), (
        f"No repo-owned CLI tool skill found for '{cli_name}' at {skill_dir}. "
        f"Fix: Run /create-cli-tool-skill for {cli_name}"
    )

    skill_md = skill_dir / "SKILL.md"
    assert skill_md.exists(), (
        f"Skill directory exists but missing SKILL.md at {skill_md}. "
        f"Fix: Run /create-cli-tool-skill for {cli_name}"
    )

    usage_json = skill_dir / "usage.json"
    assert usage_json.exists(), (
        f"Skill directory exists but missing usage.json at {usage_json}. "
        f"Fix: Run /create-cli-tool-skill for {cli_name}"
    )
