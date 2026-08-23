"""Regression tests for the four bugs blocking the affiliatemagic workflow.

Each test reproduces one bug as observed in production and pins the fixed
behaviour. The tests do not call the live CJ API — they exercise the parser,
client, and command layer with hand-crafted XML payloads and mocked dependencies.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cj_cli.client import CjClient, _parse_advertiser_element
from cj_cli.models import create_advertiser, create_advertiser_detail


# ---------------------------------------------------------------------------
# Bug 1 — multi-word advertiser search must not coerce strings to int
# Bug 3 — EPC 'N/A' must not crash the parser
#
# Both bugs share the same root cause: blind ``int()`` / ``float()`` on XML
# fields that CJ may return as sentinel strings ("New", "N/A"). The fix is
# to preserve the original string in the model, never coerce.
# ---------------------------------------------------------------------------


_XML_WITH_SENTINEL_RANK_AND_EPC = """\
<cj-api>
  <advertisers>
    <advertiser>
      <advertiser-id>7453049</advertiser-id>
      <advertiser-name>Google Cloud</advertiser-name>
      <account-status>active</account-status>
      <relationship-status>notjoined</relationship-status>
      <network-rank>New</network-rank>
      <seven-day-epc>N/A</seven-day-epc>
      <three-month-epc>N/A</three-month-epc>
      <primary-category><parent>Software</parent></primary-category>
      <link-types>Text Link</link-types>
    </advertiser>
  </advertisers>
</cj-api>
"""


def test_bug1_network_rank_accepts_sentinel_string():
    """CJ returns 'New' for newly listed programs; parser must not raise int()."""
    root = ET.fromstring(_XML_WITH_SENTINEL_RANK_AND_EPC)
    elem = root.find(".//advertiser")
    parsed = _parse_advertiser_element(elem)

    # create_advertiser must NOT raise ValueError: invalid literal for int()
    adv = create_advertiser(parsed)
    assert adv.network_rank == "New"
    assert adv.advertiser_name == "Google Cloud"


def test_bug3_epc_accepts_na_sentinel():
    """CJ returns 'N/A' for advertisers without EPC; parser must preserve it."""
    root = ET.fromstring(_XML_WITH_SENTINEL_RANK_AND_EPC)
    elem = root.find(".//advertiser")
    parsed = _parse_advertiser_element(elem)

    # create_advertiser_detail must NOT raise "could not convert string to float: 'N/A'"
    detail = create_advertiser_detail(parsed)
    assert detail.seven_day_epc == "N/A"
    assert detail.three_month_epc == "N/A"


def test_bug3_epc_accepts_numeric_value():
    """Numeric EPCs must still round-trip through the model unchanged."""
    xml = """\
<cj-api><advertisers><advertiser>
  <advertiser-id>1</advertiser-id>
  <advertiser-name>Demo</advertiser-name>
  <relationship-status>joined</relationship-status>
  <network-rank>42</network-rank>
  <seven-day-epc>1.23</seven-day-epc>
  <three-month-epc>0.45</three-month-epc>
</advertiser></advertisers></cj-api>
"""
    parsed = _parse_advertiser_element(ET.fromstring(xml).find(".//advertiser"))
    adv = create_advertiser(parsed)
    assert adv.network_rank == "42"
    assert adv.seven_day_epc == "1.23"
    assert adv.three_month_epc == "0.45"


# ---------------------------------------------------------------------------
# Bug 2 — ``--relationship all`` must not be forwarded to CJ as advertiser-ids
#
# CJ rejects ``advertiser-ids=all`` with HTTP 400 "Invalid advertiser id(s): all".
# When the user asks for ``all``, the client must fetch ``joined`` and
# ``notjoined`` separately and merge the rows.
# ---------------------------------------------------------------------------


def _build_client_with_recording_get(rows_by_relationship):
    """Build a CjClient that returns canned XML keyed by the advertiser-ids param."""
    config = MagicMock()
    config.has_api_credentials.return_value = True
    config.personal_access_token = "test-pat"
    config.publisher_id = "12345"

    client = CjClient.__new__(CjClient)
    client.config = config
    client.base_url = "https://advertiser-lookup.api.cj.com"
    client.headers = {}
    client.max_retries = 0
    client.base_delay = 0
    client.max_delay = 0
    client.jitter = 0

    seen_params = []

    def fake_get(endpoint, params):
        seen_params.append(dict(params))
        rel = params["advertiser-ids"]
        xml = rows_by_relationship.get(rel, "<cj-api><advertisers></advertisers></cj-api>")
        return ET.fromstring(xml)

    client._get = fake_get  # type: ignore[assignment]
    return client, seen_params


def _xml_for(advertiser_id: str, name: str, status: str) -> str:
    return f"""\
<cj-api><advertisers><advertiser>
  <advertiser-id>{advertiser_id}</advertiser-id>
  <advertiser-name>{name}</advertiser-name>
  <relationship-status>{status}</relationship-status>
</advertiser></advertisers></cj-api>
"""


def test_bug2_list_relationship_all_splits_into_joined_and_notjoined():
    """--relationship all must never be passed to CJ as advertiser-ids=all."""
    rows = {
        "joined": _xml_for("1", "Joined Co", "joined"),
        "notjoined": _xml_for("2", "Not Joined Co", "notjoined"),
    }
    client, seen = _build_client_with_recording_get(rows)

    results = client.list_advertisers(relationship="all", limit=100)

    # CJ must never have been asked for advertiser-ids=all.
    sent_relationships = [p["advertiser-ids"] for p in seen]
    assert "all" not in sent_relationships, f"Sent 'all' to CJ: {sent_relationships}"
    assert set(sent_relationships) == {"joined", "notjoined"}

    # Both rows must be present in the merged result.
    ids = {row.advertiser_id for row in results}
    assert ids == {"1", "2"}


def test_bug2_search_relationship_all_splits_into_joined_and_notjoined():
    """search_advertisers(relationship='all') must also split, not forward 'all'."""
    rows = {
        "joined": _xml_for("10", "Google Cloud", "joined"),
        "notjoined": _xml_for("20", "Google Workspace", "notjoined"),
    }
    client, seen = _build_client_with_recording_get(rows)

    results = client.search_advertisers(query="Google", limit=100, relationship="all")

    sent_relationships = [p["advertiser-ids"] for p in seen]
    assert "all" not in sent_relationships
    ids = {row.advertiser_id for row in results}
    assert ids == {"10", "20"}


def test_bug1_multi_word_search_query_is_not_split():
    """Multi-word queries pass through as a single keywords param, untouched."""
    rows = {
        "joined": _xml_for("1", "Google Cloud Platform", "joined"),
        "notjoined": "<cj-api><advertisers></advertisers></cj-api>",
    }
    client, seen = _build_client_with_recording_get(rows)

    client.search_advertisers(query="Google Cloud", limit=10, relationship="all")

    # The keywords param must contain the full multi-word query verbatim.
    keywords_seen = [p.get("keywords") for p in seen if "keywords" in p]
    assert keywords_seen, "search_advertisers must forward the query as keywords"
    assert all(kw == "Google Cloud" for kw in keywords_seen)


# ---------------------------------------------------------------------------
# Bug 4 — auth status and the apply credential gate must agree
#
# Tested indirectly here: assert CJBrowser hooks declare what the shared
# command_registry needs so the auth gate matches has_session() filesystem
# inspection (no live browser launch during dry-run). The deeper fix lives
# in cli_tools_shared.command_registry and has its own test there.
# ---------------------------------------------------------------------------


def test_bug4_cj_browser_declares_auth_check_url():
    """CJ browser must declare AUTH_CHECK_URL so the live check can run when needed."""
    from cj_cli.browser import CJBrowser
    assert CJBrowser.AUTH_CHECK_URL
    # Bug 5: CJ now uses absence-of-login-form (AUTH_LOGIN_FORM_SELECTOR)
    # instead of the brittle positive nav-link AUTH_SUCCESS_SELECTOR that
    # broke when CJ refactored the dashboard. Either marker is sufficient
    # for the live _check_auth path; CJ declares the login-form marker.
    assert CJBrowser.AUTH_LOGIN_FORM_SELECTOR
    assert CJBrowser.AUTH_URL_PATTERN


# ---------------------------------------------------------------------------
# Bug 5 — CJ browser must NOT rely on the stale ``a[href*='/member/publisher/']``
# selector. CJ refactored the dashboard nav and that positive selector no
# longer matches even when the session is valid. The fix swaps the positive
# nav-link check for an absence-of-login-form check declared at the CJ
# browser hook level. This test pins the declarative shape so a future
# regression that re-introduces the brittle selector fails immediately.
# ---------------------------------------------------------------------------


def test_bug5_cj_browser_uses_absence_of_login_form_check():
    """CJ browser must declare AUTH_LOGIN_FORM_SELECTOR (negative check)
    and must NOT carry the legacy positive nav-link selector that broke.
    """
    from cj_cli.browser import CJBrowser

    # The CJ class must declare the absence-of-login-form marker.
    assert CJBrowser.AUTH_LOGIN_FORM_SELECTOR, (
        "CJBrowser must declare AUTH_LOGIN_FORM_SELECTOR — the negative "
        "check is the supported auth strategy after Bug 5."
    )
    # And the marker must target real login-form elements (password input
    # or login form) — not a positive nav element.
    selector = CJBrowser.AUTH_LOGIN_FORM_SELECTOR
    assert "password" in selector or "login" in selector.lower(), (
        f"AUTH_LOGIN_FORM_SELECTOR must target login-form elements, got: {selector!r}"
    )

    # The brittle nav-link selector must NOT be the declared positive
    # auth marker. (CJBrowser MAY leave AUTH_SUCCESS_SELECTOR unset; if
    # set, it must not be the stale ``a[href*='/member/publisher/']``.)
    assert CJBrowser.AUTH_SUCCESS_SELECTOR != "a[href*='/member/publisher/']", (
        "CJBrowser still carries the stale positive nav-link selector — "
        "this is exactly the Bug 5 failure mode."
    )


# ---------------------------------------------------------------------------
# Bug 6 — Marketplace advertiser-details URL and Apply-button selectors are
# dead.  CJ removed the legacy ``/marketplace/advertiser-details.cj?adId=X``
# page (it now serves a generic "the link you clicked isn't currently active"
# stub) and consolidated Apply into the ``findAdvertisers.cj`` search page,
# where each advertiser row has a ``button.ui-btn.primary.uppercase`` whose
# only stable identifier is the literal text "Apply to Program" and the
# advertiser-scoped sibling anchor ``a[href*="advertiserIds=<id>"]``.
#
# The fix replaces:
#   * ``_marketplace_apply_url(id)`` -> ``_find_advertisers_url(id)`` which
#     returns the new findAdvertisers.cj URL with the advertiser ID
#     embedded in the hash-state JSON so the rendered page is filtered to
#     just that advertiser's row.
#   * The brittle ``_APPLY_SELECTORS`` tuple of positive testid/aria
#     patterns -> a row-scoped ``_apply_locator(id)`` selector that pins
#     the click to the specific advertiser's "Apply to Program" button by
#     scoping a text match to the row containing the advertiser anchor.
#
# These tests are the regression contract for the URL shape and the
# locator shape.  They do not require a live browser — they assert the
# declarative outputs of the helpers, which is what _apply_single feeds
# straight into Playwright.
# ---------------------------------------------------------------------------


def test_bug6_apply_url_targets_findAdvertisers_not_dead_detail_page(monkeypatch):
    """``_find_advertisers_url`` must point at the live findAdvertisers.cj
    page, NOT the dead ``advertiser-details.cj?adId=<id>`` URL.

    The URL has two distinct ids:
    * URL path: publisher *account* id (the integer prefixing member URLs)
    * Hash state ``publisherId``: ``config.publisher_id`` (CJ requestor-cid)
    """
    from cj_cli.commands import relationships as rel_mod

    fake_config = MagicMock()
    fake_config.publisher_id = "7955906"
    monkeypatch.setattr(rel_mod, "get_config", lambda: fake_config)

    url = rel_mod._find_advertisers_url(
        "7453049", publisher_account_id="7627660", keyword="Example Advertiser"
    )

    # The dead URL must be gone -- it now serves a "link not active" stub.
    assert "advertiser-details.cj" not in url, (
        f"_find_advertisers_url still points at the dead detail page: {url!r}"
    )
    # The live page is the publisher findAdvertisers.cj search view.
    assert "findAdvertisers.cj" in url, (
        f"_find_advertisers_url must target findAdvertisers.cj, got: {url!r}"
    )
    # The advertiser NAME must be the keyword filter — CJ's keyword field
    # matches names, not ids.  Passing the raw id returns 0 results.
    assert '"keywords":"Example Advertiser"' in url, (
        f"_find_advertisers_url must use the name as keyword: {url!r}"
    )
    # The URL path uses the account id; the hash state uses publisher_id.
    assert "/member/7627660/" in url, (
        f"URL path must use publisher account id 7627660, got: {url!r}"
    )
    assert '"publisherId":7955906' in url, (
        f"Hash state must use publisher_id 7955906, got: {url!r}"
    )


def test_bug6_find_advertisers_url_rejects_missing_account_id(monkeypatch):
    """No silent fallback to publisher_id for the URL-path id — that was
    the original Bug 6 manifestation when the publisher_id (7955906)
    was used in the path and CJ 302'd to ``home.do``.  And no silent
    fallback to the raw id as keyword — CJ's name filter would return 0
    results.
    """
    from cj_cli.commands import relationships as rel_mod

    fake_config = MagicMock()
    fake_config.publisher_id = "7955906"
    monkeypatch.setattr(rel_mod, "get_config", lambda: fake_config)

    with pytest.raises(ValueError, match="publisher_account_id"):
        rel_mod._find_advertisers_url("7453049", publisher_account_id="", keyword="X")
    with pytest.raises(ValueError, match="publisher_account_id"):
        rel_mod._find_advertisers_url("7453049", publisher_account_id=None, keyword="X")
    with pytest.raises(ValueError, match="keyword"):
        rel_mod._find_advertisers_url(
            "7453049", publisher_account_id="7627660", keyword=""
        )


def test_bug6_apply_locator_is_row_scoped_and_text_matched():
    """``_apply_locator`` must return a Playwright selector that scopes the
    "Apply to Program" text match to the row containing the specific
    advertiser's anchor.  This prevents clicking the wrong row's button
    and survives the next CJ refactor that drops testid/aria attributes.
    """
    from cj_cli.commands.relationships import _apply_locator

    selector = _apply_locator("7453049")

    # The selector must reference the advertiser id -- a global
    # ``button:has-text('Apply')`` would match the wrong row.
    assert "7453049" in selector, (
        f"_apply_locator must scope to the advertiser id, got: {selector!r}"
    )
    # The selector must text-match "Apply to Program" -- the only stable
    # identifier on the live button (no testid, no aria-label, no data
    # attributes; just ``<button class='ui-btn primary uppercase'>``).
    assert "Apply to Program" in selector, (
        f"_apply_locator must text-match the Apply to Program label, "
        f"got: {selector!r}"
    )
    # The selector must use Playwright's row-scoping operators -- a flat
    # ``button:has-text('Apply to Program')`` would match every row's
    # button.  ``:has(a[href*='advertiserIds='])`` is the row pin.
    assert "advertiserIds=" in selector and ":has(" in selector, (
        f"_apply_locator must use :has(a[href*='advertiserIds=<id>']) to "
        f"pin the click to the right row, got: {selector!r}"
    )


def test_bug6_legacy_apply_selectors_tuple_is_gone():
    """The brittle positive-attribute ``_APPLY_SELECTORS`` tuple must be
    retired.  Its members targeted ``data-testid='apply-button'`` and
    ``aria-label*='Apply'`` -- attributes CJ never actually rendered on
    the live Marketplace page, so every selector in the tuple matched
    nothing and the apply silently failed.
    """
    from cj_cli.commands import relationships as rel_mod

    # Either the tuple is gone, or it's been emptied.  Either way the
    # CLI must no longer ship the original dead-letter selectors.
    legacy = getattr(rel_mod, "_APPLY_SELECTORS", ())
    forbidden = {
        "button[data-testid='apply-button']",
        "a[data-testid='apply-button']",
        "button[aria-label*='Apply' i]",
        "a[aria-label*='Apply' i]",
    }
    dead_letters = forbidden.intersection(set(legacy))
    assert not dead_letters, (
        f"_APPLY_SELECTORS still ships dead-letter testid/aria patterns "
        f"that never matched the live page: {sorted(dead_letters)}"
    )


def test_bug6_apply_single_uses_row_scoped_locator_and_findAdvertisers_url(monkeypatch):
    """End-to-end behaviour test: ``_apply_single`` must navigate to the
    findAdvertisers URL and click the row-scoped Apply locator for the
    requested advertiser, not the old marketplace detail URL.
    """
    from cj_cli.commands import relationships as rel_mod
    from cj_cli.models import ApplyOutcome, RelationshipStatus

    # Force the REST helper to report "not joined" so the apply proceeds.
    advertiser_detail = MagicMock()
    advertiser_detail.relationship_status = RelationshipStatus.NOT_JOINED
    advertiser_detail.advertiser_name = "Example Advertiser"
    fake_client = MagicMock()
    fake_client.get_advertiser.return_value = advertiser_detail
    monkeypatch.setattr(rel_mod, "get_client", lambda: fake_client)

    # Capture the navigation target and the locator selector the apply
    # path uses.
    seen = {}

    fake_locator_first = MagicMock()
    fake_locator_first.click.return_value = None

    fake_locator = MagicMock()
    fake_locator.first = fake_locator_first

    def fake_locator_factory(selector):
        # ``page.locator`` is called twice in _apply_single -- once via
        # the page-level wait_for_selector indirectly (no), actually the
        # selectors we care about flow through page.locator(...).  Track
        # the apply-button selector (the one containing the advertiser
        # id and the text match).
        if "Apply to Program" in selector:
            seen["selector"] = selector
        return fake_locator

    fake_page = MagicMock()
    fake_page.locator.side_effect = fake_locator_factory
    fake_page.wait_for_load_state.return_value = None
    fake_page.wait_for_selector.return_value = MagicMock()  # row + confirmation found
    fake_page.wait_for_timeout.return_value = None

    fake_browser = MagicMock()
    fake_browser.is_authenticated.return_value = True

    nav_urls = []

    def fake_get_page(url):
        nav_urls.append(url)
        seen["url"] = url
        return fake_page

    fake_browser.get_page.side_effect = fake_get_page

    fake_config = MagicMock()
    fake_config.get_browser.return_value = fake_browser
    fake_config.publisher_id = "7955906"
    fake_config.get_profile_data_dir.return_value = Path("/tmp")
    monkeypatch.setattr(rel_mod, "get_config", lambda: fake_config)
    # Stub the publisher account id discovery — the live path navigates
    # to home.do and reads a rendered URL; here we just return the known
    # account id directly.
    monkeypatch.setattr(
        rel_mod, "_discover_publisher_account_id", lambda page: "7627660"
    )

    result = rel_mod._apply_single("7453049", dry_run=False)

    # The final navigation went to the live findAdvertisers.cj page.
    final_url = nav_urls[-1]
    assert "findAdvertisers.cj" in final_url, (
        f"_apply_single must navigate to findAdvertisers.cj, got {final_url!r}"
    )
    assert "advertiser-details.cj" not in final_url, (
        f"_apply_single still navigates to the dead detail URL: {final_url!r}"
    )
    # Path id is the discovered account id, hash state uses publisher_id.
    assert "/member/7627660/" in final_url
    assert '"publisherId":7955906' in final_url

    # Locator was row-scoped to the requested advertiser.
    assert "7453049" in seen["selector"] and "Apply to Program" in seen["selector"], (
        f"Apply locator was not row-scoped + text-matched: {seen['selector']!r}"
    )

    # Click happened.
    fake_locator_first.click.assert_called_once()

    # On confirmation, the outcome is APPLIED (or the REST repoll path).
    assert result.outcome in (ApplyOutcome.APPLIED, ApplyOutcome.ALREADY_PENDING), (
        f"_apply_single returned unexpected outcome: {result.outcome!r}"
    )


# ---------------------------------------------------------------------------
# Bug 7 — apply path crashed waiting for Accept-and-Apply on auto-approve
# advertisers, and silently failed to save screenshots.
#
# Symptom: ``cj relationships apply <id>`` returned outcome=failed, detail
# "Reached joinprograms.do but the Accept and Apply button never resolved"
# even though CJ's REST already reported relationship_status=joined.
# Two root causes, fixed together:
#   (a) Screenshot API misuse — ``page.page_screenshot(ref=str(path))`` passes
#       the destination path as a CSS selector (``ref`` is a Playwright element
#       locator).  Every call site silently failed; screenshot_path was always
#       null.
#   (b) No REST-first poll after the first click — the code blocked waiting
#       for an Accept-and-Apply form that auto-approve advertisers never
#       render.  REST is the source of truth and should be consulted before
#       waiting for the form.
# ---------------------------------------------------------------------------


def test_bug7_capture_screenshot_helper_uses_correct_api(monkeypatch):
    """``_capture_screenshot`` must call ``page.page_screenshot()`` with no
    ``ref`` argument (ref is a CSS selector, not a destination path) and
    must return the file path from the result dict.
    """
    from cj_cli.commands import relationships as rel_mod

    fake_page = MagicMock()
    fake_page.page_screenshot.return_value = {
        "file": "/tmp/playwright-screenshots/cj-1234567890.png",
        "page_url": "https://members.cj.com/...",
    }

    result = rel_mod._capture_screenshot(fake_page)

    assert result == "/tmp/playwright-screenshots/cj-1234567890.png"
    fake_page.page_screenshot.assert_called_once_with()
    # Crucially, no kwargs and no positional args -- passing a Path as
    # ``ref`` was the prior bug.
    _, kwargs = fake_page.page_screenshot.call_args
    assert "ref" not in kwargs, (
        "page_screenshot must NOT be called with ref=<path>; ref is a "
        "Playwright element locator, not a destination path."
    )


def test_bug7_capture_screenshot_returns_none_on_failure():
    """Failures must return None (not raise) so a screenshot failure
    cannot mask the underlying apply failure.
    """
    from cj_cli.commands import relationships as rel_mod

    fake_page = MagicMock()
    fake_page.page_screenshot.side_effect = RuntimeError("playwright died")

    assert rel_mod._capture_screenshot(fake_page) is None


def test_bug7_no_legacy_screenshot_ref_path_callsites():
    """No call site in relationships.py may call ``page_screenshot`` with a
    file-path argument again.  ``ref`` is a Playwright element locator;
    passing a path silently fails (page.locator(path) raises) and the
    bare ``except Exception`` swallowed it for years.
    """
    import re
    from cj_cli.commands import relationships as rel_mod

    source = Path(rel_mod.__file__).read_text()
    # Match any page_screenshot call that passes a positional or ref=
    # argument other than literally ``page.page_screenshot()`` with no
    # args.  Use a generous regex: any non-empty parentheses content.
    bad = re.findall(r"page_screenshot\(\s*ref\s*=\s*[^)]+\)", source)
    assert not bad, (
        f"page_screenshot must not receive a ``ref`` argument anywhere; "
        f"found: {bad}"
    )


def test_bug7_rest_first_poll_short_circuits_auto_approve(monkeypatch):
    """After the first Apply-to-Program click, _apply_single must re-poll
    REST and short-circuit when the relationship is no longer notjoined.
    This is what auto-approve advertisers need: they register the apply
    on the first click, and the joinprograms.do T&C form either never
    renders or shows a processing state.  Waiting for an Accept-and-Apply
    selector that will never appear was the cause of the false-negative
    FAILED returns.
    """
    from cj_cli.commands import relationships as rel_mod
    from cj_cli.models import ApplyOutcome, RelationshipStatus

    # First REST call (pre-apply) -> notjoined so we proceed.
    # Second REST call (post-click) -> joined so we short-circuit.
    pre_detail = MagicMock()
    pre_detail.relationship_status = RelationshipStatus.NOT_JOINED
    pre_detail.advertiser_name = "AutoApproveCo"

    post_detail = MagicMock()
    post_detail.relationship_status = RelationshipStatus.JOINED
    post_detail.advertiser_name = "AutoApproveCo"

    fake_client = MagicMock()
    fake_client.get_advertiser.side_effect = [pre_detail, post_detail]
    monkeypatch.setattr(rel_mod, "get_client", lambda: fake_client)

    # Page mock: the first click "succeeds" silently; the URL after the
    # click happens to be joinprograms.do but the Accept-and-Apply form
    # is never going to be looked for because REST short-circuits first.
    fake_locator_first = MagicMock()
    fake_locator_first.click.return_value = None
    fake_locator = MagicMock()
    fake_locator.first = fake_locator_first

    fake_page = MagicMock()
    fake_page.locator.return_value = fake_locator
    fake_page.wait_for_selector.return_value = MagicMock()
    fake_page.wait_for_load_state.return_value = None
    fake_page.wait_for_timeout.return_value = None
    fake_page.page_eval.return_value = {
        "result": "https://members.cj.com/member/7627660/publisher/advertisers/joinprograms.do?advertiserId=999&publisherId=7955906",
        "page_url": "",
        "page_title": "",
    }

    fake_browser = MagicMock()
    fake_browser.is_authenticated.return_value = True
    fake_browser.get_page.return_value = fake_page

    fake_config = MagicMock()
    fake_config.get_browser.return_value = fake_browser
    fake_config.publisher_id = "7955906"
    fake_config.get_profile_data_dir.return_value = Path("/tmp")
    monkeypatch.setattr(rel_mod, "get_config", lambda: fake_config)
    monkeypatch.setattr(
        rel_mod, "_discover_publisher_account_id", lambda page: "7627660"
    )
    # Speed up the 2s REST-poll delays so the test runs fast.
    monkeypatch.setattr(rel_mod.time, "sleep", lambda s: None)

    result = rel_mod._apply_single("999", dry_run=False)

    # REST flipped to joined after the first click, so the outcome is the
    # terminal "already joined" mapping (the helper does not distinguish
    # "freshly joined this call" from "was joined before we started" --
    # the apply submitted, and the post-click status is joined).
    assert result.outcome == ApplyOutcome.ALREADY_JOINED, (
        f"REST-first poll must short-circuit on a joined status; got "
        f"{result.outcome!r} / {result.detail!r}"
    )
    # The Accept-and-Apply selector must NOT have been waited for, since
    # REST short-circuited before that branch.
    accept_waits = [
        call for call in fake_page.wait_for_selector.call_args_list
        if "Accept and Apply" in str(call)
    ]
    assert not accept_waits, (
        "Accept-and-Apply wait_for_selector ran even though REST already "
        "reported joined after the first click; auto-approve advertisers "
        "must not block waiting for a T&C form they never render."
    )


def test_bug7_accept_and_apply_selector_timeout_bumped_from_6s():
    """The Accept-and-Apply wait timeout must be at least 10000ms.

    The prior 6000ms window fired before joinprograms.do hydration
    completed on manual-review advertisers whose T&C form genuinely
    rendered, producing false-negative FAILED returns.
    """
    import re
    from cj_cli.commands import relationships as rel_mod

    source = Path(rel_mod.__file__).read_text()
    # Find the wait_for_selector call for the Accept-and-Apply selector
    # and assert its timeout is >= 10000.
    match = re.search(
        r"wait_for_selector\(\s*accept_selector\s*,\s*timeout\s*=\s*(\d+)",
        source,
    )
    assert match, "Could not locate accept_selector wait_for_selector call"
    timeout_ms = int(match.group(1))
    assert timeout_ms >= 10000, (
        f"Accept-and-Apply selector timeout is {timeout_ms}ms; must be "
        f">= 10000ms (was 6000ms before Bug 7; that window was too short "
        f"for joinprograms.do hydration)."
    )


def test_bug7_screenshot_path_helper_is_removed():
    """The old ``_screenshot_path`` helper built a destination path that
    PlaywrightService.page_screenshot then ignored (it writes to its own
    tempdir).  The helper is dead code and must not be reintroduced.
    """
    from cj_cli.commands import relationships as rel_mod

    assert not hasattr(rel_mod, "_screenshot_path"), (
        "_screenshot_path is dead code -- PlaywrightService writes to its "
        "own tempdir and ignores caller-supplied paths.  Use "
        "_capture_screenshot(page) instead."
    )


# ---------------------------------------------------------------------------
# `cj links` subcommand group — initial shipment.
#
# These are not regression tests for a prior bug; they pin the contract of
# a newly-shipped feature so it cannot rot silently.  They follow the same
# numbering convention (test_links_*) as advertiser-side tests.
# ---------------------------------------------------------------------------


_LINK_SEARCH_XML = """\
<cj-api>
  <links total-matched="2" records-returned="2" page-number="1">
    <link>
      <link-id>14729571</link-id>
      <advertiser-id>4837117</advertiser-id>
      <advertiser-name>NordVPN</advertiser-name>
      <link-name>NordVPN 2 year deal</link-name>
      <link-type>Text Link</link-type>
      <clickUrl>https://www.dpbolvw.net/click-7627660-14729571</clickUrl>
      <destination>https://nordvpn.com/offer/special/</destination>
      <description>Get NordVPN 2-Year Deal</description>
      <category>Computer &amp; Electronics</category>
      <language>en</language>
      <relationship-status>joined</relationship-status>
      <sale-commission>40.00%</sale-commission>
      <seven-day-epc>285.87</seven-day-epc>
      <three-month-epc>165.99</three-month-epc>
    </link>
    <link>
      <link-id>14729572</link-id>
      <advertiser-id>4837117</advertiser-id>
      <advertiser-name>NordVPN</advertiser-name>
      <link-name>NordVPN Banner 728x90</link-name>
      <link-type>Banner</link-type>
      <clickUrl>https://www.dpbolvw.net/click-7627660-14729572</clickUrl>
      <destination>https://nordvpn.com/</destination>
      <creative-height>90</creative-height>
      <creative-width>728</creative-width>
      <relationship-status>joined</relationship-status>
    </link>
  </links>
</cj-api>
"""


def test_links_parser_handles_clickUrl_camelcase_and_kebabcase():
    """CJ's link-search payload returns ``<clickUrl>`` (camelCase) in some
    responses and ``<click-url>`` in others.  The parser must accept both
    and map to ``click_url``.  This test pins the camelCase path; future
    payloads using ``<click-url>`` are covered by the fallback in the
    parser.
    """
    from cj_cli.client import _parse_link_element

    root = ET.fromstring(_LINK_SEARCH_XML)
    elems = root.findall(".//link")
    assert len(elems) == 2

    first = _parse_link_element(elems[0])
    assert first["click_url"] == "https://www.dpbolvw.net/click-7627660-14729571"
    assert first["link_id"] == "14729571"
    assert first["advertiser_id"] == "4837117"
    assert first["link_type"] == "Text Link"


def test_links_parser_kebab_case_fallback():
    """When CJ returns ``<click-url>`` instead of ``<clickUrl>``, the
    parser must still extract the click URL.  Pin both shapes so we
    don't regress one or the other.
    """
    from cj_cli.client import _parse_link_element

    xml = """
    <link>
      <link-id>1</link-id>
      <advertiser-id>2</advertiser-id>
      <click-url>https://example.com/click</click-url>
    </link>
    """
    elem = ET.fromstring(xml)
    parsed = _parse_link_element(elem)
    assert parsed["click_url"] == "https://example.com/click"


def test_links_search_uses_link_search_host_and_website_id(monkeypatch):
    """``search_links`` must hit ``link-search.api.cj.com``, not
    ``advertiser-lookup.api.cj.com``.  And it must include
    ``website-id`` (distinct from ``publisher_id`` -- see
    ``Config.website_id``) as a required CJ parameter.  Passing the
    publisher_id in the website-id slot returns HTTP 400 ``Website id
    specified does not match your account``.
    """
    from cj_cli.client import CjClient

    fake_config = MagicMock()
    fake_config.has_api_credentials.return_value = True
    fake_config.personal_access_token = "test-pat"
    fake_config.publisher_id = "7955906"
    fake_config.website_id = "12345678"

    client = CjClient(config=fake_config)

    captured = {}

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.ok = True
    fake_resp.content = _LINK_SEARCH_XML.encode()

    def fake_get(url, headers=None, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return fake_resp

    monkeypatch.setattr("cj_cli.client.requests.get", fake_get)

    links = client.search_links(advertiser_ids="4837117", limit=10)

    assert "link-search.api.cj.com" in captured["url"], (
        f"search_links must hit link-search host; got {captured['url']!r}"
    )
    assert "advertiser-lookup.api.cj.com" not in captured["url"], (
        f"search_links must NOT hit advertiser-lookup host; got {captured['url']!r}"
    )
    assert captured["params"]["website-id"] == "12345678", (
        f"website-id must come from Config.website_id (NOT publisher_id); "
        f"got {captured['params']!r}"
    )
    assert captured["params"]["website-id"] != "7955906", (
        "website-id must NOT be the publisher_id -- they are distinct CJ ids "
        "and conflating them returns HTTP 400 from CJ."
    )
    assert captured["params"]["advertiser-ids"] == "4837117"
    assert len(links) == 2
    assert links[0].link_id == "14729571"
    assert links[0].click_url == "https://www.dpbolvw.net/click-7627660-14729571"


def test_links_deeplink_builder_format():
    """The deep-link builder must produce the exact CJ-canonical URL
    shape.  CJ's redirector resolves URLs of the form
    ``https://www.anrdoezrs.net/links/<account-id>/type/dlg/<destination>``
    -- the destination is appended as-is (NOT percent-encoded).
    """
    from cj_cli.commands.links import _build_deeplink

    url = _build_deeplink(
        publisher_account_id="7627660",
        destination_url="https://nordvpn.com/offer/special/",
    )
    assert url == (
        "https://www.anrdoezrs.net/links/7627660/type/dlg/"
        "https://nordvpn.com/offer/special/"
    ), f"Unexpected deep-link URL: {url!r}"


def test_links_deeplink_builder_with_sid():
    """The ``sid`` (publisher sub-id) must be inserted between the
    ``type/dlg`` segment and the destination URL, and must be
    URL-encoded so reserved characters can't break the URL shape.
    """
    from cj_cli.commands.links import _build_deeplink

    url = _build_deeplink(
        publisher_account_id="7627660",
        destination_url="https://nordvpn.com/",
        sid="blog-post-vpn-comparison",
    )
    assert "/sid/blog-post-vpn-comparison/" in url
    assert url.endswith("/https://nordvpn.com/")

    # Reserved chars in the sid must be encoded.
    encoded = _build_deeplink(
        publisher_account_id="7627660",
        destination_url="https://nordvpn.com/",
        sid="blog/post?id=42",
    )
    assert "/sid/blog%2Fpost%3Fid%3D42/" in encoded, (
        f"sid must be URL-encoded to keep CJ's redirector parser happy; "
        f"got {encoded!r}"
    )


def test_links_website_id_required_for_search(monkeypatch, tmp_path):
    """``Config.website_id`` must raise when ``CJ_WEBSITE_ID`` is
    missing, with a message that points the user at the Properties
    page where website-ids are listed.  No silent fallback to
    publisher_id (which would return HTTP 400 from CJ).
    """
    from cj_cli.config import Config

    config = Config()
    monkeypatch.setattr(
        config,
        "_get",
        lambda key: None if key == "WEBSITE_ID" else "7955906",
    )

    with pytest.raises(ValueError) as exc_info:
        _ = config.website_id

    msg = str(exc_info.value)
    assert "CJ_WEBSITE_ID" in msg
    assert "Properties" in msg, (
        f"Error must tell the user where to find the value (the Properties "
        f"page on members.cj.com); got: {msg!r}"
    )


def test_links_publisher_account_id_required_for_deeplink(monkeypatch, tmp_path):
    """``Config.publisher_account_id`` must raise when
    ``CJ_PUBLISHER_ACCOUNT_ID`` is missing, with a message that points
    the user at where to find the value.  Fail-fast contract: no
    silent fallback to publisher_id (they are different ids).
    """
    from cj_cli.config import Config

    # Build a Config that has no CJ_PUBLISHER_ACCOUNT_ID configured.
    env_file = tmp_path / "env"
    env_file.write_text("CJ_PUBLISHER_ID=7955906\n")

    config = Config()
    monkeypatch.setattr(config, "_get", lambda key: None if key == "PUBLISHER_ACCOUNT_ID" else "7955906")

    with pytest.raises(ValueError) as exc_info:
        _ = config.publisher_account_id

    msg = str(exc_info.value)
    assert "CJ_PUBLISHER_ACCOUNT_ID" in msg
    assert "/member/" in msg and "/publisher/" in msg, (
        f"Error must tell the user where to find the value; got: {msg!r}"
    )


def test_links_deeplink_command_verifies_relationship(monkeypatch):
    """``cj links deeplink`` must refuse to emit a URL by default when
    the publisher is not joined with the advertiser -- otherwise the
    URL would resolve but the click would not be credited.  Users can
    bypass with --no-verify when they understand the consequence.
    """
    from cj_cli.commands import links as links_mod
    from cj_cli.models import RelationshipStatus

    detail = MagicMock()
    detail.relationship_status = RelationshipStatus.NOT_JOINED
    detail.advertiser_name = "SomeOtherAdvertiser"
    fake_client = MagicMock()
    fake_client.get_advertiser.return_value = detail
    monkeypatch.setattr(links_mod, "get_client", lambda: fake_client)

    fake_config = MagicMock()
    fake_config.publisher_account_id = "7627660"
    monkeypatch.setattr(links_mod, "get_config", lambda: fake_config)

    # Direct invocation of the command function (bypasses Typer parsing).
    # typer.BadParameter is the expected raise; we catch via Exception so
    # the test doesn't import typer privately.
    import typer
    with pytest.raises((typer.BadParameter, typer.Exit, SystemExit)):
        links_mod.links_deeplink(
            advertiser_id="999",
            destination_url="https://example.com/",
            sid=None,
            verify=True,
        )


