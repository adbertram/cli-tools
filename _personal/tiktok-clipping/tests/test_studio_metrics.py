import copy
import json
import pytest

from conftest import iso
from tiktok_clipping_cli.engine import AdapterFailure, Engine
from tiktok_clipping_cli.live import LiveAdapter
from tiktok_clipping_cli.safety import SafetyError, canonical, timestamp
from tiktok_clipping_cli.studio_metrics import actor, normalize_batch


def publication(config, clock, identifier='123'):
    return {'publication_id':identifier,'publication_url':f'https://www.tiktok.com/@ata_clipper/video/{identifier}',
        'account_id':config['account']['account_id'],'handle':'ata_clipper','published_at':iso(clock()-3600),'provenance':'TEST owning receipt'}


def provider_result(config, clock, ids=('123',), *, more=False, missing=()):
    from tiktok_cli.studio_inventory import validate_request
    records=[]
    for identifier in ids:
        if identifier in missing:continue
        records.append({'id':identifier,'url':f'https://www.tiktok.com/@ata_clipper/video/{identifier}',
            'account_id':config['account']['account_id'],'author':'ata_clipper','profile':'clipper','observed_at':iso(clock()),
            'server_timestamp_ms':int(clock()*1000),'metrics':{'views':5,'likes':2,'comments':0,'shares':None,'favorites':0},'provenance':'TEST native Studio read'})
    checkpoint=None
    if more:
        checkpoint={'version':1,'actor':actor(config['account']),'request_digest':validate_request(list(ids),None,20,config['account']['account_id'])['digest'],
            'semantics_digest':'a'*64,'cursor':100,'found_ids':[i for i in ids if i not in missing]}
    return {'actor':actor(config['account']),'records':records,'unresolved_ids':list(missing),'unresolved_state':'unknown',
        'requested_complete':not missing,'provider_end':not more,'pages_read':1,'continuation':checkpoint,'semantics_digest':'a'*64,'provenance':'own_account_studio'}


def seed(engine, config, clock, identifier):
    p=publication(config,clock,identifier)
    with engine.transaction() as db:
        db.execute('INSERT INTO publications VALUES(?,?,?,?,?,?,?,?)',(identifier,'job-'+identifier,p['account_id'],'asset-'+identifier,'request-'+identifier,'published',canonical(p),1))
        db.execute('INSERT INTO metric_schedule(publication_id,next_check) VALUES(?,?)',(identifier,clock()))
    return p


def test_provider_measurement_time_and_unknown_fields_never_caller_clock(config,clock):
    result=provider_result(config,clock);result['records'][0]['server_timestamp_ms']-=2000
    out=normalize_batch(result,[publication(config,clock)],config['account'])['records'][0]
    assert out['measured_at']==iso(clock()-2) and out['observed_at']==iso(clock())
    assert out['revenue'] is None and out['watch_seconds'] is None and out['shares'] is None
    result['records'][0]['server_timestamp_ms']=None
    assert normalize_batch(result,[publication(config,clock)],config['account'])['records']==[]


@pytest.mark.parametrize('mutation',['actor','id','url','profile','future','duplicate','checkpoint'])
def test_mismatched_native_binding_is_refused(config,clock,mutation):
    result=provider_result(config,clock,more=True,missing=('123',))
    if mutation!='checkpoint':result=provider_result(config,clock)
    if mutation=='actor':result['actor']['account_id']='999'
    elif mutation=='id':result['records'][0]['id']='999'
    elif mutation=='url':result['records'][0]['url']='https://www.tiktok.com/@other/video/123'
    elif mutation=='profile':result['records'][0]['profile']='default'
    elif mutation=='future':result['records'][0]['server_timestamp_ms']+=1000
    elif mutation=='duplicate':result['records']*=2
    else:result['continuation']['request_digest']='f'*64
    with pytest.raises((SafetyError,ValueError)):normalize_batch(result,[publication(config,clock)],config['account'])


def test_one_owning_batch_call_includes_actor_preflight_and_preserves_long_transport_delay(config,clock):
    from tiktok_cli.client import ClientError
    calls=[]
    class SDK:
        def get_studio_videos(self, username, ids, **options):
            calls.append((username,ids,options));raise ClientError('SAFE',code='studio_transport_timeout',category='transient',status=0,retry_after_seconds=100000)
        def close(self):calls.append('close')
    adapter=LiveAdapter(config,studio_factory=SDK)
    with pytest.raises(AdapterFailure) as captured:adapter.metrics_batch([publication(config,clock)])
    assert calls[0][1]==['123'] and calls[0][2]['expected_account_id']==config['account']['account_id']
    assert calls[-1]=='close' and captured.value.status is None and captured.value.retry_after==100000 and captured.value.provider=='tiktok'


def test_restart_resumes_original_set_and_new_due_post_waits(config,clock,adapter):
    engine=Engine(config,adapter=adapter,clock=clock);engine.control('running')
    for identifier in ('123','456'):seed(engine,config,clock,identifier)
    calls=[]
    def batch(publications,cp,max_pages=20):
        calls.append(([p['publication_id'] for p in publications],cp))
        ids=calls[-1][0]
        if len(calls)==1:return normalize_batch(provider_result(config,clock,ids,more=True,missing=('456',)),publications,config['account'])
        if ids==['789']:return normalize_batch(provider_result(config,clock,ids),publications,config['account'])
        return normalize_batch(provider_result(config,clock,('456',)),publications,config['account'])
    adapter.metrics_batch=batch
    first=engine.prepare('metrics')['action_result'];assert first['snapshots']==1 and first['failures']==1
    seed(engine,config,clock,'789');clock.now+=config['limits']['retry_base_seconds']+1
    restarted=Engine(config,adapter=adapter,clock=clock)
    second=restarted.prepare('metrics')['action_result'];assert first['scan_id'] in second['scan_ids']
    assert calls[1][0]==['789'] and calls[1][1] is None
    assert calls[2][0]==['123','456'] and calls[2][1]['found_ids']==['123']
    with restarted.transaction() as db:
        assert db.execute("SELECT count(*) FROM snapshots WHERE publication_id='789'").fetchone()[0]==1
        assert db.execute("SELECT retired FROM metric_schedule WHERE publication_id='123'").fetchone()[0]==0


def test_missing_final_observation_does_not_retire(config,clock,adapter):
    engine=Engine(config,adapter=adapter,clock=clock);engine.control('running');seed(engine,config,clock,'123')
    clock.now+=config['limits']['metrics_max_age_seconds']+1
    adapter.metrics_batch=lambda ps,cp,max_pages=20:normalize_batch(provider_result(config,clock,missing=('123',)),ps,config['account'])
    assert engine.prepare('metrics')['action_result']['failures']==1
    with engine.transaction() as db:assert db.execute('SELECT retired FROM metric_schedule').fetchone()[0]==0
    clock.now+=config['limits']['retry_base_seconds']+1
    adapter.metrics_batch=lambda ps,cp,max_pages=20:normalize_batch(provider_result(config,clock),ps,config['account'])
    assert engine.prepare('metrics')['action_result']['snapshots']==1
    with engine.transaction() as db:assert db.execute('SELECT retired FROM metric_schedule').fetchone()[0]==1


def test_slow_reclaimed_worker_cannot_write_snapshot_or_checkpoint(config,clock,adapter):
    engine=Engine(config,adapter=adapter,clock=clock);engine.control('running');seed(engine,config,clock,'123')
    def batch(ps,cp,max_pages=20):
        with engine.transaction() as db:db.execute("UPDATE jobs SET lease_token='NEW' WHERE kind='metrics'")
        return normalize_batch(provider_result(config,clock),ps,config['account'])
    adapter.metrics_batch=batch
    engine.prepare('metrics')
    with engine.transaction() as db:
        assert db.execute('SELECT count(*) FROM snapshots').fetchone()[0]==0
        assert db.execute('SELECT checkpoint FROM metric_scans').fetchone()[0] is None


def test_expired_scan_cancels_and_later_due_publication_is_not_pinned(config,clock,adapter):
    config['limits']['metrics_batch_size']=1
    engine=Engine(config,adapter=adapter,clock=clock);engine.control('running');seed(engine,config,clock,'123')
    adapter.metrics_batch=lambda ps,cp,max_pages=20:normalize_batch(provider_result(config,clock,[p['publication_id'] for p in ps],more=True,missing=tuple(p['publication_id'] for p in ps)),ps,config['account'])
    first=engine.prepare('metrics')['action_result'];seed(engine,config,clock,'456')
    from tiktok_clipping_cli.studio_metrics import scan_lifetime
    clock.now+=scan_lifetime(config)+1
    second=engine.prepare('metrics')['action_result']
    assert first['scan_id']!=second['scan_id']
    with engine.transaction() as db:
        assert db.execute("SELECT state FROM metric_scans WHERE id=?",(first['scan_id'],)).fetchone()[0]=='canceled'
        assert json.loads(db.execute("SELECT publications FROM metric_scans WHERE id=?",(second['scan_id'],)).fetchone()[0])[0]['publication_id']=='456'


def test_provider_cooldown_survives_restart_and_new_due_ids(config,clock,adapter):
    engine=Engine(config,adapter=adapter,clock=clock);engine.control('running');seed(engine,config,clock,'123')
    calls=[]
    def reject(ps,cp,max_pages=20):
        calls.append(ps);raise AdapterFailure('rate_limit','SAFE',provider='tiktok',retry_after=100000)
    adapter.metrics_batch=reject
    engine.prepare('metrics');seed(engine,config,clock,'456');clock.now+=60
    restarted=Engine(config,adapter=adapter,clock=clock);restarted.prepare('metrics')
    assert len(calls)==1
    with restarted.transaction() as db:
        assert db.execute("SELECT until FROM circuits WHERE capability='provider:tiktok'").fetchone()[0]>=clock()+99940
        assert db.execute("SELECT next_at FROM metric_scans WHERE state='active'").fetchone()[0]>clock()


def test_invalid_resume_semantics_cancels_only_owned_scan(config,clock,adapter):
    engine=Engine(config,adapter=adapter,clock=clock);engine.control('running');seed(engine,config,clock,'123')
    adapter.metrics_batch=lambda ps,cp,max_pages=20:normalize_batch(provider_result(config,clock,more=True,missing=('123',)),ps,config['account'])
    first=engine.prepare('metrics')['action_result'];clock.now+=config['limits']['retry_base_seconds']+1
    def changed(ps,cp,max_pages=20):raise AdapterFailure('permanent','studio_contract_error',provider='tiktok')
    adapter.metrics_batch=changed;engine.prepare('metrics')
    with engine.transaction() as db:
        assert db.execute('SELECT state FROM metric_scans WHERE id=?',(first['scan_id'],)).fetchone()[0]=='canceled'
        assert db.execute('SELECT retired FROM metric_schedule').fetchone()[0]==0


def test_actual_owning_walker_result_normalizes_without_retimestamping(config,clock):
    from tiktok_cli.studio_inventory import batch_read,validate_request
    class Reader:
        identity=actor(config['account'])
        def semantics_digest(self):return 'a'*64
        def read_page(self,cursor):return provider_result(config,clock)['records'],False,0
    raw=batch_read(Reader(),validate_request(['123'],None,20,config['account']['account_id']))
    record=normalize_batch(raw,[publication(config,clock)],config['account'])['records'][0]
    assert record['observed_at']==raw['records'][0]['observed_at'] and record['measured_at']==iso(raw['records'][0]['server_timestamp_ms']/1000)


def test_thirty_six_thousand_post_account_reaches_oldest_due_target_at_scheduled_cadence(config,clock,adapter):
    from tiktok_cli.studio_inventory import batch_read,validate_request
    config['limits']['daily_runtime_seconds']=100000
    engine=Engine(config,adapter=adapter,clock=clock);engine.control('running');seed(engine,config,clock,'123')
    calls=[]
    class Reader:
        identity=actor(config['account'])
        def semantics_digest(self):return 'a'*64
        def read_page(self,cursor):
            # 720 native pages of 50 records. Requested old ID occurs at end.
            return (provider_result(config,clock)['records'] if cursor==719 else []),cursor<719,cursor+1
    def batch(ps,cp,max_pages=20):
        calls.append(cp)
        return normalize_batch(batch_read(Reader(),validate_request(['123'],cp,max_pages,config['account']['account_id'])),ps,config['account'])
    adapter.metrics_batch=batch
    scan_id=None
    for _ in range(40):
        result=engine.prepare('metrics')['action_result']
        scan_id=scan_id or result['scan_id'];assert result['scan_id']==scan_id
        if result['snapshots']==1:break
        clock.now+=1800
        engine=Engine(config,adapter=adapter,clock=clock)
    assert result['snapshots']==1 and 35<len(calls)<=40
    with engine.transaction() as db:assert db.execute('SELECT count(*) FROM snapshots').fetchone()[0]==1


@pytest.mark.parametrize('change',['publication','expiry','checkpoint'])
def test_final_commit_refuses_manifest_or_scan_change(config,clock,adapter,change):
    engine=Engine(config,adapter=adapter,clock=clock);engine.control('running');seed(engine,config,clock,'123')
    def batch(ps,cp,max_pages=20):
        with engine.transaction() as db:
            if change=='publication':
                altered={**ps[0],'publication_url':'https://www.tiktok.com/@other/video/123'}
                db.execute('UPDATE publications SET data=?',(canonical(altered),))
            elif change=='expiry':db.execute('UPDATE metric_scans SET expires_at=?',(clock()-1,))
            else:db.execute("UPDATE metric_scans SET checkpoint='{}'")
        return normalize_batch(provider_result(config,clock),ps,config['account'])
    adapter.metrics_batch=batch;engine.prepare('metrics')
    with engine.transaction() as db:
        assert db.execute('SELECT count(*) FROM snapshots').fetchone()[0]==0
        assert db.execute('SELECT last_check FROM metric_schedule').fetchone()[0] is None


def test_failure_after_lease_expiry_cannot_advance_schedule(config,clock,adapter):
    engine=Engine(config,adapter=adapter,clock=clock);engine.control('running');seed(engine,config,clock,'123')
    def batch(ps,cp,max_pages=20):
        clock.now+=config['limits']['lease_seconds']+1
        raise AdapterFailure('transient','TEST late read failure')
    adapter.metrics_batch=batch;engine.prepare('metrics')
    with engine.transaction() as db:assert db.execute('SELECT failures FROM metric_schedule').fetchone()[0]==0


def test_cached_native_record_is_not_counted_as_new_collection(config,clock,adapter):
    engine=Engine(config,adapter=adapter,clock=clock);engine.control('running');seed(engine,config,clock,'123')
    cached=normalize_batch(provider_result(config,clock),[publication(config,clock)],config['account'])
    adapter.metrics_batch=lambda ps,cp,max_pages=20:copy.deepcopy(cached)
    assert engine.prepare('metrics')['action_result']['snapshots']==1
    measured=clock();clock.now+=config['limits']['metrics_poll_seconds']+1
    assert engine.prepare('metrics')['action_result']['snapshots']==0
    with engine.transaction() as db:
        assert db.execute('SELECT count(*) FROM snapshots').fetchone()[0]==1
        assert db.execute('SELECT last_check FROM metric_schedule').fetchone()[0]==measured


def test_full_fifteen_day_population_preserves_cohorts_and_historical_progress(config,clock,adapter):
    """Modelled provider capacity, not a claim of thousands of live posts."""
    from tiktok_cli.studio_inventory import batch_read,validate_request
    config['limits'].update(metrics_batch_size=200,max_payload_bytes=1048576,
        metrics_poll_seconds=3600,metrics_max_age_seconds=90*86400,
        daily_posts=120,daily_runtime_seconds=86400)
    config['learning'].update(cohort_age_seconds=86400,cohort_tolerance_seconds=3600)
    engine=Engine(config,adapter=adapter,clock=clock);engine.control('running')
    start=clock();posts={};new_ids=[];round_pages=[];payload_max=0
    def add(identifier,published):
        p={**publication(config,clock,identifier),'published_at':iso(published)};posts[identifier]=p
        with engine.transaction() as db:
            db.execute('INSERT INTO publications VALUES(?,?,?,?,?,?,?,?)',(identifier,'job-'+identifier,p['account_id'],'asset-'+identifier,'request-'+identifier,'published',canonical(p),1))
            db.execute('INSERT INTO metric_schedule(publication_id,next_check) VALUES(?,?)',(identifier,clock()))
    for index in range(1800):add(str(200000+index),start-(1800-index)*720)
    add('123',start-365*86400)
    def batch(ps,cp,max_pages=20):
        nonlocal payload_max
        request_ids=[p['publication_id'] for p in ps]
        ordered=sorted((p for p in posts.values() if p['publication_id']!='123'),key=lambda p:p['published_at'],reverse=True)
        requested=set(request_ids)
        class Reader:
            identity=actor(config['account'])
            def semantics_digest(self):return 'a'*64
            def read_page(self,cursor):
                matches=[p for p in ordered[cursor*50:(cursor+1)*50] if p['publication_id'] in requested]
                if cursor==719 and '123' in requested:matches.append(posts['123'])
                raw=[]
                for p in matches:
                    r=provider_result(config,clock,(p['publication_id'],))['records'][0]
                    raw.append(r)
                return raw,cursor<719,cursor+1
        raw=batch_read(Reader(),validate_request(request_ids,cp,max_pages,config['account']['account_id']))
        result=normalize_batch(raw,ps,config['account'])
        round_pages[-1]+=raw['pages_read']
        request_bytes=len(canonical({'config':config,'method':'metrics_batch','args':[ps,cp,max_pages]}).encode())
        result_bytes=len(canonical({'result':result}).encode())
        payload_max=max(payload_max,request_bytes,result_bytes)
        assert request_bytes<=config['limits']['max_payload_bytes'] and result_bytes<=config['limits']['max_payload_bytes']
        return result
    adapter.metrics_batch=batch
    arrival=0
    for tick in range(90):
        wanted=(tick*120)//48
        while arrival<wanted:
            identifier=str(300000+arrival);add(identifier,start+arrival*720);new_ids.append(identifier);arrival+=1
        round_pages.append(0)
        engine.prepare('metrics')
        assert round_pages[-1]<=20
        clock.now+=1800
        engine=Engine(config,adapter=adapter,clock=clock)
    with engine.transaction() as db:
        assert db.execute("SELECT count(*) FROM snapshots WHERE publication_id='123'").fetchone()[0]>=1
        checked=0
        for identifier,p in posts.items():
            published=timestamp(p['published_at'])
            if published+86400+3600<start or published+86400-3600>clock()-1800:continue
            count=db.execute('SELECT count(*) FROM snapshots WHERE publication_id=? AND measured_at BETWEEN ? AND ?',(identifier,published+82800,published+90000)).fetchone()[0]
            assert count>=1,(identifier,published-start)
            checked+=1
        assert checked>=200
        for identifier in new_ids:
            first=db.execute('SELECT min(measured_at) FROM snapshots WHERE publication_id=?',(identifier,)).fetchone()[0]
            published=timestamp(posts[identifier]['published_at'])
            assert first is not None and first-published<=3600
    assert payload_max<1048576 and any(p>10 for p in round_pages)
    print(json.dumps({'modelled_active_population':1800,'posts_per_day':120,
        'scheduler_seconds':1800,'rounds':len(round_pages),'cohorts_within_24h_plus_minus_1h':checked,
        'new_arrivals_observed_within_1h':len(new_ids),'historical_inventory_pages':720,
        'max_native_pages_per_round':max(round_pages),'max_serialized_payload_bytes':payload_max}))


@pytest.mark.parametrize('reply',['cached','failed'])
def test_old_partial_scan_cannot_change_newer_independent_schedule(config,clock,adapter,reply):
    from tiktok_clipping_cli.studio_metrics import _run_scan
    engine=Engine(config,adapter=adapter,clock=clock);engine.control('running');seed(engine,config,clock,'123');seed(engine,config,clock,'124')
    old=clock()
    adapter.metrics_batch=lambda ps,cp,max_pages=20:normalize_batch(provider_result(config,clock,('123','124'),more=True,missing=('124',)),ps,config['account'])
    engine.prepare('metrics')
    with engine.transaction() as db:
        scan=dict(db.execute("SELECT * FROM metric_scans WHERE state='active'").fetchone())
    clock.now+=1800
    token='a'*32
    with engine.transaction() as db:
        job_id=engine._new_job(db,'metrics',{},status='ready')
        db.execute("UPDATE jobs SET status='running',lease_token=?,lease_until=? WHERE id=?",(token,clock()+120,job_id))
        job=engine._job(db,job_id)
        # A distinct fresh scan measured both IDs after this old scan started.
        db.execute('UPDATE metric_schedule SET last_check=?,next_check=?,failures=0',(clock(),clock()+3600))
        expected=[dict(r) for r in db.execute('SELECT * FROM metric_schedule ORDER BY publication_id')]
    def resumed(ps,cp,max_pages=20):
        if reply=='failed':raise AdapterFailure('transient','TEST old scan failure')
        raw=provider_result(config,clock,('123','124'))
        for r in raw['records']:r['server_timestamp_ms']=int(old*1000)
        return normalize_batch(raw,ps,config['account'])
    adapter.metrics_batch=resumed
    _run_scan(engine,job,token,[],lane=scan['lane'],max_pages=20)
    with engine.transaction() as db:
        assert [dict(r) for r in db.execute('SELECT * FROM metric_schedule ORDER BY publication_id')]==expected


def test_failure_schedule_cas_preserves_concurrent_cohort_progress(config,clock,adapter):
    engine=Engine(config,adapter=adapter,clock=clock);engine.control('running');seed(engine,config,clock,'123')
    expected={}
    def batch(ps,cp,max_pages=20):
        with engine.transaction() as db:
            db.execute('UPDATE metric_schedule SET next_check=?,last_check=?,failures=0',(clock()+3600,clock()))
            expected.update(dict(db.execute('SELECT * FROM metric_schedule').fetchone()))
        raise AdapterFailure('transient','TEST slow old read')
    adapter.metrics_batch=batch;engine.prepare('metrics')
    with engine.transaction() as db:
        assert dict(db.execute('SELECT * FROM metric_schedule').fetchone())==expected
