from importlib import import_module

from typer.testing import CliRunner


def test_main_app_imports_and_renders_help():
    module = import_module("amazon_cli.main")

    result = CliRunner().invoke(module.app, ["--help"])

    assert result.exit_code == 0
    assert "Amazon order evidence lookup" in result.stdout
