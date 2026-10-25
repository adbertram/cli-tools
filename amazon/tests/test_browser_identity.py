"""Keep persisted Amazon authentication usable across browser modes."""

from amazon_cli import config


def test_login_and_headless_reads_use_installed_chrome_identity(monkeypatch):
    monkeypatch.setattr(config.Config, "_get", lambda self, key: None)
    monkeypatch.setattr(config, "derive_real_chrome_user_agent", lambda: "installed Chrome")
    settings = object.__new__(config.Config)
    browser = settings.get_browser()

    assert browser._browser_user_agent() == "installed Chrome"
    assert settings.headless is True
    monkeypatch.setattr(config.Config, "_get", lambda self, key: "false" if key == "HEADLESS" else None)
    assert settings.headless is False
    assert browser._browser_user_agent() == "installed Chrome"


def test_explicit_user_agent_override_is_preserved(monkeypatch):
    monkeypatch.setattr(config.Config, "_get", lambda self, key: "configured Chrome")
    monkeypatch.setattr(config, "derive_real_chrome_user_agent", lambda: (_ for _ in ()).throw(AssertionError()))
    assert object.__new__(config.Config).browser_user_agent == "configured Chrome"
