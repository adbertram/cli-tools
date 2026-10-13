from types import SimpleNamespace
import pytest
from cli_tools_shared.exceptions import ClientError
from vyro_cli.client import VyroClient, bounded_limit, slug_path


def client(responses):
    c = VyroClient(config=SimpleNamespace(), browser=SimpleNamespace(close=lambda: None))
    calls = []
    def get(path):
        calls.append(path)
        return responses.pop(0)
    c._get = get
    return c, calls


@pytest.mark.parametrize('value', [0, -1, 1001, True, '1', None])
def test_limit_rejects_invalid_input(value):
    with pytest.raises(ClientError):
        bounded_limit(value)


@pytest.mark.parametrize('value', ['', '../auth/me', 'a?b', 'a/b', 'x'*201, None])
def test_slug_cannot_escape_route(value):
    with pytest.raises(ClientError):
        slug_path(value)


def test_native_fields_and_pagination_preserved():
    extra = {'requirements': {'text': {'hashtags': ['#example']}}, 'budget': {'remaining': 1.5}}
    c, calls = client([
        {'data': [{'id': 'one', **extra}], 'meta': {'page': {'next': 2}}},
        {'data': [{'id': 'two'}], 'meta': {'page': {'next': None}}},
    ])
    result = c.campaigns(2)
    assert result[0]['requirements'] == extra['requirements']
    assert len(result) == 2
    assert calls == ['/catalog/campaigns?sort=startDate.desc&limit=2&page=1', '/catalog/campaigns?sort=startDate.desc&limit=1&page=2']


@pytest.mark.parametrize('page', [
    {'data': [], 'meta': {'page': {'next': 2}}},
    {'data': [{'id': 'one'}], 'meta': {'page': {'next': 1}}},
    {'data': [{'id': 'one'}], 'meta': {'page': {'next': '2'}}},
    {'data': [{'id': 'one'}, {'id': 'one'}], 'meta': {'page': {'next': None}}},
    {'data': ['bad'], 'meta': {'page': {'next': None}}},
])
def test_malformed_campaign_pages_fail(page):
    c, _ = client([page])
    with pytest.raises(ClientError):
        c.campaigns(10)


def test_repeated_ids_across_pages_fail():
    c, _ = client([{'data':[{'id':'one'}], 'meta':{'page':{'next':2}}}, {'data':[{'id':'one'}], 'meta':{'page':{'next':None}}}])
    with pytest.raises(ClientError, match='duplicate'):
        c.campaigns(2)


def test_oversized_campaign_page_is_not_silently_truncated():
    c, _ = client([{'data':[{'id':'one'}, {'id':'two'}], 'meta':{'page':{'next':None}}}])
    with pytest.raises(ClientError, match='exceeds'):
        c.campaigns(1)


def test_no_linked_social_accounts_is_valid_empty_data():
    c, _ = client([{'data':[], 'meta':{'page':{'next':None}}}])
    assert c.social_accounts() == []


def test_social_pagination_fails_instead_of_omitting_accounts():
    c, _ = client([{'data':[], 'meta':{'page':{'next':2}}}])
    with pytest.raises(ClientError, match='pagination'):
        c.social_accounts()


@pytest.mark.parametrize('meta', [None, [], {'page': None}, {'page': []}])
@pytest.mark.parametrize('method', ['campaigns', 'social_accounts'])
def test_malformed_pagination_is_client_error(meta, method):
    c, _ = client([{'data': [], 'meta': meta}])
    with pytest.raises(ClientError, match='pagination'):
        getattr(c, method)()
