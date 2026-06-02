from facebook_cli import client as client_mod
from facebook_cli import main as main_mod
from facebook_cli import _helpers as helpers_mod
from cli_tools_shared.exceptions import ClientError
from facebook_cli.models import Comment, GroupPost


def test_group_post_model_dump_includes_thread_metadata():
    post = GroupPost(
        post_id="1001",
        title=None,
        author="Ada",
        text="Thread body",
        body="Thread body",
        url="https://www.facebook.com/groups/2318028917/posts/1001/",
        thread_url="https://www.facebook.com/groups/2318028917/posts/1001/",
        image_urls=["https://example.com/image-1.jpg"],
        comments=[
            Comment(
                comment_id="c1",
                author="Grace",
                text="Top-level comment",
                replies=[
                    Comment(
                        comment_id="r1",
                        author="Linus",
                        text="Nested reply",
                    )
                ],
            )
        ],
    )

    data = post.model_dump()

    assert "image_urls" in data
    assert data["image_urls"] == ["https://example.com/image-1.jpg"]
    assert data["thread_url"] == "https://www.facebook.com/groups/2318028917/posts/1001/"
    assert data["comments"][0]["author"] == "Grace"
    assert data["comments"][0]["replies"][0]["text"] == "Nested reply"


def test_group_post_ref_parts_returns_stable_exact_ids(monkeypatch):
    monkeypatch.setattr(client_mod, "get_config", lambda: object())
    client = client_mod.FacebookClient()

    ref = client._group_post_ref_parts("2318028917/posts/10163442043723918")

    assert ref == {
        "url": "https://www.facebook.com/groups/2318028917/posts/10163442043723918/",
        "group_id": "2318028917",
        "post_id": "10163442043723918",
    }


def test_wait_for_comment_on_exact_post_requires_exact_post_id(monkeypatch):
    monkeypatch.setattr(client_mod, "get_config", lambda: object())
    client = client_mod.FacebookClient()

    def fake_get_group_post(post_ref):
        assert post_ref == "2318028917/posts/10163442043723918"
        return GroupPost(
            post_id="10163442043723918",
            author="Donavan Brotherton",
            text="Best way to pack high value Minifigures",
            comments=[
                Comment(
                    comment_id="c1",
                    author="Example User",
                    text="Yeah, I would ship expensive figs broken down.",
                )
            ],
        )

    monkeypatch.setattr(client, "get_group_post", fake_get_group_post)

    result = client._wait_for_comment_on_exact_post(
        "2318028917",
        "10163442043723918",
        "Yeah, I would ship expensive figs broken down.",
        timeout_ms=1000,
    )

    assert result["verification"] == "confirmed"
    assert result["signal"] == "exact-post-comment-found"
    assert result["postId"] == "10163442043723918"


def test_wait_for_comment_on_exact_post_rejects_wrong_post(monkeypatch):
    monkeypatch.setattr(client_mod, "get_config", lambda: object())
    client = client_mod.FacebookClient()

    def fake_get_group_post(post_ref):
        return GroupPost(
            post_id="10163439347023918",
            author="Jesse Daley",
            text="Different thread",
            comments=[
                Comment(
                    comment_id="c1",
                    author="Example User",
                    text="Yeah, I would ship expensive figs broken down.",
                )
            ],
        )

    monkeypatch.setattr(client, "get_group_post", fake_get_group_post)

    try:
        client._wait_for_comment_on_exact_post(
            "2318028917",
            "10163442043723918",
            "Yeah, I would ship expensive figs broken down.",
            timeout_ms=1000,
        )
    except ClientError as exc:
        assert "did not match requested post ID" in str(exc)
    else:
        raise AssertionError("Expected exact-post verification to reject the wrong post ID")


def test_list_group_posts_full_threads_fetches_permalink_metadata(monkeypatch):
    monkeypatch.setattr(client_mod, "get_config", lambda: object())

    summaries = [
        GroupPost(
            post_id="1001",
            author="Ada",
            text="Summary one",
            body="Summary one",
            url="https://www.facebook.com/groups/2318028917/posts/1001/",
            thread_url="https://www.facebook.com/groups/2318028917/posts/1001/",
        ),
        GroupPost(
            post_id="1002",
            author="Grace",
            text="Full two",
            body="Full two",
            url="https://www.facebook.com/groups/2318028917/posts/1002/",
            thread_url="https://www.facebook.com/groups/2318028917/posts/1002/",
        ),
    ]

    monkeypatch.setattr(
        client_mod.FacebookClient,
        "_list_group_post_summaries",
        lambda self, group_id, limit: summaries,
    )

    requested_urls = []

    def fake_fetch(self, url, stop_markers=None):
        requested_urls.append((url, tuple(stop_markers or ())))
        return "thread-html:" + url

    def fake_extract(self, group_id, post_id, url, body, allow_truncated_tail=False):
        assert group_id == "2318028917"
        assert body == "thread-html:" + url
        assert allow_truncated_tail is True
        return GroupPost(
            post_id=post_id,
            author="Full " + post_id,
            text="Full thread body " + post_id,
            body="Full thread body " + post_id,
            url=url,
            thread_url=url,
            image_urls=[f"https://example.com/{post_id}.jpg"],
            comments=[Comment(comment_id="c-" + post_id, author="Ada", text="Comment")],
        )

    monkeypatch.setattr(client_mod.FacebookClient, "_fetch_authenticated_facebook_page", fake_fetch)
    monkeypatch.setattr(client_mod.FacebookClient, "_full_group_post_from_html", fake_extract)
    monkeypatch.setattr(client_mod.FacebookClient, "_facebook_http_client", lambda self: object())

    client = client_mod.FacebookClient()
    posts = client.list_group_posts("2318028917", limit=2, full_threads=True)

    assert [post.post_id for post in posts] == ["1001", "1002"]
    assert sorted(requested_urls) == [
        ("https://www.facebook.com/groups/2318028917/posts/1001/", tuple(client_mod.GROUP_POST_THREAD_STOP_MARKERS)),
        ("https://www.facebook.com/groups/2318028917/posts/1002/", tuple(client_mod.GROUP_POST_THREAD_STOP_MARKERS)),
    ]
    assert posts[0].image_urls == ["https://example.com/1001.jpg"]
    assert posts[0].comments[0].text == "Comment"


def test_list_group_post_summaries_uses_group_discussion_graphql(monkeypatch):
    monkeypatch.setattr(client_mod, "get_config", lambda: object())

    def fake_graphql(self, group_id, body, count):
        assert group_id == "2318028917"
        assert body == "bootstrap"
        assert count == 7
        return (
            [
                {
                    "post_id": "1001",
                    "title": None,
                    "author": "Ada",
                    "text": "First",
                    "body": "First",
                    "url": "https://www.facebook.com/groups/2318028917/posts/1001/",
                    "thread_url": "https://www.facebook.com/groups/2318028917/posts/1001/",
                },
                {
                    "post_id": "1001",
                    "title": None,
                    "author": "Ada",
                    "text": "Duplicate",
                    "body": "Duplicate",
                    "url": "https://www.facebook.com/groups/2318028917/posts/1001/",
                    "thread_url": "https://www.facebook.com/groups/2318028917/posts/1001/",
                },
                {
                    "post_id": "1002",
                    "title": None,
                    "author": "Grace",
                    "text": "Second",
                    "body": "Second",
                    "url": "https://www.facebook.com/groups/2318028917/posts/1002/",
                    "thread_url": "https://www.facebook.com/groups/2318028917/posts/1002/",
                },
            ],
            True,
        )

    monkeypatch.setattr(
        client_mod.FacebookClient,
        "_fetch_authenticated_facebook_bootstrap_html",
        lambda self, url: "bootstrap",
    )
    monkeypatch.setattr(client_mod.FacebookClient, "_graphql_group_discussion_posts", fake_graphql)

    client = client_mod.FacebookClient()
    posts = client._list_group_post_summaries("2318028917", 2)

    assert [post.post_id for post in posts] == ["1001", "1002"]


def test_extract_group_discussion_request_uses_dynamic_doc_id(monkeypatch):
    monkeypatch.setattr(client_mod, "get_config", lambda: object())
    client = client_mod.FacebookClient()

    body = (
        '{"queryID":"999888777","variables":{"groupID":"2318028917",'
        '"inviteShortLinkKey":null},"queryName":"CometGroupDiscussionRootSuccessQuery"}'
        '{"queryID":"999888777","variables":{"groupID":"2318028917",'
        '"regular_stories_count":10},"queryName":"CometGroupDiscussionRootSuccessQuery"}'
    )

    variables, document_id = client._extract_group_discussion_request(body, "2318028917")

    assert document_id == "999888777"
    assert variables["groupID"] == "2318028917"


def test_extract_comments_from_relay_payloads_builds_reply_tree(monkeypatch):
    monkeypatch.setattr(client_mod, "get_config", lambda: object())
    client = client_mod.FacebookClient()

    comments = client._extract_comments_from_relay_payloads((
        {
            "data": {
                "top": {
                    "__typename": "Comment",
                    "legacy_fbid": "c1",
                    "author": {"name": "Ada"},
                    "body": {"text": "Top level"},
                    "created_time": 1780000000,
                    "comment_direct_parent": None,
                },
                "reply": {
                    "__typename": "Comment",
                    "legacy_fbid": "r1",
                    "author": {"name": "Grace"},
                    "body": {"text": "Nested reply"},
                    "created_time": 1780000100,
                    "comment_direct_parent": {"legacy_fbid": "c1"},
                },
            }
        },
    ))

    assert comments[0]["comment_id"] == "c1"
    assert comments[0]["text"] == "Top level"
    assert comments[0]["replies"][0]["comment_id"] == "r1"
    assert comments[0]["replies"][0]["text"] == "Nested reply"


def test_title_from_group_post_body_uses_first_non_empty_line(monkeypatch):
    monkeypatch.setattr(client_mod, "get_config", lambda: object())
    client = client_mod.FacebookClient()

    title = client._title_from_group_post_body("\n  First line title  \nSecond line body")

    assert title == "First line title"


def test_iter_relay_prefetched_stream_results_allows_truncated_tail(monkeypatch):
    monkeypatch.setattr(client_mod, "get_config", lambda: object())
    client = client_mod.FacebookClient()

    complete = (
        '["RelayPrefetchedStreamCache","next",[],[null,{"__bbox":{"result":'
        '{"data":{"ok":true}}}}]]'
    )
    truncated = '["RelayPrefetchedStreamCache","next",[],[null,{"__bbox":'

    results = tuple(client._iter_relay_prefetched_stream_results(
        complete + truncated,
        allow_truncated_tail=True,
    ))

    assert results == ({"data": {"ok": True}},)


def test_fast_groups_posts_list_full_threads_serializes_metadata(monkeypatch):
    captured = {}

    class FakeClient:
        def list_group_posts(self, group_id, limit=20, full_threads=False):
            captured["call"] = (group_id, limit, full_threads)
            return [
                GroupPost(
                    post_id="1001",
                    title=None,
                    author="Ada",
                    text="Full thread body",
                    body="Full thread body",
                    url="https://www.facebook.com/groups/2318028917/posts/1001/",
                    thread_url="https://www.facebook.com/groups/2318028917/posts/1001/",
                    image_urls=["https://example.com/image-1.jpg"],
                    comments=[
                        Comment(
                            comment_id="c1",
                            author="Grace",
                            text="Top-level comment",
                            replies=[
                                Comment(
                                    comment_id="r1",
                                    author="Linus",
                                    text="Nested reply",
                                )
                            ],
                        )
                    ],
                )
            ]

        def close(self):
            captured["closed"] = True

    def fake_output_list(items, **kwargs):
        captured["items"] = items
        captured["kwargs"] = kwargs

    monkeypatch.setattr(client_mod, "get_client", lambda: FakeClient())
    monkeypatch.setattr(helpers_mod, "output_list", fake_output_list)

    status = main_mod._fast_groups_posts_list(
        ["groups", "posts", "list", "2318028917", "--limit", "25", "--full-threads"]
    )

    assert status == 0
    assert captured["call"] == ("2318028917", 25, True)
    assert captured["closed"] is True
    assert captured["items"][0]["thread_url"] == "https://www.facebook.com/groups/2318028917/posts/1001/"
    assert captured["items"][0]["image_urls"] == ["https://example.com/image-1.jpg"]
    assert captured["items"][0]["comments"][0]["replies"][0]["text"] == "Nested reply"
