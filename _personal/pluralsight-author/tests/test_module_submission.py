import json
from pathlib import Path

import pytest
import requests
from cli_tools_shared.exceptions import ClientError
from pluralsight_author_cli.module_submission import ModuleSubmission, multipart


def test_multipart_streams_with_unambiguous_length(tmp_path):
    path = tmp_path / 'clip.edited.mp4'
    path.write_bytes(b'hello' * 300000)
    body, headers = multipart({'key': 'clips/test'}, path, 'file')
    request = requests.Request('POST', 'https://example.com', data=body, headers=headers).prepare()
    assert 'Transfer-Encoding' not in request.headers
    assert int(request.headers['Content-Length']) == sum(map(len, body))
    assert max(map(len, body)) <= 1024 * 1024


class FakeSubmission(ModuleSubmission):
    def __init__(self, state):
        self.state = state
        self.calls = []
        self.canonical = {c['guid']: c['title'] for c in state['clips']}
    def displayed_clips(self, course_id, module_id, clip_ids):
        return [{'id': c['id'], 'title': self.canonical[c['guid']], 'index': c['index']} for c in sorted(self.state['clips'], key=lambda c:c['index'])]
    def inspect(self, course_id, module_order):
        return self.state
    def resolve_course(self, title):
        return 123
    def refresh(self, state):
        return state
    def remote_matches(self, url, path, **kwargs):
        return self.matches
    def request(self, *args, **kwargs):
        if args[0] == 'GET':
            return {'title': self.canonical[args[1].rsplit('/', 1)[-1]]}
        self.calls.append(args)
        raise AssertionError('No mutation should occur')


@pytest.fixture
def submitted(tmp_path):
    deck = tmp_path / 'deck.pptx'; deck.write_bytes(b'deck')
    clip = tmp_path / 'clip.edited.mp4'; clip.write_bytes(b'video')
    manifest = {'course_title': 'Course', 'module_order': 1, 'module_title': 'Module',
                'deck_path': str(deck), 'clips': [{'record_id': 'rec1', 'title': 'Clip', 'path': str(clip)}]}
    state = {'course_id': 123, 'course_title': 'Course', 'module': {'id': 1, 'guid': 'm1', 'index': 1, 'title': 'Module', 'status': 'submitted'},
             'clips': [{'id': 2, 'guid': 'c1', 'index': 0, 'title': 'Clip', 'downloadLink': 'https://object.example/video',
                        'videoFile': {'originalVideoFileName': 'uuid_clip.edited.mp4'}}],
             'assets': [{'id': 'd1', 'type': 'slides', 'status': 'done', 'downloadRoute': '/module-assets/download/d1', 'fileName': 'deck.pptx'}]}
    transport = FakeSubmission(state); transport.matches = True
    return transport, manifest


def test_already_submitted_reuses_only_verified_bytes(submitted):
    transport, manifest = submitted
    result = transport.submit(manifest)
    assert result['already_submitted'] is True
    assert result['course_title'] == 'Course'
    assert result['module_order'] == 1
    assert result['clips'][0]['record_id'] == 'rec1'
    assert not transport.calls


def test_changed_bytes_never_mutate_submitted_module(submitted):
    transport, manifest = submitted; transport.matches = False
    with pytest.raises(ClientError, match='differs from current bytes'):
        transport.submit(manifest)
    assert not transport.calls


def test_wrong_destination_never_mutates(submitted):
    transport, manifest = submitted; manifest['module_title'] = 'Other'
    with pytest.raises(ClientError, match='title differs'):
        transport.submit(manifest)
    assert not transport.calls


def test_raw_media_rejected_before_contact(submitted):
    transport, manifest = submitted
    manifest['clips'][0]['path'] = manifest['deck_path']
    with pytest.raises(ClientError, match='edited.mp4'):
        transport.submit(manifest)
    assert not transport.calls


def test_external_download_never_gets_authorization(tmp_path, monkeypatch):
    path = tmp_path / 'v'; path.write_bytes(b'video')
    class Response:
        ok = True
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_content(self, size): yield b'video'
    calls = []
    monkeypatch.setattr(requests, 'get', lambda url, **kw: calls.append(kw) or Response())
    transport = object.__new__(ModuleSubmission)
    transport.session = requests.Session(); transport.session.headers['Authorization'] = 'private'
    assert transport.remote_matches('https://s3.example/video?signed=1', path)
    assert 'headers' not in calls[0]


class UpdatingSubmission(FakeSubmission):
    def request(self, method, url, **kwargs):
        if method == 'GET':
            return {'title': self.canonical[url.rsplit('/', 1)[-1]]}
        self.calls.append((method, url, kwargs))
        if '/module-assets' in url:
            self.state['assets'] = [{'id': 'd1', 'type': 'slides', 'status': 'done',
                                    'downloadRoute': '/module-assets/download/d1', 'fileName': 'deck.pptx'}]
        elif '/clip/' in url:
            self.state['clips'][0].update(kwargs['json'])
            self.canonical[self.state['clips'][0]['guid']] = kwargs['json']['title']
        elif '/submit-move-to-qa' in url or '/updates-submit-move-to-qa' in url:
            self.state['module']['status'] = 'updates_submitted' if 'updates-submit' in url else 'submitted'
        return {'id': 'd1'}
    def remote_matches(self, url, path, **kwargs):
        return self.deck_uploaded if str(path).endswith('.pptx') else self.video_uploaded
    def upload_video(self, path, module, existing=None, index=0):
        self.calls.append(('upload_video', existing is not None))
        self.video_uploaded = True
        self.state['clips'] = [{'id': 2, 'guid': 'c1', 'index': index, 'title': Path(path).name,
             'downloadLink': 'https://object.example/video', 'videoFile': {'originalVideoFileName': 'uuid_' + Path(path).name}}]
        self.canonical['c1'] = Path(path).name
        return 'c1'
    def refresh(self, state):
        if state['assets']:
            self.deck_uploaded = True
        return state


@pytest.mark.parametrize('status,existing,action', [
    ('in_progress', False, 'submit-move-to-qa'),
    ('updates_required', True, 'updates-submit-move-to-qa'),
])
def test_new_and_revised_submission_upload_then_rename_then_submit(submitted, status, existing, action):
    old, manifest = submitted
    old.state['module']['status'] = status
    old.state['assets'] = []
    if not existing:
        old.state['clips'] = []
    transport = UpdatingSubmission(old.state)
    transport.deck_uploaded = False; transport.video_uploaded = False
    # The multipart deck upload completes before clip processing begins.
    original_request = transport.request
    def request(method, url, **kwargs):
        result = original_request(method, url, **kwargs)
        if '/module-assets' in url: transport.deck_uploaded = True
        return result
    transport.request = request
    result = transport.submit(manifest)
    assert result['ok'] and not result['already_submitted']
    assert transport.calls[0][0] == 'POST' and '/module-assets' in transport.calls[0][1]
    assert ('upload_video', existing) in transport.calls
    rename = next(c for c in transport.calls if c[0] == 'PUT' and '/v1/clip/' in c[1])
    assert rename[2]['json']['title'] == 'Clip'
    assert rename[2]['json'] == {'title': 'Clip'}
    assert transport.calls[-1][1].endswith('/' + action)


def test_video_upload_uses_proven_signature_and_create_contract(tmp_path, monkeypatch):
    path = tmp_path / 'clip.edited.mp4'; path.write_bytes(b'video')
    transport = object.__new__(ModuleSubmission)
    calls = []
    signature = {'key': 'clips/x', 'credential': 'cred', 'date': 'date', 'signature': 'sig',
                 'policy': 'policy', 'guid': 'upload-guid', 'bucket': 'https://bucket.example/'}
    transport.request = lambda method, url, **kw: calls.append((method, url, kw)) or (signature if url.endswith('/signature') else {'guid': 'created-guid'})
    class Response: ok = True
    uploads = []
    monkeypatch.setattr(requests, 'post', lambda url, **kw: uploads.append((url, kw)) or Response())
    transport.upload_video(path, {'guid': 'module-guid'}, index=2)
    assert calls[0][2]['json'] == {'originalFileName': path.name}
    assert calls[1][2]['json'] == {'uploadGuid': 'upload-guid', 'originalFileName': path.name, 'moduleGuid': 'module-guid', 'order': 2}
    assert calls[1][1].endswith('/v2/clip')
    assert uploads[0][0] == signature['bucket']
    assert 'Authorization' not in uploads[0][1]['headers']
    transport.upload_video(path, {'guid': 'module-guid'}, existing={'guid': 'existing-guid'})
    assert calls[-1][0] == 'PUT' and calls[-1][1].endswith('/v1/clip/existing-guid/video')


def test_failed_video_upload_never_creates_clip(tmp_path, monkeypatch):
    path = tmp_path / 'clip.edited.mp4'; path.write_bytes(b'video')
    transport = object.__new__(ModuleSubmission)
    calls = []
    signature = dict(key='k', credential='c', date='d', signature='s', policy='p', guid='g', bucket='https://bucket.example/')
    transport.request = lambda *args, **kw: calls.append(args) or signature
    class Response: ok = False; status_code = 503
    monkeypatch.setattr(requests, 'post', lambda *a, **kw: Response())
    with pytest.raises(ClientError, match='object upload failed'):
        transport.upload_video(path, {'guid': 'm'})
    assert len(calls) == 1


def test_replacement_waits_for_new_bytes_when_old_link_still_visible(submitted, monkeypatch):
    old, manifest = submitted
    old.state['module']['status'] = 'updates_required'
    transport = UpdatingSubmission(old.state)
    transport.deck_uploaded = True; transport.video_uploaded = False
    polls = []
    original_matches = transport.remote_matches
    def matches(url, path, **kwargs):
        if str(path).endswith('.mp4') and transport.video_uploaded:
            polls.append(url)
            if len(polls) < 3:
                return False
        return original_matches(url, path)
    transport.remote_matches = matches
    sleeps = []
    monkeypatch.setattr('pluralsight_author_cli.module_submission.time.sleep', sleeps.append)
    result = transport.submit(manifest)
    assert result['status'] == 'updates_submitted'
    assert len(sleeps) == 2
    assert len(polls) >= 3


def test_course_resolve_rejects_ambiguous_title():
    transport = object.__new__(ModuleSubmission)
    class Page:
        def wait_for_timeout(self, value): pass
        def evaluate(self, script, title):
            return ['/author-tools/details/1/modules', '/author-tools/details/2/modules']
    class Browser:
        def get_page(self, url): return Page()
    transport.browser = Browser()
    with pytest.raises(ClientError, match='exactly one'):
        transport.resolve_course('Duplicate')


def test_known_upload_404_is_pending_but_submitted_404_is_fatal(tmp_path, monkeypatch):
    path = tmp_path / 'clip.edited.mp4'; path.write_bytes(b'video')
    class Response:
        ok = False
        status_code = 404
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(requests, 'get', lambda *a, **kw: Response())
    transport = object.__new__(ModuleSubmission)
    transport.session = requests.Session()
    assert transport.remote_matches('https://storage.example/video-id', path, pending=True) is None
    with pytest.raises(ClientError, match='video-id.*HTTP 404'):
        transport.remote_matches('https://storage.example/video-id', path)


def test_partial_existing_download_waits_before_deciding_to_replace(tmp_path, monkeypatch):
    transport = object.__new__(ModuleSubmission)
    results = iter([None, None, True])
    transport.remote_matches = lambda *args, **kwargs: next(results)
    sleeps = []
    monkeypatch.setattr('pluralsight_author_cli.module_submission.time.sleep', sleeps.append)
    assert transport.existing_matches('https://storage.example/file', tmp_path / 'video', pending=True, identity='clip c1')
    assert sleeps == [2, 2]


def test_existing_other_deck_is_promoted_without_duplicate_upload(submitted):
    old, manifest = submitted
    old.state['module']['status'] = 'in_progress'
    old.state['assets'][0]['type'] = 'other'
    transport = UpdatingSubmission(old.state)
    transport.deck_uploaded = True; transport.video_uploaded = True
    result = transport.submit(manifest)
    assert result['ok'] and result['deck']['type'] == 'slides'
    asset_calls = [c for c in transport.calls if '/module-assets' in c[1]]
    assert len(asset_calls) == 1
    method, url, kwargs = asset_calls[0]
    assert method == 'PUT' and url.endswith('/module-assets/d1')
    assert kwargs == {'params': {'source': 'author-tools'}, 'json': {'type': 'slides'}}
    assert not any(c[0] == 'upload_video' for c in transport.calls)


def test_legacy_correct_title_does_not_allow_submit_when_authoritative_title_differs(submitted):
    old, manifest = submitted
    old.state['module']['status'] = 'in_progress'
    transport = UpdatingSubmission(old.state)
    transport.deck_uploaded = True; transport.video_uploaded = True
    # Independently stored authoritative service still has the generated title,
    # even though the legacy/module projection appears correctly renamed.
    transport.canonical['c1'] = 'Clip_video_generated.edited'
    with pytest.raises(ClientError, match='Authoritative Pluralsight clip c1 title'):
        transport.submit(manifest)
    assert not any('/submit-move-to-qa' in c[1] for c in transport.calls)


def test_actual_display_mismatch_blocks_irreversible_submit(submitted):
    old, manifest = submitted
    old.state['module']['status'] = 'in_progress'
    transport = UpdatingSubmission(old.state)
    transport.deck_uploaded = True; transport.video_uploaded = True
    transport.displayed_clips = lambda *args: [{'id': 2, 'title': 'Filename generated title', 'index': 0}]
    with pytest.raises(ClientError, match='Displayed Pluralsight'):
        transport.submit(manifest)
    assert not any('/submit-move-to-qa' in c[1] for c in transport.calls)


def test_post_submit_authoritative_change_never_returns_cached_success(submitted):
    old, manifest = submitted
    old.state['module']['status'] = 'in_progress'
    transport = UpdatingSubmission(old.state)
    transport.deck_uploaded = True; transport.video_uploaded = True
    original_request = transport.request
    def request(method, url, **kwargs):
        result = original_request(method, url, **kwargs)
        if '/submit-move-to-qa' in url:
            transport.canonical['c1'] = 'Generated title after submission'
        return result
    transport.request = request
    with pytest.raises(ClientError, match='Authoritative Pluralsight clip c1 title'):
        transport.submit(manifest)
    assert any('/submit-move-to-qa' in c[1] for c in transport.calls)


def test_display_extra_or_missing_rows_blocks_submit(submitted):
    old, manifest = submitted
    old.state['module']['status'] = 'in_progress'
    transport = UpdatingSubmission(old.state)
    transport.deck_uploaded = True; transport.video_uploaded = True
    transport.displayed_clips = lambda *args: []
    with pytest.raises(ClientError, match='Displayed Pluralsight'):
        transport.submit(manifest)
    assert not any('/submit-move-to-qa' in c[1] for c in transport.calls)


def test_shared_read_uses_per_guid_authority_over_correct_looking_module_projection():
    transport = object.__new__(ModuleSubmission)
    def request(method, url, **kwargs):
        assert method == 'GET'
        if '/module/' in url:
            return [{'guid': 'clip-guid', 'title': 'Expected canonical name', 'index': 0}]
        return {'guid': 'clip-guid', 'title': 'Actual generated filename title'}
    transport.request = request
    rows = transport.read_clips({'guid': 'module-guid'})
    assert rows[0]['title'] == 'Actual generated filename title'


def test_three_clip_final_pass_renames_both_generated_titles_before_submit(submitted, tmp_path):
    old, manifest = submitted
    names = ['First canonical title', 'Second canonical title', 'Third canonical title']
    manifest['clips'] = []
    old.state['module']['status'] = 'in_progress'
    old.state['clips'] = []
    for index, name in enumerate(names):
        path = tmp_path / f'clip{index}.edited.mp4'; path.write_bytes(b'video')
        manifest['clips'].append({'record_id': f'rec{index}', 'title': name, 'path': str(path)})
        old.state['clips'].append({'id': 10 + index, 'guid': f'guid{index}', 'index': index,
            'title': name if index == 0 else f'Generated filename {index}',
            'downloadLink': f'https://storage.example/{index}',
            'videoFile': {'originalVideoFileName': f'uuid_{path.name}'}})

    class ThreeClipService(FakeSubmission):
        def __init__(self, state):
            super().__init__(state)
            self.matches = True
            self.display_checks = []
        def refresh(self, state):
            # This independent store is read through service refreshes, not a
            # projection that echoes the previous request payload.
            for row in state['clips']:
                row['title'] = self.canonical[row['guid']]
            return state
        def request(self, method, url, **kwargs):
            if method == 'GET':
                guid = url.rsplit('/', 1)[-1]
                return {'guid': guid, 'title': self.canonical[guid]}
            self.calls.append((method, url, kwargs))
            if method == 'PUT' and '/content/api/v1/clip/' in url:
                self.canonical[url.rsplit('/', 1)[-1]] = kwargs['json']['title']
            elif method == 'POST' and url.endswith('/submit-move-to-qa'):
                assert [self.canonical[f'guid{i}'] for i in range(3)] == names
                assert self.display_checks[-1] == names
                self.state['module']['status'] = 'submitted'
            else:
                raise AssertionError('Unexpected mutation')
            return {}
        def displayed_clips(self, course_id, module_id, clip_ids):
            rows = super().displayed_clips(course_id, module_id, clip_ids)
            self.display_checks.append([r['title'] for r in rows])
            return rows

    service = ThreeClipService(old.state)
    result = service.submit(manifest)
    renames = [call for call in service.calls if call[0] == 'PUT']
    assert [(c[1].rsplit('/', 1)[-1], c[2]['json']) for c in renames] == [
        ('guid1', {'title': names[1]}), ('guid2', {'title': names[2]})]
    assert result['display_titles'] == names
    assert [r['title'] for r in result['clips']] == names
    assert service.display_checks == [names, names]
