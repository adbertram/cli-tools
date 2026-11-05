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
    def inspect(self, course_id, module_order):
        return self.state
    def resolve_course(self, title):
        return 123
    def refresh(self, state):
        return state
    def remote_matches(self, url, path):
        return self.matches
    def request(self, *args, **kwargs):
        self.calls.append(args)
        raise AssertionError('No mutation should occur')


@pytest.fixture
def submitted(tmp_path):
    deck = tmp_path / 'deck.pptx'; deck.write_bytes(b'deck')
    clip = tmp_path / 'clip.edited.mp4'; clip.write_bytes(b'video')
    manifest = {'course_title': 'Course', 'module_order': 1, 'module_title': 'Module',
                'deck_path': str(deck), 'clips': [{'record_id': 'rec1', 'title': 'Clip', 'path': str(clip)}]}
    state = {'course_title': 'Course', 'module': {'id': 1, 'guid': 'm1', 'index': 1, 'title': 'Module', 'status': 'submitted'},
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
        self.calls.append((method, url, kwargs))
        if '/module-assets' in url:
            self.state['assets'] = [{'id': 'd1', 'type': 'slides', 'status': 'done',
                                    'downloadRoute': '/module-assets/download/d1', 'fileName': 'deck.pptx'}]
        elif '/clip/' in url:
            self.state['clips'][0].update(kwargs['json'])
        elif '/submit-move-to-qa' in url or '/updates-submit-move-to-qa' in url:
            self.state['module']['status'] = 'updates_submitted' if 'updates-submit' in url else 'submitted'
        return {}
    def remote_matches(self, url, path):
        return self.deck_uploaded if str(path).endswith('.pptx') else self.video_uploaded
    def upload_video(self, path, module, existing=None, index=0):
        self.calls.append(('upload_video', existing is not None))
        self.video_uploaded = True
        self.state['clips'] = [{'id': 2, 'guid': 'c1', 'index': index, 'title': Path(path).name,
             'downloadLink': 'https://object.example/video', 'videoFile': {'originalVideoFileName': 'uuid_' + Path(path).name}}]
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
    rename = next(c for c in transport.calls if c[0] == 'POST' and '/clip/' in c[1])
    assert rename[2]['json']['title'] == 'Clip'
    assert rename[2]['json']['index'] == 0
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
    def matches(url, path):
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
