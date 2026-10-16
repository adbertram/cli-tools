"""Synthetic campaign contracts, including privacy and unknown-value boundaries."""
from unittest.mock import Mock

import pytest
from cli_tools_shared.exceptions import ClientError
from reach_cat_cli.client import ReachCatClient, public_campaign

ROW = {'id': 'campaign-1', 'name': 'Example', 'status': 'ACTIVE', 'networks': {'tiktok': True},
       'minViewsForPayout': 1000, 'amountRemaining': 20.0, 'settings': {'cpm': '1.5', 'requirements': ['Commentary']}}


def test_allowlist_removes_management_and_user_data():
    row = {**ROW, 'payments': {'private': 'payment'}, 'userAddress': 'private',
           'settings': {**ROW['settings'], 'blockedUsers': {'email': 'private'}, 'roleUsers': {'private': True}}}
    assert public_campaign(row) == ROW


def test_missing_values_remain_missing():
    row = public_campaign({'id': 'x', 'name': 'Unknown'})
    assert row == {'id': 'x', 'name': 'Unknown'}


def client(*pages):
    instance = ReachCatClient()
    instance._read = Mock(side_effect=pages)
    return instance


def test_native_get():
    assert client(ROW).campaign('campaign-1') == ROW


def test_filters_do_not_turn_unknown_minimum_into_zero():
    instance = client({'campaign-1': ROW, 'other': {'id': 'other', 'status': 'INACTIVE'}})
    assert instance.campaigns(1000, platform='tiktok') == [ROW]
    assert instance._read.call_args.args[0] == '/static/campaigns.json'
    assert instance._read.call_args.args[1]['orderBy'] == '"$key"'


def test_native_floor_not_derived_from_rate():
    row = {**ROW};row.pop('minViewsForPayout')
    assert 'minViewsForPayout' not in client({'campaign-1': row}).campaigns()[0]


def test_page_continuation_is_inclusive_but_no_duplicate(monkeypatch):
    monkeypatch.setattr('reach_cat_cli.client.PAGE_SIZE', 2)
    first = {'a': {**ROW, 'id': 'a'}, 'b': {**ROW, 'id': 'b'}}
    second = {'b': {**ROW, 'id': 'b'}, 'c': {**ROW, 'id': 'c'}}
    instance = client(first, second)
    assert [row['id'] for row in instance.campaigns(1000)] == ['a', 'b', 'c']
    assert instance._read.call_args.args[1]['startAt'] == '"b"'


@pytest.mark.parametrize('value', [0, -1, 1001, True])
def test_limit_rejects_before_read(value):
    instance = client()
    with pytest.raises(ClientError):
        instance.campaigns(value)
    instance._read.assert_not_called()


@pytest.mark.parametrize('value', ['', '../bad', 'bad/route', 'x\n'])
def test_identifier_rejects_before_read(value):
    instance = client()
    with pytest.raises(ClientError):
        instance.campaign(value)
    instance._read.assert_not_called()


@pytest.mark.parametrize('value', [None, [], {'id': 'wrong'}])
def test_get_requires_matching_identity(value):
    with pytest.raises(ClientError):
        client(value).campaign('campaign-1')


def test_upstream_transport_error_sanitized():
    import requests
    session = Mock();session.get.side_effect = requests.Timeout('private credential')
    instance = ReachCatClient(session, max_retries=0)
    with pytest.raises(ClientError, match='unavailable') as error:
        instance.campaign('campaign-1')
    assert 'private credential' not in str(error.value)


def test_inactive_sparse_legacy_record_does_not_break_active_discovery():
    sparse = {'status': 'INACTIVE', 'name': 'Legacy'}
    assert client({'campaign-1': ROW, 'legacy': sparse}).campaigns() == [ROW]
    with pytest.raises(ClientError, match='schema changed'):
        client({'legacy': sparse}).campaigns(status='')
