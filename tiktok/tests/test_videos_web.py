"""Unit tests for the tiktok.com web client behind `videos list/get/delete`.

A fake page stands in for the harness browser: it records every in-page
request and answers with canned TikTok web API bodies, so these tests pin the
request shape (path, method, csrf) and the output contract without a session.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from tiktok_cli.client import ClientError, TikTokWebClient, _SEC_UID_JS
from tiktok_cli.commands import videos as videos_cmd


class FakePage:
    def __init__(self, responses, sec_uid="SEC/UID+1"):
        self.responses = list(responses)
        self.sec_uid = sec_uid
        self.requests = []

    def evaluate(self, js, arg=None):
        if js == _SEC_UID_JS:
            return self.sec_uid
        self.requests.append(arg)
        status, body = self.responses.pop(0)
        return {"status": status, "statusText": "", "body": json.dumps(body)}


class FakeBrowser:
    def __init__(self, page):
        self.page = page
        self.urls = []
        self.closed = False

    def get_page(self, url):
        self.urls.append(url)
        return self.page

    def close(self):
        self.closed = True


class FakeConfig:
    base_url = "https://www.tiktok.com"

    def __init__(self, page):
        self.browser = FakeBrowser(page)

    def get_browser(self):
        return self.browser


def _client(page):
    return TikTokWebClient(config=FakeConfig(page), max_retries=0)


def _aweme(video_id, desc, author="adam"):
    return {"id": video_id, "desc": desc, "createTime": 1700000000, "author": {"uniqueId": author}}


def test_delete_posts_aweme_id_with_csrf():
    page = FakePage([(200, {"status_code": 0})])
    client = _client(page)

    assert client.delete_video("7300000000000000001") == {
        "video_id": "7300000000000000001",
        "deleted": True,
    }
    assert page.requests == [{
        "path": "/api/aweme/delete/?aid=1988&aweme_id=7300000000000000001",
        "method": "POST",
        "csrf": True,
    }]
    assert client.config.browser.urls == ["https://www.tiktok.com/"]


def test_delete_surfaces_tiktok_status_code():
    page = FakePage([(200, {"status_code": 8, "status_msg": "Login expired"})])
    with pytest.raises(ClientError, match="status code 8: Login expired"):
        _client(page).delete_video("7300000000000000001")


def test_delete_rejects_non_numeric_id():
    page = FakePage([])
    with pytest.raises(ClientError, match="must be numeric"):
        _client(page).delete_video("abc")
    assert page.requests == []


def test_list_posted_videos_resolves_sec_uid_and_pages():
    page = FakePage([
        (200, {"statusCode": 0, "itemList": [_aweme("1", "first")], "hasMore": True, "cursor": "99"}),
        (200, {"statusCode": 0, "itemList": [_aweme("2", "second")], "hasMore": False}),
    ])
    client = _client(page)

    videos = client.list_posted_videos("@adam", limit=5)

    assert client.config.browser.urls == ["https://www.tiktok.com/@adam"]
    assert [r["path"] for r in page.requests] == [
        "/api/post/item_list/?aid=1988&secUid=SEC%2FUID%2B1&count=5&cursor=0",
        "/api/post/item_list/?aid=1988&secUid=SEC%2FUID%2B1&count=4&cursor=99",
    ]
    assert videos == [
        {"id": "1", "url": "https://www.tiktok.com/@adam/video/1", "caption": "first",
         "author": "adam", "created_at": 1700000000},
        {"id": "2", "url": "https://www.tiktok.com/@adam/video/2", "caption": "second",
         "author": "adam", "created_at": 1700000000},
    ]


def test_list_posted_videos_requires_sec_uid():
    page = FakePage([], sec_uid=None)
    with pytest.raises(ClientError, match="secUid"):
        _client(page).list_posted_videos("adam")


def test_get_posted_video_missing_id_errors():
    page = FakePage([(200, {"statusCode": 0, "itemList": [_aweme("1", "x")], "hasMore": False})])
    with pytest.raises(ClientError, match="Video 2 not found"):
        _client(page).get_posted_video("adam", "2")


class FakeWebClient:
    def __init__(self):
        self.deleted = []
        self.closed = False

    def delete_video(self, video_id):
        self.deleted.append(video_id)
        return {"video_id": video_id, "deleted": True}

    def list_posted_videos(self, username, limit=100):
        return [
            {"id": "1", "url": "u1", "caption": "keep", "author": username, "created_at": 1},
            {"id": "2", "url": "u2", "caption": "e2e", "author": username, "created_at": 2},
        ][:limit]

    def close(self):
        self.closed = True


@pytest.fixture
def fake_web(monkeypatch):
    fake = FakeWebClient()
    monkeypatch.setattr(videos_cmd, "get_web_client", lambda: fake)
    return fake


def test_delete_command_requires_yes(fake_web):
    result = CliRunner().invoke(videos_cmd.app, ["delete", "123"])
    assert result.exit_code == 1
    assert "Refusing to delete TikTok video without --yes." in result.output
    assert fake_web.deleted == []


def test_delete_command_outputs_json(fake_web):
    result = CliRunner().invoke(videos_cmd.app, ["delete", "123", "--yes"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"video_id": "123", "deleted": True}
    assert fake_web.closed


def test_list_command_filters_and_selects_properties(fake_web):
    result = CliRunner().invoke(
        videos_cmd.app,
        ["list", "--username", "adam", "--filter", "caption:eq:e2e", "--properties", "id"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"id": "2"}]
