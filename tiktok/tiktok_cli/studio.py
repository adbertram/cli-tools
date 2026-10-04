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


def normalize_item(raw, identity, observed_at, measured_at):
    if not isinstance(raw, dict):
        raise StudioContractError("TikTok Studio item is malformed.")
    item_id = raw.get("item_id")
    if not isinstance(item_id, str) or not re.fullmatch(r"[1-9][0-9]{0,63}", item_id):
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
    if type(cursor) is not int or cursor < 0:
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
     if(this.status===200&&this.responseType===''){state.request=request;state.restore();}
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
   const response=await fetch(request.url,{method:'POST',headers:request.headers,credentials:'include',body:JSON.stringify(body),signal:controller.signal});
   const text=await response.text();return {status:response.status,body:text.length<=opts.max_body?text:null};
 } finally {clearTimeout(timer);}
}"""
CLEANUP_JS = "(key) => {const state=window[key];if(state){state.restore();delete window[key]}return true}"
