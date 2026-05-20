"""Profile-specific validation tests.

All CLI tools that expose auth/profiles must have at least a default profile.
CLIs in the ``no_auth_clis`` exclusion list are local-only (no remote
credentials, no auth subcommand) and intentionally have no profile system —
those CLIs are skipped here.

Profile data (cache, browser-data, auth markers) AND per-profile ``.env``
files must be stored in ~/.local/share/cli-tools/<name>/.profiles/, NOT
inside the tool directory. The single source of truth for this path is
``cli_tools_shared.config.get_profiles_base_dir``.
"""

import os
import pytest
from pathlib import Path

from cli_tools_shared.config import get_profiles_base_dir


def _get_user_data_profiles_dir(cli_name: str) -> Path:
    """Get the expected user-data profiles directory for a CLI tool."""
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "cli-tools" / cli_name / ".profiles"


def _skip_if_no_auth(cli_name, test_config):
    """Skip the test if the CLI is in the no_auth_clis exclusion list.

    no_auth CLIs (e.g. things, reminders, cliclick) are local-only tools
    with no remote credentials and no auth subcommand. They intentionally
    have no .env / profile infrastructure, so profile-validation tests do
    not apply to them.
    """
    no_auth_clis = test_config["exclusions"].get("no_auth_clis", [])
    if cli_name in no_auth_clis:
        pytest.skip(
            f"{cli_name} is in no_auth_clis exclusion list "
            f"(no auth subcommand, no profile infrastructure required)"
        )


def test_only_one_default_profile(cli_name, cli_dir, cli_executable, test_config):
    """All auth-capable CLIs: exactly one profile .env has IS_DEFAULT_PROFILE=1.

    Profiles live at ``~/.local/share/cli-tools/<tool>/.profiles/<name>/.env``
    (XDG-compliant user data dir). The path is resolved via
    ``cli_tools_shared.config.get_profiles_base_dir`` — the single source of
    truth — so this test never hardcodes the location.
    """
    _skip_if_no_auth(cli_name, test_config)

    # Invoke the CLI once so BaseConfig auto-initialises the default profile
    # (and migrates any legacy repo-local .env files into the user data dir).
    # This must be deterministic — no try/except, no fallback.
    import subprocess
    result = subprocess.run(
        [cli_executable, "--help"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, (
        f"'{cli_name} --help' failed with exit code {result.returncode}. "
        f"Cannot verify profile state without a working CLI install. "
        f"stderr: {result.stderr[:300]}"
    )

    profiles_dir = get_profiles_base_dir(cli_name)
    assert profiles_dir.exists(), (
        f"'{cli_name}' has no profiles directory at {profiles_dir}. "
        f"All auth-capable CLI tools must auto-initialise a default profile "
        f"via BaseConfig on first invocation. "
        f"Fix: Ensure Config(...) is constructed in main.py / create_auth_app()."
    )

    env_files = sorted(profiles_dir.glob("*/.env"))
    assert env_files, (
        f"'{cli_name}' has no profile .env files under {profiles_dir}. "
        f"Expected at least {profiles_dir / 'default' / '.env'}. "
        f"Fix: Ensure BaseConfig auto-initialises the default profile."
    )

    defaults = []
    for f in env_files:
        content = f.read_text()
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("IS_DEFAULT_PROFILE="):
                value = line.split("=", 1)[1].strip().strip("\"'")
                if value == "1":
                    # Report as ``<profile-name>/.env`` for a useful failure message.
                    defaults.append(f"{f.parent.name}/.env")

    assert len(defaults) == 1, (
        f"'{cli_name}' should have exactly one default profile "
        f"(IS_DEFAULT_PROFILE=1) under {profiles_dir}. "
        f"Found {len(defaults)}: {', '.join(defaults) if defaults else 'none'}. "
        f"Fix: Ensure exactly one profile .env has IS_DEFAULT_PROFILE=1."
    )


def test_env_example_has_is_default_profile(cli_name, cli_dir, test_config):
    """All auth-capable CLIs: .env.example includes IS_DEFAULT_PROFILE=."""
    _skip_if_no_auth(cli_name, test_config)
    env_example = cli_dir / ".env.example"
    assert env_example.exists(), (
        f"'{cli_name}' has no .env.example file. "
        f"All CLI tools must have a .env.example template. "
        f"Fix: Create .env.example with IS_DEFAULT_PROFILE=1 and all required env vars."
    )

    content = env_example.read_text()
    assert "IS_DEFAULT_PROFILE=" in content, (
        f"'{cli_name}/.env.example' missing IS_DEFAULT_PROFILE= line. "
        f"Fix: Add IS_DEFAULT_PROFILE=1 to .env.example."
    )


def test_profiles_dir_gitignored(cli_name, cli_dir):
    """All CLIs: .profiles/ is in .gitignore."""
    gitignore = cli_dir / ".gitignore"
    assert gitignore.exists(), (
        f"'{cli_name}' has no .gitignore file. "
        f"Fix: Create .gitignore with .profiles/ and .env.* entries."
    )

    content = gitignore.read_text()
    assert ".profiles/" in content or ".profiles" in content, (
        f"'{cli_name}/.gitignore' missing .profiles/ entry. "
        f"Fix: Add '.profiles/' to .gitignore."
    )


def test_env_star_gitignored(cli_name, cli_dir):
    """All CLIs: .env.* pattern (except .env.example) is in .gitignore."""
    gitignore = cli_dir / ".gitignore"
    assert gitignore.exists(), (
        f"'{cli_name}' has no .gitignore file. "
        f"Fix: Create .gitignore with .profiles/ and .env.* entries."
    )

    content = gitignore.read_text()
    assert ".env.*" in content, (
        f"'{cli_name}/.gitignore' missing '.env.*' pattern. "
        f"Fix: Add '.env.*' and '!.env.example' to .gitignore."
    )


def test_no_profiles_in_tool_dir(cli_name, cli_dir):
    """All CLIs: .profiles/ must NOT exist inside the tool directory.

    Profile data (browser sessions, cache, auth state) is machine-specific
    and must live in ~/.local/share/cli-tools/<name>/.profiles/ instead.
    If this test fails, the auto-migration hasn't run yet — invoke any
    CLI command (e.g. `<cli> auth status`) to trigger it.
    """
    old_profiles = cli_dir / ".profiles"
    assert not old_profiles.exists(), (
        f"'{cli_name}' has .profiles/ inside tool directory ({old_profiles}). "
        f"Profile data must be in ~/.local/share/cli-tools/{cli_name}/.profiles/. "
        f"Fix: Run any command (e.g. '{cli_name} auth status') to trigger auto-migration."
    )


def test_profiles_stored_in_user_data_dir(cli_name, cli_dir, cli_executable, test_config):
    """All auth-capable CLIs with profile data: stored in ~/.local/share/cli-tools/<name>/.profiles/.

    Skips if the tool has never created profile data (no profiles anywhere).
    The user-data profiles dir is created by BaseConfig as the parent for
    profile-specific data (browser sessions, cache). The 'default/' subdirectory
    is only created when profile data is actually written, so an empty .profiles/
    directory is acceptable.
    """
    _skip_if_no_auth(cli_name, test_config)

    import subprocess

    user_data_dir = _get_user_data_profiles_dir(cli_name)
    old_dir = cli_dir / ".profiles"

    if not user_data_dir.exists() and not old_dir.exists():
        pytest.skip(f"'{cli_name}' has no profile data yet")

    assert user_data_dir.exists(), (
        f"'{cli_name}' profile data not found at {user_data_dir}. "
        f"Fix: Run any command (e.g. '{cli_name} auth status') to trigger migration."
    )

    # Verify the profiles command can list profiles (proves profile system works)
    result = subprocess.run(
        [cli_executable, "auth", "profiles", "list"],
        capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, (
        f"'{cli_name} auth profiles list' failed with exit code {result.returncode}. "
        f"Fix: Ensure profiles are mounted under auth via create_auth_app()."
    )

    # Verify exactly one profile is flagged as the default. The default
    # profile directory may be named anything (default, adam-bertram, work,
    # etc.); is-default-ness is determined by the `is_default: true` flag in
    # the JSON, which is itself driven by the IS_DEFAULT_PROFILE=1 line in
    # the profile's .env. The directory name is irrelevant.
    import json
    try:
        profiles = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        pytest.fail(
            f"'{cli_name} auth profiles list' did not return valid JSON. "
            f"Output: {result.stdout[:200]}"
        )

    assert profiles, (
        f"'{cli_name} auth profiles list' returned no profiles. "
        f"Fix: Ensure BaseConfig auto-initialises a default profile."
    )

    defaults = [p for p in profiles if p.get("is_default") is True]
    profile_names = [p.get("name", "") for p in profiles]
    assert len(defaults) == 1, (
        f"'{cli_name} auth profiles list' should report exactly one profile with "
        f"is_default=true. Found {len(defaults)} among {profile_names}. "
        f"Fix: Ensure exactly one profile .env has IS_DEFAULT_PROFILE=1."
    )
