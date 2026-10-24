from unittest.mock import patch

from typer.testing import CliRunner

from gemini_cli.main import app

URL = "https://ai.studio/projects"
runner = CliRunner()


def test_topup_prints_url_and_opens_browser() -> None:
    with patch("webbrowser.open") as mock_open:
        result = runner.invoke(app, ["account", "topup"])

    assert result.exit_code == 0
    assert result.stdout.strip() == URL
    mock_open.assert_called_once_with(URL)


def test_topup_no_open_prints_url_only() -> None:
    with patch("webbrowser.open") as mock_open:
        result = runner.invoke(app, ["account", "topup", "--no-open"])

    assert result.exit_code == 0
    assert result.stdout.strip() == URL
    mock_open.assert_not_called()
