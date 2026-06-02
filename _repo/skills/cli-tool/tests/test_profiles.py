"""Profile-specific validation tests.

All CLI tools that expose auth/profiles must have at least one active profile.
CLIs in the ``no_auth_clis`` exclusion list are local-only (no remote
credentials, no auth subcommand) and intentionally have no profile system —
those CLIs are skipped here.

Profile data (cache, browser-data, auth markers) AND per-profile ``.env``
files must be stored in ~/.local/share/cli-tools/<name>/authentication_profiles/, NOT
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
    return base / "cli-tools" / cli_name / "authentication_profiles"


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


def test_each_auth_type_has_one_active_profile(cli_name, cli_dir, cli_executable, test_config):
    """All auth-capable CLIs: exactly one profile per auth type is ACTIVE=true.

    Profiles live at ``~/.local/share/cli-tools/<tool>/authentication_profiles/<name>/.env``
    (XDG-compliant user data dir). The path is resolved via
    ``cli_tools_shared.config.get_profiles_base_dir`` — the single source of
    truth — so this test never hardcodes the location.
    """
    _skip_if_no_auth(cli_name, test_config)

    # Invoke the CLI once so BaseConfig auto-initialises the active profile
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
        f"All auth-capable CLI tools must auto-initialise an active profile "
        f"via BaseConfig on first invocation. "
        f"Fix: Ensure Config(...) is constructed in main.py / create_auth_app()."
    )

    env_files = sorted(profiles_dir.glob("*/.env"))
    assert env_files, (
        f"'{cli_name}' has no profile .env files under {profiles_dir}. "
        f"Expected at least one profile .env. "
        f"Fix: Ensure BaseConfig auto-initialises the active profile."
    )

    import json
    profiles_result = subprocess.run(
        [cli_executable, "auth", "profiles", "list"],
        capture_output=True, text=True, timeout=15,
    )
    assert profiles_result.returncode == 0, (
        f"'{cli_name} auth profiles list' failed with exit code {profiles_result.returncode}. "
        f"Cannot verify active profiles. stderr: {profiles_result.stderr[:300]}"
    )
    profiles = json.loads(profiles_result.stdout)
    active_by_type = {}
    auth_types = set()
    for profile in profiles:
        auth_types.add(profile.get("auth_type"))
        if profile.get("active") is True:
            active_by_type.setdefault(profile.get("auth_type"), []).append(profile.get("name"))

    invalid = {
        auth_type: active_by_type.get(auth_type, [])
        for auth_type in auth_types
        if len(active_by_type.get(auth_type, [])) != 1
    }
    assert not invalid, (
        f"'{cli_name}' should have exactly one active profile per auth type. "
        f"Invalid auth types: {invalid}. "
        f"Fix: Select one active profile per auth type with '{cli_name} auth profiles select <name>'."
    )


def test_env_example_has_active_profile_marker(cli_name, cli_dir, test_config):
    """All auth-capable CLIs: .env.example includes ACTIVE=."""
    _skip_if_no_auth(cli_name, test_config)
    env_example = cli_dir / ".env.example"
    assert env_example.exists(), (
        f"'{cli_name}' has no .env.example file. "
        f"All CLI tools must have a .env.example template. "
        f"Fix: Create .env.example with ACTIVE=true and all required env vars."
    )

    content = env_example.read_text()
    assert "ACTIVE=" in content, (
        f"'{cli_name}/.env.example' missing ACTIVE= line. "
        f"Fix: Add ACTIVE=true to .env.example."
    )


def test_profiles_dir_gitignored(cli_tools_root):
    """Repo root .gitignore ignores authentication_profiles/ for every CLI."""
    gitignore = cli_tools_root / ".gitignore"
    assert gitignore.exists(), (
        "Repo root .gitignore not found. "
        f"Fix: Create .gitignore with authentication_profiles/ and .env.* entries."
    )

    content = gitignore.read_text()
    assert "authentication_profiles/" in content or "authentication_profiles" in content, (
        "Repo root .gitignore missing authentication_profiles/ entry. "
        f"Fix: Add 'authentication_profiles/' to .gitignore."
    )


def test_env_star_gitignored(cli_tools_root):
    """Repo root .gitignore ignores .env.* while preserving .env.example."""
    gitignore = cli_tools_root / ".gitignore"
    assert gitignore.exists(), (
        "Repo root .gitignore not found. "
        f"Fix: Create .gitignore with authentication_profiles/ and .env.* entries."
    )

    content = gitignore.read_text()
    assert ".env.*" in content, (
        "Repo root .gitignore missing '.env.*' pattern. "
        f"Fix: Add '.env.*' and '!.env.example' to .gitignore."
    )


def test_no_profiles_in_tool_dir(cli_name, cli_dir):
    """All CLIs: authentication_profiles/ must NOT exist inside the tool directory.

    Profile data (browser sessions, cache, auth state) is machine-specific
    and must live in ~/.local/share/cli-tools/<name>/authentication_profiles/ instead.
    If this test fails, the auto-migration hasn't run yet — invoke any
    CLI command (e.g. `<cli> auth status`) to trigger it.
    """
    old_profiles = cli_dir / "authentication_profiles"
    assert not old_profiles.exists(), (
        f"'{cli_name}' has authentication_profiles/ inside tool directory ({old_profiles}). "
        f"Profile data must be in ~/.local/share/cli-tools/{cli_name}/authentication_profiles/. "
        f"Fix: Run any command (e.g. '{cli_name} auth status') to trigger auto-migration."
    )


def test_profiles_stored_in_user_data_dir(cli_name, cli_dir, cli_executable, test_config):
    """All auth-capable CLIs with profile data: stored in ~/.local/share/cli-tools/<name>/authentication_profiles/.

    Skips if the tool has never created profile data (no profiles anywhere).
    The user-data profiles dir is created by BaseConfig as the parent for
    profile-specific data (browser sessions, cache). The 'default/' subdirectory
    is only created when profile data is actually written, so an empty authentication_profiles/
    directory is acceptable.
    """
    _skip_if_no_auth(cli_name, test_config)

    import subprocess

    user_data_dir = _get_user_data_profiles_dir(cli_name)
    old_dir = cli_dir / "authentication_profiles"

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

    # Verify exactly one profile is active per auth type.
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
        f"Fix: Ensure BaseConfig auto-initialises an active profile."
    )

    missing_fields = [
        p.get("name", "<unnamed>")
        for p in profiles
        if "is_default" in p or not isinstance(p.get("auth_type"), str) or not isinstance(p.get("active"), bool)
    ]
    assert not missing_fields, (
        f"'{cli_name} auth profiles list' must return active/auth_type schema and no is_default field. "
        f"Profiles with invalid schema: {missing_fields}."
    )

    active_by_type = {}
    for profile in profiles:
        if profile.get("active") is True:
            active_by_type.setdefault(profile["auth_type"], []).append(profile["name"])
    auth_types = {profile["auth_type"] for profile in profiles}
    invalid_auth_types = {
        auth_type: active_by_type.get(auth_type, [])
        for auth_type in auth_types
        if len(active_by_type.get(auth_type, [])) != 1
    }
    assert not invalid_auth_types, (
        f"'{cli_name} auth profiles list' should report exactly one active profile per auth type. "
        f"Invalid auth types: {invalid_auth_types}. "
        f"Fix: Ensure profile selection uses ACTIVE=true scoped by auth_type."
    )
