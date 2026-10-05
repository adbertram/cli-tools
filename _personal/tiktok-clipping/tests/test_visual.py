import hashlib
import json
from pathlib import Path

import pytest

from conftest import claim, iso, payload
from tiktok_clipping_cli.engine import Engine
from tiktok_clipping_cli.safety import SafetyError, canonical
from tiktok_clipping_cli.visual import CHECKS, VisualArtifacts, caption_samples, owned_bytes, validate_receipt


@pytest.fixture
def visual_engine(config,adapter,clock,monkeypatch):
    config['visual']={'frame_count':3,'max_frame_bytes':1048576,'timeout_seconds':30,'continuation_seconds':5,'retention_seconds':60,'workflow_id':'workflow-test'}
    config['limits']['max_disk_bytes']=10*1048576
    def render_frame(media,command,deadline,**kwargs):
        assert '-frames:v' in command and '-fs' in command
        Path(command[-1]).write_bytes(b'\xff\xd8\xffTEST frame\xff\xd9')
    from tiktok_clipping_cli.media import MediaRenderer
    monkeypatch.setattr(MediaRenderer,'_run',render_frame)
    def render_receipt(media, job, proposal, asset):
        data={'asset':asset,'proposal':proposal,'captions':[{'start':0,'end':proposal['end_seconds']-proposal['start_seconds'],'text':'TEST speech'}]}
        Path(asset['path']).with_suffix('.json').write_text(canonical(data))
        return data
    monkeypatch.setattr(MediaRenderer,'render_receipt',render_receipt)
    engine=Engine(config,adapter=adapter,clock=clock,native_execution={'execution_id':'123','workflow_id':'workflow-test'},native_completion=True)
    adapter.visual_execution_state=lambda envelope:{**envelope['native_execution'],'terminal':True,'process_absent':True,'stopped_at':iso(envelope['model_deadline']),'provenance':'TEST exact execution terminal/process absence'}
    engine.control('running')
    return engine


def issue(engine,clock):
    envelope=claim(engine,clock)
    result=engine.apply(payload(envelope))
    assert result['state']=='visual_pending'
    return result['visual']


def receipt(envelope,clock,**changes):
    return {'envelope':envelope,'outcome':'completed','decision':{'passed':True,'checks':dict.fromkeys(CHECKS,True),'reason':'TEST sampled frames pass'},
        'usage_observed':True,'usage':{'uncachedInputTokens':156,'outputTokens':1351,'cacheReadTokens':1920,'cacheWriteTokens':0},
        'model':{'provider':'deepseek-official','model':'deepseek-flash'},'observed_at':iso(clock()),**changes}


def test_actual_hash_bound_manifest_and_visual_receipt_publish_once(visual_engine,adapter,clock):
    envelope=issue(visual_engine,clock)
    overlay = Path(envelope['overlay_path']).read_text()
    assert "- id: llm-deepseek\n  config:\n    thinking: disabled\n    reasoningEffort: 'off'\n    maxTokens: 2500\n" in overlay
    assert adapter.uploads==[]
    result=visual_engine.apply_visual(receipt(envelope,clock))
    assert result['state']=='published' and len(adapter.uploads)==1
    assert visual_engine.apply_visual(receipt(envelope,clock))['deduplicated']
    assert len(adapter.uploads)==1
    with visual_engine.transaction() as db:
        attempt=db.execute('SELECT * FROM visual_attempts').fetchone()
        assert attempt['state']=='approved' and '1351' in attempt['result']
        assert db.execute('SELECT model_calls FROM budgets').fetchone()[0]==2


def test_caption_gap_preserves_composition_sample_and_samples_speech_midpoint():
    captions=[{'start':0,'end':2.9,'text':'One card.'},{'start':2.9,'end':3.74,'text':'Oh fun!'},{'start':6.24,'end':7,'text':'Whoa.'}]
    cues,samples=caption_samples(7,captions,3)
    assert cues==[{'start':cue['start'],'end':cue['end']} for cue in captions]
    assert samples==[{'seconds':1.45,'caption_expected':True},{'seconds':3.5,'caption_expected':True},{'seconds':7*2.5/3,'caption_expected':False}]
    # Even sparse speech missed by every uniform frame gets typography coverage.
    _,sparse=caption_samples(7,[{'start':0,'end':0.1,'text':'Hi.'}],3)
    assert sparse[0]=={'seconds':0.05,'caption_expected':True}
    assert len(sparse)==3 and sparse[-1]['caption_expected'] is False
    with pytest.raises(SafetyError,match='timed_transcript_required'):caption_samples(7,[],3)


def test_new_manifest_expectations_bind_actual_receipt_and_missing_speech_still_fails(visual_engine,adapter,clock):
    envelope=issue(visual_engine,clock)
    manifest=json.loads(Path(envelope['manifest_path']).read_text())
    assert manifest['schema_version']==3 and any(frame['caption_expected'] for frame in manifest['frames'])
    assert 'missing captions there fails' in manifest['prompt']
    assert 'cue gaps do not prove audio silence' in manifest['prompt'].lower()
    rejected=receipt(envelope,clock)
    rejected['decision']={'passed':False,'checks':{**dict.fromkeys(CHECKS,True),'captions_readable':False},'reason':'Expected burned speech is missing.'}
    assert visual_engine.apply_visual(rejected)['state']=='queued'
    assert adapter.uploads==[]


@pytest.mark.parametrize('change',['receipt','expectation','cue','timestamp'])
def test_caption_sampling_tampering_refuses(visual_engine,clock,change):
    envelope=issue(visual_engine,clock)
    asset=visual_engine.get(envelope['job_id'])['asset']
    manifest_path=Path(envelope['manifest_path']);manifest=json.loads(manifest_path.read_text())
    if change=='receipt':Path(asset['path']).with_suffix('.json').write_text('{}')
    else:
        if change=='expectation':manifest['frames'][0]['caption_expected']=False
        elif change=='cue':manifest['caption_cues'][0]['end']-=1
        else:manifest['frames'][0]['seconds']+=0.1
        raw=canonical(manifest).encode();manifest_path.write_bytes(raw);envelope['manifest_sha256']=hashlib.sha256(raw).hexdigest()
    with pytest.raises(SafetyError):VisualArtifacts(visual_engine.config).verify(envelope,asset)


def test_old_immutable_manifest_remains_verifiable_for_retention(visual_engine,clock):
    envelope=issue(visual_engine,clock);asset=visual_engine.get(envelope['job_id'])['asset']
    path=Path(envelope['manifest_path']);manifest=json.loads(path.read_text());manifest['schema_version']=1
    manifest.pop('caption_cues');manifest.pop('rendered_duration');manifest.pop('render_receipt_sha256')
    for field in ('checks','caption_style','required_labels'):manifest.pop(field)
    for frame in manifest['frames']:frame.pop('caption_expected')
    raw=canonical(manifest).encode();path.write_bytes(raw);envelope['manifest_sha256']=hashlib.sha256(raw).hexdigest()
    assert VisualArtifacts(visual_engine.config).verify(envelope,asset)['schema_version']==1


def test_terminal_workflow_before_native_call_recovers_to_visual_only_new_execution(visual_engine,adapter,clock):
    import subprocess
    original=issue(visual_engine,clock)
    asset=visual_engine.get(original['job_id'])['asset']
    calls=list(adapter.calls)
    clock.now=original['expires_at']+1
    visual_engine.native_execution={'execution_id':'124','workflow_id':'workflow-test'}
    recovered=visual_engine.prepare('clip')
    assert recovered['ready'] is False and recovered['state']=='visual_pending'
    next_envelope=recovered['action_result']['visual']
    assert next_envelope['attempt_id']!=original['attempt_id']
    assert next_envelope['native_execution']['execution_id']=='124'
    assert next_envelope['asset_sha256']==asset['sha256']
    assert adapter.calls.count('render')==calls.count('render')
    with visual_engine.transaction() as db:
        old=dict(db.execute('SELECT * FROM visual_attempts WHERE id=?',(original['attempt_id'],)).fetchone())
        assert old['state']=='expired' and old['result'] is None
        assert db.execute('SELECT model_calls FROM budgets').fetchone()[0]==3
        assert db.execute('SELECT count(*) FROM publications').fetchone()[0]==0
    # Execute the actual deployed Code-node source against the SDK's real
    # nested output, using this fixture's trusted coordinator clock.
    workflow=Path(__file__).resolve().parents[1]/'deploy/workflows/clip.json'
    script="const fs=require('node:fs'),vm=require('node:vm');const workflow=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));const source=workflow.nodes.find(n=>n.name==='Require visual review').parameters.jsCode;const input=JSON.parse(fs.readFileSync(0,'utf8'));const result=vm.runInNewContext('(function(){'+source+'})()',{Date:{now:()=>Number(process.argv[2])},$input:{first:()=>({json:input})}});process.stdout.write(JSON.stringify(result));"
    process=subprocess.run(['node','-e',script,str(workflow),str(clock()*1000)],input=canonical(recovered),capture_output=True,text=True,timeout=2,check=True)
    assert json.loads(process.stdout)[0]['json']['visual']==next_envelope
    assert visual_engine.prune_visual_artifacts()==0  # Preserve active new work.
    assert visual_engine.apply_visual(receipt(next_envelope,clock),execute=False)['state']=='ready'
    clock.now=next_envelope['expires_at']+visual_engine.config['visual']['retention_seconds']+1
    assert visual_engine.prune_visual_artifacts()>0
    with visual_engine.transaction() as db:
        old=json.loads(db.execute('SELECT result FROM visual_attempts WHERE id=?',(original['attempt_id'],)).fetchone()[0])
        assert old['usage_observed'] is False and old['usage'] is None


@pytest.mark.parametrize('change',['expiry','reclaim','asset','manifest','frame','input','policy','nonce'])
def test_changed_visual_binding_never_posts(visual_engine,adapter,clock,change):
    envelope=issue(visual_engine,clock)
    if change=='expiry':clock.now+=36
    elif change=='reclaim':
        with visual_engine.transaction() as db:db.execute("UPDATE jobs SET lease_token='other-worker'")
    elif change=='asset':
        asset=visual_engine.get(envelope['job_id'])['asset'];Path(asset['path']).write_bytes(b'changed')
    elif change=='manifest':Path(envelope['manifest_path']).write_text('{}')
    elif change=='frame':
        manifest=json.loads(Path(envelope['manifest_path']).read_text());Path(manifest['frames'][0]['path']).write_bytes(b'changed')
    elif change=='input':
        with visual_engine.transaction() as db:db.execute("UPDATE jobs SET input_digest='changed'")
    elif change=='policy':
        with visual_engine.transaction() as db:db.execute("UPDATE jobs SET policy_digest='changed'")
    elif change=='nonce':envelope['nonce']='changed'
    with pytest.raises((SafetyError,OSError)):visual_engine.apply_visual(receipt(envelope,clock))
    assert adapter.uploads==[]


def test_failed_native_call_preserves_usage_and_bounds_retry(visual_engine,adapter,clock):
    envelope=issue(visual_engine,clock)
    failed=receipt(envelope,clock,outcome='failed',decision=None)
    result=visual_engine.apply_visual(failed)
    assert result['state']=='ready' and adapter.uploads==[]
    with visual_engine.transaction() as db:
        row=db.execute('SELECT result,state FROM visual_attempts').fetchone()
        assert row['state']=='failed' and '1351' in row['result']
    clock.now+=61
    new=visual_engine.run(envelope['job_id'])['visual']
    assert new['attempt_id']!=envelope['attempt_id'] and new['nonce']!=envelope['nonce']
    with visual_engine.transaction() as db:assert db.execute('SELECT model_calls FROM budgets').fetchone()[0]==3


def test_expired_call_usage_is_retained_but_does_not_authorize(visual_engine,adapter,clock):
    envelope=issue(visual_engine,clock)
    clock.now+=36
    with visual_engine.transaction() as db:visual_engine._recover(db)
    with pytest.raises(SafetyError,match='expired_or_reclaimed'):visual_engine.apply_visual(receipt(envelope,clock,outcome='failed',decision=None))
    with visual_engine.transaction() as db:
        attempt=db.execute('SELECT result,state FROM visual_attempts').fetchone()
        assert attempt['state']=='expired' and '1351' in attempt['result']
    assert adapter.uploads==[]


@pytest.mark.parametrize('usage',[None,{'uncachedInputTokens':False,'outputTokens':0,'cacheReadTokens':0,'cacheWriteTokens':0},{'totalTokens':1}])
def test_usage_presence_and_shape_are_explicit(usage,clock):
    data=receipt({},clock,usage=usage)
    data['envelope']=dict.fromkeys(__import__('tiktok_clipping_cli.visual',fromlist=['ENVELOPE_FIELDS']).ENVELOPE_FIELDS,'test')
    with pytest.raises(SafetyError):validate_receipt(data)


def test_visual_native_missing_usage_cannot_publish(visual_engine,adapter,clock):
    envelope=issue(visual_engine,clock)
    result=visual_engine.apply_visual(receipt(envelope,clock,usage_observed=False,usage=None))
    assert result['state']=='ready' and adapter.uploads==[]


def test_stable_owned_read_rejects_symlink_and_oversize(tmp_path):
    p=tmp_path/'actual';p.write_bytes(b'1234')
    link=tmp_path/'alias';link.symlink_to(p)
    with pytest.raises(SafetyError):owned_bytes(link,tmp_path,10)
    with pytest.raises(SafetyError):owned_bytes(p,tmp_path,3)
    with pytest.raises(SafetyError):owned_bytes(p,tmp_path,10,'f'*64)


def test_restart_between_usage_commit_and_decision_replays_remaining_transaction(visual_engine,adapter,clock,monkeypatch):
    envelope=issue(visual_engine,clock)
    incoming=receipt(envelope,clock)
    active=visual_engine._active
    def crash(db):raise KeyboardInterrupt('simulated process death between commits')
    monkeypatch.setattr(visual_engine,'_active',crash)
    with pytest.raises(KeyboardInterrupt):visual_engine.apply_visual(incoming)
    with visual_engine.transaction() as db:
        attempt=db.execute('SELECT state,result_digest FROM visual_attempts').fetchone()
        assert attempt['state']=='pending' and attempt['result_digest']
    monkeypatch.setattr(visual_engine,'_active',active)
    current=Engine(visual_engine.config,adapter=adapter,clock=clock,native_execution=visual_engine.native_execution,native_completion=True)
    assert current.apply_visual(incoming)['state']=='published'
    assert len(adapter.uploads)==1
    with current.transaction() as db:assert db.execute("SELECT count(*) FROM events WHERE event='visual_usage_observed'").fetchone()[0]==1


def test_native_rate_limit_cooldown_blocks_other_jobs_and_preserves_long_delay(visual_engine,adapter,clock):
    from tiktok_clipping_cli.engine import AdapterFailure
    envelope=issue(visual_engine,clock)
    failed=receipt(envelope,clock,outcome='failed',decision=None,failure={'category':'rate_limit','code':'RATE_LIMIT','status':429,'retry_after_ms':172800001.5})
    result=visual_engine.apply_visual(failed)
    assert result['state']=='ready'
    from conftest import source
    visual_engine.ingest(source(clock,'another-video'))
    with pytest.raises(AdapterFailure,match='circuit_open: model'):visual_engine.prepare('clip')
    with visual_engine.transaction() as db:
        assert db.execute("SELECT until FROM circuits WHERE capability='model'").fetchone()[0]==clock()+172800.0015
        assert db.execute('SELECT model_calls FROM budgets').fetchone()[0]==2
    assert adapter.uploads==[]


def test_duplicate_model_json_is_failed_with_usage_retained(visual_engine,adapter,clock):
    envelope=issue(visual_engine,clock)
    incoming=receipt(envelope,clock,raw_result='{"passed":false,"passed":true}')
    result=visual_engine.apply_visual(incoming)
    assert result['state']=='ready' and adapter.uploads==[]
    with visual_engine.transaction() as db:
        row=json.loads(db.execute('SELECT result FROM visual_attempts').fetchone()[0])
        assert row['failure']['category']=='malformed_output' and row['usage']['outputTokens']==1351


def test_model_deadline_retains_continuation_headroom(visual_engine,adapter,clock):
    envelope=issue(visual_engine,clock)
    assert envelope['expires_at']-envelope['model_deadline']==5
    # The native call ended within its deadline; CLI transport uses headroom.
    finished=receipt(envelope,clock)
    clock.now+=32
    assert visual_engine.apply_visual(finished)['state']=='published'
    assert len(adapter.uploads)==1


def test_finished_attempt_retention_removes_exact_files_keeps_receipt(visual_engine,adapter,clock):
    envelope=issue(visual_engine,clock)
    visual_engine.apply_visual(receipt(envelope,clock))
    assert visual_engine.prune_visual_artifacts()==0
    clock.now+=121
    assert visual_engine.prune_visual_artifacts()>0
    assert not Path(envelope['manifest_path']).exists()
    with visual_engine.transaction() as db:
        row=db.execute('SELECT result,artifacts_cleaned FROM visual_attempts').fetchone()
        assert row['artifacts_cleaned']==1 and row['result']
    assert visual_engine.prune_visual_artifacts()==0


@pytest.mark.parametrize('change',['live','unknown_file','changed_frame','symlink'])
def test_retention_preserves_live_unknown_and_changed_artifacts(visual_engine,adapter,clock,change):
    envelope=issue(visual_engine,clock)
    visual_engine.apply_visual(receipt(envelope,clock))
    clock.now+=121
    root=Path(envelope['manifest_path']).parent
    if change=='live':
        with visual_engine.transaction() as db:db.execute("UPDATE jobs SET status='running',lease_until=?",(clock()+100,))
    elif change=='unknown_file':(root/'foreign').write_text('preserve')
    elif change=='changed_frame':(root/'frame-0.jpg').write_text('changed')
    elif change=='symlink':(root/'foreign').symlink_to(root/'frame-0.jpg')
    assert visual_engine.prune_visual_artifacts()==0
    assert Path(envelope['manifest_path']).exists()


def test_receiptless_timeout_reclaims_only_after_exact_native_end_and_absence(visual_engine,adapter,clock):
    envelope=issue(visual_engine,clock)
    clock.now+=121
    with visual_engine.transaction() as db:visual_engine._recover(db)
    assert visual_engine.prune_visual_artifacts()>0
    with visual_engine.transaction() as db:
        row=db.execute('SELECT * FROM visual_attempts').fetchone()
        result=json.loads(row['result'])
        assert result['usage_observed'] is False and result['usage'] is None
        assert row['artifacts_cleaned']==1 and row['native_completed_at']
        assert db.execute('SELECT model_calls FROM budgets').fetchone()[0]==2
    assert adapter.uploads==[]


@pytest.mark.parametrize('proof',[{'terminal':False},{'process_absent':False},{'execution_id':'other'},{'workflow_id':'other'}])
def test_abandoned_attempt_unknown_execution_or_live_process_preserves(visual_engine,adapter,clock,proof):
    envelope=issue(visual_engine,clock)
    clock.now+=121
    with visual_engine.transaction() as db:visual_engine._recover(db)
    adapter.visual_execution_state=lambda e:{**e['native_execution'],'terminal':True,'process_absent':True,'stopped_at':iso(e['model_deadline']),'provenance':'TEST',**proof}
    assert visual_engine.prune_visual_artifacts()==0
    assert Path(envelope['manifest_path']).exists()


@pytest.mark.parametrize('condition',['running','404','wrong_execution','wrong_workflow','live_pid','reused_pid','absent_pid'])
def test_native_execution_reader_and_pid_identity_are_exact(tmp_path,condition):
    from subprocess import CompletedProcess
    from tiktok_clipping_cli.visual import native_execution_state
    e={'native_execution':{'execution_id':'123','workflow_id':'expected'},'job_id':'a'*32,'attempt_id':'b'*32,'nonce':'ownednonce'}
    root=tmp_path/'visual'/e['job_id']/e['attempt_id'];root.mkdir(parents=True)
    (root/'process-start.json').write_text(canonical({'schema_version':1,'job_id':e['job_id'],'attempt_id':e['attempt_id'],'nonce':e['nonce'],'pid':1234,'start_identity':'Sun Oct 4 12:00:00 2026'}))
    record={'id':'123','workflowId':'expected','status':'error','stoppedAt':'2026-10-04T12:01:00Z'}
    if condition=='running':record['status']='running'
    elif condition=='wrong_execution':record['id']='other'
    elif condition=='wrong_workflow':record['workflowId']='other'
    def read(identifier):
        assert identifier=='123'
        if condition=='404':raise RuntimeError('NotFound')
        return record
    def process(pid):
        assert pid==1234
        if condition=='absent_pid':return CompletedProcess([],1,'','')
        return CompletedProcess([],0,'Sun Oct 4 12:00:00 2026' if condition=='live_pid' else 'Sun Oct 4 12:05:00 2026','')
    result=native_execution_state({'workspace':str(tmp_path)},e,execution_reader=read,process_reader=process)
    assert result['process_absent']==(condition in ['reused_pid','absent_pid'])


def test_partial_cleanup_restart_uses_persisted_end_proof_after_marker_deletion(visual_engine,adapter,clock,monkeypatch):
    envelope=issue(visual_engine,clock)
    root=Path(envelope['manifest_path']).parent
    (root/'process-start.json').write_text('{}')
    visual_engine.apply_visual(receipt(envelope,clock))
    clock.now+=121
    original=VisualArtifacts.prune
    def partial(artifacts,e,inventory):
        (root/'process-start.json').unlink()
        (root/'frame-0.jpg').unlink()
        raise OSError('simulated crash after marker unlink')
    monkeypatch.setattr(VisualArtifacts,'prune',partial)
    assert visual_engine.prune_visual_artifacts()==0
    with visual_engine.transaction() as db:assert db.execute('SELECT native_termination_proof FROM visual_attempts').fetchone()[0]
    monkeypatch.setattr(VisualArtifacts,'prune',original)
    def should_not_repeat(e):raise AssertionError('deleted PID marker must not strand saved proof')
    adapter.visual_execution_state=should_not_repeat
    current=Engine(visual_engine.config,adapter=adapter,clock=clock)
    assert current.prune_visual_artifacts()>0
    assert not root.exists()


def test_old_receiptless_attempt_cleanup_uses_immutable_original_asset(visual_engine,adapter,clock):
    envelope=issue(visual_engine,clock)
    clock.now+=121
    with visual_engine.transaction() as db:
        visual_engine._recover(db)
        db.execute("UPDATE jobs SET asset=?",(canonical({'sha256':'f'*64,'path':'changed-new-render','bytes':1,'provenance':'TEST changed new asset'}),))
    assert visual_engine.prune_visual_artifacts()>0
    assert not Path(envelope['manifest_path']).exists()


def test_visual_rejection_revision_is_atomic_with_verified_original_lease(visual_engine,adapter,clock,monkeypatch):
    import sqlite3
    envelope=issue(visual_engine,clock)
    original=visual_engine._revision
    def interleave(job_id,error,**kwargs):
        assert kwargs['worker_token']==envelope['lease_token']
        assert kwargs['db'].in_transaction
        with sqlite3.connect(visual_engine.database,timeout=0) as other:
            with pytest.raises(sqlite3.OperationalError,match='locked'):
                other.execute("UPDATE jobs SET lease_token='reclaimed',status='running'")
        return original(job_id,error,**kwargs)
    monkeypatch.setattr(visual_engine,'_revision',interleave)
    rejected=receipt(envelope,clock,decision={'passed':False,'checks':dict.fromkeys(CHECKS,False),'reason':'TEST visual rejection'})
    result=visual_engine.apply_visual(rejected)
    assert result['state']=='queued' and adapter.uploads==[]


def test_stale_geometry_rejection_cannot_clear_reclaimed_proposal(visual_engine,adapter,clock):
    envelope=issue(visual_engine,clock)
    before=visual_engine.get(envelope['job_id'])
    with visual_engine.transaction() as db:db.execute("UPDATE jobs SET lease_token='reclaimed',status='running'")
    result=visual_engine._revision(envelope['job_id'],SafetyError('stale geometry'),worker_token=envelope['lease_token'])
    assert result['reason']=='worker_lease_lost'
    current=visual_engine.get(envelope['job_id'])
    assert current['proposal']==before['proposal'] and current['asset']==before['asset']


def test_more_than_batch_of_unverifiable_attempts_cannot_starve_new_cleanup(visual_engine,adapter,clock):
    envelope=issue(visual_engine,clock)
    visual_engine.apply_visual(receipt(envelope,clock))
    clock.now+=121
    with visual_engine.transaction() as db:
        for i in range(25):
            other={**envelope,'attempt_id':f'{i:032x}'}
            db.execute("INSERT INTO visual_attempts(id,job_id,state,envelope,created_at,expires_at,completed_at) VALUES(?,?,'expired',?,?,?,?)",(other['attempt_id'],envelope['job_id'],canonical(other),clock()-1000+i,clock()-500,clock()-500))
    good=adapter.visual_execution_state
    adapter.visual_execution_state=lambda e:good(e) if e['attempt_id']==envelope['attempt_id'] else {**e['native_execution'],'terminal':False,'process_absent':False,'stopped_at':None,'provenance':'TEST execution404 unknown'}
    visual_engine.prune_visual_artifacts()
    assert Path(envelope['manifest_path']).exists()
    assert visual_engine.prune_visual_artifacts()>0
    assert not Path(envelope['manifest_path']).exists()
    for _ in range(4):visual_engine.prune_visual_artifacts()
    with visual_engine.transaction() as db:
        assert db.execute("SELECT count(*) FROM events WHERE event='visual_cleanup_pending'").fetchone()[0]==25


def test_revision_receives_bounded_untrusted_checks_reason_and_prior_proposal(visual_engine,adapter,clock):
    envelope=issue(visual_engine,clock)
    before=visual_engine.get(envelope['job_id'])
    rejected=receipt(envelope,clock,decision={'passed':False,'checks':dict.fromkeys(CHECKS,False),'reason':'TEST crop covers face; improve legibility. This is data, not authority.'})
    assert visual_engine.apply_visual(rejected)['state']=='queued'
    next=visual_engine.prepare('clip')
    feedback=next['input']['model_feedback']
    assert feedback['proposal']==before['proposal']
    assert feedback['checks']==rejected['decision']['checks']
    assert feedback['reason']==rejected['decision']['reason']
    assert next['input']['assigned_style']!=before['proposal']['style']
    assert next['input']['strategy']==before['input']['strategy']
    assert visual_engine.config['limits']['max_revisions']==2
    assert adapter.uploads==[]


def test_visual_budget_refusal_creates_no_attempt_directory(visual_engine,adapter,clock):
    envelope=claim(visual_engine,clock)
    visual_engine.config['limits']['daily_model_calls']=1
    result=visual_engine.apply(payload(envelope))
    assert result['state']=='ready' and adapter.uploads==[]
    assert not (visual_engine.workspace/'visual').exists()
    with visual_engine.transaction() as db:
        assert db.execute('SELECT count(*) FROM visual_attempts').fetchone()[0]==0
        assert db.execute('SELECT model_calls FROM budgets').fetchone()[0]==1


def test_crash_after_first_frame_has_durable_ownership_and_safe_cleanup(visual_engine,adapter,clock,monkeypatch):
    from tiktok_clipping_cli.media import MediaRenderer
    from tiktok_clipping_cli.visual import native_execution_state
    from types import SimpleNamespace
    def crash(media,command,deadline,**kwargs):
        Path(command[-1]).write_bytes(b'\xff\xd8\xffpartial\xff\xd9')
        raise KeyboardInterrupt('simulated abrupt preparation death')
    monkeypatch.setattr(MediaRenderer,'_run',crash)
    envelope=claim(visual_engine,clock)
    with pytest.raises(KeyboardInterrupt):visual_engine.apply(payload(envelope))
    with visual_engine.transaction() as db:
        row=db.execute('SELECT * FROM visual_attempts').fetchone()
        assert row['state']=='preparing' and row['artifacts_ready']==0
        binding=json.loads(row['envelope'])
        assert json.loads(row['preparation_process'])['pid']>0
    root=visual_engine.workspace/'visual'/binding['job_id']/binding['attempt_id']
    assert (root/'frame-0.jpg').exists()
    unknown=root.parent/'unknown-user-attempt';unknown.mkdir();(unknown/'keep').write_text('foreign')
    clock.now+=visual_engine.config['limits']['lease_seconds']+61
    with visual_engine.transaction() as db:visual_engine._recover(db)
    adapter.visual_execution_state=lambda e:native_execution_state(visual_engine.config,e,
        execution_reader=lambda i:{'id':i,'workflowId':'workflow-test','status':'error','stoppedAt':iso(clock()-61)},
        process_reader=lambda pid:SimpleNamespace(returncode=1,stdout=''))
    assert visual_engine.prune_visual_artifacts()>0
    assert not root.exists() and (unknown/'keep').read_text()=='foreign'
    assert adapter.uploads==[]
    with visual_engine.transaction() as db:
        assert db.execute('SELECT artifacts_cleaned FROM visual_attempts').fetchone()[0]==1
        assert db.execute('SELECT model_calls FROM budgets').fetchone()[0]==2


def test_incomplete_preparation_cleanup_refuses_live_original_worker(visual_engine,clock,adapter):
    from tiktok_clipping_cli.visual import native_execution_state,current_process_identity
    e={'native_execution':{'execution_id':'123','workflow_id':'workflow-test'},'preparation_process':current_process_identity()}
    result=native_execution_state(visual_engine.config,e,execution_reader=lambda i:{'id':i,'workflowId':'workflow-test','status':'error','stoppedAt':iso(clock())})
    assert result['terminal'] and result['process_absent'] is False


def test_current_visual_contract_requires_attribution_and_no_added_disclaimer(visual_engine,clock):
    envelope=issue(visual_engine,clock)
    manifest=json.loads(Path(envelope['manifest_path']).read_text())
    assert manifest['schema_version']==3 and set(manifest['checks'])==CHECKS
    assert 'required_attribution_visible' in CHECKS and 'no_added_ad_disclaimer' in CHECKS and 'disclosure_visible' not in CHECKS
    assert 'naturally spoken transcript words are allowed' in manifest['prompt']
    legacy=receipt(envelope,clock)
    legacy['decision']['checks'].pop('required_attribution_visible');legacy['decision']['checks'].pop('no_added_ad_disclaimer')
    legacy['decision']['checks']['disclosure_visible']=True
    with pytest.raises(SafetyError,match='current_review_checks'):visual_engine.apply_visual(legacy,execute=False)


def test_late_native_file_accounts_once_and_keeps_proof_before_cleanup(visual_engine,adapter,clock,monkeypatch):
    envelope=issue(visual_engine,clock)
    root=Path(envelope['manifest_path']).parent
    completed=receipt(envelope,clock)
    raw=(json.dumps(completed)+'\n').encode();(root/'native-receipt.json').write_bytes(raw)
    identity={'pid':123,'start_identity':'TEST native process identity'}
    (root/'process-start.json').write_text(canonical({'schema_version':1,'job_id':envelope['job_id'],'attempt_id':envelope['attempt_id'],'nonce':envelope['nonce'],**identity}))
    proof={'schema_version':1,'envelope':envelope,'process':identity,'started_at':iso(clock()),'completed_at':iso(clock()+2.4),'monotonic_started_ms':1000,'monotonic_completed_ms':3400,'elapsed_seconds':2.4,'receipt_sha256':hashlib.sha256(raw).hexdigest(),'provenance':'native_process_monotonic'}
    (root/'runtime.json').write_text(canonical(proof))
    # Native output was durable, but the continuation crashed before DB ingestion.
    clock.now=envelope['expires_at']+121
    with visual_engine.transaction() as db:visual_engine._recover(db)
    original=VisualArtifacts.prune
    def interrupted(artifacts,e,inventory):
        (root/'runtime.json').unlink()
        raise OSError('TEST cleanup crash after timing proof unlink')
    monkeypatch.setattr(VisualArtifacts,'prune',interrupted)
    assert visual_engine.prune_visual_artifacts()==0
    with visual_engine.transaction() as db:
        row=db.execute('SELECT * FROM visual_attempts').fetchone()
        assert row['state']=='expired' and json.loads(row['result'])==completed
        assert db.execute("SELECT count(*) FROM events WHERE event='visual_usage_observed'").fetchone()[0]==1
        reservation=db.execute('SELECT * FROM runtime_reservations WHERE kind=\'visual\'').fetchone()
        assert reservation['settled_seconds']==3 and json.loads(reservation['native_proof'])==proof
    assert adapter.uploads==[]
    monkeypatch.setattr(VisualArtifacts,'prune',original)
    # Newly ingested accounting receives the normal retention window too.
    clock.now+=visual_engine.config['visual']['retention_seconds']+1
    assert visual_engine.prune_visual_artifacts()>0
    assert not root.exists() and adapter.uploads==[]
    with visual_engine.transaction() as db:
        assert db.execute("SELECT count(*) FROM events WHERE event='visual_usage_observed'").fetchone()[0]==1


@pytest.mark.parametrize('invalid',['malformed','binding'])
def test_late_invalid_native_file_is_visible_and_preserved(visual_engine,adapter,clock,invalid):
    envelope=issue(visual_engine,clock);root=Path(envelope['manifest_path']).parent
    completed=receipt(envelope,clock)
    if invalid=='binding':completed['envelope']={**envelope,'native_execution':{'execution_id':'other','workflow_id':'workflow-test'}}
    (root/'native-receipt.json').write_text('{' if invalid=='malformed' else canonical(completed))
    clock.now=envelope['expires_at']+121
    with visual_engine.transaction() as db:visual_engine._recover(db)
    assert visual_engine.prune_visual_artifacts()==0
    with visual_engine.transaction() as db:
        row=db.execute('SELECT * FROM visual_attempts').fetchone()
        assert row['result'] is None and row['cleanup_issue'] and not row['artifacts_cleaned']
    assert (root/'native-receipt.json').exists() and adapter.uploads==[]


def test_failed_visual_provider_delay_pauses_all_model_kinds(visual_engine,clock):
    envelope=issue(visual_engine,clock)
    failure={'category':'provider_unavailable','code':'SERVER','status':503,'retry_after_ms':172800000}
    result=visual_engine.apply_visual(receipt(envelope,clock,outcome='failed',decision=None,failure=failure),execute=False)
    assert result['state']=='ready'
    with visual_engine.transaction() as db:
        assert db.execute("SELECT until FROM circuits WHERE capability='model'").fetchone()[0]==clock()+172800
        with pytest.raises(Exception,match='circuit_open: model'):visual_engine._model_available(db)


def test_known_other_attempt_receipt_cannot_be_recovered_from_wrong_owned_path(visual_engine,adapter,clock):
    envelope=issue(visual_engine,clock)
    root=Path(envelope['manifest_path']).parent
    other={**envelope,'attempt_id':'f'*32,'nonce':'TEST other known attempt nonce'}
    other_receipt=receipt(other,clock)
    (root/'native-receipt.json').write_text(canonical(other_receipt))
    clock.now=envelope['expires_at']+121
    with visual_engine.transaction() as db:
        visual_engine._recover(db)
        # Both envelopes are known to the ledger. Only the original expired
        # attempt is eligible for cleanup, and its path contains B's receipt.
        db.execute("INSERT INTO visual_attempts(id,job_id,state,envelope,created_at,expires_at) VALUES(?,?,'pending',?,?,?)",
            (other['attempt_id'],other['job_id'],canonical(other),envelope['model_deadline']-30,clock()+60))
    assert visual_engine.prune_visual_artifacts()==0
    with visual_engine.transaction() as db:
        rows={r['id']:dict(r)for r in db.execute('SELECT * FROM visual_attempts')}
        assert rows[envelope['attempt_id']]['cleanup_issue']
        assert rows[other['attempt_id']]['state']=='pending'
        assert all(r['result'] is None and not r['artifacts_cleaned']for r in rows.values())
        assert db.execute("SELECT count(*) FROM events WHERE event='visual_usage_observed'").fetchone()[0]==0
        assert db.execute("SELECT settled_seconds FROM runtime_reservations WHERE kind='visual'").fetchone()[0] is None
    assert (root/'native-receipt.json').is_file() and adapter.uploads==[]


def test_subject_framing_requirements_reach_hash_bound_native_manifest(visual_engine, clock):
    envelope = issue(visual_engine, clock)
    raw = Path(envelope['manifest_path']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == envelope['manifest_sha256']
    manifest = json.loads(raw)
    assert manifest['schema_version'] == 3 and set(manifest['checks']) == CHECKS
    prompt = manifest['prompt']
    for instruction in ('assess the visible subject and framing in every sampled frame',
                        'not just a 9:16 shape', 'faces and heads visible',
                        'without severe cropping at the edges', 'Reject mostly empty walls',
                        'do not compensate for poor subject framing',
                        'Do not assume unsampled frames repair a bad sampled frame'):
        assert instruction in prompt


def test_bad_subject_framing_uses_existing_bounded_revisions_and_never_posts(visual_engine, adapter, clock):
    for index in range(visual_engine.config['limits']['max_revisions'] + 1):
        envelope = issue(visual_engine, clock)
        incoming = receipt(envelope, clock, decision={
            'passed': False,
            'checks': {**dict.fromkeys(CHECKS, True), 'portrait_composition': False},
            'reason': 'Talking subject is absent in one sample and severely cropped in the others.'})
        result = visual_engine.apply_visual(incoming)
        job = visual_engine.get(envelope['job_id'])
        assert result['state'] == ('queued' if index < 2 else 'failed')
        # The exhausted rejection is recorded too; it cannot queue a fourth proposal.
        assert job['revisions'] == index + 1
        assert adapter.uploads == []
        with visual_engine.transaction() as db:
            saved = json.loads(db.execute('SELECT result FROM visual_attempts WHERE id=?',
                                         (envelope['attempt_id'],)).fetchone()[0])
            assert saved['decision'] == incoming['decision']
            assert db.execute('SELECT COUNT(*) FROM publications').fetchone()[0] == 0
        if index < 2:
            assert job['proposal'] is None and job['asset'] is None


def test_composition_rejection_assigns_full_frame_with_conditioned_propensity(visual_engine,adapter,clock,monkeypatch):
    from copy import deepcopy
    from conftest import source
    from test_outcome_learning import objective
    config=deepcopy(visual_engine.config)
    config['database']=str(Path(config['database']).with_name('framing-policy.db'))
    config['baseline']['weights']={'right':.9,'full_frame':.1}
    config['learning']['outcome_policy']={'objectives':[objective()],'baseline_share':.1}
    engine=Engine(config,adapter=adapter,clock=clock,native_execution=visual_engine.native_execution,native_completion=True)
    engine.control('running')
    with monkeypatch.context() as fixed:
        fixed.setattr('tiktok_clipping_cli.engine.secrets.token_hex',lambda size:'a'*(size*2))
        engine.ingest(source(clock))
    first=engine.prepare('clip')
    assert first['input']['assigned_style']=='right'
    review=engine.apply(payload(first))['visual']
    rejected=receipt(review,clock,decision={'passed':False,
        'checks':{**dict.fromkeys(CHECKS,True),'portrait_composition':False},
        'reason':'One frame shows only drums; other frames crop the speaker at the edge.'})
    assert engine.apply_visual(rejected)['state']=='queued'
    next=engine.prepare('clip')
    assert next['input']['assigned_style']=='full_frame'
    assignment=next['input']['outcome_selection']['style_assignment']
    assert assignment=={'style':'full_frame','propensity':{'numerator':'1','denominator':'1'},
                        'distribution':{'full_frame':{'numerator':'1','denominator':'1'}}}
    assert next['input']['strategy']==config['baseline']
    assert next['input']['model_feedback']['proposal']['style']=='right'
    assert adapter.uploads==[]


@pytest.mark.parametrize('branch,expected_style',[('baseline','right'),('exploitation','right'),('exploration','full_frame')])
def test_composition_alternative_support_matches_selected_outcome_branch(visual_engine,adapter,clock,monkeypatch,branch,expected_style):
    from copy import deepcopy
    from conftest import source
    from test_outcome_learning import objective
    config=deepcopy(visual_engine.config)
    config['database']=str(Path(config['database']).with_name('zero-frame-'+branch+'.db'))
    config['baseline']['weights']={'right':1,'full_frame':0}
    config['baseline']['exploration']=.05
    config['learning']['outcome_policy']={'objectives':[objective()],'baseline_share':.1}
    engine=Engine(config,adapter=adapter,clock=clock,native_execution=visual_engine.native_execution,native_completion=True)
    engine.control('running');engine.ingest(source(clock))
    original_select=engine._select_clip_candidates
    selected_branch='exploitation'
    def select(db,candidates):
        row,outcome=original_select(db,candidates)
        # Test the trusted selector branch seam; mixture draws are covered by
        # outcome-learning tests and the positive-weight prepare test above.
        outcome['decision']['branch']=selected_branch
        return row,outcome
    monkeypatch.setattr(engine,'_select_clip_candidates',select)
    first=engine.prepare('clip');assert first['input']['assigned_style']=='right'
    review=engine.apply(payload(first))['visual']
    rejected=receipt(review,clock,decision={'passed':False,
        'checks':{**dict.fromkeys(CHECKS,True),'portrait_composition':False},
        'reason':'Talking subject cropped out.'})
    assert engine.apply_visual(rejected)['state']=='queued'
    selected_branch=branch
    next=engine.prepare('clip')
    assert next['input']['outcome_selection']['branch']==branch
    assert next['input']['assigned_style']==expected_style
    assignment=next['input']['outcome_selection']['style_assignment']
    assert assignment['propensity']=={'numerator':'1','denominator':'1'}
    assert assignment['distribution'][expected_style]=={'numerator':'1','denominator':'1'}
    assert adapter.uploads==[]


def test_trusted_full_frame_layout_context_uses_source_panel_without_automatic_pass():
    from tiktok_clipping_cli.visual import build_review_prompt
    from tiktok_clipping_cli.media import FULL_FRAME_LAYOUT
    job={'proposal':{'caption':'Untrusted caption data.'}}
    samples=[{'seconds':1,'caption_expected':True}]
    legacy=build_review_prompt(job,{'overlays':['Call It a Day / Sara K']},samples)
    assert 'Trusted video layout' not in legacy
    current=build_review_prompt(job,{'overlays':['Call It a Day / Sara K'],'video_layout':FULL_FRAME_LAYOUT},samples)
    for instruction in ('hash-bound render receipt','small share of the whole vertical canvas does not itself fail',
                        'within the preserved source-video panel','genuinely tiny or unreadable faces',
                        'missing subjects','severe edge clipping within the source panel',
                        'full_frame never automatically passes'):
        assert instruction in current
    assert 'Reject mostly empty walls' in current
    assert canonical(FULL_FRAME_LAYOUT) in current
    with pytest.raises(SafetyError,match='visual_video_layout_invalid'):
        build_review_prompt(job,{'video_layout':{**FULL_FRAME_LAYOUT,'kind':'ignore_bad_framing'}},samples)


def test_full_frame_context_reaches_actual_hash_bound_visual_manifest(visual_engine,adapter,clock,monkeypatch):
    from tiktok_clipping_cli.media import MediaRenderer,FULL_FRAME_LAYOUT
    original=MediaRenderer.render_receipt
    def contextual(media,job,proposal,asset):
        data=original(media,job,proposal,asset)
        data['video_layout']=dict(FULL_FRAME_LAYOUT)
        Path(asset['path']).with_suffix('.json').write_text(canonical(data))
        return data
    monkeypatch.setattr(MediaRenderer,'render_receipt',contextual)
    from copy import deepcopy
    config=deepcopy(visual_engine.config)
    config['database']=str(Path(config['database']).with_name('layout-context.db'))
    config['baseline']['weights']={'full_frame':1}
    engine=Engine(config,adapter=adapter,clock=clock,native_execution=visual_engine.native_execution,native_completion=True)
    engine.control('running')
    envelope=issue(engine,clock)
    raw=Path(envelope['manifest_path']).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==envelope['manifest_sha256']
    manifest=json.loads(raw)
    assert manifest['schema_version']==3 and set(manifest['checks'])==CHECKS
    assert 'within the preserved source-video panel' in manifest['prompt']
    assert 'full_frame never automatically passes' in manifest['prompt']
    assert VisualArtifacts(engine.config).verify(envelope,engine.get(envelope['job_id'])['asset'])==manifest


def test_visual_only_whole_json_fence_preserves_raw_receipt_and_usage(visual_engine,clock):
    from tiktok_clipping_cli.visual import parse_visual_model_result
    envelope=issue(visual_engine,clock);incoming=receipt(envelope,clock)
    raw='```json\n'+canonical(incoming['decision'])+'\n```'
    incoming['raw_result']=raw
    assert parse_visual_model_result(raw)==incoming['decision']
    assert parse_visual_model_result(canonical(incoming['decision']))==incoming['decision']
    checked=validate_receipt(incoming)
    assert checked['raw_result']==raw and checked['usage']==incoming['usage']
    assert visual_engine.apply_visual(incoming,execute=False)['state']=='ready'
    saved=visual_engine.get(envelope['job_id'])
    assert saved['stage']=='publish'
    with visual_engine.transaction() as db:
        persisted=json.loads(db.execute('SELECT result FROM visual_attempts WHERE id=?',(envelope['attempt_id'],)).fetchone()[0])
        assert persisted['raw_result']==raw and persisted['usage']==incoming['usage']
    # Generic CLI/model-proposal JSON remains strict; this is visual transport only.
    from tiktok_clipping_cli.safety import strict_json
    with pytest.raises(SafetyError):strict_json(raw)
    failed={**incoming,'outcome':'failed','decision':None,'failure':{'category':'malformed_output','code':'invalid_model_result','status':None,'retry_after_ms':None}}
    assert validate_receipt(failed)['outcome']=='failed'


@pytest.mark.parametrize('raw',[
    'Prose before\n```json\n{}\n```', '```json\n{}\n```\nProse after',
    '```json\n{}\n```\n```json\n{}\n```', '```\n{}\n```',
    '```JSON\n{}\n```', ' ```json\n{}\n```',
    '```json\n{"passed":true,"passed":false}\n```',
    '```json\n{"value":NaN}\n```', '```json\n{"value":Infinity}\n```',
    '```json\n'+(' '*16384)+'{}\n```', None, 3])
def test_visual_fence_rejects_nonwhole_duplicate_nonfinite_and_oversize(raw):
    from tiktok_clipping_cli.visual import parse_visual_model_result
    with pytest.raises(SafetyError):parse_visual_model_result(raw)
