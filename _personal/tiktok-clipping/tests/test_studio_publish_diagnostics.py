"""Optional publish observations never authorize another public action."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from test_studio_adapter import bridge_fixture
from tiktok_clipping_cli.adapters import ExternalAdapter
from tiktok_clipping_cli.engine import AdapterFailure
from tiktok_clipping_cli.safety import SafetyError, adapter_diagnostics, canonical

STAGES = ('native_observation_refresh','native_post_action','post_receipt_read')


def exception():
    exc = TimeoutError('SECRET raw exception body and session token')
    exc.retry_after = 172800.25
    exc.provider, exc.code, exc.status = 'tiktok', 'publication_transport_failed', 503
    return exc


@pytest.mark.parametrize('stage', STAGES)
@pytest.mark.parametrize('state,dispatched,category', [('prepared',False,'transient'),('outcome_unknown',True,'ambiguous')])
def test_exact_journal_adds_only_closed_observation_without_changing_authority(engine, config, adapter, clock, stage, state, dispatched, category):
    bridge,sdk,job,asset,key,policy = bridge_fixture(engine,config,adapter,clock)
    binding = bridge._binding(asset,key,policy)
    sdk.operation.update(state=state,public_action_dispatched=dispatched,
                         post_failure={'stage':stage,'error_type':'FileNotFoundError'},
                         untrusted_envelope='SECRET browser payload')
    before = deepcopy(sdk.operation)
    failure = bridge._failure(sdk,binding,policy,exception())
    assert (failure.category,failure.provider,failure.code,failure.status,failure.retry_after) == (category,'tiktok','publication_transport_failed',503,172800.25)
    assert failure.diagnostics == {'kind':'studio_publish_failure','stage':stage,'error_type':'FileNotFoundError'}
    assert str(failure) == 'studio_publish: TimeoutError'
    assert sdk.operation == before and sdk.calls == ['status']
    assert 'SECRET' not in canonical(failure.diagnostics)+str(failure)


@pytest.mark.parametrize('field', ['request_id','asset_sha256','policy_digest','actor','policy','binding'])
def test_mismatched_journal_cannot_supply_diagnostics_or_pre_action_proof(engine, config, adapter, clock, field):
    bridge,sdk,_,asset,key,policy = bridge_fixture(engine,config,adapter,clock)
    binding = bridge._binding(asset,key,policy)
    sdk.operation.update(post_failure={'stage':STAGES[0],'error_type':'FileNotFoundError'})
    sdk.operation[field] = 'SECRET foreign operation'
    failure = bridge._failure(sdk,binding,policy,exception())
    assert failure.category == 'ambiguous' and failure.diagnostics is None
    assert 'SECRET' not in str(failure)


@pytest.mark.parametrize('raw', [None,[],{}, {'stage':'other','error_type':'FileNotFoundError'},
    {'stage':[],'error_type':'FileNotFoundError'}, {'stage':STAGES[0],'error_type':None},
    {'stage':STAGES[0],'error_type':False}, {'stage':STAGES[0],'error_type':'a'*129},
    {'stage':STAGES[0],'error_type':'Some.Module.Error'}, {'stage':STAGES[0],'error_type':'for'},
    {'stage':STAGES[0],'error_type':'SECRET session message'},
    {'stage':STAGES[0],'error_type':'FileNotFoundError','message':'SECRET'},
    {'stage':STAGES[0],'error_type':'FileNotFoundError','request_id':'SECRET'}])
@pytest.mark.parametrize('state,dispatched,category', [('prepared',False,'transient'),('outcome_unknown',True,'ambiguous')])
def test_malformed_optional_observation_cannot_change_original_failure(engine, config, adapter, clock, raw, state, dispatched, category):
    bridge,sdk,_,asset,key,policy = bridge_fixture(engine,config,adapter,clock)
    binding = bridge._binding(asset,key,policy)
    sdk.operation.update(state=state,public_action_dispatched=dispatched,post_failure=raw)
    failure = bridge._failure(sdk,binding,policy,exception())
    assert (failure.category,failure.provider,failure.status,failure.retry_after) == (category,'tiktok',503,172800.25)
    assert failure.diagnostics is None and 'SECRET' not in str(failure)


@pytest.mark.parametrize('raw', [
    {'kind':'studio_publish_failure','stage':'cleanup','error_type':'TimeoutError'},
    {'kind':'studio_publish_failure','stage':STAGES[0],'error_type':'Bad exception text'},
    {'kind':'studio_publish_failure','stage':STAGES[0],'error_type':'None'},
    {'kind':'studio_publish_failure','stage':STAGES[0],'error_type':'TimeoutError','raw':'SECRET'},
])
def test_transport_validator_rejects_open_or_malformed_dto(raw):
    with pytest.raises(SafetyError):adapter_diagnostics(raw)


def test_matched_ambiguous_failure_remains_ambiguous_in_durable_event_and_counters(engine, config, adapter, clock):
    bridge,sdk,job,asset,key,policy = bridge_fixture(engine,config,adapter,clock)
    with engine.transaction() as db:
        budgets = [dict(r) for r in db.execute('SELECT * FROM budgets')]
        attempts = db.execute('SELECT attempts FROM jobs WHERE id=?',(job['id'],)).fetchone()[0]
    sdk.operation.update(state='outcome_unknown',public_action_dispatched=True,
                         post_failure={'stage':'post_receipt_read','error_type':'FileNotFoundError'})
    failure = bridge._failure(sdk,bridge._binding(asset,key,policy),policy,exception())
    result = engine._fail(job['id'],'publish',failure,job['lease_token'])
    assert result['state'] == 'ambiguous' and result['diagnostics'] == failure.diagnostics
    with engine.transaction() as db:
        assert [dict(r) for r in db.execute('SELECT * FROM budgets')] == budgets
        assert db.execute('SELECT attempts FROM jobs WHERE id=?',(job['id'],)).fetchone()[0] == attempts
        assert db.execute('SELECT state FROM publications WHERE job_id=?',(job['id'],)).fetchone()[0] == 'ambiguous'
    saved = engine.get(job['id'])['last_failure']
    assert saved['category'] == 'ambiguous' and saved['diagnostics'] == failure.diagnostics
    assert 'SECRET' not in canonical(saved) and 'native-send' not in sdk.calls


@pytest.mark.parametrize('stage', STAGES)
def test_actual_external_worker_preserves_studio_failure_metadata(config, monkeypatch, stage):
    scratch = Path(__file__).parent
    config['adapter_module'] = 'worker_fixture'
    monkeypatch.setenv('PYTHONPATH',str(scratch)+os.pathsep+str(scratch.parent))
    policy = {'schema_version':1,'profile':'clipper','account_id':config['account']['account_id'],
              'username':'ata_clipper','caption':'TEST #ad','audience':'Everyone','timing':'now',
              'disclosure':'branded_content','music_rights_confirmed':True}
    with pytest.raises(AdapterFailure) as caught:
        ExternalAdapter(config).call('publish',({'post_failure':{'stage':stage,'error_type':'FileNotFoundError'}},
                                              {'sha256':'a'*64},'b'*64,policy))
    failure = caught.value
    assert (failure.category,failure.provider,failure.code,failure.status,failure.retry_after) == ('ambiguous','tiktok','publication_transport_failed',503,172800.25)
    assert failure.diagnostics == {'kind':'studio_publish_failure','stage':stage,'error_type':'FileNotFoundError'}
    assert 'SECRET' not in str(failure)+canonical(failure.diagnostics)
