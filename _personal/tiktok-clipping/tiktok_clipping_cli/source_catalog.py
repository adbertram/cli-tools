"""Indexed operational source evidence; models never establish reuse permission."""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from urllib.parse import parse_qs, urlparse

from .safety import SafetyError

MAX_EVIDENCE_BYTES = 2 * 1024 * 1024
MAX_CURSOR_BYTES = 4096
MAX_PAGE = 50
MAX_CALL_BUDGET = 20


def encoded(value):
    try:
        result = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise SafetyError('catalog_evidence_invalid') from None
    if len(result.encode()) > MAX_EVIDENCE_BYTES:
        raise SafetyError('catalog_evidence_exceeds_bound')
    return result


def version(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def text(value, maximum=4096):
    try:size=len(value.encode()) if type(value) is str else 0
    except UnicodeError:raise SafetyError('catalog_string_invalid') from None
    if type(value) is not str or not value or size > maximum:
        raise SafetyError('catalog_string_invalid')
    return value


def positive(value, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise SafetyError('catalog_budget_invalid')
    return value


def video_url(value):
    """Resolve only explicit exact video links, never a channel grant."""
    if type(value) is not str:
        return None
    try:
        parsed = urlparse(value)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.fragment or parsed.port not in (None,443):
            return None
        query = parse_qs(parsed.query,keep_blank_values=True)
        # Observed provider briefs include YouTube's short-link share token.
        # It conveys no asset scope and is never retained in the canonical URL.
        if 'si' in query and (len(query['si'])!=1 or not re.fullmatch('[A-Za-z0-9_-]{1,256}',query['si'][0])):
            return None
        if parsed.hostname in ('youtube.com','www.youtube.com') and parsed.path == '/watch':
            if set(query)-{'si'} != {'v'} or len(query['v']) != 1:
                return None
            identifier = query['v'][0]
        elif parsed.hostname == 'youtu.be' and set(query)<={'si'} and re.fullmatch('/[A-Za-z0-9_-]{11}',parsed.path):
            identifier = parsed.path[1:]
        else:
            return None
        return 'https://www.youtube.com/watch?v=' + identifier if re.fullmatch('[A-Za-z0-9_-]{11}', identifier) else None
    except ValueError:
        return None


def stable_asset(asset):
    """Only observed owning-SDK source facts belong in immutable evidence."""
    result={key:asset.get(key) for key in ('id','title','duration','channel','channel_id','upload_date')}
    text(result['id'],11)
    for key,maximum in (('title',4096),('channel',4096),('channel_id',256)):
        if result[key] is not None:text(result[key],maximum)
    duration=result['duration']
    if type(duration) not in (int,float) or not math.isfinite(duration) or duration<=0:
        raise SafetyError('catalog_asset_duration_invalid')
    if result['upload_date'] is not None and (type(result['upload_date']) is not str or not re.fullmatch('[0-9]{8}',result['upload_date'])):
        raise SafetyError('catalog_asset_upload_date_invalid')
    return result


COMMISSION_FAMILY = re.compile(
    r"(?P<commission>Clip any episode of (?P<show>[^.\n]{1,128}) with (?P<host>[^.\n]{1,128}) from (?P<publisher>[^.\n]{1,128})\.) "
    r"(?P<count>[1-9][0-9]{0,5}) episodes: (?P<guests>[^.\n]{1,1024}) and more\. "
    r"(?P<recommendation>Inspirational, sad or happy moments over trending sounds hit hardest\.) "
    r"(?P<rate>\$(?P<dollars>[0-9]{1,8})\.(?P<cents>[0-9]{2}) per 1K views on TikTok, Instagram and YouTube\.) "
    r"(?P<threshold>Pays from (?P<views>[1-9][0-9]{0,2}(?:,[0-9]{3})*|[1-9][0-9]{0,8}) views\.)")
EDITORIAL_REQUIREMENT='Clippers and editors who post rap, music and pop-culture clips on TikTok, Reels and Shorts.'
COMMISSION_VERSION='supplied-av-episode-commission-v1'


def commission_permission(evidence):
    """Compile the reviewed full supplied-episode family, with no ID allowlist."""
    campaign=evidence['campaign'];asset=evidence['asset'];description=campaign.get('description')
    if type(description) is not str:return None
    matched=COMMISSION_FAMILY.fullmatch(description)
    if matched is None or evidence['briefs']:return None
    for label in ('show','host','publisher'):
        if not re.fullmatch("[A-Za-z0-9][A-Za-z0-9 &'():-]{0,127}",matched[label]):return None
    if not re.fullmatch("[A-Za-z0-9][A-Za-z0-9 &'():,-]{0,1023}",matched['guests']):return None
    requirements=campaign.get('creatorRequirements')
    if requirements not in (None,[],[EDITORIAL_REQUIREMENT]):return None
    if asset.get('channel')!=matched['publisher']:return None
    if any(type(asset.get(key)) is not str or not asset[key] for key in ('title','channel','channel_id','upload_date')):return None
    if not re.fullmatch('[0-9]{8}',asset['upload_date']):return None
    if type(asset.get('duration')) not in (int,float) or not math.isfinite(asset['duration']) or asset['duration']<=0:return None
    if video_url(evidence['source_url'])!='https://www.youtube.com/watch?v='+asset['id']:return None
    references=campaign.get('referenceMaterials')
    if type(references) is not list or not references:return None
    membership=[]
    for index,item in enumerate(references):
        if type(item) is not dict or item.get('type')!='brandAsset' or type(item.get('url')) is not str:return None
        canonical=video_url(item['url'])
        if canonical is None:
            # Observed playlist describes a collection; it grants no inferred members.
            try:
                parsed=urlparse(item['url']);query=parse_qs(parsed.query,keep_blank_values=True)
                playlist=(parsed.scheme=='https' and parsed.hostname in ('youtube.com','www.youtube.com') and parsed.path=='/playlist'
                          and not parsed.username and not parsed.password and parsed.port in (None,443) and not parsed.fragment
                          and set(query)=={'list'} and len(query['list'])==1 and re.fullmatch('[A-Za-z0-9_-]{1,256}',query['list'][0]))
            except ValueError:playlist=False
            if not playlist:return None
        if canonical==evidence['source_url']:membership.append(index)
    if not membership:return None
    payout=campaign.get('tiktok_payout')
    if type(payout) is not dict or payout.get('platform')!='tiktok' or payout.get('payoutType')!='cpm':return None
    cents=int(matched['dollars'])*100+int(matched['cents']);views=int(matched['views'].replace(',',''))
    if type(payout.get('rateCents')) is not int or payout['rateCents']!=cents or cents<=0:return None
    if type(payout.get('minPayoutCents')) is not int or payout['minPayoutCents']*1000!=views*cents:return None
    if type(payout.get('maxPayoutCents')) is not int or payout['maxPayoutCents']<payout['minPayoutCents']:return None
    if campaign.get('private') is not False or campaign.get('requiresApplication') is not False or type(campaign.get('platforms')) is not list or 'tiktok' not in campaign['platforms']:return None
    return {'compiler_version':COMMISSION_VERSION,'campaign_id':campaign['id'],'video_url':evidence['source_url'],'video_id':asset['id'],
            'audio_scope':'embedded_original_asset_only','external_audio':False,'reuse_scope':'extract_supplied_audiovisual_episode',
            'eligibility_scope':'candidate_selection_only','publish_readiness_required':True,
            'evidence_spans':{key:{'field':'campaign.description','start':matched.start(key),'end':matched.end(key),'text':matched[key]}
                              for key in ('commission','recommendation','rate','threshold')},
            'editorial_requirement':requirements,'reference_membership_indexes':membership,
            'recommendation_requires_external_music':False,'on_video_ad_disclosure_required':False,
            'show_attribution':matched['show'],'creator_attribution':matched['host'],'publisher_attribution':matched['publisher'],
            'ranking_regime_digest':version({'compiler_version':COMMISSION_VERSION,'campaign_id':campaign['id'],
                'description':description,'editorial_requirement':requirements,'tiktok_payout':payout,'channel_id':asset['channel_id'],
                'audio_scope':'embedded_original_asset_only','external_audio':False})}


# Code-owned authority. Callers may name a registered version, never supply code.
COMPILERS = {COMMISSION_VERSION:commission_permission}


SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS catalog_stream(id INTEGER PRIMARY KEY CHECK(id=1),cursor TEXT,end_pending INTEGER NOT NULL DEFAULT 0,
 next_check REAL NOT NULL DEFAULT 0,observed_at TEXT);
INSERT OR IGNORE INTO catalog_stream(id) VALUES(1);
CREATE TABLE IF NOT EXISTS catalog_cooldowns(provider TEXT PRIMARY KEY,until REAL NOT NULL,failure TEXT);
CREATE TABLE IF NOT EXISTS catalog_page_cursors(cursor_hash TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS catalog_blobs(version TEXT PRIMARY KEY,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS catalog_campaigns(id TEXT PRIMARY KEY,current_ref TEXT,state TEXT NOT NULL,funding TEXT,observed_at REAL);
CREATE TABLE IF NOT EXISTS catalog_work(kind TEXT NOT NULL,id TEXT NOT NULL,campaign_id TEXT NOT NULL,url TEXT,
 input_version TEXT NOT NULL,data TEXT NOT NULL,value_ref TEXT,status TEXT NOT NULL DEFAULT 'pending',
 due REAL NOT NULL DEFAULT 0,failures INTEGER NOT NULL DEFAULT 0,failure TEXT,PRIMARY KEY(kind,id));
CREATE INDEX IF NOT EXISTS catalog_work_due ON catalog_work(kind,status,due,id);
CREATE TABLE IF NOT EXISTS catalog_sources(id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL,url TEXT NOT NULL,facts_version TEXT NOT NULL,
 current_version TEXT NOT NULL,state TEXT NOT NULL,reason TEXT,next_check REAL NOT NULL,observed_at REAL,UNIQUE(campaign_id,url));
CREATE INDEX IF NOT EXISTS catalog_eligible ON catalog_sources(state,id);
CREATE TABLE IF NOT EXISTS catalog_asset_observations(source_id TEXT PRIMARY KEY,availability TEXT,observed_at TEXT);
CREATE TABLE IF NOT EXISTS catalog_versions(source_id TEXT NOT NULL,version TEXT NOT NULL,facts_ref TEXT NOT NULL,
 compiler_version TEXT,permission_ref TEXT,PRIMARY KEY(source_id,version));
"""


def stable_campaign(detail):
    """Exact participant commission facts; funding remains an observation."""
    stable={key:detail.get(key) for key in ('id','name','description','platforms','private','requiresApplication','referenceMaterials','creatorRequirements')}
    payouts=detail.get('payouts')
    row=next((row for row in payouts if type(row) is dict and row.get('platform')=='tiktok'),{}) if type(payouts) is list else {}
    stable['tiktok_payout']={key:row.get(key) for key in ('platform','payoutType','rateCents','minPayoutCents','maxPayoutCents')}
    return stable


class SourceCatalog:
    """Private operational DB independent of execution configuration hashes.

    Trusted injected providers expose binding and bounded campaigns_page,
    campaign, brief and asset methods. Each call accepts deadline (monotonic).
    Page DTO: rows,next_cursor,provider_end,observed_at,scope=collapsed_groups.
    Other methods return their owning SDK's verified normalized dictionary.
    """
    def __init__(self, database, *, clock=time.time, monotonic=time.monotonic):
        self.path = Path(database).absolute()
        self.clock, self.monotonic = clock, monotonic
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.resolve()!=self.path:raise SafetyError('catalog_database_path_unsafe')
        parent = self.path.parent.stat()
        if parent.st_uid != os.getuid() or parent.st_mode & 0o022:
            raise SafetyError('catalog_parent_ownership_invalid')
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o077:
                raise SafetyError('catalog_database_ownership_invalid')
            self.inode = (info.st_dev,info.st_ino)
        finally:
            os.close(fd)
        with self._db() as db:db.executescript(SCHEMA)

    @contextmanager
    def _db(self):
        info = self.path.lstat()
        if not stat.S_ISREG(info.st_mode) or (info.st_dev,info.st_ino) != self.inode or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_mode&0o077:
            raise SafetyError('catalog_database_replaced')
        db = sqlite3.connect(self.path,timeout=2)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:yield db
        finally:db.close()

    @contextmanager
    def _refresh_lock(self):
        fd=os.open(str(self.path)+'.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_nlink!=1:
                raise SafetyError('catalog_lock_ownership_invalid')
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise SafetyError('catalog_refresh_already_running') from None
            yield
        finally:os.close(fd)

    def _bind(self, providers):
        if type(providers.binding) is not dict:raise SafetyError('catalog_provider_binding_invalid')
        bound=encoded(providers.binding)
        if len(bound.encode())>4096:raise SafetyError('catalog_provider_binding_exceeds_bound')
        with self._db() as db:
            row=db.execute("SELECT value FROM catalog_settings WHERE key='binding'").fetchone()
            if row is not None and row[0]!=bound:raise SafetyError('catalog_provider_binding_changed')
            db.execute("INSERT OR IGNORE INTO catalog_settings VALUES('binding',?)",(bound,))

    def _put(self, db, value):
        serialized=encoded(value);reference=hashlib.sha256(serialized.encode()).hexdigest()
        db.execute('INSERT OR IGNORE INTO catalog_blobs VALUES(?,?)',(reference,serialized))
        return reference

    def _blob(self, reference):
        with self._db() as db:row=db.execute('SELECT length(data),substr(data,1,?) FROM catalog_blobs WHERE version=?',(MAX_EVIDENCE_BYTES+1,reference)).fetchone()
        if row is None:raise SafetyError('catalog_evidence_missing')
        if row[0]>MAX_EVIDENCE_BYTES:raise SafetyError('catalog_evidence_exceeds_bound')
        value=json.loads(row[1])
        if version(value)!=reference:raise SafetyError('catalog_evidence_integrity_changed')
        return value

    def _cooldown(self, provider):
        with self._db() as db:row=db.execute('SELECT until FROM catalog_cooldowns WHERE provider=?',(provider,)).fetchone()
        return row[0] if row is not None and row[0]>self.clock() else None

    def _failure(self,error,provider,policy,failures):
        delay=getattr(error,'retry_after_seconds',None)
        if delay is not None and (type(delay) not in (int,float) or not math.isfinite(delay) or delay<0):
            raise SafetyError('catalog_provider_retry_delay_invalid')
        category=getattr(error,'category','invalid_data' if isinstance(error,SafetyError) else 'transient')
        if category not in ('auth','access_denied','rate_limit','transient','upstream','invalid_data','invalid_request','not_ready'):category='upstream'
        code=getattr(error,'code',None)
        if code is not None and (type(code) is not str or not re.fullmatch('[A-Za-z0-9_:-]{1,128}',code)):code=None
        status=getattr(error,'status',None)
        if status is not None and (type(status) is not int or not 100<=status<=599):status=None
        failure={'provider':provider,'category':category,'code':code,'status':status,'retry_after_seconds':delay,'observed_at':self.clock()}
        local=min(policy['max_seconds'],policy['base_seconds']*2**min(failures,20));until=self.clock()+max(local,delay or 0)
        with self._db() as db:
            if category=='rate_limit' or delay is not None:
                db.execute('INSERT INTO catalog_cooldowns VALUES(?,?,?) ON CONFLICT(provider) DO UPDATE SET until=max(until,excluded.until),failure=excluded.failure',(provider,until,encoded(failure)))
        return failure,until

    def _queue(self,db,kind,identifier,campaign_id,url,data):
        serialized=encoded(data);revision=version(data)
        db.execute("INSERT INTO catalog_work(kind,id,campaign_id,url,input_version,data,due) VALUES(?,?,?,?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET input_version=excluded.input_version,data=excluded.data,status=CASE WHEN input_version!=excluded.input_version OR status='obsolete' THEN 'pending' ELSE status END,due=CASE WHEN input_version!=excluded.input_version OR status='obsolete' THEN excluded.due ELSE due END,value_ref=CASE WHEN input_version!=excluded.input_version OR status='obsolete' THEN NULL ELSE value_ref END",
                   (kind,identifier,campaign_id,url,revision,serialized,self.clock()))

    def _due(self,kind,limit):
        with self._db() as db:return [dict(row) for row in db.execute("SELECT * FROM catalog_work WHERE kind=? AND status!='obsolete' AND due<=? ORDER BY due,id LIMIT ?",(kind,self.clock(),limit))]

    def _saved(self,work,value_ref,policy,status='ok'):
        with self._db() as db:
            saved=db.execute('UPDATE catalog_work SET value_ref=?,status=?,due=?,failures=0,failure=NULL WHERE kind=? AND id=? AND input_version=?',
                             (value_ref,status,self.clock()+policy['refresh_seconds'],work['kind'],work['id'],work['input_version']))
            if saved.rowcount and status=='ok':
                self._progress(db,work['kind'])

    def _progress(self,db,kind):
        db.execute("INSERT INTO catalog_settings VALUES('last_progress',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (encoded({'recorded_at':self.clock(),'kind':kind}),))

    def refresh(self,providers,*,page_budget,campaign_budget,brief_budget,asset_budget,retry_policy,timeout_seconds):
        for budget in (page_budget,campaign_budget,brief_budget,asset_budget):positive(budget,MAX_CALL_BUDGET)
        if page_budget<2:raise SafetyError('catalog_page_budget_must_include_head_and_continuation')
        if type(retry_policy) is not dict or set(retry_policy)!={'base_seconds','max_seconds','refresh_seconds'}:raise SafetyError('catalog_retry_policy_invalid')
        if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in retry_policy.values()) or retry_policy['base_seconds']>retry_policy['max_seconds']:raise SafetyError('catalog_retry_policy_invalid')
        if type(timeout_seconds) not in (int,float) or not math.isfinite(timeout_seconds) or not 0<timeout_seconds<=3600:raise SafetyError('catalog_timeout_invalid')
        deadline=self.monotonic()+timeout_seconds
        with self._refresh_lock():
            self._bind(providers)
            started_at=self.clock()
            with self._db() as db:
                db.execute("INSERT OR IGNORE INTO catalog_settings VALUES('first_refresh_started',?)",(encoded(started_at),))
                db.execute("INSERT INTO catalog_settings VALUES('last_refresh_started',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(encoded(started_at),))
                db.execute("INSERT INTO catalog_settings VALUES('refresh_running','true') ON CONFLICT(key) DO UPDATE SET value='true'")
            report={'pages_read':0,'campaigns_updated':0,'briefs_updated':0,'sources_updated':0,'scope':'collapsed_groups','provider_end':False,'failures':[]}
            self._walk(providers,page_budget,retry_policy,deadline,report)
            for kind,provider,budget in (('detail','whop',campaign_budget),('brief','google',brief_budget),('asset','youtube',asset_budget)):
                for work in self._due(kind,budget):
                    if self.monotonic()>=deadline or self._cooldown(provider) is not None:break
                    try:
                        value=getattr(self,'_'+kind)(providers,work,deadline,retry_policy)
                        if value:report[{'detail':'campaigns_updated','brief':'briefs_updated','asset':'sources_updated'}[kind]]+=1
                    except Exception as error:
                        failure,until=self._failure(error,provider,retry_policy,work['failures'])
                        with self._db() as db:
                            db.execute("UPDATE catalog_work SET status='failed',failures=failures+1,failure=?,due=? WHERE kind=? AND id=?",(encoded(failure),until,kind,work['id']))
                            if kind=='asset':
                                db.execute("UPDATE catalog_sources SET state='stale',reason='refresh_failed',next_check=? WHERE id=?",(until,work['id']))
                            else:
                                db.execute("UPDATE catalog_sources SET state='stale',reason='refresh_failed',next_check=? WHERE campaign_id=?",(until,work['campaign_id']))
                        report['failures'].append(failure)
            with self._db() as db:
                report['next_cursor']=db.execute('SELECT cursor FROM catalog_stream WHERE id=1').fetchone()[0]
                report['cooldowns']={row['provider']:row['until'] for row in db.execute('SELECT * FROM catalog_cooldowns WHERE until>?',(self.clock(),))}
            report['deadline_reached']=self.monotonic()>=deadline
            report['started_at']=started_at;report['finished_at']=self.clock()
            with self._db() as db:
                db.execute("INSERT INTO catalog_settings VALUES('last_refresh',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(encoded(report),))
                db.execute("UPDATE catalog_settings SET value='false' WHERE key='refresh_running'")
            return report

    def _walk(self,providers,budget,policy,deadline,report):
        with self._db() as db:stream=dict(db.execute('SELECT * FROM catalog_stream WHERE id=1').fetchone())
        if self._cooldown('whop') is not None or stream['next_check']>self.clock():return
        if stream['end_pending']:
            with self._db() as db:
                db.execute('DELETE FROM catalog_page_cursors')
                db.execute('UPDATE catalog_stream SET end_pending=0 WHERE id=1')
        resume=None if stream['end_pending'] else stream['cursor'];cursor=None;seen=set()
        for index in range(budget):
            if self.monotonic()>=deadline:break
            try:
                page=providers.campaigns_page(limit=MAX_PAGE,sort='newest',cursor=cursor,deadline=deadline)
                if type(page) is not dict or page.get('scope')!='collapsed_groups' or type(page.get('rows')) is not list or len(page['rows'])>MAX_PAGE or any(type(row) is not dict for row in page['rows']):raise SafetyError('catalog_campaign_page_schema_changed')
                observed=text(page.get('observed_at'));next_cursor=page.get('next_cursor')
                if type(page.get('provider_end')) is not bool or page['provider_end']!=(next_cursor is None):raise SafetyError('catalog_campaign_pagination_changed')
                if next_cursor is not None and (not page['rows'] or text(next_cursor,MAX_CURSOR_BYTES) in seen or next_cursor==cursor):raise SafetyError('catalog_campaign_cursor_invalid')
                ids=[text(row.get('id'),256) for row in page['rows']]
                if len(ids)!=len(set(ids)):raise SafetyError('catalog_campaign_duplicates')
                for row in page['rows']:encoded(row)
                progress=resume if index==0 and resume is not None and not page['provider_end'] else next_cursor
                with self._db() as db:
                    if cursor is not None:
                        if next_cursor is not None and db.execute('SELECT 1 FROM catalog_page_cursors WHERE cursor_hash=?',(version(next_cursor),)).fetchone():
                            raise SafetyError('catalog_campaign_cursor_cycle')
                        db.execute('INSERT INTO catalog_page_cursors VALUES(?)',(version(cursor),))
                    for identifier in ids:self._queue(db,'detail',identifier,identifier,None,{'id':identifier})
                    db.execute('UPDATE catalog_stream SET cursor=?,end_pending=?,observed_at=?,next_check=? WHERE id=1',(progress,int(page['provider_end']),observed,self.clock()+policy['refresh_seconds'] if page['provider_end'] else 0))
                    success={'provider_observed_at':observed,'recorded_at':self.clock()}
                    self._progress(db,'page')
                    db.execute("INSERT INTO catalog_settings VALUES('last_successful_page',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(encoded(success),))
                    if page['provider_end']:db.execute("INSERT INTO catalog_settings VALUES('last_provider_end',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(encoded(success),))
                report['pages_read']+=1
                if page['provider_end']:report['provider_end']=True;break
                seen.add(next_cursor);cursor=progress
            except Exception as error:
                failure,until=self._failure(error,'whop',policy,0)
                with self._db() as db:db.execute('UPDATE catalog_stream SET next_check=? WHERE id=1',(until,))
                report['failures'].append(failure);break

    def _campaign_state(self,detail):
        if detail.get('status')!='active':return 'campaign_inactive'
        if detail.get('private') is not False:return 'campaign_private_or_unknown'
        if detail.get('requiresApplication') is not False:return 'application_required_or_unknown'
        if type(detail.get('platforms')) is not list or 'tiktok' not in detail['platforms']:return 'not_tiktok'
        payouts=detail.get('payouts');rows=[row for row in payouts if type(row) is dict and row.get('platform')=='tiktok'] if type(payouts) is list else []
        if len(rows)!=1:return 'payout_missing_or_ambiguous'
        row=rows[0]
        for key in ('rateCents','minPayoutCents','maxPayoutCents'):
            if type(row.get(key)) is not int or row[key]<0:return 'payout_schema_unknown'
        if row['rateCents']<=0:return 'unfunded_or_unknown_rate'
        if row.get('budgetCents') is None and row.get('spentCents') is None:return 'funding_unknown'
        for key in ('budgetCents','spentCents'):
            if type(row.get(key)) is not int or row[key]<0:return 'payout_schema_unknown'
        return 'unfunded_or_unknown_rate' if row['budgetCents']<=row['spentCents'] or row['rateCents']<=0 else 'funded'

    def _detail(self,providers,work,deadline,policy):
        detail=providers.campaign(work['campaign_id'],deadline=deadline)
        if type(detail) is not dict or detail.get('id')!=work['campaign_id']:raise SafetyError('catalog_campaign_identity_changed')
        encoded(detail);state=self._campaign_state(detail)
        stable=stable_campaign(detail)
        payouts=detail.get('payouts')
        row=next((row for row in payouts if type(row) is dict and row.get('platform')=='tiktok'),{}) if type(payouts) is list else {}
        with self._db() as db:
            reference=self._put(db,stable);previous=db.execute('SELECT * FROM catalog_campaigns WHERE id=?',(work['campaign_id'],)).fetchone()
            db.execute('INSERT INTO catalog_campaigns VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET current_ref=excluded.current_ref,state=excluded.state,funding=excluded.funding,observed_at=excluded.observed_at',
                       (work['campaign_id'],reference,state,encoded({'budget_cents':row.get('budgetCents'),'spent_cents':row.get('spentCents')}),self.clock()))
            if state not in ('funded','funding_unknown') or previous is None or previous['current_ref']!=reference:
                db.execute("UPDATE catalog_sources SET state='stale',reason=?,next_check=? WHERE campaign_id=?",(state,self.clock(),work['campaign_id']))
            if state in ('funded','funding_unknown'):
                references=stable['referenceMaterials']
                if type(references) is not list:raise SafetyError('catalog_campaign_references_missing')
                for item in references:
                    if type(item) is not dict or type(item.get('url')) is not str:continue
                    url=item['url'];parsed=urlparse(url)
                    if parsed.scheme=='https' and parsed.hostname=='docs.google.com' and re.fullmatch('/document/d/[A-Za-z0-9_-]+/edit',parsed.path) and not parsed.username and not parsed.password:
                        self._queue(db,'brief',version({'campaign':work['campaign_id'],'url':url}),work['campaign_id'],url,{'campaign_ref':reference})
        self._saved(work,reference,policy);self._assemble(work['campaign_id']);return True

    def _brief(self,providers,work,deadline,policy):
        context=json.loads(work['data'])
        with self._db() as db:campaign=db.execute('SELECT * FROM catalog_campaigns WHERE id=?',(work['campaign_id'],)).fetchone()
        if campaign is None or campaign['state'] not in ('funded','funding_unknown') or campaign['current_ref']!=context['campaign_ref']:
            self._saved(work,None,policy,'obsolete');return False
        brief=providers.brief(work['url'],deadline=deadline)
        document_id=urlparse(work['url']).path.split('/')[3]
        if type(brief) is not dict or brief.get('documentId')!=document_id or type(brief.get('content')) is not str:raise SafetyError('catalog_brief_identity_changed')
        stable={key:value for key,value in brief.items() if key!='observed_at'};stable['url']=work['url']
        links=stable.get('links',[])
        if type(links) is not list or any(type(link) is not str for link in links):raise SafetyError('catalog_brief_links_invalid')
        with self._db() as db:
            reference=self._put(db,stable)
            if reference!=work['value_ref']:db.execute("UPDATE catalog_sources SET state='stale',reason='brief_changed',next_check=? WHERE campaign_id=?",(self.clock(),work['campaign_id']))
        self._saved(work,reference,policy)
        if brief.get('suggestions_view_mode')!='SUGGESTIONS_INLINE' or brief.get('tabs_complete') is not True or brief.get('suggestions_present') is not False:
            raise SafetyError('catalog_brief_unresolved_or_unavailable_suggestions')
        self._assemble(work['campaign_id']);return True

    def _assemble(self,campaign_id):
        with self._db() as db:
            campaign=db.execute('SELECT * FROM catalog_campaigns WHERE id=?',(campaign_id,)).fetchone()
            if campaign is None or campaign['state'] not in ('funded','funding_unknown'):return
            details=self._blob(campaign['current_ref']);urls=set();brief_refs=[];complete=True
            references=details['referenceMaterials']
            for item in references:
                if type(item) is dict and type(item.get('url')) is str:
                    canonical=video_url(item['url'])
                    if canonical:urls.add(canonical)
            rows=db.execute("SELECT * FROM catalog_work WHERE kind='brief' AND campaign_id=?",(campaign_id,)).fetchall()
            current=[row for row in rows if json.loads(row['data']).get('campaign_ref')==campaign['current_ref']]
            for row in current:
                if row['status']!='ok' or row['value_ref'] is None or row['due']<=self.clock():complete=False;continue
                brief=self._blob(row['value_ref']);brief_refs.append(row['value_ref'])
                for link in brief.get('links',[])+re.findall(r'https://[^\s<>"\\]+',brief['content']):
                    canonical=video_url(link)
                    if canonical:urls.add(canonical)
            context={'campaign_ref':campaign['current_ref'],'brief_refs':sorted(brief_refs),'complete':complete}
            for url in sorted(urls):self._queue(db,'asset',version({'campaign':campaign_id,'url':url}),campaign_id,url,context)
            for work in db.execute("SELECT id,url FROM catalog_work WHERE kind='asset' AND campaign_id=?",(campaign_id,)).fetchall():
                if work['url'] not in urls or not complete:
                    db.execute("UPDATE catalog_work SET status='obsolete' WHERE kind='asset' AND id=?",(work['id'],))
            for source in db.execute('SELECT id,url FROM catalog_sources WHERE campaign_id=?',(campaign_id,)).fetchall():
                if source['url'] not in urls or not complete:db.execute("UPDATE catalog_sources SET state='ineligible',reason='source_scope_missing_or_incomplete' WHERE id=?",(source['id'],))

    def _asset(self,providers,work,deadline,policy):
        context=json.loads(work['data'])
        with self._db() as db:
            campaign=db.execute('SELECT * FROM catalog_campaigns WHERE id=?',(work['campaign_id'],)).fetchone()
            briefs=[row for row in db.execute("SELECT * FROM catalog_work WHERE kind='brief' AND campaign_id=?",(work['campaign_id'],))
                    if json.loads(row['data']).get('campaign_ref')==context['campaign_ref']]
            brief_current=all(row['status']=='ok' and row['value_ref'] and row['due']>self.clock() for row in briefs)
            brief_current=brief_current and sorted(row['value_ref'] for row in briefs if row['value_ref'])==context['brief_refs']
            detail=db.execute("SELECT * FROM catalog_work WHERE kind='detail' AND id=?",(work['campaign_id'],)).fetchone()
            detail_current=detail is not None and detail['status']=='ok' and detail['due']>self.clock()
        if campaign is None or campaign['state'] not in ('funded','funding_unknown') or campaign['current_ref']!=context['campaign_ref'] or not context['complete'] or not brief_current or not detail_current:
            self._saved(work,None,policy,'obsolete');return False
        asset=providers.asset(work['url'],deadline=deadline)
        if type(asset) is not dict or asset.get('id')!=parse_qs(urlparse(work['url']).query)['v'][0]:raise SafetyError('catalog_asset_identity_changed')
        stable=stable_asset(asset)
        availability=asset.get('transcript_availability');observed=asset.get('observed_at')
        if availability is not None:
            if type(availability) is not dict or set(availability)!={'manual_language_codes','automatic_language_codes','kind'} or availability['kind']!='extractor_reported_language_codes':raise SafetyError('catalog_transcript_availability_invalid')
            for name in ('manual_language_codes','automatic_language_codes'):
                codes=availability[name]
                if codes is not None and (type(codes) is not list or len(codes)>512 or len(set(codes))!=len(codes) or any(type(code) is not str or not re.fullmatch('[A-Za-z0-9_-]{1,64}',code) for code in codes)):raise SafetyError('catalog_transcript_availability_invalid')
        if observed is not None:text(observed,128)
        with self._db() as db:
            db.execute('INSERT INTO catalog_asset_observations VALUES(?,?,?) ON CONFLICT(source_id) DO UPDATE SET availability=excluded.availability,observed_at=excluded.observed_at',(work['id'],encoded(availability) if availability is not None else None,observed))
            asset_ref=self._put(db,stable)
            facts_ref=self._put(db,{'campaign_ref':context['campaign_ref'],'brief_refs':context['brief_refs'],'asset_ref':asset_ref,'source_url':work['url']})
            identifier=work['id'];existing=db.execute('SELECT * FROM catalog_sources WHERE id=?',(identifier,)).fetchone()
            db.execute('INSERT OR IGNORE INTO catalog_versions VALUES(?,?,?,NULL,NULL)',(identifier,facts_ref,facts_ref))
            if existing is None or existing['facts_version']!=facts_ref:
                db.execute("INSERT INTO catalog_sources VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET facts_version=excluded.facts_version,current_version=excluded.current_version,state='pending_permission',reason=NULL,next_check=excluded.next_check,observed_at=excluded.observed_at",
                           (identifier,work['campaign_id'],work['url'],facts_ref,facts_ref,'pending_permission',None,self.clock()+policy['refresh_seconds'],self.clock()))
            else:db.execute('UPDATE catalog_sources SET next_check=?,observed_at=? WHERE id=?',(self.clock()+policy['refresh_seconds'],self.clock(),identifier))
        self._saved(work,asset_ref,policy)
        for compiler in sorted(COMPILERS):
            if self.admit(identifier,facts_ref,compiler)['eligible']:break
        else:
            with self._db() as db:db.execute("UPDATE catalog_sources SET state='pending_permission',reason='unsupported_permission_contract' WHERE id=?",(identifier,))
        return True

    def get_version(self,source_id,evidence_version):
        text(source_id,256);text(evidence_version,128)
        with self._db() as db:row=db.execute('SELECT * FROM catalog_versions WHERE source_id=? AND version=?',(source_id,evidence_version)).fetchone()
        if row is None:raise SafetyError('catalog_version_missing')
        refs=self._blob(row['facts_ref'])
        # Check serialized aggregate size before materializing all brief bodies.
        with self._db() as db:
            total=sum(db.execute('SELECT length(data) FROM catalog_blobs WHERE version=?',(reference,)).fetchone()[0]
                      for reference in [refs['campaign_ref'],refs['asset_ref'],*refs['brief_refs']])
        if total+len(refs['source_url'].encode())+128>MAX_EVIDENCE_BYTES:raise SafetyError('catalog_evidence_exceeds_bound')
        evidence={'campaign':self._blob(refs['campaign_ref']),'briefs':[self._blob(ref) for ref in refs['brief_refs']],
                  'asset':self._blob(refs['asset_ref']),'source_url':refs['source_url']}
        encoded(evidence)
        return {'source_id':source_id,'evidence_version':evidence_version,'facts_version':row['facts_ref'],'evidence':evidence,
                'compiler_version':row['compiler_version'],'permission':self._blob(row['permission_ref']) if row['permission_ref'] else None}

    def candidate_evidence(self,source_id,evidence_version):return self.get_version(source_id,evidence_version)['evidence']

    def provider_binding(self):
        with self._db() as db:
            row=db.execute("SELECT value FROM catalog_settings WHERE key='binding'").fetchone()
        return None if row is None else json.loads(row[0])

    def source_observation(self,source_id):
        with self._db() as db:row=db.execute('SELECT * FROM catalog_asset_observations WHERE source_id=?',(source_id,)).fetchone()
        if row is None:return None
        return {'transcript_availability':json.loads(row['availability']) if row['availability'] is not None else None,'observed_at':row['observed_at']}

    def validate_current(self,source_id,evidence_version):
        """Current candidate permission; historical get_version never authorizes use."""
        snapshot=self.get_version(source_id,evidence_version)
        compiler=COMPILERS.get(snapshot['compiler_version'])
        if compiler is None:raise SafetyError('catalog_permission_compiler_revoked_or_unknown')
        permission=compiler(snapshot['evidence'])
        if permission is None or permission!=snapshot['permission']:
            raise SafetyError('catalog_permission_compiler_changed')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            source=db.execute('SELECT * FROM catalog_sources WHERE id=?',(source_id,)).fetchone()
            if source is None or source['state']!='eligible' or source['current_version']!=evidence_version:
                raise SafetyError('catalog_current_permission_changed')
            fresh_until=self._fresh_until(db,source)
            if fresh_until is None:raise SafetyError('catalog_current_dependencies_stale')
            campaign=db.execute('SELECT state,funding FROM catalog_campaigns WHERE id=?',(source['campaign_id'],)).fetchone()
        funding=json.loads(campaign['funding'])
        return {**snapshot,'current_version':evidence_version,'fresh_until':fresh_until,'checked_at':self.clock(),
                'funding':{**funding,'scope':'platform' if campaign['state']=='funded' else 'unknown','state':campaign['state']},
                'eligibility_scope':'candidate_selection_only','publish_readiness_required':True}

    def _fresh_until(self,db,source):
        """All mutable dependency reads must remain current at admission/use."""
        refs=self._blob(source['facts_version'])
        campaign=db.execute('SELECT * FROM catalog_campaigns WHERE id=?',(source['campaign_id'],)).fetchone()
        if campaign is None or campaign['state'] not in ('funded','funding_unknown') or campaign['current_ref']!=refs['campaign_ref']:return None
        detail=db.execute("SELECT * FROM catalog_work WHERE kind='detail' AND id=?",(source['campaign_id'],)).fetchone()
        asset=db.execute("SELECT * FROM catalog_work WHERE kind='asset' AND id=?",(source['id'],)).fetchone()
        tasks=[detail,asset]
        briefs=[row for row in db.execute("SELECT * FROM catalog_work WHERE kind='brief' AND campaign_id=?",(source['campaign_id'],))
                if json.loads(row['data']).get('campaign_ref')==campaign['current_ref']]
        if sorted(row['value_ref'] for row in briefs if row['value_ref'])!=refs['brief_refs']:return None
        tasks+=briefs
        if any(row is None or row['status']!='ok' or row['due']<=self.clock() for row in tasks):return None
        return min(row['due'] for row in tasks)

    def admit(self,source_id,evidence_version,compiler_version):
        compiler=COMPILERS.get(compiler_version)
        evidence=self.candidate_evidence(source_id,evidence_version)
        permission=compiler(evidence) if compiler else None
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            source=db.execute('SELECT * FROM catalog_sources WHERE id=?',(source_id,)).fetchone()
            if source is None or source['facts_version']!=evidence_version:raise SafetyError('catalog_admission_version_changed')
            fresh_until=self._fresh_until(db,source)
            if fresh_until is None:raise SafetyError('catalog_admission_dependencies_stale')
            if permission is None:
                reason='unsupported_permission_contract' if compiler is None else 'permission_contract_not_matched'
                db.execute("UPDATE catalog_sources SET state='ineligible',reason=? WHERE id=?",(reason,source_id))
                return {'eligible':False,'reason':reason}
            permission_ref=self._put(db,permission);revision=version({'facts_version':evidence_version,'compiler_version':compiler_version,'permission_ref':permission_ref})
            db.execute('INSERT OR IGNORE INTO catalog_versions VALUES(?,?,?,?,?)',(source_id,revision,evidence_version,compiler_version,permission_ref))
            changed=db.execute("UPDATE catalog_sources SET current_version=?,state='eligible',reason=NULL,next_check=? WHERE id=? AND facts_version=? AND current_version=?",
                               (revision,fresh_until,source_id,evidence_version,source['current_version']))
            if changed.rowcount!=1:raise SafetyError('catalog_admission_version_changed')
        return {'eligible':True,'source_id':source_id,'evidence_version':revision,'compiler_version':compiler_version}

    def status(self):
        """Bounded operational evidence; collapsed-group absence is not global emptiness."""
        with self._db() as db:
            settings={row['key']:json.loads(row['value']) for row in db.execute("SELECT * FROM catalog_settings WHERE key IN ('binding','last_refresh','last_refresh_started','first_refresh_started','last_progress','last_successful_page','last_provider_end','refresh_running')")}
            scan=dict(db.execute('SELECT * FROM catalog_stream WHERE id=1').fetchone())
            counts={row['state']:row['count'] for row in db.execute('SELECT state,count(*) AS count FROM catalog_sources GROUP BY state')}
            pending=db.execute("SELECT count(*) FROM catalog_work WHERE status IN ('pending','failed')").fetchone()[0]
            failures=[{'provider':{'detail':'whop','brief':'google','asset':'youtube'}[row['kind']], 'category':row['category'], 'count':row['count']}
                      for row in db.execute("SELECT kind,json_extract(failure,'$.category') AS category,count(*) AS count FROM catalog_work WHERE status='failed' GROUP BY kind,category")]
            cooldowns={row['provider']:row['until'] for row in db.execute('SELECT * FROM catalog_cooldowns WHERE until>?',(self.clock(),))}
            compilers=sorted(COMPILERS)
            eligible=db.execute("SELECT count(*) FROM catalog_sources s JOIN catalog_versions v ON v.source_id=s.id AND v.version=s.current_version WHERE s.state='eligible' AND s.next_check>? AND v.compiler_version IN ("+','.join('?' for _ in compilers)+")",(self.clock(),*compilers)).fetchone()[0] if compilers else 0
        latest=settings.get('last_refresh')
        if latest is not None:latest={key:value for key,value in latest.items() if key!='next_cursor'}
        return {'binding_digest':version(settings['binding']) if 'binding' in settings else None,
                'last_refresh':latest,'refresh_interrupted_or_in_progress':settings.get('refresh_running',False),
                'scan':{'scope':'collapsed_groups','cursor_present':scan['cursor'] is not None,'current_pass_provider_end':bool(scan['end_pending']),
                        'next_check':scan['next_check'],'last_successful_page':settings.get('last_successful_page'),'last_provider_end':settings.get('last_provider_end'),
                        'last_progress':settings.get('last_progress'),'first_refresh_started':settings.get('first_refresh_started')},
                'eligible_count':eligible,'state_counts':counts,'pending_dependency_count':pending,'unit_failures':failures,'cooldowns':cooldowns,
                'eligibility_scope':'candidate_selection_only','global_empty_proven':False}

    def eligible(self,*,limit,after=None):
        positive(limit,1000)
        if after is not None:text(after,256)
        with self._db() as db:
            compilers=sorted(COMPILERS)
            rows=[dict(row) for row in db.execute("SELECT s.* FROM catalog_sources s JOIN catalog_versions v ON v.source_id=s.id AND v.version=s.current_version WHERE s.state='eligible' AND s.next_check>? AND s.id>? AND v.compiler_version IN ("+','.join('?' for _ in compilers)+") ORDER BY s.id LIMIT ?",(self.clock(),after or '',*compilers,limit+1))] if compilers else []
            selected=rows[:limit]
            for row in selected:
                campaign=db.execute('SELECT state,funding FROM catalog_campaigns WHERE id=?',(row['campaign_id'],)).fetchone()
                row['campaign_funding_state']=campaign['state'];row['platform_funding']=json.loads(campaign['funding'])
        return {'sources':selected,'after':rows[limit-1]['id'] if len(rows)>limit else None,'complete':len(rows)<=limit,
                'eligibility_scope':'candidate_selection_only','publish_readiness_required':True}


class SDKProviders:
    """Trusted owning SDK transport; no model-supplied permission or API code."""
    def __init__(self,*,whop_profile,whop_account_id,google_profile):
        from whop_cli.config import Config,rewards_location
        from google_cli.config import Config as GoogleConfig
        if any(type(name) is not str or not re.fullmatch('[A-Za-z0-9_-]{1,64}',name) for name in (whop_profile,google_profile)):
            raise SafetyError('catalog_provider_profile_invalid')
        if type(whop_account_id) is not str or not re.fullmatch('user_[A-Za-z0-9]+',whop_account_id):raise SafetyError('catalog_provider_actor_invalid')
        self.whop_config=Config(profile=whop_profile);self.google_config=GoogleConfig(profile=google_profile)
        origin,path=rewards_location(self.whop_config.rewards_url)
        self.binding={'whop_profile':whop_profile,'whop_account_id':whop_account_id,'google_profile':google_profile,'experience':origin+path}

    @staticmethod
    def _remaining(deadline):
        budget=deadline-time.monotonic()
        if budget<1:raise SafetyError('catalog_provider_deadline_exceeded')
        return min(3600,budget)

    def campaigns_page(self,*,limit,sort,cursor,deadline):
        from whop_cli.client import WhopClient
        return WhopClient.campaigns_page_bounded(self.whop_config,expected_account_id=self.binding['whop_account_id'],
            limit=limit,sort=sort,cursor=cursor,timeout_seconds=self._remaining(deadline),max_bytes=MAX_EVIDENCE_BYTES)

    def campaign(self,campaign_id,*,deadline):
        from whop_cli.client import WhopClient
        return WhopClient.campaign_bounded(self.whop_config,campaign_id,expected_account_id=self.binding['whop_account_id'],
            timeout_seconds=self._remaining(deadline),max_bytes=MAX_EVIDENCE_BYTES)

    def brief(self,url,*,deadline):
        from google_cli.client import GoogleClient
        parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.hostname!='docs.google.com' or parsed.username or parsed.password or not re.fullmatch('/document/d/[A-Za-z0-9_-]+/edit',parsed.path):raise SafetyError('catalog_brief_url_unsupported')
        return GoogleClient.read_document_bounded(self.google_config,parsed.path.split('/')[3],
            timeout_seconds=self._remaining(deadline),max_bytes=MAX_EVIDENCE_BYTES)

    def asset(self,url,*,deadline):
        from youtube_cli.client import YoutubeClient
        canonical=video_url(url)
        if canonical is None:raise SafetyError('catalog_asset_url_unsupported')
        return YoutubeClient.get_source_metadata(canonical,timeout_seconds=self._remaining(deadline),max_bytes=65536)
