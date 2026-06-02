from ring_cli.commands.auth import _login_handler
from ring_cli.commands.auth import _read_otp_code


class FakeConfig:
    def __init__(self):
        self.email = "user@example.com"
        self.password = "secret"
        self.clear_token_calls = 0
        self.saved = {"OTP_CODE": "legacy-code"}

    def clear_token(self):
        self.clear_token_calls += 1

    def _get(self, key):
        return self.saved[key]

    def _set(self, key, value):
        self.saved[key] = value


def test_login_handler_clears_cached_token_when_forced(monkeypatch):
    calls = {}

    class FakeRingClient:
        def __init__(self, config):
            calls["config"] = config

        def login(self, username, password, otp_callback):
            calls["username"] = username
            calls["password"] = password
            calls["otp_code"] = otp_callback()

    monkeypatch.setattr("ring_cli.commands.auth.RingClient", FakeRingClient)
    monkeypatch.setattr("ring_cli.commands.auth._read_otp_code", lambda: "123456")

    config = FakeConfig()
    _login_handler(config, force=True)

    assert calls == {
        "config": config,
        "username": "user@example.com",
        "password": "secret",
        "otp_code": "123456",
    }
    assert config.clear_token_calls == 1
    assert config.saved["OTP_CODE"] == ""


def test_login_handler_keeps_cached_token_without_force(monkeypatch):
    class FakeRingClient:
        def __init__(self, config):
            self.config = config

        def login(self, username, password, otp_callback):
            assert username == "user@example.com"
            assert password == "secret"
            assert otp_callback() == "123456"

    monkeypatch.setattr("ring_cli.commands.auth.RingClient", FakeRingClient)
    monkeypatch.setattr("ring_cli.commands.auth._read_otp_code", lambda: "123456")

    config = FakeConfig()
    _login_handler(config, force=False)

    assert config.clear_token_calls == 0
    assert config.saved["OTP_CODE"] == ""


def test_read_otp_code_uses_stdin(monkeypatch, capsys):
    class FakeStdin:
        def readline(self):
            return "654321\n"

    monkeypatch.setattr("ring_cli.commands.auth.sys.stdin", FakeStdin())

    assert _read_otp_code() == "654321"
    assert capsys.readouterr().err == "Enter Ring 2FA code: "
