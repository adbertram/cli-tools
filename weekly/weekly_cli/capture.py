"""Decode a stopped authorized mitmproxy capture in its own disposable environment."""
import base64
import json
import sys
from urllib.parse import parse_qs, urlsplit

if __package__:
    from .constants import CLOUD_FUNCTIONS_BASE, EXPORT_HEADER_NAMES, PROJECT_ID
else:
    from constants import CLOUD_FUNCTIONS_BASE, EXPORT_HEADER_NAMES, PROJECT_ID


def claims(value):
    try:
        payload = value.split('.')[1]
        return json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
    except (ValueError, TypeError, IndexError):
        raise ValueError('Invalid captured identity token') from None


def _flows(path):
    from mitmproxy.io import FlowReader
    with open(path, 'rb') as source:
        yield from FlowReader(source).stream()


def decode(path):
    login = None
    for flow in _flows(path):
        request, response = getattr(flow, 'request', None), getattr(flow, 'response', None)
        if not request or not response or response.status_code != 200 or request.method != 'POST':
            continue
        url = urlsplit(request.url)
        if url.scheme != 'https':
            continue
        try:
            req = json.loads(request.get_text())
            result = json.loads(response.get_text())
        except (ValueError, TypeError):
            continue
        key = parse_qs(url.query).get('key', [None])[0]
        if url.hostname == 'www.googleapis.com' and url.path == '/identitytoolkit/v3/relyingparty/verifyAssertion':
            login = (key, result)
        elif url.hostname == 'securetoken.googleapis.com' and url.path == '/v1/token' and login:
            old_key, identity = login
            token = identity.get('refreshToken')
            initial = claims(identity.get('idToken', ''))
            renewed = claims(result.get('id_token', ''))
            uid = identity.get('localId')
            required = (key, token, uid, result.get('refresh_token'), result.get('id_token'))
            if not all(isinstance(x, str) and x for x in required):
                continue
            if not (old_key == key and req.get('refreshToken') == token and uid == result.get('user_id') == initial.get('sub') == renewed.get('sub') and initial.get('aud') == renewed.get('aud') == PROJECT_ID):
                continue
            headers = {k: request.headers[k] for k in ('x-client-version', 'x-firebase-gmpid', 'x-ios-bundle-identifier') if k in request.headers}
            return {'api_key': key, 'refresh_token': result['refresh_token'], 'user_id': uid, 'headers': headers}
    raise ValueError('No matching Weekly login and refresh found')


def decode_export(path):
    match = None
    for flow in _flows(path):
        request, response = getattr(flow, 'request', None), getattr(flow, 'response', None)
        if not request or not response or response.status_code != 200 or request.method != 'GET':
            continue
        if request.pretty_host != urlsplit(CLOUD_FUNCTIONS_BASE).hostname or request.path.split('?', 1)[0] != '/downloadTransactionsCsv':
            continue
        auth = request.headers.get('authorization', '')
        if not auth.startswith('Bearer '):
            continue
        identity = claims(auth[7:])
        uid = request.headers.get('requesteduserid')
        settings = {name: request.headers.get(name) for name in EXPORT_HEADER_NAMES}
        if uid and uid == identity.get('sub') and identity.get('aud') == PROJECT_ID and all(value is not None for value in settings.values()) and settings['summaryonly'].lower() == 'false':
            match = {'user_id': uid, 'export_settings': settings}
    if match:
        return match
    raise ValueError('No matching Weekly transaction export found')


if __name__ == '__main__':
    try:
        json.dump(decode_export(sys.argv[2]) if len(sys.argv) == 3 and sys.argv[1] == 'export' else decode(sys.argv[1]), sys.stdout)
    except Exception:
        sys.stderr.write('Unable to decode a matching Weekly login and refresh from capture.\n')
        sys.exit(1)
