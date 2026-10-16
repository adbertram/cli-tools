"""Adapter for Vyro's observed authenticated JSON endpoints."""
import re
import os
from datetime import datetime, timezone
import hashlib
import json
import time
from urllib.parse import urlencode, urlsplit
from cli_tools_shared.exceptions import ClientError
from .browser import AUTH_CONTEXT_URL
from .config import get_config

# Refresh is Vyro's normal session renewal, not a campaign mutation. Tokens
# remain inside the browser; only the requested service response leaves it.
READ_JS = r"""async ({path, method = 'GET', body, expectedAccountId}) => {
    const base = 'https://api.vyro.com';
    const signal = AbortSignal.timeout(20000);
    async function read(response) {
        if (!response.ok) {
            let data; try {data=await response.json()} catch (_) {}
            const code=data?.errorCode || data?.errors?.[0];
            return {status:response.status,code:typeof code==='string'&&/^[A-Z][A-Z0-9_]{1,120}$/.test(code)?code:null};
        }
        const text = await response.text();
        if (text.length > 8000000) return {error:'response_too_large'};
        try {return {status:response.status,data:JSON.parse(text)};}
        catch (_) {return {error:'invalid_json_response'};}
    }
    try {
        const renewed = await read(await fetch(base+'/auth/refresh', {
            method:'POST', credentials:'include', headers:{'x-realm':'vyro-app'}, signal
        }));
        if (renewed.status === 401)
            return {error:'session_expired: run vyro auth login'};
        if (renewed.status === 403)
            return {error:'vyro_refresh_forbidden'+(renewed.code?':'+renewed.code:'')};
        if (renewed.status === 429)
            return {error:'vyro_refresh_rate_limited'};
        if ([500,502,503,504].includes(renewed.status))
            return {error:'vyro_refresh_unavailable'};
        if (renewed.status!==200 || typeof renewed.data?.accessToken!=='string'
                || !renewed.data.accessToken)
            return {error:'invalid_refresh_response'};
        const headers = {'authorization':'Bearer '+renewed.data.accessToken,
                         'x-realm':'vyro-app','accept':'application/json'};
        const account = await read(await fetch(base+'/auth/me',{headers,credentials:'include',signal}));
        if (account.status!==200) return account;
        if (expectedAccountId && account.data?.id !== expectedAccountId)
            return {error:'vyro_account_identity_mismatch'};
        if (path==='/auth/me') return account;
        const workspaces=account.data?.workspaces;
        if (!Array.isArray(workspaces)) return {error:'missing_workspaces'};
        const candidates=workspaces.filter(w=>w.type==='clipper' && w.access==='member');
        if(candidates.length!==1 || typeof candidates[0].id!=='string')
            return {error:'requires_exactly_one_clipper_workspace'};
        headers['ap-workspace']=candidates[0].id;
        const options = {method,headers,cache:'no-store',credentials:'include',signal};
        if (method !== 'GET') {
            // Vyro SDK wire format: CBOR text containing base64 UTF-8 JSON.
            const jsonBytes=new TextEncoder().encode(JSON.stringify(body));
            const encoded=btoa(Array.from(jsonBytes,b=>String.fromCharCode(b)).join(''));
            const bytes=new TextEncoder().encode(encoded), n=bytes.length;
            if(n>65535) return {error:'vyro_write_payload_too_large'};
            const prefix=n<24?[0x60+n]:n<256?[0x78,n]:[0x79,n>>8,n&255];
            options.body=new Uint8Array([...prefix,...bytes]);
            headers['content-type']='application/octet-stream';
        }
        return await read(await fetch(base+path,options));
    } catch (_) {return {error:'vyro_request_failed'};}
}"""


def bounded_limit(limit):
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ClientError("limit_must_be_1_to_1000")
    return limit


def pagination(result):
    meta = result.get("meta")
    page = meta.get("page") if isinstance(meta, dict) else None
    if not isinstance(page, dict) or "next" not in page:
        raise ClientError("invalid_pagination_metadata")
    return page


def slug_path(slug):
    if not isinstance(slug, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", slug):
        raise ClientError("invalid_campaign_slug")
    return "/catalog/campaigns/slug/" + slug


def requirements_digest(campaign):
    """Bind approval to stable native rules, sources and payout terms, not spend."""
    fields = ('id', 'requirements', 'targeting', 'formats', 'payoutModel', 'media', 'startDate', 'endDate', 'creatorPreferences', 'type')
    data = {key: campaign.get(key) for key in fields}
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def tiktok_post(url, username):
    """Only canonical owned TikTok posts; never resolve untrusted short links."""
    handle = username.lstrip('@').lower()
    if not re.fullmatch(r'[A-Za-z0-9_.]{1,24}', handle):
        raise ClientError('invalid_expected_username')
    parsed = urlsplit(url)
    match = re.fullmatch(r'/@([A-Za-z0-9_.]+)/video/([0-9]+)', parsed.path)
    if (parsed.scheme != 'https' or parsed.netloc not in ('www.tiktok.com', 'tiktok.com')
            or not match or match[1].lower() != handle.lower()):
        raise ClientError('post_url_must_match_expected_tiktok_username')
    return f'https://www.tiktok.com/@{handle}/video/{match[2]}', match[2]


def validate_precheck(result, campaign):
    """Require affirmative checks for rules this campaign actually requires."""
    req = campaign.get('requirements', {})
    required = []
    if any(req.get('video', {}).get(k, 0) > 0 for k in ('minLength','maxLength')): required.append(('videoLength','pass',True))
    if req.get('text', {}).get('hashtags'): required.append(('hashtags','pass',True))
    if req.get('audio', {}).get('links'): required.append(('audio','matchesRequiredAudio',True))
    if req.get('text', {}).get('ftcDisclosureHashtags') or req.get('platformRules', {}).get('ftcDisclosure', {}).get('tiktok'):
        required.append(('disclosure','verdict','PASS'))
    if req.get('collaboration', {}).get('allowCollabAndTagging') is False:
        required.append(('collab','pass',True))
    for key,field,value in required:
        check=result.get(key)
        if not isinstance(check,dict) or check.get('applicable') is not True or check.get(field)!=value:
            raise ClientError('precheck_not_passed_'+key)
    for key in ('videoLength','hashtags','collab'):
        if isinstance(result.get(key),dict) and result[key].get('applicable') and result[key].get('pass') is False:
            raise ClientError('precheck_not_passed_'+key)


class VyroClient:
    def __init__(self, config=None, browser=None):
        self.config = config or get_config()
        self.browser = browser or self.config.get_browser()

    def close(self):
        self.browser.close()

    def _get(self, path):
        return self._request(path)

    def _request(self, path, method='GET', body=None, expected_account_id=None):
        page = self.browser.get_page(AUTH_CONTEXT_URL)
        for attempt in range(3):
            try:
                result = page.evaluate(READ_JS, {"path": path, "method": method, "body": body, "expectedAccountId": expected_account_id})
            except Exception:
                raise ClientError("vyro_browser_read_failed" if method == "GET" else "vyro_write_outcome_unknown_reconcile_before_retry") from None
            if not isinstance(result, dict):
                raise ClientError("invalid_transport_response")
            if result.get("error"):
                raise ClientError("vyro_write_outcome_unknown_reconcile_before_retry" if method != "GET" and result["error"] == "vyro_request_failed" else result["error"])
            status = result.get("status")
            if status in (200, 201):
                data = result.get("data")
                if not isinstance(data, dict):
                    raise ClientError("invalid_response_object")
                return data
            if method == "GET" and status in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise ClientError(f"vyro_http_{status}" + (":" + result["code"] if result.get("code") else ""))

    def account(self):
        row = self._get("/auth/me")
        if not all(isinstance(row.get(k), str) and row[k] for k in ("id", "username", "email")):
            raise ClientError("invalid_account_response")
        return row

    def actor(self, expected_account_id, expected_social_account_id, expected_username):
        if self.account()['id'] != expected_account_id:
            raise ClientError('vyro_account_identity_mismatch')
        rows = [r for r in self.social_accounts() if r.get('id') == expected_social_account_id]
        if len(rows) != 1:
            raise ClientError('expected_social_account_not_linked')
        row = rows[0]
        if not isinstance(row.get('platformUserId'), str) or not row['platformUserId'].strip():
            raise ClientError('missing_linked_platform_user_id')
        status = row.get('status')
        if (not isinstance(status, dict) or row.get('platform') != 'tiktok' or
                row.get('platformUsername', '').lower().lstrip('@') != expected_username.lower().lstrip('@') or
                status.get('id') != 'active'):
            raise ClientError('expected_tiktok_identity_not_active')
        return row

    def campaigns(self, limit=100):
        limit = bounded_limit(limit)
        rows, page = [], 1
        seen = set()
        while len(rows) < limit:
            result = self._get("/catalog/campaigns?" + urlencode({
                "sort": "startDate.desc", "limit": min(12, limit-len(rows)), "page": page
            }))
            data = result.get("data")
            paging = pagination(result)
            if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
                raise ClientError("invalid_campaign_page")
            if len(data) > limit-len(rows):
                raise ClientError("campaign_page_exceeds_requested_limit")
            for row in data:
                identity = row.get("id")
                if not isinstance(identity, str) or identity in seen:
                    raise ClientError("duplicate_or_missing_campaign_id")
                seen.add(identity)
            rows.extend(data)
            following = paging["next"]
            if following is None:
                break
            if type(following) is not int or following <= page or not data:
                raise ClientError("invalid_campaign_pagination")
            page = following
        return rows

    def campaign(self, slug):
        return self._get(slug_path(slug))

    def eligibility(self, slug):
        return self._get(slug_path(slug) + "/eligibility")

    def social_accounts(self, limit=100):
        bounded_limit(limit)
        result = self._get("/social-accounts/me")
        rows = result.get("data")
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise ClientError("invalid_social_accounts_response")
        if pagination(result)["next"] is not None:
            raise ClientError("social_accounts_pagination_not_supported")
        # The observed endpoint has no limit parameter. Limit the returned list
        # explicitly; it always fetches the full linked-account collection.
        return rows[:limit]
    def analytics(self, slug=None, limit=100):
        return [self._analytics_record(row) for row in self.submissions(slug, limit)]

    def analytics_submission(self, identity):
        actor = self.account()['id']
        row = self.submission(identity)
        owner = row.get('owner')
        if not isinstance(owner, dict) or owner.get('id') != actor:
            raise ClientError('clip_analytics_owner_mismatch')
        return self._analytics_record(row)

    def _analytics_record(self, row):
        metrics = row.get('metrics')
        if metrics is None:
            metrics = {}
        if not isinstance(metrics, dict) or not isinstance(row.get('id'), str):
            raise ClientError('invalid_clip_analytics_record')
        return {
            'id': row['id'], 'campaign_id': row.get('campaignId'),
            'post_id': row.get('videoId'), 'post_url': row.get('videoUrl'),
            'platform': row.get('platform'), 'status': row.get('status'),
            'views': metrics.get('totalViews'), 'likes': metrics.get('totalLikes'),
            'comments': metrics.get('totalComments'), 'shares': None,
            'metrics_updated_at': metrics.get('lastMetricsUpdatedAt'),
            'earnings': row.get('earnings'),
            'observed_at': datetime.now(timezone.utc).isoformat(),
            'profile': self.config.get_active_profile_name(), 'native': row,
        }

    def readiness(self, slug, expected_account_id, expected_social_account_id, expected_username):
        social = self.actor(expected_account_id, expected_social_account_id, expected_username)
        campaign = self.campaign(slug)
        eligibility = self.eligibility(slug)
        identity = campaign.get('id')
        if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{24}', identity):
            raise ClientError('invalid_campaign_id')
        reason = None
        try:
            start=datetime.fromisoformat(campaign['startDate'].replace('Z','+00:00'))
            end=datetime.fromisoformat(campaign['endDate'].replace('Z','+00:00'))
            now=datetime.now(timezone.utc)
            if not start <= now < end: reason='campaign_outside_submission_dates'
        except (KeyError, ValueError, TypeError): raise ClientError('invalid_campaign_dates') from None
        if campaign.get('type') != 'clipping': reason=reason or 'unsupported_campaign_type'
        if campaign.get('status', {}).get('id') != 'active': reason = reason or 'campaign_not_active'
        elif campaign.get('isLocked') is not False: reason = 'campaign_locked'
        elif 'tiktok' not in campaign.get('targeting', {}).get('platforms', []): reason = 'platform_not_allowed'
        elif not isinstance(campaign.get('budget', {}).get('remaining'), (int,float)) or campaign['budget']['remaining'] <= 0: reason = 'campaign_budget_unavailable'
        mode = eligibility.get('inviteMode')
        if mode == 'social-account':
            eligible = eligibility.get('eligibleAccounts')
            if not isinstance(eligible, list): raise ClientError('invalid_eligibility')
            if not any(r.get('platform') == 'tiktok' and r.get('platformUsername','').lower() == social['platformUsername'].lower() for r in eligible):
                reason = reason or 'social_account_not_eligible'
        elif mode != 'open': reason = reason or 'unsupported_invite_mode'
        rate = self._get('/clips/rate-limit-status?' + urlencode({'campaignId':identity,'socialAccountId':social['id']}))
        throttle = self._get('/clips/throttle-status?' + urlencode({'campaignId':identity}))
        if type(rate.get('currentCount')) is not int or type(rate.get('limit')) is not int or type(throttle.get('isBlocked')) is not bool:
            raise ClientError('invalid_submission_limit_response')
        if rate['limit'] > 0 and rate['currentCount'] >= rate['limit']: reason = reason or 'submission_rate_limit'
        if throttle['isBlocked']: reason = reason or 'submission_throttled'
        enrolled = campaign.get('enrolled') is True
        if not enrolled: reason = reason or 'campaign_not_joined'
        return {'campaign':campaign,'social_account':social,'eligibility':eligibility,'enrolled':enrolled,
                'ready':reason is None,'reason':reason,'requirements_digest':requirements_digest(campaign),
                'rate_limit':rate,'throttle':throttle}

    def join(self, slug, expected_account_id, expected_social_account_id, expected_username, confirm=False):
        if not confirm: raise ClientError('Refusing to join without --yes')
        state = self.readiness(slug,expected_account_id,expected_social_account_id,expected_username)
        if state['enrolled']: return {'joined':True,'campaign':state['campaign']}
        if state['reason'] != 'campaign_not_joined': raise ClientError(state['reason'])
        try:
            self._request('/campaigns/'+state['campaign']['id']+'/members/join','POST',{},expected_account_id)
        except ClientError:
            # A membership write can return no body or time out after committing.
            if self.campaign(slug).get('enrolled') is not True: raise
        row = self.campaign(slug)
        if row.get('enrolled') is not True: raise ClientError('join_outcome_unknown')
        return {'joined':True,'campaign':row}

    def submissions(self, slug=None, limit=100, exhaustive=False):
        limit = bounded_limit(limit)
        campaign = self.campaign(slug) if slug else None
        rows, page, seen = [], 1, set()
        while len(rows) < limit:
            params={'limit':min(20,limit-len(rows)), 'page':page}
            if campaign: params['filter[campaignId]']=campaign['id']
            result = self._get('/clips/me?' + urlencode(params))
            data = result.get('data')
            following = pagination(result)['next']
            if not isinstance(data,list) or len(data)>limit-len(rows): raise ClientError('invalid_submission_page')
            for row in data:
                if not isinstance(row,dict) or not isinstance(row.get('id'),str) or row['id'] in seen: raise ClientError('invalid_submission_record')
                seen.add(row['id'])
            rows.extend(data)
            if following is None: return rows
            if type(following) is not int or following<=page or not data: raise ClientError('invalid_submission_pagination')
            page=following
        if exhaustive: raise ClientError('submission_scan_limit_reached')
        return rows

    def submission(self, identity):
        if not re.fullmatch(r'[a-f0-9]{24}',identity): raise ClientError('invalid_submission_id')
        return self._get('/clips/'+identity)

    def reconcile(self, slug, url, expected_account_id, expected_social_account_id, expected_username):
        social = self.actor(expected_account_id,expected_social_account_id,expected_username)
        canonical, post_id = tiktok_post(url,expected_username)
        campaign = self.campaign(slug)
        matches=[]
        for row in self.submissions(slug,1000,exhaustive=True):
            if (row.get('campaignId') != campaign['id'] or
                    not all(isinstance(row.get(k),str) and row[k] for k in ('platform','platformUserId')) or
                    not any(isinstance(row.get(k),str) and row[k] for k in ('videoUrl','videoRawUrl'))):
                raise ClientError('incomplete_submission_receipt')
            for key in ('videoUrl','videoRawUrl'):
                value=row.get(key)
                if not isinstance(value,str): continue
                try: _, candidate=tiktok_post(value,expected_username)
                except ClientError: continue
                if candidate==post_id:
                    if row.get('campaignId')!=campaign['id'] or row.get('platform')!='tiktok' or row.get('platformUserId')!=social.get('platformUserId'):
                        raise ClientError('submission_receipt_identity_mismatch')
                    matches.append(row);break
        if len(matches)>1: raise ClientError('multiple_submission_receipts')
        return {'status':'existing' if matches else 'not_found','submission':matches[0] if matches else None,'url':canonical}

    def create_submission(self, slug, url, digest, expected_account_id, expected_social_account_id, expected_username, confirm=False):
        if not confirm: raise ClientError('Refusing to submit without --yes')
        canonical,_=tiktok_post(url,expected_username)
        args=(slug,expected_account_id,expected_social_account_id,expected_username)
        existing=self.reconcile(slug,canonical,*args[1:])
        if existing['status']=='existing': return existing
        state=self.readiness(*args)
        if not state['ready']: raise ClientError(state['reason'])
        if digest!=state['requirements_digest']: raise ClientError('requirements_digest_changed')
        payload={'videoUrl':canonical,'socialAccountId':expected_social_account_id,'campaignId':state['campaign']['id']}
        checked=self._request('/clips/pre-check','POST',payload,expected_account_id)
        validate_precheck(checked,state['campaign'])
        current=self.readiness(*args)
        if not current['ready']: raise ClientError(current['reason'])
        if current['requirements_digest']!=digest: raise ClientError('requirements_digest_changed')
        # O_EXCL atomically binds the campaign/post/actor across processes. A crash
        # or timeout retains the marker: reconcile, never blindly dispatch again.
        directory=self.config.get_profile_data_dir()/'vyro-submissions'
        directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        if directory.is_symlink(): raise ClientError('unsafe_submission_journal')
        key=hashlib.sha256(json.dumps([expected_account_id,expected_social_account_id,payload['campaignId'],canonical]).encode()).hexdigest()
        marker=directory/(key+'.json')
        try: fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        except FileExistsError: return {'status':'uncertain','submission':None,'url':canonical,'reason':'prior_dispatch_requires_reconciliation'}
        with os.fdopen(fd,'w') as stream:
            json.dump({'payload':payload,'expected_account_id':expected_account_id,'requirements_digest':digest},stream)
            stream.flush();os.fsync(stream.fileno())
        dirfd=os.open(directory,os.O_RDONLY)
        try: os.fsync(dirfd)
        finally: os.close(dirfd)
        try:
            receipt=self._request('/clips/v2','POST',payload,expected_account_id)
        except ClientError:
            result=self.reconcile(slug,canonical,*args[1:])
            if result['status']=='existing': return result
            return {'status':'uncertain','submission':None,'url':canonical,'reason':'dispatch_requires_reconciliation'}
        if not isinstance(receipt.get('id'),str):
            return {'status':'uncertain','submission':None,'url':canonical,'reason':'unrecognized_receipt'}
        result=self.reconcile(slug,canonical,*args[1:])
        if result['status']=='existing': return {**result,'status':'created'}
        return {'status':'uncertain','submission':None,'url':canonical,'reason':'receipt_not_yet_visible'}
