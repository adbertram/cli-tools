"""Trusted Whop SDK bridge; submission recovery is independent of revenue."""
from pathlib import Path
import secrets
import sqlite3
import time
import uuid

from .engine import AdapterFailure
from .safety import SafetyError, canonical, keys, strict_json, timestamp, number


def submission_request_id(campaign_id, publication_id):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'tiktok-clipping:submission:' + campaign_id + ':' + publication_id))


class WhopSubmissionAdapter:
    def __init__(self, config, *, clock=time.time):
        self.config, self.clock = config, clock

    def _binding(self, job, ledger):
        maximum = self.config['limits']['max_payload_bytes']
        snapshot = strict_json(job['readiness']['provenance'], maximum)
        actor = self.config['rewards_account']
        expected_actor = {k: actor[k] for k in ('account_id', 'username', 'profile')}
        if snapshot['actor'] != expected_actor or snapshot['campaign_id'] != ledger['campaign_id']:
            raise SafetyError('submission_original_readiness_changed')
        receipt = job['result']
        if receipt['publication_id'] != ledger['publication_id'] or receipt['account_id'] != self.config['account']['account_id']:
            raise SafetyError('submission_original_publication_changed')
        return {'profile': actor['profile'], 'experience': snapshot['readiness']['requirements']['experience'],
            'account_id': actor['account_id'], 'tiktok_account_id': receipt['account_id'],
            'campaign_id': ledger['campaign_id'], 'publication': receipt,
            'requirements_digest': snapshot['requirements_digest']}

    def _confirm(self, job, ledger, bound, request_id, snapshot):
        keys(snapshot, {'request_id', 'binding', 'readiness'})
        if snapshot['request_id'] != request_id or snapshot['binding'] != bound:
            raise SafetyError('submission_callback_binding_changed')
        ready = snapshot['readiness']
        actor = self.config['rewards_account']
        if (ready.get('ready') is not True or ready.get('actor') != {k: actor[k] for k in ('account_id', 'username', 'profile')}
                or ready.get('campaign_id') != bound['campaign_id'] or ready.get('requirements_digest') != bound['requirements_digest']
                or ready.get('linked_account', {}).get('account_id') != bound['tiktok_account_id']
                or ready.get('linked_account', {}).get('username') != bound['publication']['handle']):
            raise SafetyError('submission_callback_readiness_changed')
        if not 0 <= self.clock() - timestamp(ready.get('observed_at')) <= self.config['limits']['work_timeout_seconds']:
            raise SafetyError('submission_callback_readiness_stale')
        number(ready.get('funding_remaining_cents'), 1, integer=True)
        maximum = self.config['limits']['max_payload_bytes']
        strict_json(canonical(snapshot), maximum)
        with sqlite3.connect(Path(self.config['database']).as_uri() + '?mode=rw', uri=True, timeout=2) as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            control = db.execute("SELECT value FROM settings WHERE key='control'").fetchone()
            reward = db.execute('SELECT * FROM rewards WHERE job_id=?', (job['id'],)).fetchone()
            post = db.execute('SELECT * FROM publications WHERE job_id=?', (job['id'],)).fetchone()
            if control is None or control[0] != 'running':
                raise SafetyError('submission_callback_control_not_running')
            token = ledger.get('lease_token')
            if (reward is None or reward['state'] != 'submitting' or not isinstance(token, str) or not token
                    or not secrets.compare_digest(reward['lease_token'] or '', token)
                    or reward['lease_until'] <= self.clock() or reward['request_id'] != request_id
                    or reward['campaign_id'] != bound['campaign_id'] or reward['publication_id'] != bound['publication']['publication_id']):
                raise SafetyError('submission_callback_reservation_changed')
            if reward['deadline'] <= self.clock():
                raise SafetyError('submission_callback_deadline_expired')
            if post is None or post['state'] != 'published' or strict_json(post['data'], maximum) != bound['publication']:
                raise SafetyError('submission_callback_publication_changed')
            db.execute("UPDATE rewards SET state='dispatch_pending',dispatch_evidence=? WHERE job_id=?", (canonical(snapshot), job['id']))
        return True

    def _result(self, result, job, ledger, bound, request_id):
        if not isinstance(result, dict) or result.get('request_id') != request_id or result.get('binding') != bound:
            raise SafetyError('submission_sdk_operation_binding_changed')
        failure = result.get('failure') or {}
        cooldown = result.get('retry_not_before')
        if failure.get('category') == 'rate_limit' or failure.get('retry_after_seconds') is not None:
            number(cooldown, 0)
            # SDK owns this absolute deadline. Reusing an old row cannot extend it.
            with sqlite3.connect(Path(self.config['database']).as_uri() + '?mode=rw', uri=True, timeout=2) as db:
                db.execute("INSERT INTO circuits VALUES('provider:whop',1,?) ON CONFLICT(capability) DO UPDATE SET until=max(circuits.until,excluded.until)", (cooldown,))
        state = result.get('state')
        if state == 'submitted_verified':
            if result.get('public_action_dispatched') is not True or not isinstance(result.get('readback_fresh'), bool):
                raise SafetyError('submission_sdk_verified_state_invalid')
            if not timestamp(bound['publication']['published_at']) <= timestamp(result.get('dispatched_at')) <= ledger['deadline']:
                raise SafetyError('submission_sdk_dispatch_timestamp_invalid')
            if timestamp(result.get('observed_at')) > self.clock() + 300:
                raise SafetyError('submission_sdk_future_readback')
            record = result.get('submission')
            if (not isinstance(record, dict) or record.get('id') != result.get('submission_id')
                    or record.get('campaignId') != bound['campaign_id'] or record.get('socialMediaPost') != {'platform': 'tiktok', 'postId': ledger['publication_id']}):
                raise SafetyError('submission_sdk_readback_changed')
            # This is durable creation proof, not a fresh moderation/earnings observation.
            return {'state': 'submitted', 'submission': {'submission_id': record['id'], 'campaign_id': ledger['campaign_id'],
                'publication_id': ledger['publication_id'], 'status': 'pending', 'submitted_at': result['dispatched_at'],
                'provenance': canonical({'kind': 'whop_submission_verified', 'request_id': request_id,
                    'observed_at': result.get('observed_at'), 'readback_fresh': result.get('readback_fresh'),
                    'inspection_observed_at': result.get('inspection_observed_at'), 'record': record})}}
        if state == 'reserved' and result.get('public_action_dispatched') is False:
            return {'state': 'pre_action', 'provenance': canonical({'kind': 'whop_pre_action_journal', 'request_id': request_id, 'binding': bound})}
        if state == 'rejected':
            return {'state': 'rejected', 'provenance': canonical({'kind': 'whop_submission_rejected', 'request_id': request_id, 'failure': failure})}
        remaining = None if cooldown is None or cooldown <= self.clock() else cooldown - self.clock()
        raise AdapterFailure('ambiguous', 'whop_submission_' + str(state), remaining,
            provider='whop', code=failure.get('code'), status=failure.get('status') or None)

    def submit(self, client, job, ledger):
        bound = self._binding(job, ledger)
        request_id = submission_request_id(ledger['campaign_id'], ledger['publication_id'])
        if ledger.get('request_id') != request_id:
            raise SafetyError('submission_request_reservation_changed')
        result = client.create_submission(request_id, bound['campaign_id'], bound['publication'],
            expected_account_id=bound['account_id'], expected_tiktok_account_id=bound['tiktok_account_id'],
            accepted_requirements_digest=bound['requirements_digest'],
            confirm=lambda snapshot: self._confirm(job, ledger, bound, request_id, snapshot))
        verified = self._result(result, job, ledger, bound, request_id)
        if verified['state'] == 'rejected':
            raise AdapterFailure('permanent', 'whop_submission_rejected', provider='whop', code='whop_submission_rejected')
        if verified['state'] != 'submitted':
            raise AdapterFailure('transient', 'whop_submission_not_dispatched', provider='whop')
        return verified['submission']

    def reconcile(self, client, job, ledger):
        bound = self._binding(job, ledger)
        request_id = submission_request_id(ledger['campaign_id'], ledger['publication_id'])
        if ledger.get('request_id') != request_id:
            return {'state': 'unknown', 'provenance': 'Original submission request unavailable.'}
        result = client.reconcile_submission(request_id)
        return self._result(result, job, ledger, bound, request_id)
