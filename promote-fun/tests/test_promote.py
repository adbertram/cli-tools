"""Public API contract tests with synthetic rows; no signed asset URLs."""
from unittest.mock import Mock

import pytest
from cli_tools_shared.exceptions import ClientError
from typer.testing import CliRunner
from promote_fun_cli.client import PromoteFunClient
from promote_fun_cli.main import app

ROW = {'_id': 'campaign123', 'slug': 'example', 'title': 'Example',
       'acceptedPlatforms': ['tiktok'], 'costPer1kViews': 2.0, 'totalBudget': 2000.0}


def response(value, status=200):
    return Mock(status_code=status, ok=status == 200, headers={}, json=Mock(return_value={'status': 'success', 'value': value}))


def client(*values):
    session = Mock()
    session.post.side_effect = [response(value) for value in values]
    return PromoteFunClient(session=session, base_delay=0)


def test_native_rows_no_guessed_view_floor():
    instance = client({'page': [ROW], 'isDone': True, 'continueCursor': '[]'})
    assert instance.campaigns(1000) == [ROW]
    assert instance.session.post.call_args.kwargs['json']['args'] == [
        {'status': 'active', 'paginationOpts': {'numItems': 100, 'cursor': None}, 'sort': 'newest'}]


def test_server_limit_cursor_and_filters():
    instance = client({'page': [ROW], 'isDone': False, 'continueCursor': 'next'},
                      {'page': [{**ROW, '_id': 'other'}], 'isDone': True, 'continueCursor': '[]'})
    assert len(instance.campaigns(2, platform='tiktok', search='Example')) == 2
    arguments = instance.session.post.call_args.kwargs['json']['args'][0]
    assert arguments == {'status': 'active', 'paginationOpts': {'numItems': 1, 'cursor': 'next'},
                         'sort': 'newest', 'platform': 'tiktok', 'search': 'Example'}


@pytest.mark.parametrize('value', [None, {}, {'page': [], 'isDone': False, 'continueCursor': ''},
    {'page': [{}], 'isDone': True}, {'page': [ROW], 'isDone': 'true'}])
def test_invalid_page_fails(value):
    with pytest.raises(ClientError):
        client(value).campaigns()


def test_cycle_fails():
    value = {'page': [ROW], 'isDone': False, 'continueCursor': 'next'}
    with pytest.raises(ClientError, match='pagination'):
        client(value, value).campaigns()


def test_get_preserves_rule_access_and_missing_thresholds():
    detail = {**ROW, 'rulesAccess': {'canViewRules': False, 'hasRules': True}, 'membershipStatus': None}
    assert client(detail).campaign('example') == detail


@pytest.mark.parametrize('value', [None, {}, []])
def test_invalid_detail_fails(value):
    with pytest.raises(ClientError):
        client(value).campaign('example')


@pytest.mark.parametrize('value', [0, -1, 1001, True])
def test_invalid_limit_never_calls_remote(value):
    instance = client()
    with pytest.raises(ClientError):
        instance.campaigns(value)
    instance.session.post.assert_not_called()


@pytest.mark.parametrize('value', ['', '\n', 'x' * 201])
def test_invalid_identifier_never_calls_remote(value):
    instance = client()
    with pytest.raises(ClientError):
        instance.campaign(value)
    instance.session.post.assert_not_called()


def test_retries_read_only_transient(monkeypatch):
    monkeypatch.setattr('promote_fun_cli.client.time.sleep', lambda value: None)
    instance = client()
    instance.session.post.side_effect = [response(None, 503), response(ROW)]
    assert instance.campaign('example') == ROW
    assert instance.session.post.call_count == 2


def test_rejects_private_error_body():
    instance = client()
    instance.session.post.return_value = Mock(ok=True, status_code=200, json=Mock(return_value={'status': 'error', 'errorMessage': 'private token'}))
    instance.session.post.side_effect = None
    with pytest.raises(ClientError, match='response schema changed') as error:
        instance.campaign('example')
    assert 'private token' not in str(error.value)


def test_cli_native_json_and_standard_options(monkeypatch):
    import promote_fun_cli.main as main
    fake = Mock();fake.campaigns.return_value = [ROW]
    monkeypatch.setattr(main, 'PromoteFunClient', lambda: fake)
    result = CliRunner().invoke(app, ['campaigns', 'list', '--limit', '10', '--filter', 'title:eq:Example', '--properties', '_id,title'])
    assert result.exit_code == 0 and 'campaign123' in result.stdout and 'costPer1kViews' not in result.stdout
    fake.close.assert_called_once()


def test_account_excludes_session_material(monkeypatch):
    instance = Mock()
    instance.account.return_value = {'_id': 'person1', 'email': 'user@example.test', 'username': 'clipper', 'token': 'must-not-print'}
    monkeypatch.setattr('promote_fun_cli.main.PromoteFunClient', lambda **kwargs: instance)
    result = CliRunner().invoke(app, ['account', 'get'])
    assert result.exit_code == 0, result.output
    assert 'clipper' in result.output
    assert 'must-not-print' not in result.output
    instance.close.assert_called_once()


def test_verification_requires_authoritative_readback(monkeypatch):
    instance = PromoteFunClient()
    before = {'_id': 'owned', 'status': 'pending'}
    monkeypatch.setattr(instance, '_owned_social_account', Mock(side_effect=[before, before]))
    dispatch = Mock(return_value={'success': True})
    monkeypatch.setattr(instance, '_authenticated_call', dispatch)
    with pytest.raises(ClientError, match='not observed'):
        instance.verify_social_account('owned')
    dispatch.assert_called_once_with('action', 'connectedAccounts:validateBioVerification', {'accountId': 'owned'})


def test_already_verified_does_not_dispatch(monkeypatch):
    instance = PromoteFunClient()
    row = {'_id': 'owned', 'status': 'verified', 'verifiedAt': 123}
    monkeypatch.setattr(instance, '_owned_social_account', Mock(return_value=row))
    dispatch = Mock()
    monkeypatch.setattr(instance, '_authenticated_call', dispatch)
    assert instance.verify_social_account('owned') == row
    dispatch.assert_not_called()
