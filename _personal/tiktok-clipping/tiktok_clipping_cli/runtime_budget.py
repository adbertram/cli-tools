"""Durable reservation ownership; unfinished native calls retain their ceiling."""
import re
import secrets
import math

from .safety import SafetyError, number


def reservation_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS runtime_reservations(
        id TEXT PRIMARY KEY, attempt_id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
        day TEXT NOT NULL, reserved_seconds REAL NOT NULL, created_at REAL NOT NULL,
        settled_seconds REAL, settled_at REAL)""")


def reserve_operation(engine, db, operation_id, method, ceiling):
    """Trusted outer operation owner; nested calls share this one reservation."""
    if not re.fullmatch('[a-f0-9]{32}',operation_id) or not re.fullmatch('[a-z_]{1,64}',method):
        raise SafetyError('operation_reservation_binding_invalid')
    ceiling = number(ceiling,1)
    reservation_schema(db)
    existing = db.execute('SELECT * FROM runtime_reservations WHERE id=?',(operation_id,)).fetchone()
    if existing is not None:
        if existing['kind'] != 'operation:'+method or existing['reserved_seconds'] != ceiling:
            raise SafetyError('operation_reservation_binding_changed')
        return operation_id
    day = engine._day()
    engine._budget(db,'runtime_seconds',ceiling,day=day)
    db.execute('INSERT INTO runtime_reservations(id,attempt_id,kind,day,reserved_seconds,created_at) VALUES(?,?,?,?,?,?)',
        (operation_id,'operation-'+operation_id,'operation:'+method,day,ceiling,engine.clock()))
    return operation_id


def settle_runtime(engine, db, reservation_id, elapsed, provenance):
    """Only trusted finite timing may settle once, against its original UTC day."""
    row = db.execute('SELECT * FROM runtime_reservations WHERE id=?',(reservation_id,)).fetchone()
    if row is None:raise SafetyError('runtime_reservation_missing')
    measured = math.ceil(number(elapsed,0,row['reserved_seconds']))
    if measured > row['reserved_seconds']:raise SafetyError('runtime_elapsed_exceeds_reservation')
    if row['settled_seconds'] is not None:
        if measured != row['settled_seconds']:raise SafetyError('runtime_settlement_binding_changed')
        return {'reservation_id':reservation_id,'day':row['day'],'seconds':measured,'deduplicated':True}
    refund = row['reserved_seconds']-measured
    changed = db.execute('UPDATE budgets SET runtime_seconds=runtime_seconds-? WHERE day=? AND runtime_seconds>=?',(refund,row['day'],refund)).rowcount
    if changed != 1:raise SafetyError('runtime_budget_reservation_missing')
    db.execute('UPDATE runtime_reservations SET settled_seconds=?,settled_at=? WHERE id=? AND settled_seconds IS NULL',(measured,engine.clock(),reservation_id))
    engine.event(db,None,'runtime_settled',{'reservation_id':reservation_id,'day':row['day'],'reserved_seconds':row['reserved_seconds'],'seconds':measured,'provenance':provenance})
    return {'reservation_id':reservation_id,'day':row['day'],'seconds':measured,'deduplicated':False}


def reserve_model_attempt(engine, db, attempt_id, kind, timeout_seconds):
    if not isinstance(attempt_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", attempt_id) or kind not in {"clip", "learn", "visual"}:
        raise SafetyError("model_reservation_binding_invalid")
    ceiling = number(timeout_seconds, 1)
    reservation_schema(db)
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
