"""Journaled Studio drafts and single-dispatch publication through the owned browser.

Public posting always requires a trusted Python callback. The callback belongs to
the caller: it must inspect the caller's authoritative state immediately before
Post. This module never reads coordinator databases or executes shell permits.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import time
from typing import Callable
from uuid import UUID

from .client import (ACCOUNT_INFO_PATH, ClientError, TikTokWebClient,
                     normalize_account_identity)
from .studio import parse_response, positive_decimal_id

UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=upload"
POST_PATH = "/tiktok/web/project/post/v1/"
PROJECT_STATUS_PATH = "/tiktok/web/project/status/v1/"
FILE_SELECTOR = 'input[type="file"][accept="video/*"]'
CAPTION_SELECTOR = '[data-e2e="caption_container"] [contenteditable="true"]'
DISCLOSURE_SELECTOR = '[data-e2e="disclose_content_container"] input[role="switch"]'
POST_SELECTOR = '[data-e2e="post_video_button"]'
MAX_ASSET_BYTES = 30_000_000_000  # Studio's observed 30 GB upload limit.
MIN_FREE_BYTES = 1 << 30  # Keep 1 GiB free after the private staging copy.
MEDIA_BINDING_FIELDS = ("creation_id", "video_id", "file_key", "file_name", "file_size", "duration_ms")
ORPHAN_BINDING_FIELDS = ("draft_id", "project_id") + MEDIA_BINDING_FIELDS

DRAFTS_JS = r"""async (owner) => {
 if(!(await indexedDB.databases()).some(x=>x.name==='web_creation_draft'))return [];
 return await new Promise((resolve,reject)=>{
  const r=indexedDB.open('web_creation_draft');r.onerror=()=>reject(Error('DRAFT_READ_FAILED'));
  r.onsuccess=()=>{const db=r.result,name='local_draft_'+owner;
   if(!db.objectStoreNames.contains(name)){db.close();return resolve([])}
   const q=db.transaction(name,'readonly').objectStore(name).getAll();
   q.onerror=()=>{db.close();reject(Error('DRAFT_READ_FAILED'))};q.onsuccess=()=>{
    try {const rows=q.result.map(v=>{const data=v.data, basic=data.basic_info,
     media=basic.media_draft_info,desc=media.video_file_desc?JSON.parse(media.video_file_desc):{};
     return {draft_id:v.key,creation_id:basic.creation_id,is_temp:v.isTemp,
      create_time:v.createTime,is_locked:v.isLocked,project_id:basic.project_id,video_id:media.vid??null,
      file_key:desc.fileKey??null,file_name:desc.rawFile?.name??null,file_size:desc.rawFile?.size??null,
      duration_ms:media.video_duration_ms??null,stage:desc.stage??null,percent:desc.percent??null,
      caption:data.web_video_param_list?.[0]?.single_post_feature_info?.text??null,
      caption_markup:data.web_video_param_list?.[0]?.single_post_feature_info?.markup_text??null,
      caption_text_extra:data.web_video_param_list?.[0]?.single_post_feature_info?.text_extra??null,
      privacy:data.web_feature_common_info.privacy_setting_info,
      commercial:data.web_feature_common_info.tcm_params?JSON.parse(data.web_feature_common_info.tcm_params):null};});db.close();resolve(rows)
    }catch(e){db.close();reject(Error('DRAFT_SCHEMA_CHANGED'))}
   }
  }
 })
}"""

# Recovery deletes a journal-owned orphan only. Source-observed heartbeat
# cleanup treats numeric timestamps at least 1000 ms old as crashed/stale.
# No lock flags or heartbeat keys are changed. Binding is reread atomically.
HEARTBEAT_JS = r"""(owner) => {
 const key='web_creation_heartbeats_'+owner;
 const heartbeats=JSON.parse(localStorage.getItem(key)||'[]');
 if(!Array.isArray(heartbeats))throw Error('HEARTBEAT_SCHEMA_CHANGED');
 for(const name of heartbeats){
  if(typeof name!=='string'||!name.startsWith('web_creation_heartbeat_'))throw Error('HEARTBEAT_SCHEMA_CHANGED');
  const value=localStorage.getItem(name);
  if(value!==null){const timestamp=JSON.parse(value);
   if(typeof timestamp!=='number'||!Number.isFinite(timestamp))throw Error('HEARTBEAT_SCHEMA_CHANGED');
   if(Date.now()-timestamp<1000)throw Error('ACTIVE_STUDIO_HEARTBEAT')
  }
 }
 return true
}"""
DELETE_ORPHAN_JS = "async (opts) => {(" + HEARTBEAT_JS + ")(opts.owner);" + r"""
 return await new Promise((resolve,reject)=>{
  const r=indexedDB.open('web_creation_draft');r.onerror=()=>reject(Error('DRAFT_READ_FAILED'));
  r.onsuccess=()=>{const db=r.result,store='local_draft_'+opts.owner;
   if(!db.objectStoreNames.contains(store)){db.close();return reject(Error('OWNER_STORE_MISSING'))}
   const tx=db.transaction(store,'readwrite'),table=tx.objectStore(store),get=table.get(opts.expected.draft_id);
   let deleted=false;
   tx.onabort=()=>{db.close();reject(Error('ORPHAN_BINDING_REJECTED'))};
   tx.onerror=()=>{};tx.oncomplete=()=>{db.close();resolve({deleted,draft_id:opts.expected.draft_id})};
   get.onsuccess=()=>{try{const v=get.result;if(!v||v.isLocked!==true&&v.isTemp!==true)throw Error('NOT_LOCKED_ORPHAN');
    const basic=v.data.basic_info,media=basic.media_draft_info,desc=media.video_file_desc?JSON.parse(media.video_file_desc):{};
    const actual={draft_id:v.key,creation_id:basic.creation_id,project_id:basic.project_id,
     video_id:media.vid,file_key:desc.fileKey,file_name:desc.rawFile.name,
     file_size:desc.rawFile.size,duration_ms:media.video_duration_ms};
    if(Object.keys(opts.expected).some(k=>actual[k]!==opts.expected[k]))throw Error('BINDING_CHANGED');
    table.delete(opts.expected.draft_id);deleted=true;
   }catch(e){tx.abort()}}
  }
 })
}"""

CHECKBOX_JS = r"""(label) => {
 return [...document.querySelectorAll('input[type=checkbox]:not([role=switch])')].map(e=>{
  let p=e.parentElement;for(let i=0;i<5&&p;i++,p=p.parentElement){
   if(p.querySelectorAll('input[type=checkbox]').length!==1)break;
   if(p.innerText.trim()===label)return {id:e.id,checked:e.checked,disabled:e.disabled};
  }return null
 }).filter(Boolean)
}"""

CONTROLS_JS = r"""() => {
 const visible=e=>Boolean(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
 const caption=document.querySelector('[data-e2e="caption_container"] [contenteditable=true]');
 const privacy=document.querySelector('[data-e2e="video_visibility_container"] button[role=combobox]');
 const disclosureContainer=document.querySelector('[data-e2e="disclose_content_container"]');
 const disclosure=disclosureContainer?.querySelector('input[role=switch]');
 const schedule=document.querySelector('[data-e2e="schedule_container"]');
 const radios=schedule?[...schedule.querySelectorAll('input[type=radio]')]:[];
 const music=document.querySelector('[data-e2e="music_usage_confirmation_container"]');
 const consent=music?[...music.querySelectorAll('input[type=checkbox]')]:[];
 const post=document.querySelector('[data-e2e="post_video_button"]');
 return {caption:visible(caption)?caption.innerText:null,
  audience:visible(privacy)?privacy.innerText:null,disclosure:visible(disclosureContainer)?disclosure?.checked:null,
  now:radios.length===2&&radios[0].checked===true&&radios[1].checked===false,
  agreement:document.body.innerText.includes('By posting, you agree to our Branded Content Policy and Music Usage Confirmation.'),
  music_present:visible(music),music_checks:consent.map(e=>({checked:e.checked,disabled:e.disabled})),
  upload_complete:document.body.innerText.includes('Uploaded'),
  post_enabled:visible(post)&&!post.disabled,
  dialogs:[...document.querySelectorAll('[role=dialog]')].filter(visible).map(e=>e.innerText)}
}"""

# The site's own post transport runs once. Tokens and signing values stay in
# browser memory. Only bounded response text and exact project IDs are exported.
OBSERVER_JS = r"""(opts) => {
 const proto=XMLHttpRequest.prototype,open=proto.open,send=proto.send;
 const state={count:0,receipt:null,creation_id:null,video_id:null,batch_index:null,project_id_present:null,blocked:null,
  restore:()=>{proto.open=open;proto.send=send}};window[opts.key]=state;
 proto.open=function(method,url,...rest){let match=false;
  try{const u=new URL(String(url),location.href);match=method==='POST'&&u.origin==='https://www.tiktok.com'&&u.pathname===opts.path}catch(_){}
  this[opts.key]=match;return open.call(this,method,url,...rest)
 };
 proto.send=function(body){if(this[opts.key]){state.count++;let valid=false;
  try{const p=JSON.parse(body),common=p.post_common_info,items=p.single_post_req_list;
   state.creation_id=common?.creation_id??null;
   state.project_id_present=Object.hasOwn(common??{},'project_id');
   const item=Array.isArray(items)&&items.length===1?items[0]:null;
   state.video_id=item?.video_id??null;state.batch_index=item?.batch_index??null;
   const feature=item?.single_post_feature_info,extra=feature?.text_extra;
   const entities=Array.isArray(extra)&&extra.length===opts.caption_text_extra.length&&extra.every((value,index)=>{
    const expected=opts.caption_text_extra[index];return value&&Object.keys(value).sort().join(',')===Object.keys(expected).sort().join(',')&&Object.keys(expected).every(k=>value[k]===expected[k])});
   valid=common&&Object.keys(common).sort().join(',')==='creation_id,enter_post_page_from,post_type'&&
    Array.isArray(items)&&items.length===1&&state.creation_id===opts.creation_id&&
    state.video_id===opts.video_id&&state.batch_index===0&&!state.project_id_present&&feature?.text===opts.caption&&entities
  }catch(_){}
  if(state.count!==1||!valid){state.blocked='POST_BINDING_OR_DUPLICATE_REJECTED';this.abort();throw Error(state.blocked)}
  this.addEventListener('loadend',()=>{state.receipt={status:this.status,
   body:this.responseType===''&&this.responseText.length<=1000000?this.responseText:null}})
 }return send.call(this,body)};return true
}"""
RECEIPT_JS = "(key)=>{const s=window[key];return s?{count:s.count,receipt:s.receipt,creation_id:s.creation_id,video_id:s.video_id,batch_index:s.batch_index,project_id_present:s.project_id_present}:null}"
RESTORE_JS = "(key)=>{const s=window[key];if(s){s.restore();delete window[key]}return true}"
CAPTION_TEXT_JS = "(selector)=>[...document.querySelector(selector).querySelectorAll('[data-block=true]')].map(x=>x.textContent).join('\\n')"
CAPTION_READY_JS = r"""(selector)=>{const e=document.querySelector(selector),s=window.getSelection();
 if(!e||!e.contains(document.activeElement)||!s||!s.isCollapsed||!e.contains(s.anchorNode)||!e.contains(s.focusNode))return false;
 const r=document.createRange();r.selectNodeContents(e);r.setStart(s.focusNode,s.focusOffset);return r.toString()===''}"""
CAPTION_OPTIONS_JS = r"""(kind)=>[...document.querySelectorAll(kind==='mention'?'[role=option].mention-suggestion-item':'[role=option].hashtag-suggestion-item')]
 .filter(x=>x.getClientRects().length).map(x=>({id:x.id,name:kind==='mention'?x.querySelector('.user-id')?.innerText.split(' · ')[0]:x.querySelector('.hash-tag-topic')?.innerText}))"""
CAPTION_TOKEN_RE = re.compile(r'(?<![\w.@])(@[A-Za-z0-9._]+|#\w+)', re.UNICODE)


class StudioPublishError(ClientError):
    """Explicit failure category distinguishes safe aborts from unknown writes."""

    def __init__(self, message: str, *, category="pre_action_abort"):
        super().__init__(message)
        self.category = category


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def caption_tokens(caption):
    return list(CAPTION_TOKEN_RE.finditer(caption))


def caption_entities(row, caption):
    """Verify the native saved Draft.js ranges and derive its Post text_extra."""
    def invalid():
        raise StudioPublishError('Studio saved caption mention/hashtag entities are unverified.')
    try:
        raw = parse_response(row['caption_markup'])
        blocks, entities = raw['blocks'], raw['entityMap']
        if not isinstance(blocks, list) or not isinstance(entities, dict) or '\n'.join(b['text'] for b in blocks) != caption:
            invalid()
        ranges = []
        base = 0
        for block in blocks:
            for value in block['entityRanges']:
                if any(type(value.get(k)) is not int or value[k] < 0 for k in ('key', 'offset', 'length')):
                    invalid()
                entity = entities[str(value['key'])]
                mention = entity['data']['mention']
                ranges.append({'start': base + value['offset'], 'length': value['length'], 'key': value['key'], 'entity': entity, 'mention': mention})
            base += len(block['text'].encode('utf-16-le')) // 2 + 1
        tokens = caption_tokens(caption)
        if len(tokens) != len(ranges) or len(entities) != len(ranges):
            invalid()
        result = []
        for token in tokens:
            text = token.group();start = len(caption[:token.start()].encode('utf-16-le')) // 2;length = len(text.encode('utf-16-le')) // 2
            matches = [r for r in ranges if type(r['start']) is int and type(r['length']) is int and r['start'] == start and r['length'] == length]
            if len(matches) != 1:invalid()
            value = matches[0];mention = value['mention'];entity = value['entity'];is_user = text.startswith('@')
            if type(value['key']) is not int or mention.get('name') != text[1:] or mention.get('type') != ('at' if is_user else 'hashTag') or entity.get('type') != ('mention' if is_user else '#mention') or entity.get('mutability') != 'IMMUTABLE':invalid()
            uid = mention.get('uid', mention.get('id')) if is_user else ''
            if is_user and not positive_decimal_id(uid):invalid()
            result.append({'tag_id': str(value['key']), 'start': start, 'end': start + length, 'user_id': uid, 'type': 0 if is_user else 1, 'hashtag_name': '' if is_user else text[1:]})
        # The observed serializer generates outgoing extras from entityMap.
        # Saved drafts may keep an empty text_extra; nonempty values must agree.
        if row.get('caption_text_extra') not in ([], result):invalid()
        return result
    except (KeyError, TypeError, ValueError, AttributeError, UnicodeError):
        invalid()


def validate_policy(value: dict) -> dict:
    """Require explicit identity, exact caption, public timing and music rights."""
    required = {"schema_version", "profile", "account_id", "username", "caption",
                "audience", "timing", "disclosure", "music_rights_confirmed"}
    if not isinstance(value, dict) or set(value) != required:
        raise StudioPublishError("Studio policy requires every documented field and rejects unknown fields.")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise StudioPublishError("Studio policy schema_version must be 1.")
    if not isinstance(value["profile"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value["profile"]) or value["profile"] == "default":
        raise StudioPublishError("Studio publishing requires an explicit named profile.")
    if not positive_decimal_id(value["account_id"]):
        raise StudioPublishError("Studio policy account_id must be an exact positive decimal string.")
    if not isinstance(value["username"], str) or not re.fullmatch(r"[A-Za-z0-9_.]{1,256}", value["username"]):
        raise StudioPublishError("Studio policy username must be an exact handle without @.")
    if not isinstance(value["caption"], str) or not value["caption"].strip() or len(value["caption"]) > 4000:
        raise StudioPublishError("Studio policy caption must contain 1 to 4000 characters.")
    if (value["audience"], value["timing"], value["disclosure"]) != ("Everyone", "now", "branded_content"):
        raise StudioPublishError("Studio publisher supports Everyone, now, and branded_content only.")
    if value["music_rights_confirmed"] is not True:
        raise StudioPublishError("Studio publishing requires explicit confirmation of music rights.")
    return dict(value)


def request_uuid(value: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise StudioPublishError("request_id must be a canonical UUID.") from None
    if str(parsed) != value:
        raise StudioPublishError("request_id must be a canonical UUID.")
    return value


def accepted_project(observed: dict, operation: dict) -> dict:
    """Validate the guarded native acceptance before parsing optional task IDs."""
    def unknown():
        raise StudioPublishError("Studio Post outcome is unknown; automatic retry is prohibited.", category="ambiguous_post_action")
    if not isinstance(observed, dict) or type(observed.get("count")) is not int or observed["count"] != 1:
        unknown()
    if observed.get("project_id_present") is not False or observed.get("creation_id") != operation["draft"]["creation_id"] or observed.get("video_id") != operation["draft"]["video_id"] or type(observed.get("batch_index")) is not int or observed["batch_index"] != 0:
        unknown()
    response = observed.get("receipt")
    if not isinstance(response, dict) or response.get("status") != 200 or not isinstance(response.get("body"), str):
        unknown()
    try:
        payload = parse_response(response["body"])
    except ValueError:
        unknown()
    if not isinstance(payload, dict) or type(payload.get("status_code")) is not int or payload["status_code"] != 0:
        unknown()
    if not positive_decimal_id(payload.get("project_id")):
        unknown()
    return payload


def receipt_item_id(payload: dict) -> str | None:
    """Async native Post may accept a project before an item exists."""
    entries = payload.get("single_post_resp_list")
    if entries is None or entries == []:
        return None
    def unknown():
        raise StudioPublishError("Studio accepted project has an invalid task receipt; reconcile only.", category="ambiguous_post_action")
    if not isinstance(entries, list) or len(entries) != 1:
        unknown()
    entry = entries[0]
    if not isinstance(entry, dict) or type(entry.get("status_code")) is not int or entry["status_code"] != 0:
        unknown()
    if type(entry.get("batch_index")) is not int or entry["batch_index"] != 0:
        unknown()
    item = entry.get("item_id")
    if item is None:
        return None
    if not positive_decimal_id(item):
        unknown()
    return item


def project_status(payload: dict) -> tuple[str, str | None]:
    """Source-observed project/task enums, with one exact single-file task."""
    def malformed():
        raise StudioPublishError("Exact Studio project status is malformed; reconcile only, never retry.", category="ambiguous_post_action")
    if not isinstance(payload, dict) or type(payload.get("status_code")) is not int or payload["status_code"] != 0:
        malformed()
    state = payload.get("project_status")
    tasks = payload.get("task_list")
    if type(state) is not int or state not in (0, 1, 2, 3, 4) or not isinstance(tasks, list) or len(tasks) != 1:
        malformed()
    task = tasks[0]
    if not isinstance(task, dict) or type(task.get("task_status")) is not int or task["task_status"] not in (0, 1, 2, 3):
        malformed()
    task_state = task["task_status"]
    if state == 3 or task_state == 3:
        if state == 2 or task_state == 2:
            malformed()
        return "post_failed", None
    if state == 0:
        return "project_unknown", None
    if state in (1, 4):
        return "project_pending", None
    if task_state != 2:
        malformed()
    item = task.get("item_id")
    if not positive_decimal_id(item):
        malformed()
    return "receipt_observed", item


class StudioPublisher:
    """Own runtime journal and exact uploaded-draft bindings, with no write retry."""

    def __init__(self, config, browser=None):
        self.config = config
        self.browser = browser
        self.page = None
        self.owns_browser = browser is None
        self.client = TikTokWebClient(config=config, max_retries=0)
        self.root = Path(config.get_profile_data_dir()) / "studio-publishing"
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self.database = self.root / "operations.sqlite3"
        self._initialize()

    def _initialize(self):
        with sqlite3.connect(self.database) as db:
            db.execute("CREATE TABLE IF NOT EXISTS operations (request_id TEXT PRIMARY KEY, binding TEXT UNIQUE NOT NULL, record TEXT NOT NULL)")
        self.database.chmod(0o600)

    @contextmanager
    def _locked(self):
        descriptor = os.open(self.root / "operation.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise StudioPublishError("Another Studio operation owns this profile; no action performed.") from None
            yield
        finally:
            os.close(descriptor)

    def _save(self, operation):
        operation["updated_at"] = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO operations VALUES (?, ?, ?) ON CONFLICT(request_id) DO UPDATE SET record=excluded.record",
                       (operation["request_id"], operation["binding"], canonical(operation)))

    def status(self, request_id: str) -> dict:
        request_uuid(request_id)
        with sqlite3.connect(self.database) as db:
            row = db.execute("SELECT record FROM operations WHERE request_id=?", (request_id,)).fetchone()
        if row is None:
            raise StudioPublishError("Studio request_id is not in this profile's operation journal.")
        return parse_response(row[0])

    def _migrate_owned_continue(self, request_id, receipt):
        """One operator-authorized migration of a recorded pre-upgrade Continue.

        This is deliberately absent from the CLI. The caller must supply the
        session's actual native Continue receipt, not an arbitrary draft ID.
        It changes journal project metadata only; draft storage is untouched.
        """
        with self._locked():
            operation = self.status(request_id)
            prior = canonical(operation)
            if operation['state'] not in {'prepared', 'preparation_failed'} or operation.get('public_action_dispatched') is not False or operation.get('project_id') != '0' or operation['draft'].get('project_id') != '0':
                raise StudioPublishError('Recorded Continue migration requires the original private project zero.')
            if not isinstance(receipt, dict) or receipt.get('resumed') is not True or receipt.get('banner') != 1 or receipt.get('draft_count') != 1 or receipt.get('draft_id') != operation['draft_id'] or receipt.get('actor') != operation['actor'] or not isinstance(receipt.get('row'), dict) or not isinstance(receipt.get('dom'), dict) or receipt['dom'].get('editor') != 1:
                raise StudioPublishError('Recorded native Continue receipt is not exact.')
            configured = operation['state'] == 'prepared'
            previous = self._match_draft(operation, [receipt.get('row')], check_controls=configured)
            if not configured and any(previous.get(k) != operation['draft'].get(k) for k in ('caption', 'privacy', 'commercial', 'create_time')):
                raise StudioPublishError('Recorded failed private draft state changed.')
            if previous.get('project_id') != '0':
                raise StudioPublishError('Recorded Continue did not start at project zero.')
            policy = validate_policy(operation['policy'])
            if digest(policy) != operation['policy_digest'] or digest({'asset_sha256': operation['asset_sha256'], 'policy': policy}) != operation['binding']:
                raise StudioPublishError('Recorded Continue immutable policy binding changed.')
            self._verify_asset(operation)
            page = self._page()
            page.wait_for_timeout(1500)
            actor = self._identity(page, operation['policy'])
            current = self._match_draft(operation, self._drafts(page, operation['policy']), check_controls=configured)
            if not configured and any(current.get(k) != previous.get(k) for k in ('caption', 'privacy', 'commercial', 'create_time')):
                raise StudioPublishError('Recorded failed private draft state changed.')
            if actor != operation['actor'] or not positive_decimal_id(current.get('project_id')):
                raise StudioPublishError('Recorded Continue actor or assigned project is unverified.')
            operation.setdefault('editor_project_transitions', []).append({
                'kind': 'operator_recorded_native_continue_v1', 'from_project_id': '0',
                'to_project_id': current['project_id'], 'creation_id': current['creation_id'],
                'receipt_digest': digest(receipt), 'asset_sha256': operation['asset_sha256'],
                'observed_at': datetime.now(timezone.utc).isoformat()})
            operation['project_id'] = current['project_id']
            operation['draft'] = current
            operation['updated_at'] = datetime.now(timezone.utc).isoformat()
            with sqlite3.connect(self.database) as db:
                db.execute('BEGIN IMMEDIATE')
                changed = db.execute('UPDATE operations SET record=? WHERE request_id=? AND binding=? AND record=?',
                    (canonical(operation), request_id, operation['binding'], prior)).rowcount
                if changed != 1:
                    raise StudioPublishError('Recorded Continue journal changed; migration refused.')
            return operation

    def _page(self):
        if self.browser is None:
            self.browser = self.config.get_browser()
        if self.page is None:
            self.page = self.browser.get_page(UPLOAD_URL)
        return self.page

    def _identity(self, page, policy):
        if self.config.get_active_profile_name() != policy["profile"]:
            raise StudioPublishError("Studio policy profile does not match the active named profile.")
        identity = normalize_account_identity(self.client._fetch_json(page, ACCOUNT_INFO_PATH))
        if identity["account_id"] != policy["account_id"] or identity["username"] != policy["username"]:
            raise StudioPublishError("Studio actor does not match the exact policy account ID and username.")
        return {**identity, "profile": policy["profile"]}

    def _drafts(self, page, policy):
        rows = page.evaluate(DRAFTS_JS, policy["account_id"])
        if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("draft_id"), str) for row in rows):
            raise StudioPublishError("Studio local draft inventory is malformed.")
        return rows

    def _wait(self, page, predicate, message, seconds=60):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            result = predicate()
            if result:
                return result
            page.wait_for_timeout(250)
        raise StudioPublishError(message)

    def _checkbox(self, page, label):
        candidates = page.evaluate(CHECKBOX_JS, label)
        if not isinstance(candidates, list) or len(candidates) != 1 or not candidates[0].get("id"):
            raise StudioPublishError(f"Studio {label} checkbox is unavailable or ambiguous.")
        return candidates[0]

    def _configure(self, page, policy, draft=None):
        caption = page.locator(CAPTION_SELECTOR)
        if caption.count() != 1:
            raise StudioPublishError("Studio caption editor is unavailable or ambiguous.")
        self._set_caption(page, policy, draft)
        page.wait_for_timeout(300)
        if page.locator('.more-btn > span:first-child:has-text("Show more")').count() == 1:
            page.locator('.more-btn > span:first-child:has-text("Show more")').click()
        page.wait_for_timeout(300)
        audience = page.locator('[data-e2e="video_visibility_container"] button[role="combobox"]')
        if audience.count() != 1:
            raise StudioPublishError("Studio audience selector is unavailable or ambiguous.")
        audience.click()
        everyone = page.get_by_role("option", name="Everyone", exact=True)
        if everyone.count() != 1:
            raise StudioPublishError("Studio Everyone option is unavailable or ambiguous.")
        everyone.click()
        now = page.locator('[data-e2e="schedule_container"] input[type="radio"][value="post_now"]')
        if now.count() != 1:
            raise StudioPublishError("Studio Now option is unavailable or ambiguous.")
        now.check()
        disclosure = page.locator(DISCLOSURE_SELECTOR)
        if disclosure.count() != 1:
            raise StudioPublishError("Studio disclosure switch is unavailable or ambiguous.")
        if not disclosure.is_checked():
            disclosure.check()
        page.wait_for_timeout(300)
        own = self._checkbox(page, "Your brand")
        if own["disabled"]:
            raise StudioPublishError("Studio Your brand is disabled.")
        if own["checked"]:
            page.locator('input[id="' + own["id"] + '"]').uncheck()
        branded = self._checkbox(page, "Branded content")
        if branded["disabled"]:
            raise StudioPublishError("Studio Branded content is disabled.")
        if not branded["checked"]:
            page.locator('input[id="' + branded["id"] + '"]').check()
        page.wait_for_timeout(300)
        # Only the observed agreement is supported. An unexpected modal or
        # separate unchecked music checkbox fails verification before Post.
        return self._verify_controls(page, policy)

    def _set_caption(self, page, policy, saved=None):
        self._caption_semantic_rollback_unverified = False
        caption = policy['caption']
        if saved is not None:
            try:
                caption_entities(saved, caption)
                if page.evaluate(CAPTION_TEXT_JS, CAPTION_SELECTOR) == caption:
                    return
            except StudioPublishError:
                pass
        previous = page.evaluate(CAPTION_TEXT_JS, CAPTION_SELECTOR)
        if not isinstance(previous, str):
            raise StudioPublishError('Studio caption editor text is unavailable.')
        page.fill_framework_input(CAPTION_SELECTOR, '')
        if page.evaluate(CAPTION_TEXT_JS, CAPTION_SELECTOR) != '':
            raise StudioPublishError('Studio native caption clear did not update the editor.')
        try:
            cursor = 0
            for token in caption_tokens(caption):
                self._wait(page, lambda: page.evaluate(CAPTION_READY_JS, CAPTION_SELECTOR), 'Studio caption focus/caret is unverified.', seconds=3)
                if caption[cursor:token.start()]:
                    page.type_text(caption[cursor:token.start()])
                self._wait(page, lambda: page.evaluate(CAPTION_TEXT_JS, CAPTION_SELECTOR) == caption[:token.start()], 'Studio caption prefix did not update.', seconds=3)
                text = token.group();kind = 'mention' if text.startswith('@') else 'hashtag'
                trigger = page.get_by_role('button', name='Mention' if kind == 'mention' else 'Hashtag', exact=True)
                if trigger.count() != 1:
                    raise StudioPublishError('Studio caption entity trigger is unavailable or ambiguous.')
                trigger.click()
                self._wait(page, lambda: page.evaluate(CAPTION_TEXT_JS, CAPTION_SELECTOR) == caption[:token.start()] + text[0], 'Studio caption entity trigger did not update.', seconds=3)
                self._wait(page, lambda: page.evaluate(CAPTION_READY_JS, CAPTION_SELECTOR), 'Studio caption entity trigger did not restore focus/caret.', seconds=3)
                page.type_text(text[1:])
                self._wait(page, lambda: page.evaluate(CAPTION_TEXT_JS, CAPTION_SELECTOR) == caption[:token.end()], 'Studio caption query did not update.', seconds=3)
                def exact_option():
                    options = page.evaluate(CAPTION_OPTIONS_JS, kind)
                    if not isinstance(options, list):raise StudioPublishError('Studio caption suggestions changed schema.')
                    matches = [x for x in options if isinstance(x, dict) and x.get('name') == (text[1:] if kind == 'mention' else text)]
                    if len(matches) > 1:raise StudioPublishError('Studio exact caption suggestion is ambiguous.')
                    return matches[0] if matches else None
                option = self._wait(page, exact_option, 'Studio exact caption suggestion is unavailable.', seconds=10)
                if not isinstance(option.get('id'), str) or not re.fullmatch(r'mention-option-[A-Za-z0-9_-]+', option['id']):
                    raise StudioPublishError('Studio caption suggestion target is unverified.')
                page.click_native('#'+option['id'])
                expected = caption[:token.end()]
                actual = self._wait(page, lambda: (value if (value := page.evaluate(CAPTION_TEXT_JS, CAPTION_SELECTOR)) in (expected, expected + ' ') else None), 'Studio selected entity did not update the caption.', seconds=3)
                if actual == expected + ' ':
                    page.keyboard_press('Backspace')
                self._wait(page, lambda: page.evaluate(CAPTION_TEXT_JS, CAPTION_SELECTOR) == expected, 'Studio selected entity changed the exact caption.', seconds=3)
                def entity_saved():
                    if saved is None:raise StudioPublishError('Studio caption editing requires exact draft ownership.')
                    rows = [r for r in self._drafts(page, policy) if r['draft_id'] == saved['draft_id']]
                    if len(rows) != 1 or any(rows[0].get(k) != saved.get(k) for k in MEDIA_BINDING_FIELDS):
                        raise StudioPublishError('Studio caption draft ownership changed.')
                    if rows[0]['caption'] != expected:return False
                    try:caption_entities(rows[0], expected)
                    except StudioPublishError:return False
                    return True
                self._wait(page, entity_saved, 'Studio selected native entity did not persist.', seconds=10)
                cursor = token.end()
            if caption[cursor:]:page.type_text(caption[cursor:])
            if page.evaluate(CAPTION_TEXT_JS, CAPTION_SELECTOR) != caption:
                raise StudioPublishError('Studio native caption does not match the exact policy.')
        except Exception:
            self._caption_semantic_rollback_unverified = True
            page.fill_framework_input(CAPTION_SELECTOR, '')
            page.type_text(previous)
            raise

    def _saved_caption_draft(self, operation, page, policy):
        row = self._match_draft(operation, self._drafts(page, policy))
        try:
            caption_entities(row, policy['caption'])
        except StudioPublishError:
            return None
        return row

    def _verify_controls(self, page, policy):
        state = page.evaluate(CONTROLS_JS)
        branded = self._checkbox(page, "Branded content")
        own = self._checkbox(page, "Your brand")
        if not isinstance(state, dict) or state.get("caption") != policy["caption"]:
            raise StudioPublishError("Studio caption does not exactly match the policy.")
        if state.get("audience") != "Everyone" or state.get("now") is not True:
            raise StudioPublishError("Studio audience or Now control is not verified.")
        if state.get("disclosure") is not True or branded["checked"] is not True or own["checked"] is not False:
            raise StudioPublishError("Studio branded disclosure choices do not match the policy.")
        if state.get("agreement") is not True or state.get("music_present") is True and not state.get("music_checks") or any(x.get("checked") is not True for x in state.get("music_checks", [])):
            raise StudioPublishError("Studio music-use agreement or consent is unresolved.")
        # A single informational editing-tip dialog is not consent. Unknown
        # blocking dialogs must be handled outside publication.
        if state.get("dialogs"):
            raise StudioPublishError("Studio has an unresolved dialog; no public action performed.")
        if state.get("upload_complete") is not True or state.get("post_enabled") is not True:
            raise StudioPublishError("Studio upload completion or Post readiness is not verified.")
        return state

    def _match_draft(self, operation, rows, *, exact=True, require_entities=False, check_controls=True):
        matches = [r for r in rows if r["draft_id"] == operation["draft_id"]]
        if len(matches) != 1:
            raise StudioPublishError("Studio exact owned draft is missing or ambiguous.")
        row = matches[0]
        fields = MEDIA_BINDING_FIELDS
        if exact and any(row.get(key) != operation["draft"][key] for key in fields):
            raise StudioPublishError("Studio exact draft media binding changed.")
        if row["file_name"] != operation["staged_name"] or row["file_size"] != operation["asset_bytes"] or row["stage"] != "complete" or row["percent"] != 100:
            raise StudioPublishError("Studio draft does not match the exact completed upload.")
        if check_controls and (row["caption"] != operation["policy"]["caption"] or not isinstance(row["privacy"], dict) or row["privacy"].get("visibility_type") != 0 or not isinstance(row["commercial"], dict) or row["commercial"].get("commerce_toggle_info", {}).get("branded_content_type") != 2001):
            raise StudioPublishError("Studio persisted draft controls do not match the policy.")
        if require_entities:
            caption_entities(row, operation['policy']['caption'])
        return row

    def prepare(self, file: str | Path, policy: dict, request_id: str) -> dict:
        with self._locked():
            return self._prepare(file, policy, request_id)

    def _prepare(self, file: str | Path, policy: dict, request_id: str) -> dict:
        policy = validate_policy(policy)
        request_uuid(request_id)
        source = Path(file)
        if not source.is_file() or source.suffix.lower() != ".mp4":
            raise StudioPublishError("Studio prepare requires an existing MP4 file.")
        workspace = self.root / "media"
        workspace.mkdir(mode=0o700, exist_ok=True)
        staged = workspace / (request_id + ".mp4")
        hasher = hashlib.sha256()
        size = 0
        # A UUID never reuses mutable bytes. Write a private temporary file,
        # then move it only after request and duplicate checks pass.
        temporary = workspace / (request_id + ".tmp")
        expected_size = source.stat().st_size
        if not 0 < expected_size <= MAX_ASSET_BYTES:
            raise StudioPublishError("Studio asset must contain 1 byte to 30 GB.")
        if shutil.disk_usage(workspace).free < expected_size + MIN_FREE_BYTES:
            raise StudioPublishError("Studio staging requires asset size plus a 1 GiB free-disk reserve.")
        # The profile lock makes an exact UUID temp left by a crashed copy
        # safe to remove. Never remove other requests' staging files.
        if temporary.is_symlink():
            raise StudioPublishError("Studio owned temporary asset is a symlink; staging refused.")
        if temporary.exists():
            temporary.unlink()
        try:
            with source.open("rb") as original, temporary.open("xb") as copy:
                temporary.chmod(0o600)
                next_disk_check = 0
                while chunk := original.read(1024 * 1024):
                    size += len(chunk)
                    if size > expected_size or size > MAX_ASSET_BYTES:
                        raise StudioPublishError("Studio source asset changed or exceeded the upload limit during staging.")
                    if size >= next_disk_check or size == expected_size:
                        remaining = expected_size - (size - len(chunk))
                        if shutil.disk_usage(workspace).free < remaining + MIN_FREE_BYTES:
                            raise StudioPublishError("Studio free disk fell below the remaining asset plus 1 GiB reserve during staging.")
                        next_disk_check = size + 8 * 1024 * 1024
                    copy.write(chunk);hasher.update(chunk)
                if size != expected_size:
                    raise StudioPublishError("Studio source asset changed during staging.")
                copy.flush();os.fsync(copy.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        if not size:
            temporary.unlink()
            raise StudioPublishError("Studio upload asset is empty.")
        binding = digest({"asset_sha256": hasher.hexdigest(), "policy": policy})
        with sqlite3.connect(self.database) as db:
            existing = db.execute("SELECT request_id,record FROM operations WHERE request_id=? OR binding=?", (request_id, binding)).fetchone()
        if existing:
            record = parse_response(existing[1])
            if existing[0] != request_id or record["binding"] != binding:
                temporary.unlink()
                raise StudioPublishError("Studio asset/policy is already bound to a different request, or this request has changed.")
            if record["state"] == "prepared":
                temporary.unlink()
                self._verify_asset(record)
                return record
            if record["state"] not in {"preparing", "preparation_failed"} or record["public_action_dispatched"]:
                temporary.unlink()
                raise StudioPublishError("Studio request cannot be retried automatically; inspect status and reconcile.")
            if staged.is_symlink():
                temporary.unlink()
                raise StudioPublishError("Studio owned staged asset is a symlink; recovery refused.")
            if staged.exists():
                temporary.unlink()
            else:
                # Current source has exactly the journaled hash/policy binding.
                temporary.replace(staged)
            self._verify_asset(record)
            self._recover_private_preparation(record)
            # Cleanup removed only this request's private upload. Reuse
            # the verified staged bytes; the journal retains prior attempts.
            history = record.get("preparation_history", []) + [{k: record.get(k) for k in ("draft_id", "state", "updated_at")}]
            recovery_audit = record.get("orphan_recovery", [])
            editor_project_transitions = record.get('editor_project_transitions', [])
            temporary = None
        else:
            history = []
            recovery_audit = []
            editor_project_transitions = []
        if temporary is not None:
            temporary.replace(staged)
        operation = {"request_id": request_id, "binding": binding, "policy_digest": digest(policy),
                     "policy": policy, "asset_sha256": hasher.hexdigest(), "asset_bytes": size,
                     "staged_name": staged.name, "state": "preparing", "public_action_dispatched": False,
                     "preparation_history": history, "orphan_recovery": recovery_audit,
                     "editor_project_transitions": editor_project_transitions}
        self._save(operation)
        page = self._page()
        try:
            page.wait_for_timeout(1500)
            operation["actor"] = self._identity(page, policy)
            before = self._drafts(page, policy)
            operation["drafts_before"] = [r["draft_id"] for r in before]
            self._save(operation)
            if page.locator('[data-e2e="local_draft_container"]').count():
                raise StudioPublishError("Studio has an existing draft awaiting Continue; preserve it before preparing another request.")
            if page.evaluate(HEARTBEAT_JS, policy["account_id"]) is not True:
                raise StudioPublishError("Studio private preparation has an unresolved heartbeat context.")
            if page.locator(FILE_SELECTOR).count() != 1:
                raise StudioPublishError("Studio single-file upload control is unavailable or ambiguous.")
            page.set_input_files(FILE_SELECTOR, str(staged))
            self._wait(page, lambda: page.evaluate("()=>document.body.innerText.includes('Uploaded')"), "Studio upload did not complete.")
            def new_draft():
                return [r for r in self._drafts(page, policy) if r["draft_id"] not in operation["drafts_before"] and r["stage"] == "complete" and r["percent"] == 100 and isinstance(r["video_id"], str) and r["video_id"] and r["file_name"] == operation["staged_name"] and r["file_size"] == operation["asset_bytes"]]
            rows = self._wait(page, new_draft, "Studio upload did not yield an exact local draft.")
            if len(rows) != 1:
                raise StudioPublishError("Studio upload produced ambiguous draft IDs.")
            operation["draft_id"] = rows[0]["draft_id"]
            operation["draft"] = rows[0]
            self._save(operation)
            operation["controls"] = self._configure(page, policy, operation['draft'])
            def saved():
                row = self._match_draft(operation, self._drafts(page, policy), require_entities=True)
                return row
            # Autosave is asynchronous. Mismatch while saving is allowed
            # only during this bounded private preparation, never publish.
            deadline = time.monotonic() + 15
            while True:
                try:
                    operation["draft"] = saved();break
                except StudioPublishError:
                    if time.monotonic() >= deadline:raise
                    page.wait_for_timeout(250)
            self._identity(page, policy)
            operation["project_id"] = operation["draft"]["project_id"]
            operation["state"] = "prepared"
            self._save(operation)
            return operation
        except Exception:
            operation["state"] = "preparation_failed"
            if getattr(self, '_caption_semantic_rollback_unverified', False):
                operation['caption_repair'] = {'state': 'failed', 'semantic_rollback_verified': False}
            self._save(operation)
            raise

    def _recover_private_preparation(self, operation):
        """Recover only this request's private draft before any public dispatch."""
        page = self._page()
        page.wait_for_timeout(1500)
        policy = operation["policy"]
        self._identity(page, policy)
        rows = self._drafts(page, policy)
        if not operation.get("draft_id"):
            if "drafts_before" not in operation:
                # Failure occurred before file selection was allowed.
                return
            delta = [r for r in rows if r["draft_id"] not in operation["drafts_before"]]
            matches = [r for r in delta if r["file_name"] == operation["staged_name"] and r["file_size"] == operation["asset_bytes"]]
            if not matches:
                if delta:
                    raise StudioPublishError("Private recovery found unowned new drafts; no draft removed.")
                return
            if len(matches) != 1:
                raise StudioPublishError("Private recovery cannot identify one exact owned draft.")
            operation["draft_id"] = matches[0]["draft_id"]
            operation["draft"] = matches[0]
            self._save(operation)
        matches = [r for r in rows if r["draft_id"] == operation["draft_id"]]
        if not matches:
            return
        expected = operation["draft"]
        if len(matches) != 1 or any(matches[0].get(k) != expected.get(k) for k in MEDIA_BINDING_FIELDS):
            raise StudioPublishError("Private recovery media binding changed; no draft removed.")
        if (matches[0].get("is_locked") is True or matches[0].get("is_temp") is True) and page.locator(CAPTION_SELECTOR).count() == 0 and page.locator('[data-e2e="local_draft_container"]').count() == 0:
            return self._delete_owned_orphan(page, operation)
        if len(rows) != 1 or page.locator('[data-e2e="local_draft_container"]').count() != 1:
            raise StudioPublishError("Private recovery cannot uniquely identify the native draft banner; preserve all drafts.")
        page.get_by_role("button", name="Discard", exact=True).click()
        page.wait_for_timeout(250)
        dialog = page.get_by_role("dialog")
        if dialog.count() != 1 or "Discard" not in dialog.inner_text():
            raise StudioPublishError("Native private-draft discard confirmation was not verified.")
        dialog.get_by_role("button", name="Discard", exact=True).click()
        self._wait(page, lambda: not any(r["draft_id"] == operation["draft_id"] for r in self._drafts(page, policy)), "Owned private draft did not disappear after native discard.", seconds=10)
        self.page = self.browser.get_page(UPLOAD_URL)
        page = self.page
        page.wait_for_timeout(1000)
        if any(r["draft_id"] == operation["draft_id"] for r in self._drafts(page, policy)):
            raise StudioPublishError("Owned private draft reappeared after discard; reprepare refused.")

    def _delete_owned_orphan(self, page, operation):
        """Delete one exact journal-owned private orphan, retaining recovery audit."""
        if operation["state"] not in {"preparing", "preparation_failed", "prepared"} or operation.get("public_action_dispatched") is not False:
            raise StudioPublishError("Orphan recovery is forbidden after any public-action boundary.")
        self._verify_asset(operation)
        policy = validate_policy(operation["policy"])
        if operation["binding"] != digest({"asset_sha256": operation["asset_sha256"], "policy": policy}):
            raise StudioPublishError("Orphan recovery journal binding changed.")
        self._identity(page, policy)
        if page.locator(CAPTION_SELECTOR).count():
            raise StudioPublishError("Orphan recovery refused an active editor.")
        fields = ORPHAN_BINDING_FIELDS
        expected = {key: operation["draft"][key] for key in fields}
        if expected["draft_id"] != operation["draft_id"] or expected["file_name"] != operation["staged_name"] or expected["file_size"] != operation["asset_bytes"]:
            raise StudioPublishError("Orphan recovery media identity does not match the journal.")
        audit = {"draft_id": operation["draft_id"], "binding": expected,
                 "asset_sha256": operation["asset_sha256"], "state": "delete_pending",
                 "requested_at": datetime.now(timezone.utc).isoformat()}
        operation.setdefault("orphan_recovery", []).append(audit)
        operation["state"] = "preparation_failed"
        self._save(operation)
        result = page.evaluate(DELETE_ORPHAN_JS, {"owner": policy["account_id"], "expected": expected})
        if result != {"deleted": True, "draft_id": operation["draft_id"]}:
            raise StudioPublishError("Exact orphan transaction did not confirm removal.")
        if any(row["draft_id"] == operation["draft_id"] for row in self._drafts(page, policy)):
            raise StudioPublishError("Exact orphan still exists after private recovery.")
        audit.update(state="deleted", removed_at=datetime.now(timezone.utc).isoformat())
        self._save(operation)

    def _verify_asset(self, operation):
        path = self.root / "media" / operation["staged_name"]
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError:
            raise StudioPublishError("Studio owned staged asset is missing or is not a regular owned file.") from None
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size != operation["asset_bytes"]:
            os.close(descriptor)
            raise StudioPublishError("Studio staged asset is not a regular file with the bound size.")
        with os.fdopen(descriptor, "rb") as stream:
            measured = hashlib.file_digest(stream, "sha256").hexdigest()
            after = os.fstat(stream.fileno())
            try:
                current = path.stat(follow_symlinks=False)
            except OSError:
                raise StudioPublishError("Studio staged asset changed during verification.") from None
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if measured != operation["asset_sha256"] or any(getattr(before, field) != getattr(after, field) or getattr(after, field) != getattr(current, field) for field in fields) or not stat.S_ISREG(current.st_mode):
            raise StudioPublishError("Studio staged asset bytes or file identity changed after preparation.")

    def publish(self, request_id: str, *, before_public_action: Callable[[dict], None]) -> dict:
        if not callable(before_public_action):
            raise StudioPublishError("Studio public action requires a trusted before_public_action callback.")
        with self._locked():
            operation = self.status(request_id)
            if operation["state"] != "prepared" or operation.get("public_action_dispatched") is not False:
                raise StudioPublishError("Studio request is not prepared; automatic Post retry is prohibited.")
            self._verify_asset(operation)
            policy = validate_policy(operation["policy"])
            if digest(policy) != operation["policy_digest"] or digest({"asset_sha256": operation["asset_sha256"], "policy": policy}) != operation["binding"]:
                raise StudioPublishError("Studio policy binding changed.")
            page = self._page()
            page.wait_for_timeout(1500)
            self._identity(page, policy)
            rows = self._drafts(page, policy)
            if not any(row["draft_id"] == operation["draft_id"] for row in rows):
                if rows:
                    raise StudioPublishError("Owned draft is missing while unknown drafts exist; preserve all drafts.")
                # Native normal-exit cleanup can remove a private temporary row.
                if page.evaluate(HEARTBEAT_JS, policy["account_id"]) is not True:
                    raise StudioPublishError("Missing private draft recovery has an unresolved heartbeat context.")
                operation.setdefault("orphan_recovery", []).append({"draft_id": operation["draft_id"], "state": "missing_private_draft_rebuild", "requested_at": datetime.now(timezone.utc).isoformat()})
                operation["state"] = "preparation_failed"
                self._save(operation)
                operation = self._prepare(self.root / "media" / operation["staged_name"], policy, request_id)
                page = self._page()
                rows = self._drafts(page, policy)
            current = self._match_draft(operation, rows)
            if len(rows) != 1:
                raise StudioPublishError("Studio editor does not uniquely identify the owned draft; preserve other drafts.")
            # The native Continue banner offers one local draft. Never click
            # it when another candidate could be resumed instead.
            if page.locator(CAPTION_SELECTOR).count() != 1:
                if len(rows) == 1 and page.locator('[data-e2e="local_draft_container"]').count() == 1:
                    page.get_by_role("button", name="Continue", exact=True).click()
                    self._wait(page, lambda: page.locator(CAPTION_SELECTOR).count() == 1, "Studio exact draft did not reopen.")
                elif current.get("is_locked") is True or current.get("is_temp") is True:
                    self._delete_owned_orphan(page, operation)
                    operation["state"] = "preparation_failed"
                    self._save(operation)
                    operation = self._prepare(self.root / "media" / operation["staged_name"], policy, request_id)
                    page = self._page()
                else:
                    raise StudioPublishError("Studio Continue does not uniquely identify the owned draft.")
            if page.locator('.more-btn > span:first-child:has-text("Show more")').count() == 1:
                page.locator('.more-btn > span:first-child:has-text("Show more")').click()
            self._wait(page, lambda: page.evaluate(CONTROLS_JS).get("upload_complete") and page.evaluate(CONTROLS_JS).get("post_enabled"), "Studio reopened upload readiness did not complete.")
            current = self._match_draft(operation, self._drafts(page, policy))
            try:
                self._set_caption(page, policy, current)
            except Exception:
                operation['state'] = 'preparation_failed'
                operation['caption_repair'] = {'state': 'failed', 'semantic_rollback_verified': False}
                self._save(operation)
                raise
            self._verify_controls(page, policy)
            draft = self._wait(page, lambda: self._saved_caption_draft(operation, page, policy), 'Studio saved native entities did not persist.', seconds=10)
            # TikTok creates a fresh project on resume. Its new observed exact
            # project ID is recorded before dispatch, retaining creation/media.
            operation["project_id"] = draft["project_id"]
            operation['draft'] = draft
            self._identity(page, policy)
            key = "__studio_publish_" + request_id.replace("-", "")
            page.evaluate(OBSERVER_JS, {"key": key, "path": POST_PATH,
                                         "video_id": draft["video_id"], "creation_id": draft["creation_id"],
                                         'caption': policy['caption'], 'caption_text_extra': caption_entities(draft, policy['caption'])})
            operation["state"] = "dispatch_pending"
            self._save(operation)
            try:
                # No browser read or file permit between trusted gate and Post.
                before_public_action({k: operation[k] for k in ("request_id", "asset_sha256", "policy_digest", "actor", "draft_id", "project_id")})
            except Exception:
                operation["state"] = "prepared"
                self._save(operation)
                page.evaluate(RESTORE_JS, key)
                raise StudioPublishError("Trusted public-action callback rejected Studio Post; no Post dispatched.") from None
            try:
                page.locator(POST_SELECTOR).click()
                operation["public_action_dispatched"] = True
                operation["state"] = "outcome_unknown"
                self._save(operation)
                deadline = time.monotonic() + 30
                observed = None
                while time.monotonic() < deadline:
                    observed = page.evaluate(RECEIPT_JS, key)
                    if observed and observed.get("receipt"):break
                    page.wait_for_timeout(250)
                payload = accepted_project(observed, operation)
                operation["post_project_id"] = payload["project_id"]
                operation["state"] = "project_accepted"
                # Persist native acceptance before interpreting any optional
                # task receipt or making the first read-only status request.
                self._save(operation)
                item = receipt_item_id(payload)
                if item is not None:
                    operation["item_id"] = item
                    operation["state"] = "receipt_observed"
                    self._save(operation)
            except Exception:
                operation["state"] = "outcome_unknown"
                self._save(operation)
                raise StudioPublishError("Studio Post outcome is unknown; reconcile only, never retry.", category="ambiguous_post_action") from None
            finally:
                page.evaluate(RESTORE_JS, key)
            return self._reconcile(operation)

    def _reconcile(self, operation):
        if not operation.get("item_id"):
            project = operation.get("post_project_id")
            if project is None:
                return {**operation, "reconciliation": "inconclusive_no_exact_receipt_id"}
            if not positive_decimal_id(project):
                raise StudioPublishError("Journaled Studio post project ID is invalid; reconcile only.", category="ambiguous_post_action")
            page = self._page()
            self._identity(page, operation["policy"])
            payload = self.client._fetch_json(page, PROJECT_STATUS_PATH + "?project_id=" + project)
            if not isinstance(payload, dict):
                raise StudioPublishError("Exact Studio project response is malformed; reconcile only.", category="ambiguous_post_action")
            if "project_id" in payload and payload["project_id"] != project:
                raise StudioPublishError("Studio status returned another project; reconcile only.", category="ambiguous_post_action")
            state, item = project_status(payload)
            operation["state"] = state
            operation["project_status_observed_at"] = datetime.now(timezone.utc).isoformat()
            if item is not None:
                operation["item_id"] = item
            self._save(operation)
            if item is None:
                return {**operation, "reconciliation": state}
        policy = operation["policy"]
        # This read is the existing verified Studio path, not the public feed.
        if self.browser is None:
            self.browser = self.config.get_browser()
        self.client._browser = self.browser
        record = self.client.get_studio_video(policy["username"], operation["item_id"], policy["account_id"])
        if record["caption"] != policy["caption"] or record["account_id"] != policy["account_id"] or record["visibility"] != 1:
            raise StudioPublishError("Exact Studio receipt post does not match the account, caption, and Everyone audience.", category="ambiguous_post_action")
        operation["state"] = "published_verified"
        operation["url"] = record["url"]
        operation["verification"] = record
        self._save(operation)
        self._prune_verified_media(operation)
        return operation

    def _prune_verified_media(self, operation):
        """Delete only this verified operation's exact hash-matched staged file."""
        path = self.root / "media" / operation["staged_name"]
        if path.is_symlink():
            raise StudioPublishError("Post verified; owned media cleanup refused a symlink.", category="local_cleanup_failed")
        if path.exists():
            try:
                self._verify_asset(operation)
            except StudioPublishError:
                raise StudioPublishError("Post verified; staged media hash mismatch prevented cleanup.", category="local_cleanup_failed") from None
            path.unlink()
        operation["media_cleanup_state"] = "removed"
        self._save(operation)

    def reconcile(self, request_id: str) -> dict:
        """Read only remote Studio state; never reconstruct IDs from captions."""
        with self._locked():
            return self._reconcile(self.status(request_id))

    def close(self):
        if self.owns_browser and self.browser is not None:
            self.browser.close()
        self.browser = None
        self.page = None
        self.client._browser = None
