import pytest
import typer

from cli_tools_shared.app_factory import run_app
from cli_tools_shared.exceptions import ConfigError


def test_run_app_handles_config_error_by_default(capsys):
    class BrokenApp:
        def __call__(self):
            raise ConfigError("Multiple active profiles found")

    with pytest.raises(typer.Exit) as exc:
        run_app(BrokenApp())

    assert exc.value.exit_code == 2
    assert "Error: Multiple active profiles found" in capsys.readouterr().err
