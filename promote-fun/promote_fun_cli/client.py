"""Read-only Convex contracts measured from promote.fun's own app assets."""
import math
import time
from typing import Optional

import requests
from cli_tools_shared.exceptions import ClientError
from .config import get_config

API_URL = 'https://dapper-duck-781.convex.cloud/api/query'
PAGE_SIZE = 100


class PromoteFunClient:
    def __init__(self, session=None, config=None, max_retries: int = 2, base_delay: float = 1, max_delay: float = 10):
        self.session = session or requests.Session()
        self.config = config
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    def close(self):
        self.session.close()

    def account(self):
        """Use the saved Clerk profile for the app's measured users:current query."""
        browser = (self.config or get_config()).get_browser()
        try:
            page = browser.get_page('https://www.promote.fun/campaigns')
            from .browser import ACCOUNT_JS
            value = page.evaluate(ACCOUNT_JS)
        finally:
            browser.close()
        if not isinstance(value, dict) or not isinstance(value.get('_id'), str):
            raise ClientError('Promote.fun account unavailable: run promote-fun auth login')
        return value

    def _authenticated_call(self, kind, path, arguments):
        browser = (self.config or get_config()).get_browser()
        try:
            page = browser.get_page('https://www.promote.fun/campaigns')
            result = page.evaluate("""async (request) => {
                const until=Date.now()+10000;
                while(!window.Clerk?.loaded && Date.now()<until)await new Promise(r=>setTimeout(r,100));
                if(!window.Clerk?.session)return null;
                const token=await window.Clerk.session.getToken({template:'convex'});
                const response=await fetch('https://dapper-duck-781.convex.cloud/api/'+request.kind,{
                    method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},
                    body:JSON.stringify({path:request.path,format:'convex_encoded_json',args:[request.arguments]})});
                const value=await response.json();
                return response.ok?value:null;
            }""", {'kind':kind,'path':path,'arguments':arguments})
        finally:
            browser.close()
        if not isinstance(result, dict) or result.get('status') != 'success':
            raise ClientError('Promote.fun authenticated operation rejected; read account state before retrying')
        return result.get('value')

    def social_accounts(self):
        rows = self._authenticated_call('query', 'connectedAccounts:getConnectedAccounts', {})
        if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get('_id'), str) for row in rows):
            raise ClientError('Promote.fun connected accounts schema changed')
        fields = {'_id', 'platform', 'username', 'accountUsername', 'status', 'verifiedAt'}
        return [{key: value for key, value in row.items() if key in fields} for row in rows]

    def verification_code(self, account_id):
        self._owned_social_account(account_id)
        value = self._authenticated_call('mutation', 'connectedAccounts:generateVerificationCode', {'accountId':account_id})
        if not isinstance(value, dict) or not isinstance(value.get('code'), str) or not isinstance(value.get('expiresAt'), (int, float)):
            raise ClientError('Promote.fun verification code schema changed')
        return value

    def _owned_social_account(self, account_id):
        matches = [row for row in self.social_accounts() if row['_id'] == account_id]
        if len(matches) != 1:
            raise ClientError('Connected account is not owned by the current Promote.fun session')
        return matches[0]

    def verify_social_account(self, account_id):
        before = self._owned_social_account(account_id)
        if before.get('status') != 'verified':
            self._authenticated_call('action', 'connectedAccounts:validateBioVerification', {'accountId':account_id})
        after = self._owned_social_account(account_id)
        if after.get('status') != 'verified' or not isinstance(after.get('verifiedAt'), (int, float)):
            raise ClientError('Promote.fun ownership verification not observed; do not infer success')
        return after

    def query(self, path: str, arguments: dict):
        body = {'path': path, 'format': 'convex_encoded_json', 'args': [arguments]}
        for attempt in range(self.max_retries + 1):
            response = None
            try:
                response = self.session.post(API_URL, json=body, timeout=30)
            except (requests.ConnectionError, requests.Timeout):
                if attempt == self.max_retries:
                    raise ClientError('Promote.fun public query unavailable') from None
            else:
                if response.status_code not in {429, 500, 502, 503, 504}:
                    break
                if attempt == self.max_retries:
                    raise ClientError(f'Promote.fun public query failed (HTTP {response.status_code})')
            delay = min(self.max_delay, self.base_delay * 2 ** attempt)
            if response is not None:
                retry_after = response.headers.get('Retry-After')
                if retry_after:
                    try:
                        seconds = float(retry_after)
                    except ValueError:
                        raise ClientError('Promote.fun Retry-After is not a supported seconds value') from None
                    if not math.isfinite(seconds) or seconds < 0 or seconds > self.max_delay:
                        raise ClientError('Promote.fun Retry-After exceeds retry bound')
                    delay = max(delay, seconds)
            time.sleep(delay)
        if response is None or not response.ok:
            raise ClientError('Promote.fun public query failed')
        try:
            data = response.json()
        except ValueError:
            raise ClientError('Promote.fun returned invalid JSON') from None
        if not isinstance(data, dict) or data.get('status') != 'success' or 'value' not in data:
            raise ClientError('Promote.fun query rejected or response schema changed')
        return data['value']

    def campaigns(self, limit: int = 100, status: str = 'active', platform: Optional[str] = None,
                  search: Optional[str] = None, sort: str = 'newest') -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ClientError('limit must be between 1 and 1000')
        rows, cursor, seen = [], None, set()
        while len(rows) < limit:
            arguments = {'status': status, 'paginationOpts': {'numItems': min(PAGE_SIZE, limit - len(rows)), 'cursor': cursor}, 'sort': sort}
            if platform is not None:
                arguments['platform'] = platform
            if search is not None:
                arguments['search'] = search
            value = self.query('campaigns:listCampaigns', arguments)
            if not isinstance(value, dict) or not isinstance(value.get('page'), list) or type(value.get('isDone')) is not bool:
                raise ClientError('Promote.fun campaign page schema changed')
            page = value['page']
            if any(not isinstance(row, dict) or not isinstance(row.get('_id'), str) for row in page):
                raise ClientError('Promote.fun campaign row schema changed')
            if len(page) > arguments['paginationOpts']['numItems']:
                raise ClientError('Promote.fun campaign page exceeded requested size')
            rows.extend(page)
            if value['isDone']:
                break
            cursor = value.get('continueCursor')
            if not isinstance(cursor, str) or not cursor or cursor in seen or not page:
                raise ClientError('Promote.fun pagination incomplete or repeated')
            seen.add(cursor)
        return rows

    def campaign(self, campaign_id: str) -> dict:
        if not campaign_id or len(campaign_id) > 200 or any(ord(character) < 32 for character in campaign_id):
            raise ClientError('Invalid Promote.fun campaign ID or slug')
        value = self.query('campaigns:getCampaignBySlugOrId', {'slugOrId': campaign_id})
        if value is None:
            raise ClientError('Promote.fun campaign not found')
        if not isinstance(value, dict) or not isinstance(value.get('_id'), str):
            raise ClientError('Promote.fun campaign detail schema changed')
        return value
