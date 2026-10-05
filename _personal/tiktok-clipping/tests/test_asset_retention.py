"""Exact ownership and restart-safe render cleanup, without public actions."""
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import claim,payload
from test_media import ffmpeg
from tiktok_clipping_cli.asset_retention import RenderOwnership,prune_owned
from tiktok_clipping_cli.safety import SafetyError,canonical


def owner_fixture(engine,clock):
    envelope=claim(engine,clock)
    engine.apply(payload(envelope),execute=False)
    with engine.transaction() as db:
        db.execute("UPDATE jobs SET status='running' WHERE id=?",(envelope['job_id'],))
        job=dict(db.execute('SELECT * FROM jobs WHERE id=?',(envelope['job_id'],)).fetchone())
    proposal=json.loads(job['proposal'])
    owner=RenderOwnership(engine.config,job,proposal,clock=clock)
    owner.root.mkdir(exist_ok=True)
    return owner,job,proposal


def intent_fixture(engine,clock):
    owner,job,proposal=owner_fixture(engine,clock)
    data=b'TEST owned obsolete render'
    path=owner.root/('c'*64+'.mp4')
    asset={'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'provenance':'TEST trusted renderer'}
    receipt={'asset':asset,'proposal':proposal,'render_owner':owner.owner}
    owner.intent(asset,receipt)
    with engine.transaction() as db:
        assert db.execute('SELECT receipt FROM rendered_assets').fetchone()[0]==canonical(receipt)
    assert not path.exists()  # Intent precedes any final path publication.
    path.write_bytes(data);path.with_suffix('.json').write_text(canonical(receipt))
    return owner,job,asset,receipt,path


def obsolete(engine,job,*,failed=False):
    with engine.transaction() as db:
        if failed:
            db.execute("UPDATE jobs SET status='failed',stage='render',lease_until=NULL WHERE id=?",(job['id'],))
        else:
            db.execute("UPDATE jobs SET status='queued',proposal=NULL,proposal_digest=NULL,lease_until=NULL WHERE id=?",(job['id'],))


@pytest.mark.parametrize('field',['lease_token','input_digest','proposal_digest','policy_digest','lease_until','status'])
def test_stale_owner_cannot_reserve_or_publish_intent(engine,clock,field):
    owner,job,proposal=owner_fixture(engine,clock)
    value=clock()-1 if field=='lease_until' else 'changed'
    with engine.transaction() as db:db.execute('UPDATE jobs SET '+field+'=? WHERE id=?',(value,job['id']))
    with pytest.raises(SafetyError,match='render_owner_lease_changed'):
        with owner.temporary('render'):raise AssertionError('must not create files')
    with engine.transaction() as db:assert db.execute('SELECT count(*) FROM render_temporaries').fetchone()[0]==0
    assert list(owner.root.iterdir())==[]


@pytest.mark.parametrize('failed',[False,True])
def test_obsolete_and_terminal_failed_assets_prune_only_exact_mp4_keep_audit(engine,clock,failed):
    owner,job,asset,receipt,path=intent_fixture(engine,clock)
    obsolete(engine,job,failed=failed)
    foreign=owner.root/'unknown.mp4';foreign.write_bytes(b'foreign')
    assert prune_owned(engine)==asset['bytes']
    assert not path.exists() and foreign.read_bytes()==b'foreign'
    assert json.loads(path.with_suffix('.json').read_text())==receipt
    with engine.transaction() as db:
        row=db.execute('SELECT * FROM rendered_assets').fetchone()
        assert row['cleaned_at'] and json.loads(row['receipt'])==receipt
    assert prune_owned(engine)==0


@pytest.mark.parametrize('protected',['active_lease','ready','blocked','visual_pending','ambiguous','recoverable_failed','public_reservation'])
def test_current_recoverable_or_publicly_reserved_asset_stays(engine,clock,protected):
    _,job,asset,_,path=intent_fixture(engine,clock)
    with engine.transaction() as db:
        db.execute('UPDATE jobs SET asset=?,lease_until=NULL WHERE id=?',(canonical(asset),job['id']))
        if protected=='active_lease':
            db.execute("UPDATE jobs SET status='failed',lease_until=? WHERE id=?",(clock()+30,job['id']))
        elif protected=='recoverable_failed':db.execute("UPDATE jobs SET status='failed',stage='visual' WHERE id=?",(job['id'],))
        elif protected=='public_reservation':
            db.execute("UPDATE jobs SET status='failed' WHERE id=?",(job['id'],))
            db.execute("INSERT INTO publications VALUES(?,?,?,?,?,'ambiguous',NULL,0)",('TEST publication',job['id'],'TEST account',asset['sha256'],'TEST unique'))
        else:db.execute('UPDATE jobs SET status=? WHERE id=?',(protected,job['id']))
    assert prune_owned(engine)==0 and path.exists()


@pytest.mark.parametrize('changed',['asset','receipt','symlink','fifo'])
def test_changed_or_nonregular_files_are_held_not_deleted(engine,clock,changed):
    _,job,_,_,path=intent_fixture(engine,clock);obsolete(engine,job)
    if changed=='asset':path.write_bytes(b'changed')
    elif changed=='receipt':path.with_suffix('.json').write_text('{}')
    else:
        path.unlink()
        if changed=='symlink':path.symlink_to(path.with_suffix('.json'))
        else:os.mkfifo(path)
    assert prune_owned(engine)==0 and path.exists()
    with engine.transaction() as db:assert db.execute('SELECT cleanup_issue FROM rendered_assets').fetchone()[0]


def test_crash_after_unlink_before_commit_resumes_without_redeleting_unknown(engine,clock,monkeypatch):
    _,job,asset,_,path=intent_fixture(engine,clock);obsolete(engine,job)
    from tiktok_clipping_cli import asset_retention as module
    original=module.fsync_directory
    def crash(p):raise OSError('TEST crash after exact owned unlink')
    monkeypatch.setattr(module,'fsync_directory',crash)
    assert prune_owned(engine)==0 and not path.exists()
    with engine.transaction() as db:
        row=db.execute('SELECT * FROM rendered_assets').fetchone()
        assert row['inventory'] and row['cleaned_at'] is None
    monkeypatch.setattr(module,'fsync_directory',original)
    assert prune_owned(engine)==0
    with engine.transaction() as db:assert db.execute('SELECT cleaned_at FROM rendered_assets').fetchone()[0]


def test_intent_without_final_rename_is_owned_and_recoverable(engine,clock):
    owner,job,proposal=owner_fixture(engine,clock)
    asset={'path':str(owner.root/('d'*64+'.mp4')),'sha256':'e'*64,'bytes':3,'provenance':'TEST'}
    owner.intent(asset,{'asset':asset,'proposal':proposal,'render_owner':owner.owner})
    obsolete(engine,job,failed=True)
    assert prune_owned(engine)==0
    with engine.transaction() as db:assert db.execute('SELECT cleaned_at FROM rendered_assets').fetchone()[0]


def test_confirmed_asset_cleanup_reuses_exact_reader_and_finishes_ownership_ledger(engine,clock):
    _,job,asset,receipt,path=intent_fixture(engine,clock)
    with engine.transaction() as db:
        db.execute("UPDATE jobs SET status='published',asset=?,lease_until=NULL WHERE id=?",(canonical(asset),job['id']))
        db.execute("INSERT INTO rewards(job_id,publication_id,campaign_id,state,deadline,updated_at) VALUES(?,?,?,'submitted',?,?)",
            (job['id'],'TEST confirmed publication','campaign-1',clock()+100,clock()))
    assert engine.prune_confirmed_assets()==asset['bytes']
    assert not path.exists() and path.with_suffix('.json').exists()
    with engine.transaction() as db:
        assert db.execute('SELECT cleaned_at FROM rendered_assets').fetchone()[0]
        assert json.loads(db.execute('SELECT receipt FROM rendered_assets').fetchone()[0])==receipt


def test_actual_cli_maintain_reclaims_only_durable_owned_obsolete_asset(engine,clock,tmp_path):
    _,job,asset,receipt,path=intent_fixture(engine,clock);obsolete(engine,job,failed=True)
    configuration=tmp_path/'retention-config.json';configuration.write_text(canonical(engine.config))
    result=subprocess.run([str(Path(sys.executable).parent/'tiktok-clipping'),'jobs','maintain','--config',str(configuration)],
        capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['removed_asset_bytes']==asset['bytes']
    assert not path.exists() and json.loads(path.with_suffix('.json').read_text())==receipt


def test_temporary_is_recorded_before_mkdir_and_normal_completion_keeps_receipt(engine,clock,monkeypatch):
    owner,_,_=owner_fixture(engine,clock)
    original=Path.mkdir
    def checked(path,*args,**kwargs):
        if path.name.startswith('render-'):
            with engine.transaction() as db:assert db.execute('SELECT path FROM render_temporaries').fetchone()[0]==str(path)
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'mkdir',checked)
    with owner.temporary('render') as temporary:
        path=Path(temporary);(path/'clip.mp4').write_bytes(b'TEST')
    assert not path.exists()
    with engine.transaction() as db:assert db.execute('SELECT cleaned_at FROM render_temporaries').fetchone()[0]


def crashed_temp(engine,clock,*,descendants=False):
    owner,job,_=owner_fixture(engine,clock)
    # Emulate SIGKILL after durable pre-mkdir reservation. No context manager
    # finally runs, and the original PID identity remains in the durable row.
    identifier='f'*32;path=owner.root/('render-'+identifier)
    with owner.transaction() as db:
        db.execute('INSERT INTO render_temporaries(id,job_id,owner,path,kind,process,descendants_unproven,created_at) VALUES(?,?,?,?,?,?,?,?)',
            (identifier,job['id'],canonical(owner.owner),str(path),'render',canonical(owner.process),int(descendants),clock()))
    path.mkdir();(path/'clip.mp4').write_bytes(b'TEST crash partial output')
    info=path.lstat()
    with engine.transaction() as db:db.execute('UPDATE render_temporaries SET directory_identity=?',(canonical([info.st_dev,info.st_ino]),))
    obsolete(engine,job,failed=True)
    return job,path


def test_crashed_owned_temp_cleanup_requires_original_process_absence(engine,clock,monkeypatch):
    job,path=crashed_temp(engine,clock)
    assert prune_owned(engine)==0 and path.exists()
    monkeypatch.setattr('tiktok_clipping_cli.asset_retention.process_absent',lambda process:True)
    assert prune_owned(engine)>0 and not path.exists()


@pytest.mark.parametrize('reason',['descendants','unknown_file','changed_hash'])
def test_unproven_crashed_temp_is_preserved_with_visible_issue(engine,clock,monkeypatch,reason):
    _,path=crashed_temp(engine,clock,descendants=reason=='descendants')
    monkeypatch.setattr('tiktok_clipping_cli.asset_retention.process_absent',lambda process:True)
    if reason=='unknown_file':(path/'foreign').write_bytes(b'unknown')
    elif reason=='changed_hash':
        from tiktok_clipping_cli.asset_retention import temporary_inventory
        with engine.transaction() as db:db.execute('UPDATE render_temporaries SET inventory=?',(canonical(temporary_inventory(path,'render',1000)),))
        (path/'clip.mp4').write_bytes(b'changed')
    assert prune_owned(engine)==0 and path.exists()
    with engine.transaction() as db:assert db.execute('SELECT cleanup_issue FROM render_temporaries').fetchone()[0]


def test_normal_temp_cleanup_failure_preserves_primary_error(engine,clock):
    owner,_,_=owner_fixture(engine,clock)
    with pytest.raises(RuntimeError,match='TEST original') as captured:
        with owner.temporary('render') as temp:
            (Path(temp)/'unknown').write_bytes(b'foreign')
            raise RuntimeError('TEST original')
    assert captured.value.__notes__
    with engine.transaction() as db:assert db.execute('SELECT cleanup_issue FROM render_temporaries').fetchone()[0]


def test_actual_direct_encoder_inherits_media_lock_after_parent_sigkill(engine,tmp_path):
    """Exercise the actual _run Popen path and kernel flock, never media/Post."""
    from tiktok_clipping_cli.media import MediaRenderer
    marker=tmp_path/'owned-child.json'
    child_script="import json,os,sys,time;from pathlib import Path;fd=int(sys.argv[1]);os.fstat(fd);Path(sys.argv[2]).write_text(json.dumps({'pid':os.getpid()}));time.sleep(30)"
    parent_script="""
import json,sys
from pathlib import Path
from tiktok_clipping_cli.media import MediaRenderer
config=json.loads(sys.argv[1]);renderer=MediaRenderer(config,ffmpeg=sys.executable)
renderer._disk=lambda *args: 1<<30
with renderer._lock(renderer._deadline()):
 renderer._run([sys.executable,'-c',sys.argv[2],str(renderer._media_lock_fd),sys.argv[3]],renderer._deadline())
"""
    parent=subprocess.Popen([sys.executable,'-c',parent_script,canonical(engine.config),child_script,str(marker)],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    encoder=None
    try:
        deadline=time.monotonic()+5
        while not marker.exists() and parent.poll() is None and time.monotonic()<deadline:time.sleep(.01)
        assert marker.exists()
        encoder=json.loads(marker.read_text())['pid']
        os.kill(parent.pid,signal.SIGKILL);parent.wait(timeout=2)
        renderer=MediaRenderer(engine.config)
        with pytest.raises(TimeoutError,match='media_lock_timeout'):
            with renderer._lock(time.monotonic()+.05):raise AssertionError('encoder still holds inherited descriptor')
    finally:
        if parent.poll() is None:parent.kill();parent.wait(timeout=2)
        if encoder is not None:
            try:os.killpg(encoder,signal.SIGKILL)
            except ProcessLookupError:pass
        renderer=MediaRenderer(engine.config)
        with renderer._lock(time.monotonic()+2):pass


def test_claim_between_hash_and_final_cleanup_preserves_asset(engine,clock,monkeypatch):
    from tiktok_clipping_cli import asset_retention as module
    _,job,asset,_,path=intent_fixture(engine,clock);obsolete(engine,job,failed=True)
    original=module.exact_file
    def reclaim(*args,**kwargs):
        result=original(*args,**kwargs)
        if kwargs.get('with_identity'):
            with engine.transaction() as db:
                db.execute("UPDATE jobs SET status='running',asset=?,lease_token='new worker',lease_until=? WHERE id=?",(canonical(asset),clock()+60,job['id']))
        return result
    monkeypatch.setattr(module,'exact_file',reclaim)
    assert prune_owned(engine)==0 and path.exists()
    with engine.transaction() as db:assert db.execute('SELECT cleaned_at FROM rendered_assets').fetchone()[0] is None


def test_atomic_final_cleanup_fences_job_claim_without_hashing_under_lock(engine,clock,monkeypatch):
    import sqlite3
    from tiktok_clipping_cli import asset_retention as module
    _,job,asset,_,path=intent_fixture(engine,clock);obsolete(engine,job,failed=True)
    original=module.unlink_checked
    def interleave(target,identity):
        with sqlite3.connect(engine.database,timeout=0) as other:
            with pytest.raises(sqlite3.OperationalError,match='locked'):
                other.execute("UPDATE jobs SET status='running',lease_token='new worker',lease_until=? WHERE id=?",(clock()+60,job['id']))
        return original(target,identity)
    monkeypatch.setattr(module,'unlink_checked',interleave)
    assert prune_owned(engine)==asset['bytes'] and not path.exists()


def test_hash_budget_exhaustion_preserves_large_asset(engine,clock,monkeypatch):
    from tiktok_clipping_cli import asset_retention as module
    _,job,asset,receipt,path=intent_fixture(engine,clock);obsolete(engine,job,failed=True)
    data=b'x'*(3<<20);path.write_bytes(data)
    asset.update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest());receipt['asset']=asset
    path.with_suffix('.json').write_text(canonical(receipt))
    engine.config['limits']['max_disk_bytes']=4<<20
    with engine.transaction() as db:db.execute('UPDATE rendered_assets SET asset=?,receipt=?,receipt_digest=?',(canonical(asset),canonical(receipt),module.digest(receipt)))
    elapsed=[0.0];original=hashlib.sha256
    class TimedHasher:
        def __init__(self,*args):self.value=original(*args)
        def update(self,chunk):self.value.update(chunk);elapsed[0]+=1
        def hexdigest(self):return self.value.hexdigest()
    monkeypatch.setattr(module.time,'monotonic',lambda:elapsed[0])
    monkeypatch.setattr(module.hashlib,'sha256',TimedHasher)
    assert prune_owned(engine)==0 and path.exists()
    with engine.transaction() as db:assert db.execute('SELECT cleanup_issue FROM rendered_assets').fetchone()[0]=='TimeoutError'


def test_owned_process_temp_is_preallocated_and_healthy_run_cleans_every_row(engine,clock):
    from tiktok_clipping_cli.media import MediaRenderer
    owner,job,_=owner_fixture(engine,clock)
    renderer=MediaRenderer(engine.config);renderer._render_ownership=owner
    renderer._disk=lambda *args:1<<30
    with renderer._lock(renderer._deadline()):
        output=renderer._run(['ffmpeg','-version'],renderer._deadline())
    assert b'ffmpeg version' in output
    with engine.transaction() as db:
        rows=db.execute('SELECT * FROM render_temporaries').fetchall()
        assert len(rows)==1 and rows[0]['kind']=='process' and rows[0]['directory_identity'] and rows[0]['cleaned_at']
        assert not rows[0]['descendants_unproven']
    assert not list(owner.root.glob('process-*'))


def test_crashed_empty_process_temp_reclaims_after_exact_parent_absence(engine,clock,monkeypatch):
    _,path=crashed_temp(engine,clock)
    (path/'clip.mp4').unlink()
    with engine.transaction() as db:db.execute("UPDATE render_temporaries SET kind='process'")
    monkeypatch.setattr('tiktok_clipping_cli.asset_retention.process_absent',lambda process:True)
    assert prune_owned(engine)==0 and not path.exists()
    with engine.transaction() as db:assert db.execute('SELECT cleaned_at FROM render_temporaries').fetchone()[0]


def test_unproven_directory_creation_is_not_adopted(engine,clock,monkeypatch):
    _,path=crashed_temp(engine,clock)
    with engine.transaction() as db:db.execute('UPDATE render_temporaries SET directory_identity=NULL')
    monkeypatch.setattr('tiktok_clipping_cli.asset_retention.process_absent',lambda process:True)
    assert prune_owned(engine)==0 and path.exists()
    with engine.transaction() as db:assert db.execute('SELECT cleanup_issue FROM render_temporaries').fetchone()[0]=='render_temporary_directory_ownership_unproven'


def test_same_edit_different_owned_job_has_distinct_destination(engine,clock,monkeypatch):
    from tiktok_clipping_cli.media import MediaRenderer
    owner,job,proposal=owner_fixture(engine,clock)
    proposal={**proposal,'start_seconds':0,'end_seconds':10,'style':'centered'}
    engine.config['baseline']['weights']={'centered':1}
    source=owner.root/'source.mp4';source.write_bytes(b'TEST source')
    renderer=MediaRenderer(engine.config)
    renderer.probe=lambda *args,**kwargs:{'duration_seconds':12 if Path(args[0])==source else 10,'audio_present':True,'width':720,'height':1280}
    renderer._decode=lambda *args:None;renderer._disk=lambda *args:1<<30
    def run(command,*args,**kwargs):
        if command[-1]=='-filters':return b' subtitles '
        Path(command[-1]).write_bytes(b'TEST actual simulated encoded bytes');return b''
    renderer._run=run
    captions=[{'start':0,'end':10,'text':'A complete sentence.'}]
    first=renderer.render_local(source,captions,proposal,'TEST',render_owner=owner.owner)
    second=renderer.render_local(source,captions,proposal,'TEST',render_owner={**owner.owner,'job_id':'different job'})
    assert first['path']!=second['path'] and first['sha256']==second['sha256']
    assert json.loads(Path(first['path']).with_suffix('.json').read_text())['render_owner']==owner.owner
    legacy=renderer.render_local(source,captions,proposal,'TEST')
    assert legacy['path'] not in {first['path'],second['path']}
    assert renderer.render_local(source,captions,proposal,'TEST')['path']==legacy['path']


def test_real_local_render_intent_precedes_rename_and_all_temps_reclaim(engine,clock,ffmpeg):
    from tiktok_clipping_cli.media import MediaRenderer
    from tiktok_clipping_cli.safety import digest
    _,job,proposal=owner_fixture(engine,clock)
    proposal={**proposal,'start_seconds':0,'end_seconds':10,'style':'centered'}
    engine.config['baseline']['weights']={'centered':1}
    with engine.transaction() as db:
        db.execute('UPDATE jobs SET proposal=?,proposal_digest=? WHERE id=?',(canonical(proposal),digest(proposal),job['id']))
        job=dict(db.execute('SELECT * FROM jobs WHERE id=?',(job['id'],)).fetchone())
    owner=RenderOwnership(engine.config,job,proposal,clock=clock)
    renderer=MediaRenderer(engine.config,ffmpeg=ffmpeg)
    source=renderer.root/'synthetic-source.mp4'
    renderer._run([renderer.ffmpeg,'-v','error','-nostdin','-f','lavfi','-i','color=c=blue:s=360x640:r=12:d=12',
        '-f','lavfi','-i','sine=frequency=330:duration=12','-shortest','-c:v','libx264','-threads','2',
        '-pix_fmt','yuv420p','-c:a','aac',str(source)],renderer._deadline())
    renderer._render_ownership=owner
    recorded=[];original=owner.intent
    def before_rename(asset,receipt):
        assert not Path(asset['path']).exists()
        original(asset,receipt)
        with engine.transaction() as db:
            assert json.loads(db.execute('SELECT receipt FROM rendered_assets').fetchone()[0])==receipt
        assert not Path(asset['path']).exists()
        recorded.append(asset)
    owner.intent=before_rename
    with renderer._lock(renderer._deadline()):
        asset=renderer.render_local(source,[{'start':0,'end':10,'text':'A real synthetic ownership test.'}],
            proposal,'TEST fixture only; never publish',render_owner=owner.owner)
    assert recorded==[asset] and Path(asset['path']).is_file()
    with engine.transaction() as db:
        temps=db.execute('SELECT * FROM render_temporaries').fetchall()
        assert temps and all(row['cleaned_at'] for row in temps)
        assert {row['kind'] for row in temps}=={'render','process'}
    obsolete(engine,job)
    assert prune_owned(engine)==asset['bytes']
    assert Path(asset['path']).with_suffix('.json').is_file()


def whisper_fixture(tmp_path,monkeypatch,*,wait=False):
    executable=tmp_path/'whisper'
    executable.write_text('#!'+sys.executable+'\nimport pathlib,tempfile,time,sys\n'
        "directory=pathlib.Path(tempfile.mkdtemp(prefix='whisper-cpp-'))\n"
        "stem=pathlib.Path(sys.argv[3]).stem\n"
        "(directory/(stem+'.16k.wav')).write_bytes(b'TEST exact normalized WAV')\n"
        "(directory/(stem+'.json')).write_text('{}')\n"+('time.sleep(30)\n' if wait else ''))
    executable.chmod(0o700)
    monkeypatch.setenv('PATH',str(tmp_path)+os.pathsep+os.environ['PATH'])
    return executable


def test_healthy_source_backed_whisper_temp_contract_reclaims_all_known_files(engine,clock,tmp_path,monkeypatch):
    from tiktok_clipping_cli.media import MediaRenderer
    owner,_,_=owner_fixture(engine,clock)
    whisper_fixture(tmp_path,monkeypatch)
    renderer=MediaRenderer(engine.config);renderer._render_ownership=owner
    with renderer._lock(renderer._deadline()):
        renderer._run(['whisper','transcripts','create',str(tmp_path/'cut-0.wav')],renderer._deadline())
    with engine.transaction() as db:
        row=db.execute('SELECT * FROM render_temporaries').fetchone()
        assert row['cleaned_at'] and not row['descendants_unproven']
        inventory=json.loads(row['inventory'])
        assert len(inventory)==3 and {Path(e['path']).name for e in inventory if 'sha256' in e}=={'cut-0.json','cut-0.16k.wav'}
        assert json.loads(row['child_groups'])[0]['process']['pid']>0
    assert not Path(row['path']).exists()


def test_exact_whisper_child_group_survives_parent_then_crash_temp_reclaims(engine,clock,tmp_path,monkeypatch):
    owner,job,proposal=owner_fixture(engine,clock)
    whisper_fixture(tmp_path,monkeypatch,wait=True)
    from tiktok_clipping_cli import asset_retention as module
    script='''import json,sys,time
from tiktok_clipping_cli.asset_retention import RenderOwnership
from tiktok_clipping_cli.media import MediaRenderer
config,job,proposal=json.loads(sys.argv[1])
owner=RenderOwnership(config,job,proposal,clock=lambda:job['lease_until']-1)
renderer=MediaRenderer(config);renderer._render_ownership=owner
with renderer._lock(renderer._deadline()):
 renderer._run(['whisper','transcripts','create',sys.argv[2]],renderer._deadline())
'''
    worker=subprocess.Popen([sys.executable,'-c',script,canonical([engine.config,job,proposal]),str(tmp_path/'cut-0.wav')],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    child=None
    try:
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            with engine.transaction() as db:row=db.execute('SELECT * FROM render_temporaries WHERE kind=\'process\'').fetchone()
            if row:
                groups=json.loads(row['child_groups'])
                if groups and groups[0]['process'] and list(Path(row['path']).glob('whisper-cpp-*/*.json')):
                    child=groups[0]['process']['pid'];break
            time.sleep(.02)
        assert child is not None
        worker.kill();worker.wait(timeout=3)
        obsolete(engine,job,failed=True)
        assert prune_owned(engine)==0 and Path(row['path']).exists()  # Live exact descendant group holds cleanup.
        os.killpg(child,signal.SIGKILL)
        # Orphan zombies are reaped by the host. A group remaining present is
        # deliberately held; no age-based process-absence inference is used.
        deadline=time.monotonic()+5
        while not module.child_groups_absent(groups) and time.monotonic()<deadline:time.sleep(.02)
        assert module.child_groups_absent(groups)
        assert prune_owned(engine)>0 and not Path(row['path']).exists()
        with engine.transaction() as db:assert db.execute('SELECT cleaned_at FROM render_temporaries').fetchone()[0]
    finally:
        if worker.poll() is None:worker.kill();worker.wait(timeout=3)
        if child is not None:
            try:os.killpg(child,signal.SIGKILL)
            except ProcessLookupError:pass


@pytest.mark.parametrize('change',['unknown_file','changed_directory','pending_group'])
def test_crashed_whisper_unknown_or_unregistered_resources_remain_held(engine,clock,monkeypatch,change):
    from tiktok_clipping_cli import asset_retention as module
    job,path=crashed_temp(engine,clock)
    (path/'clip.mp4').unlink()
    directory=path/'whisper-cpp-abcdefgh';directory.mkdir()
    (directory/'cut-0.16k.wav').write_bytes(b'TEST known')
    groups=[{'ticket':'TEST','stem':'cut-0','process':None if change=='pending_group' else {'pid':1234,'start_identity':'TEST'}}]
    with engine.transaction() as db:db.execute("UPDATE render_temporaries SET kind='process',child_groups=?",(canonical(groups),))
    monkeypatch.setattr(module,'process_absent',lambda identity:True)
    if change!='pending_group':monkeypatch.setattr(module,'child_groups_absent',lambda groups:True)
    if change=='unknown_file':(directory/'foreign.wav').write_bytes(b'unknown')
    elif change=='changed_directory':
        (directory/'cut-0.16k.wav').unlink();directory.rmdir()
        target=path.parent/'foreign-directory';target.mkdir();directory.symlink_to(target,target_is_directory=True)
    assert prune_owned(engine)==0 and path.exists()
    with engine.transaction() as db:assert db.execute('SELECT cleanup_issue FROM render_temporaries').fetchone()[0]


def test_whisper_nested_inventory_survives_partial_unlink_restart(engine,clock,monkeypatch):
    from tiktok_clipping_cli import asset_retention as module
    job,path=crashed_temp(engine,clock)
    (path/'clip.mp4').unlink()
    directory=path/'whisper-cpp-abcdefgh';directory.mkdir()
    (directory/'cut-0.16k.wav').write_bytes(b'TEST WAV');(directory/'cut-0.json').write_bytes(b'{}')
    groups=[{'ticket':'TEST','stem':'cut-0','process':{'pid':1234,'start_identity':'TEST'}}]
    with engine.transaction() as db:db.execute("UPDATE render_temporaries SET kind='process',child_groups=?",(canonical(groups),))
    monkeypatch.setattr(module,'process_absent',lambda identity:True)
    monkeypatch.setattr(module,'child_groups_absent',lambda groups:True)
    original=module.unlink_checked;calls=[]
    def interrupted(filename,identity):
        if calls:raise OSError('TEST crash after first owned file removed')
        original(filename,identity);calls.append(filename)
    monkeypatch.setattr(module,'unlink_checked',interrupted)
    assert prune_owned(engine)==0 and path.exists() and len(calls)==1
    with engine.transaction() as db:assert db.execute('SELECT inventory FROM render_temporaries').fetchone()[0]
    monkeypatch.setattr(module,'unlink_checked',original)
    assert prune_owned(engine)>0 and not path.exists()


def test_run_passes_original_lease_to_render_without_public_inspection_leak(engine,adapter,clock):
    envelope=claim(engine,clock)
    prepared=engine.apply(payload(envelope),execute=False)
    assert prepared['state']=='ready'
    assert 'lease_token' not in engine.get(envelope['job_id'])
    original=adapter.render
    seen=[]
    def render(job,proposal):
        owner=RenderOwnership(engine.config,job,proposal,clock=clock)
        owner.root.mkdir(exist_ok=True)
        with owner.temporary('render') as path:
            assert Path(path).is_dir()
            seen.append(job['lease_token'])
        return original(job,proposal)
    adapter.render=render
    result=engine.run(envelope['job_id'])
    assert result['state']=='published',result
    assert seen==[envelope['lease_token']]
    assert 'lease_token' not in engine.get(envelope['job_id'])


def test_adapter_job_refuses_reclaimed_lease(engine,clock):
    owner,job,proposal=owner_fixture(engine,clock)
    with engine.transaction() as db:
        db.execute("UPDATE jobs SET lease_token='reclaimed' WHERE id=?",(job['id'],))
    with pytest.raises(SafetyError,match='publication_worker_lease_changed'):
        engine._adapter_job(job['id'],job['lease_token'])
