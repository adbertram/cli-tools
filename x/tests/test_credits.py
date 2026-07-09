from decimal import Decimal

from typer.testing import CliRunner

from x_cli.commands.credits import _format_amount_usd
from x_cli.main import app


runner = CliRunner()


def test_credits_add_dry_run_returns_plan():
    result = runner.invoke(app, ["credits", "add", "25.00", "--dry-run"])

    assert result.exit_code == 0
    assert '"action": "purchase_credits"' in result.stdout
    assert '"amount_usd": "25.00"' in result.stdout
    assert '"will_open_browser": false' in result.stdout
    assert '"will_submit_purchase": false' in result.stdout
    assert '"would_submit_purchase": true' in result.stdout


def test_credits_add_requires_confirmation_before_submitting_payment():
    result = runner.invoke(app, ["credits", "add", "25.00"])

    assert result.exit_code == 1
    assert "Refusing to purchase $25.00 in X API credits without confirmation." in result.stderr


def test_credits_add_submits_purchase_with_confirmation(monkeypatch):
    def fake_purchase(self, amount_usd):
        return {
            "purchase_submitted": True,
            "amount_usd": amount_usd,
            "payment_success_evidence": "Payment successful",
            "balance_before": "$-0.09",
            "balance_after": "$9.91",
        }

    monkeypatch.setattr("x_cli.commands.credits.XBrowserClient.purchase_credits", fake_purchase)

    result = runner.invoke(app, ["credits", "add", "10.00", "--profile", "browser", "--yes"])

    assert result.exit_code == 0
    assert '"purchase_submitted": true' in result.stdout
    assert '"payment_success_evidence": "Payment successful"' in result.stdout
    assert '"will_submit_purchase": true' in result.stdout


def test_credits_amount_must_be_positive():
    result = runner.invoke(app, ["credits", "add", "0", "--dry-run"])

    assert result.exit_code == 1
    assert "Credit amount must be greater than 0." in result.stderr


def test_credits_amount_must_use_cents():
    result = runner.invoke(app, ["credits", "add", "25.005", "--dry-run"])

    assert result.exit_code == 1
    assert "Credit amount must use dollars and cents" in result.stderr


def test_amount_formatting_preserves_cents():
    assert _format_amount_usd(Decimal("25")) == "25.00"
