"""Group membership, privacy, and readability tests against real Facebook DOM.

Fixtures under ``tests/fixtures/`` are verbatim captures from Adam's
authenticated Facebook session on 2026-08-25:

  - ``group_header_public_member.script.txt`` -- the single ``<script>`` on
    /groups/2318028917/ carrying ``profile_header_renderer``: a PUBLIC group the
    account has JOINED ("BrickLink Worldwide Buyers and Sellers").
  - ``group_header_private_member.script.txt`` -- the same script from
    /groups/1865822383631015/: a PRIVATE group the account has JOINED
    ("LEGO STAR WARS - Buy, Sell & Trade. (FOR DIEHARD FANS )").
  - ``group_header_public_non_member.script.txt`` -- from /groups/250458852075384/:
    a PUBLIC group the account has never joined.
  - ``group_header_private_pending.script.txt`` -- from /groups/1647953932130640/:
    a PRIVATE group whose join request is PENDING ("The Lego Group - Buy, Sell &
    Swap"). This is the group that made ``groups posts list`` return ``[]`` with
    exit code 0, indistinguishable from a group with no posts.
  - ``groups_joins_main.html`` -- the ``[role="main"]`` subtree of
    /groups/joins/, holding Facebook's own "Pending group requests" and "All
    groups you've joined" sections. Its rows are what the previous extractor
    mis-read as the literal name "View group".

The joined-groups extractor is browser-evaluated JavaScript, so its fixture is
loaded into a real headless Chromium page via ``set_content`` and the exact
production JS constant is evaluated against it.
"""

from pathlib import Path

import pytest
from cli_tools_shared.exceptions import ClientError
from playwright.sync_api import sync_playwright

from facebook_cli.client import (
    GROUP_JOIN_STATE_MEMBERSHIP,
    GROUP_PRIVACY_TITLES,
    JOINED_GROUPS_JS,
    JOINED_GROUPS_SECTION_MEMBERSHIP,
    FacebookClient,
    GroupNotReadable,
)
from facebook_cli.models import Group

FIXTURES = Path(__file__).parent / "fixtures"

# (fixture stem, group id, privacy, membership, posts_readable, name)
GROUP_HEADER_CASES = [
    (
        "group_header_public_member",
        "2318028917",
        "public",
        "member",
        True,
        "BrickLink Worldwide Buyers and Sellers",
    ),
    (
        "group_header_private_member",
        "1865822383631015",
        "private",
        "member",
        True,
        "LEGO STAR WARS - Buy, Sell & Trade. (FOR DIEHARD FANS )",
    ),
    (
        "group_header_public_non_member",
        "250458852075384",
        "public",
        "non_member",
        True,
        "Lego sets- Retired And Hard To Find, Buy, For sale And Trade",
    ),
    (
        "group_header_private_pending",
        "1647953932130640",
        "private",
        "pending",
        False,
        "The Lego Group - Buy, Sell & Swap",
    ),
]


class HeaderScriptPage:
    """Stands in for the live group page, serving captured header scripts."""

    def __init__(self, scripts):
        self.scripts = scripts

    def evaluate(self, script, arg=None):
        if "profile_header_renderer" not in script:
            raise AssertionError(f"Unexpected page.evaluate call: {script[:80]}")
        return self.scripts


def _header_page(*stems):
    scripts = [
        (FIXTURES / f"{stem}.script.txt").read_text(encoding="utf-8") for stem in stems
    ]
    return HeaderScriptPage(scripts)


def _evaluate(html: str, js: str, arg=None):
    """Evaluate a production extractor against fixture DOM in real Chromium."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        result = page.evaluate(js, arg) if arg is not None else page.evaluate(js)
        browser.close()
    return result


@pytest.fixture(scope="module")
def joins_main_html() -> str:
    return (FIXTURES / "groups_joins_main.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def joined_groups_result(joins_main_html):
    return _evaluate(
        joins_main_html,
        JOINED_GROUPS_JS,
        [list(entry) for entry in JOINED_GROUPS_SECTION_MEMBERSHIP],
    )


# --- Group state: privacy, membership, readability ---------------------------


@pytest.mark.parametrize(
    "stem,group_id,privacy,membership,posts_readable,name", GROUP_HEADER_CASES
)
def test_group_state_reports_live_privacy_membership_and_readability(
    stem, group_id, privacy, membership, posts_readable, name
):
    """Every (privacy, membership) combination this account can produce."""
    state = FacebookClient()._extract_group_state(_header_page(stem), group_id)

    assert state["group_id"] == group_id
    assert state["name"] == name
    assert state["privacy"] == privacy
    assert state["membership"] == membership
    assert state["posts_readable"] is posts_readable
    assert state["member_count"]


def test_pending_membership_is_not_reported_as_member_or_non_member():
    """The reported defect: a pending join request must be its own state.

    Reporting it as "non_member" would be wrong (the request exists) and
    reporting it as "member" would restore the silent-empty bug.
    """
    state = FacebookClient()._extract_group_state(
        _header_page("group_header_private_pending"), "1647953932130640"
    )

    assert state["membership"] == "pending"
    assert state["posts_readable"] is False


def test_group_state_scopes_to_the_requested_group_not_a_related_card():
    """A group page also embeds "Related groups" cards with their own join
    state. Reading the wrong header would answer for the wrong group."""
    client = FacebookClient()
    page = _header_page("group_header_private_pending", "group_header_public_member")

    assert client._extract_group_state(page, "1647953932130640")["membership"] == "pending"
    assert client._extract_group_state(page, "2318028917")["membership"] == "member"


def test_group_state_fails_when_no_header_matches_the_requested_group():
    with pytest.raises(ClientError) as excinfo:
        FacebookClient()._extract_group_state(
            _header_page("group_header_public_member"), "999999999999999"
        )

    assert "Expected exactly one Facebook group profile header" in str(excinfo.value)


def test_group_state_resolves_a_vanity_slug_to_the_numeric_group_id():
    """`groups get legodisplay` cannot match the payload id by string, so a
    single header on the page is the requested group's own header."""
    state = FacebookClient()._extract_group_state(
        _header_page("group_header_public_member"), "some-vanity-slug"
    )

    assert state["group_id"] == "2318028917"


def test_group_state_rejects_an_unverified_join_state():
    """An unknown viewer_join_state must raise, not default to non_member:
    guessing non_member for a state that means member would silently mark a
    readable group unreadable."""
    payload = (FIXTURES / "group_header_public_member.script.txt").read_text(encoding="utf-8")
    mutated = payload.replace('"viewer_join_state":"MEMBER"', '"viewer_join_state":"BRAND_NEW"')
    assert mutated != payload

    with pytest.raises(ClientError) as excinfo:
        FacebookClient()._extract_group_state(HeaderScriptPage([mutated]), "2318028917")

    assert "Unsupported Facebook viewer_join_state" in str(excinfo.value)


def test_group_state_rejects_an_unverified_privacy_label():
    payload = (FIXTURES / "group_header_public_member.script.txt").read_text(encoding="utf-8")
    mutated = payload.replace('"text":"Public group"', '"text":"Neighborhood group"')
    assert mutated != payload

    with pytest.raises(ClientError) as excinfo:
        FacebookClient()._extract_group_state(HeaderScriptPage([mutated]), "2318028917")

    assert "Unsupported Facebook group privacy label" in str(excinfo.value)


def test_group_state_fails_when_the_page_carries_no_header_payload():
    with pytest.raises(ClientError) as excinfo:
        FacebookClient()._extract_group_state(HeaderScriptPage([]), "2318028917")

    assert "Expected exactly one Facebook group profile header" in str(excinfo.value)


def test_join_state_and_privacy_tables_cover_only_verified_tokens():
    assert set(GROUP_JOIN_STATE_MEMBERSHIP.values()) == {"member", "pending", "non_member"}
    assert set(GROUP_PRIVACY_TITLES.values()) == {"public", "private"}


# --- posts list: unreadable must not look like empty -------------------------


class FeedPage:
    """A group feed page that is never scrolled, because the read fails first."""

    def __init__(self, scripts):
        self.scripts = scripts
        self.url = "https://www.facebook.com/groups/1647953932130640/"
        self.scrolled = False

    def evaluate(self, script, arg=None):
        if "profile_header_renderer" in script:
            return self.scripts
        # _assert_authenticated_page's login/challenge probe.
        return {"loginForm": False, "recaptcha": False}

    def wait_for_timeout(self, milliseconds):
        return None

    def keyboard_press(self, key):
        self.scrolled = True


def _client_with_feed_page(page):
    client = FacebookClient()
    client._get_page = lambda url, settle_ms=3000: page
    return client


def test_posts_list_fails_loudly_for_a_pending_private_group():
    """The reported defect: `[]` with exit 0 for a group Adam cannot see."""
    page = FeedPage([(FIXTURES / "group_header_private_pending.script.txt").read_text(encoding="utf-8")])
    client = _client_with_feed_page(page)

    with pytest.raises(GroupNotReadable) as excinfo:
        client._list_group_post_summaries("1647953932130640", 2)

    message = str(excinfo.value)
    assert message.startswith("UNREADABLE_GROUP:")
    assert "privacy=private" in message
    assert "membership=pending" in message
    assert page.scrolled is False


def test_posts_list_readability_gate_passes_a_public_group_for_a_non_member():
    """A public group must stay readable for a non-member, so the gate does not
    turn a working crawl into a failure."""
    page = FeedPage(
        [(FIXTURES / "group_header_public_non_member.script.txt").read_text(encoding="utf-8")]
    )
    page.url = "https://www.facebook.com/groups/250458852075384/"
    client = _client_with_feed_page(page)
    client._extract_group_posts = lambda _page: []

    assert client._list_group_post_summaries("250458852075384", 2) == []


def test_group_not_readable_is_a_client_error_so_the_command_exits_non_zero():
    assert issubclass(GroupNotReadable, ClientError)


# --- groups list: ids and names for every row --------------------------------


def test_joined_groups_returns_an_id_and_a_real_name_for_every_row(joined_groups_result):
    """The reported defect: names degraded to the literal string "View group"."""
    groups = joined_groups_result["groups"]

    assert joined_groups_result["main_exists"] is True
    assert joined_groups_result["unparsed"] == []
    assert len(groups) >= 30
    assert all(row["group_id"] for row in groups)
    assert all(row["name"] for row in groups)
    assert not any(row["name"] == "View group" for row in groups)
    assert len({row["group_id"] for row in groups}) == len(groups)


def test_joined_groups_reports_real_names_from_the_captured_page(joined_groups_result):
    by_id = {row["group_id"]: row["name"] for row in joined_groups_result["groups"]}

    assert by_id["2318028917"] == "BrickLink Worldwide Buyers and Sellers"
    assert by_id["1865822383631015"] == "LEGO STAR WARS - Buy, Sell & Trade. (FOR DIEHARD FANS )"
    assert by_id["legodisplay"] == "LEGO Retail Displays - WORLDWIDE Buy/Sell/Swap/Show/Appraise"
    assert by_id["1532129557644306"] == "Worldwide Adult Fans Of LEGO (WAFOL)"


def test_joined_groups_separates_pending_requests_from_joined_groups(joined_groups_result):
    by_id = {row["group_id"]: row["membership"] for row in joined_groups_result["groups"]}

    assert by_id["2318028917"] == "member"
    assert by_id["1865822383631015"] == "member"
    # The pending group from the readability fixtures, on the same live page.
    assert by_id["1647953932130640"] == "pending"


def test_joined_groups_extractor_emits_joined_rows_before_pending_rows(joined_groups_result):
    """Facebook renders pending requests ABOVE the joined list, so extraction
    order decides which rows survive a small --limit."""
    memberships = [row["membership"] for row in joined_groups_result["groups"]]

    assert memberships.count("member") > 0
    assert memberships.count("pending") > 0
    assert memberships == sorted(memberships, key=lambda value: value != "member")


def test_list_joined_groups_groups_members_ahead_of_pending_across_scrolls(monkeypatch):
    """Each scrolled batch appends more joined rows after the pending ones, so
    the collected result must be regrouped before it is returned."""
    import facebook_cli.client as client_mod

    class FakePage:
        def wait_for_selector(self, selector, timeout=None):
            return None

    monkeypatch.setattr(client_mod, "get_config", lambda: object())
    client = FacebookClient()
    monkeypatch.setattr(client, "_get_page", lambda url, settle_ms=3000: FakePage())
    monkeypatch.setattr(
        client,
        "_scroll_collect",
        lambda page, extract_fn, id_key, limit, label: [
            {"group_id": "1", "name": "Joined one", "url": "u1", "membership": "member"},
            {"group_id": "2", "name": "Requested", "url": "u2", "membership": "pending"},
            {"group_id": "3", "name": "Joined two", "url": "u3", "membership": "member"},
        ],
    )

    groups = client.list_joined_groups(limit=10)

    assert [group.group_id for group in groups] == ["1", "3", "2"]
    assert [group.membership for group in groups] == ["member", "member", "pending"]


def test_joined_groups_builds_a_usable_url_for_every_row(joined_groups_result):
    for row in joined_groups_result["groups"]:
        assert row["url"] == f"https://www.facebook.com/groups/{row['group_id']}/"


def test_joined_groups_rows_survive_model_validation(joined_groups_result):
    groups = [Group(**row) for row in joined_groups_result["groups"]]

    assert all(group.membership in ("member", "pending") for group in groups)
    # Facebook renders neither on this page, so they must stay unread, not guessed.
    assert all(group.privacy is None for group in groups)
    assert all(group.posts_readable is None for group in groups)
    assert all(group.member_count is None for group in groups)


def test_joined_groups_reports_a_page_without_a_main_subtree():
    result = _evaluate(
        "<div><a href='https://www.facebook.com/groups/123/'>x</a></div>",
        JOINED_GROUPS_JS,
        [list(entry) for entry in JOINED_GROUPS_SECTION_MEMBERSHIP],
    )

    assert result == {"main_exists": False, "groups": [], "unparsed": []}


def test_joined_groups_extractor_raises_on_an_unreadable_row():
    """A row under an unrecognized heading must fail loudly rather than be
    dropped, so `groups list` can never under-report reachable groups."""
    class FakePage:
        def evaluate(self, script, arg=None):
            return {
                "main_exists": True,
                "groups": [],
                "unparsed": [{"heading": "Groups you manage", "refs": ["123"], "names": [], "text": ""}],
            }

    with pytest.raises(ClientError) as excinfo:
        FacebookClient()._extract_joined_groups(FakePage())

    assert "could not read" in str(excinfo.value)
    assert "Groups you manage" in str(excinfo.value)
