"""Typed renderer rejection and explicit quiescent recovery, without remote calls."""
import os
from copy import deepcopy
from pathlib import Path
import pytest
from conftest import claim, payload, iso
from test_text_attempts import native, issue, receipt
from tiktok_clipping_cli.engine import AdapterFailure
from tiktok_clipping_cli.safety import SafetyError, canonical, strict_json
from tiktok_clipping_cli.asset_retention import render_owner

DIAGNOSTIC={'kind':'refinement_asr_timing','cue_index':0,'crop_duration_seconds':20.0,
    'measured_endpoint_seconds':21.96,'maximum_endpoint_correction_seconds':0.25,
    'cut_index':0,'cut_start_seconds':10,'cut_end_seconds':30}


def ledger(engine,job):
    with engine.transaction() as db:
        current=engine._job(db,job['id'])
        db.execute('INSERT INTO render_temporaries(id,job_id,owner,path,kind,process,created_at,cleaned_at) VALUES(?,?,?,?,?,?,?,?)',
            ('TEST-render-'+job['id']+'-'+str(current['attempts']),job['id'],canonical(render_owner(current)),str(Path(engine.config['workspace'])/('TEST-owned-'+str(current['attempts']))),
             'refinement',canonical({'pid':99999999,'start_identity':'TEST dead worker'}),engine.clock(),engine.clock()))


def reject_adapter(engine,adapter,diagnostics=DIAGNOSTIC,code='refinement_asr_endpoint_out_of_bounds'):
    def render(job,proposal):
        ledger(engine,job)
        raise AdapterFailure('permanent',code,code=code,diagnostics=diagnostics)
    adapter.render=render


def test_real_worker_keeps_measured_cut_diagnostics(config,monkeypatch):
    from tiktok_clipping_cli.adapters import ExternalAdapter
    tests=Path(__file__).parent
    config['adapter_module']='worker_fixture'
    monkeypatch.setenv('PYTHONPATH',str(tests)+os.pathsep+str(tests.parent))
    with pytest.raises(AdapterFailure) as caught:ExternalAdapter(config).call('render',({},{}))
    assert caught.value.code=='refinement_asr_endpoint_out_of_bounds'
    assert caught.value.diagnostics=={**DIAGNOSTIC,'crop_duration_seconds':13.36,'measured_endpoint_seconds':15.32,
        'cut_start_seconds':583.04,'cut_end_seconds':596.4}


def test_automatic_revision_binds_cut_and_actual_next_prompt(engine,adapter,clock):
    env=claim(engine,clock); engine.apply(payload(env),execute=False)
    reject_adapter(engine,adapter)
    assert engine.run(env['job_id'])['state']=='queued'
    job=engine.get(env['job_id']);assert job['proposal'] is None and job['revisions']==1
    next_env=engine.prepare('clip')
    assert next_env['job_id']==env['job_id']
    feedback=next_env['input']['render_feedback']
    assert feedback['diagnostics']==DIAGNOSTIC
    assert feedback['rejected_proposal']['start_seconds']==10
    assert feedback['rejected_proposal']['end_seconds']==30
    assert canonical(feedback) in next_env['prompt']
    assert engine.apply(payload(next_env),execute=False)['state']=='ready'
    assert not adapter.uploads


@pytest.mark.parametrize('change',[lambda d:d.update(cue_index=True),lambda d:d.update(measured_endpoint_seconds=float('nan')),
    lambda d:d.update(crop_duration_seconds=-1),lambda d:d.update(text='secret'),lambda d:d.update(maximum_endpoint_correction_seconds=2),
    lambda d:d.pop('cut_index'),lambda d:d.update(cut_end_seconds=31),lambda d:d.update(measured_endpoint_seconds=20.1)])
def test_malformed_diagnostics_never_cross_worker_boundary(change):
    data=deepcopy(DIAGNOSTIC);change(data)
    with pytest.raises(SafetyError):AdapterFailure('permanent','bad',code='refinement_asr_endpoint_out_of_bounds',diagnostics=data)


@pytest.mark.parametrize('change',['unbound','unknown','missing'])
def test_unbound_or_unknown_render_error_stays_failed(engine,adapter,clock,change):
    env=claim(engine,clock);engine.apply(payload(env),execute=False)
    diagnostic=deepcopy(DIAGNOSTIC)
    if change=='unbound':diagnostic.update(cut_start_seconds=40,cut_end_seconds=60)
    reject_adapter(engine,adapter,None if change=='missing' else diagnostic,
        'unknown_render_error' if change=='unknown' else 'refinement_asr_endpoint_out_of_bounds')
    assert engine.run(env['job_id'])['state']=='failed'
    assert engine.get(env['job_id'])['revisions']==0 and not adapter.uploads


def test_revision_cap_prevents_third_proposal(engine,adapter,clock):
    env=claim(engine,clock)
    for revision in range(3):
        engine.apply(payload(env),execute=False)
        reject_adapter(engine,adapter)
        result=engine.run(env['job_id'])
        if revision<2:
            assert result['state']=='queued';env=engine.prepare('clip')
        else:assert result['state']=='failed'
    with engine.transaction() as db:
        assert db.execute('SELECT count(*) FROM render_temporaries').fetchone()[0]==3
        assert db.execute("SELECT failures FROM circuits WHERE capability='render'").fetchone()[0]==0
    assert engine.prepare('clip')['ready'] is False and not adapter.uploads


def historical(native,adapter,clock):
    env=issue(native);native.apply_text(receipt(native,env),execute=False)
    def failed(job,proposal):
        ledger(native,job)
        raise SafetyError('number_out_of_bounds')
    adapter.render=failed
    assert native.run(env['job_id'])['state']=='failed'
    adapter.visual_execution_state=lambda e:{**e['native_execution'],'terminal':True,'process_absent':True,
        'stopped_at':iso(clock()),'provenance':'TEST exact terminal workflow and absent process'}
    return env


def test_operator_revision_preserves_budget_history_and_prompts_new_cut(native,adapter,clock):
    env=historical(native,adapter,clock);before=native.get(env['job_id']);budgets=native.status()['budgets']
    with pytest.raises(SafetyError):native.retry(env['job_id'],revise_render=True,reason='Cut 10-30: measured endpoint21.96 > crop20 + tolerance0.25')
    clock.now+=native.config['limits']['lease_seconds']+1
    result=native.retry(env['job_id'],revise_render=True,reason='Cut 10-30: measured endpoint21.96 > crop20 + tolerance0.25')
    assert result['state']=='queued'
    after=native.get(env['job_id'])
    assert after['attempts']==before['attempts'] and after['revisions']==1 and after['proposal'] is None
    assert after['input']==before['input'] and after['policy_digest']==before['policy_digest']
    assert native.status()['budgets'][0]['model_calls']==budgets[0]['model_calls'] and native.status()['budgets'][0]['posts']==budgets[0]['posts']
    assert native.status()['budgets'][0]['runtime_seconds']==budgets[0]['runtime_seconds']+1 and not adapter.uploads
    next_env=native.prepare('clip')['text']
    assert 'Cut 10-30: measured endpoint21.96 > crop20 + tolerance0.25' in Path(next_env['manifest_path']).read_text()
    with native.transaction() as db:
        assert db.execute("SELECT count(*) FROM events WHERE event='operator_requested_render_revision'").fetchone()[0]==1
        assert db.execute('SELECT count(*) FROM text_attempts').fetchone()[0]==2


@pytest.mark.parametrize('boundary',['worker','group','unknown_children','missing_ledger','changed_owner','policy','expiry','publication','visual','dispatch','cap','native','race'])
def test_operator_revision_requires_original_authority_and_complete_quiescence(native,adapter,clock,monkeypatch,boundary):
    from tiktok_clipping_cli import asset_retention
    env=historical(native,adapter,clock);clock.now+=native.config['limits']['lease_seconds']+1
    if boundary=='worker':monkeypatch.setattr(asset_retention,'process_absent',lambda _:False)
    elif boundary=='group':monkeypatch.setattr(asset_retention,'child_groups_absent',lambda _:False)
    elif boundary=='policy':native.policy_digest='f'*64
    elif boundary=='expiry':clock.now+=86400*31
    elif boundary in {'native','race'}:
        original=adapter.visual_execution_state
        def observe(e):
            result=original(e)
            if boundary=='native':result['process_absent']=False
            else:
                with native.transaction() as db:db.execute("UPDATE jobs SET error='concurrent change' WHERE id=?",(env['job_id'],))
            return result
        adapter.visual_execution_state=observe
    else:
        with native.transaction() as db:
            if boundary=='unknown_children':db.execute('UPDATE render_temporaries SET descendants_unproven=1')
            elif boundary=='missing_ledger':db.execute('DELETE FROM render_temporaries')
            elif boundary=='changed_owner':db.execute("UPDATE render_temporaries SET owner='{}'")
            elif boundary=='cap':db.execute('UPDATE jobs SET revisions=?',(native.config['limits']['max_revisions'],))
            elif boundary=='publication':db.execute("INSERT INTO publications(job_id,idempotency_key,account_id,asset_digest,state,version) VALUES(?,?,?,?,'uploading',1)",(env['job_id'],'TEST',native.config['account']['account_id'],'a'*64))
            elif boundary=='visual':db.execute("INSERT INTO visual_attempts(id,job_id,state,envelope,created_at,expires_at) VALUES(?,?,'pending','{}',?,?)",('TESTvisual',env['job_id'],clock(),clock()+10))
            elif boundary=='dispatch':native.event(db,env['job_id'],'upload_started',{})
    before=native.get(env['job_id']);budget=native.status()['budgets']
    with pytest.raises(SafetyError):native.retry(env['job_id'],revise_render=True,reason='Measured cut timing rejection')
    after=native.get(env['job_id'])
    assert after['proposal']==before['proposal'] and after['revisions']==before['revisions'] and native.status()['budgets'][0]['model_calls']==budget[0]['model_calls'] and native.status()['budgets'][0]['posts']==budget[0]['posts']
    assert native.status()['budgets'][0]['runtime_seconds']>=budget[0]['runtime_seconds']
    if boundary=='race':assert after['error']=='concurrent change'
    assert not adapter.uploads


def test_actual_reaped_worker_revises_with_owned_ledger(engine,adapter,clock,config,monkeypatch):
    from tiktok_clipping_cli import adapters
    tests=Path(__file__).parent
    config['adapter_module']='worker_fixture'
    monkeypatch.setenv('PYTHONPATH',str(tests)+os.pathsep+str(tests.parent))
    processes=[];original=adapters.subprocess.Popen
    def spawn(*args,**kwargs):
        process=original(*args,**kwargs);processes.append(process);return process
    monkeypatch.setattr(adapters.subprocess,'Popen',spawn)
    external=adapters.ExternalAdapter(config)
    adapter.render=lambda job,proposal:external.call('render',(job,proposal))
    env=claim(engine,clock);engine.apply(payload(env),execute=False)
    assert engine.run(env['job_id'])['state']=='queued'
    assert all(process.poll() is not None for process in processes)
    with engine.transaction() as db:
        row=db.execute('SELECT * FROM render_temporaries').fetchone()
        assert row['cleaned_at'] is not None and row['cleanup_issue'] is None
        from tiktok_clipping_cli.asset_retention import process_absent
        assert process_absent(strict_json(row['process']))
    next_env=engine.prepare('clip')
    assert engine.apply(payload(next_env),execute=False)['state']=='ready'
    assert not adapter.uploads


def test_source_ingest_cannot_inject_render_feedback(engine,clock):
    from conftest import source
    data=source(clock)
    data['render_feedback']={'origin':'operator_requested_render_revision','reason':'TEST feedback',
        'rejected_proposal':{'start_seconds':10,'end_seconds':30,'caption':'TEST','style':'plain'}}
    with pytest.raises(SafetyError,match='source_cannot_assign_strategy'):engine.ingest(data)
