import json
from unittest.mock import MagicMock

from cli_tools_shared.exceptions import CredentialError
from typer.testing import CliRunner

from amazon_cli import commands
from amazon_cli.browser import AmazonBrowser
from amazon_cli.client import AUTH_BLOCKED_MESSAGE, AmazonClient


def test_page_snapshot_raises_actionable_auth_blocker_when_session_is_stale():
    client = AmazonClient()
    page = MagicMock()
    browser = MagicMock()
    browser.is_authenticated.return_value = False
    browser.get_page.return_value = page
    browser._check_auth.return_value = False
    client._get_browser = MagicMock(return_value=browser)

    try:
        try:
            client._page_snapshot("https://www.amazon.com/gp/css/order-history")
        except CredentialError as exc:
            assert str(exc) == AUTH_BLOCKED_MESSAGE
        else:
            raise AssertionError("Expected stale Amazon session to raise CredentialError")
    finally:
        client.close()

    browser.is_authenticated.assert_called_once_with()
    browser.get_page.assert_not_called()
    page.wait_for_timeout.assert_not_called()
    browser._check_auth.assert_not_called()


def test_amazon_auth_login_uses_manual_browser_completion_path():
    assert AmazonBrowser.MANUAL_LOGIN is True


def test_orders_match_returns_exit_two_with_actionable_auth_blocker(monkeypatch):
    client = MagicMock()
    client.match_order.side_effect = CredentialError(AUTH_BLOCKED_MESSAGE)
    monkeypatch.setattr(commands, "get_client", lambda: client)

    result = CliRunner().invoke(
        commands.app,
        [
            "match",
            "--amount",
            "43.82",
            "--date",
            "2026-06-13",
            "--query",
            "Amazon",
        ],
    )

    assert result.exit_code == 2
    assert result.stdout == ""
    assert f"Error: {AUTH_BLOCKED_MESSAGE}" in result.stderr
    client.close.assert_called_once_with()


def test_orders_match_outputs_top_level_json_array(monkeypatch):
    client = MagicMock()
    client.match_order.return_value = [
        {
            "id": "line-1",
            "line": 1,
            "text": "$43.82",
            "score": 10,
            "matched_amount": True,
            "matched_terms": ["43.82"],
        }
    ]
    monkeypatch.setattr(commands, "get_client", lambda: client)

    result = CliRunner().invoke(
        commands.app,
        [
            "match",
            "--amount",
            "43.82",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == client.match_order.return_value
    client.close.assert_called_once_with()


def test_match_order_adds_reviewer_property_fields(monkeypatch):
    monkeypatch.setenv("CACHE_ENABLED", "false")
    client = AmazonClient()
    client._page_snapshot = MagicMock(
        return_value={
            "url": "https://www.amazon.com/your-orders/orders",
            "title": "Your Orders",
            "texts": [
                "June 13, 2026",
                "$43.82",
                "Amazon order",
            ],
        }
    )

    rows = client.match_order(
        amount="43.82",
        date="June 13, 2026",
        query="Amazon",
        limit=10,
    )

    amount_row = next(row for row in rows if row["text"] == "$43.82")
    date_row = next(row for row in rows if row["text"] == "June 13, 2026")
    summary_row = next(row for row in rows if row["text"] == "Amazon order")

    assert amount_row["total"] == "$43.82"
    assert amount_row["summary"] == "$43.82"
    assert amount_row["match_score"] == amount_row["score"]
    assert date_row["order_date"] == "June 13, 2026"
    assert date_row["summary"] == "June 13, 2026"
    assert summary_row["summary"] == "Amazon order"
