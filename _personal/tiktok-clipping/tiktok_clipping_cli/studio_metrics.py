"""Exact Studio measurement batches and restart-safe caller checkpoints."""
import json
import secrets
import re
from datetime import datetime, timezone

from .safety import SafetyError, canonical, digest, keys, number, timestamp

SCHEMA = '''CREATE TABLE IF NOT EXISTS metric_scans(
 id TEXT PRIMARY KEY,binding TEXT NOT NULL,publications TEXT NOT NULL,
 checkpoint TEXT,measured_ids TEXT NOT NULL,created_at REAL NOT NULL,expires_at REAL NOT NULL,next_at REAL NOT NULL,state TEXT NOT NULL,
 lane TEXT NOT NULL,last_round REAL NOT NULL);
 CREATE INDEX IF NOT EXISTS metric_scan_active ON metric_scans(state,lane,next_at,last_round);
 CREATE TABLE IF NOT EXISTS metric_scan_members(scan_id TEXT NOT NULL,publication_id TEXT NOT NULL,measured INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(scan_id,publication_id));
 CREATE INDEX IF NOT EXISTS metric_member_pending ON metric_scan_members(publication_id,measured,scan_id);'''

# Allow 512 rounds at up to four normal polling intervals, including recovery.
# Thirty days covers the deployed half-hour graph (36,000 posts need <80 mixed rounds).
# Ninety days remains an explicit upper bound; unknown IDs are never retired.
def scan_lifetime(config):
    return min(90*86400,max(30*86400,4*512*config['limits']['metrics_poll_seconds']))


def current_scan(engine, db, job, token, scan, publications):
    current = engine._job(db,job['id'])
    if current['status'] != 'running' or current['lease_until'] <= engine.clock() or current['lease_token'] != token:
        raise SafetyError('metric_worker_lease_changed')
    active = db.execute("SELECT * FROM metric_scans WHERE id=? AND state='active'",(scan['id'],)).fetchone()
    if active is None or active['expires_at'] <= engine.clock() or active['checkpoint'] != scan['checkpoint'] or active['binding'] != scan['binding']:
        raise SafetyError('metric_scan_owner_changed')
    for publication in publications:
        row = db.execute("SELECT data FROM publications WHERE id=? AND state='published'",(publication['publication_id'],)).fetchone()
        if row is None or json.loads(row[0]) != publication:
            raise SafetyError('metric_publication_manifest_changed')


def metric_windows(config):
    learning=config['learning']
    result=[(learning['cohort_age_seconds'],learning['cohort_tolerance_seconds'],learning['objective'])]
    for objective in learning.get('outcome_policy',{}).get('objectives',[]):
        if objective['channel']=='engagement':
            result.append((objective['horizon_seconds'],objective['tolerance_seconds'],objective['field']))
    return list(dict.fromkeys(result))


def urgent(engine,publication):
    age=engine.clock()-timestamp(publication['published_at'])
    return age<=48*3600 or any(abs(age-horizon)<=tolerance for horizon,tolerance,_ in metric_windows(engine.config))


def cohort_priority(engine):
    published="CAST(strftime('%s',json_extract(p.data,'$.published_at')) AS REAL)"
    conditions=[];values=[]
    for horizon,tolerance,field in metric_windows(engine.config):
        if field not in {'views','likes','comments','shares','watch_seconds'}:continue
        conditions.append('(?-'+published+' BETWEEN ? AND ?) AND NOT EXISTS(SELECT 1 FROM snapshots n WHERE n.publication_id=p.id AND n.channel=\'performance\' AND n.measured_at BETWEEN '+published+'+? AND '+published+'+? AND json_extract(n.data,\'$.'+field+'\') IS NOT NULL)')
        values.extend([engine.clock(),horizon-tolerance,horizon+tolerance,horizon-tolerance,horizon+tolerance])
    return conditions,values


def select_due(engine,db):
    """Unmeasured cohort deadlines outrank ordinary resampling backlog."""
    conditions,values=cohort_priority(engine)
    published="CAST(strftime('%s',json_extract(p.data,'$.published_at')) AS REAL)"
    conditions.append('(?-'+published+'<172800) AND NOT EXISTS(SELECT 1 FROM snapshots n WHERE n.publication_id=p.id AND n.channel=\'performance\')')
    values.append(engine.clock())
    query="SELECT p.id,p.data,s.failures FROM publications p JOIN metric_schedule s ON p.id=s.publication_id WHERE p.state='published' AND s.retired=0 AND s.next_check<=? ORDER BY CASE WHEN "+' OR '.join('('+c+')' for c in conditions)+" THEN 0 ELSE 1 END,s.next_check,p.id LIMIT ?"
    return list(db.execute(query,[engine.clock(),*values,engine.config['limits']['metrics_batch_size']]))


def actor(account):
    return {'account_id':account['account_id'],'username':account['handle'].removeprefix('@'),'profile':account['profile']}


def validate_publications(publications, account):
    from tiktok_cli.studio import positive_decimal_id
    if type(publications) is not list or not 1 <= len(publications) <= 1000:
        raise SafetyError('studio_metrics_manifest_invalid')
    ids = []
    for publication in publications:
        identifier = publication.get('publication_id')
        if not positive_decimal_id(identifier) or publication.get('account_id') != account['account_id'] or publication.get('handle','').removeprefix('@') != actor(account)['username']:
            raise SafetyError('studio_metrics_publication_identity_changed')
        if publication.get('publication_url') != f"https://www.tiktok.com/@{actor(account)['username']}/video/{identifier}":
            raise SafetyError('studio_metrics_publication_url_changed')
        timestamp(publication['published_at'])
        ids.append(identifier)
    if len(set(ids)) != len(ids):raise SafetyError('studio_metrics_duplicate_publication')
    return ids


def normalize_batch(result, publications, account):
    from tiktok_cli.studio_inventory import validate_request
    ids = set(validate_publications(publications, account))
    keys(result, {'actor','records','unresolved_ids','unresolved_state','requested_complete','provider_end','pages_read','continuation','semantics_digest','provenance'})
    if result['actor'] != actor(account) or result['provenance'] != 'own_account_studio' or result['unresolved_state'] != 'unknown':
        raise SafetyError('studio_metrics_actor_or_scope_changed')
    if type(result['records']) is not list or len(result['records']) > len(ids) or type(result['unresolved_ids']) is not list:
        raise SafetyError('studio_metrics_batch_invalid')
    unresolved = result['unresolved_ids']
    if len(set(unresolved)) != len(unresolved) or not set(unresolved) <= ids:
        raise SafetyError('studio_metrics_unresolved_invalid')
    if type(result['requested_complete']) is not bool or result['requested_complete'] != (not unresolved) or type(result['provider_end']) is not bool:
        raise SafetyError('studio_metrics_completion_invalid')
    if not isinstance(result['semantics_digest'],str) or not re.fullmatch('[a-f0-9]{64}',result['semantics_digest']):
        raise SafetyError('studio_metrics_semantics_invalid')
    number(result['pages_read'],1,20,integer=True)
    cp = result['continuation']
    validate_request(sorted(ids), cp, 20, account['account_id'])
    if cp is not None and (cp['actor'] != actor(account) or cp['semantics_digest'] != result['semantics_digest']):
        raise SafetyError('studio_metrics_checkpoint_changed')
    publications = {p['publication_id']:p for p in publications}
    records, seen = [], set()
    for record in result['records']:
        identifier = record.get('id')
        if identifier not in ids or identifier in seen or record.get('account_id') != account['account_id'] or record.get('profile') != account['profile'] or record.get('author') != actor(account)['username'] or record.get('url') != publications[identifier]['publication_url']:
            raise SafetyError('studio_metrics_record_identity_changed')
        seen.add(identifier)
        observed = timestamp(record['observed_at'])
        measured_ms = record.get('server_timestamp_ms')
        # A missing provider measurement time is unknown, never a caller clock.
        if measured_ms is None:continue
        number(measured_ms,0,integer=True)
        measured = measured_ms/1000
        if measured > observed or measured < timestamp(publications[identifier]['published_at']):
            raise SafetyError('studio_metrics_measurement_time_invalid')
        values = record.get('metrics')
        if type(values) is not dict or set(values) != {'views','likes','comments','shares','favorites'}:
            raise SafetyError('studio_metrics_values_changed')
        for value in values.values():
            if value is not None:number(value,0,integer=True)
        records.append({'publication_id':identifier,'observed_at':record['observed_at'],
            'measured_at':datetime.fromtimestamp(measured,timezone.utc).isoformat(),
            'provenance':record['provenance'], **{name:values[name] for name in ('views','likes','comments','shares')},
            'watch_seconds':None,'revenue':None,'revenue_currency':None})
    return {'actor':actor(account),'records':records,'continuation':cp,'provider_end':result['provider_end'],
        'requested_complete':result['requested_complete'],'semantics_digest':result['semantics_digest']}


def backoff_unresolved(db, schedule, scan, now, delay):
    """An old manifest cannot postpone an independent newer measurement."""
    if schedule['last_check'] is not None and schedule['last_check'] >= scan['created_at']:
        return 0
    return db.execute(
        'UPDATE metric_schedule SET next_check=?,failures=? WHERE publication_id=? AND retired=0 AND next_check=? AND failures=? AND last_check IS ?',
        (now+delay,schedule['failures']+1,schedule['publication_id'],schedule['next_check'],schedule['failures'],schedule['last_check'])).rowcount


def _run_scan(engine, job, token, due, *, lane, max_pages, force_new=False, exclude_id=None):
    """One immutable scan; no network while holding a SQLite transaction."""
    expected_actor = actor(engine.config['account'])
    with engine.transaction() as db:
        db.executescript(SCHEMA)
        db.execute('BEGIN IMMEDIATE')
        db.execute("DELETE FROM metric_scans WHERE state!='active' AND expires_at<?",(engine.clock()-engine.config['limits']['metrics_max_age_seconds'],))
        db.execute('DELETE FROM metric_scan_members WHERE scan_id NOT IN (SELECT id FROM metric_scans)')
        for scan in list(db.execute("SELECT * FROM metric_scans WHERE state='active'")):
            stored = json.loads(scan['publications'])
            binding = digest({'actor':expected_actor,'publications':stored,'scope':'own_account_studio'})
            changed = scan['binding'] != binding or scan['expires_at'] <= engine.clock()
            for publication in stored:
                current = db.execute("SELECT data FROM publications WHERE id=? AND state='published'",(publication['publication_id'],)).fetchone()
                if current is None or json.loads(current[0]) != publication:changed = True
            if changed:
                db.execute("UPDATE metric_scans SET state='canceled' WHERE id=?",(scan['id'],))
                engine.event(db,job['id'],'metric_scan_canceled',{'scan_id':scan['id']})
        conditions,priority_values=cohort_priority(engine)
        cohort=' OR '.join('('+c+')' for c in conditions) or '0'
        priority="CASE WHEN EXISTS(SELECT 1 FROM metric_scan_members m JOIN publications p ON p.id=m.publication_id WHERE m.scan_id=s.id AND m.measured=0 AND ("+cohort+")) THEN 0 ELSE 1 END"
        scan = None if force_new else db.execute("SELECT s.* FROM metric_scans s WHERE state='active' AND lane=? AND next_at<=? AND id!=? ORDER BY "+priority+",last_round,created_at,id LIMIT 1",(lane,engine.clock(),exclude_id or '',*priority_values)).fetchone()
        if scan is None:
            if not due:return {'snapshots':0,'failures':0}
            if db.execute("SELECT count(*) FROM metric_scans WHERE state='active'").fetchone()[0]>=64:
                raise SafetyError('metric_scan_capacity_exhausted')
            publications = [json.loads(row['data']) for row in due]
            validate_publications(publications,engine.config['account'])
            identifier = secrets.token_hex(16)
            lifetime = scan_lifetime(engine.config)
            db.execute("INSERT INTO metric_scans VALUES(?,?,?,NULL,'[]',?,?,?,'active',?,?)",(identifier,digest({'actor':expected_actor,'publications':publications,'scope':'own_account_studio'}),canonical(publications),engine.clock(),engine.clock()+lifetime,engine.clock(),lane,engine.clock()))
            db.executemany('INSERT INTO metric_scan_members(scan_id,publication_id) VALUES(?,?)',[(identifier,p['publication_id']) for p in publications])
            scan = db.execute('SELECT * FROM metric_scans WHERE id=?',(identifier,)).fetchone()
        scan = dict(scan)
        publications = json.loads(scan['publications'])
        scan_ids = [p['publication_id'] for p in publications]
        placeholders = ','.join('?' for _ in scan_ids)
        schedules = {row['publication_id']:dict(row) for row in db.execute('SELECT * FROM metric_schedule WHERE publication_id IN ('+placeholders+')',scan_ids)}
    checkpoint = json.loads(scan['checkpoint']) if scan['checkpoint'] else None
    try:
        result = engine._call('metrics_batch',publications,checkpoint,max_pages)
        keys(result,{'actor','records','continuation','provider_end','requested_complete','semantics_digest'})
        if result['actor'] != expected_actor:raise SafetyError('studio_metrics_batch_actor_changed')
        if type(result['provider_end']) is not bool or type(result['requested_complete']) is not bool:
            raise SafetyError('studio_metrics_batch_completion_invalid')
        if not isinstance(result['semantics_digest'],str) or not re.fullmatch('[a-f0-9]{64}',result['semantics_digest']):
            raise SafetyError('studio_metrics_batch_semantics_invalid')
        records = result['records']
        if type(records) is not list:raise SafetyError('studio_metrics_batch_records_invalid')
        ids = {p['publication_id'] for p in publications}
        if any(type(r) is not dict or r.get('publication_id') not in ids for r in records) or len({r['publication_id'] for r in records}) != len(records):
            raise SafetyError('studio_metrics_batch_records_changed')
        from tiktok_cli.studio_inventory import validate_request
        validate_request(sorted(ids),result['continuation'],20,expected_actor['account_id'])
        if result['continuation'] is not None and (result['continuation']['actor'] != expected_actor or result['continuation']['semantics_digest'] != result['semantics_digest']):
            raise SafetyError('studio_metrics_batch_checkpoint_changed')
        with engine.transaction() as db:
            current_scan(engine,db,job,token,scan,publications)
            inserted = sum(engine._insert_snapshot(db,record,'performance') for record in records)
            observed_ids = {record['publication_id'] for record in records}
            measured_ids = set(json.loads(scan['measured_ids'])) | observed_ids
            db.executemany('UPDATE metric_scan_members SET measured=1 WHERE scan_id=? AND publication_id=?',[(scan['id'],identifier) for identifier in observed_ids])
            for publication in publications:
                identifier = publication['publication_id']; schedule = schedules[identifier]
                if identifier in observed_ids:
                    measured = max(timestamp(r['measured_at']) for r in records if r['publication_id']==identifier)
                    published = timestamp(publication['published_at'])
                    next_check = engine.clock()+engine.config['limits']['metrics_poll_seconds']
                    cohort = published+engine.config['learning']['cohort_age_seconds']
                    if engine.clock() < cohort:next_check = min(next_check,cohort)
                    # Retirement requires an actual sufficiently aged final measurement.
                    retired = int(measured-published >= engine.config['limits']['metrics_max_age_seconds'])
                    db.execute('UPDATE metric_schedule SET next_check=?,last_check=?,failures=0,retired=max(retired,?) WHERE publication_id=? AND (last_check IS NULL OR last_check<?)',(next_check,measured,retired,identifier,measured))
                elif identifier not in measured_ids:
                    failures = schedule['failures']+1
                    delay = min(engine.config['limits']['retry_max_seconds'],engine.config['limits']['retry_base_seconds']*2**min(failures-1,30))
                    backoff_unresolved(db,schedule,scan,engine.clock(),delay)
            db.execute('UPDATE metric_scans SET checkpoint=?,measured_ids=?,next_at=?,last_round=?,state=? WHERE id=?',(canonical(result['continuation']) if result['continuation'] else None,canonical(sorted(measured_ids)),engine.clock(),engine.clock(),'active' if result['continuation'] else 'completed',scan['id']))
        return {'snapshots':inserted,'failures':len(publications)-len(measured_ids),'scan_id':scan['id']}
    except Exception as exc:
        from .engine import AdapterFailure
        if not isinstance(exc,(AdapterFailure,SafetyError,ValueError,KeyError,TypeError)):raise
        if str(exc).startswith(('control_','budget_exhausted','operation_time_budget_exhausted','metric_worker_','metric_scan_owner_','metric_publication_manifest_')):raise
        with engine.transaction() as db:
            current_scan(engine,db,job,token,scan,publications)
            delays = []; backed_off = 0
            prior_measured = set(json.loads(scan['measured_ids']))
            for publication in publications:
                identifier = publication['publication_id']
                if identifier in prior_measured:continue
                failures = schedules[identifier]['failures']+1
                delay = min(engine.config['limits']['retry_max_seconds'],engine.config['limits']['retry_base_seconds']*2**min(failures-1,30))
                if isinstance(exc,AdapterFailure) and exc.retry_after is not None:delay=max(delay,exc.retry_after)
                delays.append(delay)
                backed_off += backoff_unresolved(db,schedules[identifier],scan,engine.clock(),delay)
            engine.event(db,job['id'],'metric_batch_failed',{'scan_id':scan['id'],'error':str(exc)[:500]})
            db.execute("UPDATE metric_scans SET next_at=?,last_round=? WHERE id=? AND state='active'",(engine.clock()+max(delays or [engine.config['limits']['retry_base_seconds']]),engine.clock(),scan['id']))
            if isinstance(exc,SafetyError) or isinstance(exc,AdapterFailure) and exc.category=='permanent':
                db.execute("UPDATE metric_scans SET state='canceled' WHERE id=? AND state='active'",(scan['id'],))
        return {'snapshots':0,'failures':backed_off,'scan_id':scan['id']}


def run_batch(engine,job,token,due):
    with engine.transaction() as db:
        db.executescript(SCHEMA);db.execute('BEGIN IMMEDIATE')
        due=select_due(engine,db)
        candidates=[]
        for row in due:
            pending=db.execute("SELECT 1 FROM metric_scan_members m JOIN metric_scans s ON s.id=m.scan_id WHERE m.publication_id=? AND m.measured=0 AND s.state='active' AND s.expires_at>? LIMIT 1",(row['id'],engine.clock())).fetchone()
            if pending is None:candidates.append(row)
        fresh=[row for row in candidates if urgent(engine,json.loads(row['data']))]
        historical=[row for row in candidates if not urgent(engine,json.loads(row['data']))]
        mixed=bool(historical or db.execute("SELECT 1 FROM metric_scans WHERE state='active' AND lane='historical' AND expires_at>? LIMIT 1",(engine.clock(),)).fetchone())
        active_fresh=bool(db.execute("SELECT 1 FROM metric_scans WHERE state='active' AND lane='fresh' AND expires_at>? LIMIT 1",(engine.clock(),)).fetchone())
    results=[]
    if mixed:
        if fresh:
            # Fresh head has its own immutable request set. Resume partial fresh
            # manifests fairly before historical work, all within 20 pages.
            results.append(_run_scan(engine,job,token,fresh,lane='fresh',max_pages=2,force_new=True))
        results.append(_run_scan(engine,job,token,[],lane='fresh',max_pages=8))
        results.append(_run_scan(engine,job,token,historical,lane='historical',max_pages=10))
    elif fresh and active_fresh:
        results.append(_run_scan(engine,job,token,fresh,lane='fresh',max_pages=2,force_new=True))
        results.append(_run_scan(engine,job,token,[],lane='fresh',max_pages=18))
    else:
        results.append(_run_scan(engine,job,token,fresh,lane='fresh',max_pages=20))
    scans=[r['scan_id'] for r in results if 'scan_id' in r]
    return {'snapshots':sum(r['snapshots'] for r in results),'failures':sum(r['failures'] for r in results),
        **({'scan_id':scans[0],'scan_ids':scans} if scans else {})}
