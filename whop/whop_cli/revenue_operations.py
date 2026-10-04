"""Observed individual payout allocations, shared resumable participant scans.

A completed pass is an interval of observations, never an atomic snapshot.
Unknown currency, absent records and incomplete generations cannot yield zero.
"""
import hashlib
import re
import time
from datetime import datetime, timezone
from .client import ClientError, WhopError, identifier, strict_json
from . import submission_operations as op

PAGE_SIZE=100
PAGES_PER_CALL=10
MAX_ALLOCATION_BYTES=16384
AMOUNTS=('amount','netAmount','accruedNetAmount','accruedAmount','creatorFeeAmount','submissionMigratedCompletedAmount')
FIELDS=('id','submissionId','campaignId','status','payoutModel','currency','createdAt','completeAt','paidAt','reversedAt','reversedReason','unmetSettleGate','frozenSince',*AMOUNTS)

def now(): return datetime.now(timezone.utc).isoformat()

def cents(value):
    if type(value) is int: value=str(value)
    if not isinstance(value,str) or not re.fullmatch(r'-?(0|[1-9][0-9]{0,37})',value): return None
    return str(int(value))

def allocation(raw):
    if not isinstance(raw,dict): raise ClientError('revenue_allocation_schema_changed')
    row={k:raw.get(k) for k in FIELDS}
    identifier(row['id'])
    for key in ('submissionId','campaignId'):
        if row[key] is not None: identifier(row[key])
    if not isinstance(row['status'],str) or not re.fullmatch(r'[A-Za-z_]{1,40}',row['status']): raise ClientError('revenue_allocation_status_invalid')
    for key in AMOUNTS:
        if row[key] is not None:
            parsed=cents(row[key])
            if parsed is None: raise ClientError('revenue_allocation_amount_invalid')
            row[key]=parsed
    if row['currency'] is not None and (not isinstance(row['currency'],str) or not re.fullmatch('[A-Z]{3}',row['currency'])):
        raise ClientError('revenue_allocation_currency_invalid')
    if len(op.canonical(row).encode())>MAX_ALLOCATION_BYTES: raise ClientError('revenue_allocation_too_large')
    return row

def tables(db):
    db.execute('CREATE TABLE IF NOT EXISTS payout_scans (scope TEXT PRIMARY KEY,payload TEXT NOT NULL CHECK(length(CAST(payload AS BLOB))<=262144))')
    for table in ('payout_current','payout_pending'):
        db.execute(f'''CREATE TABLE IF NOT EXISTS {table} (scope TEXT NOT NULL,id TEXT NOT NULL,submission TEXT,campaign TEXT,payload TEXT NOT NULL CHECK(length(CAST(payload AS BLOB))<=16384),observed_at TEXT NOT NULL,PRIMARY KEY(scope,id))''')
        db.execute(f'CREATE INDEX IF NOT EXISTS {table}_submission ON {table}(scope,submission,campaign)')
    db.execute("CREATE INDEX IF NOT EXISTS payout_scan_profile ON payout_scans(json_extract(payload,'$.binding.profile'),json_extract(payload,'$.binding.experience'))")
    db.execute('CREATE TABLE IF NOT EXISTS payout_cursors (scope TEXT NOT NULL,hash TEXT NOT NULL,PRIMARY KEY(scope,hash))')
    db.execute('''CREATE TABLE IF NOT EXISTS payout_disappeared (scope TEXT NOT NULL,id TEXT NOT NULL,submission TEXT,campaign TEXT,last_observed_at TEXT NOT NULL,missing_in_pass TEXT NOT NULL,PRIMARY KEY(scope,id))''')
    db.execute('CREATE INDEX IF NOT EXISTS payout_disappeared_submission ON payout_disappeared(scope,submission,campaign)')
    db.commit()

def owner(client,expected=None):
    actor=client.account()
    if expected is not None and actor['id']!=expected: raise WhopError('submission_whop_actor_changed',category='auth')
    # The observed payout endpoint uses the separate creator registry ID.
    accounts=client.linked_accounts(1000,require_complete=True)
    users={r['userId'] for r in accounts if isinstance(r,dict) and isinstance(r.get('userId'),str)}
    if len(users)!=1: raise ClientError('creator_identity_missing_or_ambiguous')
    creator=identifier(users.pop());origin,path=client._location()
    binding={'account_id':actor['id'],'profile':client.config.get_active_profile_name(),'experience':origin+path,'creator_id':creator}
    return op.digest(binding),binding

def save_scan(db,scope,state):
    text=op.canonical(state)
    if len(text.encode())>op.MAX_JOURNAL: raise ClientError('revenue_scan_too_large')
    db.execute('INSERT INTO payout_scans VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET payload=excluded.payload',(scope,text));db.commit()

def page(client,creator,cursor):
    params={'userIds':creator,'limit':PAGE_SIZE}
    if cursor is not None: params['cursor']=cursor
    result=client._rest('/api/submission/payouts',params)
    rows=result.get('data');pagination=result.get('pagination')
    if not isinstance(rows,list) or len(rows)>PAGE_SIZE or not isinstance(pagination,dict) or 'nextCursor' not in pagination:
        raise ClientError('revenue_pagination_schema_changed')
    cursor=pagination['nextCursor']
    if cursor is not None and (not isinstance(cursor,str) or not 1<=len(cursor)<=8192 or not rows): raise ClientError('revenue_cursor_invalid')
    if any(isinstance(r,dict) and r.get('userId') not in (None,creator) for r in rows): raise ClientError('revenue_creator_binding_changed')
    parsed=[allocation(r) for r in rows]
    if len({r['id'] for r in parsed})!=len(parsed): raise ClientError('revenue_duplicate_page_allocation')
    return parsed,cursor

def record_page(db,scope,rows,observed):
    for row in rows:
        existing=db.execute('SELECT submission,campaign FROM payout_pending WHERE scope=? AND id=?',(scope,row['id'])).fetchone()
        if existing is not None and existing!=(row['submissionId'],row['campaignId']): raise ClientError('revenue_allocation_binding_changed')
        existing=db.execute('SELECT submission,campaign FROM payout_current WHERE scope=? AND id=?',(scope,row['id'])).fetchone()
        if existing is not None and existing!=(row['submissionId'],row['campaignId']): raise ClientError('revenue_allocation_binding_changed')
        existing=db.execute('SELECT submission,campaign FROM payout_disappeared WHERE scope=? AND id=?',(scope,row['id'])).fetchone()
        if existing is not None and existing!=(row['submissionId'],row['campaignId']): raise ClientError('revenue_allocation_binding_changed')
        db.execute('''INSERT INTO payout_pending VALUES(?,?,?,?,?,?) ON CONFLICT(scope,id) DO UPDATE SET payload=excluded.payload,observed_at=excluded.observed_at''',
          (scope,row['id'],row['submissionId'],row['campaignId'],op.canonical(row),observed))

def promote(db,scope,state):
    completed=now()
    db.execute('''INSERT INTO payout_disappeared SELECT c.scope,c.id,c.submission,c.campaign,c.observed_at,? FROM payout_current c
        WHERE c.scope=? AND NOT EXISTS(SELECT 1 FROM payout_pending p WHERE p.scope=c.scope AND p.id=c.id)
        ON CONFLICT(scope,id) DO UPDATE SET missing_in_pass=excluded.missing_in_pass''',(completed,scope))
    db.execute('DELETE FROM payout_disappeared WHERE scope=? AND id IN (SELECT id FROM payout_pending WHERE scope=?)',(scope,scope))
    db.execute('DELETE FROM payout_current WHERE scope=?',(scope,))
    db.execute('INSERT INTO payout_current SELECT * FROM payout_pending WHERE scope=?',(scope,))
    db.execute('DELETE FROM payout_pending WHERE scope=?',(scope,))
    db.execute('DELETE FROM payout_cursors WHERE scope=?',(scope,))
    state.update(complete=True,cursor=None,completed_at=completed,completed_passes=state.get('completed_passes',0)+1)
    save_scan(db,scope,state)

def sync_locked(client,db,scope,binding,*,restart_pass=False):
    tables(db)
    raw=db.execute('SELECT payload FROM payout_scans WHERE scope=?',(scope,)).fetchone()
    state=strict_json(raw[0]) if raw else {'binding':binding,'complete':False,'cursor':None,'started_at':now(),'completed_passes':0}
    if state.get('binding')!=binding: raise ClientError('revenue_scan_binding_changed')
    if state.get('retry_not_before',0)>time.time(): return state
    if restart_pass or state.get('complete') is True:
        db.execute('DELETE FROM payout_pending WHERE scope=?',(scope,));db.execute('DELETE FROM payout_cursors WHERE scope=?',(scope,))
        state={'binding':binding,'complete':False,'cursor':None,'started_at':now(),'completed_passes':state.get('completed_passes',0)}
        save_scan(db,scope,state)
    try:
        # Refresh head while continuing a pass, including newly visible records.
        rows,head_cursor=page(client,binding['creator_id'],None)
        record_page(db,scope,rows,now())
        if state['cursor'] is None and not state.get('end_pending'): state['cursor']=head_cursor
        save_scan(db,scope,state)
        for _ in range(PAGES_PER_CALL):
            cursor=state['cursor']
            if cursor is None: break
            hashed=hashlib.sha256(cursor.encode()).hexdigest()
            if db.execute('SELECT 1 FROM payout_cursors WHERE scope=? AND hash=?',(scope,hashed)).fetchone(): raise ClientError('revenue_cursor_cycle_restart_required')
            rows,next_cursor=page(client,binding['creator_id'],cursor)
            record_page(db,scope,rows,now())
            # Commit only successful pages; failed reads don't poison cursors.
            db.execute('INSERT INTO payout_cursors VALUES(?,?)',(scope,hashed))
            state['cursor']=next_cursor
            if next_cursor is None: state['end_pending']=True
            save_scan(db,scope,state)
        state.pop('failure',None);state.pop('retry_not_before',None)
        if state['cursor'] is None: promote(db,scope,state)
        else: save_scan(db,scope,state)
    except WhopError as error:
        db.rollback()
        state['failure']={'code':error.code,'category':error.category,'status':error.status,'retry_after_seconds':error.retry_after_seconds}
        if error.category=='rate_limit' or error.retry_after_seconds is not None:
            state['retry_not_before']=time.time()+max(client.base_delay,error.retry_after_seconds or 0)
        state['complete']=False;save_scan(db,scope,state)
    except Exception:
        db.rollback();raise
    return state

def sync_summary(state):
    return {k:state.get(k) for k in ('binding','complete','started_at','completed_at','completed_passes','failure','retry_not_before')}|{'has_more':state.get('cursor') is not None,'snapshot_kind':'paginated_observation_interval'}

def cooldown(client,db):
    tables(db)
    origin,path=client._location();profile=client.config.get_active_profile_name()
    result=db.execute("SELECT max(json_extract(payload,'$.retry_not_before')) FROM payout_scans WHERE json_extract(payload,'$.binding.profile')=? AND json_extract(payload,'$.binding.experience')=?",(profile,origin+path)).fetchone()[0]
    submission_delay=db.execute("SELECT max(json_extract(payload,'$.retry_not_before')) FROM operations WHERE experience=? AND json_extract(payload,'$.binding.profile')=?",(origin+path,profile)).fetchone()[0]
    result=max(result or 0,submission_delay or 0)
    if result is not None and result>time.time():
        raise WhopError('revenue_provider_cooldown',category='rate_limit',retry_after_seconds=result-time.time())

def synchronize(client,*,restart_pass=False):
    if type(restart_pass) is not bool: raise ClientError('revenue_restart_flag_invalid')
    with op.journal_lock(client.config) as db:
        cooldown(client,db)
        scope,binding=owner(client)
        return sync_summary(sync_locked(client,db,scope,binding,restart_pass=restart_pass))

def revenue(client,submission_id,campaign_id,*,refresh_payouts=True):
    identifier(submission_id);identifier(campaign_id)
    if type(refresh_payouts) is not bool: raise ClientError('revenue_refresh_flag_invalid')
    with op.journal_lock(client.config) as db:
        cooldown(client,db)
        matches=db.execute("SELECT request_id FROM operations WHERE json_extract(payload,'$.submission_id')=? AND campaign=? LIMIT 2",(submission_id,campaign_id)).fetchall()
        if len(matches)!=1: raise ClientError('revenue_owned_submission_missing_or_ambiguous')
        row=op.load(db,matches[0][0]);bound=row['binding']
        if row.get('retry_not_before',0)>time.time():
            failure=row.get('failure',{})
            raise WhopError('submission_provider_cooldown',category=failure.get('category','rate_limit'),status=failure.get('status'),retry_after_seconds=row['retry_not_before']-time.time())
        row=op.reconcile_locked(client,db,row)
        if row.get('readback_fresh') is not True and isinstance(row.get('failure'),dict):
            failure=row['failure']
            raise WhopError(failure['code'],category=failure['category'],status=failure.get('status'),retry_after_seconds=failure.get('retry_after_seconds'))
        scope,binding=owner(client,bound['account_id'])
        if binding['experience']!=bound['experience'] or binding['profile']!=bound['profile']: raise ClientError('submission_profile_or_experience_changed')
        if refresh_payouts:
            state=sync_locked(client,db,scope,binding)
        else:
            raw=db.execute('SELECT payload FROM payout_scans WHERE scope=?',(scope,)).fetchone()
            if raw is None: raise ClientError('revenue_shared_scan_missing')
            state=strict_json(raw[0])
            if state.get('binding')!=binding: raise ClientError('revenue_scan_binding_changed')
        return result(db,scope,state,row,submission_id,campaign_id)

def result(db,scope,state,operation,submission_id,campaign_id):
    fresh=operation.get('readback_fresh') is True
    record=operation.get('submission',{})
    if record and (record.get('id')!=submission_id or not op.matches_post(record,operation['binding'])): raise ClientError('revenue_submission_binding_changed')
    removed=db.execute('SELECT id,last_observed_at,missing_in_pass FROM payout_disappeared WHERE scope=? AND submission=? AND campaign=? LIMIT 51',(scope,submission_id,campaign_id)).fetchall()
    allocations=[];count=0;currencies=set();pending=received=display_pending=0
    uncertain=set();pending_unknown=set();received_unknown=set();observation_start=observation_end=None
    rows=db.execute('SELECT payload,observed_at FROM payout_current WHERE scope=? AND submission=? AND campaign=?',(scope,submission_id,campaign_id))
    for text,observed in rows:
        allocation_row=strict_json(text);count+=1
        if allocation_row['status']=='pending':
            allocation_row['pending_amount_basis']=next((k for k in ('accruedNetAmount','accruedAmount','amount') if allocation_row[k] is not None),None)
        if len(allocations)<50: allocations.append(allocation_row|{'observed_at':observed})
        observation_start=min(observation_start,observed) if observation_start else observed
        observation_end=max(observation_end,observed) if observation_end else observed
        currency=allocation_row['currency']
        if currency is None: uncertain.add('currency_unknown')
        else: currencies.add(currency)
        if allocation_row['submissionMigratedCompletedAmount'] not in (None,'0'): uncertain.add('migrated_allocation_unverified')
        status=allocation_row['status']
        if status=='completed':
            value=allocation_row['netAmount']
            if value is None: received_unknown.add('completed_net_amount_unknown')
            else: received+=int(value)
        elif status=='pending':
            basis=next((k for k in ('accruedNetAmount','accruedAmount','amount') if allocation_row[k] is not None),None)
            allocation_row['pending_amount_basis']=basis
            # Native frozen/settlement gates can withhold this amount. Preserve
            # raw fields; don't manufacture the UI's zero fallback as earnings.
            if allocation_row['frozenSince'] is not None or allocation_row['unmetSettleGate'] is not None: pending_unknown.add('pending_settlement_gate')
            elif basis is None: pending_unknown.add('pending_amount_unknown')
            else:
                display_pending+=int(allocation_row[basis])
                if basis=='accruedNetAmount': pending+=int(allocation_row[basis])
                else: pending_unknown.add('pending_net_amount_unknown')
        elif status=='reversed': pass
        else: uncertain.add('payout_status_unverified')
    if count==0: uncertain.add('no_individual_allocations_observed')
    if len(currencies)!=1: uncertain.add('currency_unknown_or_mixed')
    if removed: uncertain.add('allocation_disappeared_not_reversed')
    if not state['complete']: uncertain.add('new_data_pending')
    if not fresh: uncertain.add('moderation_readback_not_fresh')
    pending_known=not uncertain and not pending_unknown
    received_known=not uncertain and not received_unknown
    verified=pending_known and received_known
    return {'submission_id':submission_id,'campaign_id':campaign_id,'publication_id':operation['binding']['publication']['publication_id'],
      'status':record.get('status') if fresh else None,'approved_at':record.get('approvedAt') if fresh else None,
      'flagged':record.get('flagged') if fresh else None,'is_deleted':record.get('isDeleted') if fresh else None,'creator_status':record.get('creator_status') if fresh else None,
      'observed_at':state.get('completed_at') if state['complete'] else None,'readback_fresh':fresh and state['complete'],
      'pending_cents':str(pending) if pending_known else None,'received_cents':str(received) if received_known else None,'total_earned_cents':str(pending+received) if verified else None,
      'amount_basis':'creator_net','provider_display_pending_cents':str(display_pending) if not uncertain and not pending_unknown-{'pending_net_amount_unknown'} else None,
      'currency':next(iter(currencies)) if len(currencies)==1 and 'currency_unknown' not in uncertain else None,
      'earning_window_started_at':None,'earning_window_ended_at':None,'exposure_seconds':None,
      'amounts_verified':verified,'unknown_reasons':sorted(uncertain|pending_unknown|received_unknown),'sync':sync_summary(state),
      'allocations':allocations,'allocation_count':count,'allocations_truncated':count>len(allocations),
      'allocation_observation_started_at':observation_start,'allocation_observation_ended_at':observation_end,
      'disappeared_allocations':[{'id':r[0],'last_observed_at':r[1],'missing_in_pass':r[2]} for r in removed[:50]],'disappeared_allocations_truncated':len(removed)>50,
      'provenance':{'kind':'participant_payout_allocations','endpoint':binding_endpoint(state),'moderation_observed_at':operation.get('observed_at'),'moderation_readback_fresh':fresh}}

def binding_endpoint(state):
    from urllib.parse import urlsplit
    p=urlsplit(state['binding']['experience'])
    return p.scheme+'://'+p.netloc+'/api/submission/payouts'


def invoke(client,name,*args,**kwargs):
    try: return globals()[name](client,*args,**kwargs)
    except WhopError: raise
    except ClientError as error:
        code=str(error).split(':',1)[0]
        if not re.fullmatch(r'[A-Za-z0-9_]{1,100}',code): code='revenue_read_failed'
        category='auth' if code=='submission_whop_actor_changed' else 'invalid_request' if code in ('invalid_identifier','revenue_owned_submission_missing_or_ambiguous','revenue_restart_flag_invalid') else 'upstream'
        raise WhopError(code,category=category) from None
