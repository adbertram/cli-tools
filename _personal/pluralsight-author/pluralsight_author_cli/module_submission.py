"""Author Dashboard API transport, discovered from its production client."""
from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path

import requests
from cli_tools_shared.exceptions import ClientError
from .config import get_config

API = 'https://authortools-api.pluralsight.com/api/v1/'
CONTENT = 'https://app.pluralsight.com/content/api/'
ASSETS = 'https://assets-service.pluralsight.com/'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def source_name_matches(remote_name, path):
    name = Path(path).name
    return remote_name == name or remote_name.endswith('_' + name)


def multipart(fields, path, file_field):
    """Stream the media body without buffering a complete MP4 in memory."""
    boundary = uuid.uuid4().hex
    prefix = ''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in fields.items()).encode()
    prefix += (f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{path.name}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
    suffix = f'\r\n--{boundary}--\r\n'.encode()
    def chunks():
        yield prefix
        with path.open('rb') as file:
            yield from iter(lambda: file.read(1024 * 1024), b'')
        yield suffix
    class Body:
        def __iter__(self):
            return chunks()
        def __len__(self):
            return len(prefix) + path.stat().st_size + len(suffix)
    return Body(), {'Content-Type': f'multipart/form-data; boundary={boundary}',
                      'Content-Length': str(len(prefix) + path.stat().st_size + len(suffix))}


class ModuleSubmission:
    def __init__(self, profile=None):
        self.browser = get_config(profile).get_browser()
        self.session = requests.Session()
        self.course_id = None

    def close(self):
        self.browser.close()
        self.session.close()

    def connect(self, course_id):
        if not self.browser.is_authenticated().authenticated:
            raise ClientError('Pluralsight Author browser session is not authenticated.')
        self.course_id = int(course_id)
        p = self.browser.get_page(f'https://app.pluralsight.com/author-tools/details/{self.course_id}/modules')
        p.wait_for_timeout(1500)
        # Observe the SPA's own authenticated request; keep its bearer only in memory.
        p.evaluate('''() => {window.__psSubmitAuthorization=null;
          const original=XMLHttpRequest.prototype.setRequestHeader;
          XMLHttpRequest.prototype.setRequestHeader=function(k,v){
            if(k.toLowerCase()==='authorization')window.__psSubmitAuthorization=v;
            return original.call(this,k,v)};
          const link=document.querySelector('a[href="/author-tools/details/'+''' + str(self.course_id) + '''+'"]');
          if(!link)throw Error('Author Dashboard Details link missing');link.click();}''')
        for _ in range(30):
            token = p.evaluate('() => window.__psSubmitAuthorization')
            if token:
                self.session.headers['Authorization'] = token
                for cookie in self.browser.live_cookies():
                    self.session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'], path=cookie.get('path', '/'))
                return
            p.wait_for_timeout(200)
        raise ClientError('Author Dashboard did not issue an authenticated API request.')

    def resolve_course(self, title):
        p = self.browser.get_page('https://app.pluralsight.com/author-home')
        p.wait_for_timeout(2000)
        rows = p.evaluate("""(title) => {
          const found = [];
          for(const e of document.querySelectorAll('div')) {
            if(e.childElementCount || e.textContent.trim()!==title)continue;
            let fiber=e[Object.keys(e).find(k=>k.startsWith('__reactFiber'))];
            for(let i=0;i<20&&fiber;i++,fiber=fiber.return) {
              const props=fiber.memoizedProps;
              if(props?.title===title && typeof props.path==='string') {
                found.push(props.path);break;
              }
            }
          }
          return [...new Set(found)];
        }""", title)
        import re
        if len(rows) != 1 or not re.fullmatch(r'/author-tools/details/[0-9]+/modules', rows[0]):
            raise ClientError('Course title must match exactly one in-progress Author Home course.')
        return int(rows[0].split('/')[3])

    def request(self, method, url, **kwargs):
        response = self.session.request(method, url, timeout=300, **kwargs)
        if not response.ok:
            # Error bodies may contain credentials or signed URLs; never echo them.
            raise ClientError(f'Pluralsight API {method} failed (HTTP {response.status_code}).')
        return response.json() if response.content else None

    def inspect(self, course_id, module_order):
        self.connect(course_id)
        course = self.request('GET', API + f'course/{int(course_id)}')
        query = '{ courseModules(courseIndex: %d) { id guid title index status } }' % int(course_id)
        data = self.request('POST', CONTENT + 'graphql', json={'query': query})
        modules = data.get('data', {}).get('courseModules')
        if not isinstance(modules, list):
            raise ClientError('Author Dashboard returned no courseModules array.')
        matches = [m for m in modules if m['index'] == module_order]
        if len(matches) != 1:
            raise ClientError('Module order must identify exactly one Pluralsight module.')
        module = matches[0]
        return {'course_id': int(course_id), 'course_title': course['title'], 'module': module,
                'clips': self.request('GET', API + f'clip/module/{module["id"]}'),
                'assets': self.request('GET', ASSETS + f'module-assets/{module["id"]}')}

    def refresh(self, state):
        mid = state['module']['id']
        state['module'] = self.request('GET', API + f'module/{mid}')
        state['clips'] = self.request('GET', API + f'clip/module/{mid}')
        state['assets'] = self.request('GET', ASSETS + f'module-assets/{mid}')
        return state

    def remote_matches(self, url, path, *, pending=False):
        # Compare exact uploaded bytes, including manual uploads and same-name revisions.
        getter = self.session.get if url.startswith(ASSETS + 'module-assets/') else requests.get
        try:
            response = getter(url, stream=True, timeout=300)
        except requests.RequestException:
            raise ClientError('Pluralsight asset verification network request failed.') from None
        with response as r:
            if pending and r.status_code == 404:
                return None
            if not r.ok:
                from urllib.parse import urlsplit
                identity = urlsplit(url).path.rsplit('/', 1)[-1]
                raise ClientError(f'Pluralsight download verification for {identity} failed (HTTP {r.status_code}).')
            h = hashlib.sha256()
            for block in r.iter_content(1024 * 1024):
                h.update(block)
        return h.hexdigest() == digest(path)

    def existing_matches(self, url, path, *, pending, identity):
        for _ in range(120):
            result = self.remote_matches(url, path, pending=pending)
            if result is not None:
                return result
            time.sleep(2)
        raise ClientError(f'Pluralsight {identity} download is still pending after 240 seconds.')

    def upload_video(self, path, module, existing=None, index=0):
        path = Path(path)
        signature = self.request('POST', CONTENT + 'v2/signature', json={'originalFileName': path.name})
        required = {'key', 'credential', 'date', 'signature', 'policy', 'guid', 'bucket'}
        if not required <= signature.keys():
            raise ClientError('Incomplete Pluralsight S3 upload signature.')
        fields = {'key': signature['key'], 'x-amz-algorithm': 'AWS4-HMAC-SHA256',
                  'acl': 'public-read', 'x-amz-credential': signature['credential'],
                  'x-amz-date': signature['date'], 'policy': signature['policy'],
                  'x-amz-signature': signature['signature']}
        if signature.get('securityToken'):
            fields['x-amz-security-token'] = signature['securityToken']
        body, headers = multipart(fields, path, 'file')
        # Do not forward the Author Dashboard bearer to object storage.
        try:
            r = requests.post(signature['bucket'], data=body, headers=headers, timeout=1800)
        except requests.RequestException:
            raise ClientError('Pluralsight video object upload network request failed.') from None
        if not r.ok:
            raise ClientError(f'Pluralsight video object upload failed (HTTP {r.status_code}).')
        if existing:
            self.request('PUT', CONTENT + f'v1/clip/{existing["guid"]}/video',
                         json={'uploadGuid': signature['guid'], 'originalFileName': path.name})
            return existing['guid']
        else:
            created = self.request('POST', CONTENT + 'v2/clip', json={'uploadGuid': signature['guid'],
                'originalFileName': path.name, 'moduleGuid': module['guid'], 'order': index})
            if not isinstance(created, dict) or not created.get('guid'):
                raise ClientError('Pluralsight create clip returned no clip GUID.')
            return created['guid']

    def submit(self, manifest):
        required = {'course_title', 'module_order', 'module_title', 'deck_path', 'clips'}
        if not isinstance(manifest, dict) or not required <= manifest.keys():
            raise ClientError('Incomplete module submission manifest.')
        deck = Path(manifest['deck_path'])
        clips = manifest['clips']
        if not deck.is_file() or deck.suffix.lower() != '.pptx' or not clips:
            raise ClientError('Submission requires an existing PowerPoint deck and edited clips.')
        titles = [c['title'] for c in clips]
        if len(set(titles)) != len(titles):
            raise ClientError('Clip titles must be unique within the submitted module.')
        for clip in clips:
            path = Path(clip['path'])
            if not path.is_file() or not path.name.endswith('.edited.mp4') or not clip.get('record_id'):
                raise ClientError('Every clip requires its record ID and an existing .edited.mp4 file.')
        course_id = manifest.get('course_id') or self.resolve_course(manifest['course_title'])
        state = self.inspect(course_id, manifest['module_order'])
        if state['course_title'] != manifest['course_title'] or state['module']['title'] != manifest['module_title']:
            raise ClientError('Pluralsight course or module title differs from the submission manifest.')
        module = state['module']
        submitted = module['status'] in ('submitted', 'updates_submitted')
        if not submitted and module['status'] not in ('in_progress', 'updates_required', 'available_for_updates'):
            raise ClientError('Pluralsight module is not in an upload or resubmission state.')
        expected = set(titles)
        if any(c['title'] not in expected and not any(source_name_matches(c['videoFile']['originalVideoFileName'], x['path']) for x in clips) for c in state['clips']):
            raise ClientError('Pluralsight module contains clips outside the submission manifest.')
        decks = [a for a in state['assets'] if a['type'] == 'slides' or a['fileName'] == deck.name]
        if len(decks) > 1:
            raise ClientError('Pluralsight module has multiple slide decks; resolve before submission.')
        deck_ok = bool(decks and decks[0]['status'] == 'done' and self.existing_matches(ASSETS + decks[0]['downloadRoute'].lstrip('/'), deck, pending=not submitted, identity=f'deck {decks[0]["id"]}'))
        if deck_ok and decks[0]['type'] != 'slides':
            if submitted:
                raise ClientError('Submitted module deck has the wrong asset type.')
            self.request('PUT', ASSETS + f'module-assets/{decks[0]["id"]}',
                         params={'source': 'author-tools'}, json={'type': 'slides'})
        if not deck_ok:
            if submitted:
                raise ClientError('Submitted module deck differs from current bytes; cannot modify during review.')
            url = ASSETS + 'module-assets' + (f'/{decks[0]["id"]}' if decks else '')
            with deck.open('rb') as file:
                uploaded_deck = self.request('PUT' if decks else 'POST', url,
                    data={'moduleGuid': module['guid'], 'source': 'author-tools', 'type': 'slides'},
                    files={'uri': (deck.name, file)})
            if not isinstance(uploaded_deck, dict) or not uploaded_deck.get('id'):
                raise ClientError('Pluralsight deck upload returned no asset ID.')
            self.request('PUT', ASSETS + f'module-assets/{uploaded_deck["id"]}',
                         params={'source': 'author-tools'}, json={'type': 'slides'})
        for index, clip in enumerate(clips):
            matches = [c for c in state['clips'] if c['title'] == clip['title'] or source_name_matches(c['videoFile']['originalVideoFileName'], clip['path'])]
            if len(matches) > 1:
                raise ClientError('More than one portal clip matches a manifest clip.')
            existing = matches[0] if matches else None
            same = bool(existing and self.existing_matches(existing['downloadLink'], clip['path'],
                        pending=not submitted, identity=f'clip {existing["guid"]}'))
            if not same:
                if submitted:
                    raise ClientError('Submitted module video differs from current bytes; cannot modify during review.')
                uploaded_guid = self.upload_video(clip['path'], module, existing, index)
                for _ in range(120):
                    self.refresh(state)
                    matches = [c for c in state['clips'] if c['guid'] == uploaded_guid and c.get('downloadLink')]
                    if len(matches) == 1 and self.remote_matches(matches[0]['downloadLink'], clip['path'], pending=True):
                        break
                    time.sleep(2)
                if len(matches) != 1 or not self.remote_matches(matches[0]['downloadLink'], clip['path']):
                    raise ClientError('Uploaded clip content is not ready in Pluralsight readback.')
                existing = matches[0]
            if existing['title'] != clip['title'] or existing['index'] != index:
                if submitted:
                    raise ClientError('Submitted module clip title/order differs from manifest.')
                changed = dict(existing, title=clip['title'], index=index, moduleId=module['id'])
                self.request('POST', API + f'clip/{existing["id"]}', json=changed)
        for _ in range(120):
            self.refresh(state)
            ready_decks = [a for a in state['assets'] if a['type'] == 'slides' and a['status'] == 'done']
            if len(ready_decks) == 1 and self.remote_matches(ASSETS + ready_decks[0]['downloadRoute'].lstrip('/'), deck, pending=not submitted):
                break
            time.sleep(2)
        # All uploaded data must be complete and byte-identical before external submission.
        receipts = []
        for index, clip in enumerate(clips):
            matches = [c for c in state['clips'] if c['title'] == clip['title'] and c['index'] == index]
            if len(matches) != 1 or not self.remote_matches(matches[0]['downloadLink'], clip['path']):
                raise ClientError('Pluralsight clip title/order/content verification failed.')
            c = matches[0]
            receipts.append({'record_id': clip['record_id'], 'id': c['id'], 'guid': c['guid'], 'title': c['title'],
                'index': c['index'], 'original_file_name': c['videoFile']['originalVideoFileName']})
        decks = [a for a in state['assets'] if a['type'] == 'slides']
        if len(decks) != 1 or decks[0]['status'] != 'done' or not self.remote_matches(ASSETS + decks[0]['downloadRoute'].lstrip('/'), deck):
            raise ClientError('Pluralsight deck content verification failed.')
        if not submitted:
            action = 'updates-submit-move-to-qa' if module['status'] in ('updates_required', 'available_for_updates') else 'submit-move-to-qa'
            self.request('POST', API + f'dropbox/module/{action}', json={'moduleGuid': module['guid']})
            for _ in range(60):
                self.refresh(state)
                if state['module']['status'] in ('submitted', 'updates_submitted'):
                    break
                time.sleep(2)
            else:
                raise ClientError('Pluralsight has not confirmed submitted status; retry will inspect existing uploads.')
        return {'ok': True, 'course_id': course_id, 'course_title': state['course_title'], 'module_order': state['module']['index'], 'module_id': module['id'], 'module_guid': module['guid'],
            'module_title': module['title'], 'status': state['module']['status'], 'already_submitted': submitted,
            'deck': {k: decks[0][k] for k in ('id', 'fileName', 'type', 'status')}, 'clips': receipts}
