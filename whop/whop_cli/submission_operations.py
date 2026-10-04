"""Explicit participant submissions; uncertain writes are never replayed.

The publication receipt is caller authority. Trusted callers obtain it from the
owning Studio SDK; it is not a cryptographic attestation. Whop checks the linked
account, duplicate post and publication freshness independently.
"""
import fcntl
import hashlib
import json
import os
import re
import stat
import time
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
from cli_tools_shared.exceptions import ClientError
from .client import DISCOVER_ACTION_JS, FETCH_JS, MAX_LIMIT, WhopError, retry_after_seconds, decode_action, identifier, strict_json

MAX_JOURNAL = 262144
STUDIO_READBACK = 'https://www.tiktok.com/tiktok/creator/manage/item_list/v1/'
# Read and create-action discovery share the same bounded, stable-snapshot scanner.
SUBMISSION_DISCOVERY_JS = DISCOVER_ACTION_JS

# Capture the failed predicate in the same evaluation, before the caller closes
# the browser. The selection and click behavior are unchanged.
OPEN_SUBMISSION_FORM_JS = """() => {
    const exact=[...document.querySelectorAll('button')].filter(b=>b.innerText.trim()==='Submit clip');
    const enabled=exact.filter(b=>!b.disabled);
    if(enabled.length!==1){
        const visible=b=>{const r=b.getBoundingClientRect(),s=getComputedStyle(b);
            return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
        const count=n=>Math.min(n,100000);
        return {opened:false,diagnostics:{origin:location.origin,path:location.pathname,
            ready_state:document.readyState,exact_buttons:count(exact.length),
            enabled_buttons:count(enabled.length),visible_buttons:count(exact.filter(visible).length),
            visible_enabled_buttons:count(enabled.filter(visible).length),
            dialogs:count(document.querySelectorAll('[role=dialog]').length)}};
    }
    enabled[0].click(); return true;
}"""

def form_failure(value, origin, expected_path):
    """Only a guarded exact route and bounded numeric DOM facts leave the SDK."""
    raw=value.get('diagnostics') if type(value) is dict and value.get('opened') is False else None
    context='expected_app' if type(raw) is dict and raw.get('origin')==origin else 'whop_wrapper' if type(raw) is dict and raw.get('origin')=='https://whop.com' else 'other_or_missing'
    route_match=type(raw) is dict and raw.get('origin')==origin and raw.get('path')==expected_path
    safe={'kind':'submission_form_predicate','available':False,
          'context_origin':context,'route_match':route_match}
    fields=('exact_buttons','enabled_buttons','visible_buttons','visible_enabled_buttons','dialogs')
    if (type(raw) is dict and raw.get('origin')==origin and raw.get('path')==expected_path
        and raw.get('ready_state') in ('loading','interactive','complete')
        and all(type(raw.get(k)) is int and 0<=raw[k]<=100000 for k in fields)):
        safe.update({'available':True,'origin':origin,'path':expected_path,
                     'ready_state':raw['ready_state'],**{k:raw[k] for k in fields}})
    error=WhopError('submission_form_unavailable',category='transient')
    error.diagnostics=safe
    return error

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def uuid(value):
    try:
        if not isinstance(value,str) or str(UUID(value))!=value: raise ValueError()
    except (ValueError,TypeError,AttributeError): raise ClientError('invalid_request_uuid') from None
    return value

def decimal(value):
    if not isinstance(value,str) or not re.fullmatch(r'[1-9][0-9]{0,19}',value):
        raise ClientError('invalid_tiktok_numeric_id')
    return value

def sha(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-f0-9]{64}',value):
        raise ClientError('invalid_requirements_or_receipt_digest')
    return value

def publication(value,expected_actor,*,check_age=False):
    if not isinstance(value,dict): raise ClientError('publication_receipt_invalid')
    result={k:value.get(k) for k in ('publication_id','publication_url','account_id','handle','published_at','provenance')}
    post=decimal(result['publication_id']);decimal(result['account_id'])
    if result['account_id']!=expected_actor: raise ClientError('publication_actor_changed')
    handle=result['handle']
    if not isinstance(handle,str) or not re.fullmatch(r'[A-Za-z0-9._]{1,24}',handle): raise ClientError('publication_handle_invalid')
    if result['publication_url']!=f'https://www.tiktok.com/@{handle}/video/{post}': raise ClientError('publication_url_binding_changed')
    try:
        when=datetime.fromisoformat(result['published_at'].replace('Z','+00:00'))
        if when.tzinfo is None or when.utcoffset().total_seconds()!=0 or when.microsecond or when.timestamp()<=0: raise ValueError()
    except (ValueError,TypeError,AttributeError,OverflowError): raise ClientError('publication_timestamp_invalid') from None
    raw=result['provenance']
    if not isinstance(raw,str) or len(raw)>16384: raise ClientError('publication_provenance_invalid')
    provenance=strict_json(raw)
    if not isinstance(provenance,dict) or provenance.get('kind')!='studio_verified' or provenance.get('readback')!=STUDIO_READBACK:
        raise ClientError('publication_provenance_invalid')
    required={'kind','request_id','post_project_id','asset_sha256','policy_digest','readback'}
    if not required<=set(provenance) or set(provenance)-required-{'cleanup_issue'}: raise ClientError('publication_provenance_invalid')
    if 'cleanup_issue' in provenance:
        issue=provenance['cleanup_issue']
        if not isinstance(issue,dict) or set(issue)!={'kind','error_type','recoverable'} or issue.get('kind')!='studio_browser_close_failed' or issue.get('recoverable') is not True or not isinstance(issue.get('error_type'),str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,80}',issue['error_type']):
            raise ClientError('publication_provenance_invalid')
    uuid(provenance.get('request_id'));decimal(provenance.get('post_project_id'))
    sha(provenance.get('asset_sha256'));sha(provenance.get('policy_digest'))
    result['provenance']=canonical(provenance)
    result['published_at']=when.isoformat()
    if check_age:
        age=(datetime.now(timezone.utc)-when).total_seconds()
        if not 0<=age<=1800: raise ClientError('publication_outside_30_minute_window')
    return result

def funding_evidence(campaign,payout):
    """Current provider-reported funds, never a guaranteed TikTok allocation."""
    metrics=campaign.get('metrics')
    budget=campaign.get('budgetCents');spent=metrics.get('budgetSpentCents') if isinstance(metrics,dict) else None
    if any(type(value) is not int or value<0 for value in (budget,spent)):
        raise ClientError('submission_campaign_funding_schema_changed')
    if budget<=spent:raise ClientError('submission_campaign_not_funded')
    shared={'budget_cents':budget,'spent_cents':spent,'remaining_cents':budget-spent}
    platform_budget=payout.get('budgetCents');platform_spent=payout.get('spentCents')
    if platform_budget is None and platform_spent is None:
        if any(isinstance(row,dict) and (row.get('budgetCents') is not None or row.get('spentCents') is not None) for row in campaign['payouts']):
            raise ClientError('submission_campaign_platform_funding_unknown')
        return {'scope':'campaign_reported','remaining_cents':budget-spent,'campaign':shared,'platform':None}
    if any(type(value) is not int or value<0 for value in (platform_budget,platform_spent)):
        raise ClientError('submission_campaign_payout_schema_changed')
    if platform_budget<=platform_spent:raise ClientError('submission_campaign_not_funded')
    platform={'budget_cents':platform_budget,'spent_cents':platform_spent,'remaining_cents':platform_budget-platform_spent}
    return {'scope':'platform','remaining_cents':platform['remaining_cents'],'campaign':shared,'platform':platform}


def readiness(client,campaign_id,*,expected_account_id,expected_tiktok_account_id,expected_requirements_digest=None):
    identifier(campaign_id);identifier(expected_account_id);decimal(expected_tiktok_account_id)
    if not expected_account_id.startswith('user_'): raise ClientError('invalid_expected_whop_actor')
    if expected_requirements_digest is not None: sha(expected_requirements_digest)
    actor=client.account()
    if actor['id']!=expected_account_id: raise ClientError('submission_whop_actor_changed')
    accounts=client.linked_accounts(MAX_LIMIT,require_complete=True)
    matches=[r for r in accounts if isinstance(r,dict) and r.get('platform')=='tiktok' and r.get('accountId')==expected_tiktok_account_id]
    if len(matches)!=1 or matches[0].get('status')!='active': raise ClientError('submission_linked_tiktok_missing_or_ambiguous')
    linked=matches[0]
    if not isinstance(linked.get('username'),str) or not re.fullmatch(r'[A-Za-z0-9._]{1,24}',linked['username']): raise ClientError('submission_linked_tiktok_schema_changed')
    campaign=client.campaign(campaign_id)
    if not isinstance(campaign,dict) or campaign.get('id')!=campaign_id: raise ClientError('submission_campaign_binding_changed')
    if campaign.get('status')!='active' or campaign.get('private') is not False: raise ClientError('submission_campaign_not_active_public')
    if campaign.get('requiresApplication') is not False: raise ClientError('submission_application_required_or_unknown')
    if not isinstance(campaign.get('platforms'),list) or 'tiktok' not in campaign['platforms']: raise ClientError('submission_campaign_not_tiktok')
    if not isinstance(campaign.get('description'),str) or not isinstance(campaign.get('name'),str) or not isinstance(campaign.get('referenceMaterials'),list):
        raise ClientError('submission_campaign_requirements_schema_changed')
    payouts=campaign.get('payouts')
    if not isinstance(payouts,list): raise ClientError('submission_campaign_payout_schema_changed')
    terms=[r for r in payouts if isinstance(r,dict) and r.get('platform')=='tiktok']
    if len(terms)!=1: raise ClientError('submission_campaign_payout_missing_or_ambiguous')
    payout=terms[0]
    for key in ('rateCents','minPayoutCents','maxPayoutCents'):
        if type(payout.get(key)) is not int or payout[key]<0: raise ClientError('submission_campaign_payout_schema_changed')
    if payout['rateCents']<=0:raise ClientError('submission_campaign_not_funded')
    funding=funding_evidence(campaign,payout)
    if not isinstance(payout.get('payoutType'),str): raise ClientError('submission_campaign_payout_schema_changed')
    intake=client._rest('/api/submission/submissions/intake',{'campaignIds':campaign_id})['data']
    if not isinstance(intake,list): raise ClientError('submission_intake_schema_changed')
    rows=[r for r in intake if isinstance(r,dict) and r.get('campaignId')==campaign_id]
    if len(rows)!=1: raise ClientError('submission_intake_missing_or_ambiguous')
    gate=rows[0]
    platform_intake=gate.get('platformIntake')
    if platform_intake is not None and (not isinstance(platform_intake,dict) or platform_intake.get('tiktok') not in (None,'open','closed')):
        raise ClientError('submission_intake_schema_changed')
    if gate.get('creatorMaxReached') is not False or gate.get('intake')!='open' or (platform_intake or {}).get('tiktok')=='closed':
        raise ClientError('submission_intake_not_open')
    origin,path=client._location()
    requirements={'campaign_id':campaign_id,'experience':origin+path,**{k:campaign[k] for k in ('name','description','referenceMaterials','platforms','requiresApplication','private')},
                  'tiktok_payout':{k:payout[k] for k in ('platform','payoutType','rateCents','minPayoutCents','maxPayoutCents')}}
    requirements_digest=digest(requirements)
    if expected_requirements_digest is not None and expected_requirements_digest!=requirements_digest: raise ClientError('submission_requirements_changed')
    participant_rows,participant_cursor=campaign_page(client,{'campaign_id':campaign_id},None)
    suffix='/campaigns/'+campaign_id
    document=client._action_document(suffix)
    try:
        action=client._discover_action(document,'createSubmissionAction',suffix,fresh=True,discovery_js=SUBMISSION_DISCOVERY_JS,request_timeout=12.0)
    except ClientError as error:
        if not str(error).startswith('read_action_discovery_missing:'): raise
        opened=document.evaluate(OPEN_SUBMISSION_FORM_JS,request_timeout=2.0)
        if opened is not True: raise form_failure(opened,origin,path+suffix) from None
        # The observed form is dynamically imported. Wait for its mounted dialog,
        # not an arbitrary sleep or a hard-coded build/action reference.
        mounted=document.evaluate("""async () => {const end=Date.now()+10000;
            while(Date.now()<end){if(document.querySelector('[role=dialog]'))return true;await new Promise(r=>setTimeout(r,50));}return false;}""",request_timeout=12.0)
        if mounted is not True: raise ClientError('submission_form_not_ready') from None
        action=client._discover_action(document,'createSubmissionAction',suffix,fresh=True,discovery_js=SUBMISSION_DISCOVERY_JS,request_timeout=12.0)
    # A later actor read would navigate away from this exact action context.
    client._submission_context=(document,action,path+suffix)
    return {'ready':True,'actor':{'account_id':actor['id'],'username':actor['username'],'profile':actor['profile']},
            'linked_account':{'account_id':expected_tiktok_account_id,'username':linked['username'],'id':linked.get('id')},
            'campaign_id':campaign_id,'requirements':requirements,'requirements_digest':requirements_digest,
            'funding_remaining_cents':funding['remaining_cents'],'funding':funding,'intake':'open','readback':{'kind':'participant_campaign_action','first_page_count':len(participant_rows),'has_more':participant_cursor is not None},
            'action':{'name':'createSubmissionAction','reference':action},'observed_at':datetime.now(timezone.utc).isoformat()}

def private_regular(path,*,create=False):
    flags=os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK
    if create: flags|=os.O_CREAT
    try: fd=os.open(path,flags,0o600)
    except OSError: raise ClientError('submission_journal_file_unsafe') from None
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1:
            raise ClientError('submission_journal_file_unsafe')
        return (info.st_dev,info.st_ino)
    finally: os.close(fd)

@contextmanager
def journal_lock(config):
    profile=Path(config.get_profile_data_dir())
    if profile.is_symlink() or profile.resolve()!=profile.absolute(): raise ClientError('submission_profile_path_unsafe')
    root=profile/'submission-operations'
    root.mkdir(mode=0o700,exist_ok=True)
    info=root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700: raise ClientError('submission_journal_directory_unsafe')
    parent=os.open(profile,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try: os.fsync(parent)
    finally: os.close(parent)
    lock=root/'.lock';private_regular(lock,create=True)
    fd=os.open(lock,os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK)
    db=None
    try:
        try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise ClientError('submission_operation_busy') from None
        path=root/'operations.sqlite3'
        identity=private_regular(path,create=True)
        for suffix in ('-journal','-wal','-shm'):
            sidecar=Path(str(path)+suffix)
            if sidecar.exists() or sidecar.is_symlink(): private_regular(sidecar)
        db=sqlite3.connect(path,timeout=1)
        if private_regular(path)!=identity: raise ClientError('submission_journal_file_changed')
        db.execute('PRAGMA journal_mode=DELETE')
        db.execute('PRAGMA synchronous=FULL')
        db.execute("""CREATE TABLE IF NOT EXISTS operations (
            request_id TEXT PRIMARY KEY,
            actor TEXT NOT NULL,experience TEXT NOT NULL,campaign TEXT NOT NULL,post TEXT NOT NULL,
            payload TEXT NOT NULL CHECK(length(CAST(payload AS BLOB))<=262144),
            UNIQUE(actor,experience,campaign,post))""")
        db.execute('CREATE TABLE IF NOT EXISTS reconciliation_cursors (request_id TEXT NOT NULL,cursor_hash TEXT NOT NULL,PRIMARY KEY(request_id,cursor_hash))')
        db.execute("CREATE INDEX IF NOT EXISTS operation_submission ON operations(json_extract(payload,'$.submission_id'),campaign)")
        db.execute("CREATE INDEX IF NOT EXISTS operation_provider_cooldown ON operations(experience,json_extract(payload,'$.binding.profile'),json_extract(payload,'$.retry_not_before'))")
        db.commit()
        directory=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try: os.fsync(directory)
        finally: os.close(directory)
        yield db
    except sqlite3.Error:
        raise WhopError('submission_journal_unavailable',category='transient') from None
    finally:
        if db is not None: db.close()
        os.close(fd)

def load(db,request_id):
    result=db.execute('SELECT payload,actor,experience,campaign,post FROM operations WHERE request_id=?',(uuid(request_id),)).fetchone()
    if result is None: return None
    raw=result[0]
    if not isinstance(raw,str) or len(raw.encode())>MAX_JOURNAL: raise ClientError('submission_journal_invalid')
    try: row=strict_json(raw)
    except ClientError: raise ClientError('submission_journal_invalid') from None
    if not isinstance(row,dict) or type(row.get('version')) is not int or row.get('version')!=1 or row.get('request_id')!=request_id or not isinstance(row.get('binding'),dict) or row.get('state') not in ('reserved','dispatching','uncertain','rejected','created_unverified','submitted_verified') or type(row.get('public_action_dispatched')) is not bool:
        raise ClientError('submission_journal_invalid')
    bound=row['binding']
    if (bound.get('account_id'),bound.get('experience'),bound.get('campaign_id'),bound.get('publication',{}).get('publication_id'))!=result[1:]:
        raise ClientError('submission_journal_binding_changed')
    return row

def save(db,row):
    payload=canonical(row)
    if len(payload.encode())>MAX_JOURNAL: raise ClientError('submission_journal_too_large')
    bound=row['binding']
    values=(uuid(row['request_id']),bound['account_id'],bound['experience'],bound['campaign_id'],bound['publication']['publication_id'],payload)
    try:
        db.execute("""INSERT INTO operations(request_id,actor,experience,campaign,post,payload) VALUES(?,?,?,?,?,?)
            ON CONFLICT(request_id) DO UPDATE SET payload=excluded.payload""",values)
        # FULL synchronous DELETE-mode commit is durable before any dispatch.
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback();raise ClientError('submission_publication_already_reserved') from None

def binding(client,campaign_id,receipt,actor,tiktok,requirements):
    origin,path=client._location()
    return {'profile':client.config.get_active_profile_name(),'experience':origin+path,
            'account_id':actor,'tiktok_account_id':tiktok,'campaign_id':identifier(campaign_id),
            'publication':publication(receipt,tiktok),'requirements_digest':sha(requirements)}

def verified_owner(client,bound):
    actor=client.account()
    if actor['id']!=bound['account_id']: raise ClientError('submission_whop_actor_changed')
    origin,path=client._location()
    if origin+path!=bound['experience'] or client.config.get_active_profile_name()!=bound['profile']: raise ClientError('submission_profile_or_experience_changed')

def matches_post(record,bound):
    post=record.get('socialMediaPost') if isinstance(record,dict) else None
    return record.get('campaignId')==bound['campaign_id'] and isinstance(post,dict) and post.get('platform')=='tiktok' and post.get('postId')==bound['publication']['publication_id'] if isinstance(record,dict) else False

def safe_record(record):
    safe={k:record.get(k) for k in ('id','campaignId','status','createdAt','approvedAt','pendingCents','receivedCents','totalEarnedCents')}
    for key in ('flagged','isDeleted'):
        value=record.get(key)
        if value is not None and type(value) is not bool:
            raise ClientError('submission_moderation_flag_schema_changed')
        safe[key]=value
    # The observed participant creatorStatusOf classifier is flag-based.
    # Missing flags cannot establish that raw status represents moderation.
    known=type(safe['flagged']) is bool and type(safe['isDeleted']) is bool
    safe['creator_status']=('rejected' if safe['flagged'] and not safe['isDeleted'] else safe['status'] if isinstance(safe['status'],str) else None) if known else None
    safe['socialMediaPost']={k:record['socialMediaPost'].get(k) for k in ('platform','postId')}
    return safe

def campaign_page(client,bound,cursor):
    args={'campaignId':bound['campaign_id'],'retainer':False,'limit':50}
    if cursor is not None: args['cursor']=cursor
    response=client._action('listMySubmissionsAction',[args],'/submissions')
    rows=response.get('data');pagination=response.get('pagination',response)
    if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows) or len(rows)>50 or not isinstance(pagination,dict) or 'nextCursor' not in pagination:
        raise ClientError('submission_reconciliation_schema_changed')
    next_cursor=pagination['nextCursor']
    if next_cursor is not None and (not isinstance(next_cursor,str) or not 1<=len(next_cursor)<=8192 or not rows): raise ClientError('submission_reconciliation_cursor_invalid')
    return rows,next_cursor

def reconciliation_match(row,records,page_cursor):
    progress=row['reconciliation']
    for record in records:
        if matches_post(record,row['binding']):
            remote_id=identifier(record.get('id'))
            if progress.get('match_id') is not None and progress['match_id']!=remote_id:
                raise ClientError('submission_reconciliation_duplicate_remote_rows')
            progress['match_id']=remote_id
            progress['match_record']=safe_record(record)
            progress['match_page_cursor']=page_cursor
            progress['match_observed_at']=datetime.now(timezone.utc).isoformat()

def mark_cooldown(client,row):
    failure=row.get('failure',{})
    delay=failure.get('retry_after_seconds')
    if failure.get('category')=='rate_limit' or delay is not None:
        minimum=max(client.base_delay,delay if delay is not None else 0)
        row['retry_not_before']=time.time()+minimum

def _reconcile_locked(client,db,row):
    if row.get('retry_not_before',0)>time.time(): return row
    verified_owner(client,row['binding'])
    inspection_started=datetime.now(timezone.utc).isoformat()
    row['inspection_observed_at']=inspection_started
    row['readback_fresh']=False
    if row['public_action_dispatched'] is False: return row
    progress=row.setdefault('reconciliation',{'cursor':None,'match_id':None,'completed_scans':0})
    cursor=progress['cursor']
    # Refresh head on every pass, even while continuing an older cursor.
    head,next_head=campaign_page(client,row['binding'],None)
    reconciliation_match(row,head,None)
    known_id=row.get('submission_id')
    if known_id is not None and progress.get('match_id') not in (None,known_id): raise ClientError('submission_reconciliation_binding_changed')
    record=next((r for r in head if r.get('id')==known_id and matches_post(r,row['binding'])),None) if known_id else None
    if record is None and known_id is not None and progress.get('match_page_cursor') is not None:
        match_cursor=progress['match_page_cursor']
        current,_=campaign_page(client,row['binding'],match_cursor)
        reconciliation_match(row,current,match_cursor)
        if progress.get('match_id') not in (None,known_id): raise ClientError('submission_reconciliation_binding_changed')
        record=next((r for r in current if r.get('id')==known_id and matches_post(r,row['binding'])),None)
    if cursor is None and not progress.get('pass_end_pending'): cursor=next_head
    row['inspection_complete']=False
    for _ in range(10):
        if record is not None or cursor is None: break
        page_cursor=cursor
        key=hashlib.sha256(page_cursor.encode()).hexdigest()
        if db.execute('SELECT 1 FROM reconciliation_cursors WHERE request_id=? AND cursor_hash=?',(row['request_id'],key)).fetchone():
            raise ClientError('submission_reconciliation_cursor_cycle')
        records,cursor=campaign_page(client,row['binding'],page_cursor)
        # Insert only after a successful read. Failure/cooldown persistence must
        # not poison this still-unvisited cursor as a completed page.
        db.execute('INSERT INTO reconciliation_cursors VALUES(?,?)',(row['request_id'],key))
        reconciliation_match(row,records,page_cursor)
        if known_id is not None:
            if progress.get('match_id') not in (None,known_id): raise ClientError('submission_reconciliation_binding_changed')
            record=next((r for r in records if r.get('id')==known_id and matches_post(r,row['binding'])),None)
        progress['cursor']=cursor
        if cursor is None: progress['pass_end_pending']=True
        save(db,row)
    if cursor is None:
        row['inspection_complete']=True
        progress['completed_scans']+=1
        progress.pop('pass_end_pending',None)
        db.execute('DELETE FROM reconciliation_cursors WHERE request_id=?',(row['request_id'],))
    progress['cursor']=cursor
    if known_id is None and row['inspection_complete'] and progress.get('match_id') is not None:
        # The candidate was observed in this authenticated participant list.
        # Retrieve only its refreshed campaign page, retaining exact binding.
        known_id=progress['match_id']
        row['submission_id']=known_id
        record=progress.get('match_record')
        if not matches_post(record,row['binding']) or record.get('id')!=known_id: raise ClientError('submission_reconciliation_binding_changed')
    if record is not None:
        row.update(state='submitted_verified',submission=safe_record(record),observed_at=progress['match_observed_at'],readback_fresh=progress['match_observed_at']>=inspection_started)
    elif row['state'] not in ('rejected','submitted_verified'): row['state']='uncertain'
    # Successful provider reads retire active transport failures, including a
    # clean later miss. A definitive create rejection remains a terminal reason.
    if row['state']!='rejected':
        for key in ('failure','failure_code','retry_not_before'): row.pop(key,None)
    save(db,row)
    return row

def reconcile_locked(client,db,row):
    try: return _reconcile_locked(client,db,row)
    except WhopError as error:
        if row['public_action_dispatched'] is False: raise
        row.update(state='submitted_verified' if row['state']=='submitted_verified' else 'uncertain',readback_fresh=False,failure_code=error.code,failure={'code':error.code,'category':error.category,'status':error.status,'retry_after_seconds':error.retry_after_seconds})
        mark_cooldown(client,row)
        save(db,row)
        return row

def reconcile(client,request_id):
    with journal_lock(client.config) as root:
        row=load(root,request_id)
        if row is None: raise ClientError('submission_request_not_found')
        return reconcile_locked(client,root,row)

def create(client,request_id,campaign_id,receipt,*,expected_account_id,expected_tiktok_account_id,accepted_requirements_digest,confirm):
    uuid(request_id);identifier(expected_account_id);decimal(expected_tiktok_account_id)
    bound=binding(client,campaign_id,receipt,expected_account_id,expected_tiktok_account_id,accepted_requirements_digest)
    with journal_lock(client.config) as root:
        row=load(root,request_id)
        if row is not None:
            if row['binding']!=bound: raise ClientError('submission_request_binding_changed')
            if row['state']!='reserved': return reconcile_locked(client,root,row)
        else:
            row={'version':1,'request_id':request_id,'binding':bound,'state':'reserved','public_action_dispatched':False,'created_at':datetime.now(timezone.utc).isoformat()}
            save(root,row)
        # The unique local publication index owns at-most-once dispatch.
        # Provider duplicate rejection remains separate; no full-history scan
        # consumes the publication's thirty-minute window before a new write.
        ready=readiness(client,campaign_id,expected_account_id=expected_account_id,expected_tiktok_account_id=expected_tiktok_account_id,expected_requirements_digest=accepted_requirements_digest)
        if ready['linked_account']['username']!=bound['publication']['handle']: raise ClientError('submission_publication_handle_changed')
        document,action,path=client._submission_context
        allowed=confirm(json.loads(canonical({'request_id':request_id,'binding':bound,'readiness':ready}))) if callable(confirm) else confirm
        if allowed is not True: raise ClientError('submission_confirmation_required')
        publication(bound['publication'],expected_tiktok_account_id,check_age=True)
        row.update(state='dispatching',public_action_dispatched=True,dispatched_at=datetime.now(timezone.utc).isoformat())
        save(root,row)
        try:
            # Exactly one fetch; never enter the read transport retry loop.
            response=document.evaluate(FETCH_JS,{'path':path,'action':action,'body':[{'campaignId':campaign_id,'url':bound['publication']['publication_url']}]},request_timeout=22.0)
            if not isinstance(response,dict) or type(response.get('status')) is not int: raise ClientError('submission_transport_invalid')
            if response['status']!=200:
                code=response['status'];row.update(state='uncertain',failure_code=f'http_{code}' if 0<=code<=599 else 'invalid_transport',failure={'code':f'http_{code}' if 0<=code<=599 else 'invalid_transport','category':'rate_limit' if code==429 else 'auth' if code in (401,403) else 'transient' if code==0 or 500<=code<=599 else 'upstream','status':code if 0<=code<=599 else None,'retry_after_seconds':retry_after_seconds(response.get('retryAfter'))})
            else:
                result=decode_action(response.get('text'))
                if result.get('success') is False:
                    code=result.get('code');safe=code if isinstance(code,str) and re.fullmatch('[A-Z_]{1,64}',code) else 'upstream_rejected';row.update(state='rejected',failure_code=safe,failure={'code':safe,'category':'upstream','status':200,'retry_after_seconds':retry_after_seconds(response.get('retryAfter'))})
                elif result.get('success') is True and isinstance(result.get('data'),dict):
                    row.update(state='created_unverified',submission_id=identifier(result['data'].get('id')))
                else: raise ClientError('submission_response_schema_changed')
        except Exception as error:
            row.update(state='uncertain',failure_code='transport_or_response_unverified',failure={'code':'transport_or_response_unverified','category':'ambiguous','status':None,'retry_after_seconds':None})
            save(root,row)
        mark_cooldown(client,row)
        save(root,row)
        return reconcile_locked(client,root,row)

def read_receipt(path):
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size>65536: raise ClientError('publication_receipt_file_invalid')
            raw=stream.read(65537)
        if len(raw)>65536: raise ClientError('publication_receipt_file_invalid')
        return strict_json(raw.decode())
    except (OSError,UnicodeError): raise ClientError('publication_receipt_file_invalid') from None
