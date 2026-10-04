import pytest

from tiktok_clipping_cli.safety import SafetyError


def test_model_reservation_duplicate_and_restart_day(engine, clock):
    with engine.transaction() as db:
        first = engine._reserve_model_attempt(db, 'attempt-1', 'clip', 120)
    clock.now += 86400
    with engine.transaction() as db:
        assert engine._reserve_model_attempt(db, 'attempt-1', 'clip', 120) == first
        rows = db.execute('SELECT * FROM budgets').fetchall()
        assert len(rows) == 1
        assert rows[0]['day'] == first['day']
        assert rows[0]['model_calls'] == 1
        assert rows[0]['runtime_seconds'] == 120


@pytest.mark.parametrize('kind,ceiling', [('learn', 120), ('clip', 121)])
def test_model_reservation_conflict_retains_budget(engine, kind, ceiling):
    with engine.transaction() as db:
        engine._reserve_model_attempt(db, 'attempt-1', 'clip', 120)
        with pytest.raises(SafetyError, match='binding_changed'):
            engine._reserve_model_attempt(db, 'attempt-1', kind, ceiling)
        assert db.execute('SELECT model_calls FROM budgets').fetchone()[0] == 1


def test_exhausted_runtime_does_not_charge_model_even_if_caught(engine):
    with engine.transaction() as db:
        engine._budget(db, 'runtime_seconds', engine.config['limits']['daily_runtime_seconds'])
        with pytest.raises(SafetyError, match='budget_exhausted: runtime_seconds'):
            engine._reserve_model_attempt(db, 'attempt-1', 'clip', 120)
        assert db.execute('SELECT model_calls FROM budgets').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM runtime_reservations').fetchone()[0] == 0


def test_attempt_and_reservation_rollback_together(engine):
    with pytest.raises(RuntimeError):
        with engine.transaction() as db:
            engine._reserve_model_attempt(db, 'attempt-1', 'clip', 120)
            raise RuntimeError('issuance_failed')
    with engine.transaction() as db:
        assert db.execute('SELECT count(*) FROM budgets').fetchone()[0] == 0
        engine._reserve_model_attempt(db, 'attempt-1', 'clip', 120)
        assert db.execute('SELECT count(*) FROM runtime_reservations').fetchone()[0] == 1
        assert db.execute('SELECT model_calls FROM budgets').fetchone()[0] == 1
