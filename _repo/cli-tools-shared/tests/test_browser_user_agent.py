"""Tests for the real-Chrome User-Agent derivation helper."""
import pytest

import cli_tools_shared.browser.user_agent as ua


@pytest.fixture(autouse=True)
def _reset_cache():
    ua._derived_user_agent = None
    yield
    ua._derived_user_agent = None


def test_derive_uses_installed_chrome_version(monkeypatch):
    monkeypatch.setattr(ua, "_installed_chrome_version", lambda: "149.0.7827.201")
    result = ua.derive_real_chrome_user_agent()
    assert "Chrome/149.0.7827.201 Safari/537.36" in result
    # Must NOT advertise the headless token that trips bot-protection.
    assert "Headless" not in result


def test_derive_is_cached(monkeypatch):
    calls = {"n": 0}

    def _fake_version():
        calls["n"] += 1
        return "150.0.1.2"

    monkeypatch.setattr(ua, "_installed_chrome_version", _fake_version)
    first = ua.derive_real_chrome_user_agent()
    second = ua.derive_real_chrome_user_agent()
    assert first == second
    assert calls["n"] == 1


def test_installed_chrome_version_parses_output(monkeypatch):
    class _Result:
        stdout = "Google Chrome 149.0.7827.201 \n"

    monkeypatch.setattr(ua.subprocess, "run", lambda *a, **k: _Result())
    monkeypatch.setattr(
        "cli_tools_shared.browser.driver._chrome_binary",
        lambda: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    )
    assert ua._installed_chrome_version() == "149.0.7827.201"


def test_installed_chrome_version_raises_when_unparseable(monkeypatch):
    class _Result:
        stdout = "no version here"

    monkeypatch.setattr(ua.subprocess, "run", lambda *a, **k: _Result())
    monkeypatch.setattr(
        "cli_tools_shared.browser.driver._chrome_binary",
        lambda: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    )
    with pytest.raises(RuntimeError):
        ua._installed_chrome_version()
