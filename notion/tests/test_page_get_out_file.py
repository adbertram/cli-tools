from pathlib import Path

import pytest
from typer.testing import CliRunner

from notion_cli.commands import database as database_cmd
from notion_cli.commands import page as page_cmd


runner = CliRunner()


@pytest.mark.parametrize(
    ("app", "prefix", "module"),
    [
        (database_cmd.app, ["page", "get"], database_cmd),
        (page_cmd.app, ["get"], page_cmd),
    ],
)
@pytest.mark.parametrize(
    "options",
    [
        [],
        ["--include-blocks"],
        ["--markdown"],
    ],
)
def test_out_file_requires_markdown_block_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app,
    prefix: list[str],
    module,
    options: list[str],
):
    output_path = tmp_path / "content.md"
    monkeypatch.setattr(
        module,
        "get_client",
        lambda: pytest.fail("invalid options must fail before creating the API client"),
    )

    result = runner.invoke(
        app,
        [*prefix, "page-1", *options, "--out-file", str(output_path)],
    )

    assert result.exit_code == 1
    assert "Error: --out-file requires --include-blocks and --markdown" in result.stderr
    assert not output_path.exists()


@pytest.mark.parametrize(
    ("app", "prefix", "module"),
    [
        (database_cmd.app, ["page", "get"], database_cmd),
        (page_cmd.app, ["get"], page_cmd),
    ],
)
def test_out_file_writes_markdown_when_required_options_are_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app,
    prefix: list[str],
    module,
):
    class Client:
        def get_page(self, page_id: str):
            assert page_id == "page-1"
            return {"id": page_id, "properties": {}}

        def get_block_children_all(self, page_id: str, recursive: bool):
            assert page_id == "page-1"
            assert recursive is True
            return [
                {
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"plain_text": "Exported content", "annotations": {}}]
                    },
                }
            ]

    output_path = tmp_path / "content.md"
    monkeypatch.setattr(module, "get_client", Client)

    result = runner.invoke(
        app,
        [
            *prefix,
            "page-1",
            "--include-blocks",
            "--markdown",
            "--out-file",
            str(output_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert output_path.read_text(encoding="utf-8") == "Exported content"
