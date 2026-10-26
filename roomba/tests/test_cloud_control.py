import json
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from roomba_cli.client import ClientError
from roomba_cli.cloud_control import confirmation, send_control, run_control

ROBOT = 'synthetic-robot'
TOKEN = dict(client_id='client', iot_token='token', iot_signature='signature', iot_authorizer_name='authorizer', expires=4102444800, devices=[ROBOT])
SESSION = {'robots': [{'id': ROBOT, 'sku': 'c975020', 'deployment_id': 'deployment'}], 'deployments': {'deployment': {'mqtt': 'synthetic.iot.us-east-1.amazonaws.com', 'awsRegion': 'us-east-1', 'irbtTopics': 'synthetic-prefix'}}}
CREDS = {'connection_tokens': [TOKEN]}


def snapshot(phase='charge', command=None, timestamp=None):
    state = {'cleanMissionStatus': {'phase': phase, 'cycle': 'clean'}}
    metadata = {'cleanMissionStatus': {'phase': {'timestamp': timestamp or int(time.time())}}}
    if command:
        state['lastCommand'] = command
        metadata['lastCommand'] = {'timestamp': timestamp or int(time.time())}
    return {'state': {'reported': state}, 'metadata': {'reported': metadata}}


class Transport:
    def __init__(self, *args, **kwargs):
        self.client = self; self.publishes = []; self.queries = 0; self.closed = False
    def open(self): self.opened = True
    def query(self):
        self.queries += 1
        if self.queries == 1: return snapshot()
        return snapshot('run', self.envelope)
    def remaining(self): return 1
    def publish(self, topic, payload, qos, retain):
        self.publishes.append((topic, payload, qos, retain)); self.envelope = json.loads(payload)
        return SimpleNamespace(rc=0, wait_for_publish=lambda timeout: None, is_published=lambda: True)
    def close(self): self.closed = True


@pytest.mark.parametrize('sku,partition', [('c975020', 'ro-currentstate'), ('R989020', None)])
def test_single_exact_publish_and_fresh_robot_confirmation(sku, partition):
    transport = Transport()
    session = dict(SESSION, robots=[dict(SESSION['robots'][0], sku=sku)])
    with patch('roomba_cli.cloud_control.time.time', return_value=2000000000):
        result = send_control(session, CREDS, ROBOT, 'start', transport_factory=lambda *a, **k: transport)
    topic, payload, qos, retain = transport.publishes[0]
    assert topic == 'synthetic-prefix/things/synthetic-robot/cmd'
    assert json.loads(payload) == {'command': 'start', 'time': 2000000000, 'initiator': 'rmtApp'}
    assert qos == 1 and retain is False and len(transport.publishes) == 1
    assert result['broker_received'] and result['robot_confirmed'] and transport.closed


def test_old_or_unchanged_matching_state_never_confirms():
    envelope = {'command': 'start', 'time': 2000000000, 'initiator': 'rmtApp'}
    prior = snapshot('run', envelope, 2000000000)
    assert not any(confirmation(prior, prior, envelope)[key] for key in ('matching_last_command', 'matching_mission_transition'))
    result = confirmation(snapshot(), snapshot('run', envelope, 1), envelope)
    assert not result['matching_last_command'] and not result['matching_mission_transition']


def test_pause_requires_changed_stop_phase_or_exact_lastcommand():
    envelope = {'command': 'pause', 'time': 2000000000, 'initiator': 'rmtApp'}
    assert confirmation(snapshot('run'), snapshot('stop', timestamp=2000000000), envelope)['matching_mission_transition']
    assert not confirmation(snapshot('stop'), snapshot('stop', timestamp=2000000000), envelope)['matching_mission_transition']
    wrong = dict(envelope, initiator='other')
    assert not confirmation(snapshot(), snapshot('run', wrong, 2000000000), envelope)['matching_last_command']


def test_postpublish_timeout_is_structured_unknown_and_never_retries():
    class Timeout(Transport):
        def query(self):
            if self.queries: raise ClientError('synthetic-secret')
            self.queries += 1
            return snapshot()
    transport = Timeout()
    result = send_control(SESSION, CREDS, ROBOT, 'pause', transport_factory=lambda *a, **k: transport)
    assert result['broker_received'] and not result['robot_confirmed'] and result['completion'] == 'unknown'
    assert len(transport.publishes) == 1 and transport.closed
    assert 'synthetic-secret' not in json.dumps(result)


def test_baseline_failure_never_publishes():
    transport = Transport(); transport.query = lambda: (_ for _ in ()).throw(ClientError('baseline failed'))
    with pytest.raises(ClientError): send_control(SESSION, CREDS, ROBOT, 'start', transport_factory=lambda *a, **k: transport)
    assert not transport.publishes and transport.closed


@pytest.mark.parametrize('change', ['wrong-target', 'bad-prefix', 'other-command'])
def test_invalid_inputs_never_construct_transport(change):
    session = json.loads(json.dumps(SESSION)); target = ROBOT; action = 'start'
    if change == 'wrong-target': target = 'other'
    if change == 'bad-prefix': session['deployments']['deployment']['irbtTopics'] = 'arbitrary/#'
    if change == 'other-command': action = 'dock'
    with patch('roomba_cli.cloud_control.CloudMQTT') as factory:
        with pytest.raises(ClientError): send_control(session, CREDS, target, action, transport_factory=factory)
        factory.assert_not_called()


def test_puback_alone_is_not_robot_execution_and_noack_does_not_poll():
    transport = Transport()
    transport.publish = lambda *a, **k: SimpleNamespace(rc=0, wait_for_publish=lambda timeout: None, is_published=lambda: False)
    result = send_control(SESSION, CREDS, ROBOT, 'start', transport_factory=lambda *a, **k: transport)
    assert result['publish_attempted'] and not result['broker_received'] and not result['robot_confirmed']
    assert transport.queries == 1 and transport.closed


def test_unchanged_phase_with_other_mission_change_does_not_confirm():
    envelope = {'command': 'start', 'time': 2000000000, 'initiator': 'rmtApp'}
    baseline = snapshot('run', timestamp=1)
    current = snapshot('run', timestamp=2000000000)
    current['state']['reported']['cleanMissionStatus']['error'] = 0
    assert not confirmation(baseline, current, envelope)['matching_mission_transition']


def test_phase_old_metadata_cannot_borrow_other_fresh_metadata():
    envelope = {'command': 'start', 'time': 2000000000, 'initiator': 'rmtApp'}
    current = snapshot('run', timestamp=1)
    current['metadata']['reported']['cleanMissionStatus']['error'] = {'timestamp': 2000000000}
    assert not confirmation(snapshot(), current, envelope)['matching_mission_transition']


def test_run_control_refreshes_before_publish_and_never_retries_mutation():
    from contextlib import nullcontext
    with patch('roomba_cli.cloud_auth.profile_lock', return_value=nullcontext()), patch('roomba_cli.cloud_session.load_session', return_value=SESSION), patch('roomba_cli.commands.cloud.resolve_robot', return_value=ROBOT), patch('roomba_cli.cloud_session.secret', return_value=CREDS), patch('roomba_cli.cloud_auth.credentials_due', return_value=True), patch('roomba_cli.cloud_auth.refresh_auth', return_value=(CREDS,True)) as refresh, patch('roomba_cli.cloud_control.send_control', side_effect=ClientError('failed')) as send:
        with pytest.raises(ClientError):run_control(object(), 'synthetic', 'start')
        refresh.assert_called_once(); send.assert_called_once()


def test_cloud_control_requires_explicit_target_and_unknown_exits_one():
    from typer.testing import CliRunner
    from roomba_cli.main import app
    runner = CliRunner()
    with patch('roomba_cli.cloud_control.run_control') as send:
        result = runner.invoke(app, ['cloud', 'start'])
        assert result.exit_code != 0
        send.assert_not_called()
    unknown = {'publish_attempted': True, 'broker_received': True, 'robot_confirmed': False, 'completion': 'unknown'}
    with patch('roomba_cli.cloud_control.run_control', return_value=unknown) as send:
        result = runner.invoke(app, ['cloud', 'pause', '--robot', 'synthetic'])
        assert result.exit_code == 1 and json.loads(result.stdout) == unknown
        send.assert_called_once()
