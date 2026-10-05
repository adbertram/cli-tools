"""Trusted catalog admissions separate from global configuration versions."""
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
import time

from .safety import SafetyError, canonical, digest, keys, number, string, timestamp
from .source_catalog import SourceCatalog
from .source_windows import build_windows, window_record

# Existing owning Whop cleanup reserve (10.75s) plus 0.75s worker receipt exit.
DISCOVERY_OUTER_CLEANUP_SECONDS = 11.5

SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog_admissions(
 id TEXT PRIMARY KEY,source_id TEXT NOT NULL,evidence_version TEXT NOT NULL,
 valid_until REAL NOT NULL,source TEXT NOT NULL,media TEXT NOT NULL,captions TEXT NOT NULL,
 windows TEXT NOT NULL,created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS catalog_admission_lookup ON catalog_admissions(source_id,evidence_version,created_at DESC);
CREATE TABLE IF NOT EXISTS catalog_window_cursors(
 source_id TEXT NOT NULL,caption_sha TEXT NOT NULL,next_ordinal INTEGER NOT NULL,
 PRIMARY KEY(source_id,caption_sha));
CREATE TABLE IF NOT EXISTS catalog_materializations(
 source_id TEXT PRIMARY KEY,evidence_version TEXT NOT NULL,phase TEXT NOT NULL,
 stage TEXT,media TEXT,captions TEXT,next_at REAL NOT NULL DEFAULT 0,failures INTEGER NOT NULL DEFAULT 0,error TEXT);
"""


def catalog_for(config, *, clock=time.time):
    return SourceCatalog(Path(config['workspace'])/'catalog'/'catalog.sqlite3', clock=clock)


def materialized_source(snapshot, media, *, experience_id, valid_until, minimum_clip_seconds, submission_window_seconds, provider_window_seconds=None):
    """Only this code-owned compiler output maps authoritative source rights."""
    permission = snapshot['permission']
    if snapshot['compiler_version']!='supplied-av-episode-commission-v1' or permission is None:
        raise SafetyError('catalog_materializer_compiler_unsupported')
    if permission.get('reuse_scope')!='extract_supplied_audiovisual_episode' or permission.get('audio_scope')!='embedded_original_asset_only' or permission.get('external_audio') is not False or permission.get('on_video_ad_disclosure_required') is not False:
        raise SafetyError('catalog_materializer_permission_unsupported')
    asset = snapshot['evidence']['asset']
    if media['video_id']!=asset['id'] or media['url']!=permission['video_url'] or abs(media['duration_seconds']-asset['duration'])>1 or media['audio_present'] is not True:
        raise SafetyError('catalog_materializer_full_source_mismatch')
    number(valid_until,1);number(minimum_clip_seconds,1,60)
    evidence = {'kind':'catalog_commission','catalog_source_id':snapshot['source_id'],
        'evidence_version':snapshot['evidence_version'],'facts_version':snapshot['facts_version'],
        'compiler_version':snapshot['compiler_version'],'campaign_id':permission['campaign_id'],
        'experience_id':experience_id,'campaign_evidence_digest':digest(snapshot['evidence']['campaign'])}
    # Presentation and minimum are explicit operating choices. The provider
    # commission grants this exact audiovisual asset, never external music.
    from whop_cli.submission_operations import PUBLICATION_MAX_AGE_SECONDS
    provider_window_seconds=PUBLICATION_MAX_AGE_SECONDS if provider_window_seconds is None else provider_window_seconds
    number(provider_window_seconds,1,86400,integer=True)
    deadline_seconds=min(provider_window_seconds,submission_window_seconds)
    number(deadline_seconds,1,86400,integer=True)
    labels = [permission['show_attribution'],permission['creator_attribution'],permission['publisher_attribution']]
    labels = list(dict.fromkeys(labels))
    policy = {'schema_version':2,'campaign_id':permission['campaign_id'],'commission_evidence':evidence,
        'source_url':permission['video_url'],'source_sha256':media['source_sha256'],'source_bytes':media['source_bytes'],
        'video_reuse_allowed':True,'original_audio_reuse_allowed':True,'external_audio_allowed':False,
        'full_source_repost_allowed':False,'minimum_clip_seconds':minimum_clip_seconds,
        'required_caption_tokens':labels,'required_on_screen_text':[permission['show_attribution']+' / '+permission['creator_attribution']], 'clip_rules':[]}
    source = {'id':snapshot['source_id'],'feed':permission['video_url'],'allowed_hosts':['www.youtube.com'],
        'reuse_evidence':'owning_whop_commission:'+evidence['campaign_evidence_digest'],
        'campaign':{'id':permission['campaign_id'],'enabled':True,'categories':['music'],
            'minimum_followers':0,'expires_at':datetime.fromtimestamp(valid_until,timezone.utc).isoformat(),
            'provenance':canonical({'kind':'owning_whop_commission','evidence':evidence}),
            'platform':'whop_content_rewards','submission_window_seconds':deadline_seconds},
        'publication_policy':policy,'commission_evidence':evidence,
        'ranking_regime_digest':permission['ranking_regime_digest'],
        'editorial_requirements':permission['editorial_requirement'],
        'operating_policy':{'minimum_clip_seconds':{'seconds':minimum_clip_seconds,'authority':'configured_operating_minimum'},
                            'categories':{'values':['music'],'authority':'supported_commission_editorial_selection_bucket'},
                            'audience':{'minimum_followers':0,'authority':'compiler_verified_editorial_only_no_numeric_audience_requirement'},
                            'submission_deadline':{'provider_seconds':provider_window_seconds,'operating_seconds':submission_window_seconds,'authority':'owning_whop_30_minute_publication_contract'},
                            'attribution_presentation':'show_creator_on_video_and_full_caption',
                            'eligibility_scope':'candidate_selection_only','fresh_publish_readiness_required':True}}
    from .rights import validate_policy
    validate_policy(policy,source)
    return source


def register_admission(db, config, snapshot, media, captions, *, experience_id, now):
    """Persist full immutable measurements; caller already verified actual bytes."""
    if captions['video_id']!=media['video_id'] or abs(captions['duration_seconds']-media['duration_seconds'])>1:
        raise SafetyError('catalog_caption_media_identity_mismatch')
    if captions['provenance']['timebase']!='original_full_video_seconds':raise SafetyError('catalog_caption_timebase_invalid')
    segments=[{'start_seconds':c['start'],'end_seconds':c['end'],'text':c['text']} for c in captions['segments']]
    windows=build_windows(segments,media['duration_seconds'])
    until=min(snapshot['fresh_until'],now+config['source_discovery']['authorization_seconds'])
    if until<=now:raise SafetyError('catalog_admission_expired')
    source=materialized_source(snapshot,media,experience_id=experience_id,valid_until=until,minimum_clip_seconds=config['limits']['min_clip_seconds'],submission_window_seconds=config['source_discovery']['submission_window_seconds'])
    identity={'source':source,'media':media,'caption_provenance':captions['provenance'],'windows':[window_record(w) for w in windows]}
    identifier=digest(identity)
    db.execute('INSERT OR IGNORE INTO catalog_admissions VALUES(?,?,?,?,?,?,?,?,?)',
        (identifier,snapshot['source_id'],snapshot['evidence_version'],until,canonical(source),canonical(media),canonical(captions),canonical(windows),now))
    return identifier,source,windows


def resolve_job_source(config, record, *, require_current, now=None, db=None, catalog=None):
    """Historical policy never renews; current validation can only shorten it."""
    import json
    now=time.time() if now is None else now
    reference=record.get('catalog_admission')
    if reference is None:
        if 'source_window' in record:raise SafetyError('catalog_window_requires_trusted_admission')
        source=next((s for s in config['sources'] if s['id']==record.get('source_id')),None)
        if source is None:raise SafetyError('source_not_allowlisted')
        return {'source':source,'valid_until':timestamp(source['campaign']['expires_at']),'evidence_version':None}
    if not config.get('source_discovery'):raise SafetyError('catalog_discovery_not_configured')
    keys(reference,{'id','source_id','evidence_version'})
    for value in reference.values():
        if type(value) is not str or not re.fullmatch('[a-f0-9]{64}',value):raise SafetyError('catalog_admission_reference_invalid')
    if reference['source_id']!=record['source_id']:raise SafetyError('catalog_admission_source_changed')
    owns=db is None
    if owns:
        db=sqlite3.connect(Path(config['database']).as_uri()+'?mode=ro',uri=True,timeout=2);db.row_factory=sqlite3.Row
    try:
        row=db.execute('SELECT * FROM catalog_admissions WHERE id=?',(reference['id'],)).fetchone()
        cache=db.execute('SELECT phase FROM catalog_materializations WHERE source_id=?',(reference['source_id'],)).fetchone()
        if require_current and cache is not None and cache['phase']!='ready':raise SafetyError('catalog_source_cache_not_ready')
    finally:
        if owns:db.close()
    if row is None or row['source_id']!=reference['source_id'] or row['evidence_version']!=reference['evidence_version']:
        raise SafetyError('catalog_admission_missing_or_changed')
    source=json.loads(row['source']);media=json.loads(row['media']);windows=json.loads(row['windows'])
    catalog=catalog or catalog_for(config,clock=lambda:now)
    binding=catalog.provider_binding()
    actor=config['rewards_account']
    if not binding or any(binding.get(k)!=v for k,v in {'whop_profile':actor['profile'],'whop_account_id':actor['account_id'],'google_profile':config['source_discovery']['google_profile']}.items()) or binding['experience'].rstrip('/').split('/')[-1]!=source['commission_evidence']['experience_id']:
        raise SafetyError('catalog_admission_provider_binding_changed')
    snapshot=catalog.validate_current(row['source_id'],row['evidence_version']) if require_current else catalog.get_version(row['source_id'],row['evidence_version'])
    expected=materialized_source(snapshot,media,experience_id=source['commission_evidence']['experience_id'],valid_until=row['valid_until'],minimum_clip_seconds=source['operating_policy']['minimum_clip_seconds']['seconds'],submission_window_seconds=source['operating_policy']['submission_deadline']['operating_seconds'],provider_window_seconds=source['operating_policy']['submission_deadline']['provider_seconds'])
    if expected!=source:raise SafetyError('catalog_admission_policy_changed')
    if record.get('media_id')!=media['video_id'] or record.get('media_url')!=media['url']:
        raise SafetyError('catalog_admission_media_changed')
    match=next((w for w in windows if window_record(w)==record.get('source_window')),None)
    if match is None or any(record.get(k)!=match[k] for k in ('transcript','transcript_segments')):
        raise SafetyError('catalog_admission_window_changed')
    until=min(row['valid_until'],snapshot['fresh_until']) if require_current else row['valid_until']
    if require_current and until<=now:raise SafetyError('catalog_admission_expired')
    return {'source':source,'valid_until':until,'evidence_version':row['evidence_version']}


class CatalogDiscovery:
    """Durable refresh, full-media, captions, and admission phases, one per call."""
    def __init__(self, config, media, *, providers=None, youtube=None, clock=time.time, monotonic=time.monotonic):
        from .source_catalog import SDKProviders
        from youtube_cli.client import YoutubeClient
        self.config,self.media,self.clock,self.monotonic=config,media,clock,monotonic
        actor=config['rewards_account'];settings=config['source_discovery']
        self.providers=providers or SDKProviders(whop_profile=actor['profile'],whop_account_id=actor['account_id'],google_profile=settings['google_profile'])
        self.youtube=youtube or YoutubeClient
        self.catalog=catalog_for(config,clock=clock)

    def _db(self):
        db=sqlite3.connect(self.config['database'],timeout=2);db.row_factory=sqlite3.Row
        return db

    def _timeout(self, deadline, maximum):
        budget=min(maximum,deadline-self.monotonic())
        if budget<=15:raise TimeoutError('catalog_materialization_deadline_insufficient')
        return budget

    def _verified_media(self, receipt, deadline):
        from youtube_cli.source_media import _regular_digest
        path=self.media._path(receipt['file_path'])
        sha,size=_regular_digest(path,self.config['source_discovery']['max_source_bytes'],deadline)
        if sha!=receipt['source_sha256'] or size!=receipt['source_bytes']:
            raise SafetyError('catalog_cached_media_changed')
        measured=self.media.probe(path,deadline)
        if not measured['audio_present'] or abs(measured['duration_seconds']-receipt['duration_seconds'])>1:
            raise SafetyError('catalog_cached_media_probe_changed')
        return receipt

    @staticmethod
    def _cache_busy(db,source_id):
        return db.execute("SELECT 1 FROM source_jobs s JOIN jobs j ON j.id=s.job_id WHERE s.source_id=? AND (j.status NOT IN ('published','done','failed') OR EXISTS(SELECT 1 FROM publications p WHERE p.job_id=j.id AND p.state!='published') OR (j.status='failed' AND EXISTS(SELECT 1 FROM events e WHERE e.job_id=j.id AND e.event='upload_started'))) LIMIT 1",(source_id,)).fetchone() is not None

    def _evict_cache(self, exclude, reserve, deadline):
        """Intent fences new claims; hash outside SQLite, final CAS+unlink inside."""
        import json
        from .safety import write_allowance
        from youtube_cli.source_media_recovery import read,write,process_identity
        from cli_tools_shared.bounded_read import _group_has_no_live_members
        with self._db() as db:
            rows=db.execute("SELECT * FROM catalog_materializations WHERE (? IS NULL OR source_id!=?) AND phase IN ('ready','captions','evicting') ORDER BY next_at,source_id",(exclude,exclude)).fetchall()
        for row in rows:
            if row['phase']!='evicting' and write_allowance(self.config['workspace'],self.config['limits']['max_disk_bytes'])>=reserve:return
            if self.monotonic()>=deadline:raise TimeoutError('catalog_cache_eviction_deadline')
            receipt=json.loads(row['media']);stage=self.media._path(Path(row['stage']),directory=True);path=stage/'source.mp4'
            if str(path)!=receipt['file_path']:raise SafetyError('catalog_cache_receipt_path_changed')
            with self._db() as db:
                db.execute('BEGIN IMMEDIATE')
                if self._cache_busy(db,row['source_id']):continue
                changed=db.execute("UPDATE catalog_materializations SET phase='evicting' WHERE source_id=? AND phase=? AND media=?",(row['source_id'],row['phase'],row['media'])).rowcount
                if changed!=1:continue
            # Committed intent blocks ingest/retry/claim through the resolver.
            before=None
            if path.exists() or path.is_symlink():
                before=path.stat(follow_symlinks=False)
                self._verified_media(receipt,deadline)
                measured=path.stat(follow_symlinks=False)
                if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(measured.st_dev,measured.st_ino,measured.st_size,measured.st_mtime_ns,measured.st_ctime_ns):raise SafetyError('catalog_cache_changed_during_verification')
                if {p.name for p in stage.iterdir()}!={'source.mp4'}:raise SafetyError('catalog_cache_contents_changed')
            elif row['phase']!='evicting':raise SafetyError('catalog_cache_missing_without_intent')
            owner=stage.with_name(stage.name+'.owner.json');mark=None
            if owner.exists():
                mark=read(owner);worker=mark.get('worker')
                if mark.get('phase') not in ('complete','retired') or not isinstance(worker,dict) or process_identity(worker['pid'],deadline) is not None or not _group_has_no_live_members(worker['pid']):
                    raise SafetyError('catalog_cache_worker_ownership_unknown')
                if mark.get('receipt')!=receipt:raise SafetyError('catalog_cache_owner_receipt_changed')
            with self._db() as db:
                db.execute('BEGIN IMMEDIATE')
                current=db.execute('SELECT phase,media FROM catalog_materializations WHERE source_id=?',(row['source_id'],)).fetchone()
                if current is None or current['phase']!='evicting' or current['media']!=row['media']:raise SafetyError('catalog_cache_eviction_intent_changed')
                if self._cache_busy(db,row['source_id']):
                    db.execute("UPDATE catalog_materializations SET phase=? WHERE source_id=?",('ready' if row['captions'] else 'captions',row['source_id']))
                    continue
                if self.monotonic()>=deadline:raise TimeoutError('catalog_cache_eviction_deadline')
                if mark is not None and read(owner)!=mark:raise SafetyError('catalog_cache_owner_changed')
                if before is not None:
                    after=path.stat(follow_symlinks=False)
                    if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise SafetyError('catalog_cache_changed_before_unlink')
                    path.unlink()
                if any(stage.iterdir()):raise SafetyError('catalog_cache_contents_changed')
                if mark is not None:
                    if read(owner)!=mark:raise SafetyError('catalog_cache_owner_changed')
                    write(owner,mark|{'phase':'retired','partial_files':[]})
                db.execute("UPDATE catalog_materializations SET phase='evicted',next_at=0 WHERE source_id=?",(row['source_id'],))

    def discover(self, deadline):
        import json,os
        settings=self.config['source_discovery']
        candidates=self.catalog.eligible(limit=min(1000,self.config['limits']['max_queue']))['sources']
        if not candidates:
            # Refresh persists each page/dependency. Full-source acquisition is
            # deliberately a later invocation, never appended to this pass.
            self.catalog.refresh(self.providers,page_budget=settings['page_budget'],campaign_budget=settings['campaign_budget'],brief_budget=settings['brief_budget'],asset_budget=settings['asset_budget'],
                retry_policy={'base_seconds':settings['retry_base_seconds'],'max_seconds':settings['retry_max_seconds'],'refresh_seconds':settings['refresh_seconds']},
                timeout_seconds=self._timeout(deadline,settings['refresh_timeout_seconds']))
            return []
        with self._db() as db:
            states={row['source_id']:row for row in db.execute('SELECT * FROM catalog_materializations')}
            admitted={(row['source_id'],row['evidence_version']) for row in db.execute('SELECT source_id,evidence_version FROM catalog_admissions WHERE valid_until>?',(self.clock(),))}
        due=[c for c in candidates if c['id'] not in states or states[c['id']]['next_at']<=self.clock()]
        if not due:return []
        # Finish a due owned pipeline before opening another acquisition.
        # Ready caches return to ordinary fairness after a current admission.
        def priority(candidate):
            state=states.get(candidate['id'])
            unfinished=state is not None and (state['phase'] in ('media','captions','evicting') or (state['phase']=='ready' and (candidate['id'],candidate['current_version']) not in admitted))
            return (0 if unfinished else 1,state['next_at'] if state is not None else 0,candidate['id'])
        candidate=min(due,key=priority)
        snapshot=self.catalog.validate_current(candidate['id'],candidate['current_version'])
        asset=snapshot['evidence']['asset'];state=states.get(candidate['id'])
        stage=Path(self.config['workspace'])/'catalog-media'/candidate['id']
        if stage.is_symlink():raise SafetyError('catalog_media_stage_changed')
        stage.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        phase=state['phase'] if state is not None else 'media'
        with self._db() as db:
            db.execute('INSERT OR IGNORE INTO catalog_materializations(source_id,evidence_version,phase,stage) VALUES(?,?,?,?)',(candidate['id'],candidate['current_version'],'media',str(stage)))
        try:
            with self.media._lock(deadline):
                if phase=='evicting':
                    self._evict_cache(None,0,deadline)
                    return []
                if phase in ('media','evicted'):
                    if not stage.exists():stage.mkdir(mode=0o700)
                    self.media._path(stage,directory=True)
                    peak=3*settings['max_source_bytes']+1048576
                    from .safety import write_allowance
                    if write_allowance(self.config['workspace'],self.config['limits']['max_disk_bytes'])<peak:
                        self._evict_cache(candidate['id'],peak,deadline)
                    if write_allowance(self.config['workspace'],self.config['limits']['max_disk_bytes'])<peak:
                        raise SafetyError('catalog_source_merge_capacity_unavailable')
                    kwargs=dict(expected_video_id=asset['id'],duration_seconds=asset['duration'],output_dir=stage,max_source_bytes=settings['max_source_bytes'],max_stage_bytes=peak,max_resolution=settings['max_resolution'],timeout_seconds=self._timeout(deadline,settings['materialize_timeout_seconds']),ownership_path=stage.with_name(stage.name+'.owner.json'))
                    owner=kwargs['ownership_path'];receipt=None
                    if owner.exists() or any(stage.iterdir()):
                        if not owner.exists():raise SafetyError('catalog_partial_media_owner_unknown')
                        recovered=self.youtube.recover_source_media(snapshot['permission']['video_url'],**kwargs)
                        if recovered['state']=='complete':receipt=recovered['media']
                        elif recovered['state']!='retired':raise SafetyError('catalog_media_recovery_unconfirmed')
                    if receipt is None:
                        receipt=self.youtube.acquire_source_media(snapshot['permission']['video_url'],**kwargs)
                    with self._db() as db:db.execute("UPDATE catalog_materializations SET phase='captions',media=?,error=NULL,failures=0,next_at=? WHERE source_id=?",(canonical(receipt),self.clock(),candidate['id']))
                    return []
                receipt=self._verified_media(json.loads(state['media']),deadline)
                if phase=='captions':
                    captions=self.youtube.read_source_transcript(receipt['url'],expected_video_id=asset['id'],duration_seconds=asset['duration'],language='en',timeout_seconds=self._timeout(deadline,settings['materialize_timeout_seconds']),max_caption_bytes=8*1048576,max_cues=10000,max_result_bytes=2*1048576)
                    with self._db() as db:db.execute("UPDATE catalog_materializations SET phase='ready',captions=?,error=NULL,failures=0,next_at=? WHERE source_id=?",(canonical(captions),self.clock(),candidate['id']))
                    return []
                if phase!='ready':raise SafetyError('catalog_materialization_phase_unknown')
                captions=json.loads(state['captions'])
                with self._db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    admission,source,windows=register_admission(db,self.config,snapshot,receipt,captions,experience_id=self.providers.binding['experience'].rstrip('/').split('/')[-1],now=self.clock())
                    sha=captions['provenance']['raw_sha256']
                    cursor=db.execute('SELECT next_ordinal FROM catalog_window_cursors WHERE source_id=? AND caption_sha=?',(source['id'],sha)).fetchone()
                    ordinal=(cursor[0] if cursor else 0)%len(windows);window=windows[ordinal]
                    db.execute('UPDATE catalog_materializations SET next_at=?,error=NULL,failures=0 WHERE source_id=?',(self.clock()+settings['retry_base_seconds'],source['id']))
                # Admission committed before the parent validates this record.
                return [{'source_id':source['id'],'media_id':asset['id'],'media_url':receipt['url'],'duration_seconds':receipt['duration_seconds'],
                    'transcript':window['transcript'],'transcript_segments':window['transcript_segments'],
                    'source_window':window_record(window),'catalog_admission':{'id':admission,'source_id':source['id'],'evidence_version':snapshot['evidence_version']},
                    'observed_at':datetime.fromtimestamp(self.clock(),timezone.utc).isoformat(),'categories':source['campaign']['categories'],
                    'provenance':canonical({'kind':'owning_full_video_timed_caption_window','media_sha256':receipt['source_sha256'],'caption_provenance':captions['provenance'],'window':window_record(window)})}]
        except Exception as exc:
            delay=getattr(exc,'retry_after_seconds',None)
            with self._db() as db:
                failures=db.execute('SELECT failures FROM catalog_materializations WHERE source_id=?',(candidate['id'],)).fetchone()[0]+1
                pause=min(settings['retry_max_seconds'],settings['retry_base_seconds']*2**min(failures-1,20))
                if type(delay) in (int,float) and delay>=0:pause=max(pause,delay)
                code=getattr(exc,'code',None) or ('catalog_materialization_timeout' if isinstance(exc,TimeoutError) else 'catalog_materialization_failed')
                db.execute('UPDATE catalog_materializations SET next_at=?,failures=?,error=? WHERE source_id=?',(self.clock()+pause,failures,code,candidate['id']))
            raise


def advance_window(db,record):
    """Advance only in the same transaction that persists the admitted job."""
    import json
    row=db.execute('SELECT captions,windows FROM catalog_admissions WHERE id=?',(record['catalog_admission']['id'],)).fetchone()
    if row is None:raise SafetyError('catalog_admission_missing')
    windows=json.loads(row['windows']);sha=json.loads(row['captions'])['provenance']['raw_sha256']
    cursor=db.execute('SELECT next_ordinal FROM catalog_window_cursors WHERE source_id=? AND caption_sha=?',(record['source_id'],sha)).fetchone()
    ordinal=(cursor[0] if cursor else 0)%len(windows)
    if record['source_window']!=window_record(windows[ordinal]):raise SafetyError('catalog_window_cursor_changed')
    db.execute('INSERT INTO catalog_window_cursors VALUES(?,?,?) ON CONFLICT(source_id,caption_sha) DO UPDATE SET next_ordinal=excluded.next_ordinal',
               (record['source_id'],sha,(ordinal+1)%len(windows)))
