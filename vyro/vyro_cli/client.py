"""Read-only adapter for Vyro's observed authenticated JSON endpoints."""
import re
import time
from urllib.parse import urlencode
from cli_tools_shared.exceptions import ClientError
from .config import get_config

# Refresh is Vyro's normal session renewal, not a campaign mutation. Tokens
# remain inside the browser; only the requested service response leaves it.
READ_JS = r"""async ({path}) => {
    const base = 'https://api.vyro.com';
    const signal = AbortSignal.timeout(20000);
    async function read(response) {
        if (!response.ok) return {status:response.status};
        const text = await response.text();
        if (text.length > 8000000) return {error:'response_too_large'};
        try {return {status:response.status,data:JSON.parse(text)};}
        catch (_) {return {error:'invalid_json_response'};}
    }
    try {
        const renewed = await read(await fetch(base+'/auth/refresh', {
            method:'POST', credentials:'include', headers:{'x-realm':'vyro-app'}, signal
        }));
        if (renewed.status!==200 || typeof renewed.data?.accessToken!=='string')
            return {error:'session_expired: run vyro auth login'};
        const headers = {'authorization':'Bearer '+renewed.data.accessToken,
                         'x-realm':'vyro-app','accept':'application/json'};
        const account = await read(await fetch(base+'/auth/me',{headers,credentials:'include',signal}));
        if (account.status!==200) return account;
        if (path==='/auth/me') return account;
        const workspaces=account.data?.workspaces;
        if (!Array.isArray(workspaces)) return {error:'missing_workspaces'};
        const candidates=workspaces.filter(w=>w.type==='clipper' && w.access==='member');
        if(candidates.length!==1 || typeof candidates[0].id!=='string')
            return {error:'requires_exactly_one_clipper_workspace'};
        headers['ap-workspace']=candidates[0].id;
        return await read(await fetch(base+path,{headers,credentials:'include',signal}));
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


class VyroClient:
    def __init__(self, config=None, browser=None):
        self.config = config or get_config()
        self.browser = browser or self.config.get_browser()

    def close(self):
        self.browser.close()

    def _get(self, path):
        page = self.browser.get_page("https://app.vyro.com/campaigns")
        for attempt in range(3):
            try:
                result = page.evaluate(READ_JS, {"path": path})
            except Exception:
                raise ClientError("vyro_browser_read_failed") from None
            if not isinstance(result, dict):
                raise ClientError("invalid_transport_response")
            if result.get("error"):
                raise ClientError(result["error"])
            status = result.get("status")
            if status == 200:
                data = result.get("data")
                if not isinstance(data, dict):
                    raise ClientError("invalid_response_object")
                return data
            if status in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise ClientError(f"vyro_http_{status}")

    def account(self):
        row = self._get("/auth/me")
        if not all(isinstance(row.get(k), str) and row[k] for k in ("id", "username", "email")):
            raise ClientError("invalid_account_response")
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
