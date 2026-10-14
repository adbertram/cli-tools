"""Native feed emptiness, identity, and pagination evidence."""
import pytest
from tiktok_cli.client import TikTokWebClient, ClientError, normalize_favorite, normalize_posted_video


def item(video_id='1',author='adam'):
    return {'id':video_id,'desc':'caption','author':{'uniqueId':author},'createTime':1}


@pytest.mark.parametrize('payload', [{}, {'hasMore':False}, {'hasMore':False,'total':False}, {'hasMore':True,'itemList':None}])
def test_missing_feed_is_never_empty(payload):
    with pytest.raises(ClientError,match='malformed'):
        TikTokWebClient(config=object())._list_items(None,'/api/post/item_list/?aid=1988',normalize_posted_video,1,initial_payload=payload)


def test_observed_native_empty_favorites():
    response={'statusCode':0,'total':0,'hasMore':False,'cursor':'0'}
    assert TikTokWebClient(config=object())._list_items(None,'/api/user/collect/item_list/?aid=1988',normalize_favorite,1,initial_payload=response) == []


def test_decreasing_cursor_is_valid_but_repeated_feed_is_not():
    client=TikTokWebClient(config=object())
    replies=iter([{'itemList':[item('2')],'hasMore':True,'cursor':'50'}, {'itemList':[item('3')],'hasMore':False}])
    client._fetch_json=lambda *args:next(replies)
    rows=client._list_items(None,'/api/post/item_list/?aid=1988',normalize_posted_video,3,initial_payload={'itemList':[item()],'hasMore':True,'cursor':'100'})
    assert [r['id'] for r in rows] == ['1','2','3']
    client._fetch_json=lambda *args:{'itemList':[item()],'hasMore':True,'cursor':'50'}
    with pytest.raises(ClientError,match='did not advance'):
        client._list_items(None,'/api/post/item_list/?aid=1988',normalize_posted_video,3,initial_payload={'itemList':[item()],'hasMore':True,'cursor':'100'})


def test_cross_profile_feed_rejected():
    with pytest.raises(ClientError,match='another profile'):
        TikTokWebClient(config=object())._list_items(None,'/api/post/item_list/?aid=1988',normalize_posted_video,1,initial_payload={'itemList':[item(author='other')],'hasMore':False},expected_author='adam')


@pytest.mark.parametrize('limit',[0,-1,True,1501])
def test_invalid_limit_never_opens_browser(limit):
    client=TikTokWebClient(config=object())
    client._page=lambda *args:pytest.fail('invalid limit opened browser')
    with pytest.raises(ClientError,match='limit'):
        client.list_favorites(limit=limit)
    with pytest.raises(ClientError,match='limit'):
        client.list_posted_videos('adam',limit=limit)


@pytest.mark.parametrize('author',[None,{}, {'uniqueId':123}, 'not-an-object'])
def test_malformed_authors_fail_explicitly(author):
    response={'itemList':[{**item(),'author':author}],'hasMore':False}
    with pytest.raises(ClientError,match='author is malformed'):
        TikTokWebClient(config=object())._list_items(None,'/api/post/item_list/?aid=1988',normalize_posted_video,1,initial_payload=response,expected_author='adam')
