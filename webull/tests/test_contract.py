import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner
from webull.core.exception.exceptions import ServerException

from webull_cli.client import Options, WebullClient, WebullError, safe_error, tick_json
from webull_cli.main import app


runner = CliRunner()


@pytest.fixture(autouse=True)
def offline_cli_profiles(monkeypatch):
    from webull_cli.config import Config, get_config
    monkeypatch.setattr(Config, "__init__", lambda self, profile=None: None)
    get_config.cache_clear()
    yield
    get_config.cache_clear()



def config(token=None):
    return SimpleNamespace(has_credentials=lambda: True, _get=lambda name: "test-credential", access_token=token)


@pytest.mark.parametrize("status,kind", [(400,"rejected"),(403,"rejected"),(429,"rejected"),(500,"unknown"),(502,"unknown")])
def test_error_kind_and_secret_redaction(status, kind):
    error = safe_error(ServerException("API_ERROR", "SECRET_REQUEST_HEADERS", status, "REQUEST"), write=True, client_order_id="intent-1")
    assert error.kind == kind
    assert error.client_order_id == "intent-1"
    assert "SECRET_REQUEST_HEADERS" not in json.dumps(error.as_dict())


@pytest.mark.parametrize("failure", [TimeoutError("SECRET"), ValueError("SECRET malformed JSON")])
def test_write_failure_does_not_retry_or_leak(failure):
    client = WebullClient(config=config())
    calls = []
    def send(*args):
        calls.append(args)
        if isinstance(failure, ValueError):
            return SimpleNamespace(json=lambda: (_ for _ in ()).throw(failure))
        raise failure
    with pytest.raises(WebullError) as error:
        client.call(send, "account", write=True, client_order_id="intent")
    assert len(calls) == 1
    assert error.value.kind == "unknown"
    assert "SECRET" not in str(error.value)


def test_raw_body_preserved_and_paging_unchanged():
    client = WebullClient(config=config())
    body = [{"client_order_id":"cursor", "future_field":{"anything":True}}]
    calls = []
    def history(*args, **kwargs):
        calls.append((args,kwargs))
        return SimpleNamespace(json=lambda:body)
    client._trade = SimpleNamespace(order_v3=SimpleNamespace(get_order_history=history))
    assert client.orders("A", history=True, page_size=25, last_client_order_id="C", start_date="2026-10-01", end_date="2026-10-26") is body
    assert calls == [(("A",),{"page_size":25,"last_client_order_id":"C","start_date":"2026-10-01","end_date":"2026-10-26"})]


def test_live_gate_and_production_host_gate():
    with pytest.raises(WebullError,match="confirm-live"):
        WebullClient(config=config(),options=Options(environment="live"))
    with pytest.raises(WebullError,match="Production Webull hosts"):
        WebullClient(config=config(),options=Options(api_host="api.webull.com"))
    with pytest.raises(WebullError,match="access token"):
        WebullClient(config=config(),options=Options(environment="live",confirm_live=True)).account_list()
    client=WebullClient(config=config(),options=Options(api_host="sandbox.edited.test"))
    assert client.hosts["api"] == "sandbox.edited.test"


@pytest.mark.parametrize("field", ["api_host", "quotes_api_host", "events_api_host"])
@pytest.mark.parametrize("hostname", ["api.webull.com", "data-api.webull.com", "events-api.webull.com"])
@pytest.mark.parametrize("spelling", [lambda host:host.upper(), lambda host:host+":443", lambda host:host+".", lambda host:host.upper()+".:0443", lambda host:host+":80"])
def test_sandbox_rejects_equivalent_production_hostnames(field,hostname,spelling):
    with pytest.raises(WebullError) as error:
        WebullClient(config=config(),options=Options(**{field:spelling(hostname)}))
    assert error.value.kind == "authorization"


def test_valid_host_spelling_is_canonicalized_without_changing_environment():
    client=WebullClient(config=config(),options=Options(api_host="SANDBOX.Edited.Test.:0443"))
    assert client.hosts["api"] == "sandbox.edited.test:443"
    client=WebullClient(config=config("token"),options=Options(environment="live",confirm_live=True,api_host="API.WEBULL.COM.:0443"))
    assert client.hosts["api"] == "api.webull.com:443"


@pytest.mark.parametrize("host", ["api..webull.com", "api.webull.com..", "api.webull.com:0", "api.webull.com:65536", "api.webull.com:", "api.webull.com%2e", "https://api.webull.com", "user@api.webull.com", " api.webull.com"])
def test_malformed_hostnames_fail_before_sdk_construction(host):
    with pytest.raises(WebullError) as error:
        WebullClient(config=config(),options=Options(api_host=host))
    assert error.value.kind == "validation"


@pytest.mark.parametrize("action", ["open", "history", "list"])
@pytest.mark.parametrize("value", [1, 9, 101])
def test_order_page_size_rejects_unsupported_api_values(monkeypatch,action,value):
    import webull_cli.commands.order as module
    monkeypatch.setattr(module,"WebullClient",lambda:pytest.fail("Invalid page size must not reach broker client"))
    result=runner.invoke(app,["order",action,"A","--page-size",str(value)])
    assert result.exit_code == 2
    assert "10" in result.output and "100" in result.output


@pytest.mark.parametrize("action", ["open", "history", "list"])
@pytest.mark.parametrize("value", [10, 100])
def test_order_page_size_boundaries_reach_api_unchanged(monkeypatch,action,value):
    import webull_cli.commands.order as module
    calls=[]
    body=[{"client_order_id":"unchanged-combo-id"}]
    def orders(account,**kwargs):
        calls.append((account,kwargs))
        return body
    monkeypatch.setattr(module,"WebullClient",lambda:SimpleNamespace(orders=orders))
    result=runner.invoke(app,["order",action,"A","--page-size",str(value)])
    assert result.exit_code == 0,result.output
    assert calls[0][1]["page_size"] == value
    assert json.loads(result.stdout) == body


@pytest.mark.parametrize("action", ["open", "history", "list"])
@pytest.mark.parametrize("value", [1, 3, 5])
def test_order_limit_caps_output_without_changing_api_page_or_cursor(monkeypatch,action,value):
    import webull_cli.commands.order as module
    calls=[]
    body=[{"client_order_id":f"combo-{i}","orders":[{"client_order_id":f"leg-{i}"}]} for i in range(10)]
    def orders(account,**kwargs):
        calls.append((account,kwargs))
        return body
    monkeypatch.setattr(module,"WebullClient",lambda:SimpleNamespace(orders=orders))
    result=runner.invoke(app,["order",action,"A","--limit",str(value),"--last-client-order-id","previous-combo"])
    assert result.exit_code==0,result.output
    assert calls[0][1]["page_size"]==100
    assert calls[0][1]["last_client_order_id"]=="previous-combo"
    rows=json.loads(result.stdout)
    assert rows==body[:value]
    assert rows[-1]["client_order_id"]==f"combo-{value-1}"
    assert len(body)==10


def test_sdk_hosts_timeout_and_token(monkeypatch):
    from webull.core import client as sdk_module
    calls=[]
    class API:
        def __init__(self,*args,**kwargs):calls.append((args,kwargs))
        def add_endpoint(self,*args):calls.append(args)
        def set_token(self,value):calls.append(("token",value))
    monkeypatch.setattr(sdk_module,"ApiClient",API)
    client=WebullClient(config=config("authorized-token"),options=Options(connect_timeout=2,read_timeout=4))
    api=client.api
    assert calls[0][1] == {"connect_timeout":2,"timeout":4,"auto_retry":False}
    assert ("us","api.sandbox.webull.com","api") in calls
    assert ("token","authorized-token") in calls
    assert api._stream_logger_set and api._file_logger_set


def test_full_tick_shape():
    payload=SimpleNamespace(basic=SimpleNamespace(symbol="MESmain",category="US_FUTURES",timestamp="other"),time="123",price=Decimal("123.25"),volume="2",side="B")
    assert tick_json(payload) == {"basic":{"symbol":"MESmain","category":"US_FUTURES","timestamp":"other"},"time":"123","price":"123.25","volume":"2","side":"B"}


def test_cli_dry_run_and_confirmation_before_auth(monkeypatch):
    import webull_cli.commands.order as module
    monkeypatch.setattr(module,"WebullClient",lambda: (_ for _ in ()).throw(AssertionError("Must not reach auth")))
    payload='[{"client_order_id":"one","instrument_type":"FUTURES","side":"BUY"}]'
    result=runner.invoke(app,["order","place","A","--orders-json","-","--dry-run"],input=payload)
    assert result.exit_code == 0,result.output
    assert json.loads(result.stdout)["new_orders"] == json.loads(payload)
    result=runner.invoke(app,["order","place","A","--orders-json","-"],input=payload)
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["kind"] == "validation"


def test_cli_native_response_and_explicit_filter(monkeypatch):
    import webull_cli.commands.account as module
    body=[{"account_id":str(i),"extra":{"all":True}} for i in range(105)]
    monkeypatch.setattr(module,"WebullClient",lambda:SimpleNamespace(account_list=lambda:body))
    result=runner.invoke(app,["account","list"])
    assert result.exit_code == 0,result.output
    assert json.loads(result.stdout)==body
    result=runner.invoke(app,["account","list","-l","1","-p","account_id"])
    assert result.exit_code == 0,result.output
    assert json.loads(result.stdout)==[{"account_id":"0"}]


@pytest.mark.parametrize("payload", ['{}','[]','[null]','[{"client_order_id":"x"},{"client_order_id":"x"}]'])
def test_invalid_orders_never_send(payload):
    result=runner.invoke(app,["order","replace","A","--orders-json","-","--dry-run"],input=payload)
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["kind"] == "validation"


@pytest.mark.parametrize("action", ["place", "replace"])
@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e9999", "-1e9999"])
def test_nonfinite_nested_order_json_is_rejected(action,number):
    payload='[{"client_order_id":"order-1","nested":{"values":['+number+']}}]'
    result=runner.invoke(app,["order",action,"A","--orders-json","-","--dry-run"],input=payload)
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["kind"] == "validation"


def test_expired_entry_never_calls_sdk_mutation():
    client=WebullClient(config=config())
    calls=[]
    client._trade=SimpleNamespace(order_v3=SimpleNamespace(place_order=lambda *a:calls.append(a)))
    with pytest.raises(WebullError) as error:
        client.mutate("place","A",[{"client_order_id":"entry"}],send_before_epoch_ms=1)
    assert error.value.kind == "not_sent"
    assert error.value.client_order_id == "entry"
    assert calls == []


def test_transport_rechecks_deadline_after_sdk_setup(monkeypatch):
    from webull.core import client as sdk_module
    calls=[]
    class API:
        def __init__(self,*args,**kwargs):pass
        def add_endpoint(self,*args):pass
        def get_response(self,request):calls.append(request)
    monkeypatch.setattr(sdk_module,"ApiClient",API)
    client=WebullClient(config=config())
    api=client.api
    client._send_before_epoch_ms=1
    with pytest.raises(WebullError) as error:
        api.get_response("request")
    assert error.value.kind == "not_sent"
    assert calls == []


def test_stream_emits_tick_and_disconnect_with_all_fields(monkeypatch):
    from webull.data import data_streaming_client
    events=[]
    class SDK:
        def __init__(self,*args,**kwargs):self.api_client=SimpleNamespace();self.subscriptions=[]
        def register_payload_decoder(self,*args):pass
        def subscribe(self,*args):self.subscriptions.append(args)
        def connect_and_loop_forever(self,**kwargs):
            self.on_connect_success(self,None,None)
            self.on_quotes_message(self,"tick",SimpleNamespace(basic=SimpleNamespace(symbol="MESmain",category="US_FUTURES"),time="123",price=Decimal("5.25"),volume="1",side="B"))
            self.on_disconnect(self,None,1)
            assert self.subscriptions==[(["MESmain"],"US_FUTURES",["TICK"])]
        def disconnect(self):pass
        def _sock_close(self):pass
    monkeypatch.setattr(data_streaming_client,"DataStreamingClient",SDK)
    client=WebullClient(config=config())
    client._api=SimpleNamespace()
    with pytest.raises(WebullError,match="connection ended"):
        client.stream("MESmain",events.append)
    assert events[0]=={"event":"tick","data":{"basic":{"symbol":"MESmain","category":"US_FUTURES"},"time":"123","price":"5.25","volume":"1","side":"B"}}
    assert events[1]=={"event":"disconnect"}


@pytest.mark.parametrize("stage", ["construction", "setup"])
def test_stream_setup_failures_emit_only_one_jsonl_error(monkeypatch,stage):
    import webull_cli.commands.futures as module
    def fail(*args,**kwargs):raise RuntimeError("SECRET SDK headers")
    monkeypatch.setattr(module,"WebullClient",fail if stage == "construction" else lambda:SimpleNamespace(stream=fail))
    result=runner.invoke(app,["futures","stream","MESmain"])
    assert result.exit_code == 1
    lines=result.stdout.splitlines()
    assert len(lines)==1
    event=json.loads(lines[0])
    assert event["event"]=="error" and event["error"]["kind"]=="upstream"
    assert "SECRET" not in result.output


def test_stream_suppresses_duplicate_terminal_errors(monkeypatch):
    import webull_cli.commands.futures as module
    def stream(symbol,emit,**kwargs):
        emit({"event":"error","error":{"kind":"payload","message":"Malformed Webull TICK payload."}})
        raise RuntimeError("Connection ended after the decoder stopped it")
    monkeypatch.setattr(module,"WebullClient",lambda:SimpleNamespace(stream=stream))
    result=runner.invoke(app,["futures","stream","MESmain"])
    assert result.exit_code==1
    assert [json.loads(line)["error"]["kind"] for line in result.stdout.splitlines()]==["payload"]


def test_stream_nonfinite_configuration_is_jsonl_validation():
    result=runner.invoke(app,["futures","stream","MESmain","--socket-loop-seconds","nan"])
    assert result.exit_code==1
    event=json.loads(result.stdout)
    assert event["event"]=="error" and event["error"]["kind"]=="validation"


def test_local_filter_failure_is_safe_actionable_validation(monkeypatch):
    import webull_cli.commands.account as module
    monkeypatch.setattr(module,"WebullClient",lambda:SimpleNamespace(account_list=lambda:[]))
    result=runner.invoke(app,["account","list","--filter","badfilter-SECRET"])
    assert result.exit_code==1
    error=json.loads(result.stdout)["error"]
    assert error["kind"]=="validation"
    assert "field:operator:value" in error["message"]
    assert "SECRET" not in result.output


def test_empty_token_is_structured_validation():
    result=runner.invoke(app,["auth","token"],input="")
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["kind"] == "validation"


def test_token_tty_uses_hidden_prompt(monkeypatch,capsys):
    import webull_cli.main as module
    saved=[]
    monkeypatch.setattr(module.sys,"stdin",SimpleNamespace(isatty=lambda:True))
    monkeypatch.setattr(module.getpass,"getpass",lambda prompt:"SECRET-TOKEN")
    monkeypatch.setattr(module,"get_config",lambda profile:SimpleNamespace(save_credentials=lambda **kw:saved.append(kw)))
    module.save_token(profile=None)
    assert saved==[{"ACCESS_TOKEN":"SECRET-TOKEN"}]
    assert "SECRET-TOKEN" not in capsys.readouterr().out


def test_token_pipe_does_not_echo(monkeypatch):
    import webull_cli.main as module
    saved=[]
    monkeypatch.setattr(module.getpass,"getpass",lambda prompt:pytest.fail("Pipe must not prompt"))
    monkeypatch.setattr(module,"get_config",lambda profile:SimpleNamespace(save_credentials=lambda **kw:saved.append(kw)))
    result=runner.invoke(app,["auth","token"],input="SECRET-TOKEN")
    assert result.exit_code==0,result.output
    assert saved==[{"ACCESS_TOKEN":"SECRET-TOKEN"}]
    assert "SECRET-TOKEN" not in result.output
