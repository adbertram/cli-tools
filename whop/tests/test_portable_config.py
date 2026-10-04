"""Service scope and root provisioning preserve profile isolation."""
import json
from unittest.mock import Mock
import pytest
from typer.testing import CliRunner
from cli_tools_shared.config import config_env_path_for_tool, get_profiles_base_dir, _read_env_values
from whop_cli.config import Config
from whop_cli.main import app

URL = "https://b4e0vdqv6zgqeqj4pfgm.apps.whop.com/c/exp_TEST"

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return tmp_path

def test_root_command_no_config_or_default_profile(isolated, monkeypatch):
    monkeypatch.setattr(Config, "__init__", Mock(side_effect=AssertionError("No Config bootstrap")))
    root = config_env_path_for_tool("whop")
    root.parent.mkdir(parents=True)
    root.write_text("HEADLESS=true\nCUSTOM_ROOT=kept\n")
    result = CliRunner().invoke(app, ["config", "set-rewards-url", URL])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["rewards_url"] == URL
    assert _read_env_values(root) == {"HEADLESS": "true", "CUSTOM_ROOT": "kept", "REWARDS_URL": URL}
    assert not get_profiles_base_dir("whop").exists()
    before = root.read_bytes()
    assert CliRunner().invoke(app, ["config", "set-rewards-url", URL]).exit_code == 0
    assert root.read_bytes() == before
    result = CliRunner().invoke(app, ["config", "set-rewards-url", URL.replace("exp_TEST", "exp_OTHER")])
    assert result.exit_code != 0 and root.read_bytes() == before

@pytest.mark.parametrize("url", ["http://whop.com", "https://whop.tw/c/exp_TEST", "https://example.apps.whop.com@evil.com/c/exp_TEST", URL+"?token=secret", URL+"#x", URL+"\n", " "+URL, URL+"/../settings"])
def test_bad_url_never_creates_runtime_state(isolated, url):
    assert CliRunner().invoke(app, ["config", "set-rewards-url", url]).exit_code != 0
    assert not config_env_path_for_tool("whop").exists()
    assert not get_profiles_base_dir("whop").exists()

def test_scope_uses_exact_configured_origin():
    config = Config.__new__(Config)
    config._get = lambda name: URL
    assert config.browser_session_origins() == ("https://whop.com", "https://b4e0vdqv6zgqeqj4pfgm.apps.whop.com")
    assert config.browser_session_cookie_domains() == ("whop.com", "b4e0vdqv6zgqeqj4pfgm.apps.whop.com")

def test_identity_reuses_given_browser_without_closing(monkeypatch):
    from whop_cli.client import WhopClient
    browser = Mock()
    config = Config.__new__(Config)
    config.get_browser = Mock(side_effect=AssertionError("No second browser"))
    config.get_active_profile_name = lambda: "rewards"
    monkeypatch.setattr(WhopClient, "_request", lambda self, page, path: {"id": "user_WTRcEsVm5k3qW", "username": "adam", "email": "private"})
    assert config.browser_session_identity(browser) == {"account_id": "user_WTRcEsVm5k3qW", "username": "adam"}
    browser.close.assert_not_called()

def test_auth_commands_registered_without_profile_bootstrap(isolated):
    for name in ("session-export", "session-import", "session-import-recover"):
        assert CliRunner().invoke(app, ["auth", name, "--help"]).exit_code == 0
    assert not get_profiles_base_dir("whop").exists()
