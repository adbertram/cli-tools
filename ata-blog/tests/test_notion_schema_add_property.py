"""Tests for `ata-blog notion-page schema add-property`.

Covers:
- `--help` exits 0 and exposes --name + --type flags.
- Unsupported type values (e.g. `select`, which requires options) are
  rejected with a non-zero exit before any subprocess call is made.
- Supported (empty-config) types delegate to `notion field add` with the
  exact argv expected, and emit the success JSON on stdout.
- Non-zero exit from the underlying `notion` CLI propagates as a non-zero
  exit and prints the notion CLI's error body on stderr.
"""
import json
import subprocess
from unittest.mock import patch, MagicMock

from typer.testing import CliRunner

from ata_blog_cli.commands import notion_page


runner = CliRunner()


def test_schema_add_property_help_exits_zero_and_exposes_flags():
    # The `schema` Typer is attached as a sub-Typer of the notion-page app;
    # invoking it directly with --help shows the single subcommand's help
    # (newer Typer flattens single-command sub-apps).
    result = runner.invoke(notion_page.schema_app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "--name" in result.output
    assert "--type" in result.output
    assert "rich_text" in result.output
    assert "url" in result.output
    assert "checkbox" in result.output


def test_schema_add_property_rejects_unsupported_type():
    # `select` is intentionally excluded — it requires options.
    result = runner.invoke(
        notion_page.schema_app,
        [
            "DB_ID",
            "--name",
            "Whatever",
            "--type",
            "select",
        ],
    )
    assert result.exit_code == 2
    combined = result.output + (result.stderr if hasattr(result, "stderr") else "")
    assert "not supported" in combined
    assert "select" in combined


@patch("ata_blog_cli.commands.notion_page.get_client")
@patch("ata_blog_cli.commands.notion_page.subprocess.run")
def test_schema_add_property_rich_text_delegates_to_notion_field_add(
    mock_run, mock_get_client
):
    mock_get_client.return_value = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )

    result = runner.invoke(
        notion_page.schema_app,
        [
            "DB_ID_123",
            "--name",
            "Affiliate Promotion",
            "--type",
            "rich_text",
        ],
    )

    assert result.exit_code == 0, result.output
    # Exactly one delegated subprocess call.
    assert mock_run.call_count == 1
    argv = mock_run.call_args[0][0]
    assert argv == [
        "notion",
        "field",
        "add",
        "DB_ID_123",
        "Affiliate Promotion",
        "--type",
        "rich_text",
    ]

    payload = json.loads(result.stdout)
    assert payload == {
        "database_id": "DB_ID_123",
        "property_name": "Affiliate Promotion",
        "type": "rich_text",
        "created": True,
    }


@patch("ata_blog_cli.commands.notion_page.get_client")
@patch("ata_blog_cli.commands.notion_page.subprocess.run")
def test_schema_add_property_propagates_notion_cli_error(mock_run, mock_get_client):
    mock_get_client.return_value = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=1,
        stdout="",
        stderr='{"object":"error","status":404,"code":"object_not_found"}',
    )

    result = runner.invoke(
        notion_page.schema_app,
        [
            "BAD_DB",
            "--name",
            "X",
            "--type",
            "rich_text",
        ],
    )

    assert result.exit_code != 0
    combined = result.output + (result.stderr if hasattr(result, "stderr") else "")
    assert "object_not_found" in combined
