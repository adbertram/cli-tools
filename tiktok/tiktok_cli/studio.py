"""Strict whitelist for the observed own-account Studio Manage content feed."""
import re
import json
import math

STUDIO_CONTENT_URL = "https://www.tiktok.com/tiktokstudio/content?from=seo"
STUDIO_ITEMS_PATH = "/tiktok/creator/manage/item_list/v1/"
MAX_RESPONSE_BYTES = 8_000_000
STUDIO_PAGE_SIZE = 50
MAX_STUDIO_PAGES = 20
MAX_STUDIO_ITEMS = STUDIO_PAGE_SIZE * MAX_STUDIO_PAGES
METRIC_FIELDS = {
    "views": "play_count", "likes": "like_count", "comments": "comment_count",
    "shares": "share_count", "favorites": "favorite_count",
}


class StudioContractError(ValueError):
    """A malformed/limited read cannot establish account content or absence."""
    def __init__(self, message, *, code="studio_contract_error", category="upstream", status=None, retry_after_seconds=None):
        super().__init__(message)
        self.code, self.category, self.status = code, category, status
        self.retry_after_seconds = retry_after_seconds


def retry_after_seconds(raw, now=None):
    from datetime import datetime, timezone
    from email.utils import parsedate_to_datetime
    if type(raw) is not str or len(raw) > 200:
        return None
    raw = raw.strip()
    if re.fullmatch(r"[0-9]+", raw):
        delay = float(raw)
        return delay if math.isfinite(delay) else None
    try:
        when = parsedate_to_datetime(raw)
        if when.tzinfo is None:
            return None
        delay = (when - (now or datetime.now(timezone.utc))).total_seconds()
        return max(0.0, delay) if math.isfinite(delay) else None
    except (ValueError, TypeError, OverflowError):
        return None


def parse_response(text):
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise StudioContractError("TikTok Studio response exceeds the bounded payload size.")
    def pairs(values):
        result = {}
        for name, value in values:
            if name in result:
                raise ValueError("Duplicate JSON key")
            result[name] = value
        return result
    def nonfinite(value):
        raise ValueError("Nonfinite JSON value")
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Nonfinite JSON value")
        return number
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=nonfinite, parse_float=finite_float)
    except (ValueError, TypeError, RecursionError):
        raise StudioContractError("TikTok Studio JSON is malformed; result is inconclusive.") from None


def decimal(value, field, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,64}", value):
        raise StudioContractError(f"TikTok Studio {field} is not an exact nonnegative decimal string.")
    return int(value)


def positive_decimal_id(value):
    """An exact positive string ID, never a coerced JSON number."""
    return isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,63}", value) is not None


def normalize_item(raw, identity, observed_at, measured_at):
    if not isinstance(raw, dict):
        raise StudioContractError("TikTok Studio item is malformed.")
    item_id = raw.get("item_id")
    if not positive_decimal_id(item_id):
        raise StudioContractError("TikTok Studio item ID is malformed.")
    caption = raw.get("desc")
    if caption is not None and not isinstance(caption, str):
        raise StudioContractError("TikTok Studio caption is malformed.")
    record = {
        "id": item_id,
        "url": f"https://www.tiktok.com/@{identity['username']}/video/{item_id}",
        "caption": caption, "author": identity["username"],
        "created_at": decimal(raw.get("create_time"), "create_time"),
        "posted_at": decimal(raw.get("post_time"), "post_time"),
        "account_id": identity["account_id"], "profile": identity["profile"],
        "observed_at": observed_at, "server_timestamp_ms": measured_at,
        "provenance": "https://www.tiktok.com" + STUDIO_ITEMS_PATH,
        "metrics": {name: decimal(raw.get(field), field) for name, field in METRIC_FIELDS.items()},
    }
    for field in ("visibility", "status"):
        value = raw.get(field)
        if value is not None and (type(value) is not int or value < 0):
            raise StudioContractError(f"TikTok Studio {field} is malformed.")
        record[field] = value
    for field in ("in_review", "is_pinned"):
        value = raw.get(field)
        if value is not None and type(value) is not bool:
            raise StudioContractError(f"TikTok Studio {field} is malformed.")
        record[field] = value
    return record


def validate_page(payload):
    if not isinstance(payload, dict) or type(payload.get("status_code")) is not int or payload["status_code"] != 0:
        raise StudioContractError("TikTok Studio read was not successful; content is unverified.")
    if payload.get("is_limited") is not False:
        raise StudioContractError("TikTok Studio content read is limited or malformed; result is inconclusive.")
    if not isinstance(payload.get("item_list"), list) or type(payload.get("has_more")) is not bool:
        raise StudioContractError("TikTok Studio pagination is malformed; result is inconclusive.")
    cursor = payload.get("cursor")
    if type(cursor) is not int or cursor < 0 or cursor > 2**53 - 1:
        raise StudioContractError("TikTok Studio cursor is malformed; result is inconclusive.")
    extra = payload.get("extra")
    if extra is not None and not isinstance(extra, dict):
        raise StudioContractError("TikTok Studio measurement provenance is malformed.")
    measured_at = (extra or {}).get("now")
    if measured_at is not None and (type(measured_at) is not int or measured_at < 0):
        raise StudioContractError("TikTok Studio server timestamp is malformed.")
    if extra is not None and "fatal_item_ids" in extra:
        if not isinstance(extra["fatal_item_ids"], list) or extra["fatal_item_ids"]:
            raise StudioContractError("TikTok Studio omitted failed items or supplied malformed metadata; result is inconclusive.")
    return payload["item_list"], payload["has_more"], cursor, measured_at

# Capture one native read so signing/CSRF/session values stay in page memory.
# The only UI control used is the live-observed Studio Views sorting button.
CAPTURE_JS = r"""(opts) => {
 const key=opts.key,target=opts.path;
 const proto=XMLHttpRequest.prototype;
 const saved={open:proto.open,send:proto.send,header:proto.setRequestHeader};
 const state={request:null,restore:()=>{proto.open=saved.open;proto.send=saved.send;proto.setRequestHeader=saved.header}};
 window[key]=state;
 proto.open=function(method,url,...rest){
   let matched=false;
   try {const parsed=new URL(String(url),location.href);matched=method==='POST'&&parsed.origin==='https://www.tiktok.com'&&parsed.pathname===target;} catch (_) {}
   this[key]=matched?{url:String(url),headers:{}}:null;
   return saved.open.call(this,method,url,...rest);
 };
 proto.setRequestHeader=function(name,value){if(this[key])this[key].headers[name]=value;return saved.header.call(this,name,value)};
 proto.send=function(body){const request=this[key];if(request&&typeof body==='string'){
   try {const parsed=JSON.parse(body);if(parsed.cursor===0&&parsed.size===opts.page_size){request.body=parsed;this.addEventListener('loadend',()=>{
     if(!state.request&&this.status===200&&this.responseType===''){state.request=request;state.restore();}
   });}} catch (_) {}
 }return saved.send.call(this,body)};
 return true;
}"""
READY_JS = "(key) => Boolean(window[key] && window[key].request)"
FETCH_JS = r"""async (opts) => {
 const state=window[opts.key];if(!state||!state.request)return {status:0,body:''};
 const request=state.request;
 const body={...request.body,cursor:opts.cursor};
 const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),15000);
 try {
   const response=await fetch(request.url,{method:'POST',headers:request.headers,credentials:'include',body:JSON.stringify(body),signal:controller.signal,redirect:'error'});
   const header=response.headers?.get('Retry-After');const retryAfter=typeof header==='string'&&header.length<=200?header:null;
   if(response.status!==200){try{await response.body?.cancel();}catch(_){}return {status:response.status,body:null,retryAfter};}
   const reader=response.body?.getReader();if(!reader)return {status:response.status,body:null};
   const chunks=[];let size=0;
   try {while(true){const part=await reader.read();if(part.done)break;size+=part.value.byteLength;
     if(size>opts.max_body){await reader.cancel();return {status:response.status,body:null};}chunks.push(part.value);}}
   finally {reader.releaseLock();}
   const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.byteLength;}
   return {status:response.status,body:new TextDecoder('utf-8',{fatal:true}).decode(bytes)};
 } catch(error){return {status:0,body:null,transport:error?.name==='AbortError'?'timeout':'network'};}
 finally {clearTimeout(timer);}
}"""
CLEANUP_JS = "(key) => {const state=window[key];if(state){state.restore();delete window[key]}return true}"


# Only observed body semantics leave page memory. Signed URLs/headers never do.
SEMANTICS_JS = r"""(key) => {
 const request=window[key]?.request;if(!request)return null;
 const body=request.body;
 if(Object.keys(body).sort().join(',')!=='cursor,query,size')return null;
 const q=body.query;
 if(!q||Object.keys(q).sort().join(',')!=='conditions,is_recent_posts,sort_orders'||
    !Array.isArray(q.conditions)||q.conditions.length||q.is_recent_posts!==false||
    !Array.isArray(q.sort_orders)||q.sort_orders.length!==1||
    Object.keys(q.sort_orders[0]).sort().join(',')!=='field_name,order'||
    q.sort_orders[0].field_name!=='post_time'||q.sort_orders[0].order!==2)return null;
 return {path:'/tiktok/creator/manage/item_list/v1/',size:body.size,query:q};
}"""

class StudioReader:
    """One native capture shared by list, single lookup, and batch reads."""
    def __init__(self, page, key, identity):
        self.page, self.key, self.identity = page, key, identity

    def read_page(self, cursor):
        from datetime import datetime, timezone
        response = self.page.evaluate(FETCH_JS, {"key": self.key, "cursor": cursor, "max_body": MAX_RESPONSE_BYTES})
        if not isinstance(response, dict) or type(response.get("status")) is not int:
            raise StudioContractError("TikTok Studio content response is malformed; result is inconclusive.")
        status = response["status"]
        if status != 200:
            category = "rate_limit" if status == 429 else "auth" if status in (401,403) else "transient" if status == 0 or 500 <= status <= 599 else "upstream"
            code = "studio_transport_timeout" if status == 0 and response.get("transport") == "timeout" else "studio_transport_failed" if status == 0 else "studio_http_" + str(status)
            raise StudioContractError("TikTok Studio content request failed; result is inconclusive.",
                                      code=code, category=category, status=status,
                                      retry_after_seconds=retry_after_seconds(response.get("retryAfter")))
        if not isinstance(response.get("body"), str):
            raise StudioContractError("TikTok Studio content body is unavailable or oversized; result is inconclusive.")
        raw, more, next_cursor, measured = validate_page(parse_response(response["body"]))
        if len(raw) > STUDIO_PAGE_SIZE:
            raise StudioContractError("TikTok Studio page exceeds the observed page bound.")
        observed = datetime.now(timezone.utc).isoformat()
        records = [normalize_item(item, self.identity, observed, measured) for item in raw]
        if len({record["id"] for record in records}) != len(records):
            raise StudioContractError("TikTok Studio repeated a video; pagination is inconclusive.")
        if more and (not records or next_cursor <= cursor):
            raise StudioContractError("TikTok Studio cursor did not advance; result is inconclusive.")
        return records, more, next_cursor

    def semantics_digest(self):
        import hashlib
        semantics = self.page.evaluate(SEMANTICS_JS, self.key)
        expected = {"path": STUDIO_ITEMS_PATH, "size": STUDIO_PAGE_SIZE,
                    "query": {"sort_orders": [{"field_name": "post_time", "order": 2}],
                              "conditions": [], "is_recent_posts": False}}
        # Exact JSON equality also rejects bool-for-int substitutions.
        if json.dumps(semantics, sort_keys=True) != json.dumps(expected, sort_keys=True):
            raise StudioContractError("TikTok Studio native request semantics changed; result is inconclusive.")
        return hashlib.sha256(json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
