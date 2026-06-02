from clickbank_cli import client as client_module
from clickbank_cli.client import ClickBankClient
from clickbank_cli.config import Config
from cli_tools_shared.exceptions import ClientError


class FakeConfig:
    def __init__(self, api_key: str = "API-test", base_url: str = "https://api.clickbank.com/rest/1.3"):
        self.api_key = api_key
        self.base_url = base_url

    def has_credentials(self) -> bool:
        return bool(self.api_key)

    def get_missing_credentials(self) -> list[str]:
        return [] if self.api_key else ["API_KEY"]


class FakeResponse:
    def __init__(self, status_code, payload, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = text
        self.content = b"" if payload is None else b"payload"

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload


def test_client_uses_raw_clickbank_api_key_header():
    client = ClickBankClient(config=FakeConfig(api_key="API-raw-key"), max_retries=0)

    assert client.default_headers["Authorization"] == "API-raw-key"
    assert client.default_headers["Accept"] == "application/json"
    assert client.default_headers["Content-Type"] == "application/json"


def test_orders_list_uses_page_header_pagination(monkeypatch):
    calls = []

    def fake_request(method, url, headers=None, params=None, json=None, timeout=None):
        calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "params": params,
                "json": json,
                "timeout": timeout,
            }
        )
        if len(calls) == 1:
            return FakeResponse(
                206,
                [
                    {"receipt": "R1", "transactionType": "SALE"},
                    {"receipt": "R2", "transactionType": "SALE"},
                ],
            )
        return FakeResponse(200, [{"receipt": "R3", "transactionType": "RFND"}])

    monkeypatch.setattr(client_module.requests, "request", fake_request)

    client = ClickBankClient(config=FakeConfig(), max_retries=0)
    orders = client.list_orders(limit=3)

    assert [order.receipt for order in orders] == ["R1", "R2", "R3"]
    assert calls[0]["url"] == "https://api.clickbank.com/rest/1.3/orders2/list"
    assert "Page" not in calls[0]["headers"]
    assert calls[1]["headers"]["Page"] == "2"
    assert calls[0]["json"] is None
    assert calls[1]["json"] is None


def test_create_product_sends_documented_params_in_query_string(monkeypatch):
    calls = []

    def fake_request(method, url, headers=None, params=None, json=None, timeout=None):
        calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "params": params,
                "json": json,
                "timeout": timeout,
            }
        )
        return FakeResponse(200, "ABC123")

    monkeypatch.setattr(client_module.requests, "request", fake_request)

    client = ClickBankClient(config=FakeConfig(), max_retries=0)
    result = client.create_product(
        "ABC123",
        [
            ("site", "acct"),
            ("currency", "USD"),
            ("language", "EN"),
            ("price", "49.95"),
            ("title", "Example Product"),
            ("digital", "true"),
            ("categories", "EBOOK"),
            ("pitchPage", "https://example.com/pitch"),
            ("thankYouPage", "https://example.com/thanks"),
        ],
    )

    assert result.sku == "ABC123"
    assert calls == [
        {
            "method": "PUT",
            "url": "https://api.clickbank.com/rest/1.3/products/ABC123",
            "headers": {
                "Authorization": "API-test",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            "params": [
                ("site", "acct"),
                ("currency", "USD"),
                ("language", "EN"),
                ("price", "49.95"),
                ("title", "Example Product"),
                ("digital", "true"),
                ("categories", "EBOOK"),
                ("pitchPage", "https://example.com/pitch"),
                ("thankYouPage", "https://example.com/thanks"),
            ],
            "json": None,
            "timeout": 30,
        }
    ]


def test_config_test_connection_calls_authenticated_api(monkeypatch):
    monkeypatch.setattr(Config, "has_credentials", lambda self: True)
    monkeypatch.setattr(Config, "get_missing_credentials", lambda self: [])
    monkeypatch.setattr(Config, "api_key", property(lambda self: "API-test"))
    monkeypatch.setattr(
        client_module.ClickBankClient,
        "list_quickstats_accounts",
        lambda self: [
            client_module.QuickstatsAccount(nickName="acct-one"),
            client_module.QuickstatsAccount(nickName="acct-two"),
        ],
    )

    config = Config()
    result = config.test_connection()

    assert result == {
        "api_test": "passed",
        "account_count": 2,
        "accounts": ["acct-one", "acct-two"],
    }


def test_config_test_connection_reports_client_error(monkeypatch):
    monkeypatch.setattr(Config, "has_credentials", lambda self: True)
    monkeypatch.setattr(Config, "get_missing_credentials", lambda self: [])
    monkeypatch.setattr(Config, "api_key", property(lambda self: "API-test"))

    def raise_error(self):
        raise ClientError("HTTP 403: Forbidden")

    monkeypatch.setattr(client_module.ClickBankClient, "list_quickstats_accounts", raise_error)

    config = Config()
    result = config.test_connection()

    assert result == {"api_test": "failed: HTTP 403: Forbidden"}
