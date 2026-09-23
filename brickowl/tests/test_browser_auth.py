import pytest
from brickowl_cli.browser import _BrickOwlAutomation
from brickowl_cli.config import Config
from cli_tools_shared.auth import AuthResult, BrowserAutomation
from cli_tools_shared.auth_commands import (
    _browser_declarative_login_ready,
    _handle_browser_login,
)


def test_login_url_targets_live_brickowl_login_route():
    assert (
        _BrickOwlAutomation.LOGIN_URL
        == "https://www.brickowl.com/user?destination=mystore/orders"
    )


def test_auth_url_pattern_matches_current_login_routes():
    assert _BrickOwlAutomation._is_login_page(
        _BrickOwlAutomation, "https://www.brickowl.com/user"
    )
    assert _BrickOwlAutomation._is_login_page(
        _BrickOwlAutomation, "https://www.brickowl.com/user/login"
    )
    assert _BrickOwlAutomation._is_login_page(
        _BrickOwlAutomation,
        "https://www.brickowl.com/user?destination=mystore/orders",
    )
    assert not _BrickOwlAutomation._is_login_page(
        _BrickOwlAutomation, "https://www.brickowl.com/mystore/orders"
    )


@pytest.fixture
def browser(tmp_path, monkeypatch):
    """A real Brick Owl browser object built against an isolated data home."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data-home"))
    return Config().get_browser()


def test_brick_owl_automation_declares_the_noninteractive_login(browser):
    """An expired saved session must self-heal without a human at a terminal."""
    assert browser.declarative_login_configured is True


def test_declarative_login_hooks_match_the_live_login_form():
    assert (
        _BrickOwlAutomation.AUTH_LOGIN_USERNAME_SELECTOR
        == 'input[name="main_identifier"]'
    )
    assert (
        _BrickOwlAutomation.AUTH_LOGIN_PASSWORD_SELECTOR
        == 'input[name="main_password"]'
    )
    assert _BrickOwlAutomation.AUTH_LOGIN_SUBMIT_SELECTOR == 'input[name="bottom_op"]'
    assert _BrickOwlAutomation.AUTH_LOGIN_USERNAME_SECRET == "brickowl-legacy-username"
    assert _BrickOwlAutomation.AUTH_LOGIN_PASSWORD_SECRET == "brickowl-legacy-password"


def test_browser_from_config_passes_the_declarative_login_gate(browser):
    """The object ``auth login`` receives must qualify for the headless refresh.

    The shared seam only runs the non-interactive login for an object that is
    both a real ``BrowserAutomation`` and declares the credential login; a
    delegating wrapper satisfied neither, which is why the CLI needed a human.
    """
    assert isinstance(browser, BrowserAutomation)
    assert _browser_declarative_login_ready(browser) is True


def test_login_leg_can_run_headed_via_the_headless_env(browser, monkeypatch):
    """Brick Owl is Cloudflare-fronted; the login leg runs with HEADLESS=false."""
    monkeypatch.setenv("HEADLESS", "false")
    assert browser._headless_enabled() is False

    monkeypatch.setenv("HEADLESS", "true")
    assert browser._headless_enabled() is True


def test_auth_login_uses_the_noninteractive_login_for_brick_owl(browser, monkeypatch):
    """The reported defect: ``auth login`` needed a human to re-authenticate."""
    config = Config()
    monkeypatch.setattr(config, "get_browser", lambda: browser)
    monkeypatch.setattr(
        browser,
        "ensure_fresh_session",
        lambda: AuthResult(authenticated=True, live_check=True, refreshed=True),
    )
    monkeypatch.setattr(
        browser,
        "login",
        lambda force=False: pytest.fail("auth login fell back to the interactive browser"),
    )
    monkeypatch.setattr(browser, "close", lambda: None)

    _handle_browser_login(config, "brickowl", force=False)
