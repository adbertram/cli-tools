"""Studio pre-post check decoding against state captured from @ata_clipper on 2026-10-06.

Captured live: the checking and pass states, the finished and failed music
checks, and every content-check message Studio renders. The restricted and
limit cases reuse those captures with only the code Studio's bundle defines.
"""
import json
import subprocess
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from tiktok_cli import studio_check as module
from tiktok_cli import studio_publishing as publishing
from tiktok_cli.commands import studio as studio_cmd
from tiktok_cli.studio_publishing import StudioPublisher, StudioPublishError

ACCOUNT = "7692213003349443597"
ACTOR = {"account_id": ACCOUNT, "username": "ata_clipper", "profile": "clipper"}
VIDEO = "v12025gd0000db2ngn7og65ocra8appg"
CHECK = "7693686902674833422"
# Verbatim GET /tiktok/v1/creator/content/check/ responses for that video, 11 and 21 seconds after upload.
POLL_CHECKING = '{"check_result":{"7693686902674833422":{}},"check_status":{"7693686902674833422":1},"extra":{"fatal_item_ids":[],"logid":"202610062238321979C785BDECE8283E9C","now":1791326312000},"log_pb":{"impr_id":"202610062238321979C785BDECE8283E9C"},"status_code":0,"status_msg":""}'
POLL_PASS = '{"check_result":{"7693686902674833422":{"model_check_results":[{"model_check_result":0,"model_type":0}]}},"check_status":{"7693686902674833422":2},"extra":{"fatal_item_ids":[],"logid":"2026100622384259C96DDE4F81F2F84D5E","now":1791326322000},"log_pb":{"impr_id":"2026100622384259C96DDE4F81F2F84D5E"},"status_code":0,"status_msg":""}'
# Verbatim Studio page state (form.videoFormDataMap[...].liteContentCheckResultInfo) at the same moments.
LITE_CHECKING = {"taskId": 0, "checkStatus": 1, "videoId": VIDEO, "checkId": CHECK}
LITE_PASS = {"taskId": 0, "checkStatus": 2, "videoId": VIDEO, "checkId": CHECK,
             "checkResult": [{"model_check_result": 0, "model_type": 0}]}
MUSIC_OK = {"code": 1, "copyrightPreCheckId": "US-TTP_6_7693684191309957134"}
# Every message in Studio's rendered "Content check lite" block, in document order.
UI_TEXT = [
    "We'll check your content for For You Feed eligibility.",
    "Checking in progress. This will take about 10 minutes. Longer videos may take more time.",
    "Something went wrong. Try again later. Retry",
    "Content may be restricted. You can still post, but modifying it to follow our guidelines may improve visibility. View details",
    "No issues found. However, your video could still be removed later if it violates our Community Guidelines.",
    "You’ve reached your check limit for today. Try again tomorrow.",
    "This feature isn't available for government, politician or political party accounts.",
]


def ui(shown):
    return [{"state": cls, "shown": index == shown, "text": UI_TEXT[index]} for index, cls in enumerate(module.UI_CLASSES)]


def state(lite=LITE_PASS, shown=4, **changes):
    return {"lite": lite, "lite_switch": True, "music": MUSIC_OK, "music_status": "SWITCH_ON_CHECKING_DONE",
            "music_switch": True, "lite_ui": ui(shown), "music_ui": ["No issues found."], **changes}


def test_studio_stores_exactly_the_polled_model_results():
    assert json.loads(POLL_PASS)["check_result"][CHECK]["model_check_results"] == LITE_PASS["checkResult"]
    assert json.loads(POLL_PASS)["check_status"][CHECK] == LITE_PASS["checkStatus"] == 2
    assert json.loads(POLL_CHECKING)["check_status"][CHECK] == LITE_CHECKING["checkStatus"] == 1


def test_captured_pass_is_a_pass_with_no_issues():
    result = module.normalize_check(state())
    assert result["status"] == "completed" and result["verdict"] == "pass" and result["issues"] == []
    assert result["content_check"] == {
        "check_id": CHECK, "video_id": VIDEO, "check_status": 2, "check_status_name": "success", "switch_on": True,
        "results": [{"model_check_result": 0, "model_type": 0}], "ui_state": "pass", "ui_text": UI_TEXT[4]}
    assert result["music_copyright"] == {
        "status": "SWITCH_ON_CHECKING_DONE", "verdict": "no_issue", "code": 1, "reason": None, "materials": None,
        "pre_check_id": "US-TTP_6_7693684191309957134", "switch_on": True, "ui_text": "No issues found."}


def test_captured_checking_state_has_no_verdict_and_is_not_finished():
    observed = state(LITE_CHECKING, 1, music=None, music_status="SWITCH_ON_CHECKING",
                     music_ui=["Checking in progress. This will take about 30 seconds."])
    result = module.normalize_check(observed)
    assert not module.lite_finished(observed) and not module.music_finished(observed)
    assert result["status"] == "not_finished" and result["verdict"] is None and result["issues"] == []
    assert result["content_check"]["check_status_name"] == "checking" and result["content_check"]["ui_state"] == "checking"
    assert result["music_copyright"]["verdict"] is None and result["music_copyright"]["code"] is None


def test_captured_failed_music_check_stays_unknown():
    # Studio's music request answered status_code 4; it reset the check to DEFAULT and switched it off.
    observed = state(music=None, music_status="DEFAULT", music_switch=False,
                     music_ui=["We'll check if your video has any unauthorized music that may cause it to be muted."])
    result = module.normalize_check(observed)
    assert module.music_finished(observed) and result["verdict"] == "pass"
    assert result["music_copyright"]["verdict"] is None and result["music_copyright"]["switch_on"] is False


def test_restricted_result_names_studios_reason_and_segments():
    lite = {**LITE_PASS, "checkResult": [{"model_check_result": 1, "model_type": 0,
                                           "segments": [{"query_start_time": 1000, "query_end_time": 4000}]}]}
    result = module.normalize_check(state(lite, 3))
    assert result["status"] == "completed" and result["verdict"] == "restricted"
    assert result["issues"] == [{"code": 0, "type": "unoriginal", "result_code": 1,
                                 "text": "Unoriginal, low-quality, and QR code content",
                                 "segments": [{"start_ms": 1000, "end_ms": 4000}]}]
    assert result["content_check"]["ui_state"] == "restricted" and result["content_check"]["ui_text"] == UI_TEXT[3]


def test_undecoded_codes_stay_null_without_inference():
    lite = {**LITE_PASS, "checkResult": [{"model_check_result": 7, "model_type": 0}, {"model_check_result": 1, "model_type": 9}]}
    result = module.normalize_check(state(lite))
    assert result["verdict"] is None
    assert result["issues"] == [
        {"code": 0, "type": "unoriginal", "result_code": 7, "text": "Unoriginal, low-quality, and QR code content", "segments": []},
        {"code": 9, "type": None, "result_code": 1, "text": None, "segments": []}]
    music = module.normalize_check(state(music={"code": 5}))["music_copyright"]
    assert music["code"] == 5 and music["verdict"] is None


@pytest.mark.parametrize("observed,status", [
    (state({"taskId": 0, "checkStatus": 0}, 5), "limit_reached"),
    (state({"taskId": 0, "checkStatus": 0}, 6), "unavailable"),
    (state({"taskId": 0, "checkStatus": 3, "videoId": VIDEO}, 2), "check_failed"),
    (state({"taskId": 0, "checkStatus": 0}, 0, lite_switch=False), "switch_off"),
    (state(None, 0, lite_switch=None, lite_ui=[]), "not_offered"),
])
def test_terminal_states_without_a_verdict(observed, status):
    result = module.normalize_check(observed)
    assert module.lite_finished(observed) or status == "not_offered"
    assert result["status"] == status and result["verdict"] is None and result["issues"] == []


@pytest.mark.parametrize("rows", [None, [], ui(4)[:6], [{**row, "shown": True} for row in ui(4)],
                                  [{**row, "state": "status-new"} for row in ui(4)]])
def test_changed_message_layout_is_unreadable_not_guessed(rows):
    content = module.normalize_check(state(lite_ui=rows))["content_check"]
    assert content["ui_state"] is None and content["ui_text"] is None


@pytest.mark.parametrize("observed", [{}, {"lite": "x", "music": 1, "lite_ui": "x", "music_ui": {}},
                                      state({"checkStatus": True, "checkResult": [None, 3]}, music="x")])
def test_malformed_state_never_yields_a_verdict(observed):
    result = module.normalize_check(observed)
    assert result["verdict"] is None and result["issues"] == [] and result["music_copyright"]["verdict"] is None


def test_removal_script_refuses_another_live_editor_and_a_changed_row():
    script = """
    const expected={draft_id:'OWNED',creation_id:'OWNED',project_id:'0',video_id:'VIDEO',file_key:'FILE',file_name:'UUID.mp4',file_size:42,duration_ms:1000};
    let beats=[],times={},deletes=0,changed=false,temp=true;
    global.localStorage={getItem:k=>k.startsWith('web_creation_heartbeats_')?JSON.stringify(beats):times[k]??null};
    global.indexedDB={open(){const request={};setTimeout(()=>{request.result={objectStoreNames:{contains:n=>n==='local_draft_123'},close(){},transaction(){
      const tx={abort(){setTimeout(()=>tx.onabort())},objectStore(){return {get(key){const get={};setTimeout(()=>{
        get.result={key,isLocked:false,isTemp:temp,data:{basic_info:{creation_id:'OWNED',project_id:'0',media_draft_info:{vid:changed?'FOREIGN':'VIDEO',video_duration_ms:1000,video_file_desc:JSON.stringify({fileKey:'FILE',rawFile:{name:'UUID.mp4',size:42}})}}}};
        get.onsuccess();if(!changed&&temp)setTimeout(()=>tx.oncomplete())});return get},delete(key){if(key!=='OWNED')throw Error('wrong key');deletes++}}}};return tx}};request.onsuccess()});return request}};
    const remove=DELETE;
    const refused=async(message)=>{try{await remove({owner:'123',expected});throw Error('accepted')}catch(e){if(e.message!==message)throw e}if(deletes!==0)throw Error('deleted')};
    (async()=>{
      beats=['web_creation_heartbeat_OWNED','web_creation_heartbeat_OTHER'];times[beats[0]]=times[beats[1]]=JSON.stringify(Date.now());
      await refused('ACTIVE_STUDIO_HEARTBEAT');
      beats=['web_creation_heartbeat_OWNED'];changed=true;await refused('ORPHAN_BINDING_REJECTED');
      changed=false;temp=false;await refused('ORPHAN_BINDING_REJECTED');
      temp=true;const result=await remove({owner:'123',expected});if(!result.deleted||deletes!==1)throw Error('exact delete failed');
      console.log('ONLY_OWN_TEMPORARY_ROW_DELETED');
    })().catch(e=>{console.error(e);process.exitCode=1});
    """.replace("const remove=DELETE;", "const remove=(" + module.DELETE_CHECK_DRAFT_JS + ");")
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "ONLY_OWN_TEMPORARY_ROW_DELETED"


FOREIGN = {"draft_id": "gXqwGibbFPiJydr8ekWwG", "creation_id": "gXqwGibbFPiJydr8ekWwG", "is_locked": True,
           "is_temp": False, "file_name": "2c118397-ead4-4688-8115-f8fcb588a7d7.mp4", "file_size": 2360202,
           "stage": "complete", "percent": 100, "video_id": "v12025gd0000db1eur7og65sc8mh1ug0",
           "file_key": "file_other", "project_id": "238473740294", "duration_ms": 7007}


class Page:
    """Studio upload page after a file is chosen: one new temporary draft and its own editor."""

    def __init__(self, states):
        self.rows = [dict(FOREIGN)];self.states = list(states);self.events = [];self.editor = False
        self.delete_result = None

    def wait_for_timeout(self, duration):pass

    def set_input_files(self, selector, path):
        assert selector == publishing.FILE_SELECTOR
        name = path.rsplit("/", 1)[1];size = len(open(path, "rb").read())
        self.rows.append({"draft_id": "NEW_CREATION", "creation_id": "NEW_CREATION", "is_locked": False, "is_temp": True,
                          "file_name": name, "file_size": size, "stage": "complete", "percent": 100, "video_id": VIDEO,
                          "file_key": "file_new", "project_id": "0", "duration_ms": 10000})
        self.editor = True;self.events.append("upload")

    def locator(self, selector):
        page = self
        class Locator:
            def count(self):
                assert selector in (publishing.FILE_SELECTOR, publishing.CAPTION_SELECTOR, module.DISCARD_SELECTOR), selector
                return int(page.editor) if selector == publishing.CAPTION_SELECTOR else 1
            def click(self):
                assert selector == module.DISCARD_SELECTOR, selector
                page.events.append("discard")
        return Locator()

    def get_by_role(self, role, **kwargs):
        assert role == "dialog" and not kwargs
        def button(inner, **options):
            assert inner == "button" and options == {"name": "Discard", "exact": True}
            def click():self.editor = False;self.events.append("confirm")
            return SimpleNamespace(click=click)
        return SimpleNamespace(count=lambda: 1, get_by_role=button,
                               inner_text=lambda: "Discard this post?\nThe video and all edits will be discarded.\nContinue editing\nDiscard")

    def evaluate(self, script, value=None):
        if script == publishing.DRAFTS_JS:return [dict(row) for row in self.rows]
        if script == publishing.EDITOR_STATE_JS:
            return {"project": {"projectId": "", "creationId": ""}, "track_id": "NEW_CREATION", "draft_id": None,
                    "draft_type": None, "draft_resumed_from": None, "full_screen_upload": True, "current_file_key": "",
                    "file_keys": [], "files": [], "editor_count": 0, "caption_state_count": 0,
                    "inputs": [{"disabled": False, "multiple": False}]}
        if script == publishing.HEARTBEAT_JS:return True
        if script == module.CHECK_STATE_JS:
            return self.states.pop(0) if len(self.states) > 1 else self.states[0]
        if script == module.DELETE_CHECK_DRAFT_JS:
            assert not self.editor and value["owner"] == ACCOUNT and value["expected"]["draft_id"] == "NEW_CREATION"
            assert set(value["expected"]) == set(publishing.ORPHAN_BINDING_FIELDS)
            self.events.append("delete")
            if self.delete_result == "vanished":
                self.rows = [row for row in self.rows if row["draft_id"] != "NEW_CREATION"];raise RuntimeError("ORPHAN_BINDING_REJECTED")
            if self.delete_result == "refused":raise RuntimeError("ORPHAN_BINDING_REJECTED")
            if self.delete_result is not None:return self.delete_result
            self.rows = [row for row in self.rows if row["draft_id"] != "NEW_CREATION"]
            return {"deleted": True, "draft_id": "NEW_CREATION"}
        if "Uploaded" in script:return True
        if "location.origin" in script:return "https://www.tiktok.com/tiktokstudio/upload"
        raise AssertionError(script)


@pytest.fixture
def publisher(tmp_path, monkeypatch):
    config = SimpleNamespace(get_profile_data_dir=lambda: tmp_path / "clipper", get_active_profile_name=lambda: "clipper")
    instance = StudioPublisher(config)
    monkeypatch.setattr(instance, "_identity", lambda page, policy: dict(ACTOR) if policy == ACTOR else pytest.fail("wrong actor"))
    yield instance
    instance.close()


def clip(tmp_path):
    path = tmp_path / "Private Source Name.mp4";path.write_bytes(b"known-mp4-bytes")
    return path


def test_check_returns_studios_verdict_and_removes_only_its_own_draft(publisher, tmp_path, monkeypatch):
    page = Page([state(LITE_CHECKING, 1, music=None, music_status="SWITCH_ON_CHECKING"), state()])
    monkeypatch.setattr(publisher, "_page", lambda: page)
    result = module.check(publisher, clip(tmp_path), username="ata_clipper", account_id=ACCOUNT, timeout=30)
    assert page.events == ["upload", "discard", "confirm", "delete"] and page.rows == [FOREIGN]
    assert result["status"] == "completed" and result["verdict"] == "pass" and result["account"] == ACTOR
    assert result["draft"] == {"draft_id": "NEW_CREATION", "video_id": VIDEO, "posted": False, "removed": True}
    assert result["asset_bytes"] == 15 and result["file"].endswith("Private Source Name.mp4")
    assert result["provenance"]["content_check_endpoints"] == ["/tiktok/v1/creator/content/check/create", "/tiktok/v1/creator/content/check/"]
    assert result["provenance"]["music_check_endpoint"] == "/tiktok/copyright/music/check/v1/"
    assert set(result["timings"]) == {"upload_seconds", "content_check_seconds", "music_check_seconds", "total_seconds"}
    journal = publisher.status(result["request_id"])
    assert journal["kind"] == "content_check" and journal["state"] == "checked" and journal["draft_removed"] is True
    assert journal["public_action_dispatched"] is False and list((publisher.root / "media").iterdir()) == []


def test_unfinished_check_reports_no_verdict_and_still_removes_the_draft(publisher, tmp_path, monkeypatch):
    page = Page([state(LITE_CHECKING, 1)])
    monkeypatch.setattr(publisher, "_page", lambda: page)
    clock = iter(range(0, 100000, 2))
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock))
    result = module.check(publisher, clip(tmp_path), username="ata_clipper", account_id=ACCOUNT, timeout=30)
    assert result["status"] == "not_finished" and result["verdict"] is None
    assert result["timings"]["content_check_seconds"] is None and page.rows == [FOREIGN]


def test_failed_read_still_removes_the_draft_and_journals_failure(publisher, tmp_path, monkeypatch):
    page = Page([state(lite={**LITE_PASS, "videoId": "v_other"})])
    monkeypatch.setattr(publisher, "_page", lambda: page)
    with pytest.raises(StudioPublishError, match="different video"):
        module.check(publisher, clip(tmp_path), username="ata_clipper", account_id=ACCOUNT, timeout=30)
    assert page.events == ["upload", "discard", "confirm", "delete"] and page.rows == [FOREIGN]


def test_unconfirmed_removal_or_changed_foreign_draft_is_an_error(publisher, tmp_path, monkeypatch):
    page = Page([state()]);page.delete_result = {"deleted": False}
    monkeypatch.setattr(publisher, "_page", lambda: page)
    with pytest.raises(StudioPublishError, match="not confirmed"):
        module.check(publisher, clip(tmp_path), username="ata_clipper", account_id=ACCOUNT, timeout=30)
    changed = Page([state()])
    original = changed.set_input_files
    def upload(selector, path):
        original(selector, path);changed.rows[0]["is_locked"] = False
    changed.set_input_files = upload
    monkeypatch.setattr(publisher, "_page", lambda: changed)
    with pytest.raises(StudioPublishError, match="did not create changed"):
        module.check(publisher, clip(tmp_path), username="ata_clipper", account_id=ACCOUNT, timeout=30)


@pytest.mark.parametrize("name,timeout", [("clip.mov", 60), ("clip.mp4", 29), ("clip.mp4", 901)])
def test_bad_input_fails_before_any_browser_or_journal_write(publisher, tmp_path, monkeypatch, name, timeout):
    path = tmp_path / name;path.write_bytes(b"x")
    monkeypatch.setattr(publisher, "_page", lambda: pytest.fail("must not open browser"))
    with pytest.raises(StudioPublishError):
        module.check(publisher, path, username="ata_clipper", account_id=ACCOUNT, timeout=timeout)
    assert not (publisher.root / "media").exists() or list((publisher.root / "media").iterdir()) == []


def test_cli_check_prints_the_result_and_closes_the_browser(tmp_path, monkeypatch):
    closed = []
    expected = {**module.normalize_check(state()), "timings": {"content_check_seconds": 21.4}}
    monkeypatch.setattr(studio_cmd, "get_config", lambda: None)
    monkeypatch.setattr(studio_cmd, "StudioPublisher", lambda config: SimpleNamespace(close=lambda: closed.append(True)))
    monkeypatch.setattr(module, "check", lambda publisher, file, **options: expected if options == {
        "username": "ata_clipper", "account_id": ACCOUNT, "timeout": 900} else pytest.fail(str(options)))
    path = clip(tmp_path)
    result = CliRunner().invoke(studio_cmd.app, ["check", str(path), "--username", "ata_clipper", "--account-id", ACCOUNT])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == expected and closed == [True]
    table = CliRunner().invoke(studio_cmd.app, ["check", str(path), "--username", "ata_clipper", "--account-id", ACCOUNT, "--table"])
    assert table.exit_code == 0 and "pass" in table.output and "no_issue" in table.output


def test_row_studio_already_dropped_counts_as_removed_but_a_surviving_row_fails(publisher, tmp_path, monkeypatch):
    gone = Page([state()]);gone.delete_result = "vanished"
    monkeypatch.setattr(publisher, "_page", lambda: gone)
    result = module.check(publisher, clip(tmp_path), username="ata_clipper", account_id=ACCOUNT, timeout=30)
    assert result["draft"]["removed"] is True and gone.rows == [FOREIGN]
    kept = Page([state()]);kept.delete_result = "refused"
    monkeypatch.setattr(publisher, "_page", lambda: kept)
    with pytest.raises(StudioPublishError, match="refused .temporary=True, locked=False"):
        module.check(publisher, clip(tmp_path), username="ata_clipper", account_id=ACCOUNT, timeout=30)
