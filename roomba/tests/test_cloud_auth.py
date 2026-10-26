"""Synthetic session signing, renewal, atomic publication and read retry coverage."""
import base64
import copy
from datetime import datetime, timezone
import json
import threading
from unittest.mock import Mock, patch

import pytest
import requests

from roomba_cli.client import ClientError, CloudAuthenticationError
from roomba_cli.cloud_auth import (ACCOUNT_URL, LOGIN_URL, authenticated_read, credentials_due, gigya_signature, fingerprint, prepare_refresh_material, refresh_auth, renew_credentials)

SECRET = base64.b64encode(b'synthetic-session-secret').decode()
NOW = 1800000000
FUTURE = '2099-01-01T00:00:00Z'
META = {'robots': [{'id': 'robot-a', 'sku': 'c975020', 'deployment_id': 'v011'}, {'id': 'robot-b', 'sku': 'R989020', 'deployment_id': 'v005'}], 'default_robot_id': 'robot-b', 'templates': {'robot-a': {'synthetic': True}}}
TOKEN = {'client_id': 'synthetic-client', 'expires': 9999999999, 'devices': ['robot-a', 'robot-b'], 'iot_token': 'synthetic-token', 'iot_signature': 'synthetic-signature', 'iot_authorizer_name': 'synthetic-authorizer'}


def candidate():
    params = {'apikey': 'synthetic-api-key', 'format': 'json', 'sdk': 'synthetic SDK', 'targetEnv': 'mobile', 'oauth_token': 'synthetic-session-token', 'nonce': 'captured-nonce', 'timestamp': '1000'}
    params['sig'] = gigya_signature(ACCOUNT_URL, params, SECRET)
    return {'account_info_url': ACCOUNT_URL, 'account_info_params': params, 'session_token': params['oauth_token'], 'session_secret': SECRET, 'uid': 'synthetic-uid', 'login_url': LOGIN_URL, 'login_body': {'app_id': 'synthetic-app', 'app_info': {'device_id': 'synthetic-app'}, 'multiple_authorizer_token_support': True, 'skip_ownership_check': '0', 'push_info': {'push_token': 'must-not-persist'}}}


def credentials():
    return {'AccessKeyId': 'old-key', 'SecretKey': 'synthetic-aws-secret', 'SessionToken': 'old-session', 'Expiration': FUTURE, 'connection_tokens': [copy.deepcopy(TOKEN)], 'account_identity': 'synthetic-account', 'refresh_material': prepare_refresh_material(candidate())}


def response():
    return {'credentials': {'AccessKeyId': 'new-key', 'SecretKey': 'new-aws-secret', 'SessionToken': 'new-session', 'Expiration': FUTURE, 'CognitoId': 'synthetic-account'}, 'robots': {'robot-a': {'sku': 'c975020', 'svcDeplId': 'v011', 'password': 'must-not-persist'}, 'robot-b': {'sku': 'R989020', 'svcDeplId': 'v005'}}, 'connection_tokens': [dict(TOKEN, iot_token='new-mqtt-token')]}


PROOF = {'errorCode': 0, 'UID': 'synthetic-uid', 'UIDSignature': 'fresh-proof', 'signatureTimestamp': str(NOW)}


class Config:
    def __init__(self, path): self.path = path
    def get_profile_data_dir(self): return self.path
    def get_default_robot(self): return None
    def get_robot(self, name): return None


def test_verified_material_discards_old_proof_push_and_forces_no_ownership():
    material = prepare_refresh_material(candidate())
    assert set(material['account_info_form']).isdisjoint({'sig', 'timestamp', 'nonce', 'oauth_token'})
    assert 'push_info' not in material['login_body']
    assert material['login_body']['assume_robot_ownership'] == '0'
    assert 'gigya' not in material['login_body']


@pytest.mark.parametrize('change', [{'account_info_url': 'https://attacker.invalid/'}, {'session_token': 'other-session'}, {'session_secret': base64.b64encode(b'wrong').decode()}])
def test_unverified_capture_cannot_become_refresh_material(change):
    material = candidate(); material.update(change)
    with pytest.raises(ClientError): prepare_refresh_material(material)


def test_both_expiry_types_are_deterministic_and_rest_does_not_require_mqtt():
    value = credentials()
    assert not credentials_due(value, META, NOW)
    value['Expiration'] = datetime.fromtimestamp(NOW + 30, timezone.utc).isoformat()
    assert credentials_due(value, META, NOW)
    value['Expiration'] = FUTURE
    value['connection_tokens'][0]['expires'] = NOW + 30
    assert credentials_due(value, META, NOW)
    assert not credentials_due(value, META, NOW, include_mqtt=False)


def test_renewal_uses_fresh_proof_and_preserves_identity_templates_and_selection():
    old = credentials(); before = copy.deepcopy(old); metadata = copy.deepcopy(META)
    client = Mock(); client.post.side_effect = [Mock(status_code=200, json=lambda: PROOF), Mock(status_code=200, json=response)]
    with patch('roomba_cli.cloud_auth.requests.Session', return_value=client):
        fresh = renew_credentials(old, metadata)
    assert old == before and metadata == META
    assert fresh['AccessKeyId'] == 'new-key' and fresh['connection_tokens'][0]['iot_token'] == 'new-mqtt-token'
    assert fresh['refresh_material'] == old['refresh_material']
    assert 'must-not-persist' not in json.dumps(fresh)
    first, second = client.post.call_args_list
    assert first.args == (ACCOUNT_URL,) and second.args == (LOGIN_URL,)
    params = first.kwargs['data']; body = second.kwargs['json']
    assert params['nonce'] != 'captured-nonce' and params['timestamp'] != '1000'
    unsigned = {k: v for k, v in params.items() if k != 'sig'}
    assert params['sig'] == gigya_signature(ACCOUNT_URL, unsigned, SECRET)
    assert body['gigya']['signature'] == 'fresh-proof' and body['assume_robot_ownership'] == '0'
    assert 'push_info' not in body
    assert all(call.kwargs['allow_redirects'] is False for call in client.post.call_args_list)
    assert client.trust_env is False
    client.close.assert_called_once()


@pytest.mark.parametrize('kind', ['account', 'robot', 'deployment', 'aws-expired', 'mqtt-missing', 'mqtt-device'])
def test_bad_renewal_is_rejected_before_publication(kind):
    data = response()
    if kind == 'account': data['credentials']['CognitoId'] = 'another-account'
    if kind == 'robot': del data['robots']['robot-b']
    if kind == 'deployment': data['robots']['robot-a']['svcDeplId'] = 'different'
    if kind == 'aws-expired': data['credentials']['Expiration'] = '2000-01-01T00:00:00Z'
    if kind == 'mqtt-missing': data['connection_tokens'] = []
    if kind == 'mqtt-device': data['connection_tokens'][0]['devices'] = ['robot-a']
    with patch('roomba_cli.cloud_auth._post_json', side_effect=[PROOF, data]):
        with pytest.raises(ClientError): renew_credentials(credentials(), META)


def test_revoked_session_has_clear_action_and_never_tries_v2_or_echoes_remote_data():
    with patch('roomba_cli.cloud_auth._post_json', return_value={'errorCode': 403000, 'errorMessage': 'synthetic-secret'}) as post:
        with pytest.raises(ClientError) as error: renew_credentials(credentials(), META)
    assert post.call_count == 1
    assert 'sign in to the app' in str(error.value) and 'synthetic-secret' not in str(error.value)


def test_transport_failure_is_redacted():
    client = Mock(); client.post.side_effect = requests.ConnectionError('synthetic-secret')
    with patch('roomba_cli.cloud_auth.requests.Session', return_value=client):
        with pytest.raises(ClientError) as error: renew_credentials(credentials(), META)
    assert 'synthetic-secret' not in str(error.value)
    client.close.assert_called_once()


def store(initial):
    state = {'value': copy.deepcopy(initial), 'sets': 0}
    def access(config, operation, value=None):
        if operation == 'get': return copy.deepcopy(state['value'])
        state['value'] = copy.deepcopy(value); state['sets'] += 1
    return state, access


def test_failed_renewal_preserves_previous_working_bundle_and_metadata(tmp_path):
    config = Config(tmp_path); path = tmp_path / 'cloud-session.json'; path.write_text(json.dumps(META))
    state, access = store(credentials()); before = copy.deepcopy(state['value']); text = path.read_text()
    with patch('roomba_cli.cloud_auth.secret', side_effect=access), patch('roomba_cli.cloud_auth.renew_credentials', side_effect=ClientError('safe failure')):
        with pytest.raises(ClientError): refresh_auth(config, force=True)
    assert state['value'] == before and state['sets'] == 0 and path.read_text() == text


def test_keychain_store_failure_does_not_touch_metadata_or_publish_partial_bundle(tmp_path):
    config = Config(tmp_path); path = tmp_path / 'cloud-session.json'; path.write_text(json.dumps(META)); text = path.read_text()
    old = credentials()
    def access(config, operation, value=None):
        if operation == 'get': return copy.deepcopy(old)
        raise ClientError('safe store failure')
    with patch('roomba_cli.cloud_auth.secret', side_effect=access), patch('roomba_cli.cloud_auth.renew_credentials', return_value=dict(old, AccessKeyId='new-key')):
        with pytest.raises(ClientError): refresh_auth(config, force=True)
    assert path.read_text() == text and old['AccessKeyId'] == 'old-key'


def test_overlapping_force_refreshes_coalesce_to_one_exchange(tmp_path):
    config = Config(tmp_path); (tmp_path / 'cloud-session.json').write_text(json.dumps(META))
    state, access = store(credentials()); entered = threading.Event(); release = threading.Event(); second_observed = threading.Event(); results = []; errors = []
    def lookup(config, operation, value=None):
        if operation == 'get' and threading.current_thread().name == 'second': second_observed.set()
        return access(config, operation, value)
    def renew(old, metadata):
        entered.set(); assert release.wait(3)
        return dict(old, AccessKeyId='new-key', refreshed_at=NOW)
    def invoke():
        try: results.append(refresh_auth(config, force=True))
        except Exception as error: errors.append(error)
    with patch('roomba_cli.cloud_auth.secret', side_effect=lookup), patch('roomba_cli.cloud_auth.renew_credentials', side_effect=renew) as exchange:
        first = threading.Thread(target=invoke, name='first'); first.start(); assert entered.wait(3)
        second = threading.Thread(target=invoke, name='second'); second.start(); assert second_observed.wait(3)
        release.set(); first.join(3); second.join(3)
    assert not errors and not first.is_alive() and not second.is_alive()
    assert exchange.call_count == 1 and state['sets'] == 1
    assert sorted(refreshed for _, refreshed in results) == [False, True]


@pytest.mark.parametrize('always_reject', [False, True])
def test_read_auth_failure_has_one_renewal_and_at_most_one_retry(tmp_path, always_reject):
    config = Config(tmp_path); old = credentials(); fresh = dict(old, AccessKeyId='new-key')
    operation = Mock(side_effect=[CloudAuthenticationError('rejected'), CloudAuthenticationError('again') if always_reject else 'read-ok'])
    with patch('roomba_cli.cloud_auth.load_session', return_value=META), patch('roomba_cli.cloud_auth.secret', return_value=old), patch('roomba_cli.cloud_auth.refresh_auth', return_value=(fresh, True)) as refresh:
        if always_reject:
            with pytest.raises(CloudAuthenticationError): authenticated_read(config, operation)
        else: assert authenticated_read(config, operation) == 'read-ok'
    assert operation.call_count == 2 and refresh.call_count == 1


def test_arbitrary_transport_failure_does_not_trigger_login_retry(tmp_path):
    with patch('roomba_cli.cloud_auth.load_session', return_value=META), patch('roomba_cli.cloud_auth.secret', return_value=credentials()), patch('roomba_cli.cloud_auth.refresh_auth') as refresh:
        with pytest.raises(ClientError): authenticated_read(Config(tmp_path), Mock(side_effect=ClientError('Cloud MQTT transport failed')), mqtt=True)
        refresh.assert_not_called()


def test_recent_refresh_rejection_does_not_start_another_login(tmp_path):
    config = Config(tmp_path); (tmp_path / 'cloud-session.json').write_text(json.dumps(META)); old = dict(credentials(), refreshed_at=NOW)
    with patch('roomba_cli.cloud_auth.time.time', return_value=NOW + 10), patch('roomba_cli.cloud_auth.secret', return_value=old), patch('roomba_cli.cloud_auth.renew_credentials') as exchange:
        with pytest.raises(CloudAuthenticationError, match='recent renewal'): refresh_auth(config, rejected_fingerprint=fingerprint(old))
        exchange.assert_not_called()


def test_same_profile_mqtt_sequences_are_serialized(tmp_path):
    config = Config(tmp_path); entered = threading.Event(); release = threading.Event(); second_started = threading.Event(); active = 0; maximum = 0; guard = threading.Lock(); results = []
    def operation(value):
        nonlocal active, maximum
        with guard: active += 1; maximum = max(maximum, active)
        entered.set(); assert release.wait(3)
        with guard: active -= 1
        return 'read-ok'
    def invoke(second=False):
        if second: second_started.set()
        results.append(authenticated_read(config, operation, mqtt=True))
    with patch('roomba_cli.cloud_auth.load_session', return_value=META), patch('roomba_cli.cloud_auth.secret', side_effect=lambda *a: credentials()):
        first = threading.Thread(target=invoke); first.start(); assert entered.wait(3)
        second = threading.Thread(target=lambda: invoke(True)); second.start(); assert second_started.wait(3)
        # First owns the profile lock until explicitly released; a concurrent
        # implementation without that lock would enter operation twice here.
        threading.Event().wait(0.1); release.set(); first.join(3); second.join(3)
    assert results == ['read-ok', 'read-ok'] and maximum == 1


@pytest.mark.parametrize('fail_exchange', [False, True])
def test_expired_capture_bootstraps_from_verified_session_without_publishing_expired_tokens(tmp_path, fail_exchange):
    from roomba_cli.commands.cloud import import_capture
    from test_cloud import template
    captured_credentials = credentials(); captured_credentials['Expiration'] = '2000-01-01T00:00:00Z'
    captured_token = dict(TOKEN, expires=1000)
    request = dict(template(), url='https://auth3.prod.iot.irobotapi.com/v1/robots/robot-a/setupinfo', region='us-east-1')
    data = {'credentials': captured_credentials, 'robots': META['robots'], 'requests': [request], 'connection_tokens': [captured_token], 'account_identity': 'synthetic-account', 'refresh_material': candidate()}
    config = Config(tmp_path); metadata_path = tmp_path / 'cloud-session.json'; metadata_path.write_text(json.dumps(META)); original = metadata_path.read_text()
    fresh = credentials(); fresh['AccessKeyId'] = 'new-key'
    with patch('roomba_cli.commands.cloud.subprocess.run', return_value=Mock(returncode=0, stdout=json.dumps(data))), patch('roomba_cli.commands.cloud.secret') as publish, patch('roomba_cli.cloud_auth.renew_credentials', side_effect=ClientError('safe bootstrap failure') if fail_exchange else None, return_value=fresh) as renew:
        if fail_exchange:
            with pytest.raises(ClientError): import_capture(config, tmp_path / 'synthetic.flows')
            publish.assert_not_called(); assert metadata_path.read_text() == original
        else:
            result = import_capture(config, tmp_path / 'synthetic.flows')
            assert result['automatic_refresh_configured'] is True
            assert publish.call_args.args[2]['AccessKeyId'] == 'new-key'
            assert json.loads(metadata_path.read_text())['default_robot_id'] == 'robot-b'
        renew.assert_called_once()


def test_token_only_expiry_proactively_renews_before_mqtt_operation(tmp_path):
    old = credentials(); old['connection_tokens'][0]['expires'] = NOW + 10
    fresh = credentials(); operation = Mock(return_value='snapshot')
    with patch('roomba_cli.cloud_auth.time.time', return_value=NOW), patch('roomba_cli.cloud_auth.load_session', return_value=META), patch('roomba_cli.cloud_auth.secret', return_value=old), patch('roomba_cli.cloud_auth.refresh_auth', return_value=(fresh, True)) as renew:
        assert authenticated_read(Config(tmp_path), operation, mqtt=True) == 'snapshot'
    renew.assert_called_once()
    operation.assert_called_once_with(fresh)
