import json
from pathlib import Path

from typer.testing import CliRunner

from notion_cli.commands import page as page_cmd


runner = CliRunner()


class Response:
    def __init__(self, content: bytes):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size: int):
        assert chunk_size == 1024 * 1024
        yield self.content


def test_downloads_nested_notion_and_external_file_blocks(monkeypatch, tmp_path: Path):
    class Client:
        def get_block_children_all(self, page_id: str, recursive: bool):
            assert page_id == "page-1"
            assert recursive is True
            return [
                {
                    "id": "toggle-1",
                    "type": "toggle",
                    "children": [
                        {
                            "id": "file-1",
                            "type": "file",
                            "file": {
                                "name": "meeting-intelligence.zip",
                                "type": "file",
                                "file": {
                                    "url": "https://files.example/meeting.zip",
                                    "expiry_time": "2026-08-23T19:00:00Z",
                                },
                            },
                        }
                    ],
                },
                {
                    "id": "file-2",
                    "type": "file",
                    "file": {
                        "name": "research-documentation.zip",
                        "type": "external",
                        "external": {"url": "https://files.example/research.zip"},
                    },
                },
            ]

    downloads = {
        "https://files.example/meeting.zip": b"meeting",
        "https://files.example/research.zip": b"research",
    }
    monkeypatch.setattr(page_cmd, "get_client", Client)
    monkeypatch.setattr(
        "notion_cli.downloads.requests.get",
        lambda url, stream, timeout: Response(downloads[url]),
    )
    output_dir = tmp_path / "skills"

    result = runner.invoke(
        page_cmd.app,
        ["files", "download", "page-1", "--output", str(output_dir)],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [item["name"] for item in payload] == [
        "meeting-intelligence.zip",
        "research-documentation.zip",
    ]
    assert payload[0]["expiry_time"] == "2026-08-23T19:00:00Z"
    assert (output_dir / "meeting-intelligence.zip").read_bytes() == b"meeting"
    assert (output_dir / "research-documentation.zip").read_bytes() == b"research"


def test_refuses_existing_output_without_force(monkeypatch, tmp_path: Path):
    class Client:
        def get_block_children_all(self, page_id: str, recursive: bool):
            return [
                {
                    "id": "file-1",
                    "type": "file",
                    "file": {
                        "name": "skill.zip",
                        "type": "external",
                        "external": {"url": "https://files.example/skill.zip"},
                    },
                }
            ]

    monkeypatch.setattr(page_cmd, "get_client", Client)
    monkeypatch.setattr(
        "notion_cli.downloads.requests.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not download")),
    )
    output_dir = tmp_path / "skills"
    output_dir.mkdir()
    existing = output_dir / "skill.zip"
    existing.write_bytes(b"keep")

    result = runner.invoke(
        page_cmd.app,
        ["files", "download", "page-1", "--output", str(output_dir)],
    )

    assert result.exit_code == 1
    assert "Output file already exists" in result.stderr
    assert existing.read_bytes() == b"keep"


def test_rejects_unsafe_and_duplicate_names(monkeypatch, tmp_path: Path):
    unsafe = [
        {
            "id": "file-1",
            "type": "file",
            "file": {
                "name": "../skill.zip",
                "type": "external",
                "external": {"url": "https://files.example/skill.zip"},
            },
        }
    ]

    class Client:
        def get_block_children_all(self, page_id: str, recursive: bool):
            return unsafe

    monkeypatch.setattr(page_cmd, "get_client", Client)

    result = runner.invoke(
        page_cmd.app,
        ["files", "download", "page-1", "--output", str(tmp_path)],
    )
    assert result.exit_code == 1
    assert "unsafe file name" in result.stderr

    unsafe[:] = [
        {
            "id": f"file-{index}",
            "type": "file",
            "file": {
                "name": "skill.zip",
                "type": "external",
                "external": {"url": f"https://files.example/{index}.zip"},
            },
        }
        for index in range(2)
    ]
    result = runner.invoke(
        page_cmd.app,
        ["files", "download", "page-1", "--output", str(tmp_path)],
    )
    assert result.exit_code == 1
    assert "duplicate file names: skill.zip" in result.stderr
