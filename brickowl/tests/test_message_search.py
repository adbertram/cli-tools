"""Live, fully paged Brick Owl message search."""
from datetime import datetime, timezone

import pytest

from brickowl_cli import message_search as ms
from brickowl_cli.browser import BrickOwlBrowser, MESSAGE_ROWS_SCRIPT


def _row(mid, ts):
    return {"message_id": str(mid), "timestamp": ts, "from": "geeklife", "to": "buyer",
            "url": f"https://www.brickowl.com/user/1/messages/all/{mid}"}


class PagedPage:
    """Fake DataTables page: 'Next' advances through ``pages``."""

    url = "https://www.brickowl.com/user/1/messages/sent"

    def __init__(self, pages):
        self.pages, self.i, self.clicks = pages, 0, 0

    def goto(self, url):
        self.i = 0

    def wait_for_selector(self, *a, **k):
        return True

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script, arg=None):
        if script is MESSAGE_ROWS_SCRIPT:
            return self.pages[self.i]
        if "li.next');" in script:
            return self.i < len(self.pages) - 1
        if ".click()" in script:
            self.clicks += 1
            self.i += 1
            return None
        if "return a ? a.href" in script:
            return self.pages[self.i][0]["url"]
        raise AssertionError(script)


def _browser(pages):
    b = BrickOwlBrowser.__new__(BrickOwlBrowser)
    b._page = PagedPage(pages)
    b._ensure_authenticated = lambda: None
    b.get_user_id = lambda: "1"
    return b


def test_paged_listing_walks_every_page_without_since():
    b = _browser([[_row(30, 300), _row(29, 290)], [_row(20, 200)], [_row(10, 100)]])
    rows = b.list_messages_paged("sent")
    assert [r["message_id"] for r in rows] == ["30", "29", "20", "10"]
    assert b._page.clicks == 2


def test_paged_listing_stops_once_older_than_since():
    b = _browser([[_row(30, 300)], [_row(20, 200), _row(19, 150)], [_row(10, 100)]])
    rows = b.list_messages_paged("sent", since_ts=180)
    assert [r["message_id"] for r in rows] == ["30", "20", "19"]
    assert b._page.clicks == 1


def test_paged_listing_raises_when_cap_hit_before_since():
    b = _browser([[_row(30, 300)], [_row(20, 200)], [_row(10, 100)]])
    with pytest.raises(RuntimeError, match="max-pages"):
        b.list_messages_paged("sent", since_ts=1, max_pages=2)


def test_timestamp_is_utc_and_window_filter():
    dt = ms.from_timestamp(1787753708)
    assert dt == datetime(2026, 8, 26, 14, 15, 8, tzinfo=timezone.utc)
    assert ms.in_window(dt, ms.parse_bound("2026-08-26"), ms.parse_bound("2026-08-26", end=True))
    assert not ms.in_window(dt, ms.parse_bound("2026-08-27"), None)


def test_user_matches_from_or_to():
    assert ms.user_matches({"from": "geeklife", "to": "Timeless Bricks"}, ["timeless bricks"])
    assert ms.user_matches({"from": "Timeless Bricks", "to": "geeklife"}, ["Timeless Bricks"])
    assert not ms.user_matches({"from": "geeklife", "to": "Other"}, ["Timeless Bricks"])


def test_extract_links_includes_attachments():
    links = ms.extract_links("see photos.icloud.com/shared/album/abc_123", hrefs=["https://x.test/a.jpg"])
    assert links == ["photos.icloud.com/shared/album/abc_123", "https://x.test/a.jpg"]


ROW_HTML = """<table><tbody><tr>
<td class="dtr-control"><input type="checkbox" value="5306205"></td>
<td><div><span hidden="">1787753708</span>Aug 26, 2026, 14:15</div></td>
<td><span class="user-str">geeklife</span></td>
<td><span class="user-str">Cozziealex</span></td>
<td></td>
<td><a href="/user/992223/messages/all/5306205">Re: Missing Part Notification</a></td>
</tr></tbody></table>"""


def test_row_script_reads_hidden_epoch_timestamp():
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        with sync_api.sync_playwright() as pw:
            br = pw.chromium.launch()
            page = br.new_page()
            page.set_content(ROW_HTML)
            rows = page.evaluate(MESSAGE_ROWS_SCRIPT)
            br.close()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"chromium unavailable: {exc}")
    assert rows[0]["message_id"] == "5306205"
    assert rows[0]["timestamp"] == 1787753708
    assert rows[0]["date"] == "Aug 26, 2026, 14:15"
    assert (rows[0]["from"], rows[0]["to"]) == ("geeklife", "Cozziealex")
