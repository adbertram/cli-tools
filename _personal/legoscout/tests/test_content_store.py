from pathlib import Path

import pytest

from legoscout_cli.pricing import content_store


def test_writes_to_the_sharded_relative_path(tmp_path):
    relative = content_store.write_sharded(
        str(tmp_path), "abcd1234", "stem", ".bin",
        lambda temp: temp.write_bytes(b"hello"))

    assert relative == "ab/stem.bin"
    assert (tmp_path / "ab" / "stem.bin").read_bytes() == b"hello"


def test_overwrites_an_existing_destination(tmp_path):
    writer_calls = []

    def writer(temp: Path) -> None:
        writer_calls.append(1)
        temp.write_bytes(b"version-%d" % len(writer_calls))

    first = content_store.write_sharded(str(tmp_path), "ff00", "stem", ".bin", writer)
    second = content_store.write_sharded(str(tmp_path), "ff00", "stem", ".bin", writer)

    assert first == second
    assert (tmp_path / first).read_bytes() == b"version-2"
    assert len(writer_calls) == 2


def test_removes_the_temp_file_and_reraises_when_the_writer_fails(tmp_path):
    def broken_writer(temp: Path) -> None:
        temp.write_bytes(b"partial")
        raise OSError("disk write failed")

    with pytest.raises(OSError, match="disk write failed"):
        content_store.write_sharded(str(tmp_path), "ff00", "stem", ".bin", broken_writer)

    assert list(tmp_path.rglob("*.*")) == []


def test_never_promotes_a_file_when_the_destination_directory_cannot_be_created(tmp_path):
    blocking_file = tmp_path / "ff"
    blocking_file.write_text("not a directory")

    with pytest.raises(OSError):
        content_store.write_sharded(
            str(tmp_path), "ff00", "stem", ".bin",
            lambda temp: temp.write_bytes(b"data"))
