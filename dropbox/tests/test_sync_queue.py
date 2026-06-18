import json
import sqlite3

from typer.testing import CliRunner

from dropbox_cli.main import app
from dropbox_cli.sync_queue import SyncQueueError, read_pending_sync_items


def create_queue_db(path, rows):
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE commit_intents (key BLOB PRIMARY KEY, value BLOB NOT NULL)")
        conn.executemany("INSERT INTO commit_intents (key, value) VALUES (?, ?)", rows)
        conn.commit()
    finally:
        conn.close()


def test_read_pending_sync_items_extracts_filenames_and_heuristic_paths(tmp_path):
    db_path = tmp_path / "nucleus.sqlite3"
    dropbox_root = tmp_path / "Dropbox"
    nested = dropbox_root / ".gemini" / "worktrees" / "subagent"
    nested.mkdir(parents=True)
    (nested / "SyncField.cs").write_text("pending", encoding="utf-8")
    (tmp_path / "SyncField.cs").write_text("outside", encoding="utf-8")
    create_queue_db(
        db_path,
        [
            (b"\x01", b"\x0cSyncField.cs*/"),
            (b"\x02", b"%GoogleWorkspacePropertiesViewModel.cs*/"),
            (b"\x03", b"-web-active-directory-dashboard.component.html*/"),
        ],
    )

    result = read_pending_sync_items(db_path, dropbox_root)

    assert result["count"] == 3
    assert result["unique_filename_count"] == 3
    assert result["path_resolution"]["heuristic"] is True
    assert result["path_resolution"]["candidate_paths_are_authoritative"] is False
    assert result["entries"][0]["filename"] == "SyncField.cs"
    assert result["entries"][0]["path_resolution"] == "heuristic_filename_match"
    assert result["entries"][0]["dropbox_relative_path_candidates"] == [
        ".gemini/worktrees/subagent/SyncField.cs"
    ]
    assert result["entries"][1]["filename"] == "GoogleWorkspacePropertiesViewModel.cs"
    assert result["entries"][1]["path_candidates"] == []
    assert result["entries"][2]["filename"] == "web-active-directory-dashboard.component.html"


def test_read_pending_sync_items_fails_on_unexpected_schema(tmp_path):
    db_path = tmp_path / "nucleus.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE commit_intents (id INTEGER PRIMARY KEY, value BLOB)")
        conn.commit()
    finally:
        conn.close()

    try:
        read_pending_sync_items(db_path, tmp_path / "Dropbox", resolve_paths=False)
    except SyncQueueError as exc:
        assert "Unexpected Dropbox sync DB schema for commit_intents" in str(exc)
    else:
        raise AssertionError("expected SyncQueueError")


def test_sync_pending_command_outputs_json_without_auth(tmp_path):
    db_path = tmp_path / "nucleus.sqlite3"
    dropbox_root = tmp_path / "Dropbox"
    dropbox_root.mkdir()
    create_queue_db(db_path, [(b"\x01", b"\x0cSyncField.cs*/")])

    result = CliRunner().invoke(
        app,
        [
            "sync",
            "pending",
            "--db",
            str(db_path),
            "--dropbox-root",
            str(dropbox_root),
            "--no-resolve-paths",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["count"] == 1
    assert payload["entries"][0]["filename"] == "SyncField.cs"
    assert payload["path_resolution"]["attempted"] is False
