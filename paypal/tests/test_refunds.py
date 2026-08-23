import json
import time
from datetime import datetime, timezone

from typer.testing import CliRunner

from paypal_cli.browser_client import PayPalBrowserClient, order_match_context
from paypal_cli.client import PayPalApiClient


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


def test_refund_capture_full_uses_empty_payload_and_idempotency_header(monkeypatch):
    monkeypatch.setattr("paypal_cli.client.get_config", lambda: _FakeConfig())
    calls = []

    def fake_request(method, url, headers, json, params):
        calls.append({"method": method, "url": url, "headers": headers, "json": json, "params": params})

        class Response:
            status_code = 201
            ok = True
            text = ""

            def json(self):
                return {
                    "id": "REFUND-1",
                    "status": "COMPLETED",
                    "amount": {"value": "12.34", "currency_code": "USD"},
                }

        return Response()

    monkeypatch.setattr("requests.request", fake_request)

    result = PayPalApiClient().refund_capture(
        capture_id="CAPTURE-123",
        idempotency_key="refund-CAPTURE-123-full",
    )

    assert result["refund"]["id"] == "REFUND-1"
    assert result["request"]["capture_id"] == "CAPTURE-123"
    assert result["request"]["refund_type"] == "full"
    assert calls == [
        {
            "method": "POST",
            "url": "https://api-m.paypal.com/v2/payments/captures/CAPTURE-123/refund",
            "headers": {
                "Authorization": "Bearer token",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "PayPal-Request-Id": "refund-CAPTURE-123-full",
            },
            "json": {},
            "params": None,
        }
    ]


def test_refund_capture_partial_uses_amount_payload(monkeypatch):
    monkeypatch.setattr("paypal_cli.client.get_config", lambda: _FakeConfig())
    payloads = []

    def fake_request(method, url, headers, json, params):
        payloads.append(json)

        class Response:
            status_code = 201
            ok = True
            text = ""

            def json(self):
                return {"id": "REFUND-2", "status": "COMPLETED"}

        return Response()

    monkeypatch.setattr("requests.request", fake_request)

    result = PayPalApiClient().refund_capture(
        capture_id="CAPTURE-123",
        amount="4.50",
        currency="USD",
        invoice_id="BL-12345",
        custom_id="bricklink:12345",
        note_to_payer="Missing part refund",
        idempotency_key="refund-CAPTURE-123-4.50",
    )

    assert result["request"]["refund_type"] == "partial"
    assert payloads == [
        {
            "amount": {"value": "4.50", "currency_code": "USD"},
            "invoice_id": "BL-12345",
            "custom_id": "bricklink:12345",
            "note_to_payer": "Missing part refund",
        }
    ]


def test_refunds_create_requires_yes_without_dry_run(monkeypatch):
    from paypal_cli.commands.refunds import app as refunds_app

    class FakeClient:
        def refund_capture(self, **kwargs):
            raise AssertionError("mutation must not run without --yes")

    monkeypatch.setattr("paypal_cli.commands.refunds.get_api_client", lambda: FakeClient())

    result = runner.invoke(refunds_app, ["create", "CAPTURE-123"])

    assert result.exit_code == 1
    assert "Refusing to issue refund without --yes or --dry-run" in result.stderr


def test_refund_commands_are_registered_without_preflight_auth_for_dry_run():
    from paypal_cli.commands.refunds import COMMAND_CREDENTIALS

    assert COMMAND_CREDENTIALS == {
        "create": ["no_auth"],
        "from-bricklink": ["no_auth"],
    }


def test_bricklink_subprocess_does_not_inherit_paypal_config_env(monkeypatch):
    from paypal_cli.commands.refunds import get_bricklink_order

    captured = {}
    monkeypatch.setenv("BASE_URL", "https://api-m.paypal.com")
    monkeypatch.setenv("CLIENT_ID", "paypal-client-id")
    monkeypatch.setenv("CLIENT_SECRET", "paypal-client-secret")
    monkeypatch.setenv("UNRELATED_ENV", "kept")

    def fake_run(args, check, capture_output, env, text):
        captured["args"] = args
        captured["env"] = env

        class Completed:
            returncode = 0
            stdout = json.dumps(_bricklink_order())
            stderr = ""

        return Completed()

    monkeypatch.setattr("paypal_cli.commands.refunds.subprocess.run", fake_run)

    assert get_bricklink_order("12345")["order_id"] == 12345
    assert captured["args"] == ["bricklink", "order", "get", "12345"]
    assert "BASE_URL" not in captured["env"]
    assert "CLIENT_ID" not in captured["env"]
    assert "CLIENT_SECRET" not in captured["env"]
    assert captured["env"]["UNRELATED_ENV"] == "kept"


def test_refunds_create_dry_run_outputs_precise_plan(monkeypatch):
    from paypal_cli.commands.refunds import app as refunds_app

    class FakeClient:
        def refund_capture(self, **kwargs):
            raise AssertionError("dry-run must not call refund API")

    monkeypatch.setattr("paypal_cli.commands.refunds.get_api_client", lambda: FakeClient())

    result = runner.invoke(
        refunds_app,
        ["create", "CAPTURE-123", "--amount", "4.50", "--currency", "USD", "--dry-run"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "dry_run": True,
        "request": {
            "capture_id": "CAPTURE-123",
            "refund_type": "partial",
            "amount": {"value": "4.50", "currency_code": "USD"},
            "invoice_id": None,
            "custom_id": None,
            "note_to_payer": None,
            "idempotency_key": "paypal-refund-CAPTURE-123-4.50-USD",
        },
    }


class _FakePage:
    def __init__(self, transactions=None, refund_details=None, refund_response=None):
        self.transactions = transactions or []
        self.refund_details = refund_details or {}
        self.refund_response = refund_response or {"data": {"redirectUrl": "/activity/payment/TXN-1"}}
        self.requests = []
        self.url = "https://www.paypal.com/mep/unifiedtransactions?filter=0&query="

    def evaluate(self, code, arg=None):
        if arg is None:
            return {"status": 200, "statusText": "OK", "text": json.dumps({"_csrf": "csrf-token"})}
        self.requests.append(arg)
        path = arg["path"]
        if path == "/unifiedtransactions/v1/transactions":
            return {
                "status": 200,
                "statusText": "OK",
                "text": json.dumps({"transactions": self.transactions}),
            }
        if path.startswith("/unifiedtransactions/v1/refund/edit/"):
            return {
                "status": 200,
                "statusText": "OK",
                "text": json.dumps({"data": self.refund_details}),
            }
        if path.startswith("/unifiedtransactions/v1/refund/issue-refund/"):
            return {
                "status": 200,
                "statusText": "OK",
                "text": json.dumps(self.refund_response),
            }
        raise AssertionError(f"unexpected PayPal path: {path}")


class _FakeBrowser:
    def __init__(self, page):
        self.page = page
        self.urls = []
        self.closed = False

    def get_page(self, url):
        self.urls.append(url)
        return self.page

    def close(self):
        self.closed = True


def _bricklink_order():
    return {
        "order_id": 12345,
        "buyer_name": "ClubsBricks",
        "buyer_email": "buyer@example.com",
        "date_ordered": "2026-06-08T20:59:39.527Z",
        "payment": {
            "method": "PayPal (Onsite)",
            "currency_code": "USD",
            "date_paid": "2026-06-08T20:59:39.527Z",
        },
        "shipping": {
            "address": {
                "name": {"full": "Shawn Smith"},
            }
        },
        "cost": {
            "currency_code": "USD",
            "grand_total": "25.4900",
        },
    }


def _paypal_transaction(status_content="Completed", status_value="COMPLETED"):
    return {
        "id": "TXN-1",
        "createTime": "6/8/26, 1:59 PM",
        "description": "Payment from",
        "name": "Shawn Smith",
        "status": {"content": status_content, "value": status_value},
        "gross": "$25.49 USD",
        "type": "PAYMENT",
        "currency": "USD",
        "actions": [{"name": "REFUND", "link": "/activity/actions/refund/edit/TXN-1"}],
    }


def _paypal_refund_details():
    return {
        "id": "TXN-1",
        "amount": {
            "grossAmount": {"value": "25.49", "currencyCode": "USD", "currency": "$25.49 USD"},
            "maxAllowedRefundAmount": {
                "value": "25.49",
                "formattedValue": "25.49",
                "currencyCode": "USD",
                "currency": "$25.49 USD",
            },
        },
        "counterPartyData": {"name": "Shawn Smith", "email": "buyer@example.com"},
    }


def test_browser_transaction_search_uses_zero_based_month_payload():
    page = _FakePage(transactions=[_paypal_transaction()])
    browser = _FakeBrowser(page)
    client = PayPalBrowserClient(config=object(), browser=browser)

    result = client.search_transactions(
        "buyer@example.com",
        datetime(2026, 6, 8, 0, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 6, 8, 23, 59, 59, tzinfo=timezone.utc),
    )

    assert result == [_paypal_transaction()]
    request = page.requests[0]
    assert request["path"] == "/unifiedtransactions/v1/transactions"
    assert request["jsonBody"]["search_text"] == "buyer@example.com"
    assert request["jsonBody"]["start_time"]["month"] == 5
    assert request["jsonBody"]["end_time"]["month"] == 5


def test_browser_client_matches_bricklink_order_by_email_name_amount_and_refundability():
    page = _FakePage(transactions=[_paypal_transaction()], refund_details=_paypal_refund_details())
    browser = _FakeBrowser(page)
    client = PayPalBrowserClient(config=object(), browser=browser)

    match = client.find_payment_for_order(_bricklink_order(), order_id="12345", refund_amount="4.50")

    assert match["order"]["buyer_email"] == "buyer@example.com"
    assert match["transaction"]["id"] == "TXN-1"
    assert match["refund_details"]["amount"]["maxAllowedRefundAmount"]["value"] == "25.49"
    assert match["search"]["terms"] == ["buyer@example.com", "Shawn Smith", "ClubsBricks"]


def test_browser_client_matches_partially_refunded_paypal_payment_when_refundable():
    page = _FakePage(
        transactions=[_paypal_transaction(status_content="Partially refunded", status_value="PARTIALLY_REFUNDED")],
        refund_details=_paypal_refund_details(),
    )
    browser = _FakeBrowser(page)
    client = PayPalBrowserClient(config=object(), browser=browser)

    match = client.find_payment_for_order(_bricklink_order(), order_id="12345", refund_amount="4.50")

    assert match["transaction"]["id"] == "TXN-1"
    assert match["transaction"]["status"]["content"] == "Partially refunded"


def test_browser_client_rejects_pending_paypal_payment_even_when_refundable():
    page = _FakePage(
        transactions=[_paypal_transaction(status_content="Pending", status_value="PENDING")],
        refund_details=_paypal_refund_details(),
    )
    browser = _FakeBrowser(page)
    client = PayPalBrowserClient(config=object(), browser=browser)

    try:
        client.find_payment_for_order(_bricklink_order(), order_id="12345", refund_amount="4.50")
    except Exception as exc:
        assert "No PayPal payment matched BrickLink order 12345" in str(exc)
    else:
        raise AssertionError("pending PayPal payments must not match")


def test_browser_refund_payment_uses_paypal_issue_refund_endpoint():
    page = _FakePage(refund_response={"data": {"redirectUrl": "/activity/payment/TXN-1"}})
    browser = _FakeBrowser(page)
    client = PayPalBrowserClient(config=object(), browser=browser)

    result = client.refund_payment(
        transaction_id="TXN-1",
        amount="4.50",
        currency="USD",
        invoice_number="BL-12345",
        note_to_buyer="Missing part refund",
    )

    request = page.requests[0]
    assert request["path"] == "/unifiedtransactions/v1/refund/issue-refund/TXN-1"
    assert request["jsonBody"] == {
        "currencyCode": "USD",
        "totalAmt": "4.50",
        "invoiceNumber": "BL-12345",
        "noteToBuyer": "Missing part refund",
        "txnId": "TXN-1",
    }
    assert result["refund"] == {"data": {"redirectUrl": "/activity/payment/TXN-1"}}


def test_order_match_context_rejects_non_paypal_order():
    order = _bricklink_order()
    order["payment"]["method"] = "Credit card"

    try:
        order_match_context("12345", order)
    except Exception as exc:
        assert "not a PayPal payment" in str(exc)
    else:
        raise AssertionError("expected non-PayPal order to be rejected")


def test_refunds_from_bricklink_dry_run_uses_browser_match(monkeypatch):
    from paypal_cli.commands.refunds import app as refunds_app

    calls = {}

    def fake_bricklink_order(order_id):
        calls["order_id"] = order_id
        return _bricklink_order()

    class FakeBrowserClient:
        def find_payment_for_order(self, bricklink_order, order_id, refund_amount=None):
            calls["match_args"] = {
                "bricklink_order": bricklink_order,
                "order_id": order_id,
                "refund_amount": refund_amount,
            }
            return {
                "order": {"currency": "USD"},
                "transaction": {"id": "TXN-1"},
                "refund_details": _paypal_refund_details(),
            }

        def refund_payment(self, **kwargs):
            raise AssertionError("dry-run must not issue a PayPal refund")

        def close(self):
            calls["closed"] = True

    monkeypatch.setattr("paypal_cli.commands.refunds.get_bricklink_order", fake_bricklink_order)
    monkeypatch.setattr("paypal_cli.commands.refunds.get_browser_client", lambda: FakeBrowserClient())

    result = runner.invoke(
        refunds_app,
        ["from-bricklink", "12345", "--amount", "4.50", "--details", "Missing part refund", "--dry-run"],
    )

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["bricklink_order"]["order_id"] == 12345
    assert output["paypal_match"]["transaction"]["id"] == "TXN-1"
    assert output["request"] == {
        "transaction_id": "TXN-1",
        "refund_type": "partial",
        "amount": {"value": "4.50", "currency_code": "USD"},
        "invoice_number": "BL-12345",
        "note_to_buyer": "Missing part refund",
    }
    assert calls["match_args"] == {
        "bricklink_order": _bricklink_order(),
        "order_id": "12345",
        "refund_amount": "4.50",
    }


def test_refunds_from_bricklink_can_use_verified_order_json_file(monkeypatch, tmp_path):
    from paypal_cli.commands.refunds import app as refunds_app

    calls = {}
    order_file = tmp_path / "order-context.json"
    order_file.write_text(json.dumps({"order": _bricklink_order()}), encoding="utf-8")

    def fail_bricklink_order(order_id):
        raise AssertionError("order-json path must not call bricklink order get")

    class FakeBrowserClient:
        def find_payment_for_order(self, bricklink_order, order_id, refund_amount=None):
            calls["bricklink_order"] = bricklink_order
            return {
                "order": {"currency": "USD"},
                "transaction": {"id": "TXN-1"},
                "refund_details": _paypal_refund_details(),
            }

        def refund_payment(self, **kwargs):
            raise AssertionError("dry-run must not issue a PayPal refund")

        def close(self):
            calls["closed"] = True

    monkeypatch.setattr("paypal_cli.commands.refunds.get_bricklink_order", fail_bricklink_order)
    monkeypatch.setattr("paypal_cli.commands.refunds.get_browser_client", lambda: FakeBrowserClient())

    result = runner.invoke(
        refunds_app,
        [
            "from-bricklink",
            "12345",
            "--amount",
            "4.50",
            "--order-json",
            str(order_file),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert calls["bricklink_order"] == _bricklink_order()
    assert calls["closed"] is True


def test_refunds_from_bricklink_live_requires_yes(monkeypatch):
    from paypal_cli.commands.refunds import app as refunds_app

    class FakeBrowserClient:
        def find_payment_for_order(self, bricklink_order, order_id, refund_amount=None):
            return {
                "order": {"currency": "USD"},
                "transaction": {"id": "TXN-1"},
                "refund_details": _paypal_refund_details(),
            }

        def refund_payment(self, **kwargs):
            raise AssertionError("mutation must not run without --yes")

        def close(self):
            pass

    monkeypatch.setattr("paypal_cli.commands.refunds.get_bricklink_order", lambda order_id: _bricklink_order())
    monkeypatch.setattr("paypal_cli.commands.refunds.get_browser_client", lambda: FakeBrowserClient())

    result = runner.invoke(refunds_app, ["from-bricklink", "12345", "--amount", "4.50"])

    assert result.exit_code == 1
    assert "Refusing to issue refund without --yes or --dry-run" in result.stderr
