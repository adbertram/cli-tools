"""Regression coverage for duplicating pages with non-reusable covers."""

from notion_cli.client import NotionClient


def test_duplicate_omits_file_cover_returned_by_page_api(monkeypatch):
    """A signed `file` cover from a source page is not a valid create payload."""
    client = NotionClient.__new__(NotionClient)
    captured = {}

    source_page = {
        "parent": {"type": "page_id", "page_id": "parent-page"},
        "properties": {
            "title": {
                "type": "title",
                "title": [{"plain_text": "Source page"}],
            }
        },
        "icon": None,
        "cover": {
            "type": "file",
            "file": {"url": "https://signed.example/temporary-cover"},
        },
    }
    monkeypatch.setattr(client, "get_page", lambda _page_id: source_page)
    monkeypatch.setattr(client, "get_block_children_all", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(client, "_reupload_file_blocks", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(client, "_clean_blocks_recursive", lambda blocks: blocks)

    def fake_request(method, endpoint, data=None, params=None, retry=True):
        captured.update({"method": method, "endpoint": endpoint, "data": data})
        return {"id": "new-page"}

    monkeypatch.setattr(client, "_make_request", fake_request)

    client.duplicate_page("source-page", title="Duplicate")

    assert captured["method"] == "POST"
    assert captured["endpoint"] == "/pages"
    assert "cover" not in captured["data"]
