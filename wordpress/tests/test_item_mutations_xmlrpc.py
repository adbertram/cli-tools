"""Tests for WordPress page/category/tag/media mutations over XML-RPC.

Same host defect as the post mutations (see test_post_mutations_xmlrpc.py): the
adamtheautomator.com origin issues a canonical 301 that strips the trailing
numeric id from ``/wp-json/wp/v2/<type>/<id>``, collapsing item writes/deletes
onto the collection endpoint. ``requests`` follows the redirect and a page/term/
media update lands on ``GET/POST /<collection>`` while a delete lands on
``DELETE /<collection>`` (404 ``rest_no_route``).

The client routes these item mutations through ``/xmlrpc.php`` instead:
- pages: ``wp.editPost``/``wp.deletePost`` with ``post_type=page`` (a page is a post)
- categories/tags: ``wp.editTerm``/``wp.deleteTerm`` (taxonomy ``category``/``post_tag``)
- media: ``wp.deletePost`` (an attachment is a post; there is no clean XML-RPC
  media edit/delete)

Reads back through the working ``include=`` REST path. These tests pin the field
mapping, the XML-RPC method calls, and the trash/permanent-delete behavior.
"""

from __future__ import annotations

import xmlrpc.client
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from wordpress_cli.client import WordPressClient, XMLRPC_BLOG_ID
from wordpress_cli.models import Category, PageDetail, Tag


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


def _fault_response(code: int, message: str) -> SimpleNamespace:
    body = xmlrpc.client.dumps(xmlrpc.client.Fault(code, message)).encode("utf-8")
    return SimpleNamespace(content=body, ok=True, status_code=200, text="")


def _decode_request(call):
    """Return (method_name, params) from an outgoing requests.post call object."""
    body = call.kwargs["data"].decode("utf-8")
    params, method_name = xmlrpc.client.loads(body)
    return method_name, params


def _method_of(call) -> str:
    return _decode_request(call)[0]


# ---------------------------------------------------------------------------
# Page: field mapping
# ---------------------------------------------------------------------------


def test_page_field_mapping_maps_parent_but_not_menu_order_or_template():
    client = _make_client()
    struct = client._post_fields_to_xmlrpc_struct(
        {
            "title": "Docs",
            "content": "<p>body</p>",
            "slug": "docs",
            "status": "publish",
            "parent": 12,
        }
    )
    assert struct["post_title"] == "Docs"
    assert struct["post_content"] == "<p>body</p>"
    assert struct["post_name"] == "docs"
    assert struct["post_status"] == "publish"
    assert struct["post_parent"] == 12
    # menu_order and page_template are dropped by this host's wp.editPost, so
    # they are intentionally never mapped (update_page rejects them instead).
    assert "menu_order" not in struct
    assert "page_template" not in struct


def test_update_page_rejects_menu_order_and_template():
    client = _make_client()
    for field in ("menu_order", "template"):
        with patch("wordpress_cli.client.requests.post") as mock_post:
            with pytest.raises(Exception) as exc:
                client.update_page(814, {"title": "ok", field: 3})
            assert field in str(exc.value) or "menu_order" in str(exc.value)
            mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# update_page
# ---------------------------------------------------------------------------


def test_update_page_calls_editpost_with_page_type_and_reads_back():
    client = _make_client()
    sentinel = PageDetail(id=814, title="read back")

    with patch("wordpress_cli.client.requests.post", return_value=_FakeXMLRPCResponse(True)) as mock_post, \
         patch.object(client, "get_page", return_value=sentinel) as mock_get:
        result = client.update_page(814, {"title": "New", "parent": 5})

    assert result is sentinel
    mock_get.assert_called_once_with(814)

    method_name, params = _decode_request(mock_post.call_args)
    assert method_name == "wp.editPost"
    assert mock_post.call_args.args[0] == "https://example.com/xmlrpc.php"
    blog_id, user, password, page_id, struct = params
    assert blog_id == XMLRPC_BLOG_ID
    assert user == "admin"
    assert password == "app pass word"
    assert page_id == 814
    assert struct == {"post_title": "New", "post_parent": 5, "post_type": "page"}


def test_update_page_rejects_empty_fields():
    client = _make_client()
    with pytest.raises(ValueError):
        client.update_page(814, {})


def test_update_page_raises_when_editpost_not_confirmed():
    client = _make_client()
    with patch("wordpress_cli.client.requests.post", return_value=_FakeXMLRPCResponse(False)), \
         patch.object(client, "get_page"):
        with pytest.raises(Exception) as exc:
            client.update_page(814, {"title": "x"})
    assert "did not confirm" in str(exc.value)


# ---------------------------------------------------------------------------
# delete_page (a page is trashable, same flow as delete_post)
# ---------------------------------------------------------------------------


def test_delete_page_trash_is_single_call():
    client = _make_client()
    with patch("wordpress_cli.client.requests.post", return_value=_FakeXMLRPCResponse(True)) as mock_post:
        result = client.delete_page(814)

    assert result == {"deleted": True, "id": 814, "forced": False}
    assert mock_post.call_count == 1
    method_name, params = _decode_request(mock_post.call_args)
    assert method_name == "wp.deletePost"
    assert params == (XMLRPC_BLOG_ID, "admin", "app pass word", 814)


def test_delete_page_force_on_live_page_trashes_then_deletes():
    client = _make_client()
    calls = []

    def dispatch(url, **kwargs):
        method_name = xmlrpc.client.loads(kwargs["data"].decode("utf-8"))[1]
        calls.append(method_name)
        if method_name == "wp.getPost":
            return _FakeXMLRPCResponse({"post_id": "814", "post_status": "publish"})
        return _FakeXMLRPCResponse(True)

    with patch("wordpress_cli.client.requests.post", side_effect=dispatch):
        result = client.delete_page(814, force=True)

    assert result == {"deleted": True, "id": 814, "forced": True}
    assert calls == ["wp.getPost", "wp.deletePost", "wp.deletePost"]


# ---------------------------------------------------------------------------
# Category / Tag: term field mapping
# ---------------------------------------------------------------------------


def test_category_term_struct_includes_taxonomy_and_parent():
    client = _make_client()
    struct = client._term_fields_to_xmlrpc_struct(
        "category", {"name": "Azure", "slug": "azure", "description": "d", "parent": 9}
    )
    assert struct == {
        "taxonomy": "category",
        "name": "Azure",
        "slug": "azure",
        "description": "d",
        "parent": 9,
    }


def test_tag_term_struct_omits_parent():
    client = _make_client()
    struct = client._term_fields_to_xmlrpc_struct("post_tag", {"name": "azure"})
    assert struct == {"taxonomy": "post_tag", "name": "azure"}


# ---------------------------------------------------------------------------
# update_category / update_tag
# ---------------------------------------------------------------------------


def test_update_category_calls_editterm_and_reads_back():
    client = _make_client()
    sentinel = Category(id=5403, name="read back")

    with patch("wordpress_cli.client.requests.post", return_value=_FakeXMLRPCResponse(True)) as mock_post, \
         patch.object(client, "get_category", return_value=sentinel) as mock_get:
        result = client.update_category(5403, {"name": "Azure", "parent": 9})

    assert result is sentinel
    mock_get.assert_called_once_with(5403)

    method_name, params = _decode_request(mock_post.call_args)
    assert method_name == "wp.editTerm"
    blog_id, user, password, term_id, struct = params
    assert (blog_id, user, password, term_id) == (XMLRPC_BLOG_ID, "admin", "app pass word", 5403)
    assert struct == {"taxonomy": "category", "name": "Azure", "parent": 9}


def test_update_tag_calls_editterm_with_post_tag_taxonomy():
    client = _make_client()
    sentinel = Tag(id=77, name="read back")

    with patch("wordpress_cli.client.requests.post", return_value=_FakeXMLRPCResponse(True)) as mock_post, \
         patch.object(client, "get_tag", return_value=sentinel) as mock_get:
        result = client.update_tag(77, {"name": "azure"})

    assert result is sentinel
    mock_get.assert_called_once_with(77)

    method_name, params = _decode_request(mock_post.call_args)
    assert method_name == "wp.editTerm"
    _, _, _, term_id, struct = params
    assert term_id == 77
    assert struct == {"taxonomy": "post_tag", "name": "azure"}


def test_update_category_rejects_empty_fields():
    client = _make_client()
    with pytest.raises(ValueError):
        client.update_category(5403, {})


def test_update_tag_raises_when_editterm_not_confirmed():
    client = _make_client()
    with patch("wordpress_cli.client.requests.post", return_value=_FakeXMLRPCResponse(False)), \
         patch.object(client, "get_tag"):
        with pytest.raises(Exception) as exc:
            client.update_tag(77, {"name": "x"})
    assert "did not confirm" in str(exc.value)


# ---------------------------------------------------------------------------
# delete_category / delete_tag (wp.deleteTerm, always permanent)
# ---------------------------------------------------------------------------


def test_delete_category_calls_deleteterm():
    client = _make_client()
    with patch("wordpress_cli.client.requests.post", return_value=_FakeXMLRPCResponse(True)) as mock_post:
        result = client.delete_category(5403)

    assert result == {"deleted": True, "id": 5403, "taxonomy": "category"}
    method_name, params = _decode_request(mock_post.call_args)
    assert method_name == "wp.deleteTerm"
    assert params == (XMLRPC_BLOG_ID, "admin", "app pass word", "category", 5403)


def test_delete_tag_calls_deleteterm_with_post_tag():
    client = _make_client()
    with patch("wordpress_cli.client.requests.post", return_value=_FakeXMLRPCResponse(True)) as mock_post:
        result = client.delete_tag(77)

    assert result == {"deleted": True, "id": 77, "taxonomy": "post_tag"}
    _, params = _decode_request(mock_post.call_args)
    assert params == (XMLRPC_BLOG_ID, "admin", "app pass word", "post_tag", 77)


def test_delete_tag_raises_when_deleteterm_not_confirmed():
    client = _make_client()
    with patch("wordpress_cli.client.requests.post", return_value=_FakeXMLRPCResponse(False)):
        with pytest.raises(Exception) as exc:
            client.delete_tag(77)
    assert "did not confirm" in str(exc.value)


# ---------------------------------------------------------------------------
# delete_media (attachment via wp.deletePost; MEDIA_TRASH may or may not apply)
# ---------------------------------------------------------------------------


def test_delete_media_non_force_is_single_call():
    client = _make_client()
    with patch("wordpress_cli.client.requests.post", return_value=_FakeXMLRPCResponse(True)) as mock_post:
        result = client.delete_media(27138)

    assert result == {"deleted": True, "id": 27138, "forced": False}
    assert mock_post.call_count == 1
    method_name, params = _decode_request(mock_post.call_args)
    assert method_name == "wp.deletePost"
    assert params == (XMLRPC_BLOG_ID, "admin", "app pass word", 27138)


def test_delete_media_force_without_media_trash_deletes_once():
    """No MEDIA_TRASH: the first wp.deletePost removes the attachment, so the
    follow-up wp.getPost 404s and no second delete is issued."""
    client = _make_client()
    calls = []

    def dispatch(url, **kwargs):
        method_name = xmlrpc.client.loads(kwargs["data"].decode("utf-8"))[1]
        calls.append(method_name)
        if method_name == "wp.getPost":
            return _fault_response(404, "Invalid attachment ID.")
        return _FakeXMLRPCResponse(True)

    with patch("wordpress_cli.client.requests.post", side_effect=dispatch):
        result = client.delete_media(27138, force=True)

    assert result == {"deleted": True, "id": 27138, "forced": True}
    assert calls == ["wp.deletePost", "wp.getPost"]


def test_delete_media_force_with_media_trash_deletes_twice():
    """MEDIA_TRASH enabled: the first wp.deletePost only trashes the attachment,
    so the follow-up wp.getPost still finds it and a second delete runs."""
    client = _make_client()
    calls = []

    def dispatch(url, **kwargs):
        method_name = xmlrpc.client.loads(kwargs["data"].decode("utf-8"))[1]
        calls.append(method_name)
        if method_name == "wp.getPost":
            return _FakeXMLRPCResponse({"post_id": "27138", "post_status": "trash"})
        return _FakeXMLRPCResponse(True)

    with patch("wordpress_cli.client.requests.post", side_effect=dispatch):
        result = client.delete_media(27138, force=True)

    assert result == {"deleted": True, "id": 27138, "forced": True}
    assert calls == ["wp.deletePost", "wp.getPost", "wp.deletePost"]


# ---------------------------------------------------------------------------
# _xmlrpc_post_status: only 404 faults map to "gone"; others propagate
# ---------------------------------------------------------------------------


def test_post_status_maps_404_fault_to_none():
    client = _make_client()
    with patch("wordpress_cli.client.requests.post", return_value=_fault_response(404, "Invalid post ID.")):
        assert client._xmlrpc_post_status(999) is None


def test_post_status_propagates_non_404_fault():
    client = _make_client()
    with patch("wordpress_cli.client.requests.post", return_value=_fault_response(403, "Not allowed.")):
        with pytest.raises(Exception) as exc:
            client._xmlrpc_post_status(999)
    assert "fault (403)" in str(exc.value)
