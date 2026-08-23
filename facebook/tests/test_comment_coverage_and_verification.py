"""Regression tests for the comment-coverage and verification fixes.

Covers two defects found 2026-08-22 when duplicate Adam comments accumulated
on a BrickLink Sellers group post:

1. ``get_group_post`` previously returned only Facebook's initially-loaded
   Relay comment window, hiding comments outside it. It now merges in the
   rendered-DOM comment tree (which expands "View more" controls).
2. ``_wait_for_comment_on_exact_post`` raised ClientError whenever the
   submitted comment was absent from that same blind window, even after the
   composer cleared (strong evidence of success). With
   ``composer_cleared=True`` it must now return
   ``render-timeout-likely-success`` instead — retrying created real
   duplicates.
"""

from cli_tools_shared.exceptions import ClientError

from facebook_cli import client as client_mod
from facebook_cli.models import Comment, GroupPost


def _make_client():
    client_mod.get_config = lambda: object()
    return client_mod.FacebookClient()


def test_get_group_post_merges_rendered_comments_missing_from_relay(monkeypatch):
    client = _make_client()
    monkeypatch.setattr(
        client,
        "_fetch_authenticated_facebook_page",
        lambda url, stop_markers=None: "<html></html>",
    )

    relay_post = GroupPost(
        post_id="1001",
        author="OP",
        text="post body",
        url="https://www.facebook.com/groups/2318028917/posts/1001/",
        thread_url="https://www.facebook.com/groups/2318028917/posts/1001/",
        comments=[
            Comment(comment_id="c1", author="Relay One", text="first", created_time="2026-08-22T00:00:00+00:00"),
            Comment(comment_id="c2", author="Relay Two", text="second"),
        ],
        comment_count=2,
    )
    monkeypatch.setattr(
        client, "_full_group_post_from_html",
        lambda *args, **kwargs: relay_post,
    )
    monkeypatch.setattr(
        client,
        "_extract_rendered_thread_details",
        lambda url, post_id: {
            "comments": [
                {"comment_id": "c1", "author": "Relay One", "text": "first", "replies": []},
                # Hidden from Relay: Adam's newer reply.
                {"comment_id": "c9", "author": "Adam Bertram", "text": "hidden comment", "replies": []},
            ]
        },
    )
    monkeypatch.setattr(client, "_count_comments", lambda comments: len(comments))

    post = client.get_group_post("2318028917/posts/1001")

    ids = [c.comment_id for c in post.comments]
    assert ids == ["c1", "c2", "c9"], "rendered-only comment must be appended once"
    adam = next(c for c in post.comments if c.author == "Adam Bertram")
    assert adam.text == "hidden comment"
    # Relay entries keep their richer metadata.
    assert post.comments[0].created_time == "2026-08-22T00:00:00+00:00"
    assert post.comment_count == 3


def test_get_group_post_falls_back_to_relay_when_render_extraction_fails(monkeypatch):
    client = _make_client()
    monkeypatch.setattr(
        client,
        "_fetch_authenticated_facebook_page",
        lambda url, stop_markers=None: "<html></html>",
    )
    relay_post = GroupPost(
        post_id="1001",
        comments=[Comment(comment_id="c1", author="A", text="t")],
        comment_count=1,
    )
    monkeypatch.setattr(
        client, "_full_group_post_from_html", lambda *args, **kwargs: relay_post,
    )

    def boom(url, post_id):
        raise ClientError("dialog not found")

    monkeypatch.setattr(client, "_extract_rendered_thread_details", boom)

    post = client.get_group_post("2318028917/posts/1001")
    assert [c.comment_id for c in post.comments] == ["c1"]


def test_exact_post_verifier_treats_composer_cleared_as_likely_success(monkeypatch):
    client = _make_client()

    empty_post = GroupPost(post_id="1001", comments=[], comment_count=0)
    monkeypatch.setattr(client, "get_group_post", lambda ref: empty_post)
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: None)

    result = client._wait_for_comment_on_exact_post(
        "2318028917", "1001", "some submitted comment text", timeout_ms=1500,
        composer_cleared=True,
    )

    assert result["verification"] == "render-timeout-likely-success"
    assert result["signal"] == "composer-cleared-but-no-other-evidence"


def test_exact_post_verifier_still_raises_when_composer_never_cleared(monkeypatch):
    import pytest

    client = _make_client()
    empty_post = GroupPost(post_id="1001", comments=[], comment_count=0)
    monkeypatch.setattr(client, "get_group_post", lambda ref: empty_post)
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: None)

    with pytest.raises(ClientError, match="not found on the exact target post"):
        client._wait_for_comment_on_exact_post(
            "2318028917", "1001", "some submitted comment text", timeout_ms=1200,
            composer_cleared=False,
        )


def test_verifier_confirms_when_comment_present_in_extracted_window(monkeypatch):
    client = _make_client()
    text = "Seller side here: most of those refunds aren't laziness, it's drift."
    populated_post = GroupPost(
        post_id="1001",
        comments=[Comment(comment_id="c5", author="Adam Bertram", text=text)],
        comment_count=1,
    )
    calls = {"n": 0}

    def fake_get(ref):
        calls["n"] += 1
        return populated_post if calls["n"] >= 2 else GroupPost(post_id="1001", comments=[], comment_count=0)

    monkeypatch.setattr(client, "get_group_post", fake_get)
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: None)

    result = client._wait_for_comment_on_exact_post(
        "2318028917", "1001", text, timeout_ms=5000, composer_cleared=True,
    )
    assert result["verification"] == "confirmed"
    assert result["commentId"] == "c5"
