from cli_tools_shared.credentials import CredentialType

from ring_cli.config import Config


def test_config_uses_ring_doorbell_bootstrap_auth():
    assert Config.CREDENTIAL_TYPES == [CredentialType.USERNAME_PASSWORD]
    assert Config.AUTH_EXTRA_PROMPTS == [
        ("OTP_CODE", "Ring 2FA code (sent to your phone/email at login)", False),
    ]


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
    assert config.token_file.parent.parent.name == ".profiles"

    config.clear_token()

    assert config.has_token() is False
    assert config.load_token() is None
