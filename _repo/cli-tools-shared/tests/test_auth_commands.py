from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

import cli_tools_shared.config as config_module
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.credentials import CredentialType


_SENSITIVE_TEST_FIELDS = {
    "API_KEY",
    "PERSONAL_ACCESS_TOKEN",
    "CLIENT_SECRET",
    "ACCESS_TOKEN",
    "REFRESH_TOKEN",
    "PASSWORD",
    "AZURE_CLIENT_SECRET",
    "M365_SDK_CLIENT_SECRET",
    "DIRECTLINE_SECRET",
}


def _test_secret_name(tool_name: str, profile_name: str, field_name: str) -> str:
    field_part = field_name.lower().replace("_", "-")
    if profile_name == "default":
        return f"{tool_name}-{field_part}"
    return f"{tool_name}-{profile_name}-{field_part}"


def _canonicalize_secret_profile_body(
    tool_name: str,
    profile_name: str,
    body: str,
) -> str:
    lines = []
    for line in body.splitlines():
        if "=" not in line:
            lines.append(line)
            continue
        key, value = line.split("=", 1)
        clean_value = value.strip().strip("'\"")
        if (
            key in _SENSITIVE_TEST_FIELDS
            and clean_value
            and not clean_value.startswith("secret://")
        ):
            secret_name = _test_secret_name(tool_name, profile_name, key)
            config_module._run_secret_manager(
                "set",
                secret_name,
                secret_value=clean_value,
            )
            lines.append(f"{key}='secret://{secret_name}'")
            continue
        lines.append(line)
    return "\n".join(lines) + ("\n" if body.endswith("\n") else "")


def _make_config(browser: MagicMock, profile_path: Path):
    config = MagicMock()
    config.CREDENTIAL_TYPES = [CredentialType.CUSTOM, CredentialType.BROWSER_SESSION]
    config.AUTH_EXTRA_PROMPTS = []
    config.OAUTH_AUTH_URL = ""
    config.OAUTH_TOKEN_URL = ""
    config.get_browser.return_value = browser
    # Pretend a profile already exists so the bootstrap helper is a no-op.
    config.list_profile_paths.return_value = [profile_path]
    config.profile_name_for_path.side_effect = lambda p: p.parent.name
    config.profile_path_for.side_effect = lambda name: profile_path
    config.profile_data_dir_name.return_value = "tool"
    return config


def test_single_credential_type_help_does_not_register_credential_type_option():
    config = MagicMock()
    config.CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    config.AUTH_EXTRA_PROMPTS = []
    config.OAUTH_AUTH_URL = ""
    config.OAUTH_TOKEN_URL = ""
    config.get_browser.return_value = MagicMock()

    app = create_auth_app(lambda profile=None: config, tool_name="tool")
    runner = CliRunner()

    login = runner.invoke(app, ["login", "--help"])
    invalid = runner.invoke(app, ["login", "--credential-type", "browser_session"])

    assert login.exit_code == 0, login.output
    assert "--credential-type" not in login.output
    assert invalid.exit_code == 2, invalid.output
    assert "No such option" in invalid.output


def test_browser_session_login_skips_live_probe_when_no_session_on_disk(tmp_path):
    """No on-disk session → nothing to live-verify → open browser to log in."""
    browser = MagicMock()
    browser.login.return_value = {"success": True, "message": "ok"}
    browser.close.return_value = None

    profile_path = tmp_path / "default" / ".env"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text("IS_DEFAULT_PROFILE=1\n")

    config = _make_config(browser, profile_path)
    config.has_saved_session.return_value = False
    app = create_auth_app(lambda profile=None: config, tool_name="tool")

    result = CliRunner().invoke(app, ["login", "--credential-type", "browser_session"])

    assert result.exit_code == 0, result.output
    config.has_saved_session.assert_called_once_with()
    browser.is_authenticated.assert_not_called()
    browser.login.assert_called_once_with(force=False)
    browser.close.assert_called_once_with()


def test_browser_session_login_live_verifies_before_claiming_already_authenticated(tmp_path):
    """Saved session on disk → live-verify before short-circuiting.

    ``auth login`` previously claimed "Already authenticated" based on
    ``config.has_saved_session()`` alone, even when cookies were expired or
    revoked server-side. The user directive: never claim
    already-authenticated without a live round-trip.
    """
    browser = MagicMock()
    browser.is_authenticated.return_value = True
    browser.login.return_value = {"success": True, "message": "ok"}
    browser.close.return_value = None

    profile_path = tmp_path / "default" / ".env"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text("IS_DEFAULT_PROFILE=1\n")

    config = _make_config(browser, profile_path)
    config.has_saved_session.return_value = True
    app = create_auth_app(lambda profile=None: config, tool_name="tool")

    result = CliRunner().invoke(app, ["login", "--credential-type", "browser_session"])

    assert result.exit_code == 0, result.output
    config.has_saved_session.assert_called_once_with()
    browser.is_authenticated.assert_called_once_with()
    browser.login.assert_not_called()  # short-circuit when live check passes
    browser.close.assert_called_once_with()
    assert "Already authenticated" in result.output


def test_browser_session_login_falls_through_when_live_check_fails(tmp_path):
    """Saved session on disk but live check fails → run interactive login.

    This is the bug the user hit: stale cookies on disk,
    ``config.has_saved_session()`` returns True, but the session is
    actually dead. ``auth login`` must NOT short-circuit — it must
    proceed to the interactive login flow.
    """
    browser = MagicMock()
    browser.is_authenticated.return_value = False  # live check says dead
    browser.login.return_value = {"success": True, "message": "ok"}
    browser.close.return_value = None

    profile_path = tmp_path / "default" / ".env"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text("IS_DEFAULT_PROFILE=1\n")

    config = _make_config(browser, profile_path)
    config.has_saved_session.return_value = True
    app = create_auth_app(lambda profile=None: config, tool_name="tool")

    result = CliRunner().invoke(app, ["login", "--credential-type", "browser_session"])

    assert result.exit_code == 0, result.output
    config.has_saved_session.assert_called_once_with()
    browser.is_authenticated.assert_called_once_with()
    # Live check failed -> must force=True so inner authenticate() clears
    # the stale session instead of short-circuiting on has_saved_session().
    browser.login.assert_called_once_with(force=True)
    browser.close.assert_called_once_with()
    assert "Already authenticated" not in result.output


def test_browser_session_login_returns_nonzero_when_browser_auth_fails(tmp_path):
    browser = MagicMock()
    browser.login.return_value = {
        "success": False,
        "message": "Browser session is not authenticated after login.",
    }
    browser.close.return_value = None

    profile_path = tmp_path / "default" / ".env"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text("IS_DEFAULT_PROFILE=1\n")

    config = _make_config(browser, profile_path)
    config.has_saved_session.return_value = False
    app = create_auth_app(lambda profile=None: config, tool_name="tool")

    result = CliRunner().invoke(app, ["login", "--credential-type", "browser_session"])

    assert result.exit_code == 1, result.output
    browser.login.assert_called_once_with(force=False)
    browser.close.assert_called_once_with()
    assert "Browser auth failed: Browser session is not authenticated after login." in result.output


def test_logout_clears_browser_session_via_config(tmp_path, monkeypatch):
    from cli_tools_shared.config import BaseConfig

    browser = MagicMock()
    browser.close.return_value = None

    class _Cfg(BaseConfig):
        CREDENTIAL_TYPES = [CredentialType.OAUTH, CredentialType.BROWSER_SESSION]
        OAUTH_TOKEN_EXPIRES = False
        OAUTH_STATIC_REQUIRED_FIELDS = (
            "CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN",
        )

        def get_browser(self):
            return browser

    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    (tool_dir / ".env.example").write_text(
        "IS_DEFAULT_PROFILE=1\n"
        "CLIENT_ID=\nCLIENT_SECRET=\nACCESS_TOKEN=\nREFRESH_TOKEN=\n"
    )

    base_profiles_dir = tmp_path / "data" / "tool" / "authentication_profiles"
    monkeypatch.setattr(
        "cli_tools_shared.config.get_profiles_base_dir",
        lambda name: tmp_path / "data" / name / "authentication_profiles",
    )
    monkeypatch.setattr(
        "cli_tools_shared.profiles.get_profiles_base_dir",
        lambda name: tmp_path / "data" / name / "authentication_profiles",
    )

    def get_config(profile=None):
        return _Cfg(tool_dir=tool_dir, profile=profile)

    app = create_auth_app(get_config, tool_name="tool")

    _seed_profile(
        base_profiles_dir,
        "smoke-logout",
        is_default=False,
        env_body=(
            "CLIENT_ID=client-id\n"
            "CLIENT_SECRET=client-secret\n"
            "ACCESS_TOKEN=access-token\n"
            "REFRESH_TOKEN=refresh-token\n"
        ),
    )
    cookies = (
        base_profiles_dir
        / "smoke-logout"
        / "browser-data"
        / "chromium-profile"
        / "Default"
        / "Cookies"
    )
    cookies.parent.mkdir(parents=True, exist_ok=True)
    cookies.write_text("sqlite-stub")

    result = CliRunner().invoke(app, ["logout", "--profile", "smoke-logout"])

    assert result.exit_code == 0, result.output
    browser.close.assert_called_once_with()
    browser.clear_session.assert_not_called()

    config = get_config(profile="smoke-logout")
    assert config.has_saved_session() is False
    assert config._get("CLIENT_ID") in (None, "")
    assert config._get("CLIENT_SECRET") in (None, "")
    assert config._get("ACCESS_TOKEN") in (None, "")
    assert config._get("REFRESH_TOKEN") in (None, "")


def test_refresh_command_hidden_without_oauth_token_url(tmp_path):
    """Browser/API CLIs without OAuth token support must not expose refresh."""
    browser = MagicMock()
    browser.close.return_value = None

    profile_path = tmp_path / "default" / ".env"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text("IS_DEFAULT_PROFILE=1\n")

    config = _make_config(browser, profile_path)
    app = create_auth_app(lambda profile=None: config, tool_name="tool")

    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0, result.output
    assert "refresh" not in result.output


def test_login_bootstraps_default_profile_when_none_exist(tmp_path, monkeypatch):
    """Fresh-install scenario: no env files exist; ``auth login`` must create
    a ``default`` profile, mark it default, and proceed with the login flow.
    """
    from cli_tools_shared.config import BaseConfig

    class _Cfg(BaseConfig):
        CREDENTIAL_TYPES = [CredentialType.API_KEY]

    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    (tool_dir / ".env.example").write_text("API_KEY=\nIS_DEFAULT_PROFILE=1\n")

    monkeypatch.setenv("CLI_TOOL_DATA_HOME", str(tmp_path / "data"))

    # Patch get_profiles_base_dir to use isolated path
    monkeypatch.setattr(
        "cli_tools_shared.config.get_profiles_base_dir",
        lambda name: tmp_path / "data" / name / "authentication_profiles",
    )
    monkeypatch.setattr(
        "cli_tools_shared.profiles.get_profiles_base_dir",
        lambda name: tmp_path / "data" / name / "authentication_profiles",
    )

    def get_config(profile=None):
        cfg = _Cfg(tool_dir=tool_dir, profile=profile)
        return cfg

    app = create_auth_app(get_config, tool_name="tool")

    # Provide API_KEY via prompt
    result = CliRunner().invoke(app, ["login"], input="test-key\n")

    assert result.exit_code == 0, result.output
    profile_dir = tmp_path / "data" / "tool" / "authentication_profiles" / "default"
    env_file = profile_dir / ".env"
    assert env_file.exists(), f"Expected default profile env file at {env_file}"
    content = env_file.read_text()
    assert "IS_DEFAULT_PROFILE=1" in content
    assert "API_KEY='secret://tool-api-key'" in content
    assert "API_KEY=" in content


def test_base_config_initializes_default_profile_when_none_exist(tmp_path, monkeypatch):
    from cli_tools_shared.config import BaseConfig

    class _Cfg(BaseConfig):
        CREDENTIAL_TYPES = [CredentialType.API_KEY]

    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    (tool_dir / ".env.example").write_text("API_KEY=\nIS_DEFAULT_PROFILE=0\n")

    monkeypatch.setattr(
        "cli_tools_shared.config.get_profiles_base_dir",
        lambda name: tmp_path / "data" / name / "authentication_profiles",
    )

    config = _Cfg(tool_dir=tool_dir)

    env_file = tmp_path / "data" / "tool" / "authentication_profiles" / "default" / ".env"
    assert config.env_file_path == env_file
    assert env_file.exists()
    assert "IS_DEFAULT_PROFILE=1" in env_file.read_text()


def test_login_bootstraps_named_profile_when_missing(tmp_path, monkeypatch):
    """User passes ``--profile staging`` for a profile that doesn't exist.
    The login flow must create it. It should NOT clobber an existing default.
    """
    from cli_tools_shared.config import BaseConfig

    class _Cfg(BaseConfig):
        CREDENTIAL_TYPES = [CredentialType.API_KEY]

    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    (tool_dir / ".env.example").write_text("API_KEY=\nIS_DEFAULT_PROFILE=1\n")

    base_profiles_dir = tmp_path / "data" / "tool" / "authentication_profiles"
    monkeypatch.setattr(
        "cli_tools_shared.config.get_profiles_base_dir",
        lambda name: tmp_path / "data" / name / "authentication_profiles",
    )
    monkeypatch.setattr(
        "cli_tools_shared.profiles.get_profiles_base_dir",
        lambda name: tmp_path / "data" / name / "authentication_profiles",
    )

    # Pre-create a "default" profile so the new "staging" should NOT become default
    default_dir = base_profiles_dir / "default"
    default_dir.mkdir(parents=True)
    (default_dir / ".env").write_text(
        "IS_DEFAULT_PROFILE=1\n"
        + _canonicalize_secret_profile_body(
            "tool",
            "default",
            "API_KEY=existing\n",
        )
    )

    def get_config(profile=None):
        return _Cfg(tool_dir=tool_dir, profile=profile)

    app = create_auth_app(get_config, tool_name="tool")
    result = CliRunner().invoke(app, ["login", "--profile", "staging"], input="staging-key\n")

    assert result.exit_code == 0, result.output
    staging_env = base_profiles_dir / "staging" / ".env"
    assert staging_env.exists()
    staging_content = staging_env.read_text()
    assert "API_KEY='secret://tool-staging-api-key'" in staging_content
    assert "IS_DEFAULT_PROFILE=0" in staging_content
    # Default unchanged
    default_content = (default_dir / ".env").read_text()
    assert "IS_DEFAULT_PROFILE=1" in default_content
    assert "API_KEY='secret://tool-api-key'" in default_content


def test_login_does_not_recreate_existing_profile(tmp_path, monkeypatch):
    """If the requested profile already exists, bootstrap is a no-op."""
    from cli_tools_shared.config import BaseConfig

    class _Cfg(BaseConfig):
        CREDENTIAL_TYPES = [CredentialType.API_KEY]

    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    (tool_dir / ".env.example").write_text("API_KEY=\nIS_DEFAULT_PROFILE=1\n")

    base_profiles_dir = tmp_path / "data" / "tool" / "authentication_profiles"
    monkeypatch.setattr(
        "cli_tools_shared.config.get_profiles_base_dir",
        lambda name: tmp_path / "data" / name / "authentication_profiles",
    )
    monkeypatch.setattr(
        "cli_tools_shared.profiles.get_profiles_base_dir",
        lambda name: tmp_path / "data" / name / "authentication_profiles",
    )

    default_dir = base_profiles_dir / "default"
    default_dir.mkdir(parents=True)
    (default_dir / ".env").write_text(
        "IS_DEFAULT_PROFILE=1\n"
        + _canonicalize_secret_profile_body(
            "tool",
            "default",
            "API_KEY=preserved\n",
        )
    )

    def get_config(profile=None):
        return _Cfg(tool_dir=tool_dir, profile=profile)

    app = create_auth_app(get_config, tool_name="tool")
    # API_KEY is already set, so no prompts — login should succeed silently
    result = CliRunner().invoke(app, ["login"], input="")

    assert result.exit_code == 0, result.output
    # Profile preserved exactly
    content = (default_dir / ".env").read_text()
    assert "API_KEY='secret://tool-api-key'" in content


def test_force_oauth_authorization_code_reprompts_setup_fields(tmp_path, monkeypatch):
    """--force must clear OAuth app fields before opening the auth handler."""
    from cli_tools_shared.config import BaseConfig

    class _Cfg(BaseConfig):
        CREDENTIAL_TYPES = [CredentialType.OAUTH_AUTHORIZATION_CODE]

    for name in (
        "CLIENT_ID",
        "CLIENT_SECRET",
        "REDIRECT_URI",
        "ACCESS_TOKEN",
        "REFRESH_TOKEN",
        "TOKEN_EXPIRES_AT",
    ):
        monkeypatch.delenv(name, raising=False)

    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    (tool_dir / ".env.example").write_text(
        "CLIENT_ID=\nCLIENT_SECRET=\nREDIRECT_URI=\nACCESS_TOKEN=\n"
        "REFRESH_TOKEN=\nTOKEN_EXPIRES_AT=\nIS_DEFAULT_PROFILE=1\n"
    )

    base_profiles_dir = tmp_path / "data" / "tool" / "authentication_profiles"
    monkeypatch.setattr(
        "cli_tools_shared.config.get_profiles_base_dir",
        lambda name: tmp_path / "data" / name / "authentication_profiles",
    )
    monkeypatch.setattr(
        "cli_tools_shared.profiles.get_profiles_base_dir",
        lambda name: tmp_path / "data" / name / "authentication_profiles",
    )

    default_dir = base_profiles_dir / "default"
    default_dir.mkdir(parents=True)
    (default_dir / ".env").write_text(
        "IS_DEFAULT_PROFILE=1\n"
        + _canonicalize_secret_profile_body(
            "tool",
            "default",
            "CLIENT_ID=old-client\n"
            "CLIENT_SECRET=old-secret\n"
            "REDIRECT_URI=https://old.example/callback\n"
            "ACCESS_TOKEN=old-access-token\n"
            "REFRESH_TOKEN=old-refresh-token\n"
            "TOKEN_EXPIRES_AT=1\n",
        )
    )

    handler_values = {}

    def get_config(profile=None):
        return _Cfg(tool_dir=tool_dir, profile=profile)

    def login_handler(config, force):
        handler_values.update(
            {
                "force": force,
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "redirect_uri": config.redirect_uri,
                "access_token": config.access_token,
            }
        )

    app = create_auth_app(get_config, tool_name="tool", login_handler=login_handler)
    result = CliRunner().invoke(
        app,
        ["login", "--force"],
        input="new-client\nnew-secret\nhttps://new.example/callback\n",
    )

    assert result.exit_code == 0, result.output
    assert handler_values == {
        "force": True,
        "client_id": "new-client",
        "client_secret": "new-secret",
        "redirect_uri": "https://new.example/callback",
        "access_token": None,
    }

    content = (default_dir / ".env").read_text()
    assert "CLIENT_ID='new-client'" in content
    assert "CLIENT_SECRET='secret://tool-client-secret'" in content
    assert "REDIRECT_URI='https://new.example/callback'" in content
    assert "ACCESS_TOKEN=''" in content
    assert "old-client" not in content
    assert "old-secret" not in content


# ============================================================================
# auth status canonical schema (end-to-end via CliRunner)
# ============================================================================
# These tests exercise `create_auth_app` end-to-end, invoke `status`,
# parse stdout, and assert the canonical `{profiles: [...]}` shape with
# the strict per-credential-type contract described in auth-standards.md.

import json

VALID_CRED_TYPE_KEYS = {
    "custom",
    "api_key",
    "oauth",
    "oauth_authorization_code",
    "personal_access_token",
    "username_password",
    "browser_session",
}


def _assert_canonical_status_shape(stdout: str) -> dict:
    """Parse stdout as a single JSON document and assert canonical shape.

    Mirrors the jq schema check in test-cli-tool.sh exactly so the
    fleet-level and unit-level contracts cannot drift.
    """
    # 1. stdout must be a single valid JSON document (no prose mixed in).
    data = json.loads(stdout)

    # 2. Top-level must be {"profiles": [...]} with profiles as a list.
    assert isinstance(data, dict), "auth status output must be a JSON object"
    assert set(data.keys()) == {"profiles"}, (
        f"auth status top-level keys must be exactly {{'profiles'}}, got {sorted(data.keys())}"
    )
    assert "profiles" in data, "auth status output must have a 'profiles' key"
    assert isinstance(data["profiles"], list), "'profiles' must be a list"
    assert data["profiles"], "'profiles' must not be empty"

    # 3. Each profile must have the required fields with the right types.
    for profile in data["profiles"]:
        assert isinstance(profile, dict), "profile entry must be an object"
        assert isinstance(profile.get("name"), str) and profile["name"], (
            f"profile must have non-empty string 'name': {profile!r}"
        )
        assert isinstance(profile.get("is_default"), bool), (
            f"profile '{profile.get('name')}' must have boolean 'is_default'"
        )
        assert isinstance(profile.get("authenticated"), bool), (
            f"profile '{profile.get('name')}' must have boolean 'authenticated'"
        )
        cred_types = profile.get("credential_types")
        assert isinstance(cred_types, dict), (
            f"profile '{profile.get('name')}' must have a 'credential_types' object"
        )

        # 4. credential_types keys must be valid CredentialType.value strings.
        for type_key, block in cred_types.items():
            assert type_key in VALID_CRED_TYPE_KEYS, (
                f"profile '{profile['name']}' has invalid credential_type key "
                f"'{type_key}' (must be one of {sorted(VALID_CRED_TYPE_KEYS)})"
            )
            assert isinstance(block, dict), (
                f"credential_types[{type_key}] must be an object"
            )

            # 5. Each entry must have credentials_saved (bool), authenticated (bool).
            assert isinstance(block.get("credentials_saved"), bool), (
                f"credential_types[{type_key}].credentials_saved must be a boolean"
            )
            assert isinstance(block.get("authenticated"), bool), (
                f"credential_types[{type_key}].authenticated must be a boolean"
            )

            # 6. api_test (when present) must be "passed" or start with "failed:".
            if "api_test" in block:
                val = block["api_test"]
                assert isinstance(val, str), (
                    f"credential_types[{type_key}].api_test must be a string"
                )
                assert val == "passed" or val.startswith("failed:"), (
                    f"credential_types[{type_key}].api_test must be \"passed\" "
                    f"or start with \"failed:\" (got: {val!r})"
                )

    # 7. Exactly one profile has is_default=True (when the CLI has profiles).
    defaults = [p for p in data["profiles"] if p["is_default"]]
    assert len(defaults) <= 1, (
        f"At most one profile may have is_default=True, found {len(defaults)}"
    )

    return data


def _make_auth_app_in_tmp(
    tmp_path,
    monkeypatch,
    cred_types,
    *,
    env_seed: str = "",
    test_connection_result=None,
    browser=None,
):
    """Build a create_auth_app instance backed by a temp-dir tool_dir.

    Returns (app, get_config_fn, tool_dir, base_profiles_dir).
    """
    from cli_tools_shared.config import BaseConfig

    class _Cfg(BaseConfig):
        CREDENTIAL_TYPES = cred_types

        def test_connection(self):
            return test_connection_result

        def get_browser(self):
            return browser

    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    # Provide a usable .env.example so bootstrap copies the right shape.
    example_lines = ["IS_DEFAULT_PROFILE=1"]
    if env_seed:
        example_lines.append(env_seed)
    (tool_dir / ".env.example").write_text("\n".join(example_lines) + "\n")

    base_profiles_dir = tmp_path / "data" / "tool" / "authentication_profiles"
    monkeypatch.setattr(
        "cli_tools_shared.config.get_profiles_base_dir",
        lambda name: tmp_path / "data" / name / "authentication_profiles",
    )
    monkeypatch.setattr(
        "cli_tools_shared.profiles.get_profiles_base_dir",
        lambda name: tmp_path / "data" / name / "authentication_profiles",
    )

    def get_config(profile=None):
        return _Cfg(tool_dir=tool_dir, profile=profile)

    app = create_auth_app(get_config, tool_name="tool")
    return app, get_config, tool_dir, base_profiles_dir


def _seed_profile(base_profiles_dir, name, *, is_default, env_body):
    """Create a profile env file on disk with the given body."""
    pdir = base_profiles_dir / name
    pdir.mkdir(parents=True, exist_ok=True)
    tool_name = base_profiles_dir.parent.name
    body = (
        f"IS_DEFAULT_PROFILE={1 if is_default else 0}\n"
        + _canonicalize_secret_profile_body(tool_name, name, env_body)
    )
    (pdir / ".env").write_text(body)


def test_auth_status_canonical_shape_no_credentials(tmp_path, monkeypatch):
    """Single profile, no credentials saved → status emits canonical shape with
    authenticated=False and credentials_saved=False under the configured type."""
    app, _get_config, _tool_dir, base_profiles_dir = _make_auth_app_in_tmp(
        tmp_path, monkeypatch, [CredentialType.API_KEY]
    )
    _seed_profile(base_profiles_dir, "default", is_default=True, env_body="API_KEY=\n")

    result = CliRunner().invoke(app, ["status"])
    assert result.exit_code == 0, result.output

    data = _assert_canonical_status_shape(result.stdout)
    assert len(data["profiles"]) == 1
    profile = data["profiles"][0]
    assert profile["name"] == "default"
    assert profile["is_default"] is True
    assert profile["authenticated"] is False
    block = profile["credential_types"]["api_key"]
    assert block["credentials_saved"] is False
    assert block["authenticated"] is False


def test_auth_status_canonical_shape_valid_credentials_pass(tmp_path, monkeypatch):
    """Single profile, valid credentials, test_connection→passed →
    authenticated=True and api_test='passed' under the configured type."""
    app, _get_config, _tool_dir, base_profiles_dir = _make_auth_app_in_tmp(
        tmp_path,
        monkeypatch,
        [CredentialType.API_KEY],
        test_connection_result={"api_test": "passed"},
    )
    _seed_profile(
        base_profiles_dir,
        "default",
        is_default=True,
        env_body="API_KEY=secret-key-abc-123\n",
    )

    result = CliRunner().invoke(app, ["status"])
    assert result.exit_code == 0, result.output

    data = _assert_canonical_status_shape(result.stdout)
    assert len(data["profiles"]) == 1
    profile = data["profiles"][0]
    assert profile["authenticated"] is True
    block = profile["credential_types"]["api_key"]
    assert block["credentials_saved"] is True
    assert block["authenticated"] is True
    assert block["api_test"] == "passed"


def test_auth_status_canonical_shape_failed_test_connection(tmp_path, monkeypatch):
    """Single profile, valid credentials, test_connection→failed → api_test
    must start with 'failed:' and authenticated=False."""
    app, _get_config, _tool_dir, base_profiles_dir = _make_auth_app_in_tmp(
        tmp_path,
        monkeypatch,
        [CredentialType.API_KEY],
        test_connection_result={"api_test": "failed: unauthorized"},
    )
    _seed_profile(
        base_profiles_dir,
        "default",
        is_default=True,
        env_body="API_KEY=bogus-key-with-enough-length\n",
    )

    result = CliRunner().invoke(app, ["status"])
    assert result.exit_code == 0, result.output

    data = _assert_canonical_status_shape(result.stdout)
    profile = data["profiles"][0]
    assert profile["authenticated"] is False
    block = profile["credential_types"]["api_key"]
    assert block["credentials_saved"] is True
    assert block["authenticated"] is False
    assert block["api_test"].startswith("failed:")


def test_auth_status_oauth_authorization_code_uses_live_test_connection(tmp_path, monkeypatch):
    """OAuth auth status must merge live test_connection() results, not only token expiry state."""
    app, _get_config, _tool_dir, base_profiles_dir = _make_auth_app_in_tmp(
        tmp_path,
        monkeypatch,
        [CredentialType.OAUTH_AUTHORIZATION_CODE],
        test_connection_result={"api_test": "passed", "scopes": ["w_member_social"]},
        env_seed="CLIENT_ID=\nCLIENT_SECRET=\nACCESS_TOKEN=\nREDIRECT_URI=\nTOKEN_EXPIRES_AT=\n",
    )
    _seed_profile(
        base_profiles_dir,
        "default",
        is_default=True,
        env_body=(
            "CLIENT_ID=client-id\n"
            "CLIENT_SECRET=client-secret\n"
            "ACCESS_TOKEN=token-value\n"
            "REDIRECT_URI=http://localhost/callback\n"
            "TOKEN_EXPIRES_AT=32503680000\n"
        ),
    )

    result = CliRunner().invoke(app, ["status"])
    assert result.exit_code == 0, result.output

    data = _assert_canonical_status_shape(result.stdout)
    block = data["profiles"][0]["credential_types"]["oauth_authorization_code"]
    assert block["authenticated"] is True
    assert block["oauth_status"] == "valid"
    assert block["api_test"] == "passed"
    assert block["scopes"] == ["w_member_social"]


def test_auth_status_canonical_shape_multi_profile(tmp_path, monkeypatch):
    """Multi-profile setup → profiles[] contains all profiles, is_default set
    on exactly one, every entry passes the canonical schema check."""
    app, _get_config, _tool_dir, base_profiles_dir = _make_auth_app_in_tmp(
        tmp_path,
        monkeypatch,
        [CredentialType.API_KEY],
        test_connection_result={"api_test": "passed"},
    )
    _seed_profile(
        base_profiles_dir, "default", is_default=True, env_body="API_KEY=default-key-abc\n"
    )
    _seed_profile(
        base_profiles_dir, "staging", is_default=False, env_body="API_KEY=staging-key-xyz\n"
    )
    _seed_profile(
        base_profiles_dir, "empty", is_default=False, env_body="API_KEY=\n"
    )

    result = CliRunner().invoke(app, ["status"])
    assert result.exit_code == 0, result.output

    data = _assert_canonical_status_shape(result.stdout)
    names = {p["name"]: p for p in data["profiles"]}
    assert set(names) == {"default", "staging", "empty"}, (
        f"Expected all three profiles in profiles[], got {set(names)}"
    )
    # Exactly one default.
    defaults = [p for p in data["profiles"] if p["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["name"] == "default"
    # Non-default with creds still authenticates.
    assert names["staging"]["authenticated"] is True
    # Empty profile authenticated=False.
    assert names["empty"]["authenticated"] is False
    assert names["empty"]["credential_types"]["api_key"]["credentials_saved"] is False


def test_auth_status_stdout_is_pure_json(tmp_path, monkeypatch):
    """stdout MUST be a single JSON document — no prose mixed in.

    Regression guard for the monarch stream-separation bug. ``print_info``,
    ``print_success`` and similar helpers must route to stderr; only the
    structured payload may reach stdout.
    """
    app, _get_config, _tool_dir, base_profiles_dir = _make_auth_app_in_tmp(
        tmp_path,
        monkeypatch,
        [CredentialType.API_KEY],
        test_connection_result={"api_test": "passed"},
    )
    _seed_profile(
        base_profiles_dir, "default", is_default=True, env_body="API_KEY=key-abc-def\n"
    )

    result = CliRunner().invoke(app, ["status"])
    assert result.exit_code == 0, result.output

    stripped = result.stdout.strip()
    assert stripped.startswith("{"), (
        f"auth status stdout must start with '{{' (got prefix: {stripped[:80]!r})"
    )
    assert stripped.endswith("}"), (
        f"auth status stdout must end with '}}' (got suffix: {stripped[-80:]!r})"
    )
    # The parser is the ultimate check — json.loads tolerates no prose.
    json.loads(stripped)


def test_auth_status_canonical_shape_with_browser_session(tmp_path, monkeypatch):
    """Dual-auth (API_KEY + BROWSER_SESSION) emits both credential type blocks."""
    from cli_tools_shared.auth import AuthResult

    browser = MagicMock()
    browser.is_authenticated.return_value = AuthResult(authenticated=True, live_check=True)
    browser.close.return_value = None

    app, _get_config, _tool_dir, base_profiles_dir = _make_auth_app_in_tmp(
        tmp_path,
        monkeypatch,
        [CredentialType.API_KEY, CredentialType.BROWSER_SESSION],
        test_connection_result={"api_test": "passed"},
        browser=browser,
    )
    _seed_profile(
        base_profiles_dir, "default", is_default=True, env_body="API_KEY=key-abc-def\n"
    )
    # Seed the persistent Chromium profile's cookie database so the real
    # ``BaseConfig.has_saved_session()`` reports True.
    cookies = base_profiles_dir / "default" / "browser-data" / "chromium-profile" / "Default" / "Cookies"
    cookies.parent.mkdir(parents=True, exist_ok=True)
    cookies.write_text("sqlite-stub")

    result = CliRunner().invoke(app, ["status"])
    assert result.exit_code == 0, result.output

    data = _assert_canonical_status_shape(result.stdout)
    profile = data["profiles"][0]
    assert set(profile["credential_types"]) == {"api_key", "browser_session"}
    assert profile["credential_types"]["api_key"]["api_test"] == "passed"
    assert profile["credential_types"]["browser_session"]["authenticated"] is True


def test_auth_status_dual_auth_browser_session_is_not_overridden_by_api_test(tmp_path, monkeypatch):
    """Dual-auth status must report browser-session truth independently of OAuth/API failures."""
    from cli_tools_shared.auth import AuthResult
    from cli_tools_shared.config import BaseConfig

    browser = MagicMock()
    browser.is_authenticated.return_value = AuthResult(authenticated=True, live_check=True)
    browser.close.return_value = None

    class _Cfg(BaseConfig):
        CREDENTIAL_TYPES = [CredentialType.OAUTH, CredentialType.BROWSER_SESSION]
        OAUTH_TOKEN_EXPIRES = False
        OAUTH_STATIC_REQUIRED_FIELDS = (
            "CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN",
        )

        def get_browser(self):
            return browser

    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    (tool_dir / ".env.example").write_text(
        "IS_DEFAULT_PROFILE=1\n"
        "CLIENT_ID=\nCLIENT_SECRET=\nACCESS_TOKEN=\nREFRESH_TOKEN=\n"
    )

    base_profiles_dir = tmp_path / "data" / "tool" / "authentication_profiles"
    monkeypatch.setattr(
        "cli_tools_shared.config.get_profiles_base_dir",
        lambda name: tmp_path / "data" / name / "authentication_profiles",
    )
    monkeypatch.setattr(
        "cli_tools_shared.profiles.get_profiles_base_dir",
        lambda name: tmp_path / "data" / name / "authentication_profiles",
    )

    def get_config(profile=None):
        return _Cfg(tool_dir=tool_dir, profile=profile)

    app = create_auth_app(
        get_config,
        tool_name="tool",
        test_handler=lambda cfg: {"api_test": "failed: oauth credentials invalid"},
    )

    _seed_profile(
        base_profiles_dir,
        "default",
        is_default=True,
        env_body="CLIENT_ID=\nCLIENT_SECRET=\nACCESS_TOKEN=\nREFRESH_TOKEN=\n",
    )
    cookies = (
        base_profiles_dir
        / "default"
        / "browser-data"
        / "chromium-profile"
        / "Default"
        / "Cookies"
    )
    cookies.parent.mkdir(parents=True, exist_ok=True)
    cookies.write_text("sqlite-stub")

    result = CliRunner().invoke(app, ["status"])
    assert result.exit_code == 0, result.output

    data = _assert_canonical_status_shape(result.stdout)
    profile = data["profiles"][0]
    assert profile["authenticated"] is True
    oauth_block = profile["credential_types"]["oauth"]
    browser_block = profile["credential_types"]["browser_session"]
    assert oauth_block["authenticated"] is False
    assert oauth_block["credentials_saved"] is False
    assert browser_block["credentials_saved"] is True
    assert browser_block["browser_session"] is True
    assert browser_block["authenticated"] is True
    assert "api_test" not in browser_block
