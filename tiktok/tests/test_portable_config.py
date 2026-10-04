"""Portable transfer uses the live browser and the declared service scope."""
from unittest.mock import Mock
from tiktok_cli.config import Config
from tiktok_cli.client import TikTokWebClient

def test_scope():
    config = Config.__new__(Config)
    assert config.browser_session_origins() == ("https://www.tiktok.com",)
    assert config.browser_session_cookie_domains() == ("tiktok.com", "www.tiktok.com", "tiktokw.us")

def test_identity_reuses_given_browser_without_closing(monkeypatch):
    browser = Mock()
    config = Config.__new__(Config)
    config.get_browser = Mock(side_effect=AssertionError("No second browser"))
    seen = []
    def account(self):
        seen.append(self._get_browser())
        return {"account_id": "7692213003349443597", "username": "ata_clipper", "profile": "clipper"}
    monkeypatch.setattr(TikTokWebClient, "get_account", account)
    assert config.browser_session_identity(browser) == {"account_id": "7692213003349443597", "username": "ata_clipper"}
    assert seen == [browser]
    browser.close.assert_not_called()

def test_browser_connection_success_uses_canonical_status(monkeypatch):
    from tiktok_cli.config import BROWSER_AUTH_TYPE
    config = Config.__new__(Config)
    monkeypatch.setattr(Config, "auth_type", property(lambda self: BROWSER_AUTH_TYPE))
    browser = Mock()
    browser.test_session.return_value = {"authenticated": True}
    config.get_browser = Mock(return_value=browser)
    assert config.test_connection() == {"api_test": "passed"}
