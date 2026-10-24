from unittest.mock import Mock
from itertools import chain, repeat

import pytest

from tiktok_cli.client import ClientError
from tiktok_cli.profile_operations import bio


def fixture(previous='original', observed='new'):
    client = Mock()
    client.get_account.return_value = {'account_id': '123', 'username': 'owner'}
    page = client._page.return_value
    field = Mock()
    field.input_value.side_effect = chain([previous, 'new'], repeat(observed))
    field.count.side_effect = chain([1, 1, 1, 1, 0, 0], repeat(1))
    page.get_by_role.return_value = field
    return client, field


def test_exact_previous_bio_guard_prevents_save():
    client, field = fixture()
    with pytest.raises(ClientError, match='no write dispatched'):
        bio(client, 'owner', '123', value='new', expected='other')
    field.fill.assert_not_called()
    client.get_account.assert_called_once_with(expected_username='owner', expected_account_id='123')


def test_read_preserves_exact_whitespace():
    client, field = fixture('line one\nline two ')
    assert bio(client, 'owner', '123')['bio'] == 'line one\nline two '
    field.fill.assert_not_called()


def test_save_requires_fresh_persisted_value():
    client, field = fixture()
    result = bio(client, 'owner', '123', value='new', expected='original')
    assert result['previous_bio'] == 'original'
    assert result['bio'] == 'new'
    assert result['changed'] is True
    assert client._page.call_count == 2


def test_unknown_save_is_not_success_or_retry():
    client, field = fixture(observed='original')
    with pytest.raises(ClientError, match='outcome unknown'):
        bio(client, 'owner', '123', value='new', expected='original')
    field.fill.assert_called_once_with('new')
