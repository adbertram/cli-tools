"""Weekly Firebase session stored in the CLI-tools secret manager."""
import json
from pathlib import Path
import subprocess
import requests

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.config import profile_secret_field_map
from cli_tools_shared.repo_paths import secret_manager_script
from .constants import PROJECT_ID


def secret(config, operation, value=None):
    if operation == 'set':
        config.save_credentials(SESSION_DATA=json.dumps(value))
        return None
    if operation != 'get':
        raise ClientError('Unsupported Weekly secret operation')
    name = profile_secret_field_map(config.env_file_path).get('SESSION_DATA')
    if not name:
        raise ClientError('Weekly session unavailable in secret manager; import an authorized capture')
    helper = secret_manager_script()
    try:
        result = subprocess.run([str(helper), 'get', name], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise ValueError
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise ClientError('Weekly session unavailable in secret manager; import an authorized capture') from None



def decode_capture(python, capture, error, mode=None):
    args = [str(python), '-B', str(Path(__file__).with_name('capture.py'))]
    if mode:
        args.append(mode)
    args.append(str(capture))
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise ValueError
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise ClientError(error) from None


def import_capture(config, directory):
    root = Path(directory).resolve()
    python, capture = root / 'venv/bin/python', root / 'app.flows'
    if not python.is_file() or not capture.is_file():
        raise ClientError('Capture directory must contain app.flows and its disposable decoder environment')
    data = decode_capture(python, capture, 'Unable to import a matching Weekly login and refresh from capture')
    # Retain observed export settings only when reauthenticating the same user.
    if profile_secret_field_map(config.env_file_path).get('SESSION_DATA'):
        previous = secret(config, 'get')
        if previous.get('user_id') == data.get('user_id') and 'export_settings' in previous:
            data['export_settings'] = previous['export_settings']
    # Verify against the live refresh service before publishing the imported session.
    data = renew(data)
    secret(config, 'set', data)
    config.save_credentials(SESSION_IMPORTED='yes')


def renew(data, with_token=False):
    if not isinstance(data, dict) or not all(isinstance(data.get(k), str) and data[k] for k in ('api_key', 'refresh_token', 'user_id')) or not isinstance(data.get('headers'), dict):
        raise ClientError('Weekly session data is invalid; import a fresh capture')
    client = requests.Session()
    client.trust_env = False
    try:
        response = client.post('https://securetoken.googleapis.com/v1/token', params={'key': data['api_key']}, json={'grantType': 'refresh_token', 'refreshToken': data['refresh_token']}, headers=data['headers'], timeout=20, allow_redirects=False)
        if response.status_code != 200:
            raise ClientError(f'Weekly authentication failed (HTTP {response.status_code}); import a fresh capture if revoked')
        result = response.json()
    except (requests.RequestException, ValueError):
        raise ClientError('Weekly authentication request failed') from None
    if not isinstance(result, dict) or result.get('user_id') != data['user_id'] or not all(isinstance(result.get(k), str) and result[k] for k in ('refresh_token', 'id_token', 'expires_in')):
        raise ClientError('Weekly authentication returned an invalid or different identity')
    from .capture_claims import claims
    identity = claims(result['id_token'])
    if identity.get('sub') != data['user_id'] or identity.get('aud') != PROJECT_ID:
        raise ClientError('Weekly authentication returned a different project or user')
    updated = {**data, 'refresh_token': result['refresh_token']}
    return (updated, result['id_token']) if with_token else updated


def refresh(config, with_token=False):
    data, token = renew(secret(config, 'get'), with_token=True)
    secret(config, 'set', data)
    return token if with_token else None


def import_export(config, directory, flow_file="wg-export.flows"):
    root = Path(directory).resolve()
    if not flow_file or Path(flow_file).name != flow_file:
        raise ClientError('Flow file must be a filename inside the capture directory')
    python, capture = root / 'venv/bin/python', (root / flow_file).resolve()
    if capture.parent != root or not python.is_file() or not capture.is_file():
        raise ClientError('Capture directory must contain the selected flow file and its disposable decoder environment')
    observed = decode_capture(python, capture, 'Unable to import a matching Weekly transaction export', mode='export')
    data = secret(config, 'get')
    if observed.get('user_id') != data.get('user_id'):
        raise ClientError('Transaction export belongs to a different user')
    secret(config, 'set', {**data, 'export_settings': observed['export_settings']})


def delete_profile_secret(name):
    helper = secret_manager_script()
    try:
        result = subprocess.run([str(helper), 'delete', name], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise ValueError
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise ClientError('Profile deleted but its Weekly session secret could not be removed') from None
