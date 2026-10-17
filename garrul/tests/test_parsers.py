"""Parser contracts, asserted against real DOM captured from Garrul v2.26.1."""

from pathlib import Path

import pytest

from garrul_cli import parsers

FIXTURES = Path(__file__).parent / "fixtures"
READER = "01K5ZZRDR00000000000000001"
# The seeded display name is stored with markup in it, so it proves entity decoding.
READER_NAME = "Reader O'Brien <b>&amp;</b>"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def broken(name: str, old: str, new: str) -> str:
    """Return a fixture with one piece of markup changed, proving the change applied."""
    html = load(name)
    assert old in html, f"{name} no longer contains {old!r}; the mutation test would be a no-op"
    return html.replace(old, new)


def test_queue_row_has_every_contract_field():
    page = parsers.parse_queue(load("queue_reported.html"))
    assert page["next_before"] is None
    (row,) = page["rows"]
    assert row["id"] == "01K5ZZREPT0000000000000001"
    assert row["status"] == "approved"
    assert row["post_slug"] == "cli-test-post"
    assert row["post_title"] == "CLI Test Post & Friends"
    assert row["host"] == "adamtheautomator.com"
    assert row["author_name"] == READER_NAME
    assert row["author_user_id"] == READER
    assert row["author_provider"] == "github"
    assert row["created_at"] == "2026-09-10T00:33Z"
    assert row["body_text"] == "Approved comment that readers reported."
    assert row["user_notes"] == 1


def test_queue_reports_open_report_count():
    rows = {row["id"]: row for row in parsers.parse_queue(load("queue_all.html"))["rows"]}
    assert all(isinstance(row["open_reports"], int) for row in rows.values())
    assert {row["status"] for row in rows.values()} >= {"approved", "spam"}


def test_queue_pagination_cursor_comes_from_the_server_link():
    page = parsers.parse_queue(load("queue_page1_cursor.html"))
    assert len(page["rows"]) == 50
    assert page["next_before"] == "1789100006000|01K5ZZBVLK0000000000000006"


def test_empty_queue_is_an_empty_list_not_an_error():
    assert parsers.parse_queue(load("queue_empty.html")) == {"rows": [], "next_before": None}


def test_comment_detail_supplies_parent_id_and_markdown():
    detail = parsers.parse_comment_detail(load("comment_reply.html"))
    assert detail["id"] == "01K5ZZPEND0000000000000002"
    assert detail["status"] == "pending"
    assert detail["parent_id"] == "01K5ZZAPPR0000000000000001"
    assert detail["parent"]["status"] == "approved"
    assert detail["body_md"] == "Pending reply to the approved parent."
    assert detail["author_user_id"] == READER


def test_top_level_comment_has_null_parent_and_keeps_raw_markdown():
    detail = parsers.parse_comment_detail(load("comment_pending.html"))
    assert detail["parent_id"] is None
    assert detail["body_md"].startswith("Pending **top-level** comment with <angle> brackets & an")
    assert [note["body"] for note in detail["notes"]] == ["Fixture note on the pending comment."]
    assert detail["notes"][0]["id"] == "01K5ZZNOTE0000000000000001"


def test_comment_detail_reports():
    detail = parsers.parse_comment_detail(load("comment_reported.html"))
    assert detail["open_reports"] == 2
    assert sorted(report["reason"] for report in detail["reports"]) == ["abuse", "spam"]


def test_moderated_comment_shows_reply_audit_and_admin_badge():
    detail = parsers.parse_comment_detail(load("comment_moderated.html"))
    assert detail["status"] == "approved"
    assert [entry["action"] for entry in detail["audit"]] == ["approve"]
    assert detail["audit"][0]["reason"] == "cli round trip"
    (reply,) = detail["replies"]
    assert reply["author_is_admin"] is True
    assert reply["author_name"] == "CLI Test Admin"


def test_users_list_and_ban_state():
    (user,) = parsers.parse_users(load("users_reader.html"))["rows"]
    assert user == {
        "id": READER,
        "name": READER_NAME,
        "email": "cli-reader@example.test",
        "provider": "github",
        "is_banned": False,
        "joined_on": "2026-09-10",
    }
    assert parsers.parse_users(load("users_banned.html"))["rows"][0]["is_banned"] is True
    assert parsers.parse_users(load("users_empty.html"))["rows"] == []


def test_user_detail():
    user = parsers.parse_user_detail(load("user_detail.html"))
    assert user["id"] == READER
    assert user["name"] == READER_NAME
    assert user["email"] == "cli-reader@example.test"
    assert user["role"] == "user"
    assert user["is_banned"] is False
    assert len(user["comments"]) == 50
    assert user["comments_next_before"] is not None
    assert {"ban", "unban"} <= {entry["action"] for entry in user["audit"]}
    assert parsers.parse_user_detail(load("user_detail_banned.html"))["is_banned"] is True


def test_audit_exposes_full_target_id_only_where_garrul_links_it():
    page = parsers.parse_audit(load("audit.html"))
    assert page["applied"] == {"action": "", "target_kind": ""}
    by_kind = {row["target_kind"]: row for row in page["rows"]}
    assert len(by_kind["comment"]["target_id"]) == 26
    assert by_kind["webhook"]["target_id"] is None
    assert len(by_kind["webhook"]["target_id_prefix"]) == 8
    assert isinstance(by_kind["webhook"]["meta"], dict)


def test_subscription_id_is_null_once_unsubscribed():
    rows = {row["status"]: row for row in parsers.parse_subscriptions(load("subscriptions.html"))["rows"]}
    assert rows["pending"]["id"] == "01K5ZZSUBS0000000000000002"
    assert rows["pending"]["email"] == "sub-pending@example.test"
    assert rows["unsubscribed"]["id"] is None


def test_webhooks():
    (hook,) = parsers.parse_webhooks(load("webhooks.html"))
    assert hook["id"] == "01M2R5BCGA193VTCQWK6921ETC"
    assert hook["url"] == "http://hooks.example.test/garrul"
    assert hook["adapter"] == "generic"
    assert hook["enabled"] is True
    detail = parsers.parse_webhook_detail(load("webhook_detail.html"), hook["id"])
    assert detail["events"] == ["comment.posted", "comment.approved"]
    assert "secret" not in detail


def test_settings_are_typed_by_group():
    rows = {row["key"]: row for row in parsers.parse_settings(load("settings.html"))}
    assert rows["votes_enabled"] == {"key": "votes_enabled", "group": "flags", "value": False}
    assert rows["comments_per_page"]["value"] == 25
    assert rows["default_sort"] == {"key": "default_sort", "group": "strings", "value": "old"}
    assert rows["security_contact"]["group"] == "texts"


def test_instance_pages():
    assert parsers.parse_about(load("about.html"))["version"] == "v2.26.1"
    stats = parsers.parse_dashboard(load("dashboard.html"))
    assert stats["overview"]["pending"] == "30"
    assert stats["by_host"][0]["host"] == "adamtheautomator.com"
    assert parsers.parse_operator(load("operator.html"))["rerender"] == {"current_version": 3, "up_to_date": 1980, "stale": 60}


def test_telegram_link_states():
    assert parsers.parse_telegram(load("telegram.html"))["linked"] is False
    linked = parsers.parse_telegram(load("telegram_linked.html"))
    assert linked["linked"] is True and linked["digest"] is True
    assert linked["linked_at"] == "2026-09-12T08:00Z"


@pytest.mark.parametrize(
    "parse",
    [parsers.parse_queue, parsers.parse_comment_detail, parsers.parse_users, parsers.parse_audit, parsers.parse_settings],
)
def test_access_denied_page_is_a_loud_error_never_an_empty_result(parse):
    with pytest.raises(parsers.ParseError):
        parse(load("unauthenticated.html"))


def test_changed_row_markup_is_a_loud_error():
    with pytest.raises(parsers.ParseError, match="comment id"):
        parsers.parse_queue(broken("queue_all.html", 'class="cid muted"', 'class="renamed"'))


def test_changed_empty_state_message_is_a_loud_error():
    with pytest.raises(parsers.ParseError, match="empty-table message"):
        parsers.parse_queue(broken("queue_empty.html", "No comments match.", "Nothing here."))


def test_missing_pager_is_a_loud_error():
    with pytest.raises(parsers.ParseError, match="pager"):
        parsers.parse_queue(broken("queue_all.html", 'class="pager"', 'class="gone"'))


def test_own_account_page_has_no_role_controls_but_still_parses():
    """Garrul hides the role buttons on your own page; the role comes from the header pill."""
    me = parsers.parse_user_detail(load("user_detail_self.html"))
    assert me["id"] == "01K5ZZADMN0000000000000001"
    assert me["name"] == "CLI Test Admin"  # the pill text must not leak into the name
    assert me["role"] == "admin"
    assert me["is_banned"] is False and me["is_erased"] is False


def test_role_and_ban_state_come_from_header_pills():
    assert parsers.parse_user_detail(load("user_detail_mod.html"))["role"] == "mod"
    assert parsers.parse_user_detail(load("user_detail_mod.html"))["name"] == READER_NAME
    banned = parsers.parse_user_detail(load("user_detail_banned.html"))
    assert banned["is_banned"] is True and banned["role"] == "user"


def test_unknown_header_badge_is_a_loud_error():
    with pytest.raises(parsers.ParseError, match="unrecognized badge"):
        parsers.parse_user_detail(broken("user_detail_mod.html", '<span class="pill mod">mod</span>', '<span class="pill vip">vip</span>'))


def test_missing_email_is_null_not_a_dash():
    html = broken("users_reader.html", "cli-reader@example.test", parsers.NO_VALUE)
    assert parsers.parse_users(html)["rows"][0]["email"] is None
    detail = broken("user_detail.html", "cli-reader@example.test · github", parsers.NO_VALUE + " · github")
    assert parsers.parse_user_detail(detail)["email"] is None


def test_webhook_events_is_always_a_list():
    assert parsers.parse_webhooks(load("webhooks.html"))[0]["events"] == ["comment.posted", "comment.approved"]
    everything = broken("webhooks.html", "comment.posted, comment.approved ·", "all events ·")
    assert parsers.parse_webhooks(everything)[0]["events"] == list(parsers.WEBHOOK_EVENTS)
