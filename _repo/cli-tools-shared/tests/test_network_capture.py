"""Actual daemon tap and route capture under background flood, without a browser."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from browser_harness import daemon as module
from browser_harness.network_capture import MAX_EVENTS, NetworkCapture, route_scope
from cli_tools_shared.browser import BrowserHarnessError, driver


SCOPE = route_scope('owned', 'POST', 'https://exact.test', '/post/', 10000)


def request(capture, request_id='exact', **changes):
    value = {'method': 'POST', 'url': 'https://exact.test/post/?ignored=secret',
        'postData': '{"actual":"body"}', 'hasPostData': True, 'headers': {'Cookie': 'NEVER_CAPTURE'}}
    value.update(changes)
    capture.record('Network.requestWillBeSent', {'requestId': request_id, 'request': value}, 'owned')


def response(capture, request_id='exact', **changes):
    value = {'url': 'https://exact.test/post/', 'status': 200, 'headers': {'Set-Cookie': 'NEVER_CAPTURE'}}
    value.update(changes)
    capture.record('Network.responseReceived', {'requestId': request_id, 'response': value}, 'owned')


@pytest.mark.parametrize('field,value', [('method','post'),('origin','https://exact.test/'),
    ('origin','https://user:secret@exact.test'),('origin','https://Exact.test'),('origin','https://exact.test?q=1'),
    ('path','//other.test/post'),('path','/post?q=1'),('path','/post#fragment'),('session_id',''),('max_bytes',True)])
def test_scope_requires_exact_canonical_fields(field, value):
    with pytest.raises(ValueError, match='scope_invalid'):
        route_scope(**(SCOPE | {field:value}))


def test_response_and_finish_correlate_across_drains_without_headers():
    capture = NetworkCapture(SCOPE)
    request(capture)
    first = capture.drain()
    assert first['loss'] is None and len(first['events']) == 1
    assert 'headers' not in json.dumps(first) and 'NEVER_CAPTURE' not in json.dumps(first)
    assert 'ignored=secret' not in json.dumps(first)
    response(capture)
    capture.record('Network.loadingFinished', {'requestId':'exact','encodedDataLength':99}, 'owned')
    capture.record('Network.loadingFinished', {'requestId':'other','encodedDataLength':99}, 'owned')
    last = capture.drain()
    assert [entry['method'] for entry in last['events']] == ['Network.responseReceived','Network.loadingFinished']
    assert capture.drain()['events'] == [] and capture.requests == {'exact'}


def test_matching_overflow_remains_sticky_after_repeated_drains():
    capture = NetworkCapture(SCOPE | {'max_bytes':1_000_000})
    request(capture)
    capture.drain()
    for _ in range(MAX_EVENTS + 1):
        response(capture)
    assert len(capture.events) == MAX_EVENTS
    assert capture.drain()['loss'] == 'capture_limit_exceeded'
    assert capture.drain()['loss'] == 'capture_limit_exceeded'


def test_aggregate_byte_budget_and_lifetime_request_budget_are_bounded():
    capture = NetworkCapture(SCOPE | {'max_bytes':1000})
    for i in range(10): request(capture, str(i), postData='x'*900)
    assert capture.bytes <= 4000 and capture.loss == 'capture_limit_exceeded'
    capture = NetworkCapture(SCOPE)
    for i in range(101):
        request(capture, str(i));capture.drain()
    assert len(capture.requests) == 100 and capture.loss == 'request_limit_exceeded'


@pytest.mark.parametrize('body', [None, '', 'x'*10000, 'x'*10001, '\ud800'])
def test_missing_truncated_or_unrepresentable_post_data_is_loss(body):
    capture = NetworkCapture(SCOPE)
    request(capture, postData=body)
    assert capture.drain()['loss'] == 'request_body_unavailable_or_at_limit'
    assert capture.requests == set()


@pytest.mark.parametrize('kind', ['redirect','response_without_request','response_route_changed','session_detached'])
def test_correlation_and_session_loss_are_explicit(kind):
    capture = NetworkCapture(SCOPE)
    if kind != 'response_without_request':request(capture)
    if kind == 'redirect':
        capture.record('Network.requestWillBeSent', {'requestId':'exact','redirectResponse':{},
            'request':{'method':'GET','url':'https://other.test/'}}, 'owned')
    elif kind == 'response_without_request':response(capture)
    elif kind == 'response_route_changed':response(capture,url='https://other.test/')
    else:capture.record('Target.detachedFromTarget',{'sessionId':'owned'},None)
    expected = 'redirect_inconclusive' if kind == 'redirect' else kind
    assert capture.drain()['loss'] == expected


class CDP:
    def __init__(self):
        self.connected = True
        self.calls = []
        self.msg_id = 0
        self.pending_requests = {}
        self.result = {'result':{'type':'undefined'}}
        async def original(*args):pass
        self._event_registry = SimpleNamespace(handle_event=original)
    async def send_raw(self, method, params, session_id=None):
        self.msg_id += 1
        self.calls.append((method,session_id))
        if not self.connected:raise ConnectionError('private details never returned')
        return self.result


def make_daemon():
    daemon = module.Daemon();daemon.session='owned';daemon.cdp=CDP()
    return daemon


def arm(daemon):
    return asyncio.run(daemon.handle({'meta':'begin_network_capture','scope':SCOPE}))


def test_real_daemon_tap_retains_post_through_more_than_500_unrelated_events(monkeypatch):
    daemon = make_daemon()
    monkeypatch.setattr(module,'get_ws_url',lambda:'ws://unit.invalid/')
    async def connect(url):return daemon.cdp
    async def attach():pass
    monkeypatch.setattr(module,'connect_cdp',connect)
    monkeypatch.setattr(daemon,'attach_first_page',attach)
    async def run():
        await daemon.start()
        captured = await daemon.handle({'meta':'begin_network_capture','scope':SCOPE})
        tap = daemon.cdp._event_registry.handle_event
        await tap('Network.requestWillBeSent',{'requestId':'exact','request':{'method':'POST',
            'url':'https://exact.test/post/','postData':'{}'}},'owned')
        for i in range(1000):
            await tap('Runtime.consoleAPICalled',{'irrelevant':i},'owned')
        await tap('Network.responseReceived',{'requestId':'exact','response':{'status':200,'url':'https://exact.test/post/'}},'owned')
        await tap('Network.loadingFinished',{'requestId':'exact','encodedDataLength':2},'owned')
        assert len(daemon.events) == 500
        result = await daemon.handle({'meta':'drain_network_capture',**captured})
        assert result['loss'] is None
        assert [entry['method'] for entry in result['events']] == ['Network.requestWillBeSent','Network.responseReceived','Network.loadingFinished']
    asyncio.run(run())


@pytest.mark.parametrize('change', [{'capture_id':'wrong'}, {'scope':SCOPE|{'path':'/wrong/'}}])
def test_daemon_mismatched_handle_cannot_drain_or_end(change):
    daemon=make_daemon();captured=arm(daemon)
    for meta in ('drain_network_capture','end_network_capture'):
        assert asyncio.run(daemon.handle({'meta':meta,**captured,**change})) == {'error':'network_capture_binding_changed'}
    assert daemon.network_capture is not None


def test_daemon_session_change_and_connection_loss_fail_closed():
    daemon=make_daemon();captured=arm(daemon)
    daemon.session='changed'
    assert asyncio.run(daemon.handle({'meta':'drain_network_capture',**captured})) == {'error':'network_capture_binding_changed'}
    daemon.session='owned';daemon.cdp.connected=False
    first=asyncio.run(daemon.handle({'meta':'drain_network_capture',**captured}))
    assert first['loss']=='connection_unavailable'
    daemon.cdp.connected=True
    assert asyncio.run(daemon.handle({'meta':'drain_network_capture',**captured}))['loss']=='connection_unavailable'
    assert asyncio.run(daemon.handle({'meta':'end_network_capture',**captured}))=={'ended':True}
    assert daemon.network_capture is None


def test_driver_registered_route_uses_capture_and_refuses_scope_loss(monkeypatch, tmp_path):
    monkeypatch.setattr(driver,'_ensure_runtime_dir',lambda session:tmp_path)
    daemon=make_daemon();service=driver.BrowserHarnessService('unit-route');service._opened=True
    def send(message,**kwargs):
        if message.get('meta')=='session':return {'session_id':'owned'}
        return asyncio.run(daemon.handle(message))
    monkeypatch.setattr(service._bh.h,'_send',send)
    monkeypatch.setattr(service._bh.h,'cdp',lambda *a,**k:None)
    assert service.begin_network_observation(method='POST',origin=SCOPE['origin'],path=SCOPE['path'],max_bytes=10000)=='owned'
    request(daemon.network_capture)
    first=service.network_observations('owned',method='POST',origin=SCOPE['origin'],path=SCOPE['path'],max_bytes=10000)
    assert first==[{'kind':'request','request_id':'exact','body':'{"actual":"body"}'}]
    with pytest.raises(BrowserHarnessError,match='scope_changed'):
        service.network_observations('owned',method='POST',origin=SCOPE['origin'],path='/changed/',max_bytes=10000)
    daemon.network_capture.loss='capture_limit_exceeded'
    for _ in range(2):
        with pytest.raises(BrowserHarnessError,match='capture_loss'):
            service.network_observations('owned',method='POST',origin=SCOPE['origin'],path=SCOPE['path'],max_bytes=10000)
    service.end_network_observation('owned')
    assert daemon.network_capture is None and service._native_network_capture is None


@pytest.mark.parametrize('result', [{'error':{'code':-32000}}, {'error':{},'result':{'type':'undefined'}}, {'exceptionDetails':{},'result':{'type':'undefined'}},
    {'result':{'type':'object'}}, {}, None])
def test_liveness_error_shaped_or_missing_result_never_authorizes_empty_drain(result):
    daemon=make_daemon();captured=arm(daemon)
    daemon.cdp.result=result
    observed=asyncio.run(daemon.handle({'meta':'drain_network_capture',**captured}))
    assert observed['loss']=='connection_unavailable' and observed['events']==[]
    daemon.cdp.result={'result':{'type':'undefined'}}
    assert asyncio.run(daemon.handle({'meta':'drain_network_capture',**captured}))['loss']=='connection_unavailable'


def test_liveness_timeout_cancels_only_its_owned_pending_request(monkeypatch):
    daemon=make_daemon();captured=arm(daemon)
    async def send(method, params, session_id=None):
        daemon.cdp.msg_id += 1
        future=asyncio.get_running_loop().create_future()
        daemon.cdp.pending_requests[daemon.cdp.msg_id]=future
        return await future
    daemon.cdp.send_raw=send
    async def run():
        unrelated=asyncio.get_running_loop().create_future()
        daemon.cdp.pending_requests[999]=unrelated
        observed=await daemon.handle({'meta':'drain_network_capture',**captured})
        assert observed['loss']=='connection_unavailable'
        assert daemon.cdp.pending_requests=={999:unrelated} and not unrelated.done()
        unrelated.cancel()
    asyncio.run(run())
