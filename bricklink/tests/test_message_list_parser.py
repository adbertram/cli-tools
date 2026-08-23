"""Validate the BrickLink message-list parser against real DOM snapshots.

The parser (``MESSAGE_LIST_SCRIPT``) is a JS fragment injected into
BrickLink's ``myMsg.asp`` list page. BrickLink marks unread / not-yet-replied
messages with a status icon (``/images/mailNew16.png``, alt/title
"Not Yet Replied") in the first column, and replied messages with
``/images/mailNewRe.png`` ("Already Replied"). It does NOT bold unread inbox
rows, so the previous ``<b>/<strong>``-only heuristic always returned
``is_unread: false`` and every inquiry was dropped by
``--filter is_unread:eq:true``.

These fixtures mirror the live DOM captured 2026-08-20.
"""

import pytest

from bricklink_cli.browser_runtime import MESSAGE_LIST_SCRIPT

playwright_sync = pytest.importorskip("playwright.sync_api", reason="playwright not installed")

UNREAD_ROW = (
    '<tr>'
    '<td><font face="Tahoma,Arial" size="2">&nbsp;'
    '<img src="/images/mailNew16.png" hspace="2" alt="Not Yet Replied" '
    'title="Not Yet Replied" width="16" height="16" align="ABSMIDDLE">&nbsp;'
    '<a href="/myMsg.asp?msgID=79032457&amp;a=i&amp;viewSort=D&amp;viewAsc=D">'
    'Re: Following Up on Your NSS Alert</a> '
    '(<a href="/orderDetail.asp?ID=31748542">view order</a>)</font></td>'
    '<td><font class="fv">&nbsp;<a href="/contact.asp?u=1mom">1mom</a></font></td>'
    '<td><font class="fv">&nbsp;Aug 19, 2026</font></td>'
    "</tr>"
)

READ_ROW = (
    '<tr>'
    '<td><font face="Tahoma,Arial" size="2">&nbsp;'
    '<img src="/images/mailNewRe.png" hspace="2" alt="Already Replied" '
    'title="Already Replied" width="16" height="16" align="ABSMIDDLE">&nbsp;'
    '<a href="/myMsg.asp?msgID=79020565&amp;a=o&amp;viewSort=D&amp;viewAsc=D">'
    'Following Up on Your NSS Alert</a> '
    '(<a href="/orderDetail.asp?ID=31748542">view order</a>)</font></td>'
    '<td><font class="fv">&nbsp;<a href="/contact.asp?u=1mom">1mom</a></font></td>'
    '<td><font class="fv">&nbsp;Aug 19, 2026</font></td>'
    "</tr>"
)

BOLD_UNREAD_ROW = (
    '<tr>'
    '<td><font face="Tahoma,Arial" size="2">&nbsp;'
    '<img src="/images/mailNew16.png" hspace="2" alt="Not Yet Replied" '
    'title="Not Yet Replied" width="16" height="16" align="ABSMIDDLE">&nbsp;'
    '<a href="/myMsg.asp?msgID=79034608&amp;a=o&amp;viewSort=D&amp;viewAsc=D">'
    '<b>Re: Following Up on Your NSS Alert</b></a> '
    '(<a href="/orderDetail.asp?ID=31748542">view order</a>)</font></td>'
    '<td><font class="fv">&nbsp;<a href="/contact.asp?u=1mom">1mom</a></font></td>'
    '<td><font class="fv">&nbsp;Aug 19, 2026</font></td>'
    "</tr>"
)


def _evaluate(rows_html):
    html = f"<table>{rows_html}</table>"
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page()
            page.set_content(html)
            return page.evaluate(MESSAGE_LIST_SCRIPT)
        finally:
            browser.close()


def test_unread_row_detected_via_not_yet_replied_icon():
    results = _evaluate(UNREAD_ROW)
    assert len(results) == 1
    assert results[0]["message_id"] == "79032457"
    assert results[0]["subject"] == "Re: Following Up on Your NSS Alert"
    assert results[0]["username"] == "1mom"
    assert results[0]["date"] == "Aug 19, 2026"
    assert results[0]["is_unread"] is True


def test_read_row_reported_as_read():
    results = _evaluate(READ_ROW)
    assert len(results) == 1
    assert results[0]["message_id"] == "79020565"
    assert results[0]["is_unread"] is False


def test_unread_and_read_rows_classified_independently():
    results = _evaluate(UNREAD_ROW + READ_ROW)
    by_id = {r["message_id"]: r for r in results}
    assert by_id["79032457"]["is_unread"] is True
    assert by_id["79020565"]["is_unread"] is False


def test_bold_subject_still_detected_as_unread():
    """The bold-subject fallback must remain for outbox rows."""
    results = _evaluate(BOLD_UNREAD_ROW)
    assert results[0]["is_unread"] is True
