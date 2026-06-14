"""Authentication command validation tests (Section 3)."""

import re
import pytest
from pathlib import Path

from cli_test_utils import run_cli_command, validate_json_output, parse_help_commands


def _help_has_command(help_text: str, command: str) -> bool:
    """Check whether a help page lists a command."""
    return command in parse_help_commands(help_text) or f" {command} " in help_text or f"│ {command}" in help_text


def _cli_has_auth(help_cache):
    """Auto-detect whether a CLI has an auth subcommand by inspecting its help output."""
    help_text = help_cache("")
    return _help_has_command(help_text, "auth")


def _should_skip_auth(cli_name, help_cache, test_config, command_filter):
    """Return a skip reason string if auth tests should be skipped, or None to proceed."""
    if command_filter and command_filter != "auth":
        return f"Skipping auth tests (filtering to '{command_filter}')"

    no_auth_clis = test_config["exclusions"]["no_auth_clis"]
    if cli_name in no_auth_clis:
        return f"{cli_name} is in no_auth_clis exclusion list"

    if not _cli_has_auth(help_cache):
        return f"{cli_name} has no auth subcommand (auth is optional for this CLI type)"

    return None


def _should_skip_profiles(cli_name, help_cache, test_config, command_filter):
    """Return a skip reason string if profiles tests should be skipped."""
    if command_filter and command_filter not in ("auth", "profiles"):
        return f"Skipping profiles tests (filtering to '{command_filter}')"

    no_auth_clis = test_config["exclusions"]["no_auth_clis"]
    if cli_name in no_auth_clis:
        return f"{cli_name} is in no_auth_clis exclusion list"

    if not _cli_has_auth(help_cache):
        return f"{cli_name} has no auth subcommand (profiles live under auth)"

    return None


def _skip_live_browser_auth(cli_name, is_browser_cli):
    if is_browser_cli:
        pytest.skip(f"{cli_name} is a browser CLI; compliance tests do not run live browser auth commands")


def _assert_auth_status_returncode(result, cli_name):
    assert result.returncode in (0, 2), (
        f"'{cli_name} auth status' exited {result.returncode}: {result.stderr[:300]}"
    )


def test_auth_subcommand_exists(cli_name, help_cache, test_config, command_filter):
    """Assertion 9: auth subcommand exists (skipped if CLI has no auth)."""
    if command_filter and command_filter != "auth":
        pytest.skip(f"Skipping auth tests (filtering to '{command_filter}')")

    no_auth_clis = test_config["exclusions"]["no_auth_clis"]
    if cli_name in no_auth_clis:
        pytest.skip(f"{cli_name} does not have auth commands (in no_auth_clis)")

    # Auto-detect: if CLI has no auth subcommand, skip instead of fail
    if not _cli_has_auth(help_cache):
        pytest.skip(f"{cli_name} has no auth subcommand (auth is optional for this CLI type)")

    # If we get here, auth exists - test passes
    assert True


def test_auth_no_args_shows_help(cli_executable, cli_name, help_cache, test_config, command_filter):
    """Assertion 10: auth with no args shows help."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    result = run_cli_command(cli_executable, ["auth"])
    assert result.returncode in [0, 2], "auth subcommand should show help"
    # Check both stdout and stderr since Typer's help output location varies
    combined_output = result.stdout + result.stderr
    assert "Commands:" in combined_output or "Usage:" in combined_output, (
        f"auth with no args should show help. Got stdout: '{result.stdout[:100]}', stderr: '{result.stderr[:100]}'"
    )


def test_auth_login_exists(cli_name, help_cache, test_config, command_filter):
    """Assertion 11: auth login command exists."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    help_text = help_cache("auth")
    assert _help_has_command(help_text, "login"), (
        f"'{cli_name} auth' missing 'login' command. "
        f"Fix: Add login command to auth group."
    )


def test_auth_login_has_force_flag(cli_name, help_cache, test_config, command_filter):
    """Assertion 12: auth login has --force/-F flag."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    help_text = help_cache("auth login")
    assert "--force" in help_text or "-F" in help_text, (
        f"'{cli_name} auth login' missing --force/-F flag. "
        f"Fix: Add force parameter to login command: "
        f"force: bool = typer.Option(False, '--force', '-F', help='Force re-authentication')"
    )


def test_auth_status_exists(cli_name, help_cache, test_config, command_filter):
    """Assertion 13: auth status command exists."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    help_text = help_cache("auth")
    assert _help_has_command(help_text, "status"), (
        f"'{cli_name} auth' missing 'status' command. "
        f"Fix: Add status command to auth group."
    )


def test_auth_status_outputs_json_with_profiles(cli_executable, cli_name, help_cache, test_config, command_filter, is_browser_cli):
    """auth status outputs valid JSON with a 'profiles' array of per-profile entries."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)
    _skip_live_browser_auth(cli_name, is_browser_cli)

    result = run_cli_command(cli_executable, ["auth", "status"])
    _assert_auth_status_returncode(result, cli_name)

    valid, data = validate_json_output(result.stdout)
    assert valid, (
        f"'{cli_name} auth status' did not output valid JSON. "
        f"Fix: Ensure status command uses print_json() for output."
    )
    assert "profiles" in data and isinstance(data["profiles"], list), (
        f"'{cli_name} auth status' JSON missing 'profiles' array. "
        f"Fix: Update cli-tools-shared so auth status emits "
        f"{{'profiles': [...]}} (per-profile, per-credential-type shape)."
    )
    assert data["profiles"], (
        f"'{cli_name} auth status' returned an empty 'profiles' array. "
        f"Expected at least one active profile entry."
    )
    for entry in data["profiles"]:
        assert "name" in entry, "profile entry missing 'name'"
        assert "authenticated" in entry, "profile entry missing 'authenticated'"
        assert "credential_types" in entry, "profile entry missing 'credential_types'"


def test_auth_status_has_credentials_saved(cli_executable, cli_name, cli_dir, help_cache, test_config, command_filter, is_browser_cli):
    """Every credential_types block in auth status must include 'credentials_saved'."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)
    _skip_live_browser_auth(cli_name, is_browser_cli)
    if _config_declares_no_credential_types(cli_dir, cli_name):
        pytest.skip(f"{cli_name} declares no credential types")

    result = run_cli_command(cli_executable, ["auth", "status"])
    _assert_auth_status_returncode(result, cli_name)

    valid, data = validate_json_output(result.stdout)
    assert valid, "auth status must output valid JSON"
    assert "profiles" in data, "auth status must emit 'profiles' array"

    for entry in data["profiles"]:
        cred_types = entry.get("credential_types") or {}
        assert cred_types, (
            f"profile '{entry.get('name')}' has empty credential_types. "
            f"Fix: Ensure AuthVerifier populates credential_types from config.CREDENTIAL_TYPES."
        )
        for type_key, block in cred_types.items():
            assert "credentials_saved" in block, (
                f"'{cli_name} auth status' profile '{entry.get('name')}' "
                f"credential_types['{type_key}'] missing 'credentials_saved'. "
                f"Fix: Update cli-tools-shared to latest version with AuthVerifier "
                f"that returns per-type credentials_saved."
            )


def test_auth_status_has_credential_types(cli_executable, cli_name, cli_dir, help_cache, test_config, command_filter, is_browser_cli):
    """Each profile must have a non-empty credential_types dict."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)
    _skip_live_browser_auth(cli_name, is_browser_cli)
    if _config_declares_no_credential_types(cli_dir, cli_name):
        pytest.skip(f"{cli_name} declares no credential types")

    result = run_cli_command(cli_executable, ["auth", "status"])
    _assert_auth_status_returncode(result, cli_name)

    valid, data = validate_json_output(result.stdout)
    assert valid, "auth status must output valid JSON"

    for entry in data["profiles"]:
        cred_types = entry.get("credential_types")
        assert isinstance(cred_types, dict) and cred_types, (
            f"profile '{entry.get('name')}' credential_types must be a non-empty dict. "
            f"Fix: Ensure config.CREDENTIAL_TYPES is set and AuthVerifier produces a block per type."
        )
        for type_key, block in cred_types.items():
            assert "authenticated" in block, (
                f"credential_types['{type_key}'] missing 'authenticated' in profile "
                f"'{entry.get('name')}'."
            )


def _parse_credential_types_from_config(cli_dir, cli_name) -> list:
    """AST-parse the CLI's config.py to extract CREDENTIAL_TYPES enum values.

    Returns lowercase type values (e.g. ['oauth', 'browser_session']) or [] if unknown.
    """
    import ast
    cli_pkg = cli_dir / f"{cli_name.replace('-', '_')}_cli"
    config_file = cli_pkg / "config.py"
    if not config_file.exists():
        return []
    try:
        tree = ast.parse(config_file.read_text())
    except Exception:
        return []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not (isinstance(target, ast.Name) and target.id == "CREDENTIAL_TYPES"):
                continue
            if not isinstance(node.value, ast.List):
                continue
            values = []
            for elt in node.value.elts:
                if isinstance(elt, ast.Attribute) and elt.attr:
                    values.append(elt.attr.lower())
            return values
    return []


def _config_declares_no_credential_types(cli_dir, cli_name) -> bool:
    """Return True when Config explicitly declares CREDENTIAL_TYPES = []."""
    import ast
    cli_pkg = cli_dir / f"{cli_name.replace('-', '_')}_cli"
    config_file = cli_pkg / "config.py"
    if not config_file.exists():
        return False
    try:
        tree = ast.parse(config_file.read_text())
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "CREDENTIAL_TYPES":
                return isinstance(node.value, ast.List) and len(node.value.elts) == 0
    return False


def test_auth_status_credential_types_match_config(
    cli_executable, cli_name, cli_dir, help_cache, test_config, command_filter, is_browser_cli
):
    """auth status credential_types keys must match config.CREDENTIAL_TYPES."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)
    _skip_live_browser_auth(cli_name, is_browser_cli)

    expected = set(_parse_credential_types_from_config(cli_dir, cli_name))
    if not expected:
        pytest.skip(f"Could not determine CREDENTIAL_TYPES for {cli_name}")

    result = run_cli_command(cli_executable, ["auth", "status"])
    _assert_auth_status_returncode(result, cli_name)
    valid, data = validate_json_output(result.stdout)
    assert valid, "auth status must output valid JSON"

    for entry in data["profiles"]:
        actual = set((entry.get("credential_types") or {}).keys())
        assert actual == expected, (
            f"'{cli_name} auth status' profile '{entry.get('name')}' "
            f"credential_types keys {sorted(actual)} do not match "
            f"config.CREDENTIAL_TYPES {sorted(expected)}. "
            f"Fix: Ensure AuthVerifier iterates config.CREDENTIAL_TYPES."
        )


def test_auth_status_lists_all_profiles_by_default(
    cli_executable, cli_name, help_cache, test_config, command_filter, is_browser_cli
):
    """auth status with no --profile must return active profiles only."""
    skip_reason = _should_skip_profiles(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)
    _skip_live_browser_auth(cli_name, is_browser_cli)

    profiles_result = run_cli_command(cli_executable, ["auth", "profiles", "list"])
    if profiles_result.returncode != 0:
        pytest.skip(f"{cli_name} auth profiles list failed")
    p_valid, p_data = validate_json_output(profiles_result.stdout)
    if not p_valid or not isinstance(p_data, list):
        pytest.skip(f"{cli_name} auth profiles list did not return JSON array")

    status_result = run_cli_command(cli_executable, ["auth", "status"])
    _assert_auth_status_returncode(status_result, cli_name)
    valid, data = validate_json_output(status_result.stdout)
    assert valid, "auth status must output valid JSON"

    expected_names = {p["name"] for p in p_data if p.get("active") is True}
    actual_names = {entry.get("name") for entry in data.get("profiles", [])}
    assert actual_names == expected_names, (
        f"'{cli_name} auth status' returned profiles {sorted(actual_names)} but "
        f"'auth profiles list' reports active profiles {sorted(expected_names)}. "
        f"Fix: Ensure auth_commands.py iterates only active profiles when --profile is not set."
    )


def test_auth_status_has_table_flag(cli_name, help_cache, test_config, command_filter):
    """Assertion 15: auth status has --table/-t flag."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    help_text = help_cache("auth status")
    assert "--table" in help_text or "-t" in help_text, (
        f"'{cli_name} auth status' missing --table/-t flag. "
        f"Fix: Add table parameter: "
        f"table: bool = typer.Option(False, '--table', '-t', help='Display as table')"
    )


# ==================== Profile Support (All Auth CLIs) ====================


def test_auth_login_has_profile_flag(cli_name, cli_dir, help_cache, test_config, command_filter):
    """All auth CLIs: auth login has --profile/-p flag for named profiles."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    help_text = help_cache("auth login")
    assert "--profile" in help_text or "-p" in help_text, (
        f"'{cli_name} auth login' missing --profile/-p flag. "
        f"Fix: Use create_auth_app() from cli_tools_shared which includes --profile on all commands."
    )


def test_auth_status_has_profile_flag(cli_name, cli_dir, help_cache, test_config, command_filter):
    """All auth CLIs: auth status has --profile/-p flag for named profiles."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    help_text = help_cache("auth status")
    assert "--profile" in help_text or "-p" in help_text, (
        f"'{cli_name} auth status' missing --profile/-p flag. "
        f"Fix: Use create_auth_app() from cli_tools_shared which includes --profile on all commands."
    )


def test_auth_logout_has_profile_flag(cli_name, cli_dir, help_cache, test_config, command_filter):
    """All auth CLIs: auth logout has --profile/-p flag for named profiles."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    help_text = help_cache("auth logout")
    assert "--profile" in help_text or "-p" in help_text, (
        f"'{cli_name} auth logout' missing --profile/-p flag. "
        f"Fix: Use create_auth_app() from cli_tools_shared which includes --profile on all commands."
    )


# ==================== Environment & Profiles Conventions ====================


def test_env_has_active_profile(cli_name, cli_dir, cli_executable, help_cache, test_config, command_filter):
    """All auth-capable CLIs: at least one profile under
    ``~/.local/share/cli-tools/<tool>/authentication_profiles/<name>/.env`` has
    ``ACTIVE=true``. Profile activity is scoped by auth type.

    Profile base path resolved via ``cli_tools_shared.config.get_profiles_base_dir``
    — the single source of truth — so this test never hardcodes the location.

    no_auth CLIs (local-only tools with no auth subcommand) intentionally
    have no .env / profile system, so this test does not apply to them.
    """
    if command_filter and command_filter != "auth":
        pytest.skip(f"Skipping auth tests (filtering to '{command_filter}')")

    no_auth_clis = test_config["exclusions"].get("no_auth_clis", [])
    if cli_name in no_auth_clis:
        pytest.skip(
            f"{cli_name} is in no_auth_clis exclusion list "
            f"(no auth subcommand, no .env profile required)"
        )

    from cli_tools_shared.config import get_profiles_base_dir
    import subprocess

    # Invoke the CLI once so BaseConfig auto-initialises the active profile
    # (and migrates any legacy repo-local .env files into the user data dir).
    result = subprocess.run(
        [cli_executable, "--help"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, (
        f"'{cli_name} --help' failed with exit code {result.returncode}. "
        f"Cannot verify active profile without a working CLI install. "
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
        f"Fix: Ensure BaseConfig auto-initialises an active profile on first invocation."
    )

    active_envs = []
    for env_file in env_files:
        content = env_file.read_text()
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("ACTIVE="):
                value = stripped.split("=", 1)[1].strip().strip("\"'")
                if value == "true":
                    active_envs.append(env_file)
                break

    assert active_envs, (
        f"'{cli_name}' has profile(s) under {profiles_dir} but none have "
        f"ACTIVE=true in their .env. Checked: "
        f"{[str(f.parent.name) + '/.env' for f in env_files]}. "
        f"Fix: Select an active profile with '{cli_name} auth profiles select <name>', or "
        f"reinitialise by removing the profiles dir and running any CLI command "
        f"(BaseConfig auto-creates an active profile)."
    )


def _parse_custom_allowed_fields(cli_dir, cli_name) -> set:
    """AST-parse config.py for custom field list literal values.

    Returns a set of declared field name strings, or empty set if not found.
    Fields declared there are intentionally legacy-named or optional custom
    fields preserved during auth migration and should be exempt from the
    generic-name test.
    """
    import ast
    cli_pkg = cli_dir / f"{cli_name.replace('-', '_')}_cli"
    config_file = cli_pkg / "config.py"
    if not config_file.exists():
        return set()
    try:
        tree = ast.parse(config_file.read_text())
    except Exception:
        return set()
    custom_field_attrs = {"CUSTOM_REQUIRED_FIELDS", "CUSTOM_ALL_FIELDS"}
    fields = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not (isinstance(target, ast.Name) and target.id in custom_field_attrs):
                continue
            if not isinstance(node.value, ast.List):
                continue
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    fields.add(elt.value)
    return fields


def test_env_no_service_prefix(cli_name, cli_dir, help_cache, test_config, command_filter):
    """All CLIs: .env.example vars use generic names (API_KEY not CLOUDFLARE_API_KEY).

    Exception: names declared in Config.CUSTOM_REQUIRED_FIELDS or
    Config.CUSTOM_ALL_FIELDS are intentional legacy/custom names preserved
    during auth migration and are allowed.
    """
    if command_filter and command_filter != "auth":
        pytest.skip(f"Skipping auth tests (filtering to '{command_filter}')")

    env_example = cli_dir / ".env.example"
    if not env_example.exists():
        pytest.skip(f"{cli_name} has no .env.example file")

    content = env_example.read_text()
    allowed = _parse_custom_allowed_fields(cli_dir, cli_name)

    # Check for service-prefixed vars (TOOLNAME_API_KEY instead of API_KEY)
    tool_upper = cli_name.upper().replace("-", "_")
    prefixed_vars = []
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("#") or not line or "=" not in line:
            continue
        var_name = line.split("=", 1)[0].strip()
        if var_name.startswith(f"{tool_upper}_") and var_name not in allowed:
            prefixed_vars.append(var_name)

    assert not prefixed_vars, (
        f"'{cli_name}/.env.example' has service-prefixed env vars: {', '.join(prefixed_vars)}. "
        f"Fix: Use generic names (API_KEY, BASE_URL, USERNAME) instead of "
        f"{tool_upper}_API_KEY, {tool_upper}_BASE_URL, etc. — OR declare them in "
        f"Config.CUSTOM_REQUIRED_FIELDS or Config.CUSTOM_ALL_FIELDS if preserving "
        f"legacy/custom names intentionally."
    )


def test_auth_profiles_command_exists(cli_name, help_cache, test_config, command_filter):
    """All auth CLIs: 'auth profiles' command group exists."""
    skip_reason = _should_skip_profiles(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    help_text = help_cache("auth")
    assert _help_has_command(help_text, "profiles"), (
        f"'{cli_name} auth' missing 'profiles' command group. "
        f"Fix: use create_auth_app() or mount the profiles app under custom auth."
    )


def test_top_level_profiles_command_removed(cli_name, help_cache, test_config, command_filter):
    """All CLIs: profiles must be nested under auth, not exposed at root."""
    if command_filter and command_filter not in ("auth", "profiles"):
        pytest.skip(f"Skipping profiles tests (filtering to '{command_filter}')")

    help_text = help_cache("")
    assert not _help_has_command(help_text, "profiles"), (
        f"'{cli_name}' still exposes top-level 'profiles'. "
        f"Fix: Move it under auth as '{cli_name} auth profiles'."
    )


def test_profiles_list_subcommand(cli_name, help_cache, test_config, command_filter):
    """All auth CLIs: 'auth profiles list' subcommand exists."""
    skip_reason = _should_skip_profiles(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    help_text = help_cache("auth profiles")
    assert _help_has_command(help_text, "list"), (
        f"'{cli_name} auth profiles' missing 'list' subcommand. "
        f"Fix: mount the standard profiles app under auth."
    )


def test_profiles_create_subcommand(cli_name, help_cache, test_config, command_filter):
    """All auth CLIs: 'auth profiles create' subcommand exists."""
    skip_reason = _should_skip_profiles(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    help_text = help_cache("auth profiles")
    assert _help_has_command(help_text, "create"), (
        f"'{cli_name} auth profiles' missing 'create' subcommand. "
        f"Fix: mount the standard profiles app under auth."
    )


def test_profiles_select_subcommand(cli_name, help_cache, test_config, command_filter):
    """All auth CLIs: 'auth profiles select' subcommand exists and set-default is removed."""
    skip_reason = _should_skip_profiles(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    help_text = help_cache("auth profiles")
    assert _help_has_command(help_text, "select"), (
        f"'{cli_name} auth profiles' missing 'select' subcommand. "
        f"Fix: mount the standard profiles app under auth."
    )
    assert not _help_has_command(help_text, "set-default"), (
        f"'{cli_name} auth profiles' still exposes removed 'set-default' subcommand. "
        f"Fix: replace it with '{cli_name} auth profiles select'."
    )


def test_profiles_delete_subcommand(cli_name, help_cache, test_config, command_filter):
    """All auth CLIs: 'auth profiles delete' subcommand exists."""
    skip_reason = _should_skip_profiles(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    help_text = help_cache("auth profiles")
    assert _help_has_command(help_text, "delete"), (
        f"'{cli_name} auth profiles' missing 'delete' subcommand. "
        f"Fix: mount the standard profiles app under auth."
    )


def test_config_extends_base_config(cli_name, cli_dir, help_cache, test_config, command_filter):
    """All auth CLIs: config.py imports BaseConfig from cli_tools_shared."""
    if command_filter and command_filter not in ("auth", "profiles"):
        pytest.skip(f"Skipping config tests (filtering to '{command_filter}')")

    if not _cli_has_auth(help_cache):
        pytest.skip(f"{cli_name} has no auth subcommand (auth infrastructure not required)")

    # Find config.py in the CLI package
    cli_pkg = cli_dir / f"{cli_name.replace('-', '_')}_cli"
    config_file = cli_pkg / "config.py"

    if not config_file.exists():
        pytest.skip(f"{cli_name} config.py not found at {config_file}")

    content = config_file.read_text()
    assert "BaseConfig" in content and "cli_tools_shared" in content, (
        f"'{cli_name}/config.py' does not import BaseConfig from cli_tools_shared. "
        f"Fix: Rewrite config.py as a thin BaseConfig subclass."
    )


def test_config_uses_resolve_tool_dir(cli_name, cli_dir, help_cache, test_config, command_filter):
    """Auth CLIs must resolve tool_dir from the installed distribution name."""
    if command_filter and command_filter not in ("auth", "profiles"):
        pytest.skip(f"Skipping config tests (filtering to '{command_filter}')")

    if not _cli_has_auth(help_cache):
        pytest.skip(f"{cli_name} has no auth subcommand (auth infrastructure not required)")

    cli_pkg = cli_dir / f"{cli_name.replace('-', '_')}_cli"
    config_file = cli_pkg / "config.py"
    if not config_file.exists():
        pytest.skip(f"{cli_name} config.py not found at {config_file}")

    content = config_file.read_text()
    if "BaseConfig" not in content:
        pytest.skip(f"{cli_name} does not use BaseConfig")

    assert "DIST_NAME" in content, (
        f"'{cli_name}/config.py' missing Config.DIST_NAME. "
        f"Fix: Set DIST_NAME to the pyproject [project].name."
    )
    assert "resolve_tool_dir" in content, (
        f"'{cli_name}/config.py' must use resolve_tool_dir(DIST_NAME). "
        f"Fix: import resolve_tool_dir from cli_tools_shared.config and pass "
        f"tool_dir=resolve_tool_dir(self.DIST_NAME) to BaseConfig."
    )
    assert "Path(__file__).resolve().parent.parent" not in content, (
        f"'{cli_name}/config.py' computes tool_dir from Path(__file__). "
        f"Fix: use resolve_tool_dir(DIST_NAME) so installed uv tool runtimes "
        f"load profiles from the source/tool root, not site-packages."
    )


def _find_config_test_connection_violations(config_file: Path) -> list[tuple[int, str]]:
    """Find profile-unsafe client construction inside Config.test_connection()."""
    import ast

    try:
        tree = ast.parse(config_file.read_text())
    except SyntaxError:
        return []

    violations = []
    for class_node in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "Config"]:
        for func_node in [n for n in class_node.body if isinstance(n, ast.FunctionDef) and n.name == "test_connection"]:
            for call in ast.walk(func_node):
                if not isinstance(call, ast.Call):
                    continue
                if (
                    isinstance(call.func, ast.Name)
                    and call.func.id == "get_client"
                    and not call.args
                    and not call.keywords
                ):
                    violations.append((call.lineno, "get_client()"))
                if (
                    isinstance(call.func, ast.Name)
                    and call.func.id.endswith("Client")
                    and not call.args
                    and not call.keywords
                ):
                    violations.append((call.lineno, f"{call.func.id}()"))
    return violations


def test_config_test_connection_uses_active_config(cli_name, cli_dir, help_cache, test_config, command_filter):
    """Config.test_connection() must validate the config instance being reported."""
    if command_filter and command_filter not in ("auth", "profiles"):
        pytest.skip(f"Skipping config tests (filtering to '{command_filter}')")

    if not _cli_has_auth(help_cache):
        pytest.skip(f"{cli_name} has no auth subcommand (auth infrastructure not required)")

    cli_pkg = cli_dir / f"{cli_name.replace('-', '_')}_cli"
    config_file = cli_pkg / "config.py"
    if not config_file.exists():
        pytest.skip(f"{cli_name} config.py not found at {config_file}")

    violations = _find_config_test_connection_violations(config_file)
    assert not violations, (
        f"'{cli_name}/config.py' test_connection() validates a default/global client "
        f"instead of the active profile config.\nViolations:\n"
        + "\n".join(f"  {config_file.name}:{line} uses {expr}" for line, expr in violations)
        + "\n\nFix: build the API client from self fields or pass config=self to the CLI client."
    )


def test_auth_runtime_state_uses_profile_data_dir(cli_name, cli_dir, help_cache, test_config, command_filter):
    """Auth runtime files must live under BaseConfig.get_profile_data_dir()."""
    if command_filter and command_filter not in ("auth", "profiles"):
        pytest.skip(f"Skipping profile data tests (filtering to '{command_filter}')")

    if not _cli_has_auth(help_cache):
        pytest.skip(f"{cli_name} has no auth subcommand (auth infrastructure not required)")

    cli_pkg = cli_dir / f"{cli_name.replace('-', '_')}_cli"
    if not cli_pkg.exists():
        pytest.skip(f"{cli_name} package directory not found")

    auth_state_markers = ("token.json", "robots.json", "session.json", "profile.json")
    violations = []
    for py_file in cli_pkg.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        lines = py_file.read_text().splitlines()
        for line_num, line in enumerate(lines, start=1):
            if "Path.home()" not in line:
                continue
            if any(marker in line for marker in auth_state_markers):
                violations.append((py_file.relative_to(cli_dir), line_num, line.strip()))

    assert not violations, (
        f"'{cli_name}' stores auth runtime state outside the active profile data dir.\n"
        f"Violations:\n"
        + "\n".join(f"  {path}:{line_num} {line}" for path, line_num, line in violations)
        + "\n\nFix: store auth/session/token files under config.get_profile_data_dir()."
    )


def test_no_stale_auth_commands_in_inactive_cli_packages(cli_name, cli_dir, help_cache, test_config, command_filter):
    """Repos must not retain sibling generated packages with stale auth commands."""
    if command_filter and command_filter not in ("auth", "profiles"):
        pytest.skip(f"Skipping stale auth package tests (filtering to '{command_filter}')")

    active_pkg_name = f"{cli_name.replace('-', '_')}_cli"
    stale_auth_files = []
    for candidate in cli_dir.iterdir():
        if not candidate.is_dir() or not candidate.name.endswith("_cli"):
            continue
        if candidate.name == active_pkg_name:
            continue
        auth_file = candidate / "commands" / "auth.py"
        if auth_file.exists():
            stale_auth_files.append(auth_file.relative_to(cli_dir))

    assert not stale_auth_files, (
        f"'{cli_name}' has inactive sibling CLI packages that still expose auth commands: "
        f"{', '.join(str(path) for path in stale_auth_files)}. "
        f"Fix: delete stale generated packages or migrate them if they are intentionally packaged."
    )


def test_auth_uses_shared_package(cli_name, cli_dir, help_cache, test_config, command_filter):
    """All auth CLIs: auth commands use create_auth_app from cli_tools_shared, not custom auth."""
    if command_filter and command_filter not in ("auth",):
        pytest.skip(f"Skipping auth tests (filtering to '{command_filter}')")

    if not _cli_has_auth(help_cache):
        pytest.skip(f"{cli_name} has no auth subcommand (auth infrastructure not required)")

    wrapper_clis = test_config["exclusions"].get("wrapper_clis", [])
    custom_auth_clis = test_config["exclusions"].get("custom_auth_clis", wrapper_clis)
    if cli_name in custom_auth_clis:
        pytest.skip(f"{cli_name} uses custom auth (wrapper/legacy)")

    # Check main.py for create_auth_app import
    cli_pkg = cli_dir / f"{cli_name.replace('-', '_')}_cli"
    main_file = cli_pkg / "main.py"
    auth_file = cli_pkg / "commands" / "auth.py"

    found_create_auth_app = False

    if main_file.exists():
        content = main_file.read_text()
        if "create_auth_app" in content:
            found_create_auth_app = True

    if not found_create_auth_app and auth_file.exists():
        content = auth_file.read_text()
        if "create_auth_app" in content:
            found_create_auth_app = True

    assert found_create_auth_app, (
        f"'{cli_name}' implements custom auth commands instead of using create_auth_app() "
        f"from cli_tools_shared. Fix: Use create_auth_app(get_config, tool_name='{cli_name}') "
        f"and set OAUTH_* class vars on Config for OAuth flows, or pass a login_handler for "
        f"custom flows."
    )


# ==================== No Direct Prompting (All CLIs) ====================


def test_no_direct_prompting(cli_name, cli_dir, help_cache, test_config, command_filter):
    """All CLIs: must not use typer.prompt() or input() directly — use cli_tools_shared prompting."""
    if command_filter and command_filter not in ("auth",):
        pytest.skip(f"Skipping auth tests (filtering to '{command_filter}')")

    if not _cli_has_auth(help_cache):
        pytest.skip(f"{cli_name} has no auth subcommand (prompting check not applicable)")

    cli_pkg = cli_dir / f"{cli_name.replace('-', '_')}_cli"
    if not cli_pkg.exists():
        pytest.skip(f"{cli_name} package directory not found")

    import ast

    # Only scan the CLI's own source files, not cli_tools_shared
    violations = []
    for py_file in cli_pkg.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        # Skip files inside .venv or site-packages
        rel_parts = py_file.relative_to(cli_dir).parts
        if ".venv" in rel_parts or "site-packages" in rel_parts:
            continue

        source = py_file.read_text()
        rel_path = py_file.relative_to(cli_dir)
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            # Detect typer.prompt(...)
            if isinstance(node, ast.Call):
                if (isinstance(node.func, ast.Attribute)
                        and node.func.attr == "prompt"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "typer"):
                    line = source.splitlines()[node.lineno - 1].strip()
                    violations.append((str(rel_path), node.lineno, "Direct typer.prompt() call", line))
                # Detect input(...)
                elif isinstance(node.func, ast.Name) and node.func.id == "input":
                    line = source.splitlines()[node.lineno - 1].strip()
                    violations.append((str(rel_path), node.lineno, "Direct input() call", line))

    assert not violations, (
        f"'{cli_name}' uses direct prompting instead of cli_tools_shared.\n"
        f"Violations:\n"
        + "\n".join(f"  {f}:{ln} — {desc}: {code}" for f, ln, desc, code in violations)
        + "\n\nFix: Remove direct typer.prompt()/input() calls. Instead:\n"
        "  - For login credentials: set CUSTOM_LOGIN_PROMPTS on Config class\n"
        "  - For extra auth fields: set AUTH_EXTRA_PROMPTS on Config class\n"
        "  - cli_tools_shared's create_auth_app() handles all prompting automatically."
    )


# ==================== Credential Type Scoping (Multi-Credential CLIs) ====================


def _is_multi_credential_cli(cli_dir, cli_name):
    """Check if a CLI has multiple credential types by inspecting its config.py."""
    import ast
    cli_pkg = cli_dir / f"{cli_name.replace('-', '_')}_cli"
    config_file = cli_pkg / "config.py"
    if not config_file.exists():
        return False
    try:
        tree = ast.parse(config_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "CREDENTIAL_TYPES":
                        if isinstance(node.value, ast.List) and len(node.value.elts) >= 2:
                            return True
        return False
    except Exception:
        return False


def test_auth_login_has_credential_type_flag(cli_name, cli_dir, help_cache, test_config, command_filter):
    """Multi-credential CLIs: auth login has --credential-type/-c flag."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    if not _is_multi_credential_cli(cli_dir, cli_name):
        pytest.skip(f"{cli_name} is a single credential type CLI")

    help_text = help_cache("auth login")
    assert "--credential-type" in help_text or "-c" in help_text, (
        f"'{cli_name} auth login' missing --credential-type/-c flag. "
        f"Fix: Update cli-tools-shared to latest version with credential type scoping support."
    )


def _has_browser_session_type(cli_dir, cli_name):
    """Check if a CLI has BROWSER_SESSION in its CREDENTIAL_TYPES list."""
    import ast
    cli_pkg = cli_dir / f"{cli_name.replace('-', '_')}_cli"
    config_file = cli_pkg / "config.py"
    if not config_file.exists():
        return False
    try:
        tree = ast.parse(config_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "CREDENTIAL_TYPES":
                        if isinstance(node.value, ast.List):
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Attribute) and elt.attr == "BROWSER_SESSION":
                                    return True
        return False
    except Exception:
        return False


def test_credential_type_browser_session_skips_prompts(cli_name, cli_dir, help_cache, test_config, command_filter):
    """Multi-credential CLIs with browser_session: --credential-type browser_session skips prompts."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    if not _is_multi_credential_cli(cli_dir, cli_name):
        pytest.skip(f"{cli_name} is a single credential type CLI")

    if not _has_browser_session_type(cli_dir, cli_name):
        pytest.skip(f"{cli_name} does not use BROWSER_SESSION credential type")

    # Verify the shared package implements the browser-session shortcut
    import importlib.util
    spec = importlib.util.find_spec("cli_tools_shared.auth_commands")
    assert spec is not None, "cli_tools_shared.auth_commands not found"
    source = Path(spec.origin).read_text()
    assert "resolved_type == CredentialType.BROWSER_SESSION" in source, (
        "cli_tools_shared auth_commands.py missing BROWSER_SESSION short-circuit. "
        "--credential-type browser_session must skip prompts and go directly to browser login."
    )


def test_browser_session_env_has_username_password(cli_name, cli_dir, help_cache, test_config, is_browser_cli, command_filter):
    """Browser CLIs with BROWSER_SESSION: .env has USERNAME and PASSWORD configured."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    if not is_browser_cli:
        pytest.skip(f"{cli_name} is not a browser automation CLI")

    if not _has_browser_session_type(cli_dir, cli_name):
        pytest.skip(f"{cli_name} does not use BROWSER_SESSION credential type")

    env_file = cli_dir / ".env"
    if not env_file.exists():
        pytest.skip(f"{cli_name} has no .env file (not yet configured)")

    content = env_file.read_text()
    missing = []
    for var in ("USERNAME", "PASSWORD"):
        # Check for VAR=<non-empty-value> (not just VAR= or missing)
        found = False
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key.strip() == var and val.strip():
                found = True
                break
        if not found:
            missing.append(var)

    assert not missing, (
        f"'{cli_name}/.env' missing browser session credentials: {', '.join(missing)}. "
        f"BROWSER_SESSION credential type requires USERNAME and PASSWORD in .env. "
        f"Fix: Run '{cli_name} auth login' or add {' and '.join(missing)} to .env manually."
    )


# ==================== Auth Test Command (Browser CLIs) ====================


def test_auth_test_command_exists(cli_name, cli_dir, help_cache, test_config, command_filter):
    """AI Review: auth test command exists for API credential verification."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)
    if _config_declares_no_credential_types(cli_dir, cli_name):
        pytest.skip(f"{cli_name} declares no credential types")

    help_text = help_cache("auth")
    assert _help_has_command(help_text, "test"), (
        f"'{cli_name} auth' missing 'test' command. "
        f"Fix: Override test_connection() in Config to make a lightweight API call."
    )


def test_auth_test_exists(cli_name, cli_dir, help_cache, test_config, is_browser_cli, command_filter):
    """Browser CLIs: auth test command exists for browser-based auth verification."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    if not is_browser_cli:
        pytest.skip(f"{cli_name} is not a browser automation CLI")

    help_text = help_cache("auth")
    assert _help_has_command(help_text, "test"), (
        f"'{cli_name} auth' missing 'test' command. "
        f"Fix: Add test command to auth group that launches browser and verifies session."
    )


def test_auth_test_has_table_flag(cli_name, cli_dir, help_cache, test_config, is_browser_cli, command_filter):
    """Browser CLIs: auth test has --table/-t flag."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    if not is_browser_cli:
        pytest.skip(f"{cli_name} is not a browser automation CLI")

    help_text = help_cache("auth test")
    assert "--table" in help_text or "-t" in help_text, (
        f"'{cli_name} auth test' missing --table/-t flag. "
        f"Fix: Add table parameter: "
        f"table: bool = typer.Option(False, '--table', '-t', help='Display as table')"
    )


def test_auth_test_has_verbose_flag(cli_name, cli_dir, help_cache, test_config, is_browser_cli, command_filter):
    """Browser CLIs: auth test has --verbose/-v flag."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    if not is_browser_cli:
        pytest.skip(f"{cli_name} is not a browser automation CLI")

    help_text = help_cache("auth test")
    assert "--verbose" in help_text or "-v" in help_text, (
        f"'{cli_name} auth test' missing --verbose/-v flag. "
        f"Fix: Add verbose parameter: "
        f"verbose: bool = typer.Option(False, '--verbose', '-v', help='Show detailed checks')"
    )


def test_auth_test_has_profile_flag(cli_name, cli_dir, help_cache, test_config, is_browser_cli, command_filter):
    """Browser CLIs: auth test has --profile/-p flag."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    if not is_browser_cli:
        pytest.skip(f"{cli_name} is not a browser automation CLI")

    help_text = help_cache("auth test")
    assert "--profile" in help_text or "-p" in help_text, (
        f"'{cli_name} auth test' missing --profile/-p flag. "
        f"Fix: Add profile parameter: "
        f"profile: str = typer.Option(None, '--profile', '-p', help='Profile name to test')"
    )


def test_auth_test_has_credentials_saved(cli_executable, cli_name, cli_dir, help_cache, test_config, command_filter, is_browser_cli):
    """auth test profiles must emit credential_types blocks with 'credentials_saved'."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)
    _skip_live_browser_auth(cli_name, is_browser_cli)

    help_text = help_cache("auth")
    if not _help_has_command(help_text, "test"):
        pytest.skip(f"{cli_name} has no auth test command")

    result = run_cli_command(cli_executable, ["auth", "test"])
    if result.returncode != 0:
        pytest.skip(f"{cli_name} auth test returned non-zero (may need auth)")

    valid, data = validate_json_output(result.stdout)
    if not valid:
        pytest.skip(f"{cli_name} auth test did not return valid JSON")

    assert "profiles" in data and data["profiles"], (
        f"'{cli_name} auth test' must return a non-empty 'profiles' array. "
        f"Fix: Update cli-tools-shared so auth test emits the per-profile shape."
    )
    for entry in data["profiles"]:
        cred_types = entry.get("credential_types") or {}
        assert cred_types, (
            f"profile '{entry.get('name')}' has empty credential_types in auth test output."
        )
        for type_key, block in cred_types.items():
            assert "credentials_saved" in block, (
                f"'{cli_name} auth test' profile '{entry.get('name')}' "
                f"credential_types['{type_key}'] missing 'credentials_saved'."
            )
            assert "credentials_configured" not in block, (
                f"'{cli_name} auth test' profile '{entry.get('name')}' contains legacy "
                f"'credentials_configured' in credential_types['{type_key}']. "
                f"Fix: Update cli-tools-shared to latest version."
            )


# ==================== AuthVerifier Integration (Per-CLI Source Checks) ====================
# NOTE: Tests validating cli_tools_shared internals (AuthVerifier source, browser_session field)
# live in _repo/cli-tools-shared/tests/test_auth_verifier.py. Tests here validate each CLI's own code.


def test_no_custom_browser_status_check(cli_name, cli_dir, help_cache, test_config, is_browser_cli, command_filter):
    """No CLI should duplicate browser status checking logic — must delegate to AuthVerifier."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    if not is_browser_cli:
        pytest.skip(f"{cli_name} is not a browser automation CLI")

    pkg_dir = cli_dir / f"{cli_name.replace('-', '_')}_cli"
    if not pkg_dir.exists():
        pytest.skip(f"{cli_name} package directory not found")

    # Patterns that indicate duplicated browser status checking
    forbidden_patterns = [
        (r"def\s+_check_browser_status\b", "Duplicated _check_browser_status function"),
        (r"def\s+check_browser_session\b", "Custom check_browser_session function"),
        (r"def\s+_get_browser_status\b", "Custom _get_browser_status function"),
    ]

    violations = []
    # Check all .py files except browser.py (which legitimately defines auth hooks)
    excluded = {"browser.py", "config.py"}
    for py_file in pkg_dir.rglob("*.py"):
        if py_file.name in excluded or "__pycache__" in py_file.parts:
            continue
        lines = py_file.read_text().splitlines()
        rel_path = py_file.relative_to(cli_dir)
        for line_num, line in enumerate(lines, start=1):
            for pattern, description in forbidden_patterns:
                if re.search(pattern, line):
                    violations.append((str(rel_path), line_num, description))

    assert not violations, (
        f"'{cli_name}' duplicates browser status checking logic that should be handled by "
        f"AuthVerifier in cli_tools_shared.\n"
        f"Violations:\n"
        + "\n".join(f"  {f}:{ln} — {desc}" for f, ln, desc in violations)
        + "\n\nFix: Remove custom browser status functions. Auth status and test commands "
        "use AuthVerifier which handles browser session checks via config.get_browser()."
    )


def test_browser_session_has_live_auth_check_url(cli_name, cli_dir, help_cache, test_config, command_filter):
    """Browser-session CLIs must declare a real AUTH_CHECK_URL for live auth status."""
    skip_reason = _should_skip_auth(cli_name, help_cache, test_config, command_filter)
    if skip_reason:
        pytest.skip(skip_reason)

    if not _has_browser_session_type(cli_dir, cli_name):
        pytest.skip(f"{cli_name} does not use BROWSER_SESSION credential type")

    cli_pkg = cli_dir / f"{cli_name.replace('-', '_')}_cli"
    browser_file = cli_pkg / "browser.py"
    if not browser_file.exists():
        pytest.skip(f"{cli_name} has no browser.py")

    import ast

    tree = ast.parse(browser_file.read_text())
    values = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "AUTH_CHECK_URL":
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    values.append(node.value.value)

    assert values and values[-1].strip(), (
        f"'{cli_name}/browser.py' leaves AUTH_CHECK_URL empty. "
        f"Fix: set AUTH_CHECK_URL to a page that proves the saved browser session is still live."
    )
