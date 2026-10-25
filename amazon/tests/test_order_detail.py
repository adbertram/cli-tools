from decimal import Decimal
from unittest.mock import MagicMock
import json
import pytest
from typer.testing import CliRunner
from amazon_cli import commands
from amazon_cli.parsers import normalize_item_detail
from amazon_cli.client import AmazonClient
from cli_tools_shared.exceptions import ClientError


def raw():
    return {'order_id':'113-9567151-5750627', 'order_date':'May 15, 2026',
            'summary':'Order Summary\nItem(s) Subtotal:\n$77.47\nShipping & Handling:\n$0.00\nEstimated tax to be collected:\n$5.43\nGrand Total:\n$82.90',
            'items':[{'name':n,'quantity':'','unit_price':p} for n,p in
                     [('organizer','$22.09'),('cleaner','$16.00'),('liners','$25.99'),('dog treats','$13.39')]]}


def test_observed_four_item_order_reconciles():
    result=normalize_item_detail(raw())
    assert result['item_prices_complete'] is True
    assert result['total']=='82.90'
    assert sum(Decimal(x['item_price']) for x in result['items'])==Decimal('77.47')
    assert len(result['items'])==4


@pytest.mark.parametrize('change', ['missing_price','bad_quantity','missing_item'])
def test_incomplete_price_evidence_is_flagged(change):
    data=raw()
    if change=='missing_price':data['items'][0]['unit_price']=None
    elif change=='bad_quantity':data['items'][0]['quantity']='unknown'
    else:data['items'].pop()
    result=normalize_item_detail(data)
    assert result['item_prices_complete'] is False
    assert result['split_blocker']


def test_quantity_and_promotion_are_retained():
    data=raw(); data['items']=[{'name':'two books','unit_price':'$10.00','quantity':'2'}]
    data['summary']='Item(s) Subtotal:\n$20.00\nPromotion Applied:\n-$2.00\nGrand Total:\n$18.00'
    result=normalize_item_detail(data)
    assert result['item_prices_complete'] is True
    assert result['items'][0]['item_price']=='20.00'
    assert result['summary'][1]['amount']=='-2.00'


def test_detail_command_closes_client(monkeypatch):
    client=MagicMock();client.get_order_detail.return_value=normalize_item_detail(raw())
    monkeypatch.setattr(commands,'get_client',lambda:client)
    result=CliRunner().invoke(commands.app,['detail','113-9567151-5750627'])
    assert result.exit_code==0
    assert json.loads(result.stdout)['total']=='82.90'
    client.close.assert_called_once()


def test_detail_rejects_order_mismatch_and_scopes_items():
    client=AmazonClient();browser=MagicMock();browser.AUTH_URL_PATTERN=r'/ap/signin'
    page=browser.get_page.return_value;page.url='https://www.amazon.com/your-orders/order-details'
    data=raw();data['order_id']='112-1111111-1111111';page.evaluate.return_value=data
    client._require_authenticated_browser=lambda:browser
    with pytest.raises(ClientError,match='different order'):
        client.get_order_detail('113-9567151-5750627')
    assert '[data-component="purchasedItemsRightGrid"]' in page.evaluate.call_args.args[0]


@pytest.mark.parametrize('data', [None, {}, {'items': [], 'order_id': None}, {'items': [None], 'order_id': '113-9567151-5750627', 'summary': ''}])
def test_malformed_detail_fails_explicitly(data):
    with pytest.raises(ClientError):
        normalize_item_detail(data)
