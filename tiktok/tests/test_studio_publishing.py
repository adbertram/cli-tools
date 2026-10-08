"""Private preparation recovery and single public dispatch boundaries."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tiktok_cli import studio_check
from tiktok_cli import studio_publishing as module
from tiktok_cli.studio_publishing import StudioPublisher, StudioPublishError, validate_policy


def policy():
    return {"schema_version": 1, "profile": "clipper", "account_id": "7692213003349443597",
            "username": "ata_clipper", "caption": "Exact @hardscope #loveandjustice #ad",
            "audience": "Everyone", "timing": "now", "disclosure": "branded_content",
            "music_rights_confirmed": True}


@pytest.fixture
def publisher(tmp_path):
    config = SimpleNamespace(get_profile_data_dir=lambda: tmp_path / "clipper",
                             get_active_profile_name=lambda: "clipper",
                             get_browser=lambda posting=False: SimpleNamespace(posting=posting, close=lambda: None))
    instance = StudioPublisher(config)
    yield instance
    instance.close()


@pytest.mark.parametrize("key", list(policy()))
def test_policy_never_defaults_missing_required_fields(key):
    value = policy();del value[key]
    with pytest.raises(StudioPublishError):validate_policy(value)


@pytest.mark.parametrize("change", [
    {"schema_version": True}, {"profile": "default"}, {"account_id": 7692213003349443597},
    {"username": "@ata_clipper"}, {"caption": ""}, {"caption": "x" * 4001},
    {"audience": "Friends"}, {"timing": "schedule"}, {"disclosure": "your_brand"},
    {"music_rights_confirmed": False}, {"music_rights_confirmed": 1}, {"unexpected": True},
])
def test_policy_rejects_unknown_or_unsafe_values(change):
    with pytest.raises(StudioPublishError):validate_policy(policy() | change)


def draft(operation, **changes):
    caption = changes.get('caption', operation['policy']['caption'])
    raw = {'blocks': [{'text': caption, 'entityRanges': []}], 'entityMap': {}}
    for index, token in enumerate(module.caption_tokens(caption)):
        text = token.group();user = text.startswith('@')
        raw['blocks'][0]['entityRanges'].append({'key': index, 'offset': len(caption[:token.start()].encode('utf-16-le')) // 2, 'length': len(text.encode('utf-16-le')) // 2})
        raw['entityMap'][str(index)] = {'type': 'mention' if user else '#mention', 'mutability': 'IMMUTABLE', 'data': {'mention': {'name': text[1:], 'type': 'at' if user else 'hashTag', 'id': '1234567890' if user else text[1:]}}}
    return {"draft_id": "EXACT_DRAFT", "creation_id": "EXACT_DRAFT", "video_id": "v_exact",
            "file_key": "file_exact", "file_name": operation["staged_name"],
            "file_size": operation["asset_bytes"], "duration_ms": 8266,
            "project_id": "238232531206", "stage": "complete", "percent": 100,
            "caption": operation["policy"]["caption"], "privacy": {"visibility_type": 0},
            'caption_markup': json.dumps(raw), 'caption_text_extra': [],
            "commercial": {"commerce_toggle_info": {"branded_content_type": 2001}}, **changes}


def prepared(publisher, **changes):
    request = str(uuid4());asset = b"known-mp4-bytes"
    (publisher.root / "media").mkdir()
    (publisher.root / "media" / (request + ".mp4")).write_bytes(asset)
    value = {"request_id": request, "policy": policy(), "policy_digest": module.digest(policy()),
             "asset_sha256": hashlib.sha256(asset).hexdigest(), "asset_bytes": len(asset),
             "staged_name": request + ".mp4", "state": "prepared", "binding": module.digest({"asset_sha256": hashlib.sha256(asset).hexdigest(), "policy": policy()}),
             "public_action_dispatched": False,
             "actor": {"account_id": policy()["account_id"], "username": "ata_clipper", "profile": "clipper"},
             "draft_id": "EXACT_DRAFT", "project_id": "238232531206", **changes}
    value["draft"] = draft(value)
    publisher._save(value)
    return value


def continue_migration(publisher, monkeypatch):
    import copy
    value = prepared(publisher)
    value['project_id'] = value['draft']['project_id'] = '0'
    publisher._save(value)
    receipt = {'actor': value['actor'], 'draft_id': value['draft_id'], 'draft_count': 1,
               'banner': 1, 'resumed': True, 'dom': {'editor': 1}, 'row': copy.deepcopy(value['draft'])}
    current = {**value['draft'], 'project_id': '238786606086', 'is_locked': True, 'is_temp': False}
    monkeypatch.setattr(publisher, '_page', lambda: SimpleNamespace(wait_for_timeout=lambda ms: None))
    monkeypatch.setattr(publisher, '_identity', lambda page, policy: value['actor'])
    monkeypatch.setattr(publisher, '_drafts', lambda page, policy: [current])
    return value, receipt, current


def test_recorded_continue_migration_updates_only_owned_journal_project(publisher, monkeypatch):
    value, receipt, current = continue_migration(publisher, monkeypatch)
    result = publisher._migrate_owned_continue(value['request_id'], receipt)
    assert result['project_id'] == result['draft']['project_id'] == current['project_id']
    assert result['binding'] == value['binding'] and result['asset_sha256'] == value['asset_sha256']
    assert current['is_locked'] is True and current['is_temp'] is False
    assert result['state'] == 'prepared' and result['public_action_dispatched'] is False
    assert result['editor_project_transitions'][0]['receipt_digest'] == module.digest(receipt)
    with pytest.raises(StudioPublishError):publisher._migrate_owned_continue(value['request_id'], receipt)


def test_failed_private_continue_migration_preserves_unconfigured_state(publisher, monkeypatch):
    value, receipt, current = continue_migration(publisher, monkeypatch)
    value['state'] = 'preparation_failed'
    for row in (value['draft'], receipt['row'], current):
        row.update(caption='original uploaded filename', commercial=None)
    publisher._save(value)
    result = publisher._migrate_owned_continue(value['request_id'], receipt)
    assert result['state'] == 'preparation_failed' and result['public_action_dispatched'] is False
    assert result['draft']['caption'] == 'original uploaded filename'
    assert result['draft']['commercial'] is None
    assert result['project_id'] == current['project_id']


@pytest.mark.parametrize('field', ['caption', 'privacy', 'commercial', 'create_time'])
def test_failed_private_continue_migration_refuses_changed_retained_state(publisher, monkeypatch, field):
    value, receipt, current = continue_migration(publisher, monkeypatch)
    value['state'] = 'preparation_failed'
    publisher._save(value)
    current[field] = 'changed'
    with pytest.raises(StudioPublishError):
        publisher._migrate_owned_continue(value['request_id'], receipt)
    assert publisher.status(value['request_id'])['draft']['project_id'] == '0'


@pytest.mark.parametrize('change', ['wrong_actor', 'no_editor', 'not_resumed', 'different_media', 'changed_receipt', 'dispatched', 'unknown_state', 'wrong_old_project', 'invalid_new_project', 'journal_race'])
def test_recorded_continue_migration_refuses_unproven_or_changed_binding(publisher, monkeypatch, change):
    value, receipt, current = continue_migration(publisher, monkeypatch)
    if change == 'wrong_actor':receipt['actor'] = {**receipt['actor'], 'username': 'other'}
    elif change == 'no_editor':receipt['dom']['editor'] = 0
    elif change == 'not_resumed':receipt['resumed'] = False
    elif change == 'different_media':current['video_id'] = 'different'
    elif change == 'changed_receipt':receipt['row']['file_key'] = 'other'
    elif change == 'dispatched':value['public_action_dispatched'] = True;publisher._save(value)
    elif change == 'unknown_state':value['state'] = 'outcome_unknown';publisher._save(value)
    elif change == 'wrong_old_project':value['project_id'] = '123';publisher._save(value)
    elif change == 'invalid_new_project':current['project_id'] = '0'
    else:
        def race(page, policy):
            publisher._save({**publisher.status(value['request_id']), 'concurrent_note': 'preserve'})
            return [current]
        monkeypatch.setattr(publisher, '_drafts', race)
    with pytest.raises(StudioPublishError):publisher._migrate_owned_continue(value['request_id'], receipt)
    after = publisher.status(value['request_id'])
    assert after['draft']['project_id'] == '0'
    assert 'editor_project_transitions' not in after


# Studio's own checks as they read once finished and passed (adam-server, 2026-10-07).
CHECKS_PASSED = {'lite': {'checkStatus': 2, 'checkId': '1', 'videoId': None,
                          'checkResult': [{'model_type': 0, 'model_check_result': 0}]},
                 'lite_switch': True, 'music': {'code': 1}, 'music_status': studio_check.MUSIC_DONE,
                 'music_switch': True, 'lite_ui': [], 'music_ui': []}
CHECKS_RUNNING = {**CHECKS_PASSED, 'lite': {'checkStatus': 1}, 'music_status': 'SWITCH_ON_CHECKING'}
CONFIRMATION = ("Continue to post?\n\nWe're still checking your video for potential issues. Do you want to "
                "continue posting before the check is complete?\nCancel\nPost now")

# Headed Chrome on adam-server, read 2026-10-06; headless reports HeadlessChrome/155.
HEADED_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36'


class Page:
    def __init__(self, row):
        self.rows = [row];self.events = [];self.restored = False;self.clicked = 0
        self.receipt = {"status_code": 0, "project_id": row["project_id"],
                        "single_post_resp_list": [{"status_code": 0, "batch_index": 0, "item_id": "7692252984792681742"}]}
        self.click_error = False
        self.network_after_click_error = False
        self.observer_options = None
        self.network_sent = False
        self.environment = {'user_agent': HEADED_UA, 'webdriver': False, 'screen': [1920, 1080]}
        self.checks = [CHECKS_PASSED]
        self.confirmation_on_click = False
    def begin_network_observation(self, **kwargs):
        assert kwargs == {'method': 'POST', 'origin': 'https://www.tiktok.com', 'path': module.POST_PATH}
        return 'exact-session'
    def end_network_observation(self):pass
    def native_request(self):
        opts = self.observer_options
        return {'post_common_info': {'creation_id': opts['creation_id'], 'enter_post_page_from': 1, 'post_type': 1},
                'single_post_req_list': [{'video_id': opts['video_id'], 'batch_index': 0,
                    'single_post_feature_info': {'text': opts['caption'], 'text_extra': opts['caption_text_extra']}}]}
    def network_observations(self, session, **kwargs):
        if not self.clicked or self.confirmation_on_click:return []
        if self.click_error and not self.network_after_click_error:
            raise RuntimeError('network disconnected after click')
        if not self.clicked or self.network_sent:return []
        self.network_sent = True
        return [{'kind': 'request', 'request_id': '123.1', 'body': json.dumps(self.native_request())},
                {'kind': 'response', 'request_id': '123.1', 'status': 200, 'route_matches': True},
                {'kind': 'finished', 'request_id': '123.1', 'encoded_bytes': 128}]
    def network_response_body(self, session, request_id, **kwargs):
        assert session == 'exact-session' and request_id == '123.1'
        return json.dumps(self.receipt)
    def wait_for_timeout(self, duration):pass
    def locator(self, selector):
        page = self
        class Locator:
            def count(self):return 0 if selector == '.more-btn > span:first-child:has-text("Show more")' else 1
            def click(self):
                assert selector == module.POST_SELECTOR
                page.events.append("Post");page.clicked += 1
                if page.click_error:raise RuntimeError("transport disconnected after click")
        return Locator()
    def get_by_role(self, role, **kwargs):
        assert role == "button" and kwargs == {"name": "Continue", "exact": True}
        return SimpleNamespace(click=lambda: self.events.append("Continue"))
    def evaluate(self, script, value=None):
        if script == module.EDITOR_STATE_JS:return editor_state(self.rows[0])
        if script == module.CAPTION_TEXT_JS:return self.rows[0]['caption']
        if script == module.CONTROLS_JS:
            dialogs = [CONFIRMATION] if self.confirmation_on_click and self.clicked else []
            return {"upload_complete": True, "post_enabled": True, "dialogs": dialogs}
        if script == studio_check.CHECK_STATE_JS:
            self.events.append("checks");return self.checks.pop(0) if len(self.checks) > 1 else self.checks[0]
        if script == module.DRAFTS_JS:return self.rows
        if script == module.OBSERVER_JS:self.observer_options = value;self.events.append("observe");return True
        if script == module.DEADLINE_JS:self.dispatch_deadline = value['deadline'];return True
        if script == module.RESTORE_JS:self.restored = True;return True
        if script == module.BROWSER_ENV_JS:return self.environment
        raise AssertionError(script)


def editor_state(row):
    return {'project': {'projectId': row['project_id'], 'creationId': row['creation_id']},
            'track_id': row['creation_id'], 'draft_id': None, 'draft_type': None,
            'draft_resumed_from': None, 'full_screen_upload': False,
            'current_file_key': row['file_key'], 'file_keys': [row['file_key']],
            'editor_count': 1, 'caption_state_count': 1, 'inputs': [],
            'files': [{k: row[k] for k in module.MEDIA_BINDING_FIELDS if k != 'creation_id'}]}


def fresh_state():
    return {'project': {'projectId': '', 'creationId': ''}, 'track_id': 'NEW_CREATION',
            'draft_id': None, 'draft_type': None, 'draft_resumed_from': None,
            'full_screen_upload': True, 'current_file_key': '', 'file_keys': [],
            'files': [], 'editor_count': 0, 'caption_state_count': 0, 'inputs': [{'disabled': False, 'multiple': False}]}


def test_fresh_native_entry_preserves_existing_draft(publisher):
    state = fresh_state();page = SimpleNamespace(evaluate=lambda script: state)
    assert publisher._fresh_entry(page, [{'creation_id': 'OLD_CREATION'}]) == 'NEW_CREATION'


@pytest.mark.parametrize('change', [
    {'project': {'projectId': '1', 'creationId': 'OLD_CREATION'}},
    {'draft_id': 'OLD'}, {'draft_type': 'local'}, {'draft_resumed_from': 'local'},
    {'editor_count': 1}, {'file_keys': ['old_file']}, {'current_file_key': 'old_file'},
    {'files': [{'file_key': 'old_file'}]}, {'full_screen_upload': False},
    {'track_id': 'OLD_CREATION'}, {'inputs': [{'disabled': True, 'multiple': False}]},
    {'inputs': [{'disabled': False, 'multiple': True}]}, {'inputs': []},
])
def test_fresh_native_entry_rejects_resumed_or_unproven_context(publisher, change):
    page = SimpleNamespace(evaluate=lambda script: fresh_state() | change)
    with pytest.raises(StudioPublishError):publisher._fresh_entry(page, [{'creation_id': 'OLD_CREATION'}])


@pytest.mark.parametrize('field', ['project', 'track_id', 'current_file_key', 'file_keys', 'files', 'editor_count', 'full_screen_upload', 'inputs'])
def test_owned_editor_wrong_native_binding_fails_before_edits(publisher, field):
    value = prepared(publisher);state = editor_state(value['draft'])
    state[field] = {'projectId': 'other', 'creationId': 'other'} if field == 'project' else None
    with pytest.raises(StudioPublishError):publisher._verify_editor(SimpleNamespace(evaluate=lambda script: state), value['draft'])


@pytest.mark.parametrize('field', module.MEDIA_BINDING_FIELDS)
def test_owned_editor_rejects_other_media_despite_matching_local_row(publisher, field):
    value = prepared(publisher);state = editor_state(value['draft'])
    if field == 'creation_id':state['project']['creationId'] = 'OTHER'
    else:state['files'][0][field] = 'OTHER'
    with pytest.raises(StudioPublishError):publisher._verify_editor(SimpleNamespace(evaluate=lambda script: state), value['draft'])


def test_preserved_draft_missing_or_changed_is_never_ignored(publisher):
    prior = {'draft_id': 'OLD', 'creation_id': 'OLD', 'video_id': 'old_vid'}
    operation = {'prior_drafts': {'OLD': module.digest(prior)}}
    publisher._preserve_prior_drafts(operation, [prior, {'draft_id': 'NEW'}])
    for rows in [[], [prior | {'video_id': 'other'}], [prior, prior]]:
        with pytest.raises(StudioPublishError):publisher._preserve_prior_drafts(operation, rows)


def test_exact_current_editor_allows_other_untouched_drafts(publisher, monkeypatch):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    old = draft(value, draft_id='OLD', creation_id='OLD', file_name='old.mp4', file_key='old_key', video_id='old_vid')
    value['prior_drafts'] = {'OLD': module.digest(old)}
    page.rows.append(old)
    result, _ = publisher._ready_editor(value)
    assert result['draft_id'] == value['draft_id'] and old in page.rows
    assert 'Continue' not in page.events and page.clicked == 0


def attach(publisher, value, monkeypatch):
    page = Page(value["draft"])
    monkeypatch.setattr(publisher, "_page", lambda: page)
    monkeypatch.setattr(publisher, "_identity", lambda *args: value["actor"])
    monkeypatch.setattr(publisher, "_verify_controls", lambda *args: {})
    return page


def test_trusted_callback_is_last_action_before_one_public_post(publisher, monkeypatch):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    monkeypatch.setattr(publisher, "_reconcile", lambda v: v)
    def authorize(binding):
        assert binding["request_id"] == value["request_id"]
        assert binding["asset_sha256"] == value["asset_sha256"]
        assert binding["policy_digest"] == value["policy_digest"]
        assert binding["actor"]["account_id"] == policy()["account_id"]
        assert binding["draft_id"] == value["draft_id"]
        assert publisher.status(value["request_id"])["state"] == "dispatch_pending"
        page.events.append("callback")
    result = publisher.publish(value["request_id"], before_public_action=authorize)
    assert page.events[-2:] == ["callback", "Post"] and page.clicked == 1
    assert result["state"] == "receipt_observed" and page.restored
    with pytest.raises(StudioPublishError, match="retry"):
        publisher.publish(value["request_id"], before_public_action=authorize)
    assert page.clicked == 1


def test_callback_rejection_never_posts_and_preserves_safe_prepared_state(publisher, monkeypatch):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    def reject(binding):raise RuntimeError("coordinator reservation expired")
    with pytest.raises(StudioPublishError) as error:
        publisher.publish(value["request_id"], before_public_action=reject)
    assert error.value.category == "pre_action_abort" and page.clicked == 0 and page.restored
    assert publisher.status(value["request_id"])["state"] == "prepared"


def test_observer_cleanup_failure_preserves_primary_post_error(publisher, monkeypatch):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    page.click_error = True
    original = page.evaluate
    def evaluate(script, argument=None):
        if script == module.RESTORE_JS:
            raise RuntimeError('cleanup failure')
        return original(script, argument)
    page.evaluate = evaluate
    with pytest.raises(StudioPublishError) as error:
        publisher.publish(value['request_id'], before_public_action=lambda binding: None)
    assert str(error.value.__cause__.__cause__) == 'transport disconnected after click'
    saved = publisher.status(value['request_id'])
    assert saved['state'] == 'outcome_unknown'
    assert saved['post_failure'] == {'stage': 'post_receipt_read', 'error_type': 'RuntimeError'}
    assert saved['observer_cleanup_issue'] == {'error_type': 'RuntimeError', 'recoverable': True}


def test_callback_denial_cleanup_failure_preserves_known_no_dispatch(publisher, monkeypatch):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    original = page.evaluate
    def evaluate(script, argument=None):
        if script == module.RESTORE_JS:raise RuntimeError('cleanup failure')
        return original(script, argument)
    page.evaluate = evaluate
    def deny(binding):raise RuntimeError('trusted denial')
    with pytest.raises(StudioPublishError, match='callback rejected'):
        publisher.publish(value['request_id'], before_public_action=deny)
    saved = publisher.status(value['request_id'])
    assert saved['state'] == 'prepared' and saved['public_action_dispatched'] is False
    assert page.clicked == 0 and saved['observer_cleanup_issue']['recoverable'] is True


@pytest.mark.parametrize("change", [{"video_id": "wrong"}, {"file_key": "wrong"}, {"file_size": 1},
                                  {"caption": "wrong"}, {"privacy": {"visibility_type": 1}},
                                  {"commercial": {"commerce_toggle_info": {"branded_content_type": 1}}}])
def test_media_or_saved_control_mismatch_aborts_before_callback_and_post(publisher, monkeypatch, change):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch);page.rows[0] = draft(value, **change)
    with pytest.raises(StudioPublishError):
        publisher.publish(value["request_id"], before_public_action=lambda binding: pytest.fail("callback must not run"))
    assert page.clicked == 0


def test_other_user_draft_is_preserved_without_continue_or_post(publisher, monkeypatch):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    page.rows.append(draft(value, draft_id="USER_DRAFT"))
    with pytest.raises(StudioPublishError, match="uniquely"):
        publisher.publish(value["request_id"], before_public_action=lambda b: None)
    assert page.events == [] and page.clicked == 0


def test_changed_staged_bytes_abort_before_browser(publisher, monkeypatch):
    value = prepared(publisher)
    (publisher.root / "media" / value["staged_name"]).write_bytes(b"changed")
    monkeypatch.setattr(publisher, "_page", lambda: pytest.fail("browser must not open"))
    with pytest.raises(StudioPublishError, match="bound size"):
        publisher.publish(value["request_id"], before_public_action=lambda b: None)


@pytest.mark.parametrize("failure", ["click", "malformed_receipt", "numeric_id", "wrong_project", "multiple_results"])
def test_unknown_post_cannot_be_retried_even_with_same_request(publisher, monkeypatch, failure):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    if failure == "click":page.click_error = True
    if failure == "malformed_receipt":page.receipt = {}
    if failure == "numeric_id":page.receipt["single_post_resp_list"][0]["item_id"] = 7692252984792681742
    if failure == "wrong_project":page.receipt["project_id"] = "wrong"
    if failure == "multiple_results":page.receipt["single_post_resp_list"].append(dict(page.receipt["single_post_resp_list"][0]))
    with pytest.raises(StudioPublishError) as error:
        publisher.publish(value["request_id"], before_public_action=lambda b: None)
    assert error.value.category == "ambiguous_post_action"
    assert publisher.status(value["request_id"])["state"] == "outcome_unknown"
    with pytest.raises(StudioPublishError):publisher.publish(value["request_id"], before_public_action=lambda b: None)
    assert page.clicked == 1


def test_no_receipt_reconcile_never_opens_browser_or_guesses_caption(publisher, monkeypatch):
    value = prepared(publisher, state="outcome_unknown")
    monkeypatch.setattr(publisher.config, "get_browser", lambda: pytest.fail("must not infer an ID"), raising=False)
    result = publisher.reconcile(value["request_id"])
    assert result["reconciliation"] == "inconclusive_no_exact_receipt_id"


def test_delayed_studio_receipt_stays_persisted_and_later_reconciles(publisher, monkeypatch):
    value = prepared(publisher, state="receipt_observed", item_id="7692252984792681742")
    publisher.browser = SimpleNamespace(close=lambda: None)
    def delayed(*args):raise module.ClientError("studio_video_not_found")
    monkeypatch.setattr(publisher.client, "get_studio_video", delayed)
    with pytest.raises(module.ClientError):publisher.reconcile(value["request_id"])
    assert publisher.status(value["request_id"])["item_id"] == value["item_id"]
    result = {"caption": policy()["caption"], "account_id": policy()["account_id"], "visibility": 1, "url": "exact-post-url"}
    monkeypatch.setattr(publisher.client, "get_studio_video", lambda *args: result)
    assert publisher.reconcile(value["request_id"])["state"] == "published_verified"
    assert not (publisher.root / "media" / value["staged_name"]).exists()
    assert publisher.status(value["request_id"])["media_cleanup_state"] == "removed"
    # Restart after verified cleanup is read-only and idempotent.
    assert publisher.reconcile(value["request_id"])["state"] == "published_verified"


def test_staging_limit_and_low_disk_fail_before_browser(publisher, tmp_path, monkeypatch):
    file = tmp_path / "asset.mp4";file.write_bytes(b"12345")
    monkeypatch.setattr(publisher, "_page", lambda: pytest.fail("browser must not open"))
    monkeypatch.setattr(module, "MAX_ASSET_BYTES", 4)
    with pytest.raises(StudioPublishError, match="30 GB"):publisher.prepare(file, policy(), str(uuid4()))
    monkeypatch.setattr(module, "MAX_ASSET_BYTES", 100)
    monkeypatch.setattr(module.shutil, "disk_usage", lambda p: SimpleNamespace(free=0))
    with pytest.raises(StudioPublishError, match="reserve"):publisher.prepare(file, policy(), str(uuid4()))


def test_orphan_temp_is_removed_and_copy_failure_leaves_no_temp(publisher, tmp_path, monkeypatch):
    file = tmp_path / "asset.mp4";file.write_bytes(b"12345");request = str(uuid4())
    workspace = publisher.root / "media";workspace.mkdir()
    temporary = workspace / (request + ".tmp");temporary.write_bytes(b"orphan")
    original_open = Path.open
    class FailedRead:
        def __enter__(self):return self
        def __exit__(self, *args):pass
        def read(self, *args):raise OSError("local media read failed")
    def fail(path, *args, **kwargs):
        return FailedRead() if path == file else original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", fail)
    with pytest.raises(OSError):publisher.prepare(file, policy(), request)
    assert not temporary.exists()


def test_prepared_same_request_and_binding_never_uploads_again(publisher, tmp_path, monkeypatch):
    value = prepared(publisher)
    value["binding"] = module.digest({"asset_sha256": value["asset_sha256"], "policy": value["policy"]})
    with module.sqlite3.connect(publisher.database) as db:
        db.execute("UPDATE operations SET binding=?,record=? WHERE request_id=?", (value["binding"], module.canonical(value), value["request_id"]))
    file = tmp_path / "same.mp4";file.write_bytes(b"known-mp4-bytes")
    attach(publisher, value, monkeypatch)
    assert publisher.prepare(file, policy(), value["request_id"])["state"] == "prepared"
    with pytest.raises(StudioPublishError, match="different request"):
        publisher.prepare(file, policy(), str(uuid4()))


@pytest.mark.parametrize('recovery', ['continue', 'missing'])
def test_prepare_returns_live_recovery_binding_before_publish_callback(publisher, monkeypatch, recovery):
    value = prepared(publisher)
    page = attach(publisher, value, monkeypatch)
    if recovery == 'continue':
        original = page.locator
        page.opened = False
        def locator(selector):
            if selector == module.CAPTION_SELECTOR:
                return SimpleNamespace(count=lambda: int(page.opened))
            return original(selector)
        page.locator = locator
        def continued():
            page.opened = True
            page.rows[0] = {**page.rows[0], 'project_id': '987654321'}
        page.get_by_role = lambda *args, **kwargs: SimpleNamespace(click=continued)
    else:
        page.rows = []
        original_evaluate = page.evaluate
        page.evaluate = lambda script, value=None: True if script == module.HEARTBEAT_JS else original_evaluate(script, value)
        def rebuilt(source, policy, request_id):
            row = {**value['draft'], 'draft_id': 'OWNED_REBUILT', 'creation_id': 'OWNED_REBUILT'}
            result = {**value, 'draft_id': row['draft_id'], 'draft': row}
            page.rows = [row];publisher._save(result)
            return result
        original_prepare = publisher._prepare
        def prepare(source, policy, request_id):
            if publisher.status(request_id)['state'] == 'preparation_failed':
                return rebuilt(source, policy, request_id)
            return original_prepare(source, policy, request_id)
        monkeypatch.setattr(publisher, '_prepare', prepare)
    ready = publisher.prepare(publisher.root/'media'/value['staged_name'], value['policy'], value['request_id'])
    def deny(binding):
        pending = publisher.status(value['request_id'])
        assert pending['draft'] == ready['draft']
        assert binding['draft_id'] == ready['draft_id']
        assert binding['project_id'] == ready['project_id']
        raise RuntimeError('trusted denial')
    with pytest.raises(StudioPublishError, match='callback rejected'):
        publisher.publish(value['request_id'], before_public_action=deny)
    assert page.clicked == 0


def test_cli_public_post_guard_runs_before_publisher_construction(monkeypatch):
    from typer.testing import CliRunner
    from tiktok_cli.commands import studio
    monkeypatch.setattr(studio, "StudioPublisher", lambda *args: pytest.fail("must not construct publisher"))
    result = CliRunner().invoke(studio.app, ["publish", str(uuid4())])
    assert result.exit_code == 1 and "without --yes" in result.output


@pytest.mark.parametrize("field", ["project_id_present", "creation_id", "video_id", "batch_index"])
def test_receipt_rejects_wrong_observed_request_even_with_correct_response(publisher, field):
    value = prepared(publisher)
    observed = {"count": 1, "project_id_present": False, "creation_id": value["draft"]["creation_id"], "video_id": value["draft"]["video_id"], "batch_index": 0,
        "receipt": {"status": 200, "body": json.dumps({"status_code": 0, "project_id": value["project_id"],
            "single_post_resp_list": [{"status_code": 0, "batch_index": 0, "item_id": "7692252984792681742"}]})}}
    observed[field] = "DIFFERENT_REQUEST"
    with pytest.raises(StudioPublishError) as error:module.accepted_project(observed, value)
    assert error.value.category == "ambiguous_post_action"


def test_native_transport_guard_blocks_wrong_binding_and_duplicate_before_send():
    import subprocess
    script = """
    global.window={};global.location={href:'https://www.tiktok.com/tiktokstudio/upload'};
    let sends=0,aborts=0;
    class XHR{open(){} send(){sends++} abort(){aborts++} addEventListener(){}}
    global.XMLHttpRequest=XHR;
    const install=OBSERVER;
    const exact={post_common_info:{creation_id:'OWNED',enter_post_page_from:1,post_type:2},single_post_req_list:[{video_id:'VIDEO',batch_index:0,single_post_feature_info:{text:'CAPTION',text_extra:[]}}]};
    function attempt(payload){const x=new XHR();x.open('POST','/tiktok/web/project/post/v1/');try{x.send(JSON.stringify(payload))}catch(e){}}
    const invalid=[
      {...exact,post_common_info:{...exact.post_common_info,creation_id:'FOREIGN'}},
      {...exact,post_common_info:{...exact.post_common_info,project_id:'UNSUPPORTED'}},
      {...exact,single_post_req_list:[{video_id:'FOREIGN',batch_index:0}]},
      {...exact,single_post_req_list:[{video_id:'VIDEO',batch_index:1}]},
      {...exact,single_post_req_list:[exact.single_post_req_list[0],exact.single_post_req_list[0]]},
      {...exact,single_post_req_list:[{...exact.single_post_req_list[0],single_post_feature_info:{text:'WRONG',text_extra:[]}}]},
      {...exact,single_post_req_list:[{...exact.single_post_req_list[0],single_post_feature_info:{text:'CAPTION',text_extra:[{type:0,user_id:'OTHER'}]}}]}];
    for(let i=0;i<invalid.length;i++){const key='invalid'+i;
      install({key,path:'/tiktok/web/project/post/v1/',creation_id:'OWNED',video_id:'VIDEO',caption:'CAPTION',caption_text_extra:[]});
      attempt(invalid[i]);if(sends!==0||aborts!==i+1)throw Error('mismatch sent');window[key].restore();}
    install({key:'exact',path:'/tiktok/web/project/post/v1/',creation_id:'OWNED',video_id:'VIDEO',caption:'CAPTION',caption_text_extra:[]});
    attempt(exact);attempt(exact);if(sends!==1||aborts!==8||window.exact.count!==2)throw Error('duplicate sent');
    window.exact.restore();console.log('ZERO_MISMATCH_SENDS_ONE_EXACT_SEND');
    """.replace('OBSERVER', '(' + module.OBSERVER_JS + ')')
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == 'ZERO_MISMATCH_SENDS_ONE_EXACT_SEND'


@pytest.mark.parametrize("state", ["dispatch_pending", "outcome_unknown", "receipt_observed", "published_verified"])
def test_orphan_recovery_rejects_every_public_boundary_before_browser(publisher, state):
    value = prepared(publisher, state=state)
    with pytest.raises(StudioPublishError, match="public-action boundary"):
        publisher._delete_owned_orphan(None, value)


def test_orphan_recovery_requires_exact_journal_binding_and_no_live_editor(publisher, monkeypatch):
    value = prepared(publisher)
    monkeypatch.setattr(publisher, "_identity", lambda *args: value["actor"])
    page = Page(value["draft"])
    with pytest.raises(StudioPublishError, match="active editor"):
        publisher._delete_owned_orphan(page, value)
    value["binding"] = "changed"
    with pytest.raises(StudioPublishError, match="journal binding changed"):
        publisher._delete_owned_orphan(page, value)


def test_orphan_atomic_transaction_refuses_changed_row_and_active_heartbeat():
    import subprocess
    script = """
    global.localStorage={getItem:k=>k.startsWith('web_creation_heartbeats_')?JSON.stringify(beats):times[k]??null};
    const expected={draft_id:'OWNED',creation_id:'OWNED',project_id:'PROJECT',video_id:'VIDEO',file_key:'FILE',file_name:'UUID.mp4',file_size:42,duration_ms:1000};
    let beats=[],times={},deletes=0,changed=false;
    global.indexedDB={open(){const request={};setTimeout(()=>{request.result={objectStoreNames:{contains:n=>n==='local_draft_123'},close(){},transaction(){
      const tx={abort(){setTimeout(()=>tx.onabort())},objectStore(){return {get(key){const get={};setTimeout(()=>{
        get.result={key,isLocked:true,data:{basic_info:{creation_id:'OWNED',project_id:'PROJECT',media_draft_info:{vid:changed?'FOREIGN':'VIDEO',video_duration_ms:1000,video_file_desc:JSON.stringify({fileKey:'FILE',rawFile:{name:'UUID.mp4',size:42}})}}}};
        get.onsuccess();if(!changed)setTimeout(()=>tx.oncomplete())});return get},delete(key){if(key!=='OWNED')throw Error('wrong key');deletes++}}}};return tx}};request.onsuccess()});return request}};
    const remove=DELETE;
    (async()=>{
      beats=['web_creation_heartbeat_OTHER'];times[beats[0]]=JSON.stringify(Date.now());
      try{await remove({owner:'123',expected});throw Error('active accepted')}catch(e){if(e.message!=='ACTIVE_STUDIO_HEARTBEAT')throw e}
      if(deletes!==0)throw Error('active delete');
      beats=[];changed=true;try{await remove({owner:'123',expected});throw Error('change accepted')}catch(e){if(e.message!=='ORPHAN_BINDING_REJECTED')throw e}
      if(deletes!==0)throw Error('changed delete');
      changed=false;const result=await remove({owner:'123',expected});if(!result.deleted||deletes!==1)throw Error('exact delete failed');
      console.log('ATOMIC_CHANGED_AND_ACTIVE_REFUSED_ONLY_EXACT_DELETED');
    })().catch(e=>{console.error(e);process.exitCode=1});
    """.replace('const remove=DELETE;', 'const remove=(' + module.DELETE_ORPHAN_JS + ');')
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == 'ATOMIC_CHANGED_AND_ACTIVE_REFUSED_ONLY_EXACT_DELETED'


@pytest.mark.parametrize("editor_project", ["0", "238232531206"])
def test_response_post_project_is_separate_from_editor_metadata(publisher, monkeypatch, editor_project):
    value = prepared(publisher, project_id=editor_project)
    value["draft"]["project_id"] = editor_project;publisher._save(value)
    page = attach(publisher, value, monkeypatch)
    page.receipt["project_id"] = "555666777"
    monkeypatch.setattr(publisher, "_reconcile", lambda v: v)
    result = publisher.publish(value["request_id"], before_public_action=lambda binding: None)
    assert result["project_id"] == editor_project and result["post_project_id"] == "555666777"
    assert result["item_id"] == "7692252984792681742"


@pytest.mark.parametrize("optional", [{}, {"single_post_resp_list": []}, {"single_post_resp_list": [{"status_code": 0, "batch_index": 0}]}])
def test_accepted_project_survives_restart_pending_then_exact_success(publisher, monkeypatch, optional):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    page.receipt = {"status_code": 0, "project_id": "555666777", **optional}
    monkeypatch.setattr(publisher, "_reconcile", lambda operation: operation)
    result = publisher.publish(value["request_id"], before_public_action=lambda binding: None)
    assert result["state"] == "project_accepted" and "item_id" not in result
    restarted = StudioPublisher(publisher.config, browser=SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(restarted, "_page", lambda: page)
    monkeypatch.setattr(restarted, "_identity", lambda *args: value["actor"])
    responses = iter([
        {"status_code": 0, "project_status": 1, "task_list": [{"task_status": 1}]},
        {"status_code": 0, "project_status": 2, "task_list": [{"task_status": 2, "item_id": "7692252984792681742"}]},
    ])
    paths = []
    def fetch(page, path):
        assert restarted.status(value["request_id"])["post_project_id"] == "555666777"
        paths.append(path);return next(responses)
    monkeypatch.setattr(restarted.client, "_fetch_json", fetch)
    assert restarted.reconcile(value["request_id"])["state"] == "project_pending"
    with pytest.raises(StudioPublishError):restarted.publish(value["request_id"], before_public_action=lambda b: pytest.fail("must never dispatch again"))
    record = {"caption": policy()["caption"], "account_id": policy()["account_id"], "visibility": 1, "url": "exact-post-url"}
    def exact_read(username, item, account):
        assert item == "7692252984792681742"
        assert restarted.status(value["request_id"])["item_id"] == item
        return record
    monkeypatch.setattr(restarted.client, "get_studio_video", exact_read)
    assert restarted.reconcile(value["request_id"])["state"] == "published_verified"
    assert paths == [module.PROJECT_STATUS_PATH + "?project_id=555666777"] * 2
    assert page.clicked == 1
    restarted.close()


@pytest.mark.parametrize("payload,expected", [
    ({"status_code": 0, "project_status": 3, "task_list": [{"task_status": 3}]}, "post_failed"),
    ({"status_code": 0, "project_status": 0, "task_list": [{"task_status": 0}]}, "project_unknown"),
    ({"status_code": 0, "project_status": 4, "task_list": [{"task_status": 1}]}, "project_pending"),
    ({"status_code": 0, "project_status": 2, "task_list": []}, None),
    ({"status_code": 0, "project_status": 2, "task_list": [{"task_status": 2}, {"task_status": 2}]}, None),
    ({"status_code": 0, "project_status": 2, "task_list": [{"task_status": 2, "item_id": 7692252984792681742}]}, None),
    ({"status_code": 0, "project_status": 2, "task_list": [{"task_status": 3}]}, None),
    ({"status_code": 0, "project_status": 3, "task_list": [{"task_status": 2}]}, None),
    ({"status_code": 0, "project_status": True, "task_list": [{"task_status": 1}]}, None),
    ({"status_code": 1, "project_status": 2, "task_list": [{"task_status": 2}]}, None),
    ({"status_code": 0, "project_status": 2, "task_list": [{"task_status": True}]}, None),
    ({"status_code": 0, "project_id": "WRONG", "project_status": 1, "task_list": [{"task_status": 1}]}, None),
])
def test_async_terminal_and_malformed_responses_never_repost(publisher, monkeypatch, payload, expected):
    value = prepared(publisher, state="project_accepted", public_action_dispatched=True, post_project_id="555666777")
    page = attach(publisher, value, monkeypatch)
    monkeypatch.setattr(publisher.client, "_fetch_json", lambda *args: payload)
    monkeypatch.setattr(publisher.client, "get_studio_video", lambda *args: pytest.fail("must not guess item"))
    if expected is None:
        with pytest.raises(StudioPublishError) as error:publisher.reconcile(value["request_id"])
        assert error.value.category == "ambiguous_post_action"
    else:
        assert publisher.reconcile(value["request_id"])["state"] == expected
    assert publisher.status(value["request_id"])["post_project_id"] == "555666777"
    with pytest.raises(StudioPublishError):publisher.publish(value["request_id"], before_public_action=lambda b: pytest.fail("must not authorize"))
    assert page.clicked == 0


def test_malformed_optional_item_retains_accepted_project_before_error(publisher, monkeypatch):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    page.receipt["project_id"] = "555666777"
    page.receipt["single_post_resp_list"][0]["item_id"] = 123
    with pytest.raises(StudioPublishError):publisher.publish(value["request_id"], before_public_action=lambda b: None)
    saved = publisher.status(value["request_id"])
    assert saved["post_project_id"] == "555666777" and saved["state"] == "outcome_unknown"
    assert page.clicked == 1


@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo", "same_size_changed_bytes"])
def test_asset_rejects_non_owned_file_or_changed_hash_before_browser(publisher, monkeypatch, kind, tmp_path):
    value = prepared(publisher);path = publisher.root / "media" / value["staged_name"]
    path.unlink()
    if kind == "symlink":
        target = tmp_path / "foreign.mp4";target.write_bytes(b"known-mp4-bytes");path.symlink_to(target)
    elif kind == "directory":path.mkdir()
    elif kind == "fifo":module.os.mkfifo(path)
    else:path.write_bytes(b"wrong-mp4-byte!")
    monkeypatch.setattr(publisher, "_page", lambda: pytest.fail("must not open browser"))
    with pytest.raises(StudioPublishError):publisher.publish(value["request_id"], before_public_action=lambda b: pytest.fail("must not authorize"))


def test_path_replacement_during_asset_hash_is_rejected(publisher, monkeypatch):
    value = prepared(publisher);path = publisher.root / "media" / value["staged_name"]
    original = module.hashlib.file_digest
    def replace(stream, algorithm):
        result = original(stream, algorithm)
        replacement = path.with_suffix(".replacement");replacement.write_bytes(b"known-mp4-bytes")
        replacement.replace(path)
        return result
    monkeypatch.setattr(module.hashlib, "file_digest", replace)
    with pytest.raises(StudioPublishError, match="file identity changed"):publisher._verify_asset(value)


def test_disk_pressure_after_copy_starts_removes_only_owned_temp(publisher, tmp_path, monkeypatch):
    source = tmp_path / "source.mp4";source.write_bytes(b"x" * (10 * 1024 * 1024))
    request = str(uuid4());workspace = publisher.root / "media";workspace.mkdir()
    foreign = workspace / "another-request.tmp";foreign.write_bytes(b"preserve")
    checks = []
    def available(path):
        checks.append(path)
        return SimpleNamespace(free=(source.stat().st_size + module.MIN_FREE_BYTES) if len(checks) <= 2 else 0)
    monkeypatch.setattr(module.shutil, "disk_usage", available)
    monkeypatch.setattr(publisher, "_page", lambda: pytest.fail("must not open browser"))
    with pytest.raises(StudioPublishError, match="fell below"):publisher.prepare(source, policy(), request)
    assert len(checks) == 3 and foreign.read_bytes() == b"preserve"
    assert not (workspace / (request + ".tmp")).exists()
    assert not (workspace / (request + ".mp4")).exists()


def test_cli_local_status_uses_inactive_profile_without_auth_or_browser(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from tiktok_cli.config import Config, reset_config
    from tiktok_cli.main import app
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    reset_config()
    default = Config(profile="default")
    for name, active in [("default", "true"), ("clipper", "false")]:
        path = default.profile_path_for(name);path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("AUTH_TYPE=browser_session\nACTIVE=" + active + "\n")
    snapshots = {name: default.profile_path_for(name).read_bytes() for name in ["default", "clipper"]}
    local = StudioPublisher(Config(profile="clipper"))
    value = prepared(local)
    monkeypatch.setattr(Config, "get_browser", lambda *args: pytest.fail("local status must not open browser"))
    monkeypatch.setattr(Config, "test_connection", lambda *args: pytest.fail("local status must not check auth"))
    monkeypatch.setattr(Config, "get_missing_credentials", lambda *args: pytest.fail("local status must not require credentials"))
    try:
        result = CliRunner().invoke(app, ["studio", "status", value["request_id"], "--profile", "clipper"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["request_id"] == value["request_id"]
        assert snapshots == {name: default.profile_path_for(name).read_bytes() for name in snapshots}
    finally:local.close();reset_config()


@pytest.mark.parametrize("content,message", [(b"x" * (64 * 1024 + 1), "64 KiB"), (b"\xff", "UTF-8")])
def test_cli_bounded_policy_input_rejected_before_publisher(tmp_path, monkeypatch, content, message):
    from typer.testing import CliRunner
    from tiktok_cli.commands import studio
    asset = tmp_path / "asset.mp4";asset.write_bytes(b"asset")
    policy_file = tmp_path / "policy.json";policy_file.write_bytes(content)
    monkeypatch.setattr(studio, "StudioPublisher", lambda *args: pytest.fail("must reject before publisher"))
    result = CliRunner().invoke(studio.app, ["prepare", str(asset), "--policy", str(policy_file), "--request-id", str(uuid4())])
    assert result.exit_code == 1 and message in result.output


def test_private_failed_recovery_refuses_changed_duration(publisher, monkeypatch):
    value = prepared(publisher, state="preparation_failed")
    page = attach(publisher, value, monkeypatch)
    page.rows[0] = draft(value, duration_ms=9999)
    with pytest.raises(StudioPublishError, match="media binding changed"):
        publisher._recover_private_preparation(value)
    assert not page.events and page.clicked == 0


def test_saved_native_entities_preserve_utf16_offsets_and_duplicate_tokens():
    caption = '🙂 @hardscope @hardscope #ad'
    row = draft({'policy': {'caption': caption}, 'staged_name': 'asset.mp4', 'asset_bytes': 1})
    result = module.caption_entities(row, caption)
    assert [value['start'] for value in result] == [3, 14, 25]
    assert [value['type'] for value in result] == [0, 0, 1]
    assert result[0]['user_id'] == result[1]['user_id'] == '1234567890'
    assert result[2]['hashtag_name'] == 'ad'


@pytest.mark.parametrize('change', ['empty_map', 'wrong_name', 'numeric_uid', 'zero_uid', 'wrong_type', 'mutable', 'wrong_offset', 'bool_offset', 'wrong_extra'])
def test_saved_entity_verification_denies_plain_or_contradictory_semantics(change):
    caption = '@hardscope #ad'
    row = draft({'policy': {'caption': caption}, 'staged_name': 'asset.mp4', 'asset_bytes': 1})
    raw = json.loads(row['caption_markup'])
    if change == 'empty_map':raw['entityMap'] = {}
    elif change == 'wrong_name':raw['entityMap']['0']['data']['mention']['name'] = 'hardscope.evil'
    elif change == 'numeric_uid':raw['entityMap']['0']['data']['mention']['id'] = 123
    elif change == 'zero_uid':raw['entityMap']['0']['data']['mention']['id'] = '0'
    elif change == 'wrong_type':raw['entityMap']['0']['type'] = '#mention'
    elif change == 'mutable':raw['entityMap']['0']['mutability'] = 'MUTABLE'
    elif change == 'wrong_offset':raw['blocks'][0]['entityRanges'][0]['offset'] = 1
    elif change == 'bool_offset':raw['blocks'][0]['entityRanges'][0]['offset'] = False
    else:row['caption_text_extra'] = [{'type': 0, 'user_id': 'wrong'}]
    row['caption_markup'] = json.dumps(raw)
    with pytest.raises(StudioPublishError, match='entities are unverified'):
        module.caption_entities(row, caption)


def test_already_correct_entities_skip_edit_and_reverify_controls_before_callback(publisher, monkeypatch):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    monkeypatch.setattr(publisher, '_verify_controls', lambda *args: page.events.append('controls'))
    def deny(binding):
        assert page.events[-2:] == ['controls', 'observe']
        raise RuntimeError('trusted denial')
    with pytest.raises(StudioPublishError, match='callback rejected'):
        publisher.publish(value['request_id'], before_public_action=deny)
    assert page.clicked == 0 and publisher.status(value['request_id'])['state'] == 'prepared'


@pytest.mark.parametrize('options', [[], [{'id': 'mention-option-a-0', 'name': 'other'}], [{'id': 'mention-option-a-0', 'name': 'hardscope'}, {'id': 'mention-option-a-1', 'name': 'hardscope'}]])
def test_failed_exact_selection_restores_text_and_marks_semantics_unverified(publisher, monkeypatch, options):
    class CaptionPage:
        text = 'Original text'
        def evaluate(self, script, argument=None):
            if script == module.CAPTION_TEXT_JS:return self.text
            if script == module.CAPTION_READY_JS:return True
            if script == module.CAPTION_OPTIONS_JS:return options
            raise AssertionError(script)
        def fill_framework_input(self, selector, text):self.text = text
        def type_text(self, text):self.text += text
        def get_by_role(self, *args, **kwargs):return SimpleNamespace(count=lambda: 1, click=lambda: self.type_text('@'))
        def locator(self, selector):pytest.fail('must never click a wrong or ambiguous option')
    page = CaptionPage()
    def once(page, predicate, message, seconds=60):
        result = predicate()
        if not result:raise StudioPublishError(message)
        return result
    monkeypatch.setattr(publisher, '_wait', once)
    with pytest.raises(StudioPublishError):publisher._set_caption(page, policy() | {'caption': '@hardscope'})
    assert page.text == 'Original text' and publisher._caption_semantic_rollback_unverified is True


# Rows captured live 2026-10-06: typing #CHLOEexplains lists the one challenge twice.
CHLOE_ROWS = [{'id': 'mention-option-af15k-0', 'label': '#CHLOEexplains\n400 posts', 'name': '#CHLOEexplains'},
              {'id': 'mention-option-af15k-1', 'label': '#CHLOEexplains\n400 posts', 'name': '#CHLOEexplains'},
              {'id': 'mention-option-af15k-2', 'label': '#monkeexplains\n141 posts', 'name': '#monkeexplains'}]
LYRICAL_ROWS = [{'id': 'mention-option-2icrq-0', 'label': 'Lyrical Lemonade\nlyricalemonade · 2.0M follower', 'name': 'lyricalemonade'},
                {'id': 'mention-option-2icrq-3', 'label': '_lyricallemonade_\n_lyricallemonade_1 · 2.6K follower', 'name': '_lyricallemonade_1'}]


def caption_page(options):
    class CaptionPage:
        text = ''
        def evaluate(self, script, argument=None):
            if script == module.CAPTION_TEXT_JS:return self.text
            if script == module.CAPTION_READY_JS:return True
            if script == module.CAPTION_OPTIONS_JS:return options
            raise AssertionError(script)
        def fill_framework_input(self, selector, text):self.text = text
        def type_text(self, text):self.text += text
        def get_by_role(self, role, name, exact):return SimpleNamespace(count=lambda: 1, click=lambda: self.type_text('@' if name == 'Mention' else '#'))
    return CaptionPage()


def once(page, predicate, message, seconds=60):
    result = predicate()
    if not result:raise StudioPublishError(message)
    return result


def test_identical_duplicate_hashtag_rows_select_the_first_native_row(publisher, monkeypatch):
    chosen = []
    def select(page, saved, option, kind, text, prefix):
        chosen.append((option['id'], kind, text, prefix))
        raise StudioPublishError('stop after selection')
    monkeypatch.setattr(publisher, '_wait', once)
    monkeypatch.setattr(publisher, '_select_caption_option', select)
    with pytest.raises(StudioPublishError, match='stop after selection'):
        publisher._set_caption(caption_page(CHLOE_ROWS), policy() | {'caption': '#CHLOEexplains test'})
    assert chosen == [('mention-option-af15k-0', 'hashtag', '#CHLOEexplains', '#CHLOEexplains')]


@pytest.mark.parametrize('caption,options', [
    ('#CHLOEexplains', [CHLOE_ROWS[0], CHLOE_ROWS[1] | {'label': '#CHLOEexplains\n7 posts'}]),
    ('#CHLOEexplains', [{k: v for k, v in row.items() if k != 'label'} for row in CHLOE_ROWS[:2]]),
    ('@hardscope', [{'id': 'mention-option-a-0', 'label': 'same', 'name': 'hardscope'}, {'id': 'mention-option-a-1', 'label': 'same', 'name': 'hardscope'}])])
def test_distinguishable_or_mention_duplicates_stay_ambiguous(publisher, monkeypatch, caption, options):
    monkeypatch.setattr(publisher, '_wait', once)
    monkeypatch.setattr(publisher, '_select_caption_option', lambda *args: pytest.fail('must never select an ambiguous row'))
    with pytest.raises(StudioPublishError, match='suggestion is ambiguous'):
        publisher._set_caption(caption_page(options), policy() | {'caption': caption})


def test_near_miss_handle_is_refused_and_named(publisher, monkeypatch):
    monkeypatch.setattr(publisher, '_wait', once)
    monkeypatch.setattr(publisher, '_select_caption_option', lambda *args: pytest.fail('must never select a near-miss handle'))
    with pytest.raises(StudioPublishError, match=r'suggestion is unavailable\. Studio offered no native mention named @lyricallemonade\.'):
        publisher._set_caption(caption_page(LYRICAL_ROWS), policy() | {'caption': '@lyricallemonade #CHLOEexplains test'})


def test_navigation_context_loss_still_persists_exact_native_acceptance(publisher, monkeypatch):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    page.click_error = True;page.network_after_click_error = True
    monkeypatch.setattr(publisher, '_reconcile', lambda operation: operation)
    original = page.evaluate
    def evaluate(script, argument=None):
        if script == module.RESTORE_JS:raise RuntimeError('renderer gone')
        return original(script, argument)
    page.evaluate = evaluate
    result = publisher.publish(value['request_id'], before_public_action=lambda binding: None)
    assert result['state'] == 'receipt_observed' and result['post_project_id'] == value['project_id']
    assert result['public_action_dispatched'] is True and result['network_observation']['state'] == 'accepted_response'
    assert result['observer_cleanup_issue']['recoverable'] is True and page.clicked == 1
    with pytest.raises(StudioPublishError, match='retry'):
        publisher.publish(value['request_id'], before_public_action=lambda binding: pytest.fail('no callback'))
    assert page.clicked == 1


def test_network_arming_failure_is_known_private_and_restores_guard(publisher, monkeypatch):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    page.begin_network_observation = lambda: (_ for _ in ()).throw(RuntimeError('unsupported'))
    with pytest.raises(StudioPublishError, match='armed'):
        publisher.publish(value['request_id'], before_public_action=lambda binding: pytest.fail('no callback'))
    assert page.clicked == 0 and page.restored
    assert publisher.status(value['request_id'])['state'] == 'prepared'


@pytest.mark.parametrize('change', ['creation', 'media', 'batch', 'caption', 'entities', 'multiple_items', 'project', 'not_object', 'duplicate', 'response_id', 'redirect', 'status', 'oversize', 'failed'])
def test_network_refuses_wrong_binding_duplicate_or_inconclusive_exchange(publisher, monkeypatch, change):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    original = page.network_observations
    def observations(*args, **kwargs):
        events = original(*args, **kwargs)
        if not events:return []
        body = json.loads(events[0]['body'])
        item = body['single_post_req_list'][0]
        if change == 'creation':body['post_common_info']['creation_id'] = 'different'
        elif change == 'media':item['video_id'] = 'different'
        elif change == 'batch':item['batch_index'] = True
        elif change == 'caption':item['single_post_feature_info']['text'] += 'other'
        elif change == 'entities':item['single_post_feature_info']['text_extra'] = []
        elif change == 'multiple_items':body['single_post_req_list'].append(dict(item))
        elif change == 'project':body['post_common_info']['project_id'] = '123'
        elif change == 'not_object':body = []
        elif change == 'duplicate':events.insert(1, dict(events[0]))
        elif change == 'response_id':events[1]['request_id'] = 'different'
        elif change == 'redirect':events[1]['route_matches'] = False
        elif change == 'status':events[1]['status'] = 503
        elif change == 'oversize':events[2]['encoded_bytes'] = 1_000_001
        elif change == 'failed':events[2]['kind'] = 'failed'
        events[0]['body'] = json.dumps(body)
        return events
    page.network_observations = observations
    with pytest.raises(StudioPublishError) as error:
        publisher.publish(value['request_id'], before_public_action=lambda binding: None)
    assert error.value.category == 'ambiguous_post_action'
    assert publisher.status(value['request_id'])['state'] == 'outcome_unknown' and page.clicked == 1
    with pytest.raises(StudioPublishError, match='retry'):
        publisher.publish(value['request_id'], before_public_action=lambda binding: pytest.fail('no callback'))


def test_late_response_uses_original_session_and_saves_request_before_response(publisher, monkeypatch):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    monkeypatch.setattr(publisher, '_reconcile', lambda operation: operation)
    original = page.network_observations;batches = []
    def observations(session, **kwargs):
        assert session == 'exact-session'
        if not page.clicked:return []
        if not batches:
            events = original(session, **kwargs);batches.extend([[], events[1:]])
            return events[:1]
        assert kwargs['request_ids'] == ('123.1',)
        saved = publisher.status(value['request_id'])
        assert saved['public_action_dispatched'] and saved['network_observation']['state'] == 'request_observed'
        return batches.pop(0)
    page.network_observations = observations
    result = publisher.publish(value['request_id'], before_public_action=lambda binding: None)
    assert result['state'] == 'receipt_observed' and page.clicked == 1


def test_crash_after_exact_request_observation_remains_reconcile_only(publisher, monkeypatch):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    save = publisher._save
    def crash(operation):
        save(operation)
        if operation.get('network_observation', {}).get('state') == 'request_observed':raise KeyboardInterrupt()
    monkeypatch.setattr(publisher, '_save', crash)
    with pytest.raises(KeyboardInterrupt):
        publisher.publish(value['request_id'], before_public_action=lambda binding: None)
    saved = publisher.status(value['request_id'])
    assert saved['state'] == 'outcome_unknown' and saved['public_action_dispatched'] is True
    assert saved['network_observation']['request_id'] == '123.1'
    assert publisher.reconcile(value['request_id'])['reconciliation'] == 'inconclusive_no_exact_receipt_id'
    with pytest.raises(StudioPublishError, match='retry'):
        publisher.publish(value['request_id'], before_public_action=lambda binding: pytest.fail('no callback'))


def test_background_refresh_is_after_slow_callback_before_post(publisher, monkeypatch):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    monkeypatch.setattr(publisher, '_reconcile', lambda operation: operation)
    original = page.network_observations
    def observations(*args, **kwargs):
        if not page.clicked:
            assert page.events[-1] == 'callback'
            page.events.append('refresh')
        return original(*args, **kwargs)
    page.network_observations = observations
    publisher.publish(value['request_id'], before_public_action=lambda binding: page.events.append('callback'))
    assert page.events[-3:] == ['callback', 'refresh', 'Post']


def test_unexpected_request_before_click_refuses_public_action(publisher, monkeypatch):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    page.network_observations = lambda *args, **kwargs: [{'kind': 'request', 'request_id': 'unexpected', 'body': '{}'}]
    with pytest.raises(StudioPublishError):publisher.publish(value['request_id'], before_public_action=lambda binding: None)
    assert page.clicked == 0
    saved = publisher.status(value['request_id'])
    assert saved['state'] == 'outcome_unknown' and saved['network_observation']['state'] == 'unexpected_pre_dispatch_exchange'


def test_inconclusive_refresh_never_posts_or_accepts_receipt(publisher, monkeypatch):
    """Measured on adam-server 2026-10-07: another process quit Chrome while the
    trusted callback ran, so the pre-click refresh failed with Post never clicked.
    The draft stays resumable instead of being stranded as outcome_unknown."""
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    monkeypatch.setattr(publisher, "_reconcile", lambda v: v)
    original = page.network_observations
    def observations(*args, **kwargs):raise RuntimeError('buffer overflow')
    page.network_observations = observations
    with pytest.raises(StudioPublishError) as error:publisher.publish(value['request_id'], before_public_action=lambda binding: None)
    saved = publisher.status(value['request_id'])
    assert page.clicked == 0 and 'post_project_id' not in saved and error.value.category == 'pre_action_abort'
    assert saved['state'] == 'prepared' and saved['resume_requires_owned_draft'] is True
    assert saved['post_failure'] == {'stage': 'native_observation_refresh', 'error_type': 'RuntimeError'}
    # The retry posts exactly once and keeps the earlier failure as history.
    page.network_observations = original
    publisher.publish(value['request_id'], before_public_action=lambda binding: None)
    saved = publisher.status(value['request_id'])
    assert page.clicked == 1 and saved['public_action_dispatched'] is True and 'post_failure' not in saved
    assert saved['post_failure_history'] == [{'stage': 'native_observation_refresh', 'error_type': 'RuntimeError'}]


def test_a_draft_gone_after_a_failed_pre_click_attempt_is_never_rebuilt(publisher, monkeypatch):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    def observations(*args, **kwargs):raise RuntimeError('browser closed')
    page.network_observations = observations
    with pytest.raises(StudioPublishError):publisher.publish(value['request_id'], before_public_action=lambda binding: None)
    page.rows.clear()
    with pytest.raises(StudioPublishError) as error:publisher._ready_editor(publisher.status(value['request_id']))
    saved = publisher.status(value['request_id'])
    # Nothing was sent, so the attempt ends unposted; it is never rebuilt or re-uploaded.
    assert error.value.category == 'unsent_draft_gone' and str(error.value) == module.UNSENT_DRAFT_GONE
    assert page.clicked == 0 and saved['state'] == 'prepared' and saved['public_action_dispatched'] is False
    assert saved['resume_draft_missing_at'] and not any(e in page.events for e in ('Continue', 'Post'))


def test_post_waits_for_studio_checks_so_post_is_not_held_by_the_confirmation(publisher, monkeypatch):
    """Measured on adam-server 2026-10-07: Post clicked while Content check lite
    was running opened "Continue to post?" and sent nothing."""
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    monkeypatch.setattr(publisher, "_reconcile", lambda v: v)
    page.checks = [CHECKS_RUNNING, CHECKS_RUNNING, CHECKS_PASSED]
    publisher.publish(value['request_id'], before_public_action=lambda binding: None)
    saved = publisher.status(value['request_id'])
    assert page.events.count('checks') == 3 and page.events.index('checks') < page.events.index('Post')
    assert saved['studio_checks'] | {'waited_seconds': 0} == {'status': 'completed', 'verdict': 'pass', 'music_status': studio_check.MUSIC_DONE,
                                                            'music_verdict': 'no_issue', 'waited_seconds': 0}


@pytest.mark.parametrize('checks, message', [
    ({**CHECKS_PASSED, 'lite': {'checkStatus': 2, 'checkResult': [{'model_type': 0, 'model_check_result': 1}]}}, 'did not pass'),
    ({**CHECKS_PASSED, 'music': {'code': 2}}, 'music copyright'),
])
def test_studio_check_failure_never_posts(publisher, monkeypatch, checks, message):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    page.checks = [checks]
    with pytest.raises(StudioPublishError, match=message) as error:
        publisher.publish(value['request_id'], before_public_action=lambda binding: pytest.fail('callback must not run'))
    assert error.value.category == 'pre_action_abort' and page.clicked == 0
    assert publisher.status(value['request_id'])['state'] == 'prepared'


def test_unfinished_studio_checks_never_post(publisher, monkeypatch):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    page.checks = [CHECKS_RUNNING]
    monkeypatch.setattr(module, 'STUDIO_CHECK_WAIT_SECONDS', 0)
    with pytest.raises(StudioPublishError, match='did not finish') as error:
        publisher.publish(value['request_id'], before_public_action=lambda binding: pytest.fail('callback must not run'))
    assert error.value.category == 'pre_action_abort' and page.clicked == 0
    assert publisher.status(value['request_id'])['state'] == 'prepared'


def test_click_held_by_studio_confirmation_is_proven_unsent_and_resumable(publisher, monkeypatch):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    page.confirmation_on_click = True
    clock = [0.0];monkeypatch.setattr(module.time, 'monotonic', lambda: clock.__setitem__(0, clock[0] + 1) or clock[0])
    monkeypatch.setattr(module.time, 'sleep', lambda seconds: None)
    with pytest.raises(StudioPublishError) as error:
        publisher.publish(value['request_id'], before_public_action=lambda binding: None)
    saved = publisher.status(value['request_id'])
    assert page.clicked == 1 and error.value.category == 'pre_action_abort'
    assert saved['post_failure']['stage'] == 'post_receipt_read' and saved['post_click_dialogs'] == [CONFIRMATION]
    assert saved['post_confirmation_pending']['dialog'] == CONFIRMATION and module.never_dispatched(saved)
    assert saved['state'] == 'prepared' and saved['resume_requires_owned_draft'] is True


def test_click_with_no_request_and_no_confirmation_stays_unknown(publisher, monkeypatch):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    page.network_observations = lambda *args, **kwargs: []
    clock = [0.0];monkeypatch.setattr(module.time, 'monotonic', lambda: clock.__setitem__(0, clock[0] + 1) or clock[0])
    monkeypatch.setattr(module.time, 'sleep', lambda seconds: None)
    with pytest.raises(StudioPublishError) as error:
        publisher.publish(value['request_id'], before_public_action=lambda binding: None)
    saved = publisher.status(value['request_id'])
    assert error.value.category == 'ambiguous_post_action' and saved['state'] == 'outcome_unknown'
    assert saved['post_click_dialogs'] == [] and not module.never_dispatched(saved)


def test_banner_continue_resumes_the_one_unlocked_owned_draft_beside_locked_rows(publisher, monkeypatch):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    page.rows.append(draft(value, draft_id='LOCKED', creation_id='LOCKED', file_key='old', video_id='old', is_locked=True))
    caption = [0]
    original = page.locator
    def locator(selector):
        if selector == module.CAPTION_SELECTOR:
            return SimpleNamespace(count=lambda: caption[0])
        return original(selector)
    page.locator = locator
    page.get_by_role = lambda role, **kwargs: SimpleNamespace(click=lambda: (page.events.append('Continue'), caption.__setitem__(0, 1)))
    publisher._ready_editor(value)
    assert 'Continue' in page.events


def test_a_record_journalled_unknown_before_its_click_is_resumed_by_prepare(publisher, monkeypatch, tmp_path):
    value = prepared(publisher, state='outcome_unknown', network_observation={'state': 'armed', 'request_count': 0},
                     post_failure={'stage': 'native_observation_refresh', 'error_type': 'BrowserHarnessError'})
    page = attach(publisher, value, monkeypatch)
    source = tmp_path / 'clip.mp4';source.write_bytes(b'known-mp4-bytes')
    result = publisher.prepare(source, value['policy'], value['request_id'])
    assert result['state'] == 'prepared' and result['resume_requires_owned_draft'] is True and page.clicked == 0


@pytest.mark.parametrize('change', [{'network_observation': {'state': 'unexpected_pre_dispatch_exchange', 'request_count': 0}},
                                    {'post_failure': {'stage': 'post_receipt_read', 'error_type': 'StudioPublishError'}},
                                    {'post_failure': {'stage': 'post_receipt_read', 'error_type': 'StudioPublishError'},
                                     'post_confirmation_pending': {'dialog': 'Discard this post?'}},
                                    {'post_failure': {'stage': 'native_post_action', 'error_type': 'RuntimeError'}},
                                    {'post_action_issue': {'error_type': 'RuntimeError', 'recoverable': True}},
                                    {'post_project_id': '555'}, {'public_action_dispatched': True}])
def test_any_sign_of_a_click_or_exchange_is_not_never_dispatched(change):
    base = {'public_action_dispatched': False, 'network_observation': {'state': 'armed', 'request_count': 0},
            'post_failure': {'stage': 'native_observation_refresh', 'error_type': 'BrowserHarnessError'}}
    assert module.never_dispatched(base) is True and module.never_dispatched({**base, **change}) is False


def test_expired_deadline_after_drain_never_clicks_and_remains_private(publisher, monkeypatch):
    value=prepared(publisher);page=attach(publisher,value,monkeypatch)
    now=[1000.0];monkeypatch.setattr(module.time,'time',lambda:now[0])
    def observations(*args,**kwargs):now[0]=1006;return []
    page.network_observations=observations
    with pytest.raises(StudioPublishError) as error:
        publisher.publish(value['request_id'],before_public_action=lambda binding:{'dispatch_deadline':1005.0})
    assert error.value.category=='pre_action_abort' and page.clicked==0
    assert publisher.status(value['request_id'])['state']=='prepared'


def test_native_guard_rejects_send_delayed_past_trusted_deadline():
    import subprocess
    script="""
    global.window={};global.location={href:'https://www.tiktok.com/tiktokstudio/upload'};
    let sends=0,aborts=0,now=1000000;Date.now=()=>now;
    class XHR{open(){} send(){sends++} abort(){aborts++}}global.XMLHttpRequest=XHR;
    const install=OBSERVER,setDeadline=DEADLINE;
    install({key:'owned',path:'/tiktok/web/project/post/v1/',creation_id:'OWNED',video_id:'VIDEO',caption:'CAPTION',caption_text_extra:[]});
    setDeadline({key:'owned',deadline:1005});now=1005000;
    const xhr=new XHR();xhr.open('POST','/tiktok/web/project/post/v1/');
    try{xhr.send(JSON.stringify({post_common_info:{creation_id:'OWNED',enter_post_page_from:1,post_type:2},single_post_req_list:[{video_id:'VIDEO',batch_index:0,single_post_feature_info:{text:'CAPTION',text_extra:[]}}]}))}catch(_){}
    if(sends!==0||aborts!==1)throw Error('expired send');console.log('EXPIRED_ZERO_SENDS');
    """.replace('OBSERVER','('+module.OBSERVER_JS+')').replace('DEADLINE','('+module.DEADLINE_JS+')')
    result=subprocess.run(['node','-e',script],capture_output=True,text=True,check=True)
    assert result.stdout.strip()=='EXPIRED_ZERO_SENDS'


@pytest.mark.parametrize('authorization', [{'dispatch_deadline':True},{'dispatch_deadline':float('inf')},{'dispatch_deadline':1000,'other':True},{}])
def test_invalid_trusted_deadline_remains_known_private(publisher,monkeypatch,authorization):
    value=prepared(publisher);page=attach(publisher,value,monkeypatch)
    with pytest.raises(StudioPublishError) as error:
        publisher.publish(value['request_id'],before_public_action=lambda binding:authorization)
    assert error.value.category=='pre_action_abort' and page.clicked==0
    assert publisher.status(value['request_id'])['state']=='prepared'


def test_crash_after_native_acceptance_retains_project_receipt_before_optional_item(publisher,monkeypatch):
    value=prepared(publisher);page=attach(publisher,value,monkeypatch)
    save=publisher._save
    def crash(operation):
        save(operation)
        if operation.get('network_observation',{}).get('state')=='accepted_response':raise KeyboardInterrupt()
    monkeypatch.setattr(publisher,'_save',crash)
    with pytest.raises(KeyboardInterrupt):
        publisher.publish(value['request_id'],before_public_action=lambda binding:None)
    saved=publisher.status(value['request_id'])
    assert saved['state']=='project_accepted' and saved['post_project_id']==value['project_id']
    assert 'item_id' not in saved and saved['public_action_dispatched'] is True
    with pytest.raises(StudioPublishError,match='retry'):
        publisher.publish(value['request_id'],before_public_action=lambda binding:pytest.fail('no callback'))
    assert page.clicked==1


def test_editor_changed_after_authority_callback_aborts_without_post(publisher, monkeypatch):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    original = page.evaluate
    changed = False
    def evaluate(script, argument=None):
        if script == module.EDITOR_STATE_JS and changed:
            state = editor_state(page.rows[0]);state['project']['creationId'] = 'OTHER_EDITOR';return state
        return original(script, argument)
    page.evaluate = evaluate
    def authorize(binding):
        nonlocal changed
        changed = True
    with pytest.raises(StudioPublishError, match='before dispatch'):
        publisher.publish(value['request_id'], before_public_action=authorize)
    assert page.clicked == 0
    assert publisher.status(value['request_id'])['state'] == 'prepared'


@pytest.mark.parametrize('missing', ['draft_id', 'draft_type', 'draft_resumed_from'])
def test_missing_native_context_fields_are_not_fresh_defaults(publisher, missing):
    state = fresh_state();del state[missing]
    with pytest.raises(StudioPublishError):
        publisher._fresh_entry(SimpleNamespace(evaluate=lambda script: state), [])


@pytest.mark.parametrize('state', [None, {}, {'pressed': True, 'released': False, 'blocked': False, 'expired': False}, {'pressed': True, 'released': True, 'blocked': True, 'expired': False}, {'pressed': True, 'released': True, 'blocked': False, 'expired': True}])
def test_caption_gesture_requires_exact_complete_guard_receipt(publisher, monkeypatch, state):
    monkeypatch.setattr(publisher, '_verify_editor', lambda *a: {'exact': True})
    calls = []
    def evaluate(script, value):
        calls.append(script)
        return True if script == module.CAPTION_SELECTION_JS else state
    page = SimpleNamespace(evaluate=evaluate, click_native=lambda selector: calls.append(selector))
    with pytest.raises(StudioPublishError, match='changed before native'):
        publisher._select_caption_option(page, {}, {'id': 'mention-option-x-0'}, 'hashtag', '#ad', '#ad')
    assert calls[-1] == module.CAPTION_SELECTION_DONE_JS


def test_caption_gesture_cleanup_preserves_primary_click_failure(publisher, monkeypatch):
    monkeypatch.setattr(publisher, '_verify_editor', lambda *a: {})
    calls = []
    def evaluate(script, value):
        calls.append(script)
        if script == module.CAPTION_SELECTION_JS:return True
        raise RuntimeError('cleanup')
    page = SimpleNamespace(evaluate=evaluate, click_native=lambda *a: (_ for _ in ()).throw(ValueError('primary')))
    with pytest.raises(ValueError, match='primary'):
        publisher._select_caption_option(page, {}, {'id': 'mention-option-x-0'}, 'hashtag', '#ad', '#ad')
    assert calls[-1] == module.CAPTION_SELECTION_DONE_JS


def test_caption_gesture_cleanup_failure_denies_success(publisher, monkeypatch):
    monkeypatch.setattr(publisher, '_verify_editor', lambda *a: {})
    def evaluate(script, value):
        if script == module.CAPTION_SELECTION_JS:return True
        raise RuntimeError('cleanup')
    page = SimpleNamespace(evaluate=evaluate, click_native=lambda *a: None)
    with pytest.raises(StudioPublishError, match='cleanup is unverified'):
        publisher._select_caption_option(page, {}, {'id': 'mention-option-x-0'}, 'hashtag', '#ad', '#ad')



def test_native_resume_waits_for_exact_hydrated_file_context(publisher, monkeypatch):
    value = prepared(publisher)
    checks = []
    monkeypatch.setattr(publisher, '_drafts', lambda *a: [value['draft']])
    def verify(page, row):
        checks.append(row)
        if len(checks) == 1:raise StudioPublishError('Studio native editor file context is ambiguous.')
        return {}
    monkeypatch.setattr(publisher, '_verify_editor', verify)
    def wait(page, predicate, message, seconds):
        assert predicate() is None
        return predicate()
    monkeypatch.setattr(publisher, '_wait', wait)
    assert publisher._wait_owned_editor(None, value) == value['draft']
    assert len(checks) == 2


def test_native_resume_retains_exact_failure_when_hydration_never_verifies(publisher, monkeypatch):
    value = prepared(publisher)
    changed = value['draft'] | {'video_id': 'wrong'}
    monkeypatch.setattr(publisher, '_drafts', lambda *a: [changed])
    monkeypatch.setattr(publisher, '_verify_editor', lambda *a: pytest.fail('wrong media must never reach editor acceptance'))
    def wait(page, predicate, message, seconds):
        assert predicate() is None
        raise StudioPublishError(message)
    monkeypatch.setattr(publisher, '_wait', wait)
    with pytest.raises(StudioPublishError, match='media binding changed'):
        publisher._wait_owned_editor(None, value)


def test_native_local_resume_same_key_twice_is_single_owned_post(publisher):
    value = prepared(publisher); state = editor_state(value['draft'])
    state.update(draft_type='local', draft_resumed_from='local', file_keys=[value['draft']['file_key']]*2)
    assert publisher._verify_editor(SimpleNamespace(evaluate=lambda script: state), value['draft']) == state


@pytest.mark.parametrize('change', [
    {'draft_type': None}, {'draft_resumed_from': None},
    {'file_keys': ['file', 'foreign']}, {'file_keys': ['file']*3},
    {'caption_state_count': 2}, {'caption_state_count': 0}, {'caption_state_count': True},
])
def test_native_local_resume_duplicate_key_rejects_other_or_batch_context(publisher, change):
    value = prepared(publisher); state = editor_state(value['draft'])
    state.update(draft_type='local', draft_resumed_from='local', file_keys=[value['draft']['file_key']]*2)
    state.update(change)
    with pytest.raises(StudioPublishError):
        publisher._verify_editor(SimpleNamespace(evaluate=lambda script: state), value['draft'])


@pytest.mark.parametrize("environment", [
    {"user_agent": HEADED_UA.replace("Chrome/155", "HeadlessChrome/155"), "webdriver": False, "screen": [800, 600]},
    {"user_agent": HEADED_UA, "webdriver": True, "screen": [1920, 1080]},
    None,
])
def test_headless_or_automated_browser_never_posts_and_stays_prepared(publisher, monkeypatch, environment):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    page.environment = environment
    with pytest.raises(StudioPublishError, match="headless or automated") as error:
        publisher.publish(value["request_id"], before_public_action=lambda binding: pytest.fail("callback must not run"))
    assert error.value.category == "pre_action_abort" and page.clicked == 0
    after = publisher.status(value["request_id"])
    assert after["state"] == "prepared" and after["public_action_dispatched"] is False
    assert after["browser_environment"] == environment


def test_headed_browser_environment_and_native_receipt_are_journaled(publisher, monkeypatch):
    value = prepared(publisher);page = attach(publisher, value, monkeypatch)
    monkeypatch.setattr(publisher, "_reconcile", lambda v: v)
    publisher.publish(value["request_id"], before_public_action=lambda binding: None)
    after = publisher.status(value["request_id"])
    assert after["browser_environment"]["user_agent"] == HEADED_UA
    assert json.loads(after["network_observation"]["response_body"]) == page.receipt
    assert json.loads(after["network_observation"]["request_body"]) == page.native_request()
    assert after["state"] == "receipt_observed" and page.clicked == 1


def test_posting_browser_is_visible_chrome_and_reads_stay_headless():
    from tiktok_cli.browser import StudioPostingBrowser, TiktokBrowser
    from tiktok_cli.config import Config
    config = SimpleNamespace(headless=True)
    assert StudioPostingBrowser(config)._headless_enabled() is False
    assert TiktokBrowser(config)._headless_enabled() is True
    assert type(Config.get_browser(config, posting=True)) is StudioPostingBrowser
    assert type(Config.get_browser(config)) is TiktokBrowser


def test_standalone_reconcile_reads_headless_while_posting_opens_visible_chrome(publisher, monkeypatch):
    value = prepared(publisher, state="project_accepted", public_action_dispatched=True, post_project_id="555666777")
    pages = []
    monkeypatch.setattr(publisher, "_page", lambda: pages.append(publisher.browser.posting) or SimpleNamespace())
    monkeypatch.setattr(publisher, "_identity", lambda *args: value["actor"])
    monkeypatch.setattr(publisher.client, "_fetch_json", lambda *args: {"status_code": 0, "project_status": 1, "task_list": [{"task_status": 1}]})
    assert publisher.reconcile(value["request_id"])["state"] == "project_pending"
    assert pages == [False]
    opened = []
    browser = SimpleNamespace(get_page=lambda url: opened.append(url) or "editor", close=lambda: None)
    fresh = StudioPublisher(SimpleNamespace(**{**vars(publisher.config), "get_browser": lambda posting=False: opened.append(posting) or browser}))
    assert fresh._page() == "editor" and opened == [True, module.UPLOAD_URL]
    fresh.close()
