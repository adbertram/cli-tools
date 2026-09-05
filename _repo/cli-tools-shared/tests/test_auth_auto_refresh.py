"""Unit tests for the genericized automatic browser-session refresh.

Covers ``BrowserAutomation.ensure_fresh_session()`` decision table:

* fresh session -> no-op (authenticated, not refreshed)
* stale + fully declared credential login -> headless refresh (refreshed=True)
* stale + CAPTCHA/challenge on the page -> needs_human=True, no visible
  browser opened, no stdin read
* stale + incomplete declarative config -> authenticated=False,
  needs_human=False (caller falls back to the interactive flow)
* refresh throttling, persistence verification, engine-level errors, and the
  ``auth login`` seam in ``auth_commands._handle_browser_login`` that prefers
  the headless refresh while keeping today's headed flow for CLIs without a
  declarative login.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import typer

from cli_tools_shared.auth import AuthResult, BrowserAutomation, BrowserAutomationError
from cli_tools_shared.auth_commands import _handle_browser_login


class _ConfigDouble:
    """Minimal config double exposing data dir + persistent-profile dir."""

    def __init__(self, browser_data_dir: Path):
        self.browser_data_dir = browser_data_dir
        self._tool_name = "refresh-browser"

    def get_browser_data_dir(self) -> Path:
        return self.browser_data_dir

    def get_persistent_profile_dir(self) -> Path:
        return self.browser_data_dir / "chromium-profile"

    def has_saved_session(self) -> bool:
        return False


class _DeclarativeBrowser(BrowserAutomation):
    """Fully declared non-interactive credential login."""

    LOGIN_URL = "https://example.com/login"
    AUTH_CHECK_URL = "https://example.com/dashboard"
    SESSION_NAME = "refresh-browser"
    AUTH_LOGIN_USERNAME_SELECTOR = "#username"
    AUTH_LOGIN_PASSWORD_SELECTOR = "#password"
    AUTH_LOGIN_SUBMIT_SELECTOR = "#submit"
    AUTH_LOGIN_USERNAME_SECRET = "refresh-browser-username"
    AUTH_LOGIN_PASSWORD_SECRET = "refresh-browser-password"


class _IncompleteBrowser(_DeclarativeBrowser):
    """Selectors declared but secret names missing -> not configured."""

    AUTH_LOGIN_USERNAME_SECRET = ""
    AUTH_LOGIN_PASSWORD_SECRET = ""


class _PlainBrowser(BrowserAutomation):
    """No declarative credential login at all."""

    LOGIN_URL = "https://example.com/login"
    AUTH_CHECK_URL = "https://example.com/dashboard"
    SESSION_NAME = "plain-browser"


class _PageStub:
    url = "https://example.com/login"

    def __init__(self):
        self.timeouts = []

    def wait_for_timeout(self, ms: int) -> None:
        self.timeouts.append(ms)

    def goto(self, url: str) -> None:
        self.url = url

    def evaluate(self, js: str, arg=None):
        raise AssertionError("evaluate must be stubbed before use")


class _Probe:
    """Sequence of canned is_authenticated results (last one repeats)."""

    def __init__(self, results):
        self.results = list(results)

    def __call__(self):
        return self.results.pop(0) if self.results else self.results[-1]


def _fresh_session_probe():
    return AuthResult(authenticated=True, live_check=True)


def _stale_session_probe():
    return AuthResult(authenticated=False, live_check=True)


# ---------------------------------------------------------------------------
# ensure_fresh_session decision table
# ---------------------------------------------------------------------------


def test_ensure_fresh_session_returns_early_when_session_already_fresh(tmp_path, monkeypatch):
    browser = _DeclarativeBrowser(_ConfigDouble(tmp_path))
    calls = []
    monkeypatch.setattr(browser, "is_authenticated", _fresh_session_probe)
    monkeypatch.setattr(browser, "get_page", lambda url=None: calls.append(url) or _PageStub())
    monkeypatch.setattr(browser, "_complete_noninteractive_login", lambda page: calls.append("login"))

    result = browser.ensure_fresh_session()

    assert result.authenticated is True
    assert result.refreshed is False
    assert result.needs_human is False
    assert calls == [], "a fresh session must not navigate or log in"


def test_ensure_fresh_session_refreshes_headlessly_when_configured(tmp_path, monkeypatch):
    browser = _DeclarativeBrowser(_ConfigDouble(tmp_path))
    # First probe: stale. Second probe (restart persistence check): fresh.
    monkeypatch.setattr(
        browser, "is_authenticated", _Probe([
            AuthResult(authenticated=False, live_check=True),
            AuthResult(authenticated=True, live_check=True),
        ])
    )
    page = _PageStub()
    login_pages = []
    monkeypatch.setattr(browser, "get_page", lambda url=None: page)
    monkeypatch.setattr(browser, "_complete_noninteractive_login", lambda p: login_pages.append(p))
    monkeypatch.setattr(browser, "_check_auth_settled", lambda p: True)
    monkeypatch.setattr(browser, "_detect_login_challenge", lambda p: None)
    monkeypatch.setattr(browser, "close", lambda: None)

    result = browser.ensure_fresh_session()

    assert result.authenticated is True
    assert result.refreshed is True
    assert login_pages == [page], "declarative login must run on the headless page"
    assert page.url == "https://example.com/dashboard", (
        "verification must navigate to AUTH_CHECK_URL"
    )


def test_ensure_fresh_session_challenge_returns_needs_human_without_browser_or_stdin(
    tmp_path, monkeypatch
):
    browser = _DeclarativeBrowser(_ConfigDouble(tmp_path))
    monkeypatch.setattr(browser, "is_authenticated", _stale_session_probe)
    page = _PageStub()
    login_calls = []
    monkeypatch.setattr(browser, "get_page", lambda url=None: page)
    monkeypatch.setattr(browser, "_detect_login_challenge", lambda p: "reCAPTCHA")
    monkeypatch.setattr(browser, "_complete_noninteractive_login", lambda p: login_calls.append(p))
    monkeypatch.setattr(browser, "close", lambda: None)
    input_calls = []
    monkeypatch.setattr("builtins.input", lambda *a, **k: input_calls.append(a) or "")

    def _no_engine_service():
        raise AssertionError("no engine browser service may be opened on the challenge path")

    monkeypatch.setattr(browser, "_get_service", _no_engine_service)

    result = browser.ensure_fresh_session()

    assert result.authenticated is False
    assert result.needs_human is True
    assert result.refreshed is False
    assert "reCAPTCHA" in result.reason
    assert login_calls == [], "challenge path must never attempt the credential fill"
    assert input_calls == [], "challenge path must never read stdin"


def test_ensure_fresh_session_incomplete_config_is_a_clean_failure(tmp_path, monkeypatch):
    browser = _IncompleteBrowser(_ConfigDouble(tmp_path))
    monkeypatch.setattr(browser, "is_authenticated", _stale_session_probe)
    calls = []
    monkeypatch.setattr(browser, "get_page", lambda url=None: calls.append("page") or _PageStub())
    monkeypatch.setattr(browser, "_complete_noninteractive_login", lambda p: calls.append("login"))
    monkeypatch.setattr(browser, "close", lambda: None)

    result = browser.ensure_fresh_session()

    assert result.authenticated is False
    assert result.needs_human is False
    assert result.refreshed is False
    assert "not configured" in result.reason
    assert calls == [], "an incomplete declarative login must not open a page"


def test_ensure_fresh_session_login_failure_is_reported_not_raised(tmp_path, monkeypatch):
    browser = _DeclarativeBrowser(_ConfigDouble(tmp_path))
    monkeypatch.setattr(browser, "is_authenticated", _stale_session_probe)
    monkeypatch.setattr(browser, "get_page", lambda url=None: _PageStub())
    monkeypatch.setattr(browser, "_detect_login_challenge", lambda p: None)

    def _reject(_page):
        raise BrowserAutomationError(
            "Browser login credentials were rejected by the service."
        )

    monkeypatch.setattr(browser, "_complete_noninteractive_login", _reject)
    monkeypatch.setattr(browser, "close", lambda: None)

    result = browser.ensure_fresh_session()

    assert result.authenticated is False
    assert result.needs_human is False
    assert result.refreshed is False
    assert "rejected" in result.reason


def test_ensure_fresh_session_settle_failure_is_reported_not_raised(tmp_path, monkeypatch):
    browser = _DeclarativeBrowser(_ConfigDouble(tmp_path))
    monkeypatch.setattr(browser, "is_authenticated", _stale_session_probe)
    monkeypatch.setattr(browser, "get_page", lambda url=None: _PageStub())
    monkeypatch.setattr(browser, "_complete_noninteractive_login", lambda p: None)
    monkeypatch.setattr(browser, "_check_auth_settled", lambda p: False)
    monkeypatch.setattr(browser, "_detect_login_challenge", lambda p: None)
    monkeypatch.setattr(browser, "close", lambda: None)

    result = browser.ensure_fresh_session()

    assert result.authenticated is False
    assert result.needs_human is False
    assert result.refreshed is False
    assert "did not reach an authenticated state" in result.reason


def test_ensure_fresh_session_requires_session_to_survive_restart(tmp_path, monkeypatch):
    browser = _DeclarativeBrowser(_ConfigDouble(tmp_path))
    monkeypatch.setattr(
        browser, "is_authenticated", _Probe([
            AuthResult(authenticated=False, live_check=True),
            AuthResult(authenticated=False, live_check=True),
        ])
    )
    monkeypatch.setattr(browser, "get_page", lambda url=None: _PageStub())
    monkeypatch.setattr(browser, "_complete_noninteractive_login", lambda p: None)
    monkeypatch.setattr(browser, "_check_auth_settled", lambda p: True)
    monkeypatch.setattr(browser, "_detect_login_challenge", lambda p: None)
    monkeypatch.setattr(browser, "close", lambda: None)

    result = browser.ensure_fresh_session()

    assert result.authenticated is False
    assert result.needs_human is False
    assert result.refreshed is False
    assert "did not persist" in result.reason


def test_ensure_fresh_session_engine_failures_raise(tmp_path, monkeypatch):
    browser = _DeclarativeBrowser(_ConfigDouble(tmp_path))
    monkeypatch.setattr(browser, "is_authenticated", _stale_session_probe)

    def _boom(url=None):
        raise BrowserAutomationError("browser could not start")

    monkeypatch.setattr(browser, "get_page", _boom)
    monkeypatch.setattr(browser, "close", lambda: None)

    with pytest.raises(BrowserAutomationError):
        browser.ensure_fresh_session()


def test_ensure_fresh_session_refresh_is_throttled_per_window(tmp_path, monkeypatch):
    browser = _DeclarativeBrowser(_ConfigDouble(tmp_path))
    monkeypatch.setattr(browser, "is_authenticated", _stale_session_probe)
    pages = []
    monkeypatch.setattr(browser, "get_page", lambda url=None: pages.append(url) or _PageStub())
    monkeypatch.setattr(browser, "_detect_login_challenge", lambda p: "hCaptcha")
    monkeypatch.setattr(browser, "close", lambda: None)

    first = browser.ensure_fresh_session()
    second = browser.ensure_fresh_session()

    assert first.needs_human is True
    assert second.needs_human is True
    assert second.reason == first.reason
    assert len(pages) == 1, "a repeat call inside the throttle window must not retry"


# ---------------------------------------------------------------------------
# _detect_login_challenge data-driven rule matching
# ---------------------------------------------------------------------------


def test_detect_login_challenge_matches_selector_rules(tmp_path):
    browser = _DeclarativeBrowser(_ConfigDouble(tmp_path))
    rules = list(browser.AUTH_CHALLENGE_RULES)
    assert rules, "base AUTH_CHALLENGE_RULES must not be empty"
    datadome_index = next(i for i, rule in enumerate(rules) if rule[0] == "DataDome")
    matched = [i == datadome_index for i in range(len(rules))]
    page = _PageStub()
    page.evaluate = lambda js, arg=None: {
        "matched": matched,
        "title": "",
        "text": "",
        "cookie": "",
    }

    assert browser._detect_login_challenge(page) == "DataDome"


def test_detect_login_challenge_matches_body_text_markers(tmp_path):
    browser = _DeclarativeBrowser(_ConfigDouble(tmp_path))
    rules = list(browser.AUTH_CHALLENGE_RULES)
    perimeterx_index = next(i for i, rule in enumerate(rules) if rule[0] == "PerimeterX/HUMAN")
    page = _PageStub()
    page.evaluate = lambda js, arg=None: {
        "matched": [False] * len(rules),
        "title": "",
        "text": "Press & Hold to confirm you are a human",
        "cookie": "",
    }

    assert browser._detect_login_challenge(page) == "PerimeterX/HUMAN"


def test_detect_login_challenge_returns_none_on_clean_page(tmp_path):
    browser = _DeclarativeBrowser(_ConfigDouble(tmp_path))
    rules = list(browser.AUTH_CHALLENGE_RULES)
    page = _PageStub()
    page.evaluate = lambda js, arg=None: {
        "matched": [False] * len(rules),
        "title": "Login",
        "text": "Sign in with your email and password",
        "cookie": "",
    }

    assert browser._detect_login_challenge(page) is None


def test_detect_login_challenge_tolerates_unprobeable_pages(tmp_path):
    browser = _DeclarativeBrowser(_ConfigDouble(tmp_path))
    page = _PageStub()
    page.evaluate = lambda js, arg=None: (_ for _ in ()).throw(RuntimeError("page gone"))

    assert browser._detect_login_challenge(page) is None


# ---------------------------------------------------------------------------
# account-block detection (banned accounts must stop instantly, needs_human)
# ---------------------------------------------------------------------------

_BANNED_LINE = (
    "Your account is banned for 1 day. Reason: Auto-refresh / Bot. "
    "Account will be unblocked on 09/05/2026 15:05:47"
)


class _LoginUrlBlockBrowser(_DeclarativeBrowser):
    AUTH_URL_PATTERN = r"/login"


def _probe_for(text: str, title: str = "Login", matched_all: bool = False):
    rules = list(_DeclarativeBrowser.AUTH_CHALLENGE_RULES)
    return {
        "matched": [False if not matched_all else True] * len(rules),
        "title": title,
        "text": text,
        "cookie": "",
    }


def test_ensure_fresh_session_account_block_on_login_page_returns_needs_human(
    tmp_path, monkeypatch
):
    browser = _LoginUrlBlockBrowser(_ConfigDouble(tmp_path))
    monkeypatch.setattr(browser, "is_authenticated", _stale_session_probe)
    page = _PageStub()
    page.evaluate = lambda js, arg=None: _probe_for(_BANNED_LINE)
    login_calls = []
    monkeypatch.setattr(browser, "get_page", lambda url=None: page)
    monkeypatch.setattr(
        browser, "_complete_noninteractive_login", lambda p: login_calls.append(p)
    )
    monkeypatch.setattr(browser, "close", lambda: None)

    result = browser.ensure_fresh_session()

    assert result.authenticated is False
    assert result.needs_human is True
    assert result.refreshed is False
    assert result.reason == f"Account block detected on the login page: {_BANNED_LINE}"
    assert login_calls == [], "a banned account must not be submitted to"


def test_ensure_fresh_session_account_block_after_submit_stops_instantly(
    tmp_path, monkeypatch
):
    """Live case: the login page is clean, but submitting shows the ban."""
    browser = _LoginUrlBlockBrowser(_ConfigDouble(tmp_path))
    monkeypatch.setattr(browser, "is_authenticated", _stale_session_probe)
    page = _PageStub()
    submitted = {"done": False}

    def _evaluate(js, arg=None):
        if submitted["done"]:
            return _probe_for(_BANNED_LINE)
        return _probe_for("Email Password Sign in")

    page.evaluate = _evaluate

    def _submit_and_raise(_page):
        # Mirrors _complete_noninteractive_login's poll: it spots the ban and
        # raises right away instead of burning the automation timeout.
        submitted["done"] = True
        raise BrowserAutomationError(
            "Account block detected during browser login: " + _BANNED_LINE
        )

    monkeypatch.setattr(browser, "get_page", lambda url=None: page)
    monkeypatch.setattr(browser, "_complete_noninteractive_login", _submit_and_raise)
    monkeypatch.setattr(browser, "close", lambda: None)

    result = browser.ensure_fresh_session()

    assert result.authenticated is False
    assert result.needs_human is True
    assert result.refreshed is False
    # Still on the login page (login.php) when the block appears, so the
    # reason names the login page with the site's own wording.
    assert result.reason == f"Account block detected on the login page: {_BANNED_LINE}"


def test_ensure_fresh_session_account_block_on_auth_check_page_returns_needs_human(
    tmp_path, monkeypatch
):
    """A banned interstitial can render on AUTH_CHECK_URL after login."""
    browser = _DeclarativeBrowser(_ConfigDouble(tmp_path))
    monkeypatch.setattr(browser, "is_authenticated", _stale_session_probe)
    page = _PageStub()
    page.evaluate = (
        lambda js, arg=None: _probe_for(_BANNED_LINE)
        if page.url == "https://example.com/dashboard"
        else _probe_for("Email Password Sign in")
    )
    login_calls = []
    monkeypatch.setattr(browser, "get_page", lambda url=None: page)
    monkeypatch.setattr(
        browser, "_complete_noninteractive_login", lambda p: login_calls.append(p)
    )
    monkeypatch.setattr(browser, "_check_auth_settled", lambda p: True)
    monkeypatch.setattr(browser, "close", lambda: None)

    result = browser.ensure_fresh_session()

    assert result.authenticated is False
    assert result.needs_human is True
    assert result.refreshed is False
    assert result.reason == f"Account block detected on the auth-check page: {_BANNED_LINE}"
    assert login_calls == [page]


def test_detect_account_block_captures_the_sites_own_line(tmp_path):
    browser = _DeclarativeBrowser(_ConfigDouble(tmp_path))
    page = _PageStub()
    page.evaluate = lambda js, arg=None: _probe_for(_BANNED_LINE)

    assert browser._detect_account_block(page) == _BANNED_LINE


def test_detect_account_block_returns_none_on_unrelated_text(tmp_path):
    browser = _DeclarativeBrowser(_ConfigDouble(tmp_path))
    page = _PageStub()
    page.evaluate = lambda js, arg=None: _probe_for(
        "Your account is now active. Welcome back!"
    )

    assert browser._detect_account_block(page) is None


# ---------------------------------------------------------------------------
# auth login seam: _handle_browser_login prefers the headless refresh
# ---------------------------------------------------------------------------


def _login_config(browser, has_session: bool):
    config = MagicMock()
    config.has_saved_session.return_value = has_session
    config.get_browser.return_value = browser
    return config


def test_handle_browser_login_headless_refreshes_declarative_login(
    tmp_path, monkeypatch, capsys
):
    browser = _DeclarativeBrowser(_ConfigDouble(tmp_path))
    config = _login_config(browser, has_session=False)
    ensure_calls = []
    monkeypatch.setattr(
        browser,
        "ensure_fresh_session",
        lambda: ensure_calls.append(True) or AuthResult(
            authenticated=True, live_check=True, refreshed=True
        ),
    )
    monkeypatch.setattr(
        browser,
        "login",
        lambda force=False: (_ for _ in ()).throw(AssertionError("headed login must not run")),
    )
    monkeypatch.setattr(browser, "close", lambda: None)

    _handle_browser_login(config, "refresh-browser", force=False)

    assert ensure_calls == [True]
    assert "Browser session authenticated" in capsys.readouterr().err


def test_handle_browser_login_keeps_headed_flow_without_declarative_login(
    tmp_path, monkeypatch
):
    browser = _PlainBrowser(_ConfigDouble(tmp_path))
    config = _login_config(browser, has_session=True)
    monkeypatch.setattr(browser, "is_authenticated", _stale_session_probe)
    monkeypatch.setattr(
        browser,
        "ensure_fresh_session",
        lambda: (_ for _ in ()).throw(AssertionError("headless refresh must not run")),
    )
    login_calls = []
    monkeypatch.setattr(
        browser,
        "login",
        lambda force=False: login_calls.append(force) or {"success": True, "message": "ok"},
    )
    monkeypatch.setattr(browser, "close", lambda: None)

    _handle_browser_login(config, "plain-browser", force=False)

    assert login_calls == [True], "a non-declarative CLI keeps the stale -> forced headed flow"


def test_handle_browser_login_falls_back_to_headed_when_human_needed(
    tmp_path, monkeypatch
):
    browser = _DeclarativeBrowser(_ConfigDouble(tmp_path))
    config = _login_config(browser, has_session=False)
    monkeypatch.setattr(
        browser,
        "ensure_fresh_session",
        lambda: AuthResult(
            authenticated=False,
            live_check=True,
            needs_human=True,
            reason="reCAPTCHA challenge detected on the login page; a human must complete it",
        ),
    )
    login_calls = []
    monkeypatch.setattr(
        browser,
        "login",
        lambda force=False: login_calls.append(force) or {"success": True, "message": "ok"},
    )
    monkeypatch.setattr(browser, "close", lambda: None)

    _handle_browser_login(config, "refresh-browser", force=False)

    assert login_calls == [False], "a human gate falls back to the headed interactive login"


def test_handle_browser_login_non_human_refresh_failure_exits_without_headed_browser(
    tmp_path, monkeypatch
):
    browser = _DeclarativeBrowser(_ConfigDouble(tmp_path))
    config = _login_config(browser, has_session=False)
    monkeypatch.setattr(
        browser,
        "ensure_fresh_session",
        lambda: AuthResult(
            authenticated=False,
            live_check=True,
            needs_human=False,
            reason="Browser login credentials were rejected by the service.",
        ),
    )
    monkeypatch.setattr(
        browser,
        "login",
        lambda force=False: (_ for _ in ()).throw(AssertionError("headed login must not run")),
    )
    monkeypatch.setattr(browser, "close", lambda: None)
    monkeypatch.setattr(
        "cli_tools_shared.auth_commands._interactive_stdio_available", lambda: False
    )

    with pytest.raises(typer.Exit) as exc_info:
        _handle_browser_login(config, "refresh-browser", force=False)

    assert exc_info.value.exit_code == 1


def test_handle_browser_login_non_human_refresh_failure_falls_back_on_tty(
    tmp_path, monkeypatch
):
    browser = _DeclarativeBrowser(_ConfigDouble(tmp_path))
    config = _login_config(browser, has_session=False)
    monkeypatch.setattr(
        browser,
        "ensure_fresh_session",
        lambda: AuthResult(
            authenticated=False,
            live_check=True,
            needs_human=False,
            reason="Browser login credentials were rejected by the service.",
        ),
    )
    login_calls = []
    monkeypatch.setattr(
        browser,
        "login",
        lambda force=False: login_calls.append(force) or {"success": True, "message": "ok"},
    )
    monkeypatch.setattr(browser, "close", lambda: None)
    monkeypatch.setattr(
        "cli_tools_shared.auth_commands._interactive_stdio_available", lambda: True
    )

    _handle_browser_login(config, "refresh-browser", force=False)

    assert login_calls == [False], "an interactive host can still complete login by hand"
