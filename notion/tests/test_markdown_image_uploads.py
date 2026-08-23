"""Regression tests for local Markdown image uploads.

Covers every command that converts Markdown into Notion blocks. A local
``![alt](path.png)`` must become an ``image`` block backed by a Notion
file_upload, a missing local path must fail BEFORE any page mutation, and a
non-filesystem src (``IMAGE_PLACEHOLDER: …``) must stay a verbatim paragraph.
"""

import copy

import pytest
import typer
from typer.testing import CliRunner

from notion_cli import markdown_images
from notion_cli.commands import database as database_cmd
from notion_cli.commands import page as page_cmd


PNG_BYTES = b"\x89PNG\r\n\x1a\n"


def make_png(tmp_path, name="scene.png"):
    path = tmp_path / name
    path.write_bytes(PNG_BYTES)
    return path


class FakeClient:
    """Records every mutating call so tests can assert ordering."""

    def __init__(self):
        self.events = []
        self.uploaded_files = []
        self.uploaded_blocks = []

    # --- file upload -----------------------------------------------------
    def upload_file(self, file_path):
        self.events.append(("upload_file", file_path))
        self.uploaded_files.append(file_path)
        return f"file-upload-{len(self.uploaded_files)}"

    # --- page mutation ---------------------------------------------------
    def clear_page_content(self, page_id):
        self.events.append(("clear_page_content", page_id))

    def _upload_blocks_with_nesting(self, parent_id, blocks, progress_callback=None, after=None):
        self.events.append(("_upload_blocks_with_nesting", parent_id))
        self.uploaded_blocks.append(copy.deepcopy(blocks))
        return len(blocks), [f"new-block-{index}" for index in range(len(blocks))]

    def create_standalone_page(self, parent_page_id, title, children=None, icon=None):
        self.events.append(("create_standalone_page", parent_page_id))
        self.uploaded_blocks.append(copy.deepcopy(children or []))
        return {"id": "page-new", "url": "https://notion.so/page-new"}

    # --- database page creation -----------------------------------------
    def get_database(self, database_id):
        return {"properties": {"Name": {"type": "title"}}}

    def get_data_source_id(self, database_id, data_source_id=None):
        return "data-source-1"

    def create_page(self, database_id, properties):
        self.events.append(("create_page", database_id))
        return {"id": "page-new", "url": "https://notion.so/page-new"}


def image_blocks(blocks):
    return [block for block in blocks if block["type"] == "image"]


def paragraph_texts(blocks):
    texts = []
    for block in blocks:
        if block["type"] != "paragraph":
            continue
        texts.append(
            "".join(item["text"]["content"] for item in block["paragraph"]["rich_text"])
        )
    return texts


# ---------------------------------------------------------------------------
# Scanner contract
# ---------------------------------------------------------------------------


def test_scanner_skips_fenced_code_urls_and_inline_images(tmp_path):
    png = make_png(tmp_path)
    content = "\n".join(
        [
            "# Title",
            "",
            f"![Real]({png})",
            "",
            "```markdown",
            "![Fenced](/does/not/exist.png)",
            "```",
            "",
            "![Remote](https://example.com/a.png)",
            "",
            "![Marker](IMAGE_PLACEHOLDER:scene-2)",
            "",
            "Prose with an inline ![Inline](/does/not/exist.png) reference.",
            "",
            "[IMAGE: a literal bracket line, not markdown]",
        ]
    )
    client = FakeClient()

    uploads = markdown_images.process_markdown_images(content, None, client)

    assert uploads == {str(png): "file-upload-1"}
    assert client.uploaded_files == [str(png)]


def test_scanner_uploads_each_source_once(tmp_path):
    png = make_png(tmp_path)
    content = f"![One]({png})\n\n![Two]({png})\n"
    client = FakeClient()

    uploads = markdown_images.process_markdown_images(content, None, client)

    assert uploads == {str(png): "file-upload-1"}
    assert client.uploaded_files == [str(png)]


def test_scanner_resolves_relative_paths_against_source_file(tmp_path):
    make_png(tmp_path, "scene.png")
    markdown = tmp_path / "article.md"
    markdown.write_text("![Scene](scene.png)\n", encoding="utf-8")
    client = FakeClient()

    uploads = markdown_images.process_markdown_images(
        markdown.read_text(encoding="utf-8"), str(markdown), client
    )

    assert uploads == {"scene.png": "file-upload-1"}
    assert client.uploaded_files == [str(tmp_path / "scene.png")]


def test_scanner_fails_loud_on_unsupported_extension(tmp_path):
    bad = tmp_path / "scene.bmp"
    bad.write_bytes(PNG_BYTES)
    client = FakeClient()

    with pytest.raises(typer.Exit):
        markdown_images.process_markdown_images(f"![Scene]({bad})\n", None, client)

    assert client.uploaded_files == []


# ---------------------------------------------------------------------------
# pages content set
# ---------------------------------------------------------------------------


def test_pages_content_set_file_uploads_local_images(monkeypatch, tmp_path):
    png = make_png(tmp_path)
    markdown = tmp_path / "article.md"
    markdown.write_text(
        "\n".join(
            [
                "# Article",
                "",
                f"![Scene 1: the handoff]({png})",
                "",
                "![Pending](IMAGE_PLACEHOLDER:scene-4)",
                "",
                "[IMAGE: describe scene 5 here]",
                "",
            ]
        ),
        encoding="utf-8",
    )
    client = FakeClient()
    monkeypatch.setattr(page_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        page_cmd.app, ["content", "set", "page-1", "--file", str(markdown)]
    )

    assert result.exit_code == 0, result.output
    blocks = client.uploaded_blocks[0]
    assert image_blocks(blocks) == [
        {
            "object": "block",
            "type": "image",
            "image": {
                "type": "file_upload",
                "file_upload": {"id": "file-upload-1"},
                "caption": [{"type": "text", "text": {"content": "Scene 1: the handoff"}}],
            },
        }
    ]
    assert paragraph_texts(blocks) == [
        "![Pending](IMAGE_PLACEHOLDER:scene-4)",
        "[IMAGE: describe scene 5 here]",
    ]
    # The upload happens before the destructive clear.
    assert [name for name, _ in client.events] == [
        "upload_file",
        "clear_page_content",
        "_upload_blocks_with_nesting",
    ]


def test_pages_content_set_missing_image_fails_before_clear(monkeypatch, tmp_path):
    markdown = tmp_path / "article.md"
    markdown.write_text("# Article\n\n![Scene](missing.png)\n", encoding="utf-8")
    client = FakeClient()
    monkeypatch.setattr(page_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        page_cmd.app, ["content", "set", "page-1", "--file", str(markdown)]
    )

    assert result.exit_code == 1
    assert "do not exist" in result.stderr
    assert "missing.png" in result.stderr
    assert client.events == []


def test_pages_content_set_text_keeps_placeholder_paragraph(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(page_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        page_cmd.app,
        ["content", "set", "page-1", "--text", "![Pending](IMAGE_PLACEHOLDER:scene-9)"],
    )

    assert result.exit_code == 0, result.output
    blocks = client.uploaded_blocks[0]
    assert image_blocks(blocks) == []
    assert paragraph_texts(blocks) == ["![Pending](IMAGE_PLACEHOLDER:scene-9)"]
    assert client.uploaded_files == []


# ---------------------------------------------------------------------------
# pages content append
# ---------------------------------------------------------------------------


def test_pages_content_append_file_uploads_local_images(monkeypatch, tmp_path):
    make_png(tmp_path, "scene.png")
    markdown = tmp_path / "section.md"
    markdown.write_text("![Scene](scene.png)\n", encoding="utf-8")
    client = FakeClient()
    monkeypatch.setattr(page_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        page_cmd.app, ["content", "append", "page-1", "--file", str(markdown)]
    )

    assert result.exit_code == 0, result.output
    assert client.uploaded_files == [str(tmp_path / "scene.png")]
    assert image_blocks(client.uploaded_blocks[0])[0]["image"]["file_upload"] == {
        "id": "file-upload-1"
    }


def test_pages_content_append_missing_image_fails_before_upload(monkeypatch, tmp_path):
    markdown = tmp_path / "section.md"
    markdown.write_text("![Scene](missing.png)\n", encoding="utf-8")
    client = FakeClient()
    monkeypatch.setattr(page_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        page_cmd.app, ["content", "append", "page-1", "--file", str(markdown)]
    )

    assert result.exit_code == 1
    assert "do not exist" in result.stderr
    assert client.events == []


# ---------------------------------------------------------------------------
# pages blocks append
# ---------------------------------------------------------------------------


def test_pages_blocks_append_file_uploads_local_images(monkeypatch, tmp_path):
    make_png(tmp_path, "scene.png")
    markdown = tmp_path / "chapter.md"
    markdown.write_text("![Scene](scene.png)\n", encoding="utf-8")
    client = FakeClient()
    monkeypatch.setattr(page_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        page_cmd.app, ["blocks", "append", "block-1", "--file", str(markdown)]
    )

    assert result.exit_code == 0, result.output
    assert client.uploaded_files == [str(tmp_path / "scene.png")]
    assert image_blocks(client.uploaded_blocks[0])[0]["image"]["type"] == "file_upload"


def test_pages_blocks_append_text_uploads_local_images(monkeypatch, tmp_path):
    png = make_png(tmp_path)
    client = FakeClient()
    monkeypatch.setattr(page_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        page_cmd.app, ["blocks", "append", "block-1", "--text", f"![Scene]({png})"]
    )

    assert result.exit_code == 0, result.output
    assert client.uploaded_files == [str(png)]
    assert image_blocks(client.uploaded_blocks[0])[0]["image"]["type"] == "file_upload"


def test_pages_blocks_append_missing_image_fails_before_append(monkeypatch, tmp_path):
    markdown = tmp_path / "chapter.md"
    markdown.write_text("![Scene](missing.png)\n", encoding="utf-8")
    client = FakeClient()
    monkeypatch.setattr(page_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        page_cmd.app, ["blocks", "append", "block-1", "--file", str(markdown)]
    )

    assert result.exit_code == 1
    assert "do not exist" in result.stderr
    assert client.uploaded_blocks == []


# ---------------------------------------------------------------------------
# pages create --content-file
# ---------------------------------------------------------------------------


def test_pages_create_content_file_uploads_local_images(monkeypatch, tmp_path):
    make_png(tmp_path, "scene.png")
    markdown = tmp_path / "body.md"
    markdown.write_text("![Scene](scene.png)\n", encoding="utf-8")
    client = FakeClient()
    monkeypatch.setattr(page_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        page_cmd.app,
        ["create", "parent-1", "--title", "New", "--content-file", str(markdown)],
    )

    assert result.exit_code == 0, result.output
    assert client.uploaded_files == [str(tmp_path / "scene.png")]
    assert image_blocks(client.uploaded_blocks[0])[0]["image"]["type"] == "file_upload"


def test_pages_create_missing_image_fails_before_page_create(monkeypatch, tmp_path):
    markdown = tmp_path / "body.md"
    markdown.write_text("![Scene](missing.png)\n", encoding="utf-8")
    client = FakeClient()
    monkeypatch.setattr(page_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        page_cmd.app,
        ["create", "parent-1", "--title", "New", "--content-file", str(markdown)],
    )

    assert result.exit_code == 1
    assert "do not exist" in result.stderr
    assert client.events == []


# ---------------------------------------------------------------------------
# pages content replace-section
# ---------------------------------------------------------------------------


def test_replace_section_text_source_uploads_local_images(monkeypatch, tmp_path):
    png = make_png(tmp_path)
    client = FakeClient()
    captured = []

    def fake_text_to_blocks(content, image_uploads=None):
        captured.append(image_uploads)
        return [
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": "S"}}]},
            }
        ]

    client.get_block_children_all = lambda block_id, recursive=True: []
    monkeypatch.setattr(page_cmd, "get_client", lambda: client)
    monkeypatch.setattr(page_cmd, "text_to_blocks", fake_text_to_blocks)

    result = CliRunner().invoke(
        page_cmd.app,
        [
            "content",
            "replace-section",
            "page-1",
            "--heading",
            "## S",
            "--text",
            f"## S\n\n![Scene]({png})",
        ],
    )

    assert captured == [{str(png): "file-upload-1"}]
    assert client.uploaded_files == [str(png)]
    assert result.exit_code == 1  # the scratch page has no blocks to replace
    assert "no content blocks" in result.stderr.lower()


# ---------------------------------------------------------------------------
# database page content set / append / create
# ---------------------------------------------------------------------------


def test_database_content_set_file_uploads_local_images(monkeypatch, tmp_path):
    make_png(tmp_path, "scene.png")
    markdown = tmp_path / "body.md"
    markdown.write_text("![Scene](scene.png)\n", encoding="utf-8")
    client = FakeClient()
    monkeypatch.setattr(database_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        database_cmd.page_app, ["content", "set", "page-1", "--file", str(markdown)]
    )

    assert result.exit_code == 0, result.output
    assert [name for name, _ in client.events] == [
        "upload_file",
        "clear_page_content",
        "_upload_blocks_with_nesting",
    ]
    assert image_blocks(client.uploaded_blocks[0])[0]["image"]["type"] == "file_upload"


def test_database_content_set_missing_image_fails_before_clear(monkeypatch, tmp_path):
    markdown = tmp_path / "body.md"
    markdown.write_text("![Scene](missing.png)\n", encoding="utf-8")
    client = FakeClient()
    monkeypatch.setattr(database_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        database_cmd.page_app, ["content", "set", "page-1", "--file", str(markdown)]
    )

    assert result.exit_code == 1
    assert "do not exist" in result.stderr
    assert client.events == []


def test_database_content_append_missing_image_fails_before_append(monkeypatch, tmp_path):
    markdown = tmp_path / "body.md"
    markdown.write_text("![Scene](missing.png)\n", encoding="utf-8")
    client = FakeClient()
    monkeypatch.setattr(database_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        database_cmd.page_app, ["content", "append", "page-1", "--file", str(markdown)]
    )

    assert result.exit_code == 1
    assert "do not exist" in result.stderr
    assert client.events == []


def test_database_page_create_content_file_uploads_local_images(monkeypatch, tmp_path):
    make_png(tmp_path, "scene.png")
    markdown = tmp_path / "body.md"
    markdown.write_text("![Scene](scene.png)\n", encoding="utf-8")
    client = FakeClient()
    monkeypatch.setattr(database_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        database_cmd.page_app,
        ["create", "database-1", "--title", "New", "--content-file", str(markdown)],
    )

    assert result.exit_code == 0, result.output
    assert [name for name, _ in client.events] == [
        "upload_file",
        "create_page",
        "_upload_blocks_with_nesting",
    ]
    assert image_blocks(client.uploaded_blocks[0])[0]["image"]["type"] == "file_upload"


def test_database_page_create_missing_image_fails_before_create(monkeypatch, tmp_path):
    markdown = tmp_path / "body.md"
    markdown.write_text("![Scene](missing.png)\n", encoding="utf-8")
    client = FakeClient()
    monkeypatch.setattr(database_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        database_cmd.page_app,
        ["create", "database-1", "--title", "New", "--content-file", str(markdown)],
    )

    assert result.exit_code == 1
    assert "do not exist" in result.stderr
    assert client.events == []
