"""Transport rules: cookie use, both Origin gates, retry policy, error mapping."""

from types import SimpleNamespace

import pytest
import requests
from cli_tools_shared.exceptions import ClientError, CredentialError
from cli_tools_shared.filters import apply_filters

from garrul_cli import client as client_module
from garrul_cli.client import GarrulClient

INSTANCE = "https://comments.example.test"


class FakeResponse:
    def __init__(self, status=200, body=None, content_type="application/json", text="", headers=None):
        self.status_code = status
        self._body = body
        self.text = text
        # requests.Response.content is bytes; the shared retry policy reads it
        # directly (empty-403 detection), so this mock must carry it too.
        self.content = text.encode() if text else (b"" if body is None else b"1")
        self.headers = {"content-type": content_type, **(headers or {})}
        self.ok = status < 400

    def json(self):
        return self._body


@pytest.fixture
def garrul(monkeypatch):
    config = SimpleNamespace(instance_origin=INSTANCE, embed_origin="https://blog.example.test")
    instance = GarrulClient(config=config)
    instance._cookie = "__Host-garrul_sess=" + "a" * 64
    calls = []
    responses = []

    def fake_request(method, url, **kwargs):
        calls.append(SimpleNamespace(method=method, url=url, **kwargs))
        return responses.pop(0)

    monkeypatch.setattr(client_module.requests, "request", fake_request)
    return SimpleNamespace(client=instance, calls=calls, responses=responses)


def test_admin_mutation_sends_cookie_and_instance_origin(garrul):
    garrul.responses.append(FakeResponse(body={"ok": True, "id": "c1", "status": "approved"}))
    assert garrul.client.moderate_comment("c1", "approve", None)["status"] == "approved"
    (call,) = garrul.calls
    assert (call.method, call.url) == ("POST", f"{INSTANCE}/admin/api/comments/c1")
    assert call.headers["Origin"] == INSTANCE
    assert call.headers["Cookie"].startswith("__Host-garrul_sess=")
    assert call.json == {"action": "approve"}


def test_admin_read_sends_no_origin(garrul):
    garrul.responses.append(FakeResponse(body={"replies": []}))
    assert garrul.client.list_saved_replies() == []
    assert "Origin" not in garrul.calls[0].headers


def test_public_api_sends_embed_origin_and_no_cookie(garrul):
    garrul.responses.append(FakeResponse(body={"counts": {"a": 1}}))
    garrul.client.get_counts(["a"], [])
    headers = garrul.calls[0].headers
    assert headers["Origin"] == "https://blog.example.test"
    assert "Cookie" not in headers


def test_ids_cannot_inject_path_or_query(garrul):
    garrul.responses.append(FakeResponse(body={"ok": True}))
    garrul.client.delete_note("../users/x?role=admin")
    assert garrul.calls[0].url == f"{INSTANCE}/admin/api/notes/..%2Fusers%2Fx%3Frole%3Dadmin"


def test_401_is_a_credential_error(garrul):
    garrul.responses.append(FakeResponse(status=401, body={"error": "not_authenticated"}))
    with pytest.raises(CredentialError, match="garrul auth login"):
        garrul.client.list_saved_replies()


def test_403_not_authorized_is_a_credential_error(garrul):
    garrul.responses.append(FakeResponse(status=403, body={"error": "not_authorized"}))
    with pytest.raises(CredentialError):
        garrul.client.list_saved_replies()


def test_api_error_code_is_surfaced(garrul):
    garrul.responses.append(FakeResponse(status=400, body={"error": "body_too_long", "max": 10000}))
    with pytest.raises(ClientError, match="HTTP 400: body_too_long"):
        garrul.client.preview_markdown("x")


def test_html_not_found_message_is_surfaced(garrul):
    page = "<html><body><h1>Not found</h1><p>That comment does not exist.</p></body></html>"
    garrul.responses.append(FakeResponse(status=404, content_type="text/html", text=page))
    with pytest.raises(ClientError, match="That comment does not exist."):
        garrul.client.get_comment("missing")


def test_a_failed_mutation_is_never_resent(garrul):
    garrul.responses.extend([FakeResponse(status=503, body={"error": "busy"}), FakeResponse(body={"ok": True})])
    with pytest.raises(ClientError, match="HTTP 503"):
        garrul.client.reply_to_comment("c1", "hello", True, None)
    assert len(garrul.calls) == 1


def test_a_failed_read_is_retried(garrul, monkeypatch):
    monkeypatch.setattr("cli_tools_shared.http_session.time.sleep", lambda *_: None)
    garrul.responses.extend([FakeResponse(status=503, body={"error": "busy"}), FakeResponse(body={"replies": []})])
    assert garrul.client.list_saved_replies() == []
    assert len(garrul.calls) == 2


def test_network_failure_is_a_client_error(garrul, monkeypatch):
    def boom(*_args, **_kwargs):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(client_module.requests, "request", boom)
    with pytest.raises(ClientError, match="refused"):
        garrul.client.delete_note("n1")


def test_audit_filter_garrul_ignored_is_an_error(garrul):
    from pathlib import Path

    html = (Path(__file__).parent / "fixtures" / "audit.html").read_text(encoding="utf-8")
    garrul.responses.append(FakeResponse(content_type="text/html", text=html))
    with pytest.raises(ClientError, match="ignored action='not.a.real.action'"):
        garrul.client.list_audit({"action": "not.a.real.action"}, 10, None)


def test_limit_truncates_and_withholds_a_cursor_that_would_skip_rows(garrul):
    from pathlib import Path

    html = (Path(__file__).parent / "fixtures" / "users_reader.html").read_text(encoding="utf-8")
    garrul.responses.append(FakeResponse(content_type="text/html", text=html))
    result = garrul.client.list_users(None, 1, None)
    assert len(result["rows"]) == 1 and result["next_before"] is None
    with pytest.raises(ClientError, match="at least 1"):
        garrul.client.list_users(None, 0, None)


FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures"


def html(name):
    return FakeResponse(content_type="text/html", text=(FIXTURES / name).read_text(encoding="utf-8"))


def test_limit_that_cuts_the_last_page_still_reports_more_rows(garrul):
    garrul.responses.append(html("queue_all.html"))
    result = garrul.client.list_comments({"status": "all"}, 2, None)
    assert len(result["rows"]) == 2 and result["more"] is True and result["next_before"] is None


def test_listing_does_not_fetch_detail_pages_until_asked(garrul):
    garrul.responses.append(html("queue_all.html"))
    rows = garrul.client.list_comments({"status": "all"}, 100, None)["rows"]
    assert len(garrul.calls) == 1 and "parent_id" not in rows[0]
    garrul.responses.append(html("comment_reply.html"))
    (enriched,) = garrul.client.add_comment_details(rows[:1])
    assert enriched["parent_id"] == "01K5ZZAPPR0000000000000001" and len(garrul.calls) == 2


@pytest.mark.parametrize("cursor", ["garbage", "", "|", "abc|def", "1789100006000", "1789100006000|a|b", "1|x\n"])
def test_malformed_cursor_is_rejected_before_any_request(garrul, cursor):
    with pytest.raises(ClientError, match="Invalid --before"):
        garrul.client.list_users(None, 10, cursor)
    assert garrul.calls == []


@pytest.mark.parametrize("day", ["garbage", "09/17/2026", "2026-13-45", "2026-9-1", ""])
def test_unparseable_date_is_rejected_before_any_request(garrul, day):
    with pytest.raises(ClientError, match="Invalid --from"):
        garrul.client.list_comments({"status": "all", "from": day}, 10, None)
    with pytest.raises(ClientError, match="Invalid --to"):
        garrul.client.list_audit({"to": day}, 10, None)
    assert garrul.calls == []


@pytest.mark.parametrize("value", [".", ".."])
def test_dot_segments_are_rejected(garrul, value):
    with pytest.raises(ClientError, match="not a valid id"):
        garrul.client.get_comment(value)
    assert garrul.calls == []


def test_non_json_body_names_the_request_and_warns_about_the_mutation(garrul):
    garrul.responses.append(FakeResponse(content_type="text/html", text="<html>challenge</html>"))

    def not_json():
        raise ValueError("Expecting value")

    garrul.responses[0].json = not_json
    with pytest.raises(ClientError, match=r"POST /admin/api/comments/c1 returned HTTP 200.*may or may not have been applied"):
        garrul.client.moderate_comment("c1", "approve", None)


def test_unexpected_redirect_is_an_error(garrul):
    garrul.responses.append(FakeResponse(status=302, content_type="text/html", headers={"location": "https://elsewhere.example.test/"}))
    with pytest.raises(ClientError, match="HTTP 302: unexpected redirect to 'https://elsewhere.example.test/'"):
        garrul.client.list_saved_replies()


def test_feed_must_be_atom(garrul):
    garrul.responses.append(FakeResponse(content_type="text/plain", text="Garrul landing page"))
    with pytest.raises(ClientError, match="not an Atom feed"):
        garrul.client.get_feed("a-post")


def test_settings_typo_changes_nothing(garrul):
    garrul.responses.append(html("settings.html"))
    with pytest.raises(ClientError, match="no setting named 'comments_enable'. Nothing was changed"):
        garrul.client.update_settings({"flags": {"comments_enable": False}})
    assert [call.method for call in garrul.calls] == ["GET"]


def test_setting_sent_under_the_wrong_group_changes_nothing(garrul):
    garrul.responses.append(html("settings.html"))
    with pytest.raises(ClientError, match="comments_per_page is a numbers setting, not flags"):
        garrul.client.update_settings({"flags": {"comments_per_page": True}})
    assert [call.method for call in garrul.calls] == ["GET"]


def test_clamped_setting_is_reported_not_swallowed(garrul):
    garrul.responses.extend([html("settings.html"), FakeResponse(body={"ok": True, "flags": {}, "numbers": {"comments_per_page": 200}, "strings": {}, "texts": {}})])
    with pytest.raises(ClientError, match="stored 200 for comments_per_page, not 9999"):
        garrul.client.update_settings({"numbers": {"comments_per_page": 9999}})


# --------------------------------------------------------------------------
# Finding 1 (chaos-engineer report): --filter only saw the first --limit raw
# rows fetched, so a filter Garrul cannot apply itself silently returned fewer
# rows than actually exist -- or none at all, exit 0. `_pages` now keeps
# paging (up to MAX_SCAN_PAGES) until `limit` POST-FILTER rows are collected
# whenever a `post_filter` is supplied.
# --------------------------------------------------------------------------


def _ne_approved(rows):
    return apply_filters(rows, ["status:ne:approved"])


def test_filter_the_pagination_window_previously_hid_now_returns_the_full_limit(garrul):
    """Reproduces: `comments list -f status:ne:approved --limit 10` used to return only
    the pending rows inside the first 10 RAW rows fetched (5), not the first 10 MATCHES.
    """
    garrul.responses.append(html("queue_page1_cursor.html"))  # 50 rows, alternating pending/approved

    # The old behavior, still reachable by not passing post_filter: _pages stops once
    # 10 RAW rows are fetched, then a caller's apply_filters narrows only that slice.
    old_style = garrul.client.list_comments({"status": "all"}, 10, None)
    assert len(old_style["rows"]) == 10
    old_style_matches = _ne_approved(old_style["rows"])
    assert len(old_style_matches) == 5  # the bug: half of a 10-row --limit silently dropped

    # The fix: pass post_filter so _pages' own `limit` check counts MATCHES.
    garrul.responses.append(html("queue_page1_cursor.html"))
    fixed = garrul.client.list_comments({"status": "all"}, 10, None, post_filter=_ne_approved)
    assert len(fixed["rows"]) == 10
    assert all(row["status"] != "approved" for row in fixed["rows"])
    # Only one page was needed: page one alone already has 25 matches (>= limit 10).
    assert len(garrul.calls) == 2  # one call per list_comments() above


def test_filter_scan_reaches_a_match_beyond_the_first_page(garrul):
    """Reproduces: `comments list -f id:eq:<id> --limit 10` returned `[]` even though the
    comment existed, because it sat past the raw-row scan window (queue position 62).
    """
    target_id = "01K5ZZSPAM0000000000000001"  # only present on page two (queue_all.html)
    match_target = lambda rows: apply_filters(rows, [f"id:eq:{target_id}"])  # noqa: E731

    garrul.responses.append(html("queue_page1_cursor.html"))  # page 1: 50 rows, no match, has a cursor
    garrul.responses.append(html("queue_all.html"))  # page 2: final page, contains the match
    result = garrul.client.list_comments({"status": "all"}, 10, None, post_filter=match_target)

    assert [row["id"] for row in result["rows"]] == [target_id]
    assert result["next_before"] is None and result["more"] is False
    assert len(garrul.calls) == 2  # both pages were fetched to find the one match


def test_filter_scan_stops_at_the_raw_page_count_when_nothing_is_uncovered(garrul):
    """post_filter=None (the fully-covered fast path) is untouched: one page, raw count rules."""
    garrul.responses.append(html("queue_all.html"))
    result = garrul.client.list_comments({"status": "all"}, 2, None, post_filter=None)
    assert len(result["rows"]) == 2 and len(garrul.calls) == 1


def test_filter_scan_fails_loudly_instead_of_paging_forever_or_truncating_silently(garrul, monkeypatch):
    monkeypatch.setattr(client_module, "MAX_SCAN_PAGES", 2)
    pages = [
        {"rows": [{"n": i} for i in range(50)], "next_before": f"cursor-{page}"}
        for page in range(5)
    ]
    calls = iter(pages)
    parse = lambda _html: next(calls)  # noqa: E731
    never_matches = lambda rows: [row for row in rows if row["n"] < 0]  # noqa: E731

    garrul.responses.extend(FakeResponse(content_type="text/html", text="<html></html>") for _ in range(2))
    with pytest.raises(ClientError, match=r"scanned 2 pages \(100 rows\) without collecting 5 matching rows"):
        garrul.client._pages("/admin/queue", {}, parse, 5, None, post_filter=never_matches)
    assert len(garrul.calls) == 2  # stopped scanning at the safety bound, did not fetch a third page


# --------------------------------------------------------------------------
# Finding 2 (chaos-engineer report): a mutation (non-GET) that fails AFTER the
# request was sent must say the outcome is ambiguous. Only _json's non-JSON-body
# branch carried that note before this fix.
# --------------------------------------------------------------------------


def test_network_timeout_on_a_mutation_warns_the_change_may_be_ambiguous(garrul, monkeypatch):
    def boom(*_args, **_kwargs):
        raise requests.exceptions.ReadTimeout("Read timed out")

    monkeypatch.setattr(client_module.requests, "request", boom)
    with pytest.raises(ClientError, match=r"failed: Read timed out.*may or may not have been applied"):
        garrul.client.erase_user("u1", False, None)


def test_network_timeout_on_a_read_has_no_ambiguity_note(garrul, monkeypatch):
    def boom(*_args, **_kwargs):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(client_module.requests, "request", boom)
    with pytest.raises(ClientError) as excinfo:
        garrul.client.list_saved_replies()
    assert "may or may not have been applied" not in str(excinfo.value)


def test_redirect_on_a_mutation_warns_the_change_may_be_ambiguous(garrul):
    garrul.responses.append(FakeResponse(status=302, content_type="text/html", headers={"location": "https://elsewhere.example.test/"}))
    with pytest.raises(ClientError, match=r"HTTP 302: unexpected redirect.*may or may not have been applied"):
        garrul.client.moderate_comment("c1", "approve", None)


def test_error_status_on_a_read_has_no_ambiguity_note(garrul):
    page = "<html><body><h1>Not found</h1><p>Nope.</p></body></html>"
    garrul.responses.append(FakeResponse(status=404, content_type="text/html", text=page))
    with pytest.raises(ClientError) as excinfo:
        garrul.client.get_comment("missing")
    assert "may or may not have been applied" not in str(excinfo.value)


def test_settings_response_missing_the_group_is_a_clear_error_not_a_keyerror(garrul):
    garrul.responses.extend([html("settings.html"), FakeResponse(body={"ok": True})])
    with pytest.raises(ClientError, match=r"no 'numbers' group\. The change may or may not have been applied"):
        garrul.client.update_settings({"numbers": {"comments_per_page": 30}})


def test_settings_response_missing_the_key_is_a_clear_error_not_a_keyerror(garrul):
    garrul.responses.extend(
        [html("settings.html"), FakeResponse(body={"ok": True, "flags": {}, "numbers": {}, "strings": {}, "texts": {}})]
    )
    with pytest.raises(ClientError, match=r"no 'comments_per_page' in the 'numbers' group\. The change may or may not have been applied"):
        garrul.client.update_settings({"numbers": {"comments_per_page": 30}})
