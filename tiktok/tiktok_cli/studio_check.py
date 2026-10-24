"""Read TikTok Studio's own pre-post checks for one local video, then remove the draft.

Studio starts both checks itself once a file finishes uploading (observed on
@ata_clipper, 2026-10-06, with the account's automatic checks on):

  POST /tiktok/v1/creator/content/check/create  {"video_id": <vid>, "tasks": [0]}
  GET  /tiktok/v1/creator/content/check/?video_id=<vid>&queries=[{"task":0,"check_id":<id>}]
  GET  /tiktok/copyright/music/check/v1/?video_id=<vid>

Studio polls the content check every 10 seconds for up to 15 minutes and keeps
the answer in its page state, which is what this module reads. It never starts
a check, flips a switch, or clicks Post. The enums are copied from Studio's
bundle. Only the pass, checking, and failed-music shapes were captured live;
the restricted shape follows the bundle and is not yet observed.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import shutil
import time
from pathlib import Path
from uuid import uuid4

from .studio_publishing import (CAPTION_SELECTOR, DELETE_BOUND_DRAFT_JS, FILE_SELECTOR, HEARTBEAT_JS,
                                MAX_ASSET_BYTES, MEDIA_BINDING_FIELDS, ORPHAN_BINDING_FIELDS,
                                StudioPublishError, digest)

CHECK_CREATE_PATH = "/tiktok/v1/creator/content/check/create"
CHECK_RESULT_PATH = "/tiktok/v1/creator/content/check/"
MUSIC_CHECK_PATH = "/tiktok/copyright/music/check/v1/"
DISCARD_SELECTOR = '[data-e2e="discard_post_button"]'
CHECK_STATUSES = {0: "init", 1: "checking", 2: "success", 3: "fail"}  # CONTENT_CHECK_STATUS_*
MODEL_RESULTS = {0: "pass", 1: "restricted"}  # MODEL_CHECK_RESULT_TYPE_PASS / _NR
MODEL_TYPES = {0: "unoriginal"}  # MODEL_TYPE_UNORIGINAL, the only type Studio defines
# The one reason Studio's "Content may be restricted" details panel shows for that type.
ISSUE_TEXT = {0: "Unoriginal, low-quality, and QR code content"}
MUSIC_RESULTS = {1: "no_issue", 2: "copyright_violated"}  # OK / COPYRIGHT_VIOLATED
MUSIC_DONE = "SWITCH_ON_CHECKING_DONE"
# Studio renders every content-check message at once and shows exactly one.
UI_CLASSES = ["status-ready", "status-checking", "status-error", "status-warn", "status-success",
              "status-ready", "status-ready"]
UI_STATES = ["ready", "checking", "error", "restricted", "pass", "limit_reached", "unavailable"]

# Read-only: Studio's own store plus the visible message under each check.
CHECK_STATE_JS = r"""() => {
 const anchor=document.querySelector('[data-e2e="caption_container"] [contenteditable="true"]');
 if(!anchor)throw Error('STUDIO_CONTEXT_MISSING');
 const key=Object.keys(anchor).find(k=>k.startsWith('__reactFiber$'));
 if(!key)throw Error('STUDIO_CONTEXT_MISSING');
 const stores=new Set();let fiber=anchor[key];
 for(let i=0;fiber&&i<160;i++,fiber=fiber.return){const p=fiber.memoizedProps;
  for(const store of [p?.store,p?.value?.store])if(store&&typeof store.getState==='function')stores.add(store);
 }
 if(stores.size!==1)throw Error('STUDIO_CONTEXT_AMBIGUOUS');
 const state=[...stores][0].getState(),form=state.form?.videoFormDataMap?.[state.uploader?.currentFileKey];
 if(!form)throw Error('STUDIO_CONTEXT_CHANGED');
 const rows=root=>root?[...root.querySelectorAll(':scope > .status-wrapper > .status-result')]:[];
 const heads=[...document.querySelectorAll('.headline-wrapper .headline')].filter(e=>e.textContent==='Content check lite');
 const lite=rows(heads.length===1?heads[0].closest('.headline-wrapper').parentElement:null);
 const music=rows(document.querySelector('[data-e2e="copyright_container"]')?.parentElement);
 return {lite:form.liteContentCheckResultInfo??null,lite_switch:form.isContentCheckLiteSwitchOn??null,
  music:form.copyrightCheckingResult??null,music_status:form.copyrightCheckStatus??null,
  music_switch:form.isCopyrightSwitchOn??null,
  lite_ui:lite.map(e=>({state:[...e.classList].find(x=>x.startsWith('status-')&&x!=='status-result')??null,
   shown:e.getAttribute('data-show')==='true',text:e.innerText})),
  music_ui:music.map(e=>e.innerText)};
}"""

# Runs only after Studio's own Discard closed this editor. Any other live
# editor's heartbeat refuses the removal.
DELETE_CHECK_DRAFT_JS = r"""async (opts) => {
 const names=JSON.parse(localStorage.getItem('web_creation_heartbeats_'+opts.owner)||'[]');
 if(!Array.isArray(names))throw Error('HEARTBEAT_SCHEMA_CHANGED');
 for(const name of names){
  if(name==='web_creation_heartbeat_'+opts.expected.creation_id)continue;
  const value=JSON.parse(localStorage.getItem(name)??'null');
  if(typeof value==='number'&&Date.now()-value<1000)throw Error('ACTIVE_STUDIO_HEARTBEAT');
 }""" + DELETE_BOUND_DRAFT_JS


def _lite_ui(rows):
    """Name the one visible content-check message, or nothing if the layout changed."""
    if not isinstance(rows, list) or [r.get("state") if isinstance(r, dict) else None for r in rows] != UI_CLASSES:
        return None, None
    shown = [i for i, row in enumerate(rows) if row.get("shown") is True]
    if len(shown) != 1:
        return None, None
    text = rows[shown[0]].get("text")
    return UI_STATES[shown[0]], text if isinstance(text, str) else None


def _not_offered(state: dict) -> bool:
    """Studio rendered no content-check block and never set its switch."""
    return state.get("lite_switch") is None and state.get("lite_ui") == []


def lite_finished(state: dict) -> bool:
    lite = state.get("lite") if isinstance(state.get("lite"), dict) else {}
    return (state.get("lite_switch") is False or lite.get("checkStatus") in (2, 3)
            or _lite_ui(state.get("lite_ui"))[0] in ("error", "limit_reached", "unavailable"))


def music_finished(state: dict) -> bool:
    # Studio drops back to DEFAULT when the music check is off or its request failed.
    return state.get("music_status") in (MUSIC_DONE, "DEFAULT")


def normalize_check(state: dict) -> dict:
    """Whitelist one observed Studio check state. Unreadable values stay null."""
    lite = state.get("lite") if isinstance(state.get("lite"), dict) else {}
    code = lite.get("checkStatus") if type(lite.get("checkStatus")) is int else None
    ui_state, ui_text = _lite_ui(state.get("lite_ui"))
    if state.get("lite_switch") is False:
        status = "switch_off"
    elif _not_offered(state):
        status = "not_offered"
    elif code == 2:
        status = "completed"
    elif code == 3 or ui_state == "error":
        status = "check_failed"
    elif ui_state in ("limit_reached", "unavailable"):
        status = ui_state
    else:
        status = "not_finished"
    results = [r for r in lite.get("checkResult") or [] if isinstance(r, dict)] if isinstance(lite.get("checkResult"), list) else []
    verdict, issues = None, []
    if status == "completed":
        # Studio's own verdict is the unoriginal model's result alone.
        current = [r for r in results if type(r.get("model_type")) is int and r["model_type"] == 0]
        if len(current) == 1 and type(current[0].get("model_check_result")) is int:
            verdict = MODEL_RESULTS.get(current[0]["model_check_result"])
        for result in results:
            kind, outcome = result.get("model_type"), result.get("model_check_result")
            if type(kind) is not int or type(outcome) is not int or outcome == 0:
                continue
            segments = result.get("segments") if isinstance(result.get("segments"), list) else []
            issues.append({"code": kind, "type": MODEL_TYPES.get(kind), "result_code": outcome,
                           "text": ISSUE_TEXT.get(kind),
                           "segments": [{"start_ms": s.get("query_start_time"), "end_ms": s.get("query_end_time")}
                                        for s in segments if isinstance(s, dict)]})
    music = state.get("music") if isinstance(state.get("music"), dict) else {}
    music_done = state.get("music_status") == MUSIC_DONE
    music_code = music.get("code") if music_done and type(music.get("code")) is int else None
    music_ui = state.get("music_ui")
    return {
        "status": status, "verdict": verdict, "issues": issues,
        "content_check": {"check_id": lite.get("checkId") if isinstance(lite.get("checkId"), str) else None,
                          "video_id": lite.get("videoId") if isinstance(lite.get("videoId"), str) else None,
                          "check_status": code, "check_status_name": CHECK_STATUSES.get(code),
                          "switch_on": state.get("lite_switch") if isinstance(state.get("lite_switch"), bool) else None,
                          "results": results, "ui_state": ui_state, "ui_text": ui_text},
        "music_copyright": {"status": state.get("music_status") if isinstance(state.get("music_status"), str) else None,
                            "verdict": MUSIC_RESULTS.get(music_code), "code": music_code,
                            "reason": music.get("reason") if music_done else None,
                            "materials": music.get("copyrightedMaterials") if music_done else None,
                            "pre_check_id": music.get("copyrightPreCheckId") if music_done else None,
                            "switch_on": state.get("music_switch") if isinstance(state.get("music_switch"), bool) else None,
                            "ui_text": music_ui[0] if isinstance(music_ui, list) and len(music_ui) == 1 and isinstance(music_ui[0], str) else None},
    }


def _remove_draft(publisher, page, policy, row, before):
    """Close this run's own editor with Studio's Discard, then drop its exact temporary row."""
    if page.locator(CAPTION_SELECTOR).count():
        button = page.locator(DISCARD_SELECTOR)
        if button.count() != 1:
            raise StudioPublishError("Studio editor Discard control is unavailable or ambiguous.")
        button.click()
        page.wait_for_timeout(600)
        dialog = page.get_by_role("dialog")
        if dialog.count() != 1 or not dialog.inner_text().startswith("Discard this post?"):
            raise StudioPublishError("Studio editor discard confirmation was not verified.")
        dialog.get_by_role("button", name="Discard", exact=True).click()
        publisher._wait(page, lambda: page.locator(CAPTION_SELECTOR).count() == 0,
                        "Studio editor did not close after Discard.", seconds=10)
    current = [r for r in publisher._drafts(page, policy) if r["draft_id"] == row["draft_id"]]
    if current:
        if len(current) != 1 or any(current[0].get(k) != row.get(k) for k in MEDIA_BINDING_FIELDS):
            raise StudioPublishError("Check draft media binding changed; no draft removed.")
        try:
            result = page.evaluate(DELETE_CHECK_DRAFT_JS, {"owner": policy["account_id"],
                                   "expected": {k: current[0][k] for k in ORPHAN_BINDING_FIELDS}})
        except Exception as error:
            # Studio's Discard sometimes drops the row itself a moment later; only a surviving row is a failure.
            left = [r for r in publisher._drafts(page, policy) if r["draft_id"] == row["draft_id"]]
            if left:
                raise StudioPublishError(f"Check draft removal was refused (temporary={left[0].get('is_temp')}, "
                                         f"locked={left[0].get('is_locked')}): {error}") from None
            result = {"deleted": True, "draft_id": row["draft_id"]}
        if result != {"deleted": True, "draft_id": row["draft_id"]}:
            raise StudioPublishError("Check draft removal was not confirmed.")
    rows = publisher._drafts(page, policy)
    if any(r["draft_id"] == row["draft_id"] for r in rows):
        raise StudioPublishError("Check draft still exists after removal.")
    if {r["draft_id"]: digest(r) for r in rows} != {r["draft_id"]: digest(r) for r in before}:
        raise StudioPublishError("A draft this check did not create changed during the check.")


def check(publisher, file, *, username: str, account_id: str, timeout: int = 900) -> dict:
    """Upload one MP4 as a private draft, read Studio's check verdicts, and remove that draft."""
    with publisher._locked():
        return _check(publisher, Path(file), username, account_id, timeout)


def _check(publisher, source, username, account_id, timeout):
    if not source.is_file() or source.suffix.lower() != ".mp4":
        raise StudioPublishError("Studio check requires an existing MP4 file.")
    if not 0 < source.stat().st_size <= MAX_ASSET_BYTES:
        raise StudioPublishError("Studio asset must contain 1 byte to 30 GB.")
    if type(timeout) is not int or not 30 <= timeout <= 900:
        raise StudioPublishError("Studio check timeout must be 30 to 900 seconds.")
    policy = {"profile": publisher.config.get_active_profile_name(), "account_id": account_id, "username": username}
    request_id = str(uuid4())
    workspace = publisher.root / "media"
    workspace.mkdir(mode=0o700, exist_ok=True)
    # Studio shows the file name as the default caption; the UUID keeps the source name private.
    staged = workspace / (request_id + ".mp4")
    shutil.copyfile(source, staged)
    staged.chmod(0o600)
    with staged.open("rb") as stream:
        sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    operation = {"request_id": request_id, "binding": digest({"content_check": request_id}),
                 "kind": "content_check", "state": "checking", "public_action_dispatched": False,
                 "source": str(source), "asset_sha256": sha256, "asset_bytes": staged.stat().st_size,
                 "staged_name": staged.name, "draft_removed": None}
    publisher._save(operation)
    page = row = before = None
    try:
        page = publisher._page()
        page.wait_for_timeout(1500)
        operation["actor"] = publisher._identity(page, policy)
        before = publisher._drafts(page, policy)
        fresh = publisher._fresh_entry(page, before)
        if page.evaluate(HEARTBEAT_JS, account_id) is not True:
            raise StudioPublishError("Studio check has an unresolved heartbeat context.")
        if page.locator(FILE_SELECTOR).count() != 1:
            raise StudioPublishError("Studio single-file upload control is unavailable or ambiguous.")
        started = time.monotonic()
        page.set_input_files(FILE_SELECTOR, str(staged))
        publisher._wait(page, lambda: page.evaluate("()=>document.body.innerText.includes('Uploaded')"),
                        "Studio upload did not complete.")
        uploaded = time.monotonic()
        known = {r["draft_id"] for r in before}
        rows = publisher._wait(page, lambda: [r for r in publisher._drafts(page, policy)
                               if r["draft_id"] not in known and r["stage"] == "complete" and r["percent"] == 100
                               and isinstance(r["video_id"], str) and r["video_id"]
                               and r["file_name"] == staged.name and r["file_size"] == operation["asset_bytes"]],
                               "Studio upload did not yield an exact local draft.")
        if len(rows) != 1 or rows[0]["creation_id"] != fresh:
            raise StudioPublishError("Studio upload produced an ambiguous or unrelated draft.")
        row = rows[0]
        operation.update(draft_id=row["draft_id"], draft={k: row[k] for k in ORPHAN_BINDING_FIELDS}, draft_removed=False)
        publisher._save(operation)
        deadline, lite_at, music_at = started + timeout, None, None
        while True:
            state = page.evaluate(CHECK_STATE_JS)
            now = time.monotonic()
            # The block renders just after the editor; absence only counts once it has had time.
            if lite_at is None and (lite_finished(state) or _not_offered(state) and now - uploaded >= 10):
                lite_at = now
            if music_at is None and music_finished(state):
                music_at = now
            if (lite_at and music_at) or now >= deadline:
                break
            page.wait_for_timeout(1000)
        result = normalize_check(state)
        if result["content_check"]["video_id"] not in (None, row["video_id"]):
            raise StudioPublishError("Studio check result names a different video.")
        seconds = lambda mark: None if mark is None else round(mark - started, 1)
        result = {"request_id": request_id, "file": str(source), "asset_sha256": sha256,
                  "asset_bytes": operation["asset_bytes"], "account": operation["actor"], **result,
                  "timings": {"upload_seconds": seconds(uploaded), "content_check_seconds": seconds(lite_at),
                              "music_check_seconds": seconds(music_at), "total_seconds": seconds(time.monotonic())},
                  "provenance": {"source": "studio_page_state", "page": page.evaluate("()=>location.origin+location.pathname"),
                                 "content_check_endpoints": [CHECK_CREATE_PATH, CHECK_RESULT_PATH],
                                 "music_check_endpoint": MUSIC_CHECK_PATH,
                                 "observed_at": datetime.now(timezone.utc).isoformat()},
                  "draft": {"draft_id": row["draft_id"], "video_id": row["video_id"], "posted": False}}
        operation.update(state="checked", result=result)
        publisher._save(operation)
    except BaseException:
        operation["state"] = "failed"
        publisher._save(operation)
        raise
    finally:
        staged.unlink(missing_ok=True)
        if row is None and before is not None:
            # A failure after file selection may already have left this run's draft.
            known = {r["draft_id"] for r in before}
            late = [r for r in publisher._drafts(page, policy) if r["draft_id"] not in known and r["file_name"] == staged.name]
            row = late[0] if len(late) == 1 else None
        if row is not None:
            _remove_draft(publisher, page, policy, row, before)
            operation["draft_removed"] = True
            publisher._save(operation)
    result["draft"]["removed"] = True
    return result
