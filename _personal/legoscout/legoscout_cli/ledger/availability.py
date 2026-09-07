"""Apply availability evidence without overwriting concurrent user decisions."""
from __future__ import annotations

from . import db

STATUS_FIELDS = ("status", "last_status", "last_seen_at", "notes")
SEEN_FIELDS = ("last_seen_at",)


def evidence_basis(deal: dict) -> dict:
    """The listing identity and freshness against which availability was checked."""
    return {field: deal.get(field) for field in (
        "source", "url", "direct_url", "auction_end_date", "last_seen_at",
    )}


def apply(changed: list[dict], path: str = db.DB_PATH) -> tuple[list[dict], list[dict]]:
    applied, skipped = [], []
    conn = db.connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for change in changed:
            key = change["listing_key"]
            fields = tuple(change["_sweep_fields"])
            if fields not in (STATUS_FIELDS, SEEN_FIELDS):
                raise ValueError("unsupported availability mutation fields")
            row = conn.execute("SELECT * FROM deals WHERE listing_key = ?", (key,)).fetchone()
            if row is None:
                skipped.append({"listing_key": key, "why": "listing_key no longer exists in the ledger"})
                continue
            fresh = db._row_to_deal(row)
            if fresh.get("status") != "active":
                skipped.append({"listing_key": key, "why": "status changed to %r during this run -- not overwritten" % fresh.get("status")})
                continue
            if change["_sweep_basis"] != evidence_basis(fresh):
                skipped.append({"listing_key": key, "why": "availability evidence is stale: listing identity or freshness changed"})
                continue
            merged = dict(fresh)
            merged.update({field: change[field] for field in fields})
            if fields == STATUS_FIELDS:
                if change["status"] not in ("unavailable", "blocked") or change["last_status"] != change["status"]:
                    raise ValueError("availability can only mark unavailable or blocked")
                note = change["_sweep_note"]
                if not isinstance(note, str) or not note.strip():
                    raise ValueError("availability status changes require evidence")
                merged["notes"] = ((fresh.get("notes") or "") + " " + note).strip()
            db._validate_deals([merged])
            conn.execute(
                "UPDATE deals SET " + ", ".join(field + " = ?" for field in fields) + " WHERE listing_key = ?",
                [merged[field] for field in fields] + [key],
            )
            applied.append(merged)
        if applied:
            db._bump_revision(conn, db._read_revision(conn))
        conn.commit()
        return applied, skipped
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
