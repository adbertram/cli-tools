import json
from decimal import Decimal
from unittest.mock import Mock, AsyncMock

import pytest
from typer.testing import CliRunner
from monarch_cli.commands import transactions
from monarch_cli.client import MonarchClient, ClientError
from monarch_cli.splits import allocate_items


def items(prices=('10.00', '20.00', '30.00')):
    return [dict(item_price=p, category_id=str(i), category='Household', notes=f'item {i}') for i, p in enumerate(prices)]


@pytest.mark.parametrize('amount', ['-64.99', '64.99', '-0.02'])
def test_exact_sum_and_last_remainder(amount):
    result = allocate_items(items(), amount)
    assert sum(Decimal(i['amount']) for i in result) == Decimal(amount)
    if amount == '-64.99':
        assert [i['amount'] for i in result] == ['-10.83', '-21.66', '-32.50']


@pytest.mark.parametrize('prices', [(None, '2'), ('0', '0'), ('-1', '2'), ('NaN', '2')])
def test_missing_or_invalid_prices_fail(prices):
    with pytest.raises(ValueError):
        allocate_items(items(prices), '-5')


def test_dry_run_never_constructs_client(monkeypatch):
    monkeypatch.setattr(transactions, 'get_client', Mock(side_effect=AssertionError('live access')))
    result = CliRunner().invoke(transactions.app, ['split','txn','--items-json',json.dumps(items()),'--amount','-64.99','--dry-run'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)['splits'][-1]['amount'] == '-32.50'


def test_apply_requires_explicit_yes(monkeypatch):
    monkeypatch.setattr(transactions, 'get_client', Mock(side_effect=AssertionError('live access')))
    result = CliRunner().invoke(transactions.app, ['split','txn','--items-json',json.dumps(items()),'--amount','-64.99'])
    assert result.exit_code == 1
    assert 'Refusing to split' in result.output


def sdk_client():
    client = MonarchClient(config=Mock())
    mm = Mock()
    mm.get_transaction_details = AsyncMock(side_effect=lambda id: {'getTransaction': {'amount': -64.99, 'merchant': {'name':'Amazon'}, 'needsReview':False}})
    actual = [{'id':str(i), 'amount':float(p['amount']), 'notes':p['notes'], 'category':{'id':p['category_id']}} for i,p in enumerate(allocate_items(items(), '-64.99'))]
    mm.get_transaction_splits = AsyncMock(side_effect=[{'getTransaction':{'splitTransactions':[]}}, {'getTransaction':{'splitTransactions':actual}}])
    mm.update_transaction_splits = AsyncMock(return_value={'updateTransactionSplit':{'errors':None,'transaction':{'id':'txn'}}})
    mm.update_transaction = AsyncMock(return_value={})
    client._mm = mm
    return client, mm


def test_sdk_split_payload_and_verified_children():
    client, mm = sdk_client()
    result = client.split_transaction('txn', items(), '-64.99')
    assert result['verified'] is True
    payload = mm.update_transaction_splits.call_args.args[1]
    assert [p['amount'] for p in payload] == [-10.83,-21.66,-32.5]
    assert payload[0]['categoryId'] == '0'
    assert payload[0]['notes'] == 'item 0'
    assert mm.update_transaction.call_count == 3


def test_changed_total_or_existing_splits_prevents_mutation():
    client, mm = sdk_client()
    with pytest.raises(ClientError, match='amount changed'):
        client.split_transaction('txn', items(), '-66')
    mm.update_transaction_splits.assert_not_called()
    client, mm = sdk_client()
    mm.get_transaction_splits.side_effect = [{'getTransaction':{'splitTransactions':[{'id':'existing'}]}}]
    with pytest.raises(ClientError, match='already has splits'):
        client.split_transaction('txn', items(), '-64.99')
    mm.update_transaction_splits.assert_not_called()


def test_payload_errors_fail_without_success():
    client, mm = sdk_client()
    mm.update_transaction_splits.return_value = {'updateTransactionSplit':{'errors':{'message':'denied'}}}
    with pytest.raises(ClientError, match='denied'):
        client.split_transaction('txn', items(), '-64.99')
