"""Regression tests for the `groups posts list` silent-zero defect.

Reported 2026-08-25: eight of Adam's twenty-four joined LEGO groups answered
``[]`` on stdout at exit 0 while ``groups get`` reported ``posts_readable:
true`` for every one of them, and every failing run printed the same stderr
line -- "Group discussion preload missing; reading the rendered group feed
instead". A caller could not tell "this group had no new posts" from "the
extractor missed the posts that are there".

ROOT CAUSE, proven live: the profile stored an ``AUTH_COOKIES_JSON`` snapshot
whose ``xs`` session cookie no longer matched the one in the live Chromium
profile. Facebook answers a request carrying a dead session with HTTP 200 and
the LOGGED-OUT variant of the page (``CurrentUserInitialData.USER_ID == "0"``),
which renders the group's name, privacy, and member count but carries NO Relay
discussion preload. Every group therefore fell through to a rendered-feed DOM
scraper, which happened to find posts on sixteen of them and nothing on the
other eight.

FIXTURES are slices of live captures taken from Adam's authenticated session on
2026-08-25. Each file concatenates the verbatim ``CurrentUserInitialData``,
``DTSGInitialData``, and ``LSD`` defines with the verbatim +/-6000 character
window around the page's ``CometGroupDiscussionRootSuccessQuery`` marker -- the
exact region the parser reads. Only the two session tokens (DTSG and LSD) are
replaced with ``REDACTED_*`` placeholders; every group ID, query ID, and Relay
variable is untouched.

  - ``group_feed_preload_1457540554300292.txt`` -- "LEGO Trade & Discuss - USA",
    one of the eight groups that returned zero posts.
  - ``group_feed_preload_3367761036773668.txt`` -- "BrickOwl - Offers and Help",
    another of the eight.
  - ``group_feed_preload_vanity_slug_legosforsale.txt`` -- "THE LEGO BUY/SELL/
    TRADE PAGE (U.S.A)", requested by its vanity slug ``Legosforsale``. Its
    numeric ID is 266584920129216, and matching the slug against Facebook's
    numeric payload values is the SECOND defect this group exposed.
  - ``group_feed_logged_out_1457540554300292.txt`` -- the same group fetched
    with the stale cookie snapshot: USER_ID "0", no preload at all.
"""

from pathlib import Path

import pytest

from facebook_cli import client as client_mod
from facebook_cli.client import (
    GROUP_DISCUSSION_FRIENDLY_NAME,
    FacebookClient,
    FacebookSessionLoggedOut,
    FeedExtractionFailed,
    GroupDiscussionPreloadMissing,
    GroupNotReadable,
)

FIXTURES = Path(__file__).parent / "fixtures"

# (fixture stem, requested reference, canonical numeric group id)
PREVIOUSLY_ZERO_GROUPS = [
    ("group_feed_preload_1457540554300292", "1457540554300292", "1457540554300292"),
    ("group_feed_preload_3367761036773668", "3367761036773668", "3367761036773668"),
    ("group_feed_preload_vanity_slug_legosforsale", "Legosforsale", "266584920129216"),
]


def _fixture(stem: str) -> str:
    return (FIXTURES / f"{stem}.txt").read_text(encoding="utf-8")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(client_mod, "get_config", lambda: object())
    return FacebookClient()


# --- the preload is found on every group that used to answer [] --------------


@pytest.mark.parametrize("stem,group_ref,group_id", PREVIOUSLY_ZERO_GROUPS)
def test_authenticated_page_yields_the_discussion_preload(client, stem, group_ref, group_id):
    """Each of these pages HAS a preload. The old code never saw one."""
    body = _fixture(stem)

    variables, document_id = client._extract_group_discussion_request(body, group_ref)

    assert document_id.isdigit()
    assert variables["groupID"] == group_id
    assert "regular_stories_count" in variables
    assert "regular_stories_stream_initial_count" in variables


@pytest.mark.parametrize("stem,group_ref,group_id", PREVIOUSLY_ZERO_GROUPS)
def test_captured_pages_are_authenticated_before_any_selector_runs(client, stem, group_ref, group_id):
    """Guard the capture itself.

    A logged-out capture yields parsers that pass on fixtures and answer wrongly
    in production, so every preload fixture must prove a signed-in viewer.
    """
    client._assert_authenticated_html(_fixture(stem), f"https://www.facebook.com/groups/{group_ref}/")


def test_vanity_slug_resolves_to_the_numeric_id_facebook_payloads_use(client):
    """The second defect: a slug never equals the numeric ID in the payload.

    ``contains_group_id`` compared the requested reference against Relay values,
    so requesting ``Legosforsale`` scored every candidate at zero and the
    preload looked missing on a page that had one.
    """
    body = _fixture("group_feed_preload_vanity_slug_legosforsale")

    assert client._canonical_group_id(body, "Legosforsale") == "266584920129216"
    assert client._canonical_group_id(body, "266584920129216") == "266584920129216"


def test_unresolvable_group_reference_fails_instead_of_guessing(client):
    with pytest.raises(client_mod.ClientError) as excinfo:
        client._canonical_group_id('{"groupID":"111"}{"groupID":"222"}', "some-slug")

    assert "Cannot resolve Facebook group reference 'some-slug'" in str(excinfo.value)


# --- logged-out HTML is loud, never an empty feed ----------------------------


def test_logged_out_html_is_rejected_at_the_fetch_seam(client):
    """The root cause. HTTP 200, real page title, no signed-in viewer."""
    body = _fixture("group_feed_logged_out_1457540554300292")

    with pytest.raises(FacebookSessionLoggedOut) as excinfo:
        client._assert_authenticated_html(body, "https://www.facebook.com/groups/1457540554300292/")

    message = str(excinfo.value)
    assert message.startswith("LOGGED_OUT_HTML:")
    assert "USER_ID='0'" in message
    assert "facebook auth login --force" in message


def test_logged_out_capture_carries_no_discussion_preload(client):
    """Why the logged-out page looked like a group with nothing in it."""
    body = _fixture("group_feed_logged_out_1457540554300292")

    assert f'"queryName":"{GROUP_DISCUSSION_FRIENDLY_NAME}"' not in body
    with pytest.raises(GroupDiscussionPreloadMissing):
        client._extract_group_discussion_request(body, "1457540554300292")


def test_logged_out_html_exits_with_the_credential_code(client):
    """LOGGED_OUT_HTML is a credential failure: exit 2, not 1 and not 0."""
    from facebook_cli._helpers import report_client_error

    error = FacebookSessionLoggedOut("LOGGED_OUT_HTML: stale session")

    assert report_client_error(error) == 2


# --- the three failure modes stay tellable apart -----------------------------


def test_feed_extraction_failure_has_its_own_exit_code():
    from facebook_cli._helpers import FEED_EXTRACTION_FAILED_EXIT_CODE, report_client_error

    assert FEED_EXTRACTION_FAILED_EXIT_CODE == 3
    assert report_client_error(FeedExtractionFailed("FEED_EXTRACTION_FAILED: x")) == 3
    assert report_client_error(GroupNotReadable("UNREADABLE_GROUP: x")) == 1
    assert report_client_error(FacebookSessionLoggedOut("LOGGED_OUT_HTML: x")) == 2


def test_the_removed_rendered_feed_scraper_cannot_come_back():
    """No code path may answer a missing preload with a silent [] again."""
    assert not hasattr(FacebookClient, "_extract_group_posts")
    assert not hasattr(FacebookClient, "_list_group_post_summaries")


def test_empty_readable_group_is_still_an_empty_list(client, monkeypatch):
    """The one case that MUST stay [] at exit 0: a readable group with no posts."""
    body = _fixture("group_feed_preload_1457540554300292")
    monkeypatch.setattr(client, "_fetch_authenticated_facebook_bootstrap_html", lambda url: body)
    monkeypatch.setattr(
        client,
        "_graphql_group_discussion_posts",
        lambda group_id, body, count, after=None: ([], False, None),
    )
    monkeypatch.setattr(
        client,
        "_group_feed_unavailable",
        lambda group_id, cause: pytest.fail("an empty feed must not be diagnosed as a failure"),
    )

    assert client.list_group_posts("1457540554300292", limit=3) == []
