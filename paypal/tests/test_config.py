from cli_tools_shared.credentials import CredentialType

from paypal_cli.config import Config


def test_paypal_uses_static_oauth_client_credentials():
    assert Config.CREDENTIAL_TYPES == [CredentialType.OAUTH]
    assert Config.OAUTH_TOKEN_EXPIRES is False
    assert Config.OAUTH_STATIC_REQUIRED_FIELDS == ("CLIENT_ID", "CLIENT_SECRET")


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
