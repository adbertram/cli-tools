"""Observed Whop participant reads and explicit journaled submission operations."""
import json
import math
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from types import SimpleNamespace
from urllib.parse import urlencode
from cli_tools_shared.exceptions import ClientError
from .config import get_config, rewards_location

MAX_BODY = 8_000_000
MAX_LIMIT = 1000
READ_ACTIONS = {"listSocialMediaAccounts", "listMySubmissionsAction", "countMySubmissionsAction"}
class WhopError(ClientError):
    """Sanitized provider/SDK failure with an optional minimum retry delay."""
    def __init__(self,code,*,category='invalid_request',status=None,retry_after_seconds=None):
        super().__init__(code)
        self.code=code.split(':',1)[0]
        self.category=category
        self.status=status
        self.retry_after_seconds=retry_after_seconds
        self.retry_after=retry_after_seconds

def retry_after_seconds(raw,now=None):
    if not isinstance(raw,str) or len(raw)>200: return None
    raw=raw.strip()
    if re.fullmatch(r'[0-9]+',raw):
        value=float(raw)
        return value if math.isfinite(value) else None
    try:
        when=parsedate_to_datetime(raw)
        if when.tzinfo is None: return None
        value=(when-(now or datetime.now(timezone.utc))).total_seconds()
        return max(0.0,value) if math.isfinite(value) else None
    except (ValueError,TypeError,OverflowError): return None

FETCH_JS = """async ({path, action, body}) => {
    let reader;
    try {
        const headers = action ? {'Next-Action':action,'Content-Type':'text/plain;charset=UTF-8','Accept':'text/x-component'} : {'Accept':'application/json'};
        const r = await fetch(path, {method:action?'POST':'GET',headers,body:action?JSON.stringify(body):undefined,credentials:'include',signal:AbortSignal.timeout(20000),redirect:'error'});
        const retryAfter=r.headers.get('Retry-After');
        if(!r.body)return {status:r.status,text:null,retryAfter};
        reader=r.body.getReader();const chunks=[];let size=0;
        while(true){const {value,done}=await reader.read();if(done)break;
            size+=value.byteLength;if(size>MAX_BODY)return {status:r.status,text:null,retryAfter,errorClass:'ResponseTooLarge'};
            chunks.push(value);
        }
        const decoder=new TextDecoder();const text=chunks.map(c=>decoder.decode(c,{stream:true})).join('')+decoder.decode();
        return {status:r.status,text,retryAfter};
    } catch (error) {
        const safe = ['AbortError','TimeoutError','TypeError'].includes(error?.name) ? error.name : 'Error';
        return {status:0,text:null,errorClass:safe};
    } finally {if(reader){try{await reader.cancel();}catch(_){}}}
}"""
FETCH_JS = FETCH_JS.replace("MAX_BODY",str(MAX_BODY))

# Lazy route imports may add scripts during a scan. Rediscover complete fresh
# snapshots only within one shared deadline/byte allowance; never retry actions.
DISCOVER_ACTION_JS = r"""async (name) => {
    const sourcesOf=()=>[...new Set([...document.scripts].map(s=>s.src).filter(s=>s&&new URL(s).origin===location.origin))];
    const signal=AbortSignal.timeout(10000);let total=0;
    for(let attempt=1;attempt<=3;attempt++){
    const sources=sourcesOf();
    if(sources.length>120)return {action:null,reason:'script_limit',sources:sources.length,matches:0,failures:0};
    const matches=new Set();let failures=0;
    for(let i=0;i<sources.length;i+=8){
        const texts=await Promise.all(sources.slice(i,i+8).map(async url=>{
            let reader;try{
                const r=await fetch(url,{signal,redirect:'error'});
                if(!r.ok||!r.body)throw Error();
                reader=r.body.getReader();const chunks=[];let size=0;
                while(true){const {value,done}=await reader.read();if(done)break;
                    size+=value.byteLength;total+=value.byteLength;
                    if(size>8000000||total>32000000)throw Error();chunks.push(value);
                }
                const decoder=new TextDecoder();return chunks.map(c=>decoder.decode(c,{stream:true})).join('')+decoder.decode();
            }catch(_){failures++;return '';}finally{if(reader){try{await reader.cancel();}catch(_){}}}
        }));
        for(const text of texts){const re=/createServerReference\)\("([a-f0-9]{40,64})"[^;]{0,160}?"([A-Za-z]+)"/g;
            for(const m of text.matchAll(re))if(m[2]===name)matches.add(m[1]);}
        if(signal.aborted||total>32000000)break;
    }
    const after=sourcesOf(),changed=sources.length!==after.length||after.some(s=>!sources.includes(s));
    const reason=matches.size>1?'ambiguous':failures||signal.aborted?'script_fetch_failed':changed?'scripts_changed':matches.size===1?'ready':'missing';
    if(reason==='scripts_changed'&&attempt<3&&!signal.aborted)continue;
    return {action:reason==='ready'?[...matches][0]:null,reason,sources:sources.length,matches:matches.size,failures,attempts:attempt,afterSources:after.length};
    }

}"""

def strict_json(text):
    if not isinstance(text,str) or len(text)>MAX_BODY:
        raise ClientError("response_too_large_or_missing")
    def constant(_): raise ValueError("nonfinite")
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ValueError("duplicate")
            result[key]=value
        return result
    def finite(value):
        if isinstance(value,float) and not math.isfinite(value): raise ValueError("nonfinite")
        if isinstance(value,list):
            for item in value: finite(item)
        if isinstance(value,dict):
            for item in value.values(): finite(item)
    try:
        result=json.loads(text,parse_constant=constant,object_pairs_hook=pairs)
        finite(result)
        return result
    except (ValueError,TypeError,RecursionError): raise ClientError("invalid_json_response") from None

def decode_action(text):
    """Accept the observed Flight action envelope, reject errors/references."""
    records={}
    for line in text.splitlines():
        if not line: continue
        key,sep,value=line.partition(':')
        if not sep or not re.fullmatch(r'[0-9a-f]+',key):
            raise ClientError("unsupported_action_response")
        if key in records: raise ClientError("duplicate_action_record")
        records[key]=strict_json(value)
    head=records.get('0')
    if not isinstance(head,dict) or not isinstance(head.get('a'),str) or not re.fullmatch(r'\$@[0-9a-f]+',head['a']):
        raise ClientError("unsupported_action_response")
    data=records.get(head['a'][2:])
    if not isinstance(data,dict): raise ClientError("unsupported_action_response")
    def inspect(value):
        if isinstance(value,str) and value.startswith('$'):
            raise ClientError("unsupported_action_value_encoding")
        if isinstance(value,list):
            for child in value: inspect(child)
        if isinstance(value,dict):
            for child in value.values(): inspect(child)
    inspect(data)
    return data

def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',value):
        raise ClientError("invalid_identifier")
    return value

def bounds(limit):
    if type(limit) is not int or not 1<=limit<=MAX_LIMIT: raise ClientError("limit_must_be_1_to_1000")
    return limit

class WhopClient:
    def __init__(self, config=None, browser=None):
        self.config=config or get_config()
        self.browser=browser if browser is not None else self.config.get_browser()
        self._actions={}
        self.max_retries=2
        self.base_delay=1.0
        self.max_delay=10.0
    def close(self):
        self.browser.close()
    def _location(self):
        return rewards_location(self.config.rewards_url)
    def _request(self,page,path,action=None,body=None):
        for attempt in range(self.max_retries+1):
            try: response=page.evaluate(FETCH_JS,{"path":path,"action":action,"body":body})
            except ClientError: raise
            except Exception: raise ClientError("browser_read_failed") from None
            if not isinstance(response,dict): raise ClientError("invalid_transport_response")
            status=response.get('status')
            if type(status) is not int or not 0<=status<=599:
                raise ClientError("invalid_transport_response")
            retry_delay=retry_after_seconds(response.get('retryAfter'))
            if status==200:
                if not isinstance(response.get('text'),str): raise ClientError("response_too_large_or_missing")
                return decode_action(response['text']) if action else strict_json(response['text'])
            if status in (401,403): raise WhopError("session_expired_or_access_denied: run whop auth login",category="auth",status=status,retry_after_seconds=retry_delay)
            if status not in (0,429,500,502,503,504) or attempt==self.max_retries:
                if status==0:
                    category=response.get('errorClass')
                    category=category if category in ('AbortError','TimeoutError','TypeError') else 'Error'
                    raise WhopError(f"upstream_read_failed_transport_{category}",category="transient",status=0,retry_after_seconds=retry_delay)
                raise WhopError(f"upstream_read_failed_http_{status}",category="rate_limit" if status==429 else "transient" if status>=500 else "upstream",status=status,retry_after_seconds=retry_delay)
            delay=min(self.max_delay,self.base_delay*2**attempt)
            if retry_delay is not None:
                delay=max(delay,retry_delay)
                if delay>self.max_delay: raise WhopError("rate_limited_retry_after_exceeds_bound",category="rate_limit" if status==429 else "transient",status=status,retry_after_seconds=retry_delay)
            time.sleep(delay)
    def _reward_page(self,suffix=''):
        origin,path=self._location()
        self.account()  # Validate Whop identity, not just a residual cookie.
        return self.browser.get_page(origin+path+suffix)
    def _rest(self,path,params=None):
        page=self._reward_page()
        result=self._request(page,path+('?' + urlencode(params) if params else ''))
        return self._success(result)
    @staticmethod
    def _success(result):
        if not isinstance(result,dict) or result.get('success') is not True or 'data' not in result:
            raise ClientError("upstream_read_rejected_or_malformed")
        if isinstance(result['data'],dict) and result['data'].get('partialFailure') is True:
            raise ClientError("upstream_partial_failure")
        return result
    def _action(self,name,args,suffix):
        if name not in READ_ACTIONS: raise ClientError("action_not_read_allowlisted")
        document=self._action_document(suffix)
        origin,path=self._location()
        action=self._discover_action(document,name,suffix)
        return self._success(self._request(document,path+suffix,action,args))
    def _action_document(self,suffix):
        page=self._reward_page(suffix)
        origin,path=self._location()
        # Whop may wrap the experience and reset its child route to discover.
        # Select only the configured experience, then route that frame directly.
        requested_path=path+suffix
        requested_url=origin+requested_path
        ready_js="""({origin,path}) => location.origin===origin && location.pathname===path
            && document.readyState!=='loading'
            && [...document.scripts].some(s=>s.src && new URL(s.src).origin===origin)"""
        deadline=time.monotonic()+10.0
        def remaining():
            budget=deadline-time.monotonic()
            if budget<=0: raise ClientError("read_action_readiness_deadline_exceeded")
            return budget
        navigated=False
        while True:
            frames=page.frame_documents(request_timeout=remaining())
            candidates={f['id']:f for f in frames if f['origin']==origin and (f['path']==path or f['path'].startswith(path+'/'))}
            if len(candidates)>1:
                raise ClientError("read_action_document_ambiguous")
            if candidates:
                frame=next(iter(candidates.values()))
                if frame['path']!=requested_path and not navigated:
                    page.goto_frame(frame['id'],requested_url,request_timeout=remaining())
                    navigated=True
                elif page.evaluate_in_iframe(requested_url,ready_js,{'origin':origin,'path':requested_path},request_timeout=remaining()) is True:
                    remaining()
                    break
            if time.monotonic()>=deadline:
                raise ClientError("read_action_page_not_ready: "+json.dumps({'frames':frames},separators=(',',':')))
            time.sleep(0.1)
        def scoped_evaluate(script,arg=None,*,request_timeout=None):
            guarded="""async ({origin,path,arg}) => {
                if(location.origin!==origin || location.pathname!==path) return {scopeMatched:false};
                return {scopeMatched:true,value:await ("""+script+""")(arg)};
            }"""
            options={} if request_timeout is None else {'request_timeout':request_timeout}
            result=page.evaluate_in_iframe(requested_url,guarded,{'origin':origin,'path':requested_path,'arg':arg},**options)
            if not isinstance(result,dict) or result.get('scopeMatched') is not True or 'value' not in result:
                raise ClientError("read_action_document_scope_changed")
            return result['value']
        return SimpleNamespace(evaluate=scoped_evaluate)
    def _discover_action(self,document,name,suffix,*,fresh=False,discovery_js=DISCOVER_ACTION_JS,request_timeout=None):
        key=(suffix,name)
        if fresh: self._actions.pop(key,None)
        if key not in self._actions:
            options={'request_timeout':12.0 if request_timeout is None else request_timeout}
            value=document.evaluate(discovery_js,name,**options)
            if not isinstance(value,dict): raise ClientError("invalid_action_discovery_response")
            reason=value.get('reason')
            if reason not in ('ready','ambiguous','script_fetch_failed','scripts_changed','missing','script_limit'):
                raise ClientError("invalid_action_discovery_response")
            counts=[value.get(k) for k in ('sources','matches','failures')]
            if any(type(n) is not int or not 0<=n<=10000 for n in counts):
                raise ClientError("invalid_action_discovery_response")
            action=value.get('action')
            if reason!='ready':
                raise WhopError(f"read_action_discovery_{reason}: sources={counts[0]}, matches={counts[1]}, failures={counts[2]}",category="transient" if reason in ("scripts_changed","script_fetch_failed") else "invalid_request")
            if counts[1]!=1 or counts[2]!=0 or not isinstance(action,str) or not re.fullmatch(r'[a-f0-9]{40,64}',action):
                raise ClientError("invalid_action_discovery_response")
            self._actions[key]=action
        return self._actions[key]
    def account(self):
        page=self.browser.get_page('https://whop.com/')
        row=self._request(page,'/api/v1/users/me')
        if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not row['id'].startswith('user_') or not isinstance(row.get('username'),str):
            raise ClientError("account_identity_missing")
        # Account endpoints may evolve to include session/security fields.
        safe=('id','username','name','bio','created_at','profile_picture','banner','email',
              'balance','earnings_usd','balance_history')
        result={key:row[key] for key in safe if key in row}
        result.update(profile=self.config.get_active_profile_name(),
                      observed_at=datetime.now(timezone.utc).isoformat(),
                      provenance={'method':'GET','endpoint':'https://whop.com/api/v1/users/me'})
        return result
    def linked_accounts(self,limit=100,*,require_complete=False):
        bounds(limit)
        result=self._action('listSocialMediaAccounts',[],'/settings')
        if not isinstance(result['data'],dict) or not isinstance(result['data'].get('socialMediaAccounts'),list):
            raise ClientError("linked_accounts_schema_changed")
        rows=result['data']['socialMediaAccounts']
        if require_complete and len(rows)>limit: raise ClientError('linked_accounts_inspection_incomplete')
        return rows[:limit]
    def linked_account(self,account_id):
        identifier(account_id)
        for row in self.linked_accounts(MAX_LIMIT):
            if row.get('id')==account_id: return row
        raise ClientError("linked_account_not_found")
    def _pages(self,fetch,limit):
        bounds(limit)
        rows=[];cursor=None;seen=set()
        while len(rows)<limit:
            result=fetch(min(50,limit-len(rows)),cursor)
            data=result.get('data')
            if not isinstance(data,list) or any(not isinstance(row,dict) for row in data): raise ClientError("list_schema_changed")
            rows.extend(data)
            pagination=result.get('pagination',result)
            if not isinstance(pagination,dict): raise ClientError("pagination_schema_changed")
            if 'nextCursor' not in pagination: raise ClientError("pagination_schema_changed")
            cursor=pagination['nextCursor']
            if cursor is None: break
            if not isinstance(cursor,str) or not cursor or cursor in seen or not data: raise ClientError("pagination_cycle_or_invalid_cursor")
            seen.add(cursor)
        return rows[:limit]
    def campaigns(self,limit=100,sort='featured',cursor=None):
        if sort not in ('featured','trending','newest'): raise ClientError("invalid_campaign_sort")
        def fetch(n,c):
            params={'collapseGroups':'true','limit':n,'sortBy':sort}
            if c or cursor: params['cursor']=c or cursor
            return self._rest('/api/campaign/campaigns/discover',params)
        return self._pages(fetch,limit)
    def campaign(self,campaign_id):
        return self._rest('/api/campaign/campaigns/discover/'+identifier(campaign_id))['data']
    def applications(self):
        return self._rest('/api/campaign/campaigns/applications/me')['data']
    def submissions(self,limit=100,status='approved',retainer=False):
        if status not in ('approved','pending','history'): raise ClientError("invalid_submission_status")
        def fetch(n,c):
            args={'retainer':retainer,'limit':n}
            if status=='history': args['isDeleted']=True
            else: args['status']=status
            if c: args['cursor']=c
            return self._action('listMySubmissionsAction',[args],'/submissions')
        return self._pages(fetch,limit)
    def submission(self,submission_id):
        identifier(submission_id)
        for retainer in (False,True):
            for status in ('approved','pending','history'):
                for row in self.submissions(MAX_LIMIT,status,retainer):
                    if row.get('id')==submission_id: return row
        raise ClientError("submission_not_found_in_bounded_inspection")
    def _submission_operation(self,name,*args,**kwargs):
        from . import submission_operations
        try: return getattr(submission_operations,name)(self,*args,**kwargs)
        except WhopError: raise
        except ClientError as error:
            code=str(error).split(':',1)[0]
            if not re.fullmatch(r'[A-Za-z0-9_]{1,100}',code): code='submission_read_failed'
            category='auth' if code in ('submission_whop_actor_changed','account_identity_missing') else 'policy_changed' if code=='submission_requirements_changed' else 'not_ready' if code in ('submission_linked_tiktok_missing_or_ambiguous','submission_campaign_not_active_public','submission_application_required_or_unknown','submission_campaign_not_tiktok','submission_campaign_not_funded','submission_intake_not_open','submission_form_unavailable','submission_form_not_ready') else 'invalid_request'
            raise WhopError(code,category=category) from None
    def submission_readiness(self,campaign_id,*,expected_account_id,expected_tiktok_account_id,expected_requirements_digest=None):
        return self._submission_operation('readiness',campaign_id,expected_account_id=expected_account_id,expected_tiktok_account_id=expected_tiktok_account_id,expected_requirements_digest=expected_requirements_digest)
    def create_submission(self,request_id,campaign_id,publication,*,expected_account_id,expected_tiktok_account_id,accepted_requirements_digest,confirm):
        return self._submission_operation('create',request_id,campaign_id,publication,expected_account_id=expected_account_id,expected_tiktok_account_id=expected_tiktok_account_id,accepted_requirements_digest=accepted_requirements_digest,confirm=confirm)
    def reconcile_submission(self,request_id):
        return self._submission_operation('reconcile',request_id)
    def sync_submission_revenue(self,*,restart_pass=False):
        from .revenue_operations import invoke
        return invoke(self,'synchronize',restart_pass=restart_pass)
    def submission_revenue(self,submission_id,campaign_id,*,refresh_payouts=True):
        from .revenue_operations import invoke
        return invoke(self,'revenue',submission_id,campaign_id,refresh_payouts=refresh_payouts)
    def submission_status(self):
        return {kind:self._action('countMySubmissionsAction',[{'retainer':value}],'/submissions')['data']
                for kind,value in [('clips',False),('retainers',True)]}
    def _creator_id(self):
        users={row['userId'] for row in self.linked_accounts(MAX_LIMIT) if isinstance(row.get('userId'),str)}
        if len(users)!=1: raise ClientError("creator_identity_missing_or_ambiguous")
        return identifier(users.pop())
    def earnings(self,start,end):
        from datetime import datetime
        try:
            a=datetime.fromisoformat(start.replace('Z','+00:00'));b=datetime.fromisoformat(end.replace('Z','+00:00'))
            if a.tzinfo is None or b.tzinfo is None or not a<b or (b-a).total_seconds()>366*86400: raise ValueError()
        except (ValueError,TypeError): raise ClientError("earnings_requires_ordered_timezone_dates_within_366_days") from None
        user=self._creator_id()
        return self._rest('/api/analytics/stats/creators/'+user,{'start':start,'end':end,'granularity':'day'})['data']
    def payouts(self,limit=100):
        user=self._creator_id()
        def fetch(n,c):
            params={'userIds':user,'limit':n}
            if c: params['cursor']=c
            return self._rest('/api/submission/payouts',params)
        return self._pages(fetch,limit)
