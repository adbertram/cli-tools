from pathlib import Path

from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.data_cache import cached


class _DummyBrowser:
    def __init__(self):
        self.is_authenticated_calls = 0
        self.close_calls = 0

    def is_authenticated(self):
        self.is_authenticated_calls += 1
        return True

    def close(self):
        self.close_calls += 1


class _DummyConfig:
    def __init__(self, storage_dir: Path, has_saved_session: bool):
        self.storage_dir = storage_dir
        self.CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
        self._has_saved_session = has_saved_session
        self._browser = _DummyBrowser()

    def has_saved_session(self) -> bool:
        return self._has_saved_session

    def get_browser(self) -> _DummyBrowser:
        return self._browser


class _DummyClient:
    def __init__(self, config: _DummyConfig):
        self.config = config
        self.calls = 0

    @cached
    def list_items(self, limit: int = 1) -> list[dict]:
        self.calls += 1
        return [{"id": str(limit)}]


def test_browser_session_cache_hit_does_not_launch_live_auth_probe(monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_ENABLED", "true")
    config = _DummyConfig(tmp_path, has_saved_session=True)
    client = _DummyClient(config)

    assert client.list_items(limit=1) == [{"id": "1"}]
    assert client.calls == 1

    assert client.list_items(limit=1) == [{"id": "1"}]
    assert client.calls == 1
    assert config.get_browser().is_authenticated_calls == 0
    assert config.get_browser().close_calls == 0


def test_browser_session_cache_hit_is_rejected_when_session_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_ENABLED", "true")
    config = _DummyConfig(tmp_path, has_saved_session=False)
    client = _DummyClient(config)

    assert client.list_items(limit=1) == [{"id": "1"}]
    assert client.calls == 1

    assert client.list_items(limit=1) == [{"id": "1"}]
    assert client.calls == 2


class _MixedCredentialConfig(_DummyConfig):
    """Config for a CLI declaring OAuth *and* a browser session (e.g. eBay)."""

    def __init__(self, storage_dir: Path, has_saved_session: bool):
        super().__init__(storage_dir, has_saved_session=has_saved_session)
        self.CREDENTIAL_TYPES = [
            CredentialType.OAUTH_AUTHORIZATION_CODE,
            CredentialType.BROWSER_SESSION,
        ]


class _MixedCredentialClient:
    """One client with an API-backed cached read and a browser-backed one."""

    def __init__(self, config: _MixedCredentialConfig):
        self.config = config
        self.api_calls = 0
        self.browser_calls = 0

    @cached
    def search_api(self, keyword: str) -> list[dict]:
        self.api_calls += 1
        return [{"keyword": keyword}]

    @cached(credential_type=CredentialType.BROWSER_SESSION)
    def scrape_page(self, keyword: str) -> list[dict]:
        self.browser_calls += 1
        return [{"keyword": keyword}]


def test_mixed_credential_api_method_is_cached_without_a_browser_session(
    monkeypatch, tmp_path
):
    """The browser-session gate must not reach an API-backed cached method.

    eBay declares OAuth and a browser session. Its SoldComps search needs
    neither the browser nor a saved session, so gating it on one spent a paid
    API request on every repeat call whenever no session was saved.
    """
    monkeypatch.setenv("CACHE_ENABLED", "true")
    client = _MixedCredentialClient(
        _MixedCredentialConfig(tmp_path, has_saved_session=False)
    )

    assert client.search_api("LEGO 75192") == [{"keyword": "LEGO 75192"}]
    assert client.api_calls == 1

    assert client.search_api("LEGO 75192") == [{"keyword": "LEGO 75192"}]
    assert client.api_calls == 1


def test_mixed_credential_browser_method_still_requires_a_saved_session(
    monkeypatch, tmp_path
):
    """A method that declares the browser session keeps the original gate."""
    monkeypatch.setenv("CACHE_ENABLED", "true")
    client = _MixedCredentialClient(
        _MixedCredentialConfig(tmp_path, has_saved_session=False)
    )

    assert client.scrape_page("LEGO 75192") == [{"keyword": "LEGO 75192"}]
    assert client.browser_calls == 1

    assert client.scrape_page("LEGO 75192") == [{"keyword": "LEGO 75192"}]
    assert client.browser_calls == 2


def test_mixed_credential_browser_method_serves_cache_with_a_saved_session(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CACHE_ENABLED", "true")
    client = _MixedCredentialClient(
        _MixedCredentialConfig(tmp_path, has_saved_session=True)
    )

    assert client.scrape_page("LEGO 75192") == [{"keyword": "LEGO 75192"}]
    assert client.browser_calls == 1

    assert client.scrape_page("LEGO 75192") == [{"keyword": "LEGO 75192"}]
    assert client.browser_calls == 1
