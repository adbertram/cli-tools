import json
import random
from types import SimpleNamespace

import pytest

from conftest import claim, payload
from conftest import source
from test_learning import metric
from test_outcome_learning import objective
from test_revenue import normalized
from tiktok_clipping_cli.engine import Engine
from tiktok_clipping_cli.outcome_learning import assign_style
from tiktok_clipping_cli.safety import SafetyError, canonical, digest


def configured(config, adapter, clock, *, money=False, baseline_share=.1):
    policy = {'objectives': [objective()], 'baseline_share': baseline_share}
    if money:
        policy['objectives'].insert(0, objective('creator_net', 'received_cents', 1209600, 86400, 'USD'))
    config['learning']['outcome_policy'] = policy
    engine = Engine(config, adapter=adapter, clock=clock)
    engine.control('running')
    return engine


def candidate(engine, media, *, source_id='source-1', ordinal=0):
    return {'candidate_id': media, 'job_id': 'TEST representative-' + media, 'source_id': source_id, 'media_id': media,
            'campaign_id': 'campaign-1', 'evidence_version': 'TEST evidence', 'ordinal': ordinal,
            'regime_digest': digest({'legacy_source_id': source_id, 'policy_digest': engine.policy_digest})}


def context(engine, rows, name='TEST window'):
    with engine.transaction() as db:
        return engine.outcome_context(db, rows, window_id=name, window_digest=digest(rows))


def publish(engine, clock, media):
    envelope = claim(engine, clock, media)
    return engine.apply(payload(envelope))['publication']


def test_exact_history_is_durable_and_keeps_polling_proof(engine, adapter, clock, config):
    envelope = claim(engine, clock)
    engine.apply(payload(envelope))
    adapter.reward_status = lambda job, ledger: normalized(clock, ledger, received='769221300334944359700')
    engine.reward_status(envelope['job_id'])
    restarted = Engine(config, adapter=adapter, clock=clock)
    with restarted.transaction() as db:
        row = dict(db.execute('SELECT * FROM revenue_history').fetchone())
    data, proof = json.loads(row['data']), json.loads(row['proof'])
    assert data['received_cents'] == '769221300334944359700' and data['pending_cents'] is None
    assert proof['polling_lease_token'] and proof['reward_request_id']
    assert proof['binding'] == data['sync']['binding']
    assert row['measured_at'] == clock() and row['recorded_at'] == clock()


def test_stale_reward_poll_does_not_append_history(engine, adapter, clock):
    envelope = claim(engine, clock)
    engine.apply(payload(envelope))
    def changed(job, ledger):
        result = normalized(clock, ledger, received='1')
        with engine.transaction() as db:
            db.execute("UPDATE rewards SET lease_token='other' WHERE job_id=?", (job['id'],))
        return result
    adapter.reward_status = changed
    assert engine.reward_status(envelope['job_id'])['reason'] == 'reward_inspection_lease_lost'
    with engine.transaction() as db:
        assert db.execute('SELECT count(*) FROM revenue_history').fetchone()[0] == 0


def test_actual_day10_receipt_never_backdated_or_retained_at_day14(config, adapter, clock):
    current = configured(config, adapter, clock, money=True)
    publication = publish(current, clock, 'late')
    job_id = current.list()[0]['id']
    clock.now += 10 * 86400
    adapter.reward_status = lambda job, ledger: normalized(clock, ledger, received='500')
    current.reward_status(job_id)
    objective14 = config['learning']['outcome_policy']['objectives'][0]
    assert current.cohorts(objective=objective14) == []
    clock.now += 4 * 86400
    adapter.reward_status = lambda job, ledger: normalized(clock, ledger, received=None, fresh=False)
    current.reward_status(job_id)
    assert current.cohorts(objective=objective14) == []
    assert current.rewards(job_id)['last_known_revenue']['received_cents']['cents'] == '500'
    with current.transaction() as db:
        assert [row['data'] for row in db.execute('SELECT data FROM revenue_history')]
    clock.now += config['limits']['metrics_poll_seconds']
    adapter.reward_status = lambda job, ledger: normalized(clock, ledger, received='-30')
    current.reward_status(job_id)
    sample = current.cohorts(objective=objective14)[0]
    assert sample['value'] == '-30' and sample['age_seconds'] == 14 * 86400 + config['limits']['metrics_poll_seconds']
    assert 'polling_lease_token' not in canonical(sample['provenance'])


def test_new_income_snapshot_changes_future_video_choice(config, adapter, clock):
    config['baseline']['exploration'] = 0
    current = configured(config, adapter, clock, money=True)
    # Root policy baseline share remains real; use fixed seed window whose branch exploits.
    context(current, [candidate(current, 'low'), candidate(current, 'high', ordinal=1)])
    publications = [(publish(current, clock, media), value) for media, value in [('low', '1'), ('low2', '1'), ('high', '500'), ('high2', '500')]]
    # Different future videos reuse their configured source strata below.
    with current.transaction() as db:
        for publication, value in publications:
            publication_row = db.execute('SELECT job_id FROM publications WHERE id=?', (publication['publication_id'],)).fetchone()
            row = current._job(db, publication_row['job_id'])
            data = json.loads(row['input'])
            regime = 'high-regime' if value == '500' else 'low-regime'
            data['outcome_selection'] = {'candidate': {'regime_digest': regime}}
            db.execute('UPDATE jobs SET input=? WHERE id=?', (canonical(data), row['id']))
    clock.now += 14 * 86400
    for publication, value in publications:
        job_id = next(row['id'] for row in current.list() if row['result'] and row['result'].get('publication_id') == publication['publication_id'])
        adapter.reward_status = lambda job, ledger, v=value: normalized(clock, ledger, received=v)
        current.reward_status(job_id)
    low, high = candidate(current, 'new-low'), candidate(current, 'new-high', ordinal=1)
    low['regime_digest'], high['regime_digest'] = 'low-regime', 'high-regime'
    result = context(current, [low, high])
    assert result['decision']['candidate_id'] == 'new-high'
    assert result['decision']['objective']['field'] == 'received_cents'
    assert result['decision']['distribution']['new-low'] == {'numerator': '1', 'denominator': '20'}


def test_legacy_config_does_not_migrate_baseline(engine):
    with engine.transaction() as db:
        assert db.execute('SELECT count(*) FROM objective_strategies').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM strategies').fetchone()[0] == 1


def test_objective_migration_keeps_history_budgets_and_independent_baseline(config, adapter, clock):
    current = configured(config, adapter, clock, money=True)
    with current.transaction() as db:
        revenue = current.outcome_strategy(db, config['learning']['outcome_policy']['objectives'][0])
        views = current.outcome_strategy(db, config['learning']['outcome_policy']['objectives'][1])
        assert revenue['baseline_version'] != views['baseline_version']
        assert db.execute('SELECT count(*) FROM objective_strategies').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM budgets').fetchone()[0] == 0
    restarted = Engine(config, adapter=adapter, clock=clock)
    with restarted.transaction() as db:
        assert restarted.outcome_strategy(db, config['learning']['outcome_policy']['objectives'][0]) == revenue


def test_learn_proposal_binds_descriptor_and_revisions(config, adapter, clock):
    current = configured(config, adapter, clock)
    context(current, [candidate(current, 'a')])
    pubs = [publish(current, clock, media) for media in ('a', 'b')]
    clock.now += 86400
    for pub in pubs:
        current.snapshot(metric(clock, pub, age=86400))
    envelope = current.prepare('learn')
    assert envelope['input']['outcome_objective'] == objective()
    proposal = {'weights': {'plain': .6, 'highlight': .4}, 'exploration': .05}
    request = {key: envelope[key] for key in ('job_id', 'lease_token', 'input_digest', 'policy_digest')} | {'proposal': proposal}
    current.snapshot(metric(clock, pubs[0], age=86400, observed=clock() + 1, views=None))
    with pytest.raises(SafetyError, match='stale_learning_evidence'):
        current.apply(request)


def test_branch_styles_are_independent_and_actual_probabilities_normalized():
    active = {'weights': {'plain': 0, 'highlight': 1}, 'exploration': .1}
    baseline = {'weights': {'plain': 1, 'highlight': 0}, 'exploration': .05}
    assert assign_style(active, baseline, 'baseline', 1)['style'] == 'plain'
    assert assign_style(active, baseline, 'exploitation', 1)['style'] == 'highlight'
    explored = assign_style(active, baseline, 'exploration', 1)
    assert explored['propensity'] == {'numerator': '1', 'denominator': '2'}
    revised = assign_style(active, baseline, 'exploration', 1, allowed=['plain'])
    assert revised['style'] == 'plain' and revised['propensity'] == {'numerator': '1', 'denominator': '1'}


def controlled_seed(monkeypatch):
    from tiktok_clipping_cli import outcome_learning
    # Real sampling with seed0 takes the exploitation branch at B=.1/E=0.
    # The candidate winner is still calculated from the actual measured cohort.
    monkeypatch.setattr(outcome_learning, 'random', SimpleNamespace(Random=lambda seed: random.Random(0)))


def test_actual_prepare_changes_next_source_from_measured_outcomes(config, adapter, clock, monkeypatch):
    controlled_seed(monkeypatch)
    config['sources'].append({**config['sources'][0], 'id': 'source-2'})
    config['baseline']['exploration'] = 0
    current = configured(config, adapter, clock)
    publications = []
    for source_id, value in [('source-1', 10), ('source-2', 1000)]:
        for index in range(2):
            record = source(clock, source_id + '-' + str(index))
            record['source_id'] = source_id
            current.ingest(record)
            envelope = current.prepare('clip')
            publications.append((current.apply(payload(envelope))['publication'], value))
    clock.now += 86400
    for publication, value in publications:
        current.snapshot(metric(clock, publication, views=value, age=86400))
    low = source(clock, 'old-low')
    high = source(clock, 'new-high')
    high['source_id'] = 'source-2'
    current.ingest(low)
    clock.now += 1
    current.ingest(high)
    prepared = current.prepare('clip')
    assert prepared['input']['source_id'] == 'source-2'
    decision = prepared['input']['outcome_selection']
    assert decision['candidate']['media_id'] == 'new-high'
    assert decision['reason'] == 'measured_outcome' and decision['branch'] == 'exploitation'
    assert decision['propensity'] == {'numerator': '19', 'denominator': '20'}
    with current.transaction() as db:
        row = db.execute('SELECT * FROM selection_windows WHERE id=?', (decision['window_id'],)).fetchone()
        assert digest(json.loads(row['candidates'])) == decision['window_digest']
        assert len(json.loads(row['candidates'])) == 2


def test_actual_prepare_changes_next_video_not_only_source(config, adapter, clock, monkeypatch):
    controlled_seed(monkeypatch)
    config['baseline']['exploration'] = 0
    current = configured(config, adapter, clock)
    pubs = [(publish(current, clock, video), value) for video, value in [('low', 10), ('high', 1000)]]
    # Second distinct allowed edit per video supplies enough video samples.
    for video, value in [('low', 10), ('high', 1000)]:
        current.ingest(source(clock, video))
        envelope = current.prepare('clip')
        pubs.append((current.apply(payload(envelope, start_seconds=40, end_seconds=60))['publication'], value))
    clock.now += 86400
    for publication, value in pubs:
        current.snapshot(metric(clock, publication, views=value, age=86400))
    current.ingest(source(clock, 'low'))
    clock.now += 1
    current.ingest(source(clock, 'high'))
    prepared = current.prepare('clip')
    assert prepared['input']['media_id'] == 'high'
    assert next(row for row in prepared['input']['outcome_selection']['scores'] if row['candidate_id'] == prepared['job_id'])['scope'] == 'video'


def test_untrusted_ingest_cannot_supply_selection_proof(config, adapter, clock):
    current = configured(config, adapter, clock)
    record = source(clock, 'malicious')
    record['outcome_selection'] = {'branch': 'baseline', 'candidate': {'regime_digest': 'fabricated'}}
    with pytest.raises(SafetyError):
        current.ingest(record)


def test_revenue_sparse_regimes_continue_to_mature_engagement(config, adapter, clock, monkeypatch):
    current = configured(config, adapter, clock, money=True)
    revenue, engagement = config['learning']['outcome_policy']['objectives']
    with current.transaction() as db:
        money_state = current.outcome_strategy(db, revenue)
        views_state = current.outcome_strategy(db, engagement)
    def measured(db, objective):
        state = money_state if objective['channel'] == 'creator_net' else views_state
        return [{'publication_id': str(i), 'version': state['baseline_version'], 'campaign_id': 'campaign',
                 'regime_digest': str(i) if objective['channel'] == 'creator_net' else 'same',
                 'assigned_at': clock(), 'style': 'plain', 'branch': 'baseline',
                 'value': '100' if objective['channel'] == 'creator_net' else 100} for i in range(2)]
    monkeypatch.setattr(current, '_outcome_cohorts', measured)
    result = current._learn_input()
    assert result['outcome_objective'] == engagement and result['reason'] == 'engagement_proxy'
    assert result['skipped_objectives'][0]['reason'] == 'compatible_contemporary_controls_required'


def test_old_high_baseline_cannot_rollback_without_contemporary_controls(config, adapter, clock, monkeypatch):
    current = configured(config, adapter, clock)
    obj = config['learning']['outcome_policy']['objectives'][0]
    with current.transaction() as db:
        state = current.outcome_strategy(db, obj)
        version = state['strategy_version'] + 1
        db.execute('INSERT INTO strategies VALUES(?,?,?,0)', (version, canonical(config['baseline']), clock()))
        db.execute('UPDATE objective_strategies SET current_version=? WHERE objective_key=?', (version, state['objective_key']))
    rows = [{'publication_id': str(i), 'version': state['baseline_version'], 'campaign_id': 'campaign',
             'regime_digest': 'same', 'assigned_at': clock() - 100, 'value': 1000, 'style': 'plain', 'branch': 'baseline'} for i in range(2)]
    rows += [{'publication_id': str(i + 2), 'version': version, 'campaign_id': 'campaign',
              'regime_digest': 'same', 'assigned_at': clock() + 1, 'value': 10, 'style': 'plain', 'branch': 'exploitation'} for i in range(2)]
    monkeypatch.setattr(current, '_outcome_cohorts', lambda db, objective: rows)
    assert current._learn_input() is None
    with current.transaction() as db:
        assert current.outcome_strategy(db, obj)['strategy_version'] == version
    # Real contemporary baseline controls now establish the observed regression.
    rows += [{**row, 'publication_id': 'control-' + str(i), 'assigned_at': clock() + 1} for i, row in enumerate(rows[:2])]
    assert current._learn_input() is None
    with current.transaction() as db:
        assert current.outcome_strategy(db, obj)['strategy_version'] == state['baseline_version']


def test_year_scale_learning_view_keeps_full_exact_stats_digest_and_stale_fence(config, adapter, clock, monkeypatch):
    current = configured(config, adapter, clock, money=True)
    obj = config['learning']['outcome_policy']['objectives'][0]
    with current.transaction() as db:
        state = current.outcome_strategy(db, obj)
    huge = '769221300334944359700'
    rows = [{'publication_id': 'p-' + str(i), 'version': state['baseline_version'], 'campaign_id': 'campaign',
             'regime_digest': 'same', 'assigned_at': clock(), 'measured_at': clock(), 'value': huge,
             'style': 'plain', 'branch': 'baseline', 'caption': 'A' * 4000} for i in range(36500)]
    monkeypatch.setattr(current, '_outcome_cohorts', lambda db, objective: rows if objective == obj else [])
    data = current._learn_input()
    assert 0 < len(data['samples']) < 20
    assert len(current._proposal_prompt('learn', data).encode()) <= config['limits']['max_payload_bytes']
    assert data['sample_view'] == {'complete': False, 'total_samples': 36500, 'max_examples': 20}
    assert data['evidence_digest'] == digest(rows)
    summary = data['sufficient_statistics'][0]
    assert summary['count'] == 36500 and summary['total'] == {'numerator': str(int(huge) * 36500), 'denominator': '1'}
    assert summary['mean'] == {'numerator': huge, 'denominator': '1'}
    # The complete cohort, not just the20example view, fences later callbacks.
    rows[0] = {**rows[0], 'value': '-1'}
    with current.transaction() as db:
        version, observed = current._learning_binding(db, data)
    assert version == state['strategy_version'] and digest(observed) != data['evidence_digest']


def test_zero_baseline_operational_policy_is_rejected(config, adapter, clock):
    with pytest.raises(SafetyError, match='outcome_baseline_share_required'):
        configured(config, adapter, clock, baseline_share=0)
