from cli_tools_shared.credentials import CredentialType

from paypal_cli.browser import PayPalBrowser
from paypal_cli.config import Config


def test_paypal_uses_static_oauth_client_credentials_and_browser_session():
    assert Config.CREDENTIAL_TYPES == [CredentialType.OAUTH, CredentialType.BROWSER_SESSION]
    assert Config.OAUTH_TOKEN_EXPIRES is False
    assert Config.OAUTH_STATIC_REQUIRED_FIELDS == ("CLIENT_ID", "CLIENT_SECRET")


def test_paypal_browser_login_uses_manual_no_cdp_mode():
    assert PayPalBrowser.MANUAL_LOGIN is True


def test_profile_path_helpers_use_base_config_contract(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr("paypal_cli.config.resolve_tool_dir", lambda _: tmp_path / "paypal")

    config = Config()

    assert not hasattr(config, "get_profile_dir")
    assert config.get_profiles_dir().name == "authentication_profiles"
    assert config.storage_dir == config.get_profile_data_dir()
    assert config.get_profile_data_dir() == config.get_profiles_dir() / "default"


def test_connection_returns_shared_api_test_shape(monkeypatch, tmp_path):
    class Response:
        ok = True

        def json(self):
            return {
                "app_id": "app-123",
                "scope": "payouts payments",
            }

    calls = {}

    def post(url, headers, data, timeout):
        calls["url"] = url
        calls["headers"] = headers
        calls["data"] = data
        calls["timeout"] = timeout
        return Response()

    monkeypatch.setattr("requests.post", post)
    monkeypatch.setattr("paypal_cli.config.resolve_tool_dir", lambda _: tmp_path)

    config = Config()
    config._set("CLIENT_ID", "client-id")
    config._set("CLIENT_SECRET", "client-secret")

    result = config.test_connection()

    assert result == {
        "api_test": "passed",
        "app_id": "app-123",
        "scope": "payouts payments",
    }
    assert calls["url"] == "https://api-m.paypal.com/v1/oauth2/token"
    assert calls["data"] == "grant_type=client_credentials"
    assert calls["timeout"] == 10
