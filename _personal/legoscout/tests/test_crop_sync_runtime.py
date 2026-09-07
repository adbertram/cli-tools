"""Exercise the installed rsync, not invented transport output, against real files."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from legoscout_cli.deploy import config, db_sync
from legoscout_cli.ledger import db, ingestion
from test_server_ingestion import deal


@pytest.fixture
def crop_roots(tmp_path, monkeypatch):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    assert shutil.which("rsync"), "rsync is required by crop publication"

    def local_rsync(argv, input=None):
        assert argv[0] == "rsync", "this acceptance test cannot execute SSH"
        assert ":" not in argv[-2] and ":" not in argv[-1]
        if argv[-2] == str(destination) + "/":
            assert "--dry-run" in argv, "reverse inspection must never write to the source"
        return subprocess.run(argv, input=input, text=True, capture_output=True, check=True).stdout

    monkeypatch.setattr(db_sync.ssh, "run_local", local_rsync)
    return source, destination


def _sync(roots):
    return db_sync._sync_additive(*(str(path) + "/" for path in roots))


def test_installed_rsync_transfers_new_crop_bytes_and_replays_without_changes(crop_roots):
    source, destination = crop_roots
    (source / "nested").mkdir()
    (source / "nested" / "new.jpg").write_bytes(b"reviewed crop bytes")
    assert _sync(crop_roots) == {"transferred": True, "collisions": []}
    landed = destination / "nested" / "new.jpg"
    assert landed.is_file() and not landed.is_symlink()
    assert landed.read_bytes() == b"reviewed crop bytes"
    assert _sync(crop_roots) == {"transferred": False, "collisions": []}
    assert landed.read_bytes() == b"reviewed crop bytes"


@pytest.mark.parametrize("collision", ["different-bytes", "symlink", "directory"])
def test_installed_rsync_rejects_destination_collisions_without_replacement(
    crop_roots, tmp_path, collision,
):
    source, destination = crop_roots
    (source / "crop.jpg").write_bytes(b"original crop")
    target = destination / "crop.jpg"
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"outside remains")
    if collision == "different-bytes":
        target.write_bytes(b"modified crop")  # Same size: checksum must decide.
    elif collision == "symlink":
        target.symlink_to(outside)
    else:
        target.mkdir()
    with pytest.raises(ValueError, match="collision|did not land|regular file"):
        _sync(crop_roots)
    assert outside.read_bytes() == b"outside remains"
    if collision == "different-bytes":
        assert target.read_bytes() == b"modified crop"
    elif collision == "symlink":
        assert target.is_symlink() and target.resolve() == outside
    else:
        assert target.is_dir()


def test_installed_rsync_rejects_source_symlink_before_transfer(crop_roots, tmp_path):
    source, destination = crop_roots
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"unreviewed external bytes")
    (source / "crop.jpg").symlink_to(outside)
    with pytest.raises(ValueError, match="regular file"):
        _sync(crop_roots)
    assert not (destination / "crop.jpg").exists()
    assert not (destination / "crop.jpg").is_symlink()
    assert outside.read_bytes() == b"unreviewed external bytes"


@pytest.mark.parametrize("new_code, changed_code", [
    (">f+++++++", ">fc......"),  # Captured installed macOS openrsync.
    (">f+++++++++", ">fc........"),  # rsync with trailing attribute columns.
    ("<f+++++++", "<fc......"),
])
def test_item_parser_uses_transfer_semantics_not_attribute_column_count(new_code, changed_code):
    assert db_sync._parse_rsync_preflight(f"{new_code}|new.jpg\n{changed_code}|changed.jpg\n") == (
        ["new.jpg"], ["changed.jpg"])


@pytest.mark.parametrize("item", ["bad", ">f???????", "cL+++++++", "*deleting"])
def test_unhandled_rsync_transfer_is_not_reported_as_clean(item):
    with pytest.raises(ValueError, match="unsupported|regular file"):
        db_sync._parse_rsync_preflight(item + "|crop.jpg\n")


def test_actual_crop_collision_blocks_ingest_before_database_publication(crop_roots, tmp_path, monkeypatch):
    source, destination = crop_roots
    (source / "crop.jpg").write_bytes(b"original crop")
    (destination / "crop.jpg").write_bytes(b"modified crop")
    server, baseline = str(tmp_path / "server.db"), str(tmp_path / "baseline.db")
    db.init(server).close()
    db.upsert_deals([deal(price=25)], path=server)
    db.snapshot(server, baseline, baseline=True)
    payload = tmp_path / "ingest.json"
    payload.write_text(json.dumps(ingestion.prepare("crop-collision", baseline, [deal(price=31)])))
    monkeypatch.setattr(config, "LOCAL_SHARED_CROPS", str(source))
    monkeypatch.setattr(db_sync, "_remote_crop_source", lambda: str(destination) + "/")
    monkeypatch.setattr(db_sync, "_ensure_remote_crop_root", lambda: None)
    published = []
    def publish(value):
        published.append(value)
        return ingestion.ingest(value, path=server)
    monkeypatch.setattr(db_sync, "_ingest_database", publish)
    before = db.load_document(server)
    outcome = db_sync.ingest(str(payload))
    assert outcome["ok"] is False
    assert "collision" in outcome["crops"]["error"]
    assert outcome["db"]["skipped"] is True
    assert published == []
    assert db.load_document(server) == before
    assert db.get_deal("ebay|1", path=server)["current_price"] == 25
    assert (destination / "crop.jpg").read_bytes() == b"modified crop"


@pytest.mark.parametrize("collision", ["symlink", "file"])
def test_installed_rsync_preserves_conflicting_destination_container(crop_roots, tmp_path, collision):
    source, destination = crop_roots
    (source / "nested").mkdir()
    (source / "nested" / "crop.jpg").write_bytes(b"reviewed crop")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.jpg").write_bytes(b"external bytes")
    target = destination / "nested"
    if collision == "symlink":
        target.symlink_to(outside, target_is_directory=True)
    else:
        target.write_bytes(b"existing destination file")
    with pytest.raises(ValueError, match="regular file|collision"):
        _sync(crop_roots)
    assert (source / "nested" / "crop.jpg").read_bytes() == b"reviewed crop"
    assert sorted(path.name for path in outside.iterdir()) == ["keep.jpg"]
    assert (outside / "keep.jpg").read_bytes() == b"external bytes"
    if collision == "symlink":
        assert target.is_symlink() and target.resolve() == outside
    else:
        assert target.read_bytes() == b"existing destination file"
