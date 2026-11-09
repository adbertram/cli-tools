import json

from typer.testing import CliRunner

from slack_cli.client import SlackClient, _canvas_html_to_text
from slack_cli.commands import canvas

CANVAS_HTML = (
    '<div class="quip-canvas-content"><h1>Canvas: Demo</h1>'
    '<ul><li><span><control id="x"><img alt="e">:emoji:</img></control> '
    '<lnk href="https://docs.google.com/spreadsheets/d/abc/edit">Sheet link</lnk></span></li>'
    '<li><span>Slug: demo</span></li></ul></div>'
)


class _Response:
    text = CANVAS_HTML


def test_canvas_html_to_text_keeps_link_targets_and_drops_controls():
    assert _canvas_html_to_text(CANVAS_HTML) == (
        "Canvas: Demo\nSheet link (https://docs.google.com/spreadsheets/d/abc/edit)\nSlug: demo"
    )


def test_get_canvas_content_reads_file_download(monkeypatch):
    client = object.__new__(SlackClient)
    monkeypatch.setattr(
        client, "_open_file_download", lambda file_id: ({"title": "Canvas: Demo"}, _Response())
    )
    result = client.get_canvas_content("F1")
    assert result["title"] == "Canvas: Demo"
    assert "docs.google.com/spreadsheets" in result["content"]
    assert result["html"] == CANVAS_HTML


def test_canvas_get_command_outputs_json(monkeypatch):
    client = object.__new__(SlackClient)
    monkeypatch.setattr(
        client, "_open_file_download", lambda file_id: ({"title": "Canvas: Demo"}, _Response())
    )
    monkeypatch.setattr(canvas, "get_client", lambda: client)
    result = CliRunner().invoke(canvas.app, ["get", "F1"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["canvas_id"] == "F1"
    assert "docs.google.com/spreadsheets" in data["content"]
    assert "html" not in data
