from pathlib import Path
import tempfile
from types import SimpleNamespace

from dev_to_cli.client import DevToClient, build_create_payload
from dev_to_cli.config import Config


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)


def config():
    return SimpleNamespace(
        api_key="test-key",
        base_url="https://dev.to/api",
        storage_dir=Path(tempfile.mkdtemp(prefix="dev_to_test_")),
        has_credentials=lambda: True,
        get_missing_credentials=lambda: [],
    )


def test_config_exposes_cache_storage_dir():
    cfg = SimpleNamespace(get_profile_data_dir=lambda: Path("/tmp/dev_to_cache"))

    assert Config.storage_dir.fget(cfg) == Path("/tmp/dev_to_cache")


def test_request_headers_match_official_forem_contract():
    session = FakeSession([FakeResponse([])])
    client = DevToClient(config=config(), session=session)

    client.list_posts(limit=1)

    headers = session.calls[0]["headers"]
    assert headers["api-key"] == "test-key"
    assert headers["Accept"] == "application/vnd.forem.api-v1+json"
    assert headers["Content-Type"] == "application/json"
    assert headers["User-Agent"].startswith("dev_to-cli/")


def test_build_create_payload_keeps_only_supported_article_fields():
    payload = build_create_payload(
        title="Hello DEV",
        body_markdown="**Hi**",
        published=True,
        tags="python, cli , testing",
        canonical_url="https://example.com/post",
        description="Short description",
        series="CLI Series",
        main_image="https://example.com/image.png",
    )

    assert payload == {
        "article": {
            "title": "Hello DEV",
            "body_markdown": "**Hi**",
            "published": True,
            "tags": "python, cli, testing",
            "canonical_url": "https://example.com/post",
            "description": "Short description",
            "series": "CLI Series",
            "main_image": "https://example.com/image.png",
        }
    }


def test_create_post_wraps_payload_under_article_key():
    session = FakeSession(
        [
            FakeResponse(
                {
                    "id": 101,
                    "type_of": "article",
                    "title": "Hello DEV",
                    "description": "Short description",
                    "slug": "hello-dev",
                    "path": "/example-user/hello-dev",
                    "url": "https://dev.to/example-user/hello-dev",
                    "published_at": "2026-05-18T10:00:00Z",
                    "published_timestamp": "2026-05-18T10:00:00Z",
                    "created_at": "2026-05-18T10:00:00Z",
                    "edited_at": None,
                    "canonical_url": "https://example.com/post",
                    "cover_image": "https://example.com/image.png",
                    "tag_list": ["python", "cli"],
                    "body_markdown": "**Hi**",
                    "user": {"name": "Example User", "username": "example-user"},
                },
                status_code=201,
            )
        ]
    )
    client = DevToClient(config=config(), session=session)

    article = client.create_post(
        title="Hello DEV",
        body_markdown="**Hi**",
        published=True,
        tags="python, cli",
        canonical_url="https://example.com/post",
        description="Short description",
        series="CLI Series",
        main_image="https://example.com/image.png",
    )

    assert session.calls[0]["method"] == "POST"
    assert session.calls[0]["url"] == "https://dev.to/api/articles"
    assert session.calls[0]["json"]["article"]["tags"] == "python, cli"
    assert article["id"] == 101
    assert article["tag_list"] == ["python", "cli"]


def test_list_posts_uses_authenticated_articles_endpoint():
    session = FakeSession(
        [
            FakeResponse(
                [
                    {
                        "id": 1,
                        "type_of": "article",
                        "title": "Draft",
                        "description": "One",
                        "slug": "draft",
                        "path": "/example-user/draft",
                        "url": "https://dev.to/example-user/draft",
                        "published_at": None,
                        "published_timestamp": None,
                        "created_at": "2026-05-18T09:00:00Z",
                        "edited_at": None,
                        "canonical_url": None,
                        "cover_image": None,
                        "tag_list": "python, cli",
                        "body_markdown": "Body",
                        "user": {"name": "Example User", "username": "example-user"},
                    }
                ]
            )
        ]
    )
    client = DevToClient(config=config(), session=session)

    articles = client.list_posts(limit=1)

    assert session.calls[0]["method"] == "GET"
    assert session.calls[0]["url"] == "https://dev.to/api/articles/me/all"
    assert session.calls[0]["params"] == {"page": 1, "per_page": 1}
    assert articles[0]["published"] is False
    assert articles[0]["tag_list"] == ["python", "cli"]


def test_get_post_uses_authenticated_all_articles_endpoint():
    session = FakeSession(
        [
            FakeResponse(
                [
                    {
                        "id": 3694312,
                        "type_of": "article",
                        "title": "Draft",
                        "description": "One",
                        "slug": "draft",
                        "path": "/example-user/draft",
                        "url": "https://dev.to/example-user/draft",
                        "published": False,
                        "published_at": None,
                        "published_timestamp": None,
                        "created_at": "2026-05-18T09:00:00Z",
                        "edited_at": None,
                        "canonical_url": None,
                        "cover_image": None,
                        "tag_list": [],
                        "body_markdown": "Body",
                        "user": {"name": "Example User", "username": "example-user"},
                    }
                ]
            )
        ]
    )
    client = DevToClient(config=config(), session=session)

    article = client.get_post(3694312)

    assert session.calls[0]["method"] == "GET"
    assert session.calls[0]["url"] == "https://dev.to/api/articles/me/all"
    assert session.calls[0]["params"] == {"page": 1, "per_page": 1000}
    assert article["id"] == 3694312
    assert article["published"] is False


def test_remove_post_uses_documented_unpublish_endpoint():
    published_article = {
        "id": 3694312,
        "type_of": "article",
        "title": "Published",
        "description": "One",
        "slug": "published",
        "path": "/example-user/published",
        "url": "https://dev.to/example-user/published",
        "published": True,
        "published_at": "2026-05-18T09:00:00Z",
        "published_timestamp": "2026-05-18T09:00:00Z",
        "created_at": "2026-05-18T08:00:00Z",
        "edited_at": None,
        "canonical_url": None,
        "cover_image": None,
        "tag_list": [],
        "body_markdown": "Body",
        "user": {"name": "Example User", "username": "example-user"},
    }
    unpublished_article = {
        **published_article,
        "published": False,
        "published_at": None,
        "published_timestamp": None,
    }
    session = FakeSession([FakeResponse({}, status_code=204)])
    client = DevToClient(config=config(), session=session)
    calls = []

    def fake_get_post(post_id):
        calls.append(post_id)
        if len(calls) == 1:
            return published_article
        if len(calls) == 2:
            return unpublished_article
        raise AssertionError("remove_post called get_post more than twice")

    client.get_post = fake_get_post

    result = client.remove_post(3694312)

    assert calls == [3694312, 3694312]
    assert session.calls[0]["method"] == "PUT"
    assert session.calls[0]["url"] == "https://dev.to/api/articles/3694312/unpublish"
    assert session.calls[0]["json"] is None
    assert session.calls[0]["params"] is None
    assert result == unpublished_article


def test_remove_post_returns_existing_unpublished_article_without_unpublish_request():
    article = {
        "id": 3694312,
        "type_of": "article",
        "title": "Draft",
        "description": "One",
        "slug": "draft",
        "path": "/example-user/draft",
        "url": "https://dev.to/example-user/draft",
        "published": False,
        "published_at": None,
        "published_timestamp": None,
        "created_at": "2026-05-18T09:00:00Z",
        "edited_at": None,
        "canonical_url": None,
        "cover_image": None,
        "tag_list": [],
        "body_markdown": "Body",
        "user": {"name": "Example User", "username": "example-user"},
    }
    session = FakeSession([])
    client = DevToClient(config=config(), session=session)
    client.get_post = lambda post_id: article

    result = client.remove_post(3694312)

    assert session.calls == []
    assert result == article
