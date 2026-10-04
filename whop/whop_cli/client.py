"""Read-only observed Whop participant contracts. No mutation transport."""
import json
import math
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit
from cli_tools_shared.exceptions import ClientError
from .config import get_config

MAX_BODY = 8_000_000
MAX_LIMIT = 1000
READ_ACTIONS = {"listSocialMediaAccounts", "listMySubmissionsAction", "countMySubmissionsAction"}
FETCH_JS = """async ({path, action, body}) => {
    try {
        const headers = action ? {'Next-Action':action,'Content-Type':'text/plain;charset=UTF-8','Accept':'text/x-component'} : {'Accept':'application/json'};
        const r = await fetch(path, {method:action?'POST':'GET',headers,body:action?JSON.stringify(body):undefined,credentials:'include',signal:AbortSignal.timeout(20000),redirect:'error'});
        const text = await r.text();
        return {status:r.status,text:text.length<=MAX_BODY?text:null,retryAfter:r.headers.get('Retry-After')};
    } catch (error) {
        const safe = ['AbortError','TimeoutError','TypeError'].includes(error?.name) ? error.name : 'Error';
        return {status:0,text:null,errorClass:safe};
    }
}"""
FETCH_JS = FETCH_JS.replace("MAX_BODY",str(MAX_BODY))
DISCOVER_ACTION_JS = r"""async (name) => {
    const scriptSources = () => [...new Set([...document.scripts].map(s=>s.src).filter(s=>s && new URL(s).origin===location.origin))];
    const sources = scriptSources();
    if (sources.length>120) return {action:null,reason:'script_limit',sources:sources.length,matches:0,failures:0};
    const matches = new Set();
    let failures = 0;
    for (let i=0;i<sources.length;i+=8) {
        const texts=await Promise.all(sources.slice(i,i+8).map(async u=>{
            try { const r=await fetch(u,{signal:AbortSignal.timeout(10000)});if(!r.ok){failures++;return '';}return await r.text(); }catch(_){failures++;return '';}
        }));
        for(const text of texts){
            const re=/createServerReference\)\("([a-f0-9]{40,64})"[^;]{0,160}?"([A-Za-z]+)"/g;
            for(const m of text.matchAll(re)) if(m[2]===name) matches.add(m[1]);
        }
    }
    const after=scriptSources();
    const changed=sources.length!==after.length || after.some(u=>!sources.includes(u));
    const reason=matches.size>1?'ambiguous':matches.size===1?'ready':failures?'script_fetch_failed':changed?'scripts_changed':'missing';
    return {action:matches.size===1?[...matches][0]:null,reason,sources:sources.length,matches:matches.size,failures};
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
    def __init__(self, config=None):
        self.config=config or get_config()
        self.browser=self.config.get_browser()
        self._actions={}
        self.max_retries=2
        self.base_delay=1.0
        self.max_delay=10.0
    def close(self):
        self.browser.close()
    def _location(self):
        raw=self.config.rewards_url
        if not raw: raise ClientError("rewards_url_unconfigured: run whop auth login")
        u=urlsplit(raw)
        if u.scheme!='https' or not re.fullmatch(r'[a-z0-9]+\.apps\.whop\.com',u.netloc) or not re.fullmatch(r'/c/exp_[A-Za-z0-9]+/?',u.path) or u.query or u.fragment:
            raise ClientError("invalid_rewards_url")
        return f'https://{u.netloc}',u.path.rstrip('/')
    def _request(self,page,path,action=None,body=None):
        for attempt in range(self.max_retries+1):
            try: response=page.evaluate(FETCH_JS,{"path":path,"action":action,"body":body})
            except Exception: raise ClientError("browser_read_failed") from None
            if not isinstance(response,dict): raise ClientError("invalid_transport_response")
            status=response.get('status')
            if type(status) is not int or not 0<=status<=599:
                raise ClientError("invalid_transport_response")
            if status==200:
                if not isinstance(response.get('text'),str): raise ClientError("response_too_large_or_missing")
                return decode_action(response['text']) if action else strict_json(response['text'])
            if status in (401,403): raise ClientError("session_expired_or_access_denied: run whop auth login")
            if status not in (0,429,500,502,503,504) or attempt==self.max_retries:
                if status==0:
                    category=response.get('errorClass')
                    category=category if category in ('AbortError','TimeoutError','TypeError') else 'Error'
                    raise ClientError(f"upstream_read_failed_transport_{category}")
                raise ClientError(f"upstream_read_failed_http_{status}")
            delay=min(self.max_delay,self.base_delay*2**attempt)
            retry=response.get('retryAfter')
            if isinstance(retry,str) and retry.isdigit():
                delay=max(delay,float(retry))
                if delay>self.max_delay: raise ClientError("rate_limited_retry_after_exceeds_bound")
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
        page=self._reward_page(suffix)
        origin,path=self._location()
        # Navigation can return while the new document has no scripts yet.
        # Wait for the configured document before taking the script snapshot.
        ready_js="""({origin,path}) => location.origin===origin && location.pathname===path
            && document.readyState!=='loading'
            && [...document.scripts].some(s=>s.src && new URL(s.src).origin===origin)"""
        deadline=time.monotonic()+10.0
        while page.evaluate(ready_js,{'origin':origin,'path':path+suffix}) is not True:
            if time.monotonic()>=deadline: raise ClientError("read_action_page_not_ready")
            time.sleep(0.1)
        key=(suffix,name)
        if key not in self._actions:
            value=page.evaluate(DISCOVER_ACTION_JS,name)
            if not isinstance(value,dict): raise ClientError("invalid_action_discovery_response")
            reason=value.get('reason')
            if reason not in ('ready','ambiguous','script_fetch_failed','scripts_changed','missing','script_limit'):
                raise ClientError("invalid_action_discovery_response")
            counts=[value.get(k) for k in ('sources','matches','failures')]
            if any(type(n) is not int or not 0<=n<=10000 for n in counts):
                raise ClientError("invalid_action_discovery_response")
            action=value.get('action')
            if reason!='ready':
                raise ClientError(f"read_action_discovery_{reason}: sources={counts[0]}, matches={counts[1]}, failures={counts[2]}")
            if counts[1]!=1 or not isinstance(action,str) or not re.fullmatch(r'[a-f0-9]{40,64}',action):
                raise ClientError("invalid_action_discovery_response")
            self._actions[key]=action
        return self._success(self._request(page,path+suffix,self._actions[key],args))
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
    def linked_accounts(self,limit=100):
        bounds(limit)
        result=self._action('listSocialMediaAccounts',[],'/settings')
        if not isinstance(result['data'],dict) or not isinstance(result['data'].get('socialMediaAccounts'),list):
            raise ClientError("linked_accounts_schema_changed")
        return result['data']['socialMediaAccounts'][:limit]
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
