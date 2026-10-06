"""Manual opt-in preserves the shared profile and authentication lifecycle."""
from types import SimpleNamespace

import pytest
import typer
from typer.testing import CliRunner
from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError
import cli_tools_shared.auth as shared_auth
import cli_tools_shared.config as shared_config
import tiktok_cli.browser as browser_mod

from tiktok_cli import auth as auth_mod
from tiktok_cli.browser import ManualTiktokBrowser, TiktokBrowser, manual_login_requested
from tiktok_cli.config import Config


def command_app(monkeypatch, callback):
    auth_app = typer.Typer()
    auth_app.command("login")(callback)
    auth_mod.add_manual_login_option(auth_app)
    app = typer.Typer()
    app.add_typer(auth_app, name="auth")
    return app


def test_manual_routes_only_this_invocation_to_same_config(monkeypatch, tmp_path):
    config = object.__new__(Config)
    config.get_persistent_profile_dir = lambda: tmp_path / "clipping" / "chromium-profile"
    config.get_browser_data_dir = lambda: tmp_path / "clipping" / "browser-data"
    observed = []
    def login(profile, force, credential_type):
        browser = config.get_browser()
        observed.append((profile, force, credential_type, type(browser)))
        assert browser.config is config
        assert browser._get_persistent_profile_dir() == config.get_persistent_profile_dir()
        assert browser._get_browser_data_dir() == config.get_browser_data_dir()
    app = command_app(monkeypatch, login)
    runner = CliRunner()
    result = runner.invoke(app, ["auth", "login", "--profile", "clipping", "--credential-type", "browser_session", "--manual"])
    assert result.exit_code == 0, result.output
    assert observed == [("clipping", False, "browser_session", ManualTiktokBrowser)]
    assert type(config.get_browser()) is TiktokBrowser
    assert not manual_login_requested.get()
    result = runner.invoke(app, ["auth", "login", "--profile", "clipping", "--credential-type", "browser_session"])
    assert result.exit_code == 0, result.output
    assert observed[-1][-1] is TiktokBrowser


@pytest.mark.parametrize("options", [[], ["--profile", "default"], ["--profile", "   ", "--credential-type", "browser_session"], ["--profile", "clipping", "--credential-type", "custom"], ["--profile", "clipping"]])
def test_manual_rejects_shared_or_non_browser_profile(monkeypatch, options):
    app = command_app(monkeypatch, lambda **kwargs: pytest.fail("must not mutate auth state"))
    result = CliRunner().invoke(app, ["auth", "login", "--manual", *options])
    assert result.exit_code != 0
    assert not manual_login_requested.get()


def test_request_scope_resets_on_cancel(monkeypatch):
    def login(**kwargs):
        assert manual_login_requested.get()
        raise KeyboardInterrupt()
    app = command_app(monkeypatch, login)
    result = CliRunner().invoke(app, ["auth", "login", "--profile", "clipping", "--credential-type", "browser_session", "--manual"])
    assert result.exit_code != 0
    assert not manual_login_requested.get()


def test_manual_declarative_hooks_delegate_shared_lifecycle():
    assert TiktokBrowser.AUTH_LOGIN_HANDLER is not None
    assert not TiktokBrowser.MANUAL_LOGIN
    assert ManualTiktokBrowser.AUTH_LOGIN_HANDLER is None
    assert ManualTiktokBrowser.MANUAL_LOGIN
    assert ManualTiktokBrowser.authenticate is BrowserAutomation.authenticate
    assert ManualTiktokBrowser._authenticate_manual is BrowserAutomation._authenticate_manual
    assert ManualTiktokBrowser.is_authenticated is BrowserAutomation.is_authenticated


@pytest.mark.parametrize("outcome", ["success", "unauthenticated", "timeout", "cancel"])
def test_manual_uses_plain_profile_chrome_and_cleans_up(monkeypatch, tmp_path, outcome):
    config = SimpleNamespace(get_persistent_profile_dir=lambda: tmp_path / "clipping" / "chromium-profile")
    browser = ManualTiktokBrowser(config)
    monkeypatch.setattr(shared_config, "read_cli_tool_secret", lambda *a: pytest.fail("manual must not read secrets"))
    monkeypatch.setattr(browser_mod, "read_cli_tool_secret", lambda *a: pytest.fail("manual must not read secrets"))
    monkeypatch.setenv("CLI_TOOLS_CHROME_BINARY", "/fake/chrome")
    launched = []
    process = object()
    monkeypatch.setattr(shared_auth.subprocess, "Popen", lambda args, **kwargs: launched.append(args) or process)
    closed = []
    monkeypatch.setattr(browser, "close", lambda: None)
    monkeypatch.setattr(browser, "_quit_login_chrome", lambda proc: closed.append(proc))
    monkeypatch.setattr(browser, "_prompt_enter_eof_safe", lambda **kwargs: outcome not in ("timeout",))
    if outcome == "cancel":
        def cancel(**kwargs):
            raise KeyboardInterrupt()
        monkeypatch.setattr(browser, "_prompt_enter_eof_safe", cancel)
    if outcome == "timeout":
        def timeout(*args):
            raise BrowserAutomationError("Timed out waiting for the manual login browser window to close.")
        monkeypatch.setattr(browser, "_wait_for_manual_browser_close", timeout)
    checked = []
    monkeypatch.setattr(browser, "is_authenticated", lambda: checked.append(True) or outcome == "success")
    if outcome == "success":
        browser.authenticate()
    elif outcome == "cancel":
        with pytest.raises(KeyboardInterrupt):
            browser.authenticate()
    else:
        with pytest.raises(BrowserAutomationError):
            browser.authenticate()
    assert launched == [["/fake/chrome", f"--user-data-dir={config.get_persistent_profile_dir()}", "--no-first-run", "--no-default-browser-check", "https://www.tiktok.com/login"]]
    assert closed == [process]
    assert checked == ([True] if outcome in ("success", "unauthenticated") else [])
