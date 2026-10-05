"""Offline ledger/action regressions. No provider or remote publication calls."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import sys

import pytest

from conftest import iso, source
from tiktok_clipping_cli.engine import Engine
from tiktok_clipping_cli.safety import SafetyError, canonical, strict_json
from tiktok_clipping_cli.text_attempts import TextAttempts

NATIVE = {'execution_id': '123', 'workflow_id': 'clip-native'}

@pytest.fixture
def native(config, adapter, clock):
    config['native_text'] = {'workflow_ids': {'clip': 'clip-native', 'learn': 'learn-native'}, 'model': {'provider': 'deepseek-official', 'model': 'deepseek-flash'}, 'max_output_tokens': 2048,
        'max_result_bytes': 16384, 'timeout_seconds': 30, 'continuation_seconds': 5, 'retention_seconds': 60,
        'sdk_package': '/test/installed-sdk', 'python_executable': sys.executable}
    engine = Engine(config, adapter=adapter, clock=clock, native_execution=NATIVE, native_completion=True)
    engine.control('running')
    engine.ingest(source(clock))
    return engine


def issue(native):
    return native.prepare('clip', require_native_text=True)['text']


def receipt(native, envelope, *, failure=None, usage=True):
    data = native.get(envelope['job_id'])['input']
    proposal = {'start_seconds': 10, 'end_seconds': 30, 'caption': 'TEST caption', 'style': data['assigned_style']}
    return {'envelope': deepcopy(envelope), 'outcome': 'failed' if failure else 'completed', 'raw_result': None if failure else canonical(proposal),
        'usage_observed': usage, 'usage': {'uncachedInputTokens': 11, 'outputTokens': 22, 'cacheReadTokens': 33, 'cacheWriteTokens': 44} if usage else None,
        'usage_provenance': {'session_id': 'session-test', 'as_of_seq': 8} if usage else {'session_id': None, 'as_of_seq': None},
        'model': native.config['native_text']['model'], 'observed_at': iso(native.clock()), 'failure': failure}


def attempt(native, envelope):
    with native.transaction() as db:
        return dict(db.execute('SELECT * FROM text_attempts WHERE id=?', (envelope['attempt_id'],)).fetchone())


def test_issue_reserves_one_original_day_and_artifacts(native):
    env = issue(native)
    row = attempt(native, env)
    assert row['state'] == 'pending'
    assert strict_json(row['reservation'])['day'] == '2026-10-03'
    assert TextAttempts(native).verify_artifacts(row).is_dir()
    overlay = Path(env['overlay_path']).read_text()
    assert "- id: llm-deepseek\n  config:\n    thinking: disabled\n    reasoningEffort: 'off'\n    maxTokens: 2048\n" in overlay
    assert native.status()['budgets'][0]['model_calls'] == 1
    assert native.status()['budgets'][0]['runtime_seconds'] == 30


def test_receipt_usage_once_and_proposal_once(native):
    env = issue(native); data = receipt(native, env)
    assert native.apply_text(data, execute=False)['state'] == 'ready'
    assert native.apply_text(data, execute=False)['deduplicated']
    with native.transaction() as db:
        assert db.execute("SELECT count(*) FROM events WHERE event='text_usage_observed'").fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM clips').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM runtime_reservations').fetchone()[0] == 1
    assert not native.adapter.uploads


def test_concurrent_receipts_do_not_repeat_proposal(native):
    env = issue(native); data = receipt(native, env)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: native.apply_text(data, execute=False), range(2)))
    assert all(item['accounted'] for item in results)
    with native.transaction() as db:
        assert db.execute('SELECT count(*) FROM clips').fetchone()[0] == 1
    assert attempt(native, env)['state'] == 'applied'


def test_pause_records_usage_no_action(native):
    env = issue(native); data = receipt(native, env)
    native.control('paused')
    assert native.apply_text(data, execute=False)['state'] == 'paused'
    assert attempt(native, env)['result']
    assert native.get(env['job_id'])['proposal'] is None
    native.control('running')
    assert native.apply_text(data, execute=False)['state'] == 'ready'


def test_expired_receipt_accounts_usage_without_action(native, clock):
    env = issue(native); data = receipt(native, env)
    clock.now = env['expires_at'] + 1
    result = native.apply_text(data, execute=False)
    assert result['reason'] == 'stale_or_invalid_lease'
    assert attempt(native, env)['result']
    assert native.get(env['job_id'])['proposal'] is None


def test_provider_503_cooldown_over_24h_persists_globally(native, clock):
    env = issue(native)
    failure = {'category': 'provider_unavailable', 'code': 'HTTP_ERROR', 'status': 503, 'retry_after_ms': 172800000}
    result = native.apply_text(receipt(native, env, failure=failure), execute=False)
    assert result['state'] == 'queued'
    assert result['retry_at'] == clock() + 172800
    with native.transaction() as db:
        assert db.execute("SELECT until FROM circuits WHERE capability='model'").fetchone()[0] == clock() + 172800
    clock.now += 100
    restarted = Engine(native.config, adapter=native.adapter, clock=clock, native_execution=NATIVE)
    assert not restarted.prepare('clip')['ready']
    assert restarted.status()['budgets'][0]['model_calls'] == 1


def test_blocked_retry_requires_recovered_prerequisite_and_native_end(native):
    env = issue(native)
    failure = {'category': 'auth', 'code': 'AUTH_FAILED', 'status': 401, 'retry_after_ms': None}
    result = native.apply_text(receipt(native, env, failure=failure, usage=False), execute=False)
    assert result['state'] == 'blocked'
    assert native.retry_text(env['job_id'])['state'] == 'queued'
    assert native.status()['budgets'][0]['model_calls'] == 1


def test_retry_text_refuses_proposal_and_publication_history(native):
    env = issue(native)
    native.apply_text(receipt(native, env), execute=False)
    with native.transaction() as db:
        db.execute("UPDATE jobs SET status='blocked',error='text:AUTH_FAILED' WHERE id=?", (env['job_id'],))
    with pytest.raises(SafetyError, match='only_blocked_preproposal'):
        native.retry_text(env['job_id'])


@pytest.mark.parametrize('field,value', [('usage', {'uncachedInputTokens': -1}), ('model', {'provider': 'other','model': 'deepseek-flash'}), ('outcome','ready'), ('raw_result', 'x'*16385)])
def test_untrusted_receipt_rejected_before_accounting(native, field, value):
    env = issue(native); data = receipt(native, env); data[field] = value
    with pytest.raises(SafetyError): native.apply_text(data, execute=False)
    assert attempt(native, env)['result'] is None


def test_receipt_original_identity_immutable(native):
    env = issue(native); data = receipt(native, env)
    data['envelope']['native_execution']['execution_id'] = '456'
    with pytest.raises(SafetyError, match='binding_changed'): native.apply_text(data, execute=False)
    data = receipt(native, env); native.apply_text(data, execute=False)
    data['usage']['outputTokens'] += 1
    with pytest.raises(SafetyError, match='duplicate_result_changed'): native.apply_text(data, execute=False)


def test_paused_maintenance_ingests_receipt_before_process_proof(native, clock):
    env = issue(native); data = receipt(native, env)
    native.native_completion = False
    Path(env['manifest_path']).with_name('result.json').write_text(canonical(data))
    native.control('paused')
    result = native.maintain_text()
    assert result[0]['accounted'] is True
    assert attempt(native, env)['native_completed_at'] is None
    assert native.get(env['job_id'])['proposal'] is None


def test_expired_process_without_proof_stays_blocked_and_charged(native, clock):
    env = issue(native); native.native_completion = False
    clock.now = env['expires_at'] + 1
    result = native.maintain_text()
    assert result[0]['state'] == 'unknown'
    assert native.get(env['job_id'])['status'] == 'blocked'
    assert native.status()['budgets'][0]['runtime_seconds'] == 30


def test_legacy_apply_refused_only_when_native_configured(native, config, adapter, clock):
    with pytest.raises(SafetyError, match='native_text_receipt_required'): native.apply({})
    config = deepcopy(config); config.pop('native_text')
    config['database'] += '.legacy'
    engine = Engine(config, adapter=adapter, clock=clock); engine.control('running')
    assert engine.prepare('clip', require_native_text=True)['reason'] == 'native_text_configuration_required'


def test_learn_identity_does_not_fall_back_to_clip(native):
    with pytest.raises(SafetyError, match='text_native_workflow_identity_changed'): native.prepare('learn')


def test_prune_requires_exact_process_proof_and_retention(native, clock):
    env = issue(native); native.apply_text(receipt(native, env), execute=False)
    attempts = TextAttempts(native); clock.now += 100
    assert not attempts.prune(env['attempt_id'])
    proof = {**NATIVE,'terminal':True,'process_absent':True,'stopped_at':iso(clock()-100),'provenance':'TEST native API exact proof'}
    with native.transaction() as db:
        db.execute('UPDATE text_attempts SET native_termination_proof=? WHERE id=?', (canonical(proof),env['attempt_id']))
    assert attempts.prune(env['attempt_id'])
    assert not Path(env['manifest_path']).parent.exists()
    assert attempt(native, env)['result']


def test_native_transport_failure_unknown_usage_never_zero(native):
    env = issue(native)
    result = native.consume_text({'envelope':env,'receipt_json':None,'native_failure':{'timed_out':True,'exit_code':None}},execute=False)
    assert result['state'] == 'queued'
    observed = strict_json(attempt(native, env)['result'])
    assert observed['outcome'] == 'timeout'
    assert observed['usage'] is None and observed['usage_observed'] is False
    assert native.status()['budgets'][0]['runtime_seconds'] == 30


def test_native_transport_recovers_committed_receipt_without_stdout(native):
    env = issue(native); data = receipt(native, env)
    Path(env['manifest_path']).with_name('result.json').write_text(canonical(data))
    result = native.consume_text({'envelope':env,'receipt_json':None,'native_failure':{'timed_out':False,'exit_code':1}},execute=False)
    assert result['state'] == 'ready'
    assert strict_json(attempt(native, env)['result'])['usage'] == data['usage']


def test_native_bridge_raw_duplicate_key_is_rejected_without_proposal(native):
    env = issue(native); data = receipt(native, env)
    raw = canonical(data).replace('"outcome":"completed"','"outcome":"failed","outcome":"completed"')
    result = native.consume_text({'envelope':env,'receipt_json':raw,'native_failure':None},execute=False)
    assert result['state'] == 'queued'
    assert native.get(env['job_id'])['proposal'] is None
    assert strict_json(attempt(native, env)['result'])['usage'] is None


def test_native_bridge_foreign_receipt_is_never_accounted(native):
    env = issue(native); data = receipt(native, env); data['envelope']['nonce']='other'
    with pytest.raises(SafetyError, match='receipt_owner_changed'):
        native.consume_text({'envelope':env,'receipt_json':canonical(data),'native_failure':None},execute=False)
    assert attempt(native, env)['result'] is None


def test_late_completed_response_records_measured_usage_then_retries(native, clock):
    env = issue(native); clock.now = env['model_deadline'] + 1
    result = native.apply_text(receipt(native, env),execute=False)
    assert result['state']=='queued' and result['reason']=='text_model_deadline_exceeded'
    assert strict_json(attempt(native, env)['result'])['usage']['outputTokens']==22


def test_retry_text_refuses_unknown_worker(native):
    env = issue(native)
    with native.transaction() as db:
        db.execute("UPDATE jobs SET status='blocked',error='text:AUTH_FAILED' WHERE id=?",(env['job_id'],))
    with pytest.raises(SafetyError,match='text_native_termination_unknown'): native.retry_text(env['job_id'])


def test_prerequisite_retry_does_not_bypass_long_provider_delay(native):
    env = issue(native)
    failure={'category':'auth','code':'AUTH_FAILED','status':401,'retry_after_ms':172800000}
    native.apply_text(receipt(native,env,failure=failure),execute=False)
    with pytest.raises(Exception,match='circuit_open: model'): native.retry_text(env['job_id'])


def test_preparation_failure_retains_reservation_and_requires_process_proof(native, monkeypatch):
    def crash(plan):
        raise OSError('TEST preparation crash')
    monkeypatch.setattr(TextAttempts,'finish',lambda self,plan:crash(plan))
    with pytest.raises(OSError): issue(native)
    with native.transaction() as db:
        row=dict(db.execute('SELECT * FROM text_attempts').fetchone())
    assert row['state']=='preparing' and row['artifacts_ready']==0
    assert native.status()['budgets'][0]['model_calls']==1
    assert native.status()['budgets'][0]['runtime_seconds']==30


def test_reservation_refusal_rolls_back_claim_and_artifacts(native):
    native.config['limits']['daily_runtime_seconds']=29
    with pytest.raises(SafetyError,match='budget_exhausted: runtime_seconds'): issue(native)
    with native.transaction() as db:
        assert db.execute('SELECT count(*) FROM text_attempts').fetchone()[0]==0
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='runtime_reservations'").fetchone()[0]==0
        assert db.execute("SELECT count(*) FROM jobs WHERE status='leased'").fetchone()[0]==0
    assert not (native.workspace/'model').exists()


def test_learn_native_mapping_receipt_and_evidence_application(native, clock):
    from test_learning import publish, metric
    legacy_config=deepcopy(native.config); legacy_config.pop('native_text')
    legacy=Engine(legacy_config,adapter=native.adapter,clock=clock)
    pubs=[publish(legacy,clock,'learn-'+str(i)) for i in range(2)]
    clock.now += 3600
    for pub in pubs: legacy.snapshot(metric(clock,pub))
    learner=Engine(native.config,adapter=native.adapter,clock=clock,native_execution={'execution_id':'124','workflow_id':'learn-native'},native_completion=True)
    env=learner.prepare('learn',require_native_text=True)['text']
    data={'envelope':env,'outcome':'completed','raw_result':canonical({'weights':{'plain':0.6,'highlight':0.4},'exploration':0.05}),
        'usage_observed':True,'usage':{'uncachedInputTokens':1,'outputTokens':2,'cacheReadTokens':3,'cacheWriteTokens':4},
        'usage_provenance':{'session_id':'session-learning','as_of_seq':10},'model':learner.config['native_text']['model'],'observed_at':iso(clock()),'failure':None}
    assert learner.apply_text(data)['strategy_version']==2
    assert learner.apply_text(data)['deduplicated']
    assert learner.prepare('learn')['state']=='insufficient_samples'


def test_expired_terminal_process_requeues_without_refunding_unknown_usage(native, clock, monkeypatch):
    env=issue(native); native.native_completion=False; clock.now=env['expires_at']+1
    proof={**NATIVE,'terminal':True,'process_absent':True,'stopped_at':iso(clock()),'provenance':'TEST execution API+PID absence'}
    monkeypatch.setattr(TextAttempts,'native_state',lambda self,row:proof)
    result=native.maintain_text()
    assert result[0]['accounted']
    assert native.get(env['job_id'])['status']=='queued'
    assert strict_json(attempt(native,env)['result'])['usage'] is None
    assert native.status()['budgets'][0]['runtime_seconds']==30
    clock.now+=3
    second=issue(native)
    assert second['attempt_id']!=env['attempt_id'] and second['lease_token']!=env['lease_token']
    assert native.status()['budgets'][0]['model_calls']==2


def test_cleanup_refuses_link_outside_owned_attempt(native, clock):
    env=issue(native); native.apply_text(receipt(native,env),execute=False);clock.now+=100
    proof={**NATIVE,'terminal':True,'process_absent':True,'stopped_at':iso(clock()-100),'provenance':'TEST proof'}
    with native.transaction() as db:
        db.execute('UPDATE text_attempts SET native_termination_proof=? WHERE id=?',(canonical(proof),env['attempt_id']))
    path=Path(env['manifest_path']).parent/'foreign-link';path.symlink_to(native.workspace.parent)
    with pytest.raises(SafetyError,match='text_cleanup_unowned_object'):TextAttempts(native).prune(env['attempt_id'])
    assert Path(env['manifest_path']).exists()


def test_urgent_rewards_precede_text_and_deadline_can_defer_text(native, clock, monkeypatch):
    seen=[]
    with native.transaction() as db:
        # Maintenance ordering only; no external reward/remote publication.
        db.execute("INSERT INTO rewards(job_id,publication_id,campaign_id,state,deadline,updated_at) VALUES('urgent','post-test','campaign-1','pending_submission',?,?)",(clock()+600,clock()))
    def urgent(job_id):
        seen.append('urgent');clock.now+=30;return {'state':'submitted'}
    monkeypatch.setattr(native,'submit_rewards',urgent)
    monkeypatch.setattr(native,'maintain_text',lambda:seen.append('text') or [])
    result=native.maintain()
    assert seen==['urgent'] and result['text_results']==[]


def test_active_maintenance_text_after_urgent_and_before_cleanup(native, clock, monkeypatch):
    seen=[]
    with native.transaction() as db:
        db.execute("INSERT INTO rewards(job_id,publication_id,campaign_id,state,deadline,updated_at) VALUES('urgent','post-test','campaign-1','pending_submission',?,?)",(clock()+600,clock()))
    monkeypatch.setattr(native,'submit_rewards',lambda _:seen.append('urgent') or {'state':'submitted'})
    monkeypatch.setattr(native,'maintain_text',lambda:seen.append('text') or [])
    monkeypatch.setattr(native,'prune_confirmed_assets',lambda:seen.append('cleanup') or 0)
    native.maintain()
    assert seen[:3]==['urgent','text','cleanup']


def test_native_failure_before_process_marker_can_recover_only_with_return_proof(native, clock, monkeypatch):
    env=issue(native);row=attempt(native,env)
    with pytest.raises(SafetyError,match='launch_proof_missing'):TextAttempts(native).native_state(row)
    native.consume_text({'envelope':env,'receipt_json':None,'native_failure':{'timed_out':False,'exit_code':1}},execute=False)
    calls=[]
    def read(method,envelope):
        calls.append(envelope)
        return {**NATIVE,'terminal':True,'process_absent':True,'stopped_at':iso(clock()),'provenance':'TEST exact execution+preparation PID absence'}
    monkeypatch.setattr(native,'_call',read)
    proof=TextAttempts(native).native_state(attempt(native,env))
    assert proof['process_absent']
    assert 'native_node_return_observed_at' in proof['provenance']
    assert calls[0]['preparation_process']==strict_json(row['preparation_process'])


def test_partial_preparation_can_recover_without_runner_marker(native, clock, monkeypatch):
    def crash(self,plan):
        plan['root'].mkdir(parents=True);Path(plan['envelope']['manifest_path']).write_bytes(plan['manifest'])
        raise OSError('TEST interrupted after manifest write')
    monkeypatch.setattr(TextAttempts,'finish',crash)
    with pytest.raises(OSError):issue(native)
    with native.transaction() as db:row=dict(db.execute('SELECT * FROM text_attempts').fetchone())
    proof={**NATIVE,'terminal':True,'process_absent':True,'stopped_at':iso(clock()),'provenance':'TEST exact native+dead prep worker'}
    monkeypatch.setattr(native,'_call',lambda method,env:proof)
    assert TextAttempts(native).native_state(row)['terminal']
    assert row['artifacts_ready']==0 and Path(strict_json(row['envelope'])['manifest_path']).exists()


def test_cleanup_inventory_survives_interruption_and_rejects_changed_file(native, clock, monkeypatch):
    env=issue(native);native.apply_text(receipt(native,env),execute=False);clock.now+=100
    proof={**NATIVE,'terminal':True,'process_absent':True,'stopped_at':iso(clock()-100),'provenance':'TEST native proof'}
    with native.transaction() as db:db.execute('UPDATE text_attempts SET native_termination_proof=? WHERE id=?',(canonical(proof),env['attempt_id']))
    original=Path.unlink
    called=[]
    def interrupted(path,*args,**kwargs):
        if called:raise OSError('TEST interrupted cleanup')
        called.append(str(path));return original(path,*args,**kwargs)
    with monkeypatch.context() as context:
        context.setattr(Path,'unlink',interrupted)
        with pytest.raises(OSError):TextAttempts(native).prune(env['attempt_id'])
    row=attempt(native,env);assert row['cleanup_inventory'] and not row['artifacts_cleaned']
    remaining=next(Path(env['manifest_path']).parent.glob('*.json'))
    before=remaining.read_bytes();remaining.write_bytes(before+b' ')
    with pytest.raises(SafetyError,match='inventory_changed'):TextAttempts(native).prune(env['attempt_id'])
    remaining.write_bytes(before)
    assert TextAttempts(native).prune(env['attempt_id'])
    assert attempt(native,env)['result']


@pytest.mark.parametrize('field,value', [('workflow_ids',{'clip':'same','learn':'same'}),('max_output_tokens',True),('max_result_bytes',-1),('timeout_seconds',120),('sdk_package','relative/path')])
def test_native_config_rejects_invalid_bounds_and_mapping(native, field, value):
    config=deepcopy(native.config);config['native_text'][field]=value
    with pytest.raises(SafetyError):Engine(config,adapter=native.adapter,clock=native.clock,native_execution=NATIVE)


def test_retry_text_refuses_erased_prior_proposal_history(native):
    env=issue(native);native.apply_text(receipt(native,env),execute=False)
    with native.transaction() as db:
        db.execute("UPDATE jobs SET status='blocked',error='text:AUTH_FAILED',proposal=NULL,proposal_digest=NULL WHERE id=?",(env['job_id'],))
    with pytest.raises(SafetyError,match='text_retry_public_action_history'):native.retry_text(env['job_id'])


def test_generic_retry_cannot_bypass_unknown_text_worker(native, clock):
    env=issue(native);native.native_completion=False;clock.now=env['expires_at']+1
    native.maintain_text()
    with pytest.raises(SafetyError,match='preproposal_text_job_requires_retry_text'):native.retry(env['job_id'])
    assert native.get(env['job_id'])['status']=='blocked'


def test_duplicate_native_return_keeps_first_completion_timestamp(native, clock):
    env=issue(native);data=receipt(native,env);native.apply_text(data,execute=False)
    first=attempt(native,env)['native_completed_at'];clock.now+=1
    native.apply_text(data,execute=False)
    assert attempt(native,env)['native_completed_at']==first
