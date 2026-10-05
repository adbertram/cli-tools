"""Shared Chromium user-data-dir contract for browser CLIs."""
import sys
import types
from pathlib import Path

import pytest

from cli_tools_shared.config import (
    BaseConfig,
    default_shared_chromium_profile_dir,
    get_cli_tools_data_root,
    get_profiles_base_dir,
)
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ConfigError


class BrowserConfig(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]


class ApiConfig(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.API_KEY]


def _write_profile(path: Path, *, active: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"ACTIVE={'true' if active else 'false'}\n")


@pytest.fixture
def isolated_data_home(tmp_path, monkeypatch):
    data_home = tmp_path / "share"
    data_home.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.delenv("CLI_TOOLS_SHARED_CHROME_PROFILE", raising=False)
    monkeypatch.delenv("CLI_TOOLS_ISOLATE_CHROME_PROFILE", raising=False)
    monkeypatch.delenv("CLI_TOOLS_PROFILE", raising=False)
    return data_home


def _tool_dir(tmp_path: Path, name: str = "dealcli") -> Path:
    tool_dir = tmp_path / name
    tool_dir.mkdir()
    return tool_dir


def test_default_shared_path_under_cli_tools_root(isolated_data_home):
    assert default_shared_chromium_profile_dir() == (
        get_cli_tools_data_root() / "_shared" / "chromium-profile"
    )


def test_browser_default_profile_uses_shared_dir(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    _write_profile(get_profiles_base_dir(tool_dir.name) / "default" / ".env")
    config = BrowserConfig(tool_dir=tool_dir)

    assert config.uses_shared_chromium_profile() is True
    assert config.get_persistent_profile_dir() == default_shared_chromium_profile_dir()
    assert config.get_persistent_profile_dir().is_dir()


def test_two_browser_clis_share_same_profile_dir(tmp_path, isolated_data_home):
    a = _tool_dir(tmp_path, "poshmark")
    b = _tool_dir(tmp_path, "offerup")
    _write_profile(get_profiles_base_dir(a.name) / "default" / ".env")
    _write_profile(get_profiles_base_dir(b.name) / "default" / ".env")

    cfg_a = BrowserConfig(tool_dir=a)
    cfg_b = BrowserConfig(tool_dir=b)

    assert cfg_a.get_persistent_profile_dir() == cfg_b.get_persistent_profile_dir()


def test_named_auth_profile_stays_isolated(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path, "google")
    _write_profile(get_profiles_base_dir(tool_dir.name) / "default" / ".env", active=False)
    named = get_profiles_base_dir(tool_dir.name) / "adbertram" / ".env"
    _write_profile(named, active=True)
    config = BrowserConfig(tool_dir=tool_dir)

    assert config.get_active_profile_name() == "adbertram"
    assert config.uses_shared_chromium_profile() is False
    expected = config.get_browser_data_dir() / "chromium-profile"
    assert config.get_persistent_profile_dir() == expected


def test_isolate_env_forces_per_tool_profile(tmp_path, isolated_data_home, monkeypatch):
    monkeypatch.setenv("CLI_TOOLS_ISOLATE_CHROME_PROFILE", "1")
    tool_dir = _tool_dir(tmp_path)
    _write_profile(get_profiles_base_dir(tool_dir.name) / "default" / ".env")
    config = BrowserConfig(tool_dir=tool_dir)

    assert config.uses_shared_chromium_profile() is False
    assert config.get_persistent_profile_dir() == (
        config.get_browser_data_dir() / "chromium-profile"
    )


def test_shared_path_env_override(tmp_path, isolated_data_home, monkeypatch):
    custom = tmp_path / "custom-chrome"
    monkeypatch.setenv("CLI_TOOLS_SHARED_CHROME_PROFILE", str(custom))
    tool_dir = _tool_dir(tmp_path)
    _write_profile(get_profiles_base_dir(tool_dir.name) / "default" / ".env")
    config = BrowserConfig(tool_dir=tool_dir)

    assert config.get_persistent_profile_dir() == custom.resolve()
    assert custom.resolve().is_dir()


def test_api_only_config_does_not_use_shared(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path, "apionly")
    _write_profile(get_profiles_base_dir(tool_dir.name) / "default" / ".env")
    # API_KEY configs still need a field; BaseConfig may require more — use BROWSER off
    config = ApiConfig(tool_dir=tool_dir)
    assert config.uses_shared_chromium_profile() is False
    assert config.get_persistent_profile_dir() == (
        config.get_browser_data_dir() / "chromium-profile"
    )


def test_clear_session_preserves_shared_profile(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    _write_profile(get_profiles_base_dir(tool_dir.name) / "default" / ".env")
    config = BrowserConfig(tool_dir=tool_dir)
    shared = config.get_persistent_profile_dir()
    (shared / "Default").mkdir(parents=True)
    (shared / "Default" / "Cookies").write_text("cookies")

    # Local-only noise next to a symlink-style pointer
    local = config.get_browser_data_dir()
    (local / "auth-state.json").write_text("{}")
    link = local / "chromium-profile"
    if not link.exists():
        link.symlink_to(shared)

    config.clear_session()

    assert (shared / "Default" / "Cookies").read_text() == "cookies"
    assert not (local / "auth-state.json").exists()
    # symlink may be removed as tool-local; shared data remains
    assert shared.exists()


def test_clear_shared_chromium_profile_wipes_shared(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    _write_profile(get_profiles_base_dir(tool_dir.name) / "default" / ".env")
    config = BrowserConfig(tool_dir=tool_dir)
    shared = config.get_persistent_profile_dir()
    (shared / "Default").mkdir(parents=True)
    (shared / "Default" / "Cookies").write_text("cookies")

    cleared = config.clear_shared_chromium_profile()
    assert cleared == shared
    assert not shared.exists()


def _write_cookies(profile_dir: Path, value: str = "cookies") -> None:
    cookies = profile_dir / "Default" / "Cookies"
    cookies.parent.mkdir(parents=True, exist_ok=True)
    cookies.write_text(value)


def test_unseeded_shared_profile_reports_exact_seed_command(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path, "bricklink")
    _write_profile(get_profiles_base_dir(tool_dir.name) / "default" / ".env")
    config = BrowserConfig(tool_dir=tool_dir)
    _write_cookies(config.get_legacy_chromium_profile_dir())

    assert config.shared_chromium_profile_seed_guidance("bricklink") == (
        "shared Chromium profile not seeded; run "
        "'bricklink auth seed-shared-chromium-profile'"
    )


def test_partially_populated_shared_profile_does_not_report_seed_command(
    tmp_path,
    isolated_data_home,
):
    tool_dir = _tool_dir(tmp_path, "bricklink")
    _write_profile(get_profiles_base_dir(tool_dir.name) / "default" / ".env")
    config = BrowserConfig(tool_dir=tool_dir)
    _write_cookies(config.get_legacy_chromium_profile_dir())
    shared = config.get_persistent_profile_dir()
    (shared / "Preferences").write_text("partial shared profile")

    assert config.shared_chromium_profile_seed_guidance("bricklink") is None


def test_seed_shared_profile_copies_one_legacy_profile(tmp_path, isolated_data_home, monkeypatch):
    tool_dir = _tool_dir(tmp_path, "bricklink")
    _write_profile(get_profiles_base_dir(tool_dir.name) / "default" / ".env")
    config = BrowserConfig(tool_dir=tool_dir)
    source = config.get_legacy_chromium_profile_dir()
    _write_cookies(source, "legacy-cookies")
    (source / "Preferences").write_text("preferences")
    (source / "SingletonLock").write_text("stale-lock")
    target = config.get_persistent_profile_dir()
    monkeypatch.setattr(
        "cli_tools_shared.shared_chromium_profile.profile_process_pids",
        lambda _profile: [],
    )

    seeded = config.seed_shared_chromium_profile()

    assert seeded == target
    assert (target / "Default" / "Cookies").read_text() == "legacy-cookies"
    assert (target / "Preferences").read_text() == "preferences"
    assert not (target / "SingletonLock").exists()
    assert config.shared_chromium_profile_seed_guidance("bricklink") is None


def test_seed_shared_profile_refuses_missing_legacy_session(tmp_path, isolated_data_home, monkeypatch):
    tool_dir = _tool_dir(tmp_path, "bricklink")
    _write_profile(get_profiles_base_dir(tool_dir.name) / "default" / ".env")
    config = BrowserConfig(tool_dir=tool_dir)
    monkeypatch.setattr(
        "cli_tools_shared.shared_chromium_profile.profile_process_pids",
        lambda _profile: [],
    )

    with pytest.raises(ConfigError, match="source has no Cookies database"):
        config.seed_shared_chromium_profile()


def test_seed_shared_profile_refuses_populated_target(tmp_path, isolated_data_home, monkeypatch):
    tool_dir = _tool_dir(tmp_path, "bricklink")
    _write_profile(get_profiles_base_dir(tool_dir.name) / "default" / ".env")
    config = BrowserConfig(tool_dir=tool_dir)
    _write_cookies(config.get_legacy_chromium_profile_dir())
    target = config.get_persistent_profile_dir()
    (target / "existing.txt").write_text("do not overwrite")
    monkeypatch.setattr(
        "cli_tools_shared.shared_chromium_profile.profile_process_pids",
        lambda _profile: [],
    )

    with pytest.raises(ConfigError, match="destination is not empty"):
        config.seed_shared_chromium_profile()


def test_seed_shared_profile_refuses_nonshared_config(tmp_path, isolated_data_home, monkeypatch):
    monkeypatch.setenv("CLI_TOOLS_ISOLATE_CHROME_PROFILE", "1")
    tool_dir = _tool_dir(tmp_path, "bricklink")
    _write_profile(get_profiles_base_dir(tool_dir.name) / "default" / ".env")
    config = BrowserConfig(tool_dir=tool_dir)

    with pytest.raises(ConfigError, match="requires the default browser authentication profile"):
        config.seed_shared_chromium_profile()


def test_seed_shared_profile_refuses_running_chrome(tmp_path, isolated_data_home, monkeypatch):
    tool_dir = _tool_dir(tmp_path, "bricklink")
    _write_profile(get_profiles_base_dir(tool_dir.name) / "default" / ".env")
    config = BrowserConfig(tool_dir=tool_dir)
    _write_cookies(config.get_legacy_chromium_profile_dir())
    monkeypatch.setattr(
        "cli_tools_shared.shared_chromium_profile.profile_process_pids",
        lambda _profile: [421],
    )

    with pytest.raises(ConfigError, match="PID\\(s\\): 421"):
        config.seed_shared_chromium_profile()


def test_browser_clear_session_preserves_shared_data(tmp_path, isolated_data_home, monkeypatch):
    from unittest.mock import MagicMock
    from cli_tools_shared.auth import BrowserAutomation

    tool_dir = _tool_dir(tmp_path)
    _write_profile(get_profiles_base_dir(tool_dir.name) / "default" / ".env")
    config = BrowserConfig(tool_dir=tool_dir)
    shared = config.get_persistent_profile_dir()
    (shared / "Default").mkdir(parents=True)
    (shared / "Default" / "Cookies").write_text("cookies")

    browser = BrowserAutomation(config)
    service = MagicMock()
    browser._service = service
    browser._page = MagicMock()

    browser.clear_session()

    service.close.assert_called_once_with()
    service.data_delete.assert_not_called()
    assert (shared / "Default" / "Cookies").read_text() == "cookies"
    assert browser._service is None
    assert browser._page is None


def test_browser_clear_session_deletes_isolated_profile(tmp_path, isolated_data_home, monkeypatch):
    from unittest.mock import MagicMock
    from cli_tools_shared.auth import BrowserAutomation

    monkeypatch.setenv("CLI_TOOLS_ISOLATE_CHROME_PROFILE", "1")
    tool_dir = _tool_dir(tmp_path)
    _write_profile(get_profiles_base_dir(tool_dir.name) / "default" / ".env")
    config = BrowserConfig(tool_dir=tool_dir)
    browser = BrowserAutomation(config)
    service = MagicMock()
    service._user_data_dir = None
    browser._service = service

    browser.clear_session()

    service.data_delete.assert_called_once_with()
    assert service._user_data_dir == config.get_persistent_profile_dir()


class _SessionLifecyclePage:
    def __init__(self):
        self.url = "about:blank"

    def title(self):
        return "Session lifecycle test page"

    def set_default_timeout(self, _timeout):
        return None

    def set_default_navigation_timeout(self, _timeout):
        return None

    def goto(self, url, **_kwargs):
        self.url = url

    def close(self):
        return None


class _SessionLifecycleContext:
    def __init__(self, cookies):
        self._cookies = cookies
        self.pages = [_SessionLifecyclePage()]
        self.closed = False

    def cookies(self):
        return [dict(cookie) for cookie in self._cookies]

    def new_page(self):
        page = _SessionLifecyclePage()
        self.pages.append(page)
        return page

    def close(self):
        self.closed = True


class _SessionLifecycleChromium:
    """Fake persistent profile backend that models Chrome's keychain split."""

    _MOCK_KEYCHAIN_ARGS = {"--use-mock-keychain", "--password-store=basic"}

    def __init__(self):
        self._cookies_by_profile = {}

    def save_plain_chrome_session(self, profile_dir, cookie):
        self._cookies_by_profile.setdefault(str(profile_dir), []).append(dict(cookie))

    def plain_chrome_session_is_authenticated(self, profile_dir):
        return any(
            cookie.get("name") == "bricklink_session"
            and cookie.get("value") == "authenticated"
            for cookie in self._cookies_by_profile.get(str(profile_dir), [])
        )

    def launch_persistent_context(self, profile_dir, **kwargs):
        cookies = self._cookies_by_profile.setdefault(str(profile_dir), [])
        ignored = set(kwargs.get("ignore_default_args", []))
        if not self._MOCK_KEYCHAIN_ARGS.issubset(ignored):
            # Chrome cannot decrypt cookies written with the other keychain and
            # drops them when the second tool opens the shared profile.
            cookies.clear()
        return _SessionLifecycleContext(cookies)


class _PlainRealKeychainTool:
    """Distinct CDP/plain-Chrome launcher used by Tool A in this regression."""

    def __init__(self, chromium):
        self._chromium = chromium

    def authenticate(self, profile_dir):
        self._chromium.save_plain_chrome_session(
            profile_dir,
            {
                "name": "bricklink_session",
                "value": "authenticated",
                "domain": ".bricklink.com",
            },
        )

    def is_authenticated(self, profile_dir):
        return self._chromium.plain_chrome_session_is_authenticated(profile_dir)


class _SessionLifecyclePlaywright:
    def __init__(self, chromium):
        self.chromium = chromium

    def stop(self):
        return None


def test_plain_chrome_tool_session_survives_second_tool_playwright_lifecycle(
    tmp_path, isolated_data_home, monkeypatch
):
    """A Playwright Tool B lifecycle must not sign out plain-Chrome Tool A (#530)."""
    from cli_tools_shared.browser import playwright_service as module
    from cli_tools_shared.browser.playwright_service import PlaywrightBrowserService

    first_tool_dir = _tool_dir(tmp_path, "bricklink")
    second_tool_dir = _tool_dir(tmp_path, "brickowl")
    _write_profile(get_profiles_base_dir(first_tool_dir.name) / "default" / ".env")
    _write_profile(get_profiles_base_dir(second_tool_dir.name) / "default" / ".env")
    first_config = BrowserConfig(tool_dir=first_tool_dir)
    second_config = BrowserConfig(tool_dir=second_tool_dir)
    shared_profile = first_config.get_persistent_profile_dir()
    assert shared_profile == second_config.get_persistent_profile_dir()

    chromium = _SessionLifecycleChromium()
    fake_sync_module = types.SimpleNamespace(
        sync_playwright=lambda: types.SimpleNamespace(
            start=lambda: _SessionLifecyclePlaywright(chromium)
        )
    )
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_module)
    monkeypatch.setattr(module, "_chrome_binary", lambda: "/Applications/Google Chrome")
    monkeypatch.setattr(
        PlaywrightBrowserService, "_cleanup_stale_profile_locks", lambda self: None
    )

    tool_a = _PlainRealKeychainTool(chromium)
    tool_a.authenticate(shared_profile)
    assert tool_a.is_authenticated(shared_profile)

    tool_b = PlaywrightBrowserService("brickowl-default")
    tool_b.browser_open(persistent_profile_dir=shared_profile)
    tool_b_context = tool_b._context
    tool_b.browser_close()
    assert tool_b_context.closed is True

    assert tool_a.is_authenticated(shared_profile)


def test_all_browser_consumers_inherit_shared_profile_resolution():
    """No browser CLI may fork the shared-vs-isolated path contract."""
    from cli_tools_shared.discovery import discover_consumers

    repo_root = Path(__file__).resolve().parents[3]
    consumers = discover_consumers(repo_root)
    assert consumers, "expected browser CLI consumers in the monorepo"

    offenders = []
    for browser_py in consumers:
        package_dir = browser_py.parent
        for py_file in package_dir.glob("*.py"):
            if "def get_persistent_profile_dir" in py_file.read_text():
                offenders.append(str(py_file.relative_to(repo_root)))
    assert offenders == [], (
        "browser CLIs must inherit BaseConfig shared-profile resolution; "
        f"remove per-tool overrides: {offenders}"
    )
