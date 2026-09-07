"""Publish explicit observations into the server ledger, atomically and once.

Each listing carries the observation hash read from an immutable run baseline.
An overlapping change rejects the entire batch; user decisions are never inputs
to that comparison or overwritten. Run receipts bind retries to exact payloads.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from . import db, sellers, source_names, watermarks


SERVER_FIELDS = db.SERVER_OWNED_FIELDS
USER_DECISION_STATUSES = frozenset({"inquired", "bid_placed", "purchased"})


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def payload_hash(payload: dict[str, Any]) -> str:
    """Canonical payload digest shared by the server receipt and its caller."""
    return hashlib.sha256(_json(payload).encode()).hexdigest()


def observation_hash(record: dict[str, Any] | None) -> str | None:
    """Content version of persisted observation fields; null means absent key."""
    if record is None:
        return None
    # Normalize absent/null fields exactly as SQLite stores them.
    values = {key: record.get(key) for key in db._COLUMNS if key not in SERVER_FIELDS}
    return hashlib.sha256(_json(values).encode()).hexdigest()


def validate_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict) or set(payload) != {"version", "run_id", "observations"}:
        raise ValueError("ingestion requires version, run_id, and observations only")
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise ValueError("unsupported ingestion version")
    if not isinstance(payload["run_id"], str) or not payload["run_id"].strip():
        raise ValueError("run_id must be a non-empty string")
    items = payload["observations"]
    if not isinstance(items, list) or not items:
        raise ValueError("observations must be a non-empty array")
    records = []
    keys = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {"expected_hash", "record"}:
            raise ValueError("each observation requires expected_hash and record only")
        expected = item["expected_hash"]
        if expected is not None and (not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)):
            raise ValueError("expected_hash must be null or a lowercase SHA-256 digest")
        record = item["record"]
        if not isinstance(record, dict):
            raise ValueError("record must be an object")
        if set(record) - set(db._COLUMNS):
            raise ValueError("record contains fields the ledger cannot persist: %s" % sorted(set(record) - set(db._COLUMNS)))
        key = record.get("listing_key")
        if not isinstance(key, str) or not key or key in keys:
            raise ValueError("missing or duplicate listing_key: %r" % key)
        keys.add(key)
        if record.get("source") != source_names.namespace_of(key):
            raise ValueError("source must match listing_key namespace: %s" % key)
        if expected is None and any(record.get(field) in USER_DECISION_STATUSES
                                    for field in ("status", "last_status")):
            raise ValueError("new observations cannot create user decisions: %s" % key)
        if record.get("listing_category") == "minifigure":
            from ..pricing.minifig_receipt import validate_publication_record
            validate_publication_record(record, kind="deal")
        elif (record.get("minifig_review_receipt") is not None
              or record.get("minifig_analysis") is not None
              or record.get("figure_count_source") == "detection"):
            raise ValueError("minifigure evidence requires the minifigure listing category")
        records.append(record)
    db._validate_deals(records)
    _json(payload)


def prepare(run_id: str, baseline: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    """Bind explicit records to an immutable server snapshot, without writing it."""
    conn = db.connect_readonly(baseline)
    try:
        conn.execute("BEGIN")
        marker = conn.execute("SELECT value FROM meta WHERE key = '_ingest_baseline'").fetchone()
        if marker is None or marker["value"] != "true":
            raise ValueError("baseline must be an immutable deploy pull-db snapshot")
        if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
            raise ValueError("records must be a JSON array of deal objects")
        observations = []
        for record in records:
            row = conn.execute("SELECT * FROM deals WHERE listing_key = ?", (record.get("listing_key"),)).fetchone()
            observations.append({"expected_hash": observation_hash(db._row_to_deal(row) if row else None), "record": record})
    finally:
        conn.close()
    payload = {"version": 1, "run_id": run_id, "observations": observations}
    validate_payload(payload)
    return payload


def ingest(payload: dict[str, Any], path: str = db.DB_PATH) -> dict[str, Any]:
    """Apply one keyed batch and receipt under the authoritative DB write lock."""
    validate_payload(payload)
    encoded = _json(payload)
    digest = payload_hash(payload)
    conn = sellers.connect(path)
    try:
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS ingestion_runs (run_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, payload TEXT NOT NULL, result TEXT NOT NULL)")
            receipt = conn.execute("SELECT payload_hash, result FROM ingestion_runs WHERE run_id = ?", (payload["run_id"],)).fetchone()
            if receipt is not None:
                if receipt["payload_hash"] != digest:
                    raise ValueError("run_id already accepted with a different payload: %s" % payload["run_id"])
                conn.execute("COMMIT")
                return {**json.loads(receipt["result"]), "replayed": True}
            records = []
            conflicts = []
            inserted = 0
            for item in payload["observations"]:
                record = dict(item["record"])
                row = conn.execute("SELECT * FROM deals WHERE listing_key = ?", (record["listing_key"],)).fetchone()
                current = db._row_to_deal(row) if row is not None else None
                if observation_hash(current) != item["expected_hash"]:
                    conflicts.append(record["listing_key"])
                    continue
                if current is None:
                    inserted += 1
                else:
                    for field in SERVER_FIELDS:
                        record.pop(field, None)
                        if field in current:
                            record[field] = current[field]
                records.append(record)
            if conflicts:
                raise db.StaleWrite("observation conflict; no records accepted: %s; pull a new baseline and re-observe before preparing a new run" % ", ".join(conflicts))
            db._validate_deals(records)
            cols = list(db._COLUMNS) + ["_key_order"]
            updates = ", ".join(f"{col} = excluded.{col}" for col in cols if col != "listing_key")
            conn.executemany(
                f"INSERT INTO deals ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) ON CONFLICT(listing_key) DO UPDATE SET {updates}",
                [db._deal_to_params(record) for record in records],
            )
            sellers.upsert_seen(conn, records)
            touched = {watermarks.namespace(record["listing_key"]) for record in records}
            computed = watermarks.compute_watermarks({"deals": db._deals(conn)}, namespaces=[])
            now = datetime.now(timezone.utc).isoformat()
            for source in sorted(touched):
                conn.execute("INSERT INTO source_watermarks (source, payload) VALUES (?, ?) ON CONFLICT(source) DO UPDATE SET payload = excluded.payload", (source, _json({**computed[source], "updated_at": now})))
            revision = db._bump_revision(conn, db._read_revision(conn))
            result = {"run_id": payload["run_id"], "payload_hash": digest, "inserted": inserted, "updated": len(records) - inserted, "revision": revision, "replayed": False}
            conn.execute("INSERT INTO ingestion_runs (run_id, payload_hash, payload, result) VALUES (?, ?, ?, ?)", (payload["run_id"], digest, encoded, _json(result)))
            conn.execute("COMMIT")
            return result
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
