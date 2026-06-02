from cli_tools_shared.credentials import CredentialType

from ring_cli.config import Config
from ring_cli.client import RingClient


def test_config_uses_ring_doorbell_bootstrap_auth():
    assert Config.CREDENTIAL_TYPES == [CredentialType.USERNAME_PASSWORD]
    assert Config.AUTH_EXTRA_PROMPTS == []


def test_token_cache_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr("ring_cli.config.resolve_tool_dir", lambda _: tmp_path)

    config = Config()
    token = {"access_token": "abc", "refresh_token": "xyz"}

    config.clear_token()
    assert config.load_token() is None

    config.save_token(token)

    assert config.has_token() is True
    assert config.load_token() == token
    assert config.token_file.name == "ring_token.json"
    assert config.token_file.parent.name == "default"
    assert config.token_file.parent.parent.name == "authentication_profiles"

    config.clear_token()

    assert config.has_token() is False
    assert config.load_token() is None


def test_ensure_session_closes_auth_when_update_data_fails(monkeypatch):
    closed = {"value": False}

    class FakeConfig:
        USER_AGENT = "ring-cli-test"

        def load_token(self):
            return {"access_token": "token"}

        def save_token(self, token):
            self.token = token

    class FakeAuth:
        def __init__(self, user_agent, token, token_updated_callback):
            self.user_agent = user_agent
            self.token = token
            self.token_updated_callback = token_updated_callback

        async def async_close(self):
            closed["value"] = True

    class FakeRing:
        def __init__(self, auth):
            self.auth = auth

        async def async_create_session(self):
            return None

        async def async_update_data(self):
            raise RuntimeError("Ring rejected session")

    monkeypatch.setattr("ring_cli.client.Auth", FakeAuth)
    monkeypatch.setattr("ring_cli.client.Ring", FakeRing)

    client = RingClient(config=FakeConfig())

    try:
        client._run_async(client._ensure_session())
    except RuntimeError as exc:
        assert str(exc) == "Ring rejected session"
    else:
        raise AssertionError("expected Ring rejected session")

    assert closed["value"] is True
