"""Dynamic admission trust, durable phases, fair windows and renewal."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import iso, source
from test_source_catalog import Providers, VIDEO, commission_provider, refresh
from test_outcome_learning import objective
from tiktok_clipping_cli import catalog_runtime as cr
from tiktok_clipping_cli.engine import Engine
from tiktok_clipping_cli.safety import SafetyError, canonical, digest, validate_source


def settings(config):
    config['limits'].update(work_timeout_seconds=600,max_disk_bytes=10*1073741824,lease_seconds=900)
    config['sources']=[]
    config['rewards_account']={'account_id':'user_TEST','username':'TEST','profile':'rewards','verified_at':config['account']['verified_at'],'provenance':'TEST identity'}
    config['source_discovery']={'google_profile':'test','page_budget':2,'campaign_budget':20,'brief_budget':20,'asset_budget':20,
        'refresh_seconds':120,'retry_base_seconds':2,'retry_max_seconds':60,'authorization_seconds':60,
        'refresh_timeout_seconds':500,'materialize_timeout_seconds':500,'max_source_bytes':1048576,'max_resolution':480,'submission_window_seconds':600}
    return config


@pytest.fixture
def prepared(config,clock,adapter):
    settings(config)
    engine=Engine(config,adapter=adapter,clock=clock);engine.control('running')
    catalog=cr.catalog_for(config,clock=clock);catalog.monotonic=lambda:0
    providers=Providers();commission_provider(providers)
    providers.assets[VIDEO]['duration']=1800
    refresh(catalog,providers)
    row=catalog.eligible(limit=5)['sources'][0];snapshot=catalog.validate_current(row['id'],row['current_version'])
    stage=Path(config['workspace'])/'catalog-media'/row['id'];stage.mkdir(parents=True,mode=0o700)
    path=stage/'source.mp4';path.write_bytes(b'TEST full source bytes; not live media')
    media={'video_id':'abcdefghijk','url':VIDEO,'file_path':str(path),'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'source_bytes':path.stat().st_size,'duration_seconds':1800,'width':854,'height':480,'audio_present':True,'provenance':{'kind':'TEST measured source'}}
    captions={'video_id':'abcdefghijk','duration_seconds':1800,'language':'en','segments':[{'start':i,'end':i+1,'text':'TEST words.'} for i in range(0,1800,2)],'observed_at':iso(clock()),
        'provenance':{'timebase':'original_full_video_seconds','raw_sha256':'a'*64,'kind':'TEST provider timed captions'}}
    with engine.transaction() as db:
        admission,approved,windows=cr.register_admission(db,config,snapshot,media,captions,experience_id='exp_TEST',now=clock())
    def record(ordinal=0):
        w=windows[ordinal]
        return {'source_id':row['id'],'media_id':'abcdefghijk','media_url':VIDEO,'duration_seconds':1800,
            'transcript':w['transcript'],'transcript_segments':w['transcript_segments'],'observed_at':iso(clock()),'provenance':'TEST exact timed window','categories':['music'],
            'catalog_admission':{'id':admission,'source_id':row['id'],'evidence_version':snapshot['evidence_version']},'source_window':cr.window_record(w)}
    return SimpleNamespace(config=config,engine=engine,catalog=catalog,providers=providers,snapshot=snapshot,media=media,captions=captions,windows=windows,record=record,source=approved)


def test_transaction_local_admission_and_injected_clock(prepared,clock):
    p=prepared
    with p.engine.transaction() as db:
        db.execute('DELETE FROM catalog_admissions')
        identifier,_,_=cr.register_admission(db,p.config,p.snapshot,p.media,p.captions,experience_id='exp_TEST',now=clock())
        record=p.record();record['catalog_admission']['id']=identifier
        assert validate_source(record,p.config,clock(),db=db)
    # Fixture's October clock is authoritative, regardless of actual wall time.
    assert p.engine._resolve_job_source(record)['valid_until']==clock()+60


def test_historical_policy_frozen_and_current_expiry_does_not_renew(prepared,clock,monkeypatch):
    p=prepared;record=p.record();old=p.engine._resolve_job_source(record,False)
    p.config['limits']['min_clip_seconds']=30
    p.config['source_discovery']['submission_window_seconds']=1200
    import whop_cli.submission_operations as sdk
    monkeypatch.setattr(sdk,'PUBLICATION_MAX_AGE_SECONDS',2400)
    assert p.engine._resolve_job_source(record,False)==old
    clock.now+=61
    with pytest.raises(SafetyError,match='catalog_admission_expired'):p.engine._resolve_job_source(record)
    assert p.engine._resolve_job_source(record,False)==old


@pytest.mark.parametrize('field,value',[('media_id','lmnopqrstuv'),('transcript','TEST altered'),('source_window',{'id':'f'*64})])
def test_trusted_admission_rejects_changed_record(prepared,field,value):
    record=prepared.record();record[field]=value
    with pytest.raises(SafetyError):prepared.engine._resolve_job_source(record)


def test_provider_binding_changed_is_refused(prepared):
    prepared.config['rewards_account']['account_id']='user_DIFFERENT'
    with pytest.raises(SafetyError,match='provider_binding_changed'):prepared.engine._resolve_job_source(prepared.record())


def test_fair_cursor_commits_with_job_and_retry_retains_window(prepared,clock):
    p=prepared;result=p.engine.ingest(p.record(0))
    with p.engine.transaction() as db:
        assert db.execute('SELECT next_ordinal FROM catalog_window_cursors').fetchone()[0]==1
        job=p.engine._job(db,result['job_id']);p.engine._retire_source_job(db,job,'TEST prepublication failure')
    # The next window remains the same actual video and has a new job.
    second=p.engine.ingest(p.record(1));assert not second['deduplicated']
    with p.engine.transaction() as db:
        assert db.execute('SELECT next_ordinal FROM catalog_window_cursors').fetchone()[0]==2
        assert len({r[0] for r in db.execute('SELECT media_id FROM source_jobs')})==1
    assert p.engine.ingest(p.record(2))['deduplicated']


def test_renewed_evidence_after_expired_prepublic_job_preserves_old_journal(prepared,clock):
    p=prepared;first=p.engine.ingest(p.record())
    old=p.engine.get(first['job_id'])
    clock.now+=61
    with p.engine.transaction() as db:p.engine._retire_source_job(db,p.engine._job(db,first['job_id']),'catalog_admission_expired')
    p.snapshot=p.catalog.validate_current(p.snapshot['source_id'],p.snapshot['evidence_version'])
    with p.engine.transaction() as db:
        new_id,_,windows=cr.register_admission(db,p.config,p.snapshot,p.media,p.captions,experience_id='exp_TEST',now=clock())
    record=p.record(1);record['observed_at']=iso(clock());record['catalog_admission']['id']=new_id
    second=p.engine.ingest(record)
    assert second['job_id']!=first['job_id'] and not second['deduplicated']
    assert p.engine.get(first['job_id'])['input']==old['input']


def test_stale_candidate_does_not_starve_fresh_candidate(config,adapter,clock,monkeypatch):
    from test_outcome_engine import configured
    current=configured(config,adapter,clock)
    stale=current.ingest(source(clock,'stale'))['job_id'];fresh=current.ingest(source(clock,'fresh'))['job_id']
    original=current._resolve_job_source
    def resolve(record,require_current=True,db=None):
        if record['media_id']=='stale':raise SafetyError('catalog_current_permission_changed')
        return original(record,require_current,db)
    monkeypatch.setattr(current,'_resolve_job_source',resolve)
    with current.transaction() as db:
        rows=db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at,id").fetchall()
        selected,_=current._select_clip_candidates(db,rows)
        assert selected['id']==fresh and current._job(db,stale)['status']=='failed'


def test_restart_after_completed_media_never_downloads_again(prepared,clock,monkeypatch):
    p=prepared
    with p.engine.transaction() as db:db.execute('INSERT INTO catalog_materializations(source_id,evidence_version,phase,stage,media,captions) VALUES(?,?,?,?,?,?)',(p.snapshot['source_id'],p.snapshot['evidence_version'],'captions',str(Path(p.media['file_path']).parent),canonical(p.media),None))
    sdk=SimpleNamespace(acquire_source_media=lambda *a,**k:pytest.fail('completed media must be reused'),read_source_transcript=lambda *a,**k:p.captions)
    from tiktok_clipping_cli.media import MediaRenderer
    media=MediaRenderer(p.config);monkeypatch.setattr(media,'probe',lambda *a,**k:{'duration_seconds':1800,'audio_present':True})
    d=cr.CatalogDiscovery(p.config,media,providers=p.providers,youtube=sdk,clock=clock)
    assert d.discover(d.monotonic()+120)==[]
    restarted=cr.CatalogDiscovery(p.config,media,providers=p.providers,youtube=sdk,clock=clock)
    records=restarted.discover(restarted.monotonic()+120)
    assert len(records)==1 and records[0]['catalog_admission']['evidence_version']==p.snapshot['evidence_version']
    assert p.engine.ingest(records[0])['deduplicated'] is False


def test_same_failed_version_window_backoff_and_published_quota_preserved(prepared,clock):
    p=prepared;job=p.engine.ingest(p.record())['job_id']
    with p.engine.transaction() as db:
        p.engine._retire_source_job(db,p.engine._job(db,job),'TEST failure')
        db.execute('UPDATE catalog_window_cursors SET next_ordinal=0')
    assert p.engine.ingest(p.record())['reason']=='source_window_backoff'
    clock.now+=3
    with p.engine.transaction() as db:db.execute('UPDATE catalog_window_cursors SET next_ordinal=0')
    fresh=p.engine.ingest(p.record());assert not fresh['deduplicated']
    with p.engine.transaction() as db:
        db.execute("UPDATE jobs SET status='published' WHERE id=?",(fresh['job_id'],))
    p.config['limits']['max_clips_per_source']=1
    assert p.engine.ingest(p.record(1))['exhausted']


def test_whole_model_prompt_includes_original_range_rights_and_learning(prepared):
    p=prepared;p.config['learning']['outcome_policy']={'objectives':[objective()],'baseline_share':.1}
    # Install optional policy before the new Engine boot, preserving admitted evidence.
    current=Engine(p.config,adapter=p.engine.adapter,clock=p.engine.clock)
    current.ingest(p.record());envelope=current.prepare('clip')
    assert envelope['ready'] and len(envelope['prompt'].encode())<=65536
    assert 'source_window' in envelope['prompt'] and 'outcome_selection' in envelope['input']
    assert 'embedded_original' not in envelope['input']['transcript'] # no invented spoken text
    assert current._resolve_job_source(envelope['input'])['source']['publication_policy']['schema_version']==2


def test_current_compiler_revocation_does_not_rewrite_historical_rights(prepared,monkeypatch):
    from tiktok_clipping_cli import source_catalog as sc
    monkeypatch.delitem(sc.COMPILERS,'supplied-av-episode-commission-v1')
    with pytest.raises(SafetyError,match='compiler_revoked'):prepared.engine._resolve_job_source(prepared.record())
    assert prepared.engine._resolve_job_source(prepared.record(),False)['source']==prepared.source


def test_outer_discovery_deadline_includes_startup_and_reserves_cleanup(config,monkeypatch):
    from tiktok_clipping_cli import adapters
    settings(config);ticks=SimpleNamespace(now=100.)
    monkeypatch.setattr(adapters.time,'monotonic',lambda:ticks.now)
    captured={}
    class Process:
        returncode=0
        def __init__(self,*args,**kwargs):
            self.output=kwargs['stdout'];ticks.now+=7 # actual child startup consumes parent budget
        def communicate(self,message,timeout):
            captured.update(json.loads(message),wait_timeout=timeout)
            self.output.write(b'{"result":[]}')
    monkeypatch.setattr(adapters.subprocess,'Popen',Process)
    client=adapters.ExternalAdapter(config);client.timeout=40
    assert client.discover(None)==[]
    assert captured['operation_deadline']==140-cr.DISCOVERY_OUTER_CLEANUP_SECONDS
    assert captured['wait_timeout']==33
    assert 140-captured['operation_deadline']>=10.75


def test_insufficient_discovery_headroom_never_launches(config,monkeypatch):
    from tiktok_clipping_cli import adapters
    from tiktok_clipping_cli.engine import AdapterFailure
    settings(config);client=adapters.ExternalAdapter(config);client.timeout=20
    monkeypatch.setattr(adapters.subprocess,'Popen',lambda *a,**k:pytest.fail('insufficient child cleanup budget'))
    with pytest.raises(AdapterFailure,match='startup_headroom'):client.discover(None)


def test_exhausted_window_wrap_skips_durably_without_consuming_new_job(prepared,clock):
    p=prepared;job=p.engine.ingest(p.record())['job_id']
    with p.engine.transaction() as db:
        p.engine._retire_source_job(db,p.engine._job(db,job),'TEST failure')
        db.execute('UPDATE jobs SET attempts=? WHERE id=?',(p.config['limits']['max_attempts'],job))
        db.execute('UPDATE catalog_window_cursors SET next_ordinal=0')
    assert p.engine.ingest(p.record())['reason']=='source_window_retry_exhausted'
    with p.engine.transaction() as db:
        assert db.execute('SELECT count(*) FROM jobs').fetchone()[0]==1
        assert db.execute('SELECT next_ordinal FROM catalog_window_cursors').fetchone()[0]==1
    assert not p.engine.ingest(p.record(1))['deduplicated']


def test_owned_cache_eviction_preserves_active_dependencies_and_compact_receipts(prepared,clock,monkeypatch):
    p=prepared
    from tiktok_clipping_cli.media import MediaRenderer
    media=MediaRenderer(p.config);monkeypatch.setattr(media,'probe',lambda *a,**k:{'duration_seconds':1800,'audio_present':True})
    d=cr.CatalogDiscovery(p.config,media,providers=p.providers,youtube=SimpleNamespace(),clock=clock)
    # Multiple completed caches are exact owned ledger entries, never glob guesses.
    with p.engine.transaction() as db:
        for i in range(5):
            stage=Path(p.config['workspace'])/'catalog-media'/('cache'+str(i));stage.mkdir(mode=0o700)
            path=stage/'source.mp4';path.write_bytes(b'cache'+bytes([i]))
            receipt=p.media|{'file_path':str(path),'source_bytes':6,'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            db.execute('INSERT INTO catalog_materializations(source_id,evidence_version,phase,stage,media,captions) VALUES(?,?,?,?,?,?)',('cache'+str(i),'v','ready',str(stage),canonical(receipt),canonical(p.captions)))
        job=p.engine._new_job(db,'clip',{'source_id':'cache0'})
        db.execute('INSERT INTO source_jobs VALUES(?,?,?,?)',('cache0','abcdefghijk',job,'TEST key'))
    import tiktok_clipping_cli.safety as safety
    monkeypatch.setattr(safety,'write_allowance',lambda *a,**k:0)
    with media._lock(d.monotonic()+120):d._evict_cache('none',100,d.monotonic()+120)
    assert Path(p.config['workspace'],'catalog-media','cache0','source.mp4').is_file()
    assert all(not Path(p.config['workspace'],'catalog-media','cache'+str(i),'source.mp4').exists() for i in range(1,5))
    with p.engine.transaction() as db:
        rows=db.execute("SELECT * FROM catalog_materializations WHERE phase='evicted'").fetchall()
        assert len(rows)==4 and all(json.loads(row['media'])['source_sha256'] for row in rows)


def test_restart_before_media_phase_commit_uses_owning_recovery(prepared,clock,monkeypatch):
    p=prepared;stage=Path(p.media['file_path']).parent
    stage.with_name(stage.name+'.owner.json').write_text('TEST owning SDK marker')
    with p.engine.transaction() as db:db.execute('INSERT INTO catalog_materializations(source_id,evidence_version,phase,stage) VALUES(?,?,?,?)',(p.snapshot['source_id'],p.snapshot['evidence_version'],'media',str(stage)))
    calls=[]
    sdk=SimpleNamespace(acquire_source_media=lambda *a,**k:pytest.fail('completed owned bytes must not download again'),recover_source_media=lambda *a,**k:(calls.append(k) or {'state':'complete','media':p.media}))
    from tiktok_clipping_cli.media import MediaRenderer
    d=cr.CatalogDiscovery(p.config,MediaRenderer(p.config),providers=p.providers,youtube=sdk,clock=clock)
    assert d.discover(d.monotonic()+120)==[]
    with p.engine.transaction() as db:
        row=db.execute('SELECT * FROM catalog_materializations').fetchone()
        assert row['phase']=='captions' and json.loads(row['media'])==p.media
    assert len(calls)==1


def test_eviction_hash_outside_transaction_fences_interleaved_ingest(prepared,clock,monkeypatch):
    p=prepared;stage=Path(p.media['file_path']).parent
    with p.engine.transaction() as db:db.execute('INSERT INTO catalog_materializations(source_id,evidence_version,phase,stage,media,captions) VALUES(?,?,?,?,?,?)',(p.snapshot['source_id'],p.snapshot['evidence_version'],'ready',str(stage),canonical(p.media),canonical(p.captions)))
    from tiktok_clipping_cli.media import MediaRenderer
    media=MediaRenderer(p.config);d=cr.CatalogDiscovery(p.config,media,providers=p.providers,youtube=SimpleNamespace(),clock=clock)
    def verified(receipt,deadline):
        # Independent writer succeeds while hashing, so no long SQLite lock.
        with p.engine.transaction() as db:db.execute("INSERT OR REPLACE INTO settings VALUES('TEST_writer','ok')")
        with pytest.raises(SafetyError,match='cache_not_ready'):p.engine.ingest(p.record())
        return receipt
    monkeypatch.setattr(d,'_verified_media',verified)
    import tiktok_clipping_cli.safety as safety
    monkeypatch.setattr(safety,'write_allowance',lambda *a,**k:0)
    with media._lock(d.monotonic()+120):d._evict_cache(None,100,d.monotonic()+120)
    assert not Path(p.media['file_path']).exists()
    with p.engine.transaction() as db:assert db.execute('SELECT count(*) FROM jobs').fetchone()[0]==0


def test_cache_replacement_during_probe_never_deleted(prepared,clock,monkeypatch):
    p=prepared;path=Path(p.media['file_path']);stage=path.parent
    with p.engine.transaction() as db:db.execute('INSERT INTO catalog_materializations(source_id,evidence_version,phase,stage,media,captions) VALUES(?,?,?,?,?,?)',(p.snapshot['source_id'],p.snapshot['evidence_version'],'ready',str(stage),canonical(p.media),canonical(p.captions)))
    from tiktok_clipping_cli.media import MediaRenderer
    media=MediaRenderer(p.config);d=cr.CatalogDiscovery(p.config,media,providers=p.providers,youtube=SimpleNamespace(),clock=clock)
    replacement=b'TEST replacement during probe'
    def probe(*args,**kwargs):
        new=stage/'replacement';new.write_bytes(replacement);new.replace(path)
        return {'duration_seconds':1800,'audio_present':True}
    monkeypatch.setattr(media,'probe',probe)
    import tiktok_clipping_cli.safety as safety
    monkeypatch.setattr(safety,'write_allowance',lambda *a,**k:0)
    with media._lock(d.monotonic()+120):
        with pytest.raises(SafetyError,match='changed_during_verification'):d._evict_cache(None,100,d.monotonic()+120)
    assert path.read_bytes()==replacement
    with p.engine.transaction() as db:assert db.execute('SELECT phase FROM catalog_materializations').fetchone()[0]=='evicting'
