import json
import time

from typer.testing import CliRunner

from paypal_cli.client import PayPalApiClient
from paypal_cli.commands.transactions import app as transactions_app


runner = CliRunner()


class _FakeConfig:
    def __init__(self):
        self.client_id = "client-id"
        self.client_secret = "client-secret"
        self.api_base_url = "https://api-m.paypal.com"
        self.access_token = "token"
        self.token_expires_at = str(time.time() + 3600)

    def has_credentials(self):
        return True

    def get_missing_credentials(self):
        return []

    def save_tokens(self, access_token, token_expires_at):
        self.access_token = access_token
        self.token_expires_at = token_expires_at


def test_normalize_transaction_range_supports_dates_and_datetimes():
    start_date, end_date = PayPalApiClient.normalize_transaction_range(
        "2026-05-01",
        "2026-05-02T09:15:00-05:00",
    )

    assert PayPalApiClient.format_transaction_datetime(start_date) == "2026-05-01T00:00:00Z"
    assert PayPalApiClient.format_transaction_datetime(end_date) == "2026-05-02T14:15:00Z"


def test_iter_transaction_windows_splits_ranges_into_31_day_chunks():
    start_date, end_date = PayPalApiClient.normalize_transaction_range(
        "2026-04-01",
        "2026-05-31",
    )

    windows = list(PayPalApiClient.iter_transaction_windows(start_date, end_date))

    assert [
        (
            PayPalApiClient.format_transaction_datetime(window_start),
            PayPalApiClient.format_transaction_datetime(window_end),
        )
        for window_start, window_end in windows
    ] == [
        ("2026-04-01T00:00:00Z", "2026-05-01T23:59:59Z"),
        ("2026-05-02T00:00:00Z", "2026-05-31T23:59:59Z"),
    ]


def test_list_transactions_pages_windows_and_applies_filters(monkeypatch):
    monkeypatch.setattr("paypal_cli.client.get_config", lambda: _FakeConfig())

    responses = {
        ("2026-04-01T00:00:00Z", "2026-05-01T23:59:59Z", 1): {
            "page": 1,
            "total_pages": 2,
            "transaction_details": [
                {
                    "transaction_info": {
                        "transaction_id": "APR-1",
                        "transaction_status": "P",
                    }
                },
                {
                    "transaction_info": {
                        "transaction_id": "APR-2",
                        "transaction_status": "S",
                    }
                },
            ],
        },
        ("2026-04-01T00:00:00Z", "2026-05-01T23:59:59Z", 2): {
            "page": 2,
            "total_pages": 2,
            "transaction_details": [
                {
                    "transaction_info": {
                        "transaction_id": "APR-3",
                        "transaction_status": "S",
                    }
                }
            ],
        },
        ("2026-05-02T00:00:00Z", "2026-05-31T23:59:59Z", 1): {
            "page": 1,
            "total_pages": 1,
            "transaction_details": [
                {
                    "transaction_info": {
                        "transaction_id": "MAY-1",
                        "transaction_status": "S",
                    }
                },
                {
                    "transaction_info": {
                        "transaction_id": "MAY-2",
                        "transaction_status": "P",
                    }
                },
            ],
        },
    }
    calls = []

    def fake_request(method, url, headers, json, params):
        calls.append({"method": method, "url": url, "headers": headers, "params": params})

        class Response:
            status_code = 200
            ok = True
            text = ""

            def json(self_inner):
                key = (params["start_date"], params["end_date"], params["page"])
                return responses[key]

        return Response()

    monkeypatch.setattr("requests.request", fake_request)

    client = PayPalApiClient()
    transactions = client.list_transactions(
        start_date="2026-04-01",
        end_date="2026-05-31",
        limit=3,
        filters=["transaction_info.transaction_status:eq:S"],
        page_size=2,
        balance_affecting_records_only="N",
    )

    assert [item["transaction_info"]["transaction_id"] for item in transactions] == ["APR-2", "APR-3", "MAY-1"]
    assert [call["params"]["page"] for call in calls] == [1, 2, 1]
    assert all(call["params"]["fields"] == "all" for call in calls)
    assert all(call["params"]["page_size"] == 2 for call in calls)
    assert all(call["params"]["balance_affecting_records_only"] == "N" for call in calls)
    assert all("transaction_id" not in call["params"] for call in calls)
    assert all(call["headers"]["PayPal-Enforce-ISO8601-Format"] == "true" for call in calls)


def test_get_transaction_searches_by_transaction_id(monkeypatch):
    monkeypatch.setattr("paypal_cli.client.get_config", lambda: _FakeConfig())
    calls = []

    def fake_request(method, url, headers, json, params):
        calls.append(params)

        class Response:
            status_code = 200
            ok = True
            text = ""

            def json(self_inner):
                return {
                    "page": 1,
                    "total_pages": 1,
                    "transaction_details": [
                        {"transaction_info": {"transaction_id": "TXN-1234567890123"}}
                    ],
                }

        return Response()

    monkeypatch.setattr("requests.request", fake_request)

    client = PayPalApiClient()
    result = client.get_transaction(
        transaction_id="TXN-1234567890123",
        start_date="2026-05-01",
        end_date="2026-05-31",
        page_size=50,
        balance_affecting_records_only="N",
    )

    assert result["matching_transaction_count"] == 1
    assert calls[0]["transaction_id"] == "TXN-1234567890123"
    assert calls[0]["page_size"] == 50
    assert calls[0]["balance_affecting_records_only"] == "N"


def test_transactions_list_applies_properties_filter_in_json_output(monkeypatch):
    class FakeClient:
        def list_transactions(self, **kwargs):
            assert kwargs["start_date"] == "2026-05-01"
            assert kwargs["end_date"] == "2026-05-31"
            assert kwargs["limit"] == 2
            assert kwargs["page_size"] == 50
            assert kwargs["balance_affecting_records_only"] == "Y"
            return [
                {
                    "transaction_info": {
                        "transaction_id": "TXN-1",
                        "transaction_initiation_date": "2026-05-01T10:00:00Z",
                    },
                    "payer_info": {"email_address": "buyer@example.com"},
                }
            ]

    monkeypatch.setattr("paypal_cli.commands.transactions.get_api_client", lambda: FakeClient())

    result = runner.invoke(
        transactions_app,
        [
            "list",
            "--start-date",
            "2026-05-01",
            "--end-date",
            "2026-05-31",
            "--limit",
            "2",
            "--page-size",
            "50",
            "--properties",
            "transaction_info.transaction_id,payer_info.email_address",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {
            "transaction_info.transaction_id": "TXN-1",
            "payer_info.email_address": "buyer@example.com",
        }
    ]


def test_transactions_get_applies_properties_filter(monkeypatch):
    class FakeClient:
        def get_transaction(self, **kwargs):
            assert kwargs["transaction_id"] == "TXN-1234567890123"
            assert kwargs["start_date"] == "2026-05-01"
            assert kwargs["end_date"] == "2026-05-31"
            return {
                "transaction_id": "TXN-1234567890123",
                "matching_transaction_count": 1,
                "transaction_details": [
                    {
                        "transaction_info": {
                            "transaction_id": "TXN-1234567890123",
                            "transaction_status": "S",
                        },
                        "payer_info": {"email_address": "buyer@example.com"},
                    }
                ],
            }

    monkeypatch.setattr("paypal_cli.commands.transactions.get_api_client", lambda: FakeClient())

    result = runner.invoke(
        transactions_app,
        [
            "get",
            "TXN-1234567890123",
            "--start-date",
            "2026-05-01",
            "--end-date",
            "2026-05-31",
            "--properties",
            "transaction_info.transaction_id,payer_info.email_address",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "transaction_id": "TXN-1234567890123",
        "matching_transaction_count": 1,
        "transaction_details": [
            {
                "transaction_info.transaction_id": "TXN-1234567890123",
                "payer_info.email_address": "buyer@example.com",
            }
        ],
    }
