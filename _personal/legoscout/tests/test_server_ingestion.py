"""Disposable DB acceptance of stale-client and overlapping-server writes."""
from __future__ import annotations

import copy
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from legoscout_cli.commands import deploy
from legoscout_cli.deploy import db_sync
from legoscout_cli.ledger import db, ingestion, sellers


def deal(key="ebay|1", price=25):
    return {"listing_key": key, "source": key.split("|")[0], "title": "LEGO lot",
            "url": "https://example.invalid/" + key, "current_price": price,
            "price_basis": "current_price", "status": "active", "seller_id": "seller-1",
            "first_seen_at": "2026-09-01T12:00:00Z", "last_seen_at": "2026-09-01T12:00:00Z"}


@pytest.fixture
def run_db(tmp_path):
    server = str(tmp_path / "server.db")
    baseline = str(tmp_path / "baseline.db")
    db.init(server).close()
    db.upsert_deals([deal()], path=server)
    conn = db.connect(server)
    with conn:
        conn.execute("CREATE TABLE historic_outreach (id TEXT PRIMARY KEY, note TEXT)")
        conn.execute("INSERT INTO historic_outreach VALUES ('old-1', 'preserve history')")
    conn.close()
    db.snapshot(server, baseline, baseline=True)
    return server, baseline


@pytest.mark.parametrize("status", ["active", "rejected", "inquired", "bid_placed", "purchased"])
def test_interleaved_user_decision_favorite_and_server_only_row_survive(run_db, status):
    server, baseline = run_db
    incoming = deal(price=31)
    incoming["first_seen_at"] = incoming["last_seen_at"] = "2099-01-01"
    payload = ingestion.prepare("run-1", baseline, [incoming])
    db.update_status("ebay|1", status, "2026-09-07T12:00:00Z", path=server)
    sellers.set_favorite("ebay", "seller-1", True, path=server)
    db.upsert_deals([deal("shopgoodwill|2")], path=server)
    result = ingestion.ingest(payload, path=server)
    stored = db.get_deal("ebay|1", path=server)
    assert stored["status"] == stored["last_status"] == status
    assert stored["first_seen_at"] == "2026-09-01T12:00:00Z"
    assert stored["last_seen_at"] == "2026-09-07T12:00:00Z"
    assert stored["current_price"] == 31
    assert sellers.is_favorite("ebay", "seller-1", path=server)
    assert db.get_deal("shopgoodwill|2", path=server)
    assert db.query("SELECT * FROM historic_outreach", path=server) == [{"id": "old-1", "note": "preserve history"}]
    assert result["updated"] == 1


@pytest.mark.parametrize("category", ["bulk", "set", "excluded", None])
def test_category_change_cannot_bypass_minifigure_review(run_db, category):
    from test_build_record_identification import _entry, _identification

    server, _ = run_db
    before = db.load_document(server)
    record = deal("k-bid|1")
    identification = _identification([_entry("g1")])
    record.update({key: identification[key] for key in (
        "minifig_analysis", "minifig_review_receipt", "figure_count", "figure_count_source",
    )})
    record.update(listing_category=category, status="active")
    record["minifig_analysis"][0]["fig_no"] = "sw-unreviewed"
    payload = {"version": 1, "run_id": "category-bypass", "observations": [
        {"expected_hash": None, "record": record},
    ]}
    with pytest.raises(ValueError, match="minifigure evidence requires"):
        ingestion.ingest(payload, path=server)
    assert db.load_document(server) == before


def test_retry_is_exactly_once_and_changed_run_id_payload_fails(run_db):
    server, baseline = run_db
    payload = ingestion.prepare("run-1", baseline, [deal(price=31), deal("ebay|2")])
    first = ingestion.ingest(payload, path=server)
    doc = db.load_document(server)
    repeated = ingestion.ingest(copy.deepcopy(payload), path=server)
    assert repeated == {**first, "replayed": True}
    assert db.load_document(server) == doc
    assert len(db.query("SELECT * FROM ingestion_runs", path=server)) == 1
    payload["observations"][0]["record"]["current_price"] = 32
    with pytest.raises(ValueError, match="different payload"):
        ingestion.ingest(payload, path=server)
    assert db.load_document(server) == doc


def test_conflict_rolls_back_valid_sibling_history_and_watermarks(run_db):
    server, baseline = run_db
    payload = ingestion.prepare("stale", baseline, [deal("ebay|3"), deal(price=31)])
    ingestion.ingest(ingestion.prepare("first", baseline, [deal(price=40)]), path=server)
    before = db.load_document(server)
    with pytest.raises(db.StaleWrite, match="ebay\\|1"):
        ingestion.ingest(payload, path=server)
    assert db.load_document(server) == before
    assert db.get_deal("ebay|3", path=server) is None
    assert [row["run_id"] for row in db.query("SELECT run_id FROM ingestion_runs", path=server)] == ["first"]


@pytest.mark.parametrize("same_key", [True, False])
def test_two_runs_forced_to_contend_at_transaction_boundary(run_db, monkeypatch, same_key):
    server, baseline = run_db
    payloads = [ingestion.prepare("run-a", baseline, [deal(price=31)]),
                ingestion.prepare("run-b", baseline, [deal("ebay|1" if same_key else "ebay|2", price=32)])]
    gate = threading.Barrier(2)
    connect = sellers.connect
    def synchronized_connect(path):
        conn = connect(path)
        gate.wait(timeout=5)
        return conn
    monkeypatch.setattr(sellers, "connect", synchronized_connect)
    def accept(payload):
        try:
            return ingestion.ingest(payload, path=server)
        except db.StaleWrite:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(accept, payloads))
    assert outcomes.count("conflict") == int(same_key)
    assert len(db.query("SELECT * FROM ingestion_runs", path=server)) == (1 if same_key else 2)


def test_baseline_refuses_all_legacy_writes_and_preserves_unsent_file(run_db, tmp_path):
    server, baseline = run_db
    before = db.load_document(baseline)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        db.upsert_deals([deal(price=99)], path=baseline)
    assert db.load_document(baseline) == before
    with pytest.raises(FileExistsError):
        db.snapshot(server, baseline, baseline=True)
    unsent = tmp_path / "unsent.db"
    unsent.write_bytes(b"unsent observations")
    with pytest.raises(FileExistsError):
        db.snapshot(server, str(unsent), baseline=True)
    assert unsent.read_bytes() == b"unsent observations"
    with pytest.raises(ValueError, match="immutable"):
        ingestion.prepare("run", server, [deal()])


def test_baseline_snapshot_includes_wal_rows_without_modifying_source(run_db, tmp_path):
    server, _ = run_db
    writer = db.connect(server)
    db.upsert_deals([deal("ebay|wal")], path=server)
    destination = str(tmp_path / "wal-baseline.db")
    db.snapshot(server, destination, baseline=True)
    writer.close()
    assert db.get_deal("ebay|wal", path=destination)
    assert db.query("SELECT * FROM meta WHERE key = '_ingest_baseline'", path=server) == []


def test_watermarks_derive_from_server_rows_and_leave_other_sources_untouched(run_db):
    server, baseline = run_db
    server_only = deal("ebay|newest")
    server_only["posted_date"] = "2026-09-07"
    db.upsert_deals([server_only], path=server)
    conn = db.connect(server)
    with conn:
        conn.execute("INSERT INTO source_watermarks VALUES ('shopgoodwill', ?)", (json.dumps({"keep": "exact"}),))
    conn.close()
    ingestion.ingest(ingestion.prepare("run", baseline, [deal(price=31)]), path=server)
    marks = db.load_document(server)["source_watermarks"]
    assert marks["ebay"]["newest_listing_key"] == "ebay|newest"
    assert marks["ebay"]["deal_count"] == 2
    assert marks["shopgoodwill"] == {"keep": "exact"}


def test_mid_transaction_seller_failure_rolls_back_rows_and_receipt(run_db, monkeypatch):
    server, baseline = run_db
    payload = ingestion.prepare("run", baseline, [deal(price=31)])
    before = db.load_document(server)
    def fail(*args):
        raise RuntimeError("forced seller transaction failure")
    monkeypatch.setattr(sellers, "upsert_seen", fail)
    with pytest.raises(RuntimeError, match="forced seller"):
        ingestion.ingest(payload, path=server)
    assert db.load_document(server) == before
    assert db.query("SELECT name FROM sqlite_master WHERE name = 'ingestion_runs'", path=server) == []


@pytest.mark.parametrize("change", ["duplicate", "unknown", "missing_hash", "bad_price"])
def test_malformed_batches_never_reach_writer(run_db, change):
    server, baseline = run_db
    payload = ingestion.prepare("run", baseline, [deal(price=31)])
    if change == "duplicate":
        payload["observations"] *= 2
    elif change == "unknown":
        payload["observations"][0]["record"]["unpersisted"] = "lost"
    elif change == "missing_hash":
        del payload["observations"][0]["expected_hash"]
    else:
        payload["observations"][0]["record"]["current_price"] = "invented"
    before = db.load_document(server)
    with pytest.raises(ValueError):
        ingestion.ingest(payload, path=server)
    assert db.load_document(server) == before


def test_code_push_never_calls_data_transport(monkeypatch):
    monkeypatch.setattr(deploy.release, "deploy_code", lambda: SimpleNamespace(skipped=False, release_name="new"))
    monkeypatch.setattr(db_sync.ssh, "run_local", lambda *a, **k: pytest.fail("code push attempted data transport"))
    result = CliRunner().invoke(deploy.app, ["push"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"ok": True, "code_deployed": True, "release_name": "new"}


def test_prepare_and_ingest_commands_accept_explicit_records(run_db, tmp_path, monkeypatch):
    server, baseline = run_db
    records = tmp_path / "records.json"
    payload = tmp_path / "payload.json"
    records.write_text(json.dumps([deal(price=31)]))
    runner = CliRunner()
    args = ["prepare-ingest", "--run-id", "run", "--baseline", baseline, "--records", str(records), "--output", str(payload)]
    result = runner.invoke(deploy.app, args)
    assert result.exit_code == 0, result.output
    events = []
    monkeypatch.setattr(db_sync, "_push_crops", lambda: events.append("crops") or {"transferred": True})
    monkeypatch.setattr(db_sync, "_ingest_database", lambda value: events.append("db") or ingestion.ingest(value, path=server))
    result = runner.invoke(deploy.app, ["ingest", str(payload)])
    assert result.exit_code == 0, result.output
    assert events == ["crops", "db"]
    assert db.get_deal("ebay|1", path=server)["current_price"] == 31
    assert runner.invoke(deploy.app, args).exit_code != 0


def test_crop_collision_blocks_ingestion_and_no_deletion_is_attempted(run_db, tmp_path, monkeypatch):
    server, baseline = run_db
    payload = tmp_path / "payload.json"
    payload.write_text(json.dumps(ingestion.prepare("run", baseline, [deal(price=31)])))
    def collision():
        raise ValueError("crop content collision: aa/x.jpg")
    monkeypatch.setattr(db_sync, "_push_crops", collision)
    monkeypatch.setattr(db_sync, "_ingest_database", lambda *a: pytest.fail("DB must not publish missing crops"))
    result = db_sync.ingest(str(payload))
    assert result["ok"] is False
    assert result["db"]["skipped"] is True
    assert db.get_deal("ebay|1", path=server)["current_price"] == 25


def test_pull_existing_destination_refuses_before_remote_snapshot(tmp_path, monkeypatch):
    target = tmp_path / "existing.db"
    target.write_bytes(b"unsent observations")
    monkeypatch.setattr(db_sync.ssh, "run_remote", lambda *a: pytest.fail("existing destination must fail before remote work"))
    with pytest.raises(FileExistsError):
        db_sync._pull_database(str(target))
    assert target.read_bytes() == b"unsent observations"


def test_real_remote_ingestion_program_updates_same_server_file(run_db, monkeypatch):
    server, baseline = run_db
    payload = ingestion.prepare("transport", baseline, [deal(price=31)])
    inode = os.stat(server).st_ino
    monkeypatch.setattr(db_sync.config, "REMOTE_TOOL_PYTHON", sys.executable)
    monkeypatch.setattr(db_sync.config, "REMOTE_SHARED_DB", server)
    def execute_remote_program(argv, input):
        assert argv[:2] == ["ssh", "adam-server"]
        return subprocess.run(shlex.split(argv[2]), input=input, text=True, capture_output=True, check=True).stdout
    monkeypatch.setattr(db_sync.ssh, "run_local", execute_remote_program)
    result = db_sync._ingest_database(payload)
    assert result["updated"] == 1
    assert db.get_deal("ebay|1", path=server)["current_price"] == 31
    assert os.stat(server).st_ino == inode


def test_real_pull_program_delivers_new_immutable_snapshot(run_db, tmp_path, monkeypatch):
    server, _ = run_db
    target = str(tmp_path / "pulled.db")
    monkeypatch.setattr(db_sync.config, "REMOTE_TOOL_PYTHON", sys.executable)
    monkeypatch.setattr(db_sync.config, "REMOTE_SHARED_DB", server)
    calls = []
    def remote(argv):
        calls.append(argv)
        return subprocess.run(argv, text=True, capture_output=True, check=True).stdout
    def transfer(argv):
        assert argv[:2] == ["scp", "-q"]
        shutil.copyfile(argv[2].split(":", 1)[1], argv[3])
        return ""
    monkeypatch.setattr(db_sync.ssh, "run_remote", remote)
    monkeypatch.setattr(db_sync.ssh, "run_local", transfer)
    result = db_sync._pull_database(target)
    assert result == {"copied": True, "immutable": True, "path": target}
    assert db.load_deals(target) == db.load_deals(server)
    assert calls[-1][:2] == ["rm", "-f"]
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        db.update_status("ebay|1", "rejected", "2026-09-07", path=target)


def test_environment_selector_uses_immutable_baseline_for_all_imported_readers(run_db):
    _, baseline = run_db
    code = "from legoscout_cli import paths; from legoscout_cli.ledger import db, sellers, watermarks; from legoscout_cli.sources import registry; import json; print(json.dumps([paths.DB_PATH, db.DB_PATH, sellers.DB_PATH, watermarks.LEDGER, registry.DB_PATH]))"
    result = subprocess.run([sys.executable, "-c", code], env={**os.environ, "LEGOSCOUT_DB_PATH": baseline}, text=True, capture_output=True, check=True)
    assert json.loads(result.stdout) == [baseline] * 5


def test_deploy_expire_routes_to_authoritative_server(monkeypatch):
    report = {"checked": 3, "expired": 1}
    monkeypatch.setattr(deploy.availability, "expire", lambda: report)
    result = CliRunner().invoke(deploy.app, ["expire"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == report


def test_unbound_minifigure_receipt_is_rejected_at_ingestion(run_db):
    server, _ = run_db
    record = deal("ebay|minifig")
    record["listing_category"] = "minifigure"
    payload = {"version": 1, "run_id": "unreviewed", "observations": [{"expected_hash": None, "record": record}]}
    with pytest.raises(ValueError, match="receipt"):
        ingestion.ingest(payload, path=server)
    assert db.get_deal("ebay|minifig", path=server) is None


def test_source_mutation_rejected_before_prepare_and_at_server_without_registry_reads(run_db, monkeypatch):
    from legoscout_cli.ledger import source_names

    server, baseline = run_db
    valid = deal("ebay|new")
    payload = ingestion.prepare("source-mismatch", baseline, [valid])
    payload["observations"][0]["record"]["source"] = "shopgoodwill"
    before = db.load_document(server)
    monkeypatch.setattr(source_names, "canonical_table", lambda: pytest.fail(
        "namespace consistency must not read the default source registry"))
    with pytest.raises(ValueError, match="source must match listing_key namespace"):
        ingestion.prepare("source-mismatch", baseline, [payload["observations"][0]["record"]])
    with pytest.raises(ValueError, match="source must match listing_key namespace"):
        ingestion.ingest(payload, path=server)
    assert db.load_document(server) == before
    assert db.get_deal("ebay|new", path=server) is None


@pytest.mark.parametrize("status", ["inquired", "bid_placed", "purchased"])
@pytest.mark.parametrize("field", ["status", "last_status"])
def test_new_observation_cannot_invent_user_decision(run_db, status, field):
    server, baseline = run_db
    record = deal("ebay|new")
    payload = ingestion.prepare("new-user-decision", baseline, [deal(price=31), record])
    payload["observations"][1]["record"][field] = status
    before = db.load_document(server)
    with pytest.raises(ValueError, match="new observations cannot create user decisions"):
        ingestion.prepare("new-user-decision", baseline, [record])
    with pytest.raises(ValueError, match="new observations cannot create user decisions"):
        ingestion.ingest(payload, path=server)
    assert db.load_document(server) == before
    assert db.get_deal("ebay|new", path=server) is None


def test_new_rejected_observation_remains_allowed(run_db):
    server, baseline = run_db
    record = deal("ebay|excluded")
    record.update(status="rejected", last_status="rejected")
    result = ingestion.ingest(ingestion.prepare("excluded", baseline, [record]), path=server)
    assert result["inserted"] == 1
    assert db.get_deal("ebay|excluded", path=server)["status"] == "rejected"


@pytest.mark.parametrize("status", ["inquired", "bid_placed", "purchased"])
def test_existing_user_decision_in_payload_is_preserved(run_db, tmp_path, status):
    server, _ = run_db
    db.update_status("ebay|1", status, "2026-09-07T12:00:00Z", path=server)
    baseline = str(tmp_path / "decision-baseline.db")
    db.snapshot(server, baseline, baseline=True)
    record = db.get_deal("ebay|1", path=baseline)
    record["current_price"] = 40
    ingestion.ingest(ingestion.prepare("existing-decision", baseline, [record]), path=server)
    stored = db.get_deal("ebay|1", path=server)
    assert stored["status"] == stored["last_status"] == status
    assert stored["current_price"] == 40
