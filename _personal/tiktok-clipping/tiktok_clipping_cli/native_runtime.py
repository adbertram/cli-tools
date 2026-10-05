"""Trusted native timing settles accounting without granting action authority."""
import hashlib
import sqlite3
from pathlib import Path

from .runtime_budget import reservation_schema, settle_runtime
from .safety import SafetyError, canonical, keys, number, strict_json, string, timestamp
from .visual import owned_bytes


def validate_timing(proof, envelope, reservation, marker, receipt_raw, now):
    keys(proof, {'schema_version', 'envelope', 'process', 'started_at', 'completed_at',
                 'elapsed_seconds', 'monotonic_started_ms', 'monotonic_completed_ms', 'receipt_sha256', 'provenance'})
    keys(marker, {'schema_version', 'job_id', 'attempt_id', 'nonce', 'pid', 'start_identity'})
    keys(proof['process'], {'pid', 'start_identity'})
    number(marker['pid'], 1, 2**31-1, integer=True)
    string(marker['start_identity'], 128)
    if (type(proof['schema_version']) is not int or type(marker['schema_version']) is not int
            or proof['schema_version'] != 1 or marker['schema_version'] != 1
            or proof['envelope'] != envelope
            or any(marker[field] != envelope[field] for field in ('job_id', 'attempt_id', 'nonce'))
            or proof['process'] != {field: marker[field] for field in ('pid', 'start_identity')}
            or proof['provenance'] != 'native_process_monotonic'
            or proof['receipt_sha256'] != hashlib.sha256(receipt_raw).hexdigest()):
        raise SafetyError('native_runtime_binding_changed')
    started, completed = timestamp(proof['started_at']), timestamp(proof['completed_at'])
    if not reservation['created_at']-5 <= started <= completed <= now+5:
        raise SafetyError('native_runtime_timestamps_invalid')
    if strict_json(receipt_raw, 1 << 20).get('envelope') != envelope:
        raise SafetyError('native_runtime_receipt_binding_changed')
    beginning = number(proof['monotonic_started_ms'],0,10**15)
    ending = number(proof['monotonic_completed_ms'],beginning,10**15)
    elapsed = number(proof['elapsed_seconds'], 0, reservation['reserved_seconds'])
    if abs((ending-beginning)/1000-elapsed) > 1e-9:
        raise SafetyError('native_runtime_elapsed_changed')
    return elapsed


def settle_native(engine, db, envelope, kind, reservation_id, receipt):
    """Missing, legacy or invalid proof holds the ceiling; outcome stays intact."""
    if reservation_id is None:
        return False
    reservation_schema(db)
    reservation = db.execute('SELECT * FROM runtime_reservations WHERE id=?', (reservation_id,)).fetchone()
    if reservation is None or reservation['settled_seconds'] is not None:
        return False
    root = Path(engine.config['workspace']) / ('visual' if kind == 'visual' else 'model') / envelope['job_id'] / envelope['attempt_id']
    if not (root / 'runtime.json').exists():
        return False
    try:
        if reservation['attempt_id'] != envelope['attempt_id'] or reservation['kind'] != kind:
            raise SafetyError('native_runtime_reservation_changed')
        raw = owned_bytes(root / 'runtime.json', Path(engine.config['workspace']), 16384)
        proof = strict_json(raw, 16384)
        marker = strict_json(owned_bytes(root / 'process-start.json', Path(engine.config['workspace']), 2048), 2048)
        filename = 'native-receipt.json' if kind == 'visual' else 'result.json'
        receipt_raw = owned_bytes(root / filename, Path(engine.config['workspace']), 1 << 20)
        if strict_json(receipt_raw, 1 << 20) != receipt:
            raise SafetyError('native_runtime_terminal_receipt_changed')
        elapsed = validate_timing(proof, envelope, reservation, marker, receipt_raw, engine.clock())
        # Refund and immutable proof become durable in this same transaction.
        db.execute('SAVEPOINT native_runtime_settlement')
        try:
            settle_runtime(engine, db, reservation_id, elapsed, proof['provenance'])
            db.execute('UPDATE runtime_reservations SET native_proof=?,native_proof_digest=?,held_reason=NULL WHERE id=?',
                       (canonical(proof), hashlib.sha256(raw).hexdigest(), reservation_id))
        except BaseException:
            db.execute('ROLLBACK TO native_runtime_settlement')
            raise
        finally:
            db.execute('RELEASE native_runtime_settlement')
        return True
    except (SafetyError, OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
        reason = str(exc) if isinstance(exc, SafetyError) else type(exc).__name__
        if reservation['held_reason'] != reason:
            db.execute('UPDATE runtime_reservations SET held_reason=? WHERE id=?', (reason, reservation_id))
            engine.event(db, envelope['job_id'], 'native_runtime_settlement_held',
                         {'attempt_id': envelope['attempt_id'], 'reservation_id': reservation_id, 'reason': reason})
        return False
