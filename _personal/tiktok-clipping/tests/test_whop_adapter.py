"""Real coordinator reservation with owning Whop SDK doubles, never a live write."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from conftest import claim, payload, iso
from tiktok_clipping_cli.engine import AdapterFailure, Engine
from tiktok_clipping_cli.safety import SafetyError, canonical
from tiktok_clipping_cli.whop_adapter import WhopSubmissionAdapter, submission_request_id


@pytest.fixture
def reward_context(engine, adapter, config, clock):
    config['rewards_account'] = {'account_id': 'user_fixture', 'username': 'fixture', 'profile': 'rewards', 'verified_at': iso(clock()), 'provenance': 'TEST'}
    envelope = claim(engine, clock)
    engine.apply(payload(envelope), execute=False)
    job_id = envelope['job_id']
    publication = adapter.receipt({'id': job_id})
    actor = {k: config['rewards_account'][k] for k in ('account_id', 'username', 'profile')}
    snapshot = {'actor': actor, 'campaign_id': 'campaign-1', 'requirements_digest': 'a' * 64,
        'readiness': {'requirements': {'experience': 'https://fixture.example/rewards'}}}
    with engine.transaction() as db:
        db.execute("UPDATE jobs SET status='published',result=?,readiness=? WHERE id=?", (canonical(publication), canonical({'provenance': canonical(snapshot)}), job_id))
        db.execute("INSERT INTO publications VALUES(?,?,?,?,?,'published',?,1)", (publication['publication_id'], job_id, publication['account_id'], 'b' * 64, 'c' * 64, canonical(publication)))
        db.execute("INSERT INTO rewards(job_id,publication_id,campaign_id,state,deadline,updated_at) VALUES(?,?,?,'pending_submission',?,?)", (job_id, publication['publication_id'], 'campaign-1', clock() + 600, clock()))
    bridge = WhopSubmissionAdapter(config, clock=clock)
    class SDK:
        def __init__(self): self.sends = 0; self.reads = 0; self.row = None; self.fail = False; self.before_confirm = None
        def create_submission(self, request, campaign, publication, **kwargs):
            if self.row is not None and self.row['state'] != 'reserved':
                return self.reconcile_submission(request)
            bound = {'profile': 'rewards', 'experience': 'https://fixture.example/rewards', 'account_id': 'user_fixture',
                'tiktok_account_id': publication['account_id'], 'campaign_id': campaign, 'publication': publication, 'requirements_digest': kwargs['accepted_requirements_digest']}
            self.row = {'request_id': request, 'binding': bound, 'state': 'reserved', 'public_action_dispatched': False}
            ready = {'ready': True, 'actor': actor, 'campaign_id': campaign, 'requirements_digest': 'a' * 64,
                'linked_account': {'account_id': publication['account_id'], 'username': publication['handle']}, 'funding_remaining_cents': 10000, 'observed_at': iso(clock())}
            if self.before_confirm: self.before_confirm()
            assert kwargs['confirm']({'request_id': request, 'binding': bound, 'readiness': ready}) is True
            self.sends += 1
            self.row.update(state='uncertain' if self.fail else 'submitted_verified', public_action_dispatched=True,
                dispatched_at=iso(clock()), observed_at=iso(clock()), readback_fresh=True,
                submission_id='provider-fixture', submission={'id': 'provider-fixture', 'campaignId': campaign,
                'status': 'pending', 'socialMediaPost': {'platform': 'tiktok', 'postId': publication['publication_id']}})
            return deepcopy(self.row)
        def reconcile_submission(self, request):
            self.reads += 1
            assert request == self.row['request_id']
            return deepcopy(self.row)
    sdk = SDK()
    adapter.submit_rewards = lambda job, ledger: bridge.submit(sdk, job, ledger)
    adapter.reconcile_rewards = lambda job, ledger: bridge.reconcile(sdk, job, ledger)
    return job_id, bridge, sdk


def test_confirm_reserves_before_dispatch_and_exact_readback_persists(engine, config, reward_context):
    job, _, sdk = reward_context
    assert engine.submit_rewards(job)['state'] == 'submitted'
    assert sdk.sends == 1
    assert engine.submit_rewards(job)['deduplicated'] is True
    reward = engine.rewards(job)
    assert 'lease_token' not in reward
    assert reward['request_id'] == submission_request_id('campaign-1', reward['publication_id'])
    assert reward['submission']['submission_id'] == 'provider-fixture'
    with engine.transaction() as db: assert db.execute('SELECT dispatch_evidence FROM rewards').fetchone()[0] is not None


@pytest.mark.parametrize('change', ['pause', 'lease', 'publication', 'deadline'])
def test_changed_authority_aborts_before_one_submission_send(engine, clock, reward_context, change):
    job, _, sdk = reward_context
    def change_state():
        with engine.transaction() as db:
            if change == 'pause': db.execute("UPDATE settings SET value='paused' WHERE key='control'")
            elif change == 'lease': db.execute("UPDATE rewards SET lease_token='another-owner'")
            elif change == 'publication': db.execute("UPDATE publications SET data='{}'")
            else: db.execute('UPDATE rewards SET deadline=?', (clock(),))
    sdk.before_confirm = change_state
    result = engine.submit_rewards(job)
    assert result['state'] != 'submitted' and sdk.sends == 0
    assert sdk.row['state'] == 'reserved' and sdk.row['public_action_dispatched'] is False


def test_uncertain_then_restart_reconciles_exact_same_request_without_send(engine, adapter, config, clock, reward_context):
    job, _, sdk = reward_context
    sdk.fail = True
    assert engine.submit_rewards(job)['state'] == 'ambiguous'
    assert sdk.sends == 1
    clock.now += 3
    restarted = Engine(config, adapter=adapter, clock=clock)
    assert restarted.submit_rewards(job)['state'] == 'ambiguous'
    assert sdk.sends == 1 and sdk.reads == 1
    sdk.row.update(state='submitted_verified', readback_fresh=False)
    clock.now += 5
    assert restarted.submit_rewards(job)['state'] == 'submitted'
    assert sdk.sends == 1
    assert '"readback_fresh":false' in restarted.rewards(job)['submission']['provenance']


def test_returned_uncertain_provider_delay_persists_without_reposting(engine, adapter, config, clock, reward_context):
    job, bridge, sdk = reward_context
    sdk.fail = True
    engine.submit_rewards(job)
    sdk.row.update(failure={'code': 'http_429', 'category': 'rate_limit', 'status': 429, 'retry_after_seconds': 172800.25}, retry_not_before=clock()+172800.25)
    clock.now += 3
    assert engine.submit_rewards(job)['state'] == 'ambiguous'
    restarted = Engine(config, adapter=adapter, clock=clock)
    with restarted.transaction() as db:
        until = db.execute("SELECT until FROM circuits WHERE capability='provider:whop'").fetchone()[0]
    assert until == sdk.row['retry_not_before']
    assert sdk.sends == 1
    assert 'submission_deadline_before_next_retry' in restarted.rewards(job)['error']


def test_known_reserved_recovery_retries_same_uuid_but_not_after_deadline(engine, adapter, clock, reward_context):
    job, _, sdk = reward_context
    def fail_before_confirm(): raise AdapterFailure('transient', 'TEST readiness timeout')
    sdk.before_confirm = fail_before_confirm
    assert engine.submit_rewards(job)['state'] == 'ambiguous'
    request = sdk.row['request_id']
    clock.now += 3
    assert engine.submit_rewards(job)['state'] == 'pending_submission'
    assert sdk.sends == 0 and sdk.row['request_id'] == request
    clock.now += 600
    assert engine.submit_rewards(job)['state'] == 'expired'
    assert sdk.sends == 0


def test_safe_reserved_recovery_retries_same_request_once(engine, clock, reward_context):
    job, _, sdk = reward_context
    sdk.before_confirm = lambda: (_ for _ in ()).throw(AdapterFailure('transient','TEST read interrupted'))
    assert engine.submit_rewards(job)['state'] == 'ambiguous'
    request = sdk.row['request_id']
    clock.now += 3
    assert engine.submit_rewards(job)['state'] == 'pending_submission'
    sdk.before_confirm = None
    assert engine.submit_rewards(job)['state'] == 'submitted'
    assert sdk.sends == 1 and sdk.row['request_id'] == request


def test_recovery_preserves_active_original_reward_lease(engine, clock, reward_context):
    job, _, sdk = reward_context
    with engine.transaction() as db:
        db.execute("UPDATE rewards SET state='submitting',lease_token='original',lease_until=?", (clock()+120,))
    assert engine.submit_rewards(job)['reason'] == 'submission_lease_active'
    assert sdk.sends == 0 and sdk.reads == 0


def test_reconciling_crash_becomes_read_only_recovery_after_original_lease(engine, clock, reward_context):
    job, _, sdk = reward_context
    sdk.fail = True
    engine.submit_rewards(job)
    with engine.transaction() as db:
        db.execute("UPDATE rewards SET state='reconciling',lease_token='original',lease_until=?", (clock()+120,))
    clock.now += 121
    assert engine.submit_rewards(job)['state'] == 'ambiguous'
    assert sdk.sends == 1 and sdk.reads == 1


@pytest.mark.parametrize('field,value', [('request_id','foreign'),('binding',{}),('public_action_dispatched',False),('submission_id','foreign'),('observed_at','2100-01-01T00:00:00+00:00')])
def test_malformed_or_foreign_verification_never_becomes_submission(engine, clock, reward_context, field, value):
    job, _, sdk = reward_context
    sdk.fail=True
    engine.submit_rewards(job)
    sdk.row.update(state='submitted_verified')
    sdk.row[field]=value
    clock.now+=3
    assert engine.submit_rewards(job)['state']=='ambiguous'
    assert sdk.sends==1


def test_provider_rejection_is_persisted_and_does_not_retry(engine, clock, reward_context):
    job, _, sdk = reward_context
    sdk.fail=True
    engine.submit_rewards(job)
    sdk.row.update(state='rejected',failure={'code':'upstream_rejected','category':'upstream','status':200,'retry_after_seconds':None})
    clock.now+=3
    assert engine.submit_rewards(job)['state']=='rejected'
    assert engine.submit_rewards(job)['deduplicated'] is True
    assert sdk.sends==1


@pytest.mark.parametrize('new_state', ['reconciling', 'accepted'])
def test_stale_success_retains_proof_but_never_overwrites_new_owner_or_earnings(engine, adapter, reward_context, new_state):
    job, bridge, sdk = reward_context
    original = adapter.submit_rewards
    def interleave(job_data, ledger):
        result = original(job_data, ledger)
        with engine.transaction() as db:
            db.execute("UPDATE rewards SET state=?,lease_token='new-owner',earnings=? WHERE job_id=?", (new_state, canonical({'amount': 7, 'currency': 'USD'}), job))
        return result
    adapter.submit_rewards = interleave
    result = engine.submit_rewards(job)
    assert result['state'] == new_state and result['reason'] == 'creation_proof_retained_newer_owner'
    with engine.transaction() as db:
        row = db.execute('SELECT * FROM rewards WHERE job_id=?', (job,)).fetchone()
        assert row['lease_token'] == 'new-owner' and row['state'] == new_state
        assert row['earnings'] == canonical({'amount': 7, 'currency': 'USD'})
        assert row['creation_proof'] is not None
    assert sdk.sends == 1


def test_stale_preaction_reconcile_reports_current_persisted_state(engine, adapter, clock, reward_context):
    job, _, sdk = reward_context
    sdk.before_confirm = lambda: (_ for _ in ()).throw(AdapterFailure('transient', 'TEST interrupted'))
    engine.submit_rewards(job)
    clock.now += 3
    original = adapter.reconcile_rewards
    def interleave(job_data, ledger):
        result = original(job_data, ledger)
        with engine.transaction() as db: db.execute("UPDATE rewards SET state='accepted',lease_token='new-owner'")
        return result
    adapter.reconcile_rewards = interleave
    result = engine.submit_rewards(job)
    assert result['state'] == 'accepted' and result['reason'] == 'submission_lease_lost'
    assert sdk.sends == 0


def test_actual_released_whop_sdk_roundtrips_runtime_receipt_binding_and_callback(engine, adapter, config, clock, reward_context, tmp_path):
    """Only provider I/O is mocked; real SDK journal, create and reconcile run."""
    import time
    from types import SimpleNamespace
    from unittest.mock import Mock
    from whop_cli.client import WhopClient
    from whop_cli import submission_operations as op
    job_id, bridge, _ = reward_context
    clock.now = time.time()
    bridge.clock = time.time
    publication = {'publication_id': '1234567890123456789', 'publication_url': 'https://www.tiktok.com/@ata_clipper/video/1234567890123456789',
        'account_id': config['account']['account_id'], 'handle': 'ata_clipper', 'published_at': iso(int(clock()) - 60),
        'provenance': canonical({'kind': 'studio_verified', 'request_id': '9b3f4dc5-1072-4d2a-9738-3a1a6a275dce',
            'post_project_id': '123', 'asset_sha256': 'a'*64, 'policy_digest': 'b'*64, 'readback': op.STUDIO_READBACK})}
    sdk_config = SimpleNamespace(rewards_url='https://example.apps.whop.com/c/exp_TEST', get_browser=lambda: Mock(),
        get_active_profile_name=lambda: 'rewards', get_profile_data_dir=lambda: tmp_path/'owned-sdk-profile')
    (tmp_path/'owned-sdk-profile').mkdir(mode=0o700)
    client = WhopClient(sdk_config)
    client.account = Mock(return_value={'id': 'user_fixture', 'username': 'fixture', 'profile': 'rewards'})
    client.linked_accounts = Mock(return_value=[{'accountId': publication['account_id'], 'platform': 'tiktok', 'status': 'active', 'username': 'ata_clipper', 'id': 'linked', 'userId': 'creator_fixture'}])
    client.campaign = Mock(return_value={'id': 'campaign-1', 'name': 'TEST', 'description': 'Actual fixture brief', 'referenceMaterials': [], 'platforms': ['tiktok'],
        'budgetCents': 100000, 'metrics': {'budgetSpentCents': 1000},
        'status': 'active', 'private': False, 'requiresApplication': False,
        'payouts': [{'platform': 'tiktok', 'payoutType': 'cpm', 'rateCents': 100, 'minPayoutCents': 100, 'maxPayoutCents': 35000, 'budgetCents': 15000, 'spentCents': 0}]})
    client._rest = Mock(return_value={'data': [{'campaignId': 'campaign-1', 'creatorMaxReached': False, 'intake': 'open', 'platformIntake': {'tiktok': 'open'}}]})
    document = Mock()
    client._action_document = Mock(return_value=document)
    client._discover_action = Mock(return_value='a'*40)
    client._action = Mock(return_value={'success': True, 'data': [], 'nextCursor': None})
    ready = client.submission_readiness('campaign-1', expected_account_id='user_fixture', expected_tiktok_account_id=publication['account_id'])
    def transport(*args, **kwargs):
        with engine.transaction() as db: assert db.execute('SELECT state FROM rewards').fetchone()[0] == 'dispatch_pending'
        client._action.return_value = {'success': True, 'data': [{'id': 'native-provider', 'campaignId': 'campaign-1', 'status': 'pending',
            'socialMediaPost': {'platform': 'tiktok', 'postId': publication['publication_id']}}], 'nextCursor': None}
        return {'status': 200, 'text': '0:{"a":"$@1"}\n1:{"success":true,"data":{"id":"native-provider"}}\n'}
    document.evaluate.side_effect = transport
    snapshot = {'actor': ready['actor'], 'campaign_id': 'campaign-1', 'requirements_digest': ready['requirements_digest'], 'readiness': ready}
    with engine.transaction() as db:
        db.execute('UPDATE jobs SET result=?,readiness=? WHERE id=?', (canonical(publication), canonical({'provenance': canonical(snapshot)}), job_id))
        db.execute('UPDATE publications SET id=?,data=? WHERE job_id=?', (publication['publication_id'], canonical(publication), job_id))
        db.execute('UPDATE rewards SET publication_id=?,deadline=? WHERE job_id=?', (publication['publication_id'], clock()+600, job_id))
    adapter.submit_rewards = lambda job, ledger: bridge.submit(client, job, ledger)
    adapter.reconcile_rewards = lambda job, ledger: bridge.reconcile(client, job, ledger)
    result = engine.submit_rewards(job_id)
    assert result['state'] == 'submitted', result
    assert document.evaluate.call_count == 1
    assert engine.rewards(job_id)['submission']['submission_id'] == 'native-provider'
    request = submission_request_id('campaign-1', publication['publication_id'])
    sdk_row = client.reconcile_submission(request)
    assert sdk_row['state'] == 'submitted_verified' and sdk_row['binding']['publication'] == publication
    assert document.evaluate.call_count == 1

    # Actual released SDK shared scan and individual net derivation, with only
    # provider reads mocked. A gross-only pending row must not erase known net.
    from tiktok_clipping_cli.revenue import normalize_revenue
    client._rest.return_value = {'data': [
        {'id': 'net_FIXTURE', 'submissionId': 'native-provider', 'campaignId': 'campaign-1',
         'status': 'completed', 'currency': 'USD', 'netAmount': '900719925474099312345'},
        {'id': 'pending_FIXTURE', 'submissionId': 'native-provider', 'campaignId': 'campaign-1',
         'status': 'pending', 'currency': 'USD', 'amount': '40'}], 'pagination': {'nextCursor': None}}
    scan = client.sync_submission_revenue()
    assert scan['complete'] is True
    raw = client.submission_revenue('native-provider', 'campaign-1', refresh_payouts=False)
    assert raw['received_cents'] == '900719925474099312345'
    assert raw['pending_cents'] is None and raw['amounts_verified'] is False
    normalized = normalize_revenue(raw, engine.rewards(job_id), config['rewards_account'],
        sdk_row['binding']['experience'], config['limits']['max_payload_bytes'])
    assert normalized['revenue']['received_cents'] == raw['received_cents']
    assert normalized['earnings'] is None and document.evaluate.call_count == 1
