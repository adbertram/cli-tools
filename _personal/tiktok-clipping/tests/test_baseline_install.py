"""Local administrative baseline CAS; no live adapters or browser operations."""
from copy import deepcopy
import json

import pytest
from typer.testing import CliRunner

from conftest import source
from test_outcome_engine import candidate, context
from test_outcome_learning import objective
from tiktok_clipping_cli.engine import Engine
from tiktok_clipping_cli.main import app
from tiktok_clipping_cli.safety import SafetyError, canonical, digest


def migration(config, adapter, clock, *, outcomes=True):
    original = deepcopy(config)
    original['baseline'] = {'weights': {'centered': 1}, 'exploration': 0}
    if outcomes:
        original['learning']['outcome_policy'] = {'objectives': [objective()], 'baseline_share': .1}
    old = Engine(original, adapter=adapter, clock=clock)
    if outcomes:
        context(old, [candidate(old, 'old-video')])
    future = deepcopy(original)
    future['baseline'] = {'weights': {'centered': 0, 'full_frame': 1}, 'exploration': 0}
    return old, Engine(future, adapter=adapter, clock=clock), future


def rows(engine, tables):
    with engine.transaction() as db:
        return {table: [dict(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY rowid')] for table in tables}


def learned(engine):
    with engine.transaction() as db:
        version = db.execute('SELECT max(version)+1 FROM strategies').fetchone()[0]
        proposal = {'weights': {'centered': .1, 'full_frame': .9}, 'exploration': 0}
        db.execute('INSERT INTO strategies VALUES(?,?,?,0)', (version, canonical(proposal), engine.clock()))
        objective_row = db.execute('SELECT * FROM objective_strategies').fetchone()
        if objective_row:
            db.execute('INSERT INTO strategy_objectives VALUES(?,?,?)', (version, objective_row['objective_key'], objective_row['descriptor']))
            db.execute("UPDATE objective_strategies SET current_version=?,last_evidence='new measured evidence' WHERE objective_key=?", (version, objective_row['objective_key']))
        db.execute("UPDATE settings SET value=? WHERE key='strategy_version'", (str(version),))
    return version


def test_append_only_install_preserves_failed_ambiguous_jobs_budgets_and_history(config, adapter, clock):
    old, future, _ = migration(config, adapter, clock)
    old.control('running')
    for status in ('failed', 'ambiguous'):
        job = old.ingest(source(clock, status))['job_id']
        with old.transaction() as db:
            db.execute('UPDATE jobs SET status=?,error=?,result=? WHERE id=?', (status, 'retained original failure', '{"original_unknown":"unchanged"}', job))
    with old.transaction() as db:
        db.execute('INSERT INTO budgets VALUES(?,?,?,?)', ('2026-10-05', 1, 12, 456))
        db.execute("UPDATE objective_strategies SET last_evidence='old evidence'")
    tables = ('jobs','sources','source_jobs','clips','publications','budgets','snapshots','rewards','revenue_history','selection_windows','text_attempts','visual_attempts')
    history = rows(old, tables)
    strategy_rows = rows(old, ('strategies','strategy_objectives'))
    snapshot = future.baseline_state()
    result = future.install_baseline(snapshot, 'Allow explicit future full-frame style')
    assert result['state'] == 'installed' and rows(future, tables) == history
    for table, previous in strategy_rows.items():
        assert rows(future, (table,))[table][:len(previous)] == previous
    after = future.baseline_state()
    assert after['objectives'][0]['baseline'] == after['objectives'][0]['current']
    assert after['objectives'][0]['baseline']['proposal_digest'] == digest(future.config['baseline'])
    assert after['objectives'][0]['descriptor_digest'] == snapshot['objectives'][0]['descriptor_digest']
    with future.transaction() as db:
        assert db.execute('SELECT last_evidence FROM objective_strategies').fetchone()[0] is None
        event = json.loads(db.execute("SELECT data FROM events WHERE event='baseline_installed'").fetchone()[0])
    assert event['before'] == snapshot and event['after'] == after
    assert event['intentional_style_space_change'] and event['reason']


def test_same_request_replay_is_noop_but_cannot_reset_subsequent_learning(config, adapter, clock):
    _, future, _ = migration(config, adapter, clock)
    snapshot = future.baseline_state()
    future.install_baseline(snapshot, 'First install')
    before = rows(future, ('strategies','events','settings','objective_strategies'))
    assert future.install_baseline(snapshot, 'Retry after lost acknowledgement')['idempotent_replay']
    assert rows(future, tuple(before)) == before
    version = learned(future)
    with pytest.raises(SafetyError, match='baseline_snapshot_conflict'):
        future.install_baseline(snapshot, 'Stale retry must preserve measured strategy')
    assert future.baseline_state()['active_strategy']['version'] == version
    now = future.baseline_state()
    assert future.install_baseline(now, 'Already installed')['state'] == 'unchanged'
    assert future.baseline_state() == now


def test_concurrent_learning_and_rollback_fence_both_current_and_baseline(config, adapter, clock):
    _, future, _ = migration(config, adapter, clock)
    snapshot = future.baseline_state()
    learned(future)
    with pytest.raises(SafetyError, match='baseline_snapshot_conflict'):
        future.install_baseline(snapshot, 'Learning won the write race')
    learned_snapshot = future.baseline_state()
    future.rollback('Concurrent operator rollback')
    with pytest.raises(SafetyError, match='baseline_snapshot_conflict'):
        future.install_baseline(learned_snapshot, 'Rollback won the write race')
    baseline_snapshot = future.baseline_state()
    with future.transaction() as db:
        db.execute('UPDATE objective_strategies SET baseline_version=current_version+1')
    with pytest.raises(SafetyError, match='baseline_objective_version_binding_changed'):
        future.install_baseline(baseline_snapshot, 'Baseline pointer corrupted')


@pytest.mark.parametrize('status', ['leased','running','ready'])
def test_active_jobs_block_install_without_changing_any_pointer(config, adapter, clock, status):
    old, future, _ = migration(config, adapter, clock)
    old.control('running');job = old.ingest(source(clock))['job_id']
    with old.transaction() as db:
        db.execute("UPDATE jobs SET status=?,lease_token='live',lease_until=? WHERE id=?", (status, clock()+100, job))
    snapshot = future.baseline_state()
    with pytest.raises(SafetyError, match='baseline_active_work'):
        future.install_baseline(snapshot, 'Refuse active worker')
    assert future.baseline_state() == snapshot


@pytest.mark.parametrize('table', ['text_attempts','visual_attempts'])
@pytest.mark.parametrize('status', ['preparing','pending','recorded'])
def test_native_work_even_with_expired_timer_blocks_install(config, adapter, clock, table, status):
    _, future, _ = migration(config, adapter, clock)
    with future.transaction() as db:
        if table == 'text_attempts':
            db.execute('INSERT INTO text_attempts(id,job_id,kind,state,envelope,settings,reservation,created_at,preparation_process) VALUES(?,?,?,?,?,?,?,?,?)', ('attempt','job','clip',status,'{}','{}','{}',clock()-1000,'{}'))
        else:
            db.execute('INSERT INTO visual_attempts(id,job_id,state,envelope,created_at,expires_at) VALUES(?,?,?,?,?,?)', ('attempt','job',status,'{}',clock()-1000,clock()-900))
    snapshot = future.baseline_state()
    with pytest.raises(SafetyError, match='baseline_active_native_work'):
        future.install_baseline(snapshot, 'Expired clock is not worker termination')
    assert future.baseline_state() == snapshot


def test_future_actual_prepare_assigns_full_frame_and_rollback_uses_new_baseline(config, adapter, clock):
    _, future, _ = migration(config, adapter, clock)
    future.install_baseline(future.baseline_state(), 'Future full-frame operation')
    future.control('running');future.ingest(source(clock,'new-video'))
    prepared = future.prepare('clip')
    assert prepared['input']['assigned_style'] == 'full_frame'
    assert prepared['input']['strategy'] == future.config['baseline']
    new_baseline = prepared['input']['outcome_selection']['baseline_version']
    with future.transaction() as db:
        db.execute("UPDATE jobs SET status='failed',lease_token=NULL,lease_until=NULL")
    learned(future)
    assert future.rollback()['strategy_version'] == new_baseline
    with future.transaction() as db:
        assert db.execute('SELECT proposal FROM strategies WHERE version=1').fetchone()[0] == canonical({'weights':{'centered':1},'exploration':0})


def test_legacy_pointer_fallback_and_new_baseline_learning_read(config, adapter, clock):
    _, future, _ = migration(config, adapter, clock, outcomes=False)
    assert future.baseline_state()['legacy_baseline']['version'] == 1
    result = future.install_baseline(future.baseline_state(), 'Legacy future baseline')
    version = result['snapshot']['legacy_baseline']['version']
    assert version > 1
    learned(future)
    assert future.rollback()['strategy_version'] == version
    with future.transaction() as db:
        assert future._baseline_version(db) == version
        db.execute("UPDATE settings SET value='missing' WHERE key='baseline_pointer'")
    with pytest.raises(SafetyError, match='baseline_pointer_invalid'):
        future.baseline_state()


def test_historical_inactive_objective_rows_unchanged_and_no_id_rename(config, adapter, clock):
    old, future, _ = migration(config, adapter, clock)
    inactive = objective('creator_net','received_cents',1209600,86400,'USD')
    with old.transaction() as db:
        state = old.outcome_strategy(db, inactive)
        saved = dict(db.execute('SELECT * FROM objective_strategies WHERE objective_key=?', (state['objective_key'],)).fetchone())
    snapshot = future.baseline_state();assert len(snapshot['objectives']) == 1
    future.install_baseline(snapshot, 'Only currently configured descriptors')
    with future.transaction() as db:
        assert dict(db.execute('SELECT * FROM objective_strategies WHERE objective_key=?', (state['objective_key'],)).fetchone()) == saved
    renamed = deepcopy(future.config)
    renamed['learning']['outcome_policy']['objectives'][0]['id'] = 'renamed label'
    future = Engine(renamed, adapter=adapter, clock=clock)
    with pytest.raises(SafetyError, match='baseline_objective_identity_changed'):
        future.baseline_state()


@pytest.mark.parametrize('target,code', [
    ({'weights':{'unknown_renderer_style':1},'exploration':0}, 'baseline_render_style_not_supported'),
    ({'weights':{'full_frame':1},'exploration':0}, 'baseline_style_removal_forbidden'),
])
def test_installed_renderer_allowlist_and_append_only_style_space(config, adapter, clock, target, code):
    _, future, _ = migration(config, adapter, clock)
    changed = deepcopy(future.config);changed['baseline'] = target
    future = Engine(changed, adapter=adapter, clock=clock)
    snapshot = future.baseline_state()
    with pytest.raises(SafetyError, match=code):
        future.install_baseline(snapshot, 'Invalid style space')
    assert future.baseline_state() == snapshot


def test_actual_cli_state_and_bounded_stdin_install(config, adapter, clock, tmp_path):
    _, future, future_config = migration(config, adapter, clock)
    config_path = tmp_path/'future.json';config_path.write_text(canonical(future_config))
    runner = CliRunner()
    snapshot = runner.invoke(app, ['strategy','baseline-state','--config',str(config_path)])
    assert snapshot.exit_code == 0, snapshot.output
    installed = runner.invoke(app, ['strategy','install-baseline','--config',str(config_path),'--reason','Explicit future style space'], input=snapshot.stdout)
    assert installed.exit_code == 0, installed.output
    assert json.loads(installed.stdout)['state'] == 'installed'
    assert future.baseline_state()['target_baseline_digest'] == digest(future_config['baseline'])


def test_mutated_in_memory_config_cannot_claim_original_policy_binding(config, adapter, clock):
    _, future, _ = migration(config, adapter, clock)
    snapshot = future.baseline_state()
    future.config['baseline']['exploration'] = .05
    with pytest.raises(SafetyError, match='baseline_config_changed'):
        future.install_baseline(snapshot, 'Cannot migrate under stale policy digest')


def test_direct_sdk_snapshot_is_bounded_and_nonfinite_rejected(config, adapter, clock):
    _, future, _ = migration(config, adapter, clock)
    snapshot = future.baseline_state()
    for bad, code in [({**snapshot,'schema_version':float('nan')},'baseline_snapshot_invalid'),
                      ({**snapshot,'extra':'x'*65536},'payload_too_large')]:
        with pytest.raises(SafetyError, match=code):
            future.install_baseline(bad, 'Bad snapshot')
    assert future.baseline_state() == snapshot
