"""Tests for runtime discovery of the Photos album-asset join table.

Core Data entity numbers change between macOS releases (Z_30ASSETS on older
releases, Z_34ASSETS on newer), so the client reads them from the schema.
"""

import sqlite3

import pytest

from photos_app_cli.client import ClientError, PhotosClient


def _make_library(tmp_path, join_ddl):
    lib = tmp_path / "Test.photoslibrary"
    (lib / "database").mkdir(parents=True)
    conn = sqlite3.connect(lib / "database" / "Photos.sqlite")
    conn.executescript(
        """
        CREATE TABLE ZGENERICALBUM (
            Z_PK INTEGER PRIMARY KEY, ZUUID TEXT, ZTITLE TEXT, ZTRASHEDSTATE INTEGER);
        CREATE TABLE ZASSET (
            Z_PK INTEGER PRIMARY KEY, ZUUID TEXT, ZFILENAME TEXT, ZDATECREATED REAL,
            ZADDEDDATE REAL, ZKIND INTEGER, ZUNIFORMTYPEIDENTIFIER TEXT, ZWIDTH INTEGER,
            ZHEIGHT INTEGER, ZCLOUDLOCALSTATE INTEGER, ZFAVORITE INTEGER, ZHIDDEN INTEGER,
            ZTRASHEDSTATE INTEGER);
        -- Decoys that share the Z_%ASSETS suffix but are not the album join table.
        CREATE TABLE Z_3MEMORIESBEINGCURATEDASSETS (Z_3CURATEDASSETS INTEGER, Z_59MEMORIESBEINGCURATEDASSETS INTEGER);
        CREATE TABLE Z_33KEYASSETS (Z_33ALBUMSBEINGKEYASSETS INTEGER, Z_3KEYASSETS INTEGER);
        """
    )
    conn.executescript(join_ddl)
    conn.execute("INSERT INTO ZGENERICALBUM VALUES (7, 'u-album', 'Listing', 0)")
    conn.execute("INSERT INTO ZASSET VALUES (1, 'u-in', 'in.jpg', 100.0, 100.0, 0, 'public.jpeg', 10, 10, 0, 0, 0, 0)")
    conn.execute("INSERT INTO ZASSET VALUES (2, 'u-out', 'out.jpg', 200.0, 200.0, 0, 'public.jpeg', 10, 10, 0, 0, 0, 0)")
    conn.commit()
    conn.close()
    return PhotosClient(library_path=lib), lib


OLD_LAYOUT = "CREATE TABLE Z_30ASSETS (Z_30ALBUMS INTEGER, Z_3ASSETS INTEGER, Z_FOK_3ASSETS INTEGER);"
NEW_LAYOUT = "CREATE TABLE Z_34ASSETS (Z_34ALBUMS INTEGER, Z_3ASSETS INTEGER, Z_FOK_3ASSETS INTEGER);"


def _link(lib, table, album_col, asset_col):
    conn = sqlite3.connect(lib / "database" / "Photos.sqlite")
    conn.execute(f"INSERT INTO {table} ({album_col}, {asset_col}) VALUES (7, 1)")
    conn.commit()
    conn.close()


@pytest.mark.parametrize(
    "ddl,expected",
    [
        (OLD_LAYOUT, ("Z_30ASSETS", "Z_30ALBUMS", "Z_3ASSETS")),
        (NEW_LAYOUT, ("Z_34ASSETS", "Z_34ALBUMS", "Z_3ASSETS")),
    ],
)
def test_join_table_resolved_and_used_for_album_listing(tmp_path, ddl, expected):
    client, lib = _make_library(tmp_path, ddl)
    assert client._album_asset_join() == expected
    _link(lib, *expected)

    photos = client.list_photos(album="Listing")
    assert [p.uuid for p in photos] == ["u-in"]


def test_join_resolution_is_cached(tmp_path):
    client, _ = _make_library(tmp_path, NEW_LAYOUT)
    first = client._album_asset_join()
    client.db_path = tmp_path / "gone.sqlite"  # a second discovery would fail
    assert client._album_asset_join() is first


def test_missing_join_table_raises_clear_error(tmp_path):
    client, _ = _make_library(tmp_path, "")
    with pytest.raises(ClientError, match=r"join table not found.*Z_<n>ASSETS"):
        client._album_asset_join()
    with pytest.raises(ClientError, match="join table not found"):
        client.list_photos(album="Listing")


def test_ambiguous_join_tables_raise(tmp_path):
    client, _ = _make_library(tmp_path, OLD_LAYOUT + NEW_LAYOUT)
    with pytest.raises(ClientError, match="ambiguous"):
        client._album_asset_join()
