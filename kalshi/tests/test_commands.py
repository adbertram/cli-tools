import json

import pytest
from cli_tools_shared.exceptions import ClientError
from typer.testing import CliRunner

from kalshi_cli.main import app

runner = CliRunner()
TICKER = "KXBTC15M-26NOV011630-30"


def place(*args):
    return runner.invoke(app, ["orders", "place", TICKER, "--outcome", "yes", "--count", "1", "--price", "0.40", *args])


def test_place_without_yes_or_dry_run_refuses():
    result = place("--demo")
    assert result.exit_code != 0
    assert "Refusing to place order without --yes or --dry-run" in result.output


def test_place_on_production_refuses_without_allow_production():
    result = place("--yes")
    assert result.exit_code != 0
    assert "Refusing to place order on production without --allow-production" in result.output


def test_cancel_without_yes_or_dry_run_refuses():
    result = runner.invoke(app, ["orders", "cancel", "abc", "--demo"])
    assert result.exit_code != 0
    assert "Refusing to cancel order without --yes or --dry-run" in result.output


def test_cancel_on_production_refuses_without_allow_production():
    result = runner.invoke(app, ["orders", "cancel", "abc", "--yes"])
    assert result.exit_code != 0
    assert "without --allow-production" in result.output


def test_dry_run_prints_the_request_and_needs_no_credentials_or_network():
    result = place("--dry-run")
    assert result.exit_code == 0
    request = json.loads(result.output)
    assert request["dry_run"] is True and request["environment"] == "prod"
    assert request["method"] == "POST" and request["path"] == "/portfolio/events/orders"
    assert request["body"]["side"] == "bid" and request["body"]["price"] == "0.4000"


def test_dry_run_for_no_outcome_uses_the_complement():
    result = runner.invoke(app, ["orders", "place", TICKER, "-o", "no", "-c", "2", "--price", "0.30", "--demo", "--dry-run"])
    assert result.exit_code == 0
    body = json.loads(result.output)["body"]
    assert body["side"] == "ask" and body["price"] == "0.7000" and body["count"] == "2"


def test_benchmark_orders_require_confirmation_and_demo():
    result = runner.invoke(app, ["metrics", "get", "--orders", "--demo"])
    assert "Refusing to place benchmark order without --yes or --dry-run" in result.output
    result = runner.invoke(app, ["metrics", "get", "--orders", "--yes"])
    assert "outside the demo exchange" in result.output


def test_presets_list_runs_without_credentials():
    result = runner.invoke(app, ["presets", "list"])
    assert result.exit_code == 0
    assert json.loads(result.output)[0]["series_ticker"] == "KXBTC15M"


class TestProfileSelection:
    """--demo must use the demo profile and prod must never use it, whatever the default profile is."""

    @staticmethod
    def signer_for(monkeypatch, env, runtime, ed_pem):
        import base64

        from kalshi_cli.commands import _common

        seen = {}

        class FakeConfig:
            def __init__(self, profile):
                seen["profile"] = profile
                self.key_id = f"key-{profile}"
                self.private_key = base64.b64encode(ed_pem.encode()).decode()

        monkeypatch.setattr(_common, "get_runtime_profile_resolution", lambda: (runtime, None))
        monkeypatch.setattr(_common, "env_path_for_profile", lambda tool, profile: __import__("pathlib").Path(__file__))
        monkeypatch.setattr(_common, "get_config", lambda profile=None: FakeConfig(profile))
        signer = _common._signer(env)
        return signer, seen["profile"]

    @pytest.mark.parametrize("runtime", [None, "default", "demo"])
    def test_demo_uses_the_demo_profile(self, monkeypatch, ed_pem, runtime):
        signer, profile = self.signer_for(monkeypatch, "demo", runtime, ed_pem)
        assert profile == "demo" and signer.key_id == "key-demo"

    def test_prod_uses_the_default_or_explicit_profile(self, monkeypatch, ed_pem):
        assert self.signer_for(monkeypatch, "prod", "default", ed_pem)[1] == "default"
        assert self.signer_for(monkeypatch, "prod", "trading", ed_pem)[1] == "trading"

    def test_prod_refuses_the_demo_profile(self, monkeypatch, ed_pem):
        with pytest.raises(ClientError, match="Add --demo"):
            self.signer_for(monkeypatch, "prod", "demo", ed_pem)

    def test_demo_refuses_another_explicit_profile(self, monkeypatch, ed_pem):
        with pytest.raises(ClientError, match="cannot be used with the demo exchange"):
            self.signer_for(monkeypatch, "demo", "trading", ed_pem)


class TestOptionValidation:
    def test_limit_has_an_upper_bound(self):
        result = runner.invoke(app, ["markets", "list", "--limit", "100000000"])
        assert result.exit_code != 0 and "10000" in result.output

    @pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
    def test_watch_duration_must_be_positive_and_finite(self, value):
        result = runner.invoke(app, ["stream", "watch", "btc15m", "--duration", value])
        assert result.exit_code != 0

    def test_max_stream_age_must_be_finite(self):
        result = runner.invoke(app, ["markets", "current", "btc15m", "--max-stream-age", "nan"])
        assert result.exit_code != 0 and "finite" in result.output

    @pytest.mark.parametrize("order_id", ["", "o1/../../balance", "a?b"])
    def test_cancel_dry_run_rejects_a_path_changing_id(self, order_id):
        result = runner.invoke(app, ["orders", "cancel", order_id, "--dry-run", "--demo"])
        assert result.exit_code != 0 and "Invalid order ID" in result.output

    def test_place_rejects_blank_ticker(self):
        result = runner.invoke(app, ["orders", "place", " ", "-o", "yes", "-c", "1", "--price", "0.5", "--dry-run"])
        assert result.exit_code != 0 and "Invalid ticker" in result.output


class TestMarketFilters:
    def test_status_and_ticker_filters_become_api_parameters(self):
        from kalshi_cli.commands.markets import FILTER_MAP

        assert FILTER_MAP.to_api_params(["status:eq:active"]) == {"status": "open"}
        assert FILTER_MAP.to_api_params(["status:eq:finalized"]) == {"status": "settled"}
        assert FILTER_MAP.to_api_params(["ticker:in:A|B"]) == {"tickers": "A,B"}
        assert FILTER_MAP.to_api_params(["status:eq:unknown"]) == {}

    def test_empty_series_is_an_error_not_every_market(self):
        result = runner.invoke(app, ["markets", "list", "--series", ""])
        assert result.exit_code != 0 and "preset name or series ticker is required" in result.output


def test_status_option_and_status_filter_do_not_collide(monkeypatch):
    from kalshi_cli.client import KalshiClient

    seen = {}

    def fake_list(self, series=None, status=None, limit=100, **params):
        seen.update(series=series, status=status, params=params)
        return [{"ticker": "M-1", "status": "active"}]

    monkeypatch.setattr(KalshiClient, "list_markets", fake_list)
    result = runner.invoke(app, ["markets", "list", "-s", "btc15m", "--status", "open", "-f", "status:eq:active"])
    assert result.exit_code == 0, result.output
    assert seen["status"] == "open" and seen["series"] == "KXBTC15M"
    result = runner.invoke(app, ["markets", "list", "-f", "status:eq:active"])
    assert seen["status"] == "open"


def test_benchmark_order_dry_run_prints_the_body_with_a_placeholder_ticker():
    result = runner.invoke(app, ["metrics", "get", "--orders", "--dry-run", "--demo"])
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)["body"]
    assert body["ticker"] == "<open market of KXBTC15M>" and body["post_only"] is True and body["price"] == "0.0100"
