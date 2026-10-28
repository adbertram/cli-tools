"""Missing required manual device credentials never prompt or save partial config."""
from unittest.mock import Mock, patch
from typer.testing import CliRunner
from roomba_cli.commands.device import app


def test_missing_manual_credentials_fail_without_saving_or_echoing_values():
    config = Mock()
    with patch("roomba_cli.config.get_config", return_value=config):
        result = CliRunner().invoke(app, ["add", "synthetic", "127.0.0.1", "--blid", "synthetic-private-id"])
    assert result.exit_code == 1
    assert "Missing credentials" in result.stderr
    assert "synthetic-private-id" not in result.output
    config.add_robot.assert_not_called()
