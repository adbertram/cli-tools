from unittest.mock import MagicMock

import pytest

from bricklink_cli.client import BricklinkClient
from cli_tools_shared.exceptions import ClientError


def _assert_sequence_required(method, item_type, item_no, **kwargs):
    client = object.__new__(BricklinkClient)
    client._make_request = MagicMock()

    with pytest.raises(
        ClientError,
        match=f'{item_type} item numbers must include a positive sequence suffix',
    ):
        method(client, item_type, item_no, **kwargs)

    client._make_request.assert_not_called()


@pytest.mark.parametrize('item_no', ['4184', '4184-x', '-1', '4184-0'])
def test_instruction_catalog_number_requires_positive_sequence(item_no):
    _assert_sequence_required(
        BricklinkClient.get_catalog_item.__wrapped__,
        'INSTRUCTION',
        item_no,
    )


def test_instruction_catalog_number_with_sequence_reaches_api():
    client = object.__new__(BricklinkClient)
    client._make_request = MagicMock(return_value={'no': '4184-1'})

    result = BricklinkClient.get_catalog_item.__wrapped__(
        client,
        'INSTRUCTION',
        '4184-1',
    )

    assert result == {'no': '4184-1'}
    client._make_request.assert_called_once_with(
        'GET',
        '/items/INSTRUCTION/4184-1',
    )


@pytest.mark.parametrize('item_no', ['6868', '6868-x', '-1', '6868-0'])
def test_set_price_number_requires_positive_sequence(item_no):
    _assert_sequence_required(
        BricklinkClient.get_price_guide.__wrapped__,
        'SET',
        item_no,
        guide_type='sold',
        condition='U',
    )


def test_set_price_number_with_sequence_sends_sold_condition_filters():
    client = object.__new__(BricklinkClient)
    client._make_request = MagicMock(return_value={'avg_price': '48.00'})

    result = BricklinkClient.get_price_guide.__wrapped__(
        client,
        'SET',
        '6868-1',
        guide_type='sold',
        condition='U',
    )

    assert result == {'avg_price': '48.00'}
    client._make_request.assert_called_once_with(
        'GET',
        '/items/SET/6868-1/price',
        params={'guide_type': 'sold', 'new_or_used': 'U'},
    )


def test_request_retries_transient_bricklink_meta_500(monkeypatch):
    transient_response = MagicMock(status_code=200, headers={})
    transient_response.json.return_value = {
        'meta': {'code': 500, 'description': 'INTERNAL_SERVER_ERROR'},
    }
    success_response = MagicMock(status_code=200, headers={})
    success_response.json.return_value = {
        'meta': {'code': 200, 'description': 'OK'},
        'data': {'total_quantity': 1, 'avg_price': '6.7610'},
    }

    client = object.__new__(BricklinkClient)
    client.base_url = 'https://api.bricklink.com/api/store/v1'
    client.session = MagicMock()
    client.session.request.side_effect = [transient_response, success_response]
    client.max_retries = 3
    client.base_delay = 1.0
    client.max_delay = 30.0
    client.jitter = 0.1
    monkeypatch.setattr('bricklink_cli.client.time.sleep', MagicMock())

    result = client._make_request(
        'GET',
        '/items/GEAR/54187/price',
        params={
            'color_id': 11,
            'new_or_used': 'U',
            'guide_type': 'sold',
            'region': 'north_america',
        },
    )

    assert result == {'total_quantity': 1, 'avg_price': '6.7610'}
    assert client.session.request.call_count == 2
