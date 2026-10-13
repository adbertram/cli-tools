"""Hashtag filtering, count integrity, and bounded native pagination."""
import pytest
from tiktok_cli.client import ClientError
from tiktok_cli.search import normalize_search_video, search_hashtag_videos, _open_search as native_open_search


@pytest.fixture(autouse=True)
def fake_native_capture(monkeypatch):
    from tiktok_cli import search
    def capture(client, hashtag):
        page = client._page('/')
        native_url = page.evaluate('')
        return page, client._fetch_json(page, native_url), native_url
    monkeypatch.setattr(search, '_open_search', capture)


def item(caption='#boxabl', **stats):
    return {'id':'123','desc':caption,'author':{'uniqueId':'builder'},'createTime':1234,'video':{'duration':17},'stats':stats}


def test_exact_hashtag_and_public_views():
    assert normalize_search_video(item('#boxabler', playCount=99), 'boxabl') is None
    row = normalize_search_video(item('House #BoXaBl!', playCount=201600, diggCount=12700), 'boxabl')
    assert row['views'] == 201600 and row['likes'] == 12700
    assert row['comments'] is None and row['duration'] == 17


def test_zero_is_measurement():
    assert normalize_search_video(item(playCount=0), 'boxabl')['views'] == 0
    with pytest.raises(ClientError):
        normalize_search_video(item(playCount=True), 'boxabl')


class Page:
    def evaluate(self, script):
        return 'https://www.tiktok.com/api/search/general/full/?keyword=%23boxabl&cursor=0&offset=0&count=12'


class Client:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []
    def _page(self, path):
        return Page()
    def _fetch_json(self, page, path):
        self.calls.append(path)
        return next(self.pages)


def payload(items, cursor=12, more=1):
    return {'data':[{'type':1,'item':i} for i in items], 'cursor':cursor, 'has_more':more, 'extra':{'logid':'123'}}


def test_bounded_dedup_pagination():
    c = Client([payload([item()]), payload([item(), {**item(), 'id':'456'}],cursor=24)])
    assert len(search_hashtag_videos(c,'#boxabl',max_pages=2)) == 2
    assert len(c.calls) == 2 and 'cursor=12' in c.calls[1]


def test_stalled_and_malformed_pages_fail():
    with pytest.raises(ClientError):
        search_hashtag_videos(Client([payload([],cursor=0)]),'boxabl')
    with pytest.raises(ClientError):
        search_hashtag_videos(Client([{'cursor':12,'has_more':0}]),'boxabl')


@pytest.mark.parametrize('tag',['', '##boxabl', 'a b','https://tiktok.com'])
def test_invalid_hashtag_fails_before_browser(tag):
    with pytest.raises(ClientError):
        search_hashtag_videos(None,tag)


def test_native_hashtag_metadata_and_caption_boundary():
    assert normalize_search_video(item('word#boxabl'), 'boxabl') is None
    row = normalize_search_video({**item('House'), 'textExtra':[{'hashtagName':'boxabl'}]}, 'boxabl')
    assert row['matched_hashtags'] == ['boxabl']


def test_provenance_and_sanitized_provider_errors():
    c = Client([payload([item()], more=0)])
    row = search_hashtag_videos(c,'boxabl')[0]
    assert row['observed_at'] and row['provenance'] == 'https://www.tiktok.com/api/search/general/full/'
    calls = []
    def fail(*args):
        calls.append(1)
        if len(calls) == 1:
            return payload([item()])
        raise ClientError('URL contains secret-token', code='rate_limited', category='rate_limit', status=429, retry_after_seconds=60)
    c._fetch_json = fail
    with pytest.raises(ClientError) as error:
        search_hashtag_videos(c,'boxabl')
    assert 'secret-token' not in str(error.value)
    assert error.value.status == 429 and error.value.retry_after_seconds == 60


@pytest.mark.parametrize('body,code',[('', 'tiktok_empty_response'),('{', 'tiktok_non_json_response'),('[]','tiktok_malformed_response'),('{"status_code":203}','tiktok_provider_203')])
def test_safe_fetch_failure_metadata(body, code):
    from tiktok_cli.client import TikTokWebClient
    class FetchPage:
        def evaluate(self, script, options):
            return {'status':200,'body':body}
    with pytest.raises(ClientError) as error:
        TikTokWebClient(config=object())._fetch_json(FetchPage(), '/api/search/general/full/')
    assert error.value.code == code and error.value.status == 200


def test_native_first_response_never_replays_fetch():
    import json
    from types import SimpleNamespace
    class NativePage(Page):
        def begin_network_observation(self, **options):
            assert options['method'] == 'GET'
            return 'owner'
        def goto(self, url):
            assert url.endswith('/search?q=%23boxabl')
        def network_observations(self, session, **options):
            return [{'kind':'request','request_id':'one'}, {'kind':'response','request_id':'one','status':200,'route_matches':True},{'kind':'finished','request_id':'one'}]
        def network_response_body(self, session, request_id):
            return json.dumps(payload([item()],more=0))
        def end_network_observation(self, session):
            self.closed = True
    page = NativePage()
    client = SimpleNamespace(_page=lambda path:page, config=SimpleNamespace(base_url='https://www.tiktok.com'))
    _, response, url = native_open_search(client,'boxabl')
    assert response['data'] and page.closed and '/api/search/general/full/' in url
