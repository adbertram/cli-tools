"""Durable reservation ownership; unfinished native calls retain their ceiling."""
import re
import secrets

from .safety import SafetyError, number


def reserve_model_attempt(engine, db, attempt_id, kind, timeout_seconds):
    if not isinstance(attempt_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", attempt_id) or kind not in {"clip", "learn", "visual"}:
        raise SafetyError("model_reservation_binding_invalid")
    ceiling = number(timeout_seconds, 1)
    db.execute("""CREATE TABLE IF NOT EXISTS runtime_reservations(
        id TEXT PRIMARY KEY, attempt_id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
        day TEXT NOT NULL, reserved_seconds REAL NOT NULL, created_at REAL NOT NULL,
        settled_seconds REAL, settled_at REAL)""")
    existing = db.execute("SELECT * FROM runtime_reservations WHERE attempt_id=?", (attempt_id,)).fetchone()
    if existing is not None:
        if existing['kind'] != kind or existing['reserved_seconds'] != ceiling:
            raise SafetyError("model_reservation_binding_changed")
        return {"reservation_id": existing['id'], "day": existing['day'], "runtime_reserved_seconds": existing['reserved_seconds']}
    day = engine._day()
    reservation_id = secrets.token_hex(16)
    db.execute("SAVEPOINT reserve_model_attempt")
    try:
        engine._budget(db, "model_calls", 1, day=day)
        engine._budget(db, "runtime_seconds", ceiling, day=day)
        db.execute("INSERT INTO runtime_reservations(id,attempt_id,kind,day,reserved_seconds,created_at) VALUES(?,?,?,?,?,?)",
                   (reservation_id, attempt_id, kind, day, ceiling, engine.clock()))
    except BaseException:
        db.execute("ROLLBACK TO reserve_model_attempt")
        raise
    finally:
        db.execute("RELEASE reserve_model_attempt")
    return {"reservation_id": reservation_id, "day": day, "runtime_reserved_seconds": ceiling}
