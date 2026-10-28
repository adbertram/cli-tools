"""Live message search: parsing, paging, link extraction, and verified sends."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from bricklink_cli import message_search as ms
from bricklink_cli.browser_runtime import BricklinkRuntimeBrowser, MESSAGE_DETAIL_SCRIPT
from bricklink_cli.commands.messages import _folder_code

ET = ZoneInfo("America/New_York")


def test_parse_sent_is_eastern_and_converts_to_central():
    dt = ms.parse_sent("Oct 24, 2026 21:04", ET)
    assert dt.astimezone(timezone.utc) == datetime(2026, 10, 25, 1, 4, tzinfo=timezone.utc)
    assert dt.astimezone(ZoneInfo("America/Chicago")).strftime("%H:%M") == "20:04"


def test_parse_bound_date_only_covers_whole_day():
    start = ms.parse_bound("2026-10-24")
    end = ms.parse_bound("2026-10-24", end=True)
    assert start.tzinfo and end.tzinfo
    assert (start.hour, start.minute) == (0, 0)
    assert (end.hour, end.minute) == (23, 59)


def test_extract_links_finds_schemeless_icloud_album_and_hrefs():
    body = "Photos here: photos.icloud.com/shared/album/0fat1UtTS-zTmFV6eY-yWMJlw. Thanks!"
    links = ms.extract_links(body, hrefs=["https://example.com/a"])
    assert links == ["photos.icloud.com/shared/album/0fat1UtTS-zTmFV6eY-yWMJlw", "https://example.com/a"]


def test_normalize_body_drops_br_doubling_keeps_paragraphs():
    assert ms.normalize_body("Hello, \n\n \n\nThanks  \n\nmore\n\n \n\n- Adam") == "Hello,\n\nThanks\nmore\n\n- Adam"


def _rows(*dates, start=1):
    return [{"message_id": str(start + i), "date": d} for i, d in enumerate(dates)]


def test_iter_live_rows_pages_until_older_than_since():
    pages = {1: _rows("Oct 28, 2026", "Oct 20, 2026", start=1),
             2: _rows("Oct 12, 2026", "Oct 1, 2026", start=10),
             3: _rows("Sep 1, 2026", start=20)}
    fetched = []

    def fetch(pg):
        fetched.append(pg)
        return pages.get(pg, [])

    ids = [r["message_id"] for r in ms.iter_live_rows(fetch, since_day=date(2026, 10, 5))]
    assert fetched == [1, 2]  # page 2 already reaches before Oct 5
    assert ids == ["1", "2", "10", "11"]


def test_iter_live_rows_stops_when_last_page_repeats():
    page = _rows("Oct 28, 2026")
    assert len(list(ms.iter_live_rows(lambda pg: page, since_day=None))) == 1


def test_iter_live_rows_raises_instead_of_silently_truncating():
    with pytest.raises(RuntimeError, match="max-pages"):
        list(ms.iter_live_rows(lambda pg: _rows("Oct 28, 2026", start=pg * 10), since_day=date(2026, 1, 1), max_pages=3))


def test_user_matches_is_case_insensitive_exact():
    assert ms.user_matches("Blockus", ["blockus"])
    assert not ms.user_matches("Blockus2", ["blockus"])
    assert ms.user_matches("anyone", None)


@pytest.mark.parametrize("value,code", [("outbox", "o"), ("o", "o"), ("sent", "o"), ("inbox", "i"), ("i", "i")])
def test_folder_code_maps_names(value, code):
    assert _folder_code(value) == code


class _FakeBrowser:
    _submit_page_notice = staticmethod(lambda page: "Message contains a link that is not allowed.")

    def __init__(self, pages):
        self.pages = list(pages)

    def list_messages_live(self, page_num=1, folder="i"):
        return self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]


class _Page:
    url = "https://www.bricklink.com/contact.asp?u=buyalo"

    def wait_for_timeout(self, ms):
        pass


def test_send_verification_requires_new_outbox_row_for_recipient():
    browser = _FakeBrowser([[{"message_id": "9", "username": "buyalo"}, {"message_id": "1", "username": "x"}]])
    row = BricklinkRuntimeBrowser._verify_sent_in_outbox(browser, _Page(), {"1"}, "buyalo")
    assert row["message_id"] == "9"


def test_send_verification_raises_when_outbox_unchanged():
    browser = _FakeBrowser([[{"message_id": "1", "username": "buyalo"}]])
    with pytest.raises(RuntimeError, match="NOT sent.*BrickLink said: 'Message contains a link"):
        BricklinkRuntimeBrowser._verify_sent_in_outbox(browser, _Page(), {"1"}, "buyalo")


def test_send_verification_ignores_new_row_to_someone_else():
    browser = _FakeBrowser([[{"message_id": "9", "username": "other"}]])
    with pytest.raises(RuntimeError, match="NOT sent"):
        BricklinkRuntimeBrowser._verify_sent_in_outbox(browser, _Page(), {"1"}, "buyalo")


DASH = "-" * 60
DETAIL_HTML = f"""<html><body><table>
<tr><td>Subject:&nbsp;&nbsp;&nbsp;</td><td><b>Re: Item condition</b>&nbsp;(<a href="/orderDetail.asp?ID=32870835">view order</a>)</td></tr>
<tr><td>Sent:&nbsp;</td><td>Oct 27, 2026 21:06</td></tr>
<tr><td>From:</td><td><b>geeklife&nbsp;<a href="/feedback.asp?u=geeklife">(1179)</a></b></td></tr>
<tr><td>To:</td><td><b>buyalo&nbsp;<a href="/feedback.asp?u=buyalo">(158)</a></b></td></tr>
<tr><td bgcolor="#EEEEEE">CAUTION: member message.<br>{DASH}<br>Hello Artem,
<br>
I put a coupon on your BrickLink account. Photos: <a href="https://photos.icloud.com/shared/album/072-fh7pHan3ZeYKA_bJFV-zA">album</a>
<br>
- Adam</td></tr></table>
<footer id="js-blp-footer">BrickLink About Us</footer></body></html>"""


def test_detail_script_keeps_text_after_word_bricklink_and_returns_links():
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        with sync_api.sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.set_content(DETAIL_HTML)
            info = page.evaluate(MESSAGE_DETAIL_SCRIPT)
            browser.close()
    except Exception as exc:  # pragma: no cover - environment without browsers
        pytest.skip(f"chromium unavailable: {exc}")
    assert info["sent_date"] == "Oct 27, 2026 21:06"
    assert info["to_username"] == "buyalo"
    assert info["order_id"] == "32870835"
    assert "BrickLink account. Photos:" in info["body"]
    assert info["body"].rstrip().endswith("- Adam")
    assert "About Us" not in info["body"]
    assert info["links"] == ["https://photos.icloud.com/shared/album/072-fh7pHan3ZeYKA_bJFV-zA"]
