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


def test_completed_idle_discovery_settles_actual_elapsed_once(config,adapter,clock):
    from tiktok_clipping_cli.engine import Engine
    ticks=iter([10.0,12.2])
    engine=Engine(config,adapter=adapter,clock=clock,monotonic=lambda:next(ticks));engine.control('running')
    adapter.discover=lambda *args:[]
    assert engine.prepare('clip')['state']=='idle'
    with engine.transaction() as db:
        assert db.execute('SELECT runtime_seconds FROM budgets').fetchone()[0]==3
        rows=db.execute('SELECT * FROM runtime_reservations').fetchall()
        assert len(rows)==1 and rows[0]['settled_seconds']==3
        assert db.execute("SELECT count(*) FROM events WHERE event='runtime_settled'").fetchone()[0]==1


def test_nested_render_quality_publish_share_one_owner(config,adapter,clock):
    from tiktok_clipping_cli.engine import Engine
    from conftest import claim,payload
    ticks=iter([1.0,2.0,4.2])
    engine=Engine(config,adapter=adapter,clock=clock,monotonic=lambda:next(ticks));engine.control('running')
    envelope=claim(engine,clock);engine.apply(payload(envelope))
    with engine.transaction() as db:
        rows=db.execute('SELECT * FROM runtime_reservations').fetchall()
        assert len(rows)==1 and rows[0]['settled_seconds']==3
        assert db.execute('SELECT runtime_seconds FROM budgets').fetchone()[0]==3


def test_error_call_settles_and_preserves_original_failure(config,adapter,clock):
    from tiktok_clipping_cli.engine import Engine,AdapterFailure
    ticks=iter([2.0,4.1])
    engine=Engine(config,adapter=adapter,clock=clock,monotonic=lambda:next(ticks));engine.control('running')
    adapter.discover=lambda *args:(_ for _ in ()).throw(AdapterFailure('transient','TEST original'))
    with pytest.raises(AdapterFailure,match='TEST original'):engine.prepare('clip')
    with engine.transaction() as db:assert db.execute('SELECT runtime_seconds FROM budgets').fetchone()[0]==3


def test_midnight_settlement_refunds_original_day_only(engine,clock):
    from tiktok_clipping_cli.runtime_budget import reserve_operation,settle_runtime
    with engine.transaction() as db:
        reservation=reserve_operation(engine,db,'a'*32,'prepare',30)
        original=engine._day()
    clock.now+=86400
    with engine.transaction() as db:
        engine._budget(db,'runtime_seconds',10)
        first=settle_runtime(engine,db,reservation,2.5,'TEST trusted timing')
        assert settle_runtime(engine,db,reservation,2.5,'TEST trusted timing')['deduplicated']
        assert first['day']==original
        amounts={r['day']:r['runtime_seconds'] for r in db.execute('SELECT * FROM budgets')}
        assert amounts[original]==3 and amounts[engine._day()]==10


def test_crash_missing_timing_and_legacy_spend_remain_reserved(engine):
    from tiktok_clipping_cli.runtime_budget import reserve_operation
    with engine.transaction() as db:
        engine._budget(db,'runtime_seconds',100)
        reserve_operation(engine,db,'b'*32,'prepare',30)
    from tiktok_clipping_cli.engine import Engine
    restarted=Engine(engine.config,clock=engine.clock)
    with restarted.transaction() as db:
        assert db.execute('SELECT runtime_seconds FROM budgets').fetchone()[0]==130
        assert db.execute('SELECT settled_seconds FROM runtime_reservations').fetchone()[0] is None


@pytest.mark.parametrize('elapsed',[-1,float('nan'),float('inf'),31])
def test_invalid_timing_never_refunds_reservation(engine,elapsed):
    from tiktok_clipping_cli.runtime_budget import reserve_operation,settle_runtime
    with engine.transaction() as db:
        reserve_operation(engine,db,'c'*32,'prepare',30)
        with pytest.raises(SafetyError):settle_runtime(engine,db,'c'*32,elapsed,'TEST timing')
        assert db.execute('SELECT runtime_seconds FROM budgets').fetchone()[0]==30


def test_timeout_cleanup_overrun_preserves_primary_and_holds_ceiling(config,adapter,clock):
    from tiktok_clipping_cli.engine import Engine,AdapterFailure
    ticks=iter([2.0,35.0])
    engine=Engine(config,adapter=adapter,clock=clock,monotonic=lambda:next(ticks));engine.control('running')
    adapter.discover=lambda *args:(_ for _ in ()).throw(AdapterFailure('transient','TEST timeout cleanup'))
    with pytest.raises(AdapterFailure,match='TEST timeout cleanup') as error:
        engine.prepare('clip')
    assert 'no refund applied' in error.value.__notes__[0]
    with engine.transaction() as db:
        assert db.execute('SELECT runtime_seconds FROM budgets').fetchone()[0]==30
        assert db.execute('SELECT settled_seconds FROM runtime_reservations').fetchone()[0] is None
        assert db.execute("SELECT count(*) FROM events WHERE event='runtime_settlement_held'").fetchone()[0]==1


def test_completed_publication_outcome_survives_settlement_overrun(config,adapter,clock):
    from tiktok_clipping_cli.engine import Engine
    from conftest import claim,payload
    ticks=iter([1.0,2.0,33.0])
    engine=Engine(config,adapter=adapter,clock=clock,monotonic=lambda:next(ticks));engine.control('running')
    envelope=claim(engine,clock)
    result=engine.apply(payload(envelope))
    assert result['state']=='published'
    with engine.transaction() as db:
        assert db.execute("SELECT count(*) FROM publications WHERE state='published'").fetchone()[0]==1
        assert db.execute('SELECT runtime_seconds FROM budgets').fetchone()[0]==30
        assert db.execute('SELECT settled_seconds FROM runtime_reservations').fetchone()[0] is None
        assert db.execute("SELECT count(*) FROM events WHERE event='runtime_settlement_held'").fetchone()[0]==1
