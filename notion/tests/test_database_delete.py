"""Tests for `notion database delete` (client + command).

The Notion API is never hit: the NotionClient's `_make_request` is replaced
with a fake that records each request and returns canned API 2025-09-03
objects.
"""
import pytest
from typer.testing import CliRunner

from notion_cli.client import NotionClient, ClientError
from notion_cli.commands import database as database_cmd


def container_response(database_id, in_trash):
    """Build a database container object shaped like API 2025-09-03."""
    return {
        "object": "database",
        "id": database_id,
        "title": [{"plain_text": "Cody Agent Task Status"}],
        "url": f"https://www.notion.so/{database_id}",
        "in_trash": in_trash,
        "archived": in_trash,
        "data_sources": [{"id": "ds-1", "name": "Cody Agent Task Status"}],
    }


def make_client(captured, data_source_ids=()):
    """Build a NotionClient whose _make_request is captured (no live API).

    IDs listed in `data_source_ids` behave like bare data_source IDs: the
    container endpoint 404s for them, matching the real resolver path.
    """
    from notion_cli.client import NotFoundError

    client = NotionClient.__new__(NotionClient)
    client._resolution_cache = {}

    def fake_make_request(method, endpoint, data=None, params=None, retry=True):
        captured.append({"method": method, "endpoint": endpoint, "data": data})

        if endpoint.startswith("/databases/"):
            database_id = endpoint.split("/databases/", 1)[1]
            if database_id in data_source_ids:
                raise NotFoundError(f"Could not find database with ID: {database_id}")
            return container_response(database_id, (data or {}).get("in_trash", False))

        if endpoint.startswith("/data_sources/"):
            return {
                "object": "data_source",
                "id": endpoint.split("/data_sources/", 1)[1],
                "parent": {"type": "database_id", "database_id": "db-container-1"},
            }

        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    client._make_request = fake_make_request
    return client


# --------------------------------------------------------------------------
# Client-level: endpoint and body shape
# --------------------------------------------------------------------------


def test_set_database_trash_patches_database_container():
    captured = []
    client = make_client(captured)

    result = client.set_database_trash("db-container-1")

    # First request resolves the ID, second performs the trash.
    patch_requests = [r for r in captured if r["method"] == "PATCH"]
    assert len(patch_requests) == 1
    assert patch_requests[0]["endpoint"] == "/databases/db-container-1"
    assert patch_requests[0]["data"] == {"in_trash": True}
    assert result["in_trash"] is True


def test_set_database_trash_restore_sends_false():
    captured = []
    client = make_client(captured)

    client.set_database_trash("db-container-1", in_trash=False)

    patch_requests = [r for r in captured if r["method"] == "PATCH"]
    assert patch_requests[0]["data"] == {"in_trash": False}


def test_set_database_trash_never_uses_data_sources_endpoint():
    """Schema edits go to /data_sources; trashing must not."""
    captured = []
    client = make_client(captured)

    client.set_database_trash("db-container-1")

    assert not [
        r
        for r in captured
        if r["method"] == "PATCH" and r["endpoint"].startswith("/data_sources/")
    ]


def test_data_source_id_resolves_to_parent_container():
    captured = []
    client = make_client(captured, data_source_ids=("ds-1",))

    client.set_database_trash("ds-1")

    patch_requests = [r for r in captured if r["method"] == "PATCH"]
    assert patch_requests[0]["endpoint"] == "/databases/db-container-1"


def test_get_database_container_id_rejects_non_database_parent():
    from notion_cli.client import NotFoundError

    captured = []
    client = NotionClient.__new__(NotionClient)
    client._resolution_cache = {}

    def fake_make_request(method, endpoint, data=None, params=None, retry=True):
        captured.append(endpoint)
        if endpoint.startswith("/databases/"):
            raise NotFoundError("Could not find database")
        return {
            "object": "data_source",
            "id": "ds-orphan",
            "parent": {"type": "workspace", "workspace": True},
        }

    client._make_request = fake_make_request

    with pytest.raises(ClientError) as exc:
        client.get_database_container_id("ds-orphan")
    assert "workspace" in str(exc.value)


# --------------------------------------------------------------------------
# Command-level: confirmation, flags, output
# --------------------------------------------------------------------------


def run_delete(monkeypatch, captured, args, **kwargs):
    """Invoke the database app's delete command against a captured client."""
    client = make_client(captured, **kwargs)
    monkeypatch.setattr(database_cmd, "get_client", lambda: client)
    return CliRunner().invoke(database_cmd.app, ["delete"] + args)


def test_delete_force_skips_prompt_and_trashes(monkeypatch):
    captured = []
    result = run_delete(monkeypatch, captured, ["db-container-1", "--force"])

    assert result.exit_code == 0
    patch_requests = [r for r in captured if r["method"] == "PATCH"]
    assert patch_requests[0]["endpoint"] == "/databases/db-container-1"
    assert patch_requests[0]["data"] == {"in_trash": True}
    assert '"in_trash": true' in result.stdout
    assert '"title": "Cody Agent Task Status"' in result.stdout


def test_delete_short_force_flag_skips_prompt(monkeypatch):
    captured = []
    result = run_delete(monkeypatch, captured, ["db-container-1", "-F"])

    assert result.exit_code == 0
    assert [r for r in captured if r["method"] == "PATCH"]


def test_delete_prompts_and_trashes_on_yes(monkeypatch):
    captured = []
    client = make_client(captured)
    monkeypatch.setattr(database_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        database_cmd.app, ["delete", "db-container-1"], input="y\n"
    )

    assert result.exit_code == 0
    assert "Move database db-container-1 to trash?" in result.stdout
    assert [r for r in captured if r["method"] == "PATCH"]


def test_delete_cancel_makes_no_request(monkeypatch):
    captured = []
    client = make_client(captured)
    monkeypatch.setattr(database_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        database_cmd.app, ["delete", "db-container-1"], input="n\n"
    )

    assert result.exit_code == 0
    assert "Cancelled." in result.stdout
    assert captured == []


def test_restore_sends_in_trash_false(monkeypatch):
    captured = []
    result = run_delete(monkeypatch, captured, ["db-container-1", "--restore", "-F"])

    assert result.exit_code == 0
    patch_requests = [r for r in captured if r["method"] == "PATCH"]
    assert patch_requests[0]["data"] == {"in_trash": False}
    assert '"in_trash": false' in result.stdout


def test_restore_prompt_wording(monkeypatch):
    captured = []
    client = make_client(captured)
    monkeypatch.setattr(database_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        database_cmd.app, ["delete", "db-container-1", "--restore"], input="n\n"
    )

    assert result.exit_code == 0
    assert "Restore database db-container-1 from trash?" in result.stdout
