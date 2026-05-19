import json
import sys

from typer.testing import CliRunner

from cli_tools_shared import command_registry
from clickbank_cli.main import app
from clickbank_cli.commands import products as products_commands
from clickbank_cli.models import ProductCreateResult


class FakeProductsClient:
    def __init__(self):
        self.calls = []

    def create_product(self, sku, params):
        self.calls.append((sku, params))
        return ProductCreateResult(sku=sku)


def test_top_level_help_registers_clickbank_modules():
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "orders" in result.stdout
    assert "products" in result.stdout
    assert "quickstats" in result.stdout
    assert "auth" in result.stdout
    assert "cache" in result.stdout
    assert "items" not in result.stdout


def test_list_command_help_exposes_standard_cli_flags(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(command_registry, "_check_credentials", lambda config, cred_types, cli_name: None)

    for argv in (
        ["orders", "list", "--help"],
        ["products", "list", "--help"],
        ["quickstats", "list", "--help"],
    ):
        monkeypatch.setattr(sys, "argv", ["clickbank", *argv])
        result = runner.invoke(app, argv)
        assert result.exit_code == 0
        assert "--limit" in result.stdout
        assert "--filter" in result.stdout
        assert "--properties" in result.stdout


def test_products_create_parses_repeatable_key_value_params(monkeypatch):
    client = FakeProductsClient()
    monkeypatch.setattr(command_registry, "_check_credentials", lambda config, cred_types, cli_name: None)
    monkeypatch.setattr(products_commands, "get_client", lambda: client)

    result = CliRunner().invoke(
        app,
        [
            "products",
            "create",
            "ABC123",
            "--param",
            "site=acct",
            "--param",
            "currency=USD",
            "--param",
            "language=EN",
            "--param",
            "price=49.95",
            "--param",
            "title=Example Product",
            "--param",
            "digital=true",
            "--param",
            "categories=EBOOK",
            "--param",
            "pitchPage=https://example.com/pitch",
            "--param",
            "thankYouPage=https://example.com/thanks",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"sku": "ABC123"}
    assert client.calls == [
        (
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
    ]
