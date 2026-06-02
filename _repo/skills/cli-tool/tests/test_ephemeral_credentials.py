"""Ephemeral credentials tests.

Verifies that --force on auth login only clears ephemeral state (tokens,
browser sessions) and never clears static credentials (API keys, PATs,
client IDs, passwords, etc.).

Two categories:
1. Per-CLI structural tests: verify each CLI's config is properly wired
2. Shared package unit tests: verify CredentialType and BaseConfig behavior
"""

import shutil
import tempfile
import subprocess
from pathlib import Path

import pytest

import cli_tools_shared.config as config_module
from cli_tools_shared.credentials import (
    CredentialType,
    combined_ephemeral_fields,
    combined_sensitive_fields,
)
from cli_tools_shared.config import BaseConfig, get_profiles_base_dir


# ==================== Per-CLI Structural Tests ====================


def test_config_has_credential_types_list(cli_name, cli_dir, help_cache, test_config, command_filter):
    """Config.py must define CREDENTIAL_TYPES as a list (not deprecated CREDENTIAL_TYPE)."""
    if command_filter and command_filter not in ("auth", "profiles"):
        pytest.skip(f"Skipping config tests (filtering to '{command_filter}')")

    help_text = help_cache("")
    if " auth " not in help_text and "│ auth" not in help_text:
        pytest.skip(f"{cli_name} has no auth subcommand (auth infrastructure not required)")

    cli_pkg = cli_dir / f"{cli_name.replace('-', '_')}_cli"
    config_file = cli_pkg / "config.py"

    if not config_file.exists():
        pytest.skip(f"{cli_name} config.py not found")

    content = config_file.read_text()

    assert "CREDENTIAL_TYPES" in content, (
        f"'{cli_name}/config.py' missing CREDENTIAL_TYPES class variable. "
        f"Fix: Set CREDENTIAL_TYPES = [CredentialType.API_KEY] (or appropriate types) "
        f"on your BaseConfig subclass. This is required for clear_ephemeral() to know "
        f"which fields are ephemeral vs static."
    )


def test_config_does_not_override_clear_ephemeral(cli_name, cli_dir, test_config, command_filter):
    """CLIs should NOT override clear_ephemeral — the shared package handles it."""
    if command_filter and command_filter not in ("auth",):
        pytest.skip(f"Skipping config tests (filtering to '{command_filter}')")

    cli_pkg = cli_dir / f"{cli_name.replace('-', '_')}_cli"
    config_file = cli_pkg / "config.py"

    if not config_file.exists():
        pytest.skip(f"{cli_name} config.py not found")

    content = config_file.read_text()

    assert "def clear_ephemeral(" not in content, (
        f"'{cli_name}/config.py' overrides clear_ephemeral(). "
        f"Fix: Remove the override. BaseConfig.clear_ephemeral() handles ephemeral "
        f"field clearing based on CREDENTIAL_TYPES. Custom overrides may break the "
        f"contract that --force never clears static credentials."
    )


def test_auth_no_clear_credentials_on_force(cli_name, cli_dir, test_config, command_filter):
    """Auth commands must NOT call clear_credentials() for --force flows.

    clear_credentials() wipes ALL fields including static ones (API keys, etc.).
    --force should only use clear_ephemeral() which preserves static credentials.
    """
    if command_filter and command_filter not in ("auth",):
        pytest.skip(f"Skipping auth tests (filtering to '{command_filter}')")

    cli_pkg = cli_dir / f"{cli_name.replace('-', '_')}_cli"

    # Check if CLI uses the shared create_auth_app (handles force correctly)
    main_file = cli_pkg / "main.py"
    if main_file.exists() and "create_auth_app" in main_file.read_text():
        return  # Pass — shared package handles force correctly

    auth_file = cli_pkg / "commands" / "auth.py"
    if auth_file.exists() and "create_auth_app" in auth_file.read_text():
        return  # Pass — shared package handles force correctly

    # Custom auth: verify no clear_credentials in force paths
    if auth_file.exists():
        content = auth_file.read_text()
        if "clear_credentials" in content and "force" in content:
            pytest.fail(
                f"'{cli_name}' commands/auth.py calls clear_credentials() with --force logic. "
                f"Fix: Use config.clear_ephemeral() instead of config.clear_credentials() "
                f"in --force flows. clear_credentials() wipes static credentials (API keys, "
                f"passwords) which should never be cleared by --force. "
                f"Better yet, switch to create_auth_app() from cli_tools_shared."
            )
    else:
        # No auth.py and no create_auth_app — CLI has auth but no implementation
        help_text = ""
        try:
            import subprocess
            result = subprocess.run(
                [cli_name, "--help"], capture_output=True, text=True, timeout=10
            )
            help_text = result.stdout
        except Exception:
            pass
        if " auth " in help_text or "│ auth" in help_text:
            pytest.fail(
                f"'{cli_name}' has auth commands but no create_auth_app() or commands/auth.py. "
                f"Fix: Use create_auth_app() from cli_tools_shared in main.py."
            )


# ==================== Shared Package Unit Tests ====================
# These test the cli_tools_shared package directly.


class TestCredentialTypeEphemeralFields:
    """Verify CredentialType.ephemeral_fields returns correct values."""

    def test_api_key_has_no_ephemeral_fields(self):
        """API_KEY: no fields are ephemeral (the key itself is static)."""
        assert CredentialType.API_KEY.ephemeral_fields == []

    def test_personal_access_token_has_no_ephemeral_fields(self):
        """PERSONAL_ACCESS_TOKEN: PATs are static."""
        assert CredentialType.PERSONAL_ACCESS_TOKEN.ephemeral_fields == []

    def test_oauth_ephemeral_fields_are_tokens(self):
        """OAUTH: tokens are ephemeral, client ID/secret are not."""
        ephemeral = CredentialType.OAUTH.ephemeral_fields
        assert "ACCESS_TOKEN" in ephemeral
        assert "REFRESH_TOKEN" in ephemeral
        assert "TOKEN_EXPIRES_AT" in ephemeral
        assert "CLIENT_ID" not in ephemeral
        assert "CLIENT_SECRET" not in ephemeral

    def test_oauth_auth_code_ephemeral_fields_are_tokens(self):
        """OAUTH_AUTHORIZATION_CODE: tokens ephemeral, setup creds static."""
        ephemeral = CredentialType.OAUTH_AUTHORIZATION_CODE.ephemeral_fields
        assert "ACCESS_TOKEN" in ephemeral
        assert "REFRESH_TOKEN" in ephemeral
        assert "TOKEN_EXPIRES_AT" in ephemeral
        assert "CLIENT_ID" not in ephemeral
        assert "CLIENT_SECRET" not in ephemeral
        assert "REDIRECT_URI" not in ephemeral

    def test_username_password_has_no_ephemeral_fields(self):
        """USERNAME_PASSWORD: credentials are static."""
        assert CredentialType.USERNAME_PASSWORD.ephemeral_fields == []

    def test_browser_session_has_no_ephemeral_fields(self):
        """BROWSER_SESSION: session data is cleared separately via clear_session()."""
        assert CredentialType.BROWSER_SESSION.ephemeral_fields == []

    def test_ephemeral_fields_subset_of_all_fields(self):
        """Ephemeral fields must be a subset of all_fields for every type."""
        for ct in CredentialType:
            ephemeral = set(ct.ephemeral_fields)
            all_f = set(ct.all_fields)
            assert ephemeral.issubset(all_f), (
                f"{ct.name}: ephemeral_fields {ephemeral - all_f} not in all_fields"
            )

    def test_ephemeral_fields_disjoint_from_login_prompts(self):
        """Ephemeral fields must NOT overlap with login prompt fields.

        Login prompts ask for static credentials. If ephemeral_fields included
        a login prompt field, --force would clear it and then the user would
        be re-prompted to enter the same static value.
        """
        for ct in CredentialType:
            ephemeral = set(ct.ephemeral_fields)
            prompt_fields = {field for field, _, _ in ct.login_prompts}
            overlap = ephemeral & prompt_fields
            assert not overlap, (
                f"{ct.name}: ephemeral_fields {overlap} overlap with login_prompts. "
                f"These fields would be cleared by --force then immediately re-prompted."
            )


class TestCombinedEphemeralFields:
    """Verify combined_ephemeral_fields helper."""

    def test_combined_deduplicates(self):
        """Multiple credential types with same ephemeral field: deduplicated."""
        result = combined_ephemeral_fields([
            CredentialType.OAUTH,
            CredentialType.OAUTH_AUTHORIZATION_CODE,
        ])
        assert result.count("ACCESS_TOKEN") == 1
        assert result.count("REFRESH_TOKEN") == 1

    def test_combined_empty_for_static_types(self):
        """Types with no ephemeral fields return empty list."""
        result = combined_ephemeral_fields([
            CredentialType.API_KEY,
            CredentialType.USERNAME_PASSWORD,
        ])
        assert result == []

    def test_combined_mixed_types(self):
        """API_KEY + OAUTH: only OAuth tokens are ephemeral."""
        result = combined_ephemeral_fields([
            CredentialType.API_KEY,
            CredentialType.OAUTH,
        ])
        assert "ACCESS_TOKEN" in result
        assert "REFRESH_TOKEN" in result
        assert "API_KEY" not in result


class TestBaseConfigClearEphemeral:
    """Verify BaseConfig.clear_ephemeral() preserves static credentials."""

    def _make_config(self, cred_types, env_vars):
        """Create a BaseConfig subclass with canonical profile placeholders."""
        tmp = tempfile.mkdtemp()
        data_home = Path(tmp) / "share"
        data_home.mkdir()
        tool_dir = Path(tmp) / "exampletool"
        tool_dir.mkdir()

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
        env_path = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
        env_path.parent.mkdir(parents=True, exist_ok=True)
        sensitive_fields = set(combined_sensitive_fields(cred_types))
        secret_store = {}
        lines = []
        for key, value in env_vars.items():
            if key in sensitive_fields and value:
                secret_name = f"{tool_dir.name}-{key.lower().replace('_', '-')}"
                secret_store[secret_name] = value
                lines.append(f"{key}=secret://{secret_name}")
                continue
            lines.append(f"{key}={value}")
        lines.append("ACTIVE=true")
        env_path.write_text("\n".join(lines) + "\n")

        def fake_run_secret_manager(command: str, secret_name: str, *, secret_value=None):
            if command == "get":
                if secret_name not in secret_store:
                    return subprocess.CompletedProcess([], 1, stdout="", stderr="missing")
                return subprocess.CompletedProcess([], 0, stdout=f"{secret_store[secret_name]}\n", stderr="")
            if command == "has":
                return subprocess.CompletedProcess(
                    [],
                    0 if secret_name in secret_store else 1,
                    stdout="",
                    stderr="",
                )
            if command == "set":
                secret_store[secret_name] = secret_value
                return subprocess.CompletedProcess([], 0, stdout="", stderr="")
            if command == "delete":
                existed = secret_name in secret_store
                secret_store.pop(secret_name, None)
                return subprocess.CompletedProcess([], 0 if existed else 1, stdout="", stderr="")
            raise AssertionError(f"Unexpected secret manager command: {command}")

        monkeypatch.setattr(config_module, "_run_secret_manager", fake_run_secret_manager)

        class TestConfig(BaseConfig):
            CREDENTIAL_TYPES = cred_types
            DEFAULT_BASE_URL = "https://test.example.com"

            def __init__(self):
                super().__init__(tool_dir=tool_dir)

        config = TestConfig()
        return config, tmp, monkeypatch

    def test_api_key_preserved_after_clear_ephemeral(self):
        """clear_ephemeral() on API_KEY type preserves the API key."""
        config, tmp, monkeypatch = self._make_config(
            [CredentialType.API_KEY],
            {"API_KEY": "my-secret-key-1234"},
        )
        assert config.api_key == "my-secret-key-1234"
        config.clear_ephemeral()
        assert config.api_key == "my-secret-key-1234", (
            "clear_ephemeral() must NOT clear API_KEY"
        )
        shutil.rmtree(tmp)
        monkeypatch.undo()

    def test_oauth_tokens_cleared_after_clear_ephemeral(self):
        """clear_ephemeral() on OAUTH clears tokens but keeps client creds."""
        config, tmp, monkeypatch = self._make_config(
            [CredentialType.OAUTH],
            {
                "CLIENT_ID": "my-client-id",
                "CLIENT_SECRET": "my-client-secret",
                "ACCESS_TOKEN": "old-token",
                "REFRESH_TOKEN": "old-refresh",
                "TOKEN_EXPIRES_AT": "1234567890",
            },
        )
        assert config.access_token == "old-token"
        assert config.client_id == "my-client-id"

        config.clear_ephemeral()

        assert config.access_token is None, "ACCESS_TOKEN should be cleared"
        assert config.refresh_token is None, "REFRESH_TOKEN should be cleared"
        assert config.token_expires_at is None, "TOKEN_EXPIRES_AT should be cleared"
        assert config.client_id == "my-client-id", "CLIENT_ID must be preserved"
        assert config.client_secret == "my-client-secret", "CLIENT_SECRET must be preserved"

        shutil.rmtree(tmp)
        monkeypatch.undo()

    def test_pat_preserved_after_clear_ephemeral(self):
        """clear_ephemeral() on PERSONAL_ACCESS_TOKEN preserves the PAT."""
        config, tmp, monkeypatch = self._make_config(
            [CredentialType.PERSONAL_ACCESS_TOKEN],
            {"PERSONAL_ACCESS_TOKEN": "ghp_abc123"},
        )
        assert config.personal_access_token == "ghp_abc123"
        config.clear_ephemeral()
        assert config.personal_access_token == "ghp_abc123", (
            "clear_ephemeral() must NOT clear PERSONAL_ACCESS_TOKEN"
        )
        shutil.rmtree(tmp)
        monkeypatch.undo()

    def test_username_password_preserved_after_clear_ephemeral(self):
        """clear_ephemeral() on USERNAME_PASSWORD preserves username and password."""
        config, tmp, monkeypatch = self._make_config(
            [CredentialType.USERNAME_PASSWORD],
            {"USERNAME": "admin", "PASSWORD": "secret"},
        )
        assert config.username == "admin"
        config.clear_ephemeral()
        assert config.username == "admin", "clear_ephemeral() must NOT clear USERNAME"
        assert config.password == "secret", "clear_ephemeral() must NOT clear PASSWORD"
        shutil.rmtree(tmp)
        monkeypatch.undo()

    def test_mixed_api_key_oauth_clear_ephemeral(self):
        """Mixed API_KEY + OAUTH: clear_ephemeral clears tokens, preserves key."""
        config, tmp, monkeypatch = self._make_config(
            [CredentialType.API_KEY, CredentialType.OAUTH],
            {
                "API_KEY": "my-api-key",
                "CLIENT_ID": "cid",
                "CLIENT_SECRET": "csecret",
                "ACCESS_TOKEN": "old-token",
                "REFRESH_TOKEN": "old-refresh",
            },
        )
        config.clear_ephemeral()

        assert config.api_key == "my-api-key", "API_KEY must be preserved"
        assert config.client_id == "cid", "CLIENT_ID must be preserved"
        assert config.access_token is None, "ACCESS_TOKEN must be cleared"
        assert config.refresh_token is None, "REFRESH_TOKEN must be cleared"

        shutil.rmtree(tmp)
        monkeypatch.undo()

    def test_clear_credentials_clears_everything(self):
        """Contrast: clear_credentials() DOES clear all fields (for logout)."""
        config, tmp, monkeypatch = self._make_config(
            [CredentialType.API_KEY],
            {"API_KEY": "my-key"},
        )
        assert config.api_key == "my-key"
        config.clear_credentials()
        assert config.api_key is None, "clear_credentials() should clear API_KEY"
        shutil.rmtree(tmp)
        monkeypatch.undo()

    def test_clear_ephemeral_clears_browser_session(self):
        """clear_ephemeral() also removes browser session data directory."""
        config, tmp, monkeypatch = self._make_config(
            [CredentialType.API_KEY],
            {"API_KEY": "my-key"},
        )
        cookies_path = config.get_persistent_profile_dir() / "Default" / "Cookies"
        cookies_path.parent.mkdir(parents=True, exist_ok=True)
        cookies_path.write_text("")

        assert config.has_saved_session()
        config.clear_ephemeral()

        assert config.api_key == "my-key"
        assert not config.has_saved_session(), (
            "clear_ephemeral() must clear browser session data"
        )
        shutil.rmtree(tmp)
        monkeypatch.undo()
