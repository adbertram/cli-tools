import json
from pathlib import Path

from typer.testing import CliRunner

from notion_cli.commands import skills


runner = CliRunner()


class JsonResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def skill_block(block_id: str, name: str, attachment_id: str, size: str = "27 KiB"):
    return {
        block_id: {
            "value": {
                "value": {
                    "type": "file",
                    "properties": {
                        "title": [[name]],
                        "source": [[f"attachment:{attachment_id}:{name}"]],
                        "size": [[size]],
                    },
                }
            }
        }
    }


def install_catalog(monkeypatch):
    blocks = {
        **skill_block("block-1", "notion-meeting-intelligence.zip", "attachment-1"),
        **skill_block("block-2", "notion-research-documentation.zip", "attachment-2", "29 KiB"),
        "text-1": {"value": {"value": {"type": "text", "properties": {}}}},
    }
    calls = []

    def post(url, json, timeout):
        calls.append((url, json, timeout))
        if url.endswith("/loadCachedPageChunk"):
            return JsonResponse({"recordMap": {"block": blocks}})
        return JsonResponse({"signedUrls": ["https://file.notion.com/signed-skill.zip"]})

    monkeypatch.setattr(skills.requests, "post", post)
    return calls


def test_list_exposes_unique_stable_block_ids(monkeypatch):
    calls = install_catalog(monkeypatch)

    result = runner.invoke(skills.app, ["list"])

    assert result.exit_code == 0, result.output
    records = json.loads(result.stdout)
    assert [record["id"] for record in records] == ["block-1", "block-2"]
    assert len({record["id"] for record in records}) == len(records)
    assert records[0]["attachment_id"] == "attachment-1"
    assert "_attachment_source" not in records[0]
    assert len(calls) == 1


def test_list_supports_standard_filter_limit_and_properties(monkeypatch):
    install_catalog(monkeypatch)

    result = runner.invoke(
        skills.app,
        ["list", "-f", "name:contains:research", "-l", "1", "-p", "id,name"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [
        {"id": "block-2", "name": "notion-research-documentation.zip"}
    ]


def test_get_returns_exact_skill(monkeypatch):
    install_catalog(monkeypatch)

    result = runner.invoke(skills.app, ["get", "block-2"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["name"] == "notion-research-documentation.zip"


def test_get_rejects_unknown_skill_id(monkeypatch):
    install_catalog(monkeypatch)

    result = runner.invoke(skills.app, ["get", "missing"])

    assert result.exit_code == 1
    assert "Official Notion skill not found: missing" in result.stderr


def test_download_signs_and_downloads_only_selected_skill(monkeypatch, tmp_path: Path):
    calls = install_catalog(monkeypatch)
    captured_downloads = []

    def download_files(downloads, output, force):
        captured_downloads.extend(downloads)
        return [
            {
                "id": downloads[0]["id"],
                "name": downloads[0]["name"],
                "source_type": downloads[0]["source_type"],
                "output": str(Path(output) / downloads[0]["name"]),
                "bytes": 123,
            }
        ]

    monkeypatch.setattr(skills, "download_files", download_files)

    result = runner.invoke(skills.app, ["download", "block-2", "-o", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert len(captured_downloads) == 1
    assert captured_downloads[0]["id"] == "block-2"
    assert calls[1][1] == {
        "urls": [
            {
                "permissionRecord": {"table": "block", "id": "block-2"},
                "url": "attachment:attachment-2:notion-research-documentation.zip",
            }
        ]
    }
    assert json.loads(result.stdout)[0]["id"] == "block-2"


def test_download_rejects_signed_url_count_mismatch(monkeypatch, tmp_path: Path):
    blocks = skill_block("block-1", "notion-skill.zip", "attachment-1")
    responses = iter(
        [
            JsonResponse({"recordMap": {"block": blocks}}),
            JsonResponse({"signedUrls": []}),
        ]
    )
    monkeypatch.setattr(skills.requests, "post", lambda *args, **kwargs: next(responses))

    result = runner.invoke(skills.app, ["download", "block-1", "-o", str(tmp_path)])

    assert result.exit_code == 1
    assert "must contain exactly one URL" in result.stderr


def test_removed_bulk_download_shape_is_rejected_before_network(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr(skills.requests, "post", lambda *args, **kwargs: calls.append(args))

    result = runner.invoke(skills.app, ["download", "-o", str(tmp_path)])

    assert result.exit_code == 2
    assert "Missing argument" in result.output
    assert "SKILL_ID" in result.output
    assert calls == []


def test_rejects_attachment_name_mismatch(monkeypatch):
    blocks = skill_block("block-1", "notion-skill.zip", "attachment-1")
    blocks["block-1"]["value"]["value"]["properties"]["source"] = [
        ["attachment:attachment-1:different.zip"]
    ]
    monkeypatch.setattr(
        skills.requests,
        "post",
        lambda *args, **kwargs: JsonResponse({"recordMap": {"block": blocks}}),
    )

    result = runner.invoke(skills.app, ["list"])

    assert result.exit_code == 1
    assert "not a valid ZIP attachment" in result.stderr
