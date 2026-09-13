"""Shared Chromium user-data-dir contract for browser CLIs."""
from pathlib import Path

import pytest

from cli_tools_shared.config import (
    BaseConfig,
    default_shared_chromium_profile_dir,
    get_cli_tools_data_root,
    get_profiles_base_dir,
)
from cli_tools_shared.credentials import CredentialType


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
