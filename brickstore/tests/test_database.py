import hashlib
import lzma

import pytest
from cli_tools_shared.exceptions import ClientError

from brickstore_cli.database import CatalogDatabase, download, read_etag
from tests.database_fixtures import build_database, date_chunk, one_set_one_part_database


def write_database(tmp_path, data: bytes):
    path = tmp_path / "database-v12"
    path.write_bytes(data)
    return path


def test_load_reads_status_metadata(tmp_path):
    path = write_database(tmp_path, one_set_one_part_database())

    status = CatalogDatabase.load(path).status()

    assert status == {
        "path": str(path),
        "version": 12,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "etag": None,
        "colors": 1,
        "categories": 1,
        "item_types": 2,
        "items": 2,
        "sets": 1,
        "sets_with_inventory": 1,
    }


def test_load_reports_the_stored_etag_when_a_sidecar_file_exists(tmp_path):
    path = write_database(tmp_path, one_set_one_part_database())
    path.with_name(path.name + ".etag").write_text("W/\"abc123\"", encoding="utf-8")

    assert CatalogDatabase.load(path).status()["etag"] == 'W/"abc123"'


def test_set_contents_merges_regular_and_extra_quantities_into_one_entry(tmp_path):
    path = write_database(tmp_path, one_set_one_part_database())

    result = CatalogDatabase.load(path).set_contents("30670-1")

    assert result == {
        "set_id": "30670-1",
        "items": [
            {
                "item": {"no": "3001", "name": "Brick 2 x 4", "type": "PART", "category_id": 5},
                "color_id": 5,
                "quantity": 3,
                "extra_quantity": 1,
                "is_alternate": False,
                "is_counterpart": False,
                "match_no": 0,
            }
        ],
    }


def test_set_contents_rejects_an_unknown_set(tmp_path):
    path = write_database(tmp_path, one_set_one_part_database())

    with pytest.raises(ClientError, match="holds no set with the ID 99999-1"):
        CatalogDatabase.load(path).set_contents("99999-1")


def test_load_rejects_missing_file(tmp_path):
    with pytest.raises(ClientError, match="does not exist"):
        CatalogDatabase.load(tmp_path / "missing-database")


def test_load_rejects_wrong_magic_bytes(tmp_path):
    data = bytearray(one_set_one_part_database())
    data[0:4] = b"NOPE"
    path = write_database(tmp_path, bytes(data))

    with pytest.raises(ClientError, match="is not a BrickStore database"):
        CatalogDatabase.load(path)


def test_load_rejects_wrong_version(tmp_path):
    data = bytearray(one_set_one_part_database())
    data[4:8] = (99).to_bytes(4, "little")
    path = write_database(tmp_path, bytes(data))

    with pytest.raises(ClientError, match="has version 99, but this CLI reads version 12"):
        CatalogDatabase.load(path)


def test_load_rejects_a_truncated_chunk_header(tmp_path):
    path = write_database(tmp_path, b"BSDB")

    with pytest.raises(ClientError, match="is truncated: the file is smaller than one chunk header"):
        CatalogDatabase.load(path)


def test_load_rejects_a_truncated_chunk_body(tmp_path):
    data = one_set_one_part_database()[:-1]
    path = write_database(tmp_path, data)

    with pytest.raises(ClientError, match="is truncated: chunk .* runs past the end"):
        CatalogDatabase.load(path)


def test_load_rejects_a_footer_that_does_not_match_its_header(tmp_path):
    data = bytearray(one_set_one_part_database())
    # The root chunk's footer id sits in the final 4 bytes of the file.
    data[-4:] = b"NOPE"
    path = write_database(tmp_path, bytes(data))

    with pytest.raises(ClientError, match="is corrupt: the footer of chunk .* does not match its header"):
        CatalogDatabase.load(path)


def test_load_rejects_a_missing_required_chunk(tmp_path):
    data = build_database(
        colors=[(5, "Red")],
        categories=[(5, "Basic")],
        item_types=[("P", "Part"), ("S", "Set")],
        items=[],
        chunks=("DATE", "COL ", "CAT ", "TYPE"),
    )
    path = write_database(tmp_path, data)

    with pytest.raises(ClientError, match="is missing the required chunk\\(s\\) ITEM"):
        CatalogDatabase.load(path)


def test_read_etag_returns_none_without_a_sidecar_file(tmp_path):
    path = tmp_path / "database-v12"
    path.write_bytes(b"BSDB")

    assert read_etag(path) is None


def test_read_etag_reads_the_sidecar_file(tmp_path):
    path = tmp_path / "database-v12"
    path.write_bytes(b"BSDB")
    path.with_name(path.name + ".etag").write_text(" abc123 \n", encoding="utf-8")

    assert read_etag(path) == "abc123"


DOWNLOAD_URL = "https://example.test/brickstore-database"


def compressed_body(plain: bytes) -> bytes:
    return hashlib.sha512(plain).digest() + lzma.compress(plain, format=lzma.FORMAT_ALONE)


class FakeResponse:
    def __init__(self, status_code=200, content=b"", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


def test_download_installs_a_new_database_and_writes_the_etag(monkeypatch, tmp_path):
    path = tmp_path / "database-v12"
    plain = one_set_one_part_database()
    requests = []

    def get(url, headers, timeout):
        requests.append({"url": url, "headers": headers, "timeout": timeout})
        return FakeResponse(200, compressed_body(plain), {"ETag": '"new-etag"'})

    monkeypatch.setattr("brickstore_cli.database.requests.get", get)

    result = download(path, DOWNLOAD_URL, force=False)

    assert result == {
        "path": str(path),
        "url": DOWNLOAD_URL,
        "updated": True,
        "etag": '"new-etag"',
        "compressed_bytes": len(compressed_body(plain)),
        "bytes": len(plain),
    }
    assert path.read_bytes() == plain
    assert read_etag(path) == '"new-etag"'
    assert requests == [{"url": "{}/database-v12.lzma".format(DOWNLOAD_URL), "headers": {}, "timeout": 300}]


def test_download_sends_if_none_match_when_a_local_etag_exists(monkeypatch, tmp_path):
    path = tmp_path / "database-v12"
    path.write_bytes(b"old-bytes")
    path.with_name(path.name + ".etag").write_text('"old-etag"', encoding="utf-8")
    requests = []

    def get(url, headers, timeout):
        requests.append(headers)
        return FakeResponse(304)

    monkeypatch.setattr("brickstore_cli.database.requests.get", get)

    result = download(path, DOWNLOAD_URL, force=False)

    assert result == {"path": str(path), "url": DOWNLOAD_URL, "updated": False, "etag": '"old-etag"'}
    assert requests == [{"If-None-Match": '"old-etag"'}]
    assert path.read_bytes() == b"old-bytes"


def test_download_skips_if_none_match_when_forced(monkeypatch, tmp_path):
    path = tmp_path / "database-v12"
    path.write_bytes(b"old-bytes")
    path.with_name(path.name + ".etag").write_text('"old-etag"', encoding="utf-8")
    plain = one_set_one_part_database()
    requests = []

    def get(url, headers, timeout):
        requests.append(headers)
        return FakeResponse(200, compressed_body(plain), {"ETag": '"new-etag"'})

    monkeypatch.setattr("brickstore_cli.database.requests.get", get)

    result = download(path, DOWNLOAD_URL, force=True)

    assert result["updated"] is True
    assert requests == [{}]


def test_download_rejects_a_non_200_status(monkeypatch, tmp_path):
    monkeypatch.setattr("brickstore_cli.database.requests.get", lambda url, headers, timeout: FakeResponse(500))

    with pytest.raises(ClientError, match="server returned HTTP 500"):
        download(tmp_path / "database-v12", DOWNLOAD_URL)


def test_download_rejects_a_missing_etag_header(monkeypatch, tmp_path):
    plain = one_set_one_part_database()
    monkeypatch.setattr(
        "brickstore_cli.database.requests.get",
        lambda url, headers, timeout: FakeResponse(200, compressed_body(plain), {}),
    )

    with pytest.raises(ClientError, match="server returned no ETag"):
        download(tmp_path / "database-v12", DOWNLOAD_URL)


def test_download_rejects_a_failed_sha512_check(monkeypatch, tmp_path):
    plain = one_set_one_part_database()
    corrupted = b"\x00" * 64 + lzma.compress(plain, format=lzma.FORMAT_ALONE)
    monkeypatch.setattr(
        "brickstore_cli.database.requests.get",
        lambda url, headers, timeout: FakeResponse(200, corrupted, {"ETag": '"e"'}),
    )

    with pytest.raises(ClientError, match="failed its SHA-512 check"):
        download(tmp_path / "database-v12", DOWNLOAD_URL)


def test_download_rejects_invalid_lzma(monkeypatch, tmp_path):
    corrupted = hashlib.sha512(b"not lzma").digest() + b"not lzma"
    monkeypatch.setattr(
        "brickstore_cli.database.requests.get",
        lambda url, headers, timeout: FakeResponse(200, corrupted, {"ETag": '"e"'}),
    )

    with pytest.raises(ClientError, match="is not valid LZMA"):
        download(tmp_path / "database-v12", DOWNLOAD_URL)


def test_download_rejects_wrong_magic_bytes_after_decompression(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "brickstore_cli.database.requests.get",
        lambda url, headers, timeout: FakeResponse(200, compressed_body(b"NOPEnotadatabase"), {"ETag": '"e"'}),
    )

    with pytest.raises(ClientError, match="has the wrong magic bytes"):
        download(tmp_path / "database-v12", DOWNLOAD_URL)


def test_download_rejects_wrong_version_after_decompression(monkeypatch, tmp_path):
    data = bytearray(one_set_one_part_database())
    data[4:8] = (99).to_bytes(4, "little")
    monkeypatch.setattr(
        "brickstore_cli.database.requests.get",
        lambda url, headers, timeout: FakeResponse(200, compressed_body(bytes(data)), {"ETag": '"e"'}),
    )

    with pytest.raises(ClientError, match="has version 99, but this CLI reads version 12"):
        download(tmp_path / "database-v12", DOWNLOAD_URL)
