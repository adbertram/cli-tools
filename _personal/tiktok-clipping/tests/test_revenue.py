import copy
import json

import pytest

from conftest import claim, iso, payload
from tiktok_clipping_cli.engine import AdapterFailure
from tiktok_clipping_cli.revenue import normalize_revenue, retain_known, validate_revenue
from tiktok_clipping_cli.safety import SafetyError, canonical


def observation(clock, ledger, *, received='900719925474099312345', pending=None, total=None, complete=True, fresh=True):
    return {'submission_id': ledger['submission']['submission_id'],
        'campaign_id': ledger['campaign_id'], 'publication_id': ledger['publication_id'],
        'status': 'approved' if fresh else None, 'creator_status': 'approved' if fresh else None,
        'flagged': False if fresh else None, 'is_deleted': False if fresh else None,
        'readback_fresh': complete and fresh, 'observed_at': iso(clock()) if complete else None,
        'pending_cents': pending, 'received_cents': received, 'total_earned_cents': total,
        'currency': 'USD', 'amount_basis': 'creator_net', 'amounts_verified': pending is not None and received is not None,
        'unknown_reasons': ['pending_net_amount_unknown'] if pending is None else [],
        'sync': {'complete': complete, 'started_at': iso(clock()-10), 'completed_at': iso(clock()) if complete else None,
            'binding': {'account_id': 'user_fixture', 'profile': 'rewards', 'experience': 'https://example.apps.whop.com/c/exp_TEST'}},
        'provenance': {'moderation_readback_fresh': fresh, 'moderation_observed_at': iso(clock()) if fresh else None}}


def publish(engine, clock):
    envelope = claim(engine, clock)
    engine.apply(payload(envelope))
    return envelope['job_id']


def normalized(clock, ledger, **kwargs):
    return normalize_revenue(observation(clock, ledger, **kwargs), ledger,
        {'account_id': 'user_fixture', 'profile': 'rewards'}, 'https://example.apps.whop.com/c/exp_TEST', 65536)


def test_independent_received_net_preserves_exact_big_string(engine, adapter, clock):
    job_id = publish(engine, clock)
    adapter.reward_status = lambda job, ledger: normalized(clock, ledger)
    result = engine.reward_status(job_id)
    assert result['state'] == 'accepted'
    assert result['revenue_observation']['amounts_verified'] is False
    assert result['last_known_revenue']['received_cents']['cents'] == '900719925474099312345'
    assert result['earnings'] is None
    with engine.transaction() as db:
        assert db.execute('SELECT count(*) FROM snapshots WHERE channel=?', ('rewards',)).fetchone()[0] == 0


def test_unknown_preserves_prior_known_and_new_reversal_replaces(engine, adapter, clock, config):
    job_id = publish(engine, clock)
    adapter.reward_status = lambda job, ledger: normalized(clock, ledger, received='150')
    first = engine.reward_status(job_id)
    original_time = first['last_known_revenue']['received_cents']['observed_at']
    clock.now += config['limits']['metrics_poll_seconds']
    adapter.reward_status = lambda job, ledger: normalized(clock, ledger, received=None, fresh=False)
    unknown = engine.reward_status(job_id)
    assert unknown['state'] == 'accepted'
    assert unknown['revenue_observation']['received_cents'] is None
    assert unknown['last_known_revenue']['received_cents']['observed_at'] == original_time
    clock.now += config['limits']['metrics_poll_seconds']
    adapter.reward_status = lambda job, ledger: normalized(clock, ledger, received='-30')
    reversed_result = engine.reward_status(job_id)
    assert reversed_result['last_known_revenue']['received_cents']['cents'] == '-30'
    assert reversed_result['last_known_revenue']['received_cents']['observed_at'] != original_time


def test_cached_old_scan_never_overwrites_newer_known(engine, adapter, clock, config):
    job_id = publish(engine, clock)
    ledger = engine.rewards(job_id)
    old = normalized(clock, ledger, received='999')
    clock.now += 100
    adapter.reward_status = lambda job, ledger: normalized(clock, ledger, received='20')
    result = engine.reward_status(job_id)
    known = result['last_known_revenue']
    clock.now += config['limits']['metrics_poll_seconds']
    adapter.reward_status = lambda job, ledger: old
    repeated = engine.reward_status(job_id)
    assert repeated['last_known_revenue'] == known
    assert repeated['state'] == 'accepted'
    assert repeated['revenue_observation']['observed_at'] == old['revenue']['observed_at']


def test_slow_stale_read_cannot_overwrite_reclaimed_owner(engine, adapter, clock, config):
    job_id = publish(engine, clock)
    def late(job, ledger):
        result = normalized(clock, ledger, received='1')
        clock.now += config['limits']['lease_seconds'] + 1
        with engine.transaction() as db:
            db.execute("UPDATE rewards SET lease_token='new-owner',lease_until=?,state='accepted',last_known_revenue=? WHERE job_id=?",
                (clock()+100, canonical({'received_cents': {'cents': '2', 'currency': 'USD', 'observed_at': iso(clock())}}), job_id))
        # Test coordinator CAS independently of the adapter wall-time limit.
        engine._deadline = clock() + 30
        return result
    adapter.reward_status = late
    # _call detects elapsed work first. Its error cleanup must also retain new owner.
    with pytest.raises(AdapterFailure, match='adapter_work_timeout'):
        engine.reward_status(job_id)
    with engine.transaction() as db:
        row = db.execute('SELECT * FROM rewards WHERE job_id=?', (job_id,)).fetchone()
        assert row['lease_token'] == 'new-owner' and row['state'] == 'accepted'
        assert json.loads(row['last_known_revenue'])['received_cents']['cents'] == '2'


def test_changed_owner_before_read_completion_returns_actual_state(engine, adapter, clock):
    job_id = publish(engine, clock)
    def late(job, ledger):
        result = normalized(clock, ledger, received='1')
        with engine.transaction() as db:
            db.execute("UPDATE rewards SET lease_token='new-owner',state='accepted' WHERE job_id=?", (job_id,))
        return result
    adapter.reward_status = late
    result = engine.reward_status(job_id)
    assert result['state'] == 'accepted' and result['reason'] == 'reward_inspection_lease_lost'
    assert engine.rewards(job_id)['last_known_revenue'] is None


def test_due_poll_survives_restart_and_repeated_tick_skips(engine, adapter, clock, config):
    job_id = publish(engine, clock)
    calls = []
    adapter.reward_status = lambda job, ledger: calls.append(job['id']) or normalized(clock, ledger)
    engine.reward_status(job_id)
    engine.maintain()
    assert calls == [job_id]
    from tiktok_clipping_cli.engine import Engine
    restarted = Engine(config, adapter=adapter, clock=clock)
    restarted.maintain()
    assert calls == [job_id]
    clock.now += config['limits']['metrics_poll_seconds']
    restarted.maintain()
    assert calls == [job_id, job_id]


def test_one_shared_scan_for_due_batch(engine, adapter, clock, config):
    ids = [publish(engine, clock)]
    second = claim(engine, clock, 'media-2')
    engine.apply(payload(second))
    ids.append(second['job_id'])
    config['rewards_account'] = {'account_id': 'user_fixture', 'username': 'fixture', 'profile': 'rewards', 'verified_at': iso(clock()), 'provenance': 'TEST'}
    calls = []
    adapter.sync_reward_revenue = lambda: calls.append('sync') or {'complete': True}
    adapter.reward_status = lambda job, ledger, refresh: calls.append((job['id'], refresh)) or normalized(clock, ledger)
    result = engine.maintain()
    assert result['processed'] == 2
    assert calls[0] == 'sync' and len(calls) == 3
    assert {item[0] for item in calls[1:]} == set(ids)
    assert all(item[1] is False for item in calls[1:])
    engine.maintain()
    assert len(calls) == 3


def test_batch_rate_limit_schedules_all_due_and_stops_provider(engine, adapter, clock, config):
    job_id = publish(engine, clock)
    config['rewards_account'] = {'account_id': 'user_fixture', 'username': 'fixture', 'profile': 'rewards', 'verified_at': iso(clock()), 'provenance': 'TEST'}
    def refused():
        raise AdapterFailure('rate_limit', 'TEST typed limit', 90000, provider='whop')
    adapter.sync_reward_revenue = refused
    result = engine.maintain()
    assert result['results'][0]['state'] == 'revenue_sync_failed'
    assert engine.rewards(job_id)['next_at'] == clock() + 90000
    with pytest.raises(AdapterFailure, match='provider:whop'):
        engine._call('verify_ready', {})


@pytest.mark.parametrize('mutation', [
    lambda r: r.update(publication_id='other'),
    lambda r: r.update(received_cents=1),
    lambda r: r.update(currency=None),
    lambda r: r.update(amount_basis='gross'),
    lambda r: r.update(readback_fresh=False),
    lambda r: r.update(total_earned_cents='2', pending_cents='1'),
])
def test_invalid_sdk_money_proof_refused(engine, clock, mutation):
    job_id = publish(engine, clock)
    ledger = engine.rewards(job_id)
    raw = observation(clock, ledger)
    mutation(raw)
    with pytest.raises(SafetyError):
        normalize_revenue(raw, ledger, {'account_id': 'user_fixture', 'profile': 'rewards'}, 'https://example.apps.whop.com/c/exp_TEST', 65536)


def test_incomplete_money_pass_can_have_fresh_moderation(engine, adapter, clock):
    job_id = publish(engine, clock)
    adapter.reward_status = lambda job, ledger: normalized(clock, ledger, received=None, complete=False)
    result = engine.reward_status(job_id)
    assert result['state'] == 'accepted'
    assert result['last_known_revenue'] == {}
    assert result['revenue_observation']['sync']['complete'] is False


@pytest.mark.parametrize('sync_failure', ['slow', 'refused'])
def test_urgent_submission_precedes_due_earnings_scan(engine, adapter, clock, config, sync_failure):
    old = publish(engine, clock)
    second = claim(engine, clock, 'media-2')
    engine.apply(payload(second))
    config['rewards_account'] = {'account_id': 'user_fixture', 'username': 'fixture', 'profile': 'rewards', 'verified_at': iso(clock()), 'provenance': 'TEST'}
    with engine.transaction() as db:
        db.execute("UPDATE rewards SET state='pending_submission',submission=NULL,creation_proof=NULL,deadline=? WHERE job_id=?", (clock()+10, second['job_id']))
    calls = []
    original = adapter.submit_rewards
    adapter.submit_rewards = lambda job, ledger: calls.append('urgent-submit') or original(job, ledger)
    def scan():
        calls.append('earnings-sync')
        if sync_failure == 'slow':
            clock.now += config['limits']['work_timeout_seconds'] + 1
            return {'complete': True}
        raise AdapterFailure('rate_limit', 'TEST scan refusal', 90000, provider='whop')
    adapter.sync_reward_revenue = scan
    result = engine.maintain()
    assert calls[:2] == ['urgent-submit', 'earnings-sync']
    assert engine.rewards(second['job_id'])['state'] == 'submitted'
    assert result['results'][0]['state'] == 'submitted'
    assert result['results'][-1]['state'] == 'revenue_sync_failed'


def test_urgent_submission_precedes_slow_visual_cleanup_even_with_full_media(engine, adapter, clock, config, monkeypatch):
    job_id = publish(engine, clock)
    with engine.transaction() as db:
        db.execute("UPDATE rewards SET state='pending_submission',submission=NULL,creation_proof=NULL,deadline=? WHERE job_id=?", (clock()+10, job_id))
    calls = []
    original = adapter.submit_rewards
    adapter.submit_rewards = lambda job, ledger: calls.append('urgent-submit') or original(job, ledger)
    def no_media_allowance():
        raise SafetyError('disk_budget_exhausted')
    monkeypatch.setattr(engine, '_disk_check', no_media_allowance)
    def slow_cleanup():
        calls.append('visual-cleanup')
        assert engine.rewards(job_id)['state'] == 'submitted'
        clock.now += config['limits']['work_timeout_seconds'] + 1
        return 0
    monkeypatch.setattr(engine, 'prune_visual_artifacts', slow_cleanup)
    result = engine.maintain()
    assert calls == ['urgent-submit', 'visual-cleanup']
    assert result['results'][0]['state'] == 'submitted'


@pytest.mark.parametrize('flags,raw,creator,expected', [
    ((True, False), 'pending', 'rejected', 'rejected'),
    ((False, False), 'approved', 'approved', 'accepted'),
    ((None, None), 'approved', None, 'unknown'),
    ((True, None), 'rejected', None, 'unknown'),
])
def test_moderation_uses_only_verified_creator_status(engine, clock, flags, raw, creator, expected):
    ledger = engine.rewards(publish(engine, clock))
    record = observation(clock, ledger)
    record.update(flagged=flags[0], is_deleted=flags[1], status=raw, creator_status=creator)
    result = normalize_revenue(record, ledger, {'account_id': 'user_fixture', 'profile': 'rewards'},
        'https://example.apps.whop.com/c/exp_TEST', 65536)
    assert result['status'] == expected
