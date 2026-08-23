"""Tests for WordPress post update/delete over XML-RPC.

The adamtheautomator.com origin issues a canonical 301 that strips the trailing
numeric id from ``/wp-json/wp/v2/posts/<id>`` (and downgrades https->http),
collapsing item requests onto the collection endpoint. ``requests`` follows the
redirect and converts a POST update into ``GET /posts`` (a list) and a DELETE
into ``DELETE /posts`` (404 ``rest_no_route``). Feeding that list into
``PostDetail(**data)`` crashes with "argument after ** must be a mapping, not
list".

The client routes post mutations through ``/xmlrpc.php`` instead, a fixed path
the numeric-strip rule cannot match, and reads the result back through the
working ``include=`` REST path. These tests pin the field mapping, the XML-RPC
method calls, and the trash/permanent-delete behavior.
"""

from __future__ import annotations

import xmlrpc.client
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from wordpress_cli.client import WordPressClient, XMLRPC_BLOG_ID
from wordpress_cli.models import PostDetail, create_post_detail


def _make_client() -> WordPressClient:
    client = WordPressClient.__new__(WordPressClient)
    client.base_url = "https://example.com/wp-json/wp/v2"
    client.config = SimpleNamespace(username="admin", app_password="app pass word")
    client.headers = {"User-Agent": "test"}
    return client


class _FakeXMLRPCResponse:
    def __init__(self, value):
        # A well-formed XML-RPC methodResponse carrying a single return value.
        self.content = xmlrpc.client.dumps((value,), methodresponse=True).encode("utf-8")
        self.status_code = 200
        self.ok = True
        self.text = ""


def _decode_request(call):
    """Return (method_name, params) from an outgoing requests.post call object."""
    body = call.kwargs["data"].decode("utf-8")
    params, method_name = xmlrpc.client.loads(body)
    return method_name, params


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------


def test_field_mapping_covers_publish_path():
    client = _make_client()
    fields = {
        "title": "New Title",
        "content": "<p>body</p>",
        "excerpt": "the excerpt",
        "slug": "new-slug",
        "status": "future",
        "date": "2026-09-01T09:00:00",
        "featured_media": 27138,
        "tags": [1, 2],
        "categories": [5403],
        "meta": {"rank_math_focus_keyword": "azure", "adthrive_ads_disable": "on"},
    }

    struct = client._post_fields_to_xmlrpc_struct(fields)

    assert struct["post_title"] == "New Title"
    assert struct["post_content"] == "<p>body</p>"
    assert struct["post_excerpt"] == "the excerpt"
    assert struct["post_name"] == "new-slug"
    assert struct["post_status"] == "future"
    assert struct["post_thumbnail"] == 27138
    # date maps to post_date_gmt (unambiguous UTC), not post_date (which is
    # relative to whatever timezone the site is configured with).
    assert "post_date" not in struct
    assert isinstance(struct["post_date_gmt"], xmlrpc.client.DateTime)
    assert str(struct["post_date_gmt"]) == "20260901T09:00:00"
    assert struct["terms"] == {"post_tag": [1, 2], "category": [5403]}
    assert struct["custom_fields"] == [
        {"key": "rank_math_focus_keyword", "value": "azure"},
        {"key": "adthrive_ads_disable", "value": "on"},
    ]


def test_field_mapping_only_maps_supplied_fields():
    client = _make_client()
    assert client._post_fields_to_xmlrpc_struct({"status": "draft"}) == {"post_status": "draft"}


def test_status_enum_value_is_unwrapped():
    from wordpress_cli.models import PostStatus

    client = _make_client()
    struct = client._post_fields_to_xmlrpc_struct({"status": PostStatus.DRAFT})
    assert struct["post_status"] == "draft"


# ---------------------------------------------------------------------------
# update_post
# ---------------------------------------------------------------------------


def test_update_post_calls_editpost_and_reads_back():
    client = _make_client()
    sentinel = PostDetail(id=27139, title="read back")

    with patch("wordpress_cli.client.requests.post", return_value=_FakeXMLRPCResponse(True)) as mock_post, \
         patch.object(client, "get_post", return_value=sentinel) as mock_get:
        result = client.update_post(27139, {"status": "draft", "featured_media": 27138})

    assert result is sentinel
    mock_get.assert_called_once_with(27139)

    method_name, params = _decode_request(mock_post.call_args)
    assert method_name == "wp.editPost"
    assert mock_post.call_args.args[0] == "https://example.com/xmlrpc.php"
    blog_id, user, password, post_id, struct = params
    assert blog_id == XMLRPC_BLOG_ID
    assert user == "admin"
    assert password == "app pass word"
    assert post_id == 27139
    assert struct == {"post_status": "draft", "post_thumbnail": 27138}


def test_update_post_rejects_empty_fields():
    client = _make_client()
    with pytest.raises(ValueError):
        client.update_post(27139, {})


def test_update_post_raises_when_editpost_not_confirmed():
    client = _make_client()
    with patch("wordpress_cli.client.requests.post", return_value=_FakeXMLRPCResponse(False)), \
         patch.object(client, "get_post"):
        with pytest.raises(Exception) as exc:
            client.update_post(27139, {"status": "draft"})
    assert "did not confirm" in str(exc.value)


def test_update_post_surfaces_xmlrpc_fault():
    client = _make_client()
    fault_body = xmlrpc.client.dumps(
        xmlrpc.client.Fault(403, "Sorry, you are not allowed to edit this post.")
    ).encode("utf-8")
    fake = SimpleNamespace(content=fault_body, ok=True, status_code=200, text="")
    with patch("wordpress_cli.client.requests.post", return_value=fake):
        with pytest.raises(Exception) as exc:
            client.update_post(27139, {"status": "draft"})
    assert "fault (403)" in str(exc.value)


# ---------------------------------------------------------------------------
# delete_post
# ---------------------------------------------------------------------------


def test_delete_post_trash_is_single_call():
    client = _make_client()
    with patch("wordpress_cli.client.requests.post", return_value=_FakeXMLRPCResponse(True)) as mock_post:
        result = client.delete_post(27139)

    assert result == {"deleted": True, "id": 27139, "forced": False}
    assert mock_post.call_count == 1
    method_name, params = _decode_request(mock_post.call_args)
    assert method_name == "wp.deletePost"
    assert params == (XMLRPC_BLOG_ID, "admin", "app pass word", 27139)


def test_delete_post_force_on_live_post_trashes_then_deletes():
    client = _make_client()
    calls = []

    def dispatch(url, **kwargs):
        method_name, _ = xmlrpc.client.loads(kwargs["data"].decode("utf-8"))[::-1]
        calls.append(method_name)
        if method_name == "wp.getPost":
            return _FakeXMLRPCResponse({"post_id": "27139", "post_status": "draft"})
        return _FakeXMLRPCResponse(True)

    with patch("wordpress_cli.client.requests.post", side_effect=dispatch):
        result = client.delete_post(27139, force=True)

    assert result == {"deleted": True, "id": 27139, "forced": True}
    # getPost (state check) + two deletePost calls (trash, then permanent).
    assert calls == ["wp.getPost", "wp.deletePost", "wp.deletePost"]


def test_delete_post_force_on_already_trashed_post_deletes_once():
    client = _make_client()
    calls = []

    def dispatch(url, **kwargs):
        method_name, _ = xmlrpc.client.loads(kwargs["data"].decode("utf-8"))[::-1]
        calls.append(method_name)
        if method_name == "wp.getPost":
            return _FakeXMLRPCResponse({"post_id": "27139", "post_status": "trash"})
        return _FakeXMLRPCResponse(True)

    with patch("wordpress_cli.client.requests.post", side_effect=dispatch):
        result = client.delete_post(27139, force=True)

    assert result == {"deleted": True, "id": 27139, "forced": True}
    # An already-trashed post is permanently deleted by the single deletePost.
    assert calls == ["wp.getPost", "wp.deletePost"]


# ---------------------------------------------------------------------------
# Regression: the pre-fix crash shape
# ---------------------------------------------------------------------------


def test_create_post_detail_still_rejects_a_list_payload():
    """The redirect returned a list; splatting it is the original crash.

    update_post no longer feeds the raw mutation response into
    create_post_detail, but pin the crash so nobody reintroduces a code path
    that passes a list to it.
    """
    with pytest.raises(TypeError):
        create_post_detail([{"id": 1, "title": "a"}, {"id": 2, "title": "b"}])
