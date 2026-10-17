"""Offline CLI-to-signed-transport contracts for reconciliation and fee reads."""
import json

import pytest
import requests
from typer.testing import CliRunner

from cryptocom_cli.commands import account, orders
from cli_tools_shared.exceptions import ClientError
from test_orders import ENVELOPE_OK, make_client, make_response, patch_transport


@pytest.mark.parametrize('command_name', ['get', 'details'])
def test_client_oid_lookup_preserves_terminal_accounting(monkeypatch, command_name):
    client = make_client()
    row = {'account_id': '1', 'order_id': '2', 'client_oid': 'intent-1',
           'status': 'FILLED', 'cumulative_quantity': '0.100000000000000001',
           'cumulative_value': '9.65', 'cumulative_fee': '0.01', 'fee_instrument_name': 'USD'}
    calls = patch_transport(monkeypatch, client, [ENVELOPE_OK(row)])
    monkeypatch.setattr(orders, 'get_client', lambda: client)
    result = CliRunner().invoke(orders.app, [command_name, '--client-oid', 'intent-1'])
    assert result.exit_code == 0, result.output
    assert calls[0]['json']['params'] == {'client_oid': 'intent-1'}
    data = json.loads(result.stdout)
    assert {key: data[key] for key in row} == row


@pytest.mark.parametrize('args', [[], ['2', '--client-oid', 'intent-1'], ['--client-oid', ' ']])
def test_order_selector_rejected_before_transport(monkeypatch, args):
    client = make_client()
    calls = patch_transport(monkeypatch, client, [ENVELOPE_OK({})])
    monkeypatch.setattr(orders, 'get_client', lambda: client)
    result = CliRunner().invoke(orders.app, ['details', *args])
    assert result.exit_code != 0
    assert result.stdout == ''
    assert calls == []


@pytest.mark.parametrize('args,endpoint,params,row', [
    (['fee-rate'], 'private/get-fee-rate', {}, {'effective_spot_maker_rate_bps': '1.1', 'effective_spot_taker_rate_bps': '2.2'}),
    (['instrument-fee-rate', 'SOL_USD'], 'private/get-instrument-fee-rate', {'instrument_name': 'SOL_USD'}, {'instrument_name': 'SOL_USD', 'effective_maker_rate_bps': '1.1', 'effective_taker_rate_bps': '2.2'}),
])
def test_fee_commands_preserve_basis_points(monkeypatch, args, endpoint, params, row):
    client = make_client()
    calls = patch_transport(monkeypatch, client, [ENVELOPE_OK(row)])
    monkeypatch.setattr(account, 'get_client', lambda: client)
    result = CliRunner().invoke(account.app, args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == row
    assert calls[0]['json']['method'] == endpoint
    assert calls[0]['json']['params'] == params


@pytest.mark.parametrize('module,action,endpoint', [(account, 'fills', 'private/get-trades'), (orders, 'history', 'private/get-order-history')])
def test_history_commands_preserve_exact_records_and_time_window(monkeypatch, module, action, endpoint):
    client = make_client()
    rows = [{'order_id': '2', 'client_oid': 'intent-1', 'trade_id': '3', 'fees': '-0.001', 'traded_quantity': '0.100000000000001', 'create_time_ns': '1771761038000000001'}]
    calls = patch_transport(monkeypatch, client, [ENVELOPE_OK({'data': rows})])
    monkeypatch.setattr(module, 'get_client', lambda: client)
    result = CliRunner().invoke(module.app, [action, '--instrument-name', 'SOL_USD', '--start-time', '1771761038000000000', '--end-time', '1771761038000000002', '--limit', '100'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == rows
    assert len(calls) == 1
    assert calls[0]['json']['method'] == endpoint
    assert calls[0]['json']['params'] == {'instrument_name': 'SOL_USD', 'start_time': 1771761038000000000, 'end_time': 1771761038000000002, 'limit': 100}


@pytest.mark.parametrize('module,action', [(account, 'fills'), (orders, 'history')])
@pytest.mark.parametrize('args', [['--limit', '101'], ['--limit', '0'], ['--start-time', '3', '--end-time', '2']])
def test_history_rejects_invalid_window_before_network(monkeypatch, module, action, args):
    client = make_client()
    calls = patch_transport(monkeypatch, client, [ENVELOPE_OK({'data': []})])
    monkeypatch.setattr(module, 'get_client', lambda: client)
    result = CliRunner().invoke(module.app, [action, *args])
    assert result.exit_code != 0
    assert result.stdout == ''
    assert calls == []


@pytest.mark.parametrize('operation', ['create', 'cancel'])
@pytest.mark.parametrize('failure', ['timeout', 'http500'])
def test_ambiguous_mutation_is_never_retried(monkeypatch, operation, failure):
    client = make_client()
    calls = []
    def request(**kwargs):
        calls.append(kwargs)
        if failure == 'timeout':
            raise requests.Timeout('timeout after acceptance')
        return make_response({'message': 'Internal server error'}, 500)
    monkeypatch.setattr('cryptocom_cli.client.requests.request', request)
    monkeypatch.setattr('cryptocom_cli.client.time.sleep', lambda _: None)
    with pytest.raises(ClientError):
        if operation == 'create':
            client.create_order('SOL_USD', 'BUY', '0.1', limit_price='96.50', client_oid='intent-1')
        else:
            client.cancel_order('2')
    assert len(calls) == 1


@pytest.mark.parametrize('data', [None, {}, ['invalid']])
def test_malformed_history_fails_instead_of_returning_empty(monkeypatch, data):
    client = make_client()
    patch_transport(monkeypatch, client, [ENVELOPE_OK({'data': data})])
    with pytest.raises(ClientError, match='data array of objects'):
        client.get_history_page('private/get-trades')


def test_history_filter_and_properties_are_page_local(monkeypatch):
    client = make_client()
    rows = [{'trade_id': '1', 'order_id': '2', 'fees': '-0.001'}, {'trade_id': '3', 'order_id': '4', 'fees': '-0.002'}]
    calls = patch_transport(monkeypatch, client, [ENVELOPE_OK({'data': rows})])
    monkeypatch.setattr(account, 'get_client', lambda: client)
    result = CliRunner().invoke(account.app, ['fills', '--filter', 'order_id:eq:2', '--properties', 'trade_id,fees'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{'trade_id': '1', 'fees': '-0.001'}]
    assert len(calls) == 1


def test_read_only_retry_remains_available(monkeypatch):
    client = make_client()
    calls = []
    def request(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise requests.Timeout('read interrupted')
        return make_response(ENVELOPE_OK({'effective_spot_taker_rate_bps': '2.2'}))
    monkeypatch.setattr('cryptocom_cli.client.requests.request', request)
    monkeypatch.setattr('cryptocom_cli.client.time.sleep', lambda _: None)
    assert client.get_fee_rate() == {'effective_spot_taker_rate_bps': '2.2'}
    assert len(calls) == 2
