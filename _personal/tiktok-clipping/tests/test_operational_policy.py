from conftest import payload
from test_visual import visual_engine, issue, receipt
from tiktok_clipping_cli.visual import CHECKS


def test_final_allowed_visual_revision_can_publish_once(visual_engine, adapter, clock):
    visual_engine.config['limits']['max_attempts'] = 12
    visual_engine.config['limits']['max_revisions'] = 2
    envelope = issue(visual_engine, clock)
    job_id = envelope['job_id']
    for revision in (1, 2):
        rejected = receipt(envelope, clock, decision={
            'passed': False, 'checks': dict.fromkeys(CHECKS, False),
            'reason': 'TEST improve speech caption legibility before publication',
        })
        assert visual_engine.apply_visual(rejected)['state'] == 'queued'
        assert visual_engine.get(job_id)['revisions'] == revision
        assert adapter.uploads == []
        proposal = visual_engine.prepare('clip')
        assert proposal['job_id'] == job_id
        envelope = visual_engine.apply(payload(proposal))['visual']
    approved = receipt(envelope, clock)
    result = visual_engine.apply_visual(approved)
    assert result['state'] == 'published'
    assert visual_engine.get(job_id)['revisions'] == 2
    assert visual_engine.get(job_id)['attempts'] < 12
    assert len(adapter.uploads) == 1
    assert visual_engine.apply_visual(approved)['deduplicated']
    assert len(adapter.uploads) == 1


def test_received_14day_objective_bypasses_legacy_8day_filter(config, adapter, clock):
    from test_outcome_engine import configured, publish
    from test_revenue import normalized
    config['learning']['cohort_age_seconds'] = 8 * 86400
    config['limits']['metrics_max_age_seconds'] = 15 * 86400
    current = configured(config, adapter, clock, money=True)
    publication = publish(current, clock, 'TEST fourteen-day actual receipt')
    job_id = current.list()[0]['id']
    clock.now += 14 * 86400
    adapter.reward_status = lambda job, ledger: normalized(clock, ledger, received='500')
    current.reward_status(job_id)
    descriptor = current.config['learning']['outcome_policy']['objectives'][0]
    samples = current.cohorts(objective=descriptor)
    assert descriptor['horizon_seconds'] == 14 * 86400
    assert len(samples) == 1 and samples[0]['value'] == '500'
    assert samples[0]['publication_id'] == publication['publication_id']
    assert samples[0]['age_seconds'] == 14 * 86400


def test_sparse_or_unchanged_hourly_learning_issues_no_attempt_or_charge(config, adapter, clock, monkeypatch):
    from test_outcome_engine import configured
    from tiktok_clipping_cli.safety import digest
    current = configured(config, adapter, clock)
    assert current.prepare('learn')['ready'] is False
    with current.transaction() as db:
        objective = current.config['learning']['outcome_policy']['objectives'][0]
        state = current.outcome_strategy(db, objective)
    rows = [{'publication_id': str(i), 'version': state['baseline_version'],
             'campaign_id': 'TEST campaign', 'regime_digest': 'TEST same regime',
             'assigned_at': clock(), 'value': 50, 'style': next(iter(config['baseline']['weights'])),
             'branch': 'baseline'} for i in range(config['learning']['minimum_samples'])]
    monkeypatch.setattr(current, '_outcome_cohorts', lambda db, objective: rows)
    with current.transaction() as db:
        db.execute('UPDATE objective_strategies SET last_evidence=? WHERE objective_key=?',
                   (digest(rows), state['objective_key']))
    assert current.prepare('learn')['ready'] is False
    with current.transaction() as db:
        assert db.execute("SELECT count(*) FROM jobs WHERE kind='learn'").fetchone()[0] == 0
        assert db.execute('SELECT coalesce(sum(model_calls),0) FROM budgets').fetchone()[0] == 0


def test_workflow_deadline_covers_serial_work_and_native_ceilings():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / 'deploy'
    config = json.loads((root / 'config.json').read_text())
    work = config['limits']['work_timeout_seconds']
    text = config['native_text']['timeout_seconds']
    visual = config['visual']['timeout_seconds']
    serial = {'clip': 3 * work + text + visual,
              'learn': 2 * work + text, 'metrics': work, 'maintain': work}
    for kind, ceiling in serial.items():
        graph = json.loads((root / 'workflows' / (kind + '.json')).read_text())
        assert graph['settings']['executionTimeout'] >= ceiling + 360
