"""Regression tests for the group-feed bootstrap read's stop markers.

Reported 2026-08-25: ``GROUP_DISCUSSION_BOOTSTRAP_MARKERS`` carried
``"queryID":"26647538378198347"`` -- the discussion query's document ID as it
stood when the marker list was written. Facebook rotates that ID, and by
2026-08-25 the live pages served 27950770684584803 instead. A stop marker that
no longer matches is SILENT: ``_read_response`` stops only once every marker is
present, so the marker set never completed and ``groups posts list`` downloaded
the whole ~2.8MB group page on every call instead of the ~482KB bootstrap slice.

Nothing was wrong with the answer -- a never-matching stop marker is strictly
safe -- and that is the point: the defect could only be found by measuring. The
fix is to key the read to strings that do not rotate (the Relay bootstrap
defines this client already parses by name, plus Facebook's own FRIENDLY name
for the query, the same string sent back as ``X-FB-Friendly-Name``), and to keep
a bounded tail so the extractor's window is not cut in half by stopping ON the
last marker.

Measured live 2026-08-25 against Adam's authenticated session:

    /groups/1457540554300292/   2,846,266 chars, friendly marker at 482,460
    /groups/Legosforsale/       3,099,382 chars, friendly marker at 482,628

Both pages carried exactly ONE occurrence of the friendly marker, carried the
stale doc ID nowhere at all, and served the discussion query as
``"queryID":"27950770684584803","variables":{...},"queryName":...`` -- i.e.
everything the parser reads sits BEFORE the marker, and the 6000 characters
after it hold no ``"queryID"`` and no ``"variables"`` at all. The tail is kept
anyway: field order is Facebook's to change, and a half-window would fail on
every group at once.
"""

import re
from pathlib import Path

import pytest

from cli_tools_shared.http_session import _read_response

from facebook_cli import client as client_mod
from facebook_cli.client import (
    GROUP_DISCUSSION_BOOTSTRAP_MARKERS,
    GROUP_DISCUSSION_BOOTSTRAP_TAIL_BYTES,
    GROUP_DISCUSSION_FRIENDLY_NAME,
    GROUP_DISCUSSION_WINDOW_CHARS,
    FacebookClient,
)

FIXTURES = Path(__file__).parent / "fixtures"

# The doc ID the marker list used to name, and the one Facebook served when the
# rot was measured. Neither may appear in the marker set.
RETIRED_DOC_ID = "26647538378198347"
LIVE_DOC_ID_2026_08_25 = "27950770684584803"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(client_mod, "get_config", lambda: object())
    return FacebookClient()


class _FakeResponse:
    """Minimal stand-in for the ``http.client`` response ``_read_response`` reads."""

    def __init__(self, body: bytes, chunk_size: int):
        self.body = body
        self.chunk_size = chunk_size
        self.offset = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self.body[self.offset:self.offset + self.chunk_size]
        self.offset += len(chunk)
        return chunk


def _bootstrap_slice() -> str:
    """A real captured bootstrap slice: defines plus the discussion-query window."""
    return (FIXTURES / "group_feed_preload_1457540554300292.txt").read_text(encoding="utf-8")


# --- the marker set names nothing that rotates -------------------------------


def test_no_bootstrap_marker_names_a_facebook_query_id():
    """The whole defect in one assertion.

    Facebook's numeric IDs are the one thing on that page guaranteed to change
    out from under a hard-coded string, and a stop marker that stops matching
    reports nothing.
    """
    for marker in GROUP_DISCUSSION_BOOTSTRAP_MARKERS:
        assert not re.search(r"\d{8,}", marker), (
            f"Bootstrap stop marker {marker!r} embeds a Facebook numeric ID. "
            "Facebook rotates those, and the read would silently stop stopping."
        )


def test_the_retired_doc_id_marker_cannot_come_back():
    assert not hasattr(client_mod, "GROUP_DISCUSSION_DOC_ID")
    joined = "".join(GROUP_DISCUSSION_BOOTSTRAP_MARKERS)
    assert RETIRED_DOC_ID not in joined
    assert LIVE_DOC_ID_2026_08_25 not in joined


def test_bootstrap_markers_are_the_defines_and_the_friendly_name():
    assert GROUP_DISCUSSION_BOOTSTRAP_MARKERS == [
        '["CurrentUserInitialData",',
        '["DTSGInitialData",',
        '["LSD",',
        f'"queryName":"{GROUP_DISCUSSION_FRIENDLY_NAME}"',
    ]


def test_the_tail_covers_the_extractor_window_in_the_worst_case():
    """The window is measured in characters; the tail in bytes.

    UTF-8 spends at most four bytes on a character, so the tail must be four
    times the window for the guarantee to hold on a page full of emoji.
    """
    assert GROUP_DISCUSSION_BOOTSTRAP_TAIL_BYTES >= 4 * GROUP_DISCUSSION_WINDOW_CHARS


# --- the bounded read still carries everything the parser needs --------------


def test_bootstrap_read_stops_early_and_still_parses(client):
    """Stand the real captured slice in front of the rest of a group page.

    The filler stands in for the ~2.4MB of rendered page that follows the
    bootstrap slice live. The read must not touch it, and what it does return
    must extract exactly what the untruncated body extracts.
    """
    captured = _bootstrap_slice()
    body = captured + ("<div>filler</div>" * 100_000)
    assert len(body) > 1_000_000

    raw = _read_response(
        _FakeResponse(body.encode("utf-8"), chunk_size=65536),
        GROUP_DISCUSSION_BOOTSTRAP_MARKERS,
        GROUP_DISCUSSION_BOOTSTRAP_TAIL_BYTES,
        65536,
        "utf-8",
    )
    read_text = raw.decode("utf-8")

    # Stopped: the whole captured slice arrived, the rest of the page did not.
    assert captured in read_text
    assert len(read_text) < len(body) / 2

    assert client._extract_group_discussion_request(
        read_text, "1457540554300292"
    ) == client._extract_group_discussion_request(body, "1457540554300292")


def test_a_read_that_stops_on_the_marker_still_holds_the_whole_window(client):
    """The captured window's own shape, asserted rather than assumed.

    ``_extract_group_discussion_request`` reads ``GROUP_DISCUSSION_WINDOW_CHARS``
    either side of the friendly-name marker. If Facebook ever moves the query's
    ``queryID``/``variables`` to AFTER that marker, the tail is what keeps the
    read from cutting them off -- so pin down which half they live in today, and
    let this test fail loudly on the day it changes.
    """
    body = _bootstrap_slice()
    marker = f'"queryName":"{GROUP_DISCUSSION_FRIENDLY_NAME}"'
    marker_end = body.find(marker) + len(marker)
    assert marker_end > len(marker)

    after_marker = body[marker_end:marker_end + GROUP_DISCUSSION_WINDOW_CHARS]
    assert '"queryID":' not in after_marker
    assert '"variables":' not in after_marker

    variables, document_id = client._extract_group_discussion_request(
        body[:marker_end], "1457540554300292"
    )
    assert (variables, document_id) == client._extract_group_discussion_request(
        body, "1457540554300292"
    )


# --- the fetch seam actually asks for the bounded read -----------------------


def test_bootstrap_fetch_passes_the_markers_and_the_tail_to_the_http_client(client, monkeypatch):
    """A tail nobody threads through is a tail nobody gets."""
    body = _bootstrap_slice()
    requested = {}

    class _FakeResult:
        text = body
        bytes_read = len(body)
        elapsed_seconds = 0.1

    class _FakeHttpClient:
        def get_text_result(self, url, stop_after_markers=(), stop_after_tail_bytes=0):
            requested.update(
                url=url,
                markers=list(stop_after_markers),
                tail=stop_after_tail_bytes,
            )
            return _FakeResult()

    monkeypatch.setattr(client, "_facebook_http_client", lambda: _FakeHttpClient())

    fetched = client._fetch_authenticated_facebook_bootstrap_html(
        "https://www.facebook.com/groups/1457540554300292/"
    )

    assert fetched == body
    assert requested == {
        "url": "https://www.facebook.com/groups/1457540554300292/",
        "markers": GROUP_DISCUSSION_BOOTSTRAP_MARKERS,
        "tail": GROUP_DISCUSSION_BOOTSTRAP_TAIL_BYTES,
    }


def test_post_thread_fetch_asks_for_no_tail(client, monkeypatch):
    """Only the group-feed read needs a window; the thread read stops at its marker."""
    requested = {}

    class _FakeResult:
        text = '["CurrentUserInitialData",[],{"USER_ID":"47201652"}]'
        bytes_read = 52
        elapsed_seconds = 0.1

    class _FakeHttpClient:
        def get_text_result(self, url, stop_after_markers=(), stop_after_tail_bytes=0):
            requested.update(markers=list(stop_after_markers), tail=stop_after_tail_bytes)
            return _FakeResult()

    monkeypatch.setattr(client, "_facebook_http_client", lambda: _FakeHttpClient())

    client._fetch_authenticated_facebook_page(
        "https://www.facebook.com/groups/1457540554300292/posts/1001/",
        stop_markers=client_mod.GROUP_POST_THREAD_STOP_MARKERS,
    )

    assert requested == {
        "markers": client_mod.GROUP_POST_THREAD_STOP_MARKERS,
        "tail": 0,
    }
