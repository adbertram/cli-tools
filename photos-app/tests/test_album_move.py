"""Tests for photos-app album name matching and the albums-move flow.

Regression coverage for agent-issues #611:
- Album titles can carry incidental leading/trailing whitespace that the
  list/get commands do not surface. _get_album_pk previously trimmed only the
  stored side of the comparison, so no caller input could satisfy both the
  pre-check and an exact AppleScript match.
- move_album_to_folder built one AppleScript that created the new album, copied
  photos, then deleted the source. The make-new-album/add-photos step mutated
  Photos' live "every album" collection mid-script, so the delete failed with
  "Invalid index" after the copy had already succeeded, leaving a DUPLICATE
  un-trashed album behind while reporting failure.

These tests exercise the SQL/matching fix directly and verify the move drives
Photos by stable album id and issues the delete as a separate invocation, with
rollback on delete failure so no duplicate album is left behind. The live move
is not exercised because it mutates the real macOS Photos library.
"""

import sqlite3
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from photos_app_cli.client import PhotosClient, ClientError


def _make_library(tmp_path, albums):
    """Create a minimal Photos.sqlite fixture and return a PhotosClient.

    albums: list of dicts with keys pk, uuid, title, trashed (default 0).
    """
    lib = tmp_path / "Test.photoslibrary"
    (lib / "database").mkdir(parents=True)
    db_path = lib / "database" / "Photos.sqlite"

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE ZGENERICALBUM (
            Z_PK INTEGER PRIMARY KEY,
            ZUUID TEXT,
            ZTITLE TEXT,
            ZTRASHEDSTATE INTEGER,
            ZCACHEDPHOTOSCOUNT INTEGER,
            ZCACHEDVIDEOSCOUNT INTEGER,
            ZCREATIONDATE REAL
        )
        """
    )
    conn.execute("CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY)")
    for a in albums:
        conn.execute(
            "INSERT INTO ZGENERICALBUM (Z_PK, ZUUID, ZTITLE, ZTRASHEDSTATE, "
            "ZCACHEDPHOTOSCOUNT, ZCACHEDVIDEOSCOUNT, ZCREATIONDATE) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (a["pk"], a["uuid"], a["title"], a.get("trashed", 0), 3, 0, 700000000.0),
        )
    conn.commit()
    conn.close()

    return PhotosClient(library_path=lib)


TRAILING = "eBay - 12 32x32 baseplates "  # note the trailing space


def test_identity_matches_trailing_space_regardless_of_caller_whitespace(tmp_path):
    client = _make_library(
        tmp_path, [{"pk": 5, "uuid": "SRC-UUID", "title": TRAILING}]
    )

    # Caller passes the name WITHOUT the trailing space.
    identity = client._get_album_identity("eBay - 12 32x32 baseplates")
    assert identity is not None
    assert identity["pk"] == 5
    assert identity["uuid"] == "SRC-UUID"
    # The exact stored title (with trailing space) is preserved.
    assert identity["title"] == TRAILING

    # Caller passes the name WITH the trailing space -> also resolves.
    assert client._get_album_identity(TRAILING)["pk"] == 5
    # Case-insensitive.
    assert client._get_album_identity("EBAY - 12 32X32 BASEPLATES")["pk"] == 5
    # _get_album_pk delegates to the same resolver.
    assert client._get_album_pk("eBay - 12 32x32 baseplates") == 5


def test_identity_ignores_trashed_albums(tmp_path):
    client = _make_library(
        tmp_path, [{"pk": 9, "uuid": "T", "title": "Gone", "trashed": 1}]
    )
    assert client._get_album_identity("Gone") is None


def test_missing_album_raises(tmp_path):
    client = _make_library(tmp_path, [])
    with pytest.raises(ClientError, match="not found"):
        client.move_album_to_folder("nope", "Completed eBay Listings")


def _completed(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_move_uses_stable_id_and_separate_delete_invocation(tmp_path):
    client = _make_library(
        tmp_path, [{"pk": 5, "uuid": "SRC-UUID", "title": "eBay - Viking sets"}]
    )
    calls = []

    def fake_run(args, **kwargs):
        script = args[2]  # ["osascript", "-e", script]
        calls.append(script)
        if len(calls) == 1:
            return _completed(stdout="NEW-UUID/L0/040\n")
        return _completed()  # delete succeeds

    with patch.object(subprocess, "run", side_effect=fake_run):
        album = client.move_album_to_folder("eBay - Viking sets", "Completed eBay Listings")

    # Exactly two osascript invocations: create/copy, then delete.
    assert len(calls) == 2
    create_script, delete_script = calls
    # Source referenced by its stable album id, never by "whose name is".
    assert 'album id "SRC-UUID/L0/040"' in create_script
    assert "whose name is" not in create_script
    assert "every album" not in create_script
    # Delete is a separate invocation targeting the source by stable id.
    assert 'delete (album id "SRC-UUID/L0/040")' in delete_script
    assert album.title == "eBay - Viking sets"


def test_move_rolls_back_new_album_when_source_delete_fails(tmp_path):
    client = _make_library(
        tmp_path, [{"pk": 5, "uuid": "SRC-UUID", "title": "eBay - Viking sets"}]
    )
    calls = []

    def fake_run(args, **kwargs):
        script = args[2]
        calls.append(script)
        if len(calls) == 1:
            return _completed(stdout="NEW-UUID/L0/040\n")  # create succeeds
        if len(calls) == 2:
            return _completed(returncode=1, stderr="Photos got an error: Invalid index. (-1719)")
        return _completed()  # rollback delete succeeds

    with patch.object(subprocess, "run", side_effect=fake_run):
        with pytest.raises(ClientError) as excinfo:
            client.move_album_to_folder("eBay - Viking sets", "Completed eBay Listings")

    # Three invocations: create, failed source-delete, rollback of the new album.
    assert len(calls) == 3
    rollback_script = calls[2]
    assert 'delete (album id "NEW-UUID/L0/040")' in rollback_script
    msg = str(excinfo.value)
    assert "rolled back" in msg
    assert "Retry" in msg
