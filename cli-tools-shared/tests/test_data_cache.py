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
