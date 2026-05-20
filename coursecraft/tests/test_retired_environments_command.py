from typer.testing import CliRunner

from coursecraft_cli.main import app


runner = CliRunner()


def test_environments_command_is_not_registered():
    result = runner.invoke(app, ["--help"], terminal_width=200)

    assert result.exit_code == 0
    assert "environments" not in result.output


def test_environments_command_is_rejected():
    result = runner.invoke(app, ["environments", "list"], terminal_width=200)

    assert result.exit_code == 2
    assert "No such command 'environments'" in result.output
