"""`invalidate/checks.py`'s per-source live-check dispatch table.

Every namespace the live source registry carries must resolve to SOME check
function -- `dispatch()` must never KeyError on an unlisted namespace, it
must fall through to `check_generic`. Individual source functions were
live-tested against the real ledger during implementation (see checks.py's
own module docstring and per-function comments for what was verified live on
2026-08-08, and what could not be and is covered here with fixtures instead:
Reddit's block, LiveAuctioneers'/Proxibid's bot-wall path, and the generic
fallback's phrase matching).
"""
from __future__ import annotations

import json
import time

import pytest

from legoscout_cli.invalidate import checks, sweep
from legoscout_cli.sources import listing as source_listing


def _deal(listing_key, url="https://example.invalid/listing"):
    return {"listing_key": listing_key, "url": url, "direct_url": url,
            "title": "lego bulk lot"}


# --- playwright-cli lifecycle ------------------------------------------------

def test_playwright_text_opens_reads_and_closes_one_browser(monkeypatch):
    calls = []
    responses = iter([
        ("opened", None),
        ('### Result\n"rendered listing text"\n### Ran Playwright code', None),
        ("closed", None),
    ])

    def _fake_run(args, timeout=60):
        calls.append(args)
        return next(responses)

    monkeypatch.setattr(checks, "_playwright_session_name", lambda: "lsdeadbeef")
    monkeypatch.setattr(checks, "_run_playwright", _fake_run)

    assert checks._playwright_text("https://example.invalid/listing") == (
        True, "rendered listing text")
    assert calls == [
        ["-s=lsdeadbeef", "open", "https://example.invalid/listing"],
        ["-s=lsdeadbeef", "eval", "() => document.body.innerText"],
        ["-s=lsdeadbeef", "close"],
    ]


def test_playwright_text_open_failure_stops_without_availability_inference(monkeypatch):
    calls = []

    def _fake_run(args, timeout=60):
        calls.append(args)
        return None, "playwright-cli open failed"

    monkeypatch.setattr(checks, "_playwright_session_name", lambda: "lsdeadbeef")
    monkeypatch.setattr(checks, "_run_playwright", _fake_run)

    assert checks._playwright_text("https://example.invalid/listing") == (
        False, "playwright-cli open failed")
    assert calls == [[
        "-s=lsdeadbeef", "open", "https://example.invalid/listing"]]


def test_playwright_text_eval_failure_still_closes_browser(monkeypatch):
    calls = []
    responses = iter([
        ("opened", None),
        (None, "playwright-cli eval failed"),
        ("closed", None),
    ])

    def _fake_run(args, timeout=60):
        calls.append(args)
        return next(responses)

    monkeypatch.setattr(checks, "_playwright_session_name", lambda: "lsdeadbeef")
    monkeypatch.setattr(checks, "_run_playwright", _fake_run)

    assert checks._playwright_text("https://example.invalid/listing") == (
        False, "playwright-cli eval failed")
    assert calls[-1] == ["-s=lsdeadbeef", "close"]


def test_playwright_text_uses_a_unique_session_for_each_call(monkeypatch):
    session_names = iter(["ls00000001", "ls00000002"])
    calls = []

    def _fake_run(args, timeout=60):
        calls.append(args)
        if args[1] == "eval":
            return '### Result\n"rendered"\n### Ran Playwright code', None
        return "ok", None

    monkeypatch.setattr(
        checks, "_playwright_session_name", lambda: next(session_names))
    monkeypatch.setattr(checks, "_run_playwright", _fake_run)

    assert checks._playwright_text("https://example.invalid/one") == (
        True, "rendered")
    assert checks._playwright_text("https://example.invalid/two") == (
        True, "rendered")
    assert {call[0] for call in calls[:3]} == {"-s=ls00000001"}
    assert {call[0] for call in calls[3:]} == {"-s=ls00000002"}


# --- dispatch never KeyErrors -------------------------------------------------

@pytest.mark.parametrize("ns", [
    "americasthriftsupply", "auctionzip", "craigslist", "estatesales",
    "estatesalesorg", "govdeals", "k-bid", "nextdoor", "offerup",
    "palletliquidation", "somebrandnewsourcenoonehasseenyet",
])
def test_unlisted_namespace_falls_through_to_generic(monkeypatch, ns):
    # "ordinary page text" is short and carries no unambiguous signal either
    # way -- it must resolve `error`, never a guessed `available` (see the
    # generic-fallback section below). This test's own job is only to prove
    # `dispatch()` never KeyErrors on an unregistered namespace and reaches
    # `check_generic` at all, so both fetch tiers are mocked to fail fast
    # rather than hit the real network/subprocess.
    monkeypatch.setattr(checks, "_http_get", lambda url, timeout=45: (200, "ordinary page text"))
    monkeypatch.setattr(checks, "_playwright_text", lambda url: (False, "second tier mocked to also produce no signal"))
    result = checks.dispatch(_deal("%s|123" % ns))
    assert result.status == "error"


def test_every_live_namespace_dispatches_to_its_registered_check(monkeypatch):
    """Prove real coverage, not a dict agreeing with itself: for every
    namespace the LIVE source registry (`legoscout sources list`) carries,
    `dispatch()` must actually route to that namespace's own `CHECKS` entry
    (or `check_generic` for a namespace with none). Each namespace's
    function is patched to return a unique sentinel, and `dispatch()` is
    called for real -- a wrong or missing dispatch key (a rename, a typo,
    a namespace pointed at the wrong function) fails this, unlike the old
    `checks.CHECKS.get(ns) is fn for ns, fn in checks.CHECKS.items()` check,
    which is tautological for any dict and cannot fail."""
    from legoscout_cli.sources import registry

    live_namespaces = sorted(registry.sources.table().keys())
    assert live_namespaces, "the live source registry returned no namespaces"

    for ns in live_namespaces:
        marker = checks.CheckResult("available", "sentinel for %s" % ns)
        if ns in checks.CHECKS:
            monkeypatch.setitem(checks.CHECKS, ns, lambda deal, _m=marker: _m)
        else:
            monkeypatch.setattr(checks, "check_generic", lambda deal, _m=marker: _m)
        result = checks.dispatch(_deal("%s|sentinel" % ns))
        assert result is marker, (
            "namespace %r did not dispatch to its registered check function" % ns)
        monkeypatch.undo()


# --- generic fallback: unambiguous gone vs ambiguous -------------------------

def test_generic_fallback_404_is_gone(monkeypatch):
    monkeypatch.setattr(checks, "_http_get", lambda url, timeout=45: (404, ""))
    result = checks.check_generic(_deal("craigslist|1"))
    assert result.status == "gone"


def test_generic_fallback_unambiguous_removal_phrase_is_gone(monkeypatch):
    monkeypatch.setattr(
        checks, "_http_get",
        lambda url, timeout=45: (200, "<html>Sorry, this listing has been removed by the seller.</html>"))
    result = checks.check_generic(_deal("offerup|1"))
    assert result.status == "gone"


def test_generic_fallback_ambiguous_text_never_confirms_unavailable(monkeypatch):
    # Weak/ambiguous: the word appears, but not as one of the documented
    # unambiguous phrases -- must never resolve to "gone", and must not be
    # guessed as "available" either (the CSS boilerplate plus one short
    # sentence is nowhere near substantial listing content). Both tiers are
    # mocked so the ambiguous http tier's fallback attempt at playwright is
    # also exercised without touching the real network/subprocess.
    monkeypatch.setattr(
        checks, "_http_get",
        lambda url, timeout=45: (200, "<style>.icon.sold-tag{display:none}</style><p>Great bulk lot!</p>"))
    monkeypatch.setattr(checks, "_playwright_text", lambda url: (False, "second tier mocked to also produce no signal"))
    result = checks.check_generic(_deal("nextdoor|1"))
    assert result.status == "error"


def test_generic_fallback_503_service_unavailable_is_error_not_available(monkeypatch):
    """Reproduced live: a mocked 503 'Service Temporarily Unavailable' body
    used to return `available` -- an error page says nothing about the
    LISTING's own state and must never be read as confirmation it is still
    there."""
    monkeypatch.setattr(
        checks, "_http_get",
        lambda url, timeout=45: (
            503,
            "<html><body><h1>503 Service Temporarily Unavailable</h1>"
            "<p>The server is temporarily unable to service your request due "
            "to maintenance downtime. Please try again later.</p></body></html>"))
    monkeypatch.setattr(checks, "_playwright_text", lambda url: (False, "second tier mocked to also produce no signal"))
    result = checks.check_generic(_deal("craigslist|1"))
    assert result.status == "error"


def test_generic_fallback_blank_spa_shell_is_error_not_available(monkeypatch):
    """Reproduced live: an unrendered React SPA shell (no visible content at
    all) used to return `available` -- exactly the shape a genuinely gone
    listing behind a client-rendered 404 route could produce."""
    monkeypatch.setattr(
        checks, "_http_get",
        lambda url, timeout=45: (200, '<html><body><div id="root"></div></body></html>'))
    monkeypatch.setattr(checks, "_playwright_text", lambda url: (False, "second tier mocked to also produce no signal"))
    result = checks.check_generic(_deal("offerup|1"))
    assert result.status == "error"


def test_generic_fallback_substantial_content_is_available(monkeypatch):
    """The positive case this stricter rule must still pass: a real 200 with
    substantial, listing-shaped visible text and no removal/error/wall
    signature resolves `available`."""
    monkeypatch.setattr(
        checks, "_http_get",
        lambda url, timeout=45: (200, "<html><body><h1>LEGO Bulk Lot, 15 lbs</h1>"
                                 "<p>Great mix of Star Wars, City, and Technic pieces, "
                                 "cleaned and sorted from a smoke-free home. Local pickup "
                                 "or shipping available. Message me with any questions "
                                 "about this listing before you make an offer.</p>"
                                 "</body></html>"))
    result = checks.check_generic(_deal("craigslist|2"))
    assert result.status == "available"


def test_generic_fallback_playwright_attempted_when_http_tier_is_ambiguous(monkeypatch):
    """Mirrors every other tiered check in this file: the playwright
    fallback tier must be attempted whenever the FIRST tier's content is
    ambiguous, not only on an outright fetch failure or a detected wall."""
    monkeypatch.setattr(checks, "_http_get", lambda url, timeout=45: (200, "short"))
    calls = []
    monkeypatch.setattr(
        checks, "_playwright_text",
        lambda url: (calls.append(url), (True, "this listing has been removed"))[1])
    result = checks.check_generic(_deal("k-bid|1"))
    assert calls == ["https://example.invalid/listing"]
    assert result.status == "gone"


def test_generic_fallback_wall_is_blocked_not_error(monkeypatch):
    monkeypatch.setattr(
        checks, "_http_get",
        lambda url, timeout=45: (200, "Request unsuccessful. Incapsula incident ID: 123"))
    result = checks.check_generic(_deal("estatesalesorg|1"))
    assert result.status == "blocked"


def test_generic_fallback_falls_back_to_playwright_on_network_failure(monkeypatch):
    def _raise(url, timeout=45):
        raise OSError("connection reset")
    monkeypatch.setattr(checks, "_http_get", _raise)
    monkeypatch.setattr(checks, "_playwright_text", lambda url: (True, "this listing has been removed"))
    result = checks.check_generic(_deal("govdeals|1"))
    assert result.status == "gone"


# --- Reddit: never probes ------------------------------------------------------

def test_reddit_never_makes_a_network_call(monkeypatch):
    def _fail(*a, **k):
        pytest.fail("reddit check made a network call -- its own reader says 'do not probe'")

    monkeypatch.setattr(checks, "_run_cli_json", _fail)
    monkeypatch.setattr(checks, "_http_get", _fail)
    monkeypatch.setattr(checks, "_playwright_text", _fail)
    monkeypatch.setattr(checks.subprocess, "run", _fail)
    monkeypatch.setattr(checks.source_listing, "cli", _fail)

    result = checks.check_reddit(_deal("reddit|1"))

    assert result.status == "blocked"


# --- LiveAuctioneers / Proxibid: a detected wall is blocked, never bypassed --

def test_liveauctioneers_incapsula_wall_is_blocked(monkeypatch):
    monkeypatch.setattr(source_listing, "http",
                        lambda url: "Request unsuccessful. Incapsula incident ID: 999")
    result = checks.check_liveauctioneers(_deal("liveauctioneers|1"))
    assert result.status == "blocked"


def test_liveauctioneers_hcaptcha_wall_on_playwright_tier_is_blocked(monkeypatch):
    def _raise_http(url):
        raise OSError("blocked at http tier")
    monkeypatch.setattr(source_listing, "http", _raise_http)
    monkeypatch.setattr(checks, "_playwright_text",
                        lambda url: (True, "Please click below to continue. I am human. hCaptcha"))
    result = checks.check_liveauctioneers(_deal("liveauctioneers|1"))
    assert result.status == "blocked"


def test_liveauctioneers_open_bidding_text_is_available(monkeypatch):
    monkeypatch.setattr(source_listing, "http",
                        lambda url: "This lot is OPEN FOR BIDDING. Current Bid: $5. Place Bid.")
    result = checks.check_liveauctioneers(_deal("liveauctioneers|1"))
    assert result.status == "available"


def test_proxibid_imperva_wall_is_blocked_never_bypassed(monkeypatch):
    monkeypatch.setattr(source_listing, "http",
                        lambda url: "Error 15 - access denied. Incident details.")
    result = checks.check_proxibid(_deal("proxibid|1"))
    assert result.status == "blocked"


def test_proxibid_real_countdown_is_available(monkeypatch):
    monkeypatch.setattr(
        source_listing, "http",
        lambda url: 'LotTimeRem.push("102212901,168059"); updating...')
    result = checks.check_proxibid(_deal("proxibid|102212901"))
    assert result.status == "available"


def test_proxibid_elapsed_countdown_is_gone(monkeypatch):
    monkeypatch.setattr(
        source_listing, "http",
        lambda url: 'LotTimeRem.push("102212901,-5"); Bidding has ended')
    result = checks.check_proxibid(_deal("proxibid|102212901"))
    assert result.status == "gone"


# --- AuctionNinja: unverified-live closed phrase, unit-tested here ----------

def test_auctionninja_open_bid_now_is_available(monkeypatch):
    monkeypatch.setattr(source_listing, "http", lambda url: "Bid Now  Current Bid $1.00 1 Bid")
    result = checks.check_auctionninja(_deal("auctionninja|1"))
    assert result.status == "available"


def test_auctionninja_ended_phrase_is_gone(monkeypatch):
    monkeypatch.setattr(source_listing, "http", lambda url: "This auction has ended. Winning bid: $12.")
    result = checks.check_auctionninja(_deal("auctionninja|1"))
    assert result.status == "gone"


# --- Poshmark: schema.org JSON-LD, never a raw text scan ---------------------

def _posh_html(availability):
    payload = json.dumps({"@type": "Product", "offers": {"availability": availability}})
    return ('<html><style>.icon.sold-tag{}</style><script type="application/ld+json" '
            'data-vmid="x">%s</script></html>' % payload)


def test_poshmark_instock_is_available(monkeypatch):
    monkeypatch.setattr(source_listing, "http", lambda url: _posh_html("https://schema.org/InStock"))
    result = checks.check_poshmark(_deal("poshmark|1"))
    assert result.status == "available"


def test_poshmark_outofstock_is_gone(monkeypatch):
    monkeypatch.setattr(source_listing, "http", lambda url: _posh_html("https://schema.org/OutOfStock"))
    result = checks.check_poshmark(_deal("poshmark|1"))
    assert result.status == "gone"


def test_poshmark_css_boilerplate_sold_tag_is_not_mistaken_for_gone(monkeypatch):
    """The whole reason a raw text scan was rejected for Poshmark: every page
    (sold or not) carries `icon.sold-tag` CSS class definitions in its
    stylesheet, so scanning for the substring "sold" alone false-positives on
    every listing. Confirm the JSON-LD-only parser is immune."""
    monkeypatch.setattr(source_listing, "http", lambda url: _posh_html("https://schema.org/InStock"))
    result = checks.check_poshmark(_deal("poshmark|1"))
    assert result.status == "available"


def test_poshmark_playwright_recaptcha_stops_source(monkeypatch):
    def _raise_http(url):
        raise OSError("plain fetch denied")

    monkeypatch.setattr(source_listing, "http", _raise_http)
    monkeypatch.setattr(
        checks, "_playwright_text",
        lambda url: (True, "Please complete the reCAPTCHA challenge"))

    result = checks.check_poshmark(_deal("poshmark|1"))

    assert result.status == "blocked"
    assert result.stop_source is True
    assert "recaptcha" in result.detail


# --- Depop: one direct-URL signal, with source-stop on an actual wall --------

def test_depop_direct_url_instock_is_available(monkeypatch):
    """Verified live 2026-08-08 against 3 real active Depop rows pulled from
    the ledger: every one returns HTTP 200 with this exact JSON-LD shape."""
    monkeypatch.setattr(
        checks, "_http_get",
        lambda url, timeout=45: (200, _posh_html("https://schema.org/InStock")))
    result = checks.check_depop(_deal("depop|1"))
    assert result.status == "available"
    assert result.stop_source is False


def test_depop_direct_url_outofstock_is_gone(monkeypatch):
    monkeypatch.setattr(
        checks, "_http_get",
        lambda url, timeout=45: (200, _posh_html("https://schema.org/OutOfStock")))
    result = checks.check_depop(_deal("depop|1"))
    assert result.status == "gone"


def test_depop_cloudflare_challenge_stops_the_source(monkeypatch):
    body = (
        "<title>Forbidden - Depop</title>"
        "<h1>Checking if the connection is secure.</h1>"
        "<div class='captchaBox'></div><script>window._cf_chl_opt = {}</script>"
    )
    monkeypatch.setattr(checks, "_http_get", lambda url, timeout=45: (403, body))
    result = checks.check_depop(_deal("depop|1"))
    assert result.status == "blocked"
    assert result.stop_source is True
    assert "HTTP 403" in result.detail


def test_depop_plain_http_403_stops_the_source(monkeypatch):
    monkeypatch.setattr(
        checks, "_http_get",
        lambda url, timeout=45: (403, "<title>Forbidden - Depop</title>"))
    result = checks.check_depop(_deal("depop|1"))
    assert result.status == "blocked"
    assert result.stop_source is True
    assert result.detail == "HTTP 403 direct URL denied source access"


def test_depop_plain_parser_miss_is_one_row_error(monkeypatch):
    monkeypatch.setattr(
        checks, "_http_get",
        lambda url, timeout=45: (200, "<html><body>no structured data here</body></html>"))
    result = checks.check_depop(_deal("depop|796765204"))
    assert result.status == "error"
    assert result.stop_source is False
    assert "no Product JSON-LD" in result.detail


def test_depop_direct_url_not_found_is_gone(monkeypatch):
    monkeypatch.setattr(checks, "_http_get", lambda url, timeout=45: (404, ""))
    result = checks.check_depop(_deal("depop|1"))
    assert result.status == "gone"


# --- ShopGoodwill: a MISSING 'available' key is not the same as an explicit
# `false` -- only the latter is real evidence the listing is gone -----------

def test_shopgoodwill_explicit_false_is_gone(monkeypatch):
    monkeypatch.setattr(
        checks, "_run_cli_json",
        lambda args, timeout=30: {"available": False, "isItemEndTimeExpire": True,
                                  "remainingTime": 0})
    result = checks.check_shopgoodwill(_deal("shopgoodwill|1"))
    assert result.status == "gone"


def test_shopgoodwill_explicit_true_is_available(monkeypatch):
    monkeypatch.setattr(
        checks, "_run_cli_json",
        lambda args, timeout=30: {"available": True, "isItemEndTimeExpire": False})
    result = checks.check_shopgoodwill(_deal("shopgoodwill|1"))
    assert result.status == "available"


def test_shopgoodwill_missing_available_key_is_error_not_gone(monkeypatch):
    """The one check in this file that used to default a missing/ambiguous
    signal to `gone` rather than `error` -- inconsistent with every sibling
    check, and the same 'weak signal -> destructive write' shape as a
    real 2026-08-08 15-row incident. A payload that never answers the
    question must not be guessed as confirmed-gone."""
    monkeypatch.setattr(
        checks, "_run_cli_json",
        lambda args, timeout=30: {"isItemEndTimeExpire": False, "remainingTime": 500})
    result = checks.check_shopgoodwill(_deal("shopgoodwill|1"))
    assert result.status == "error"


def test_shopgoodwill_cli_failure_is_error(monkeypatch):
    monkeypatch.setattr(checks, "_run_cli_json", lambda args, timeout=30: None)
    result = checks.check_shopgoodwill(_deal("shopgoodwill|1"))
    assert result.status == "error"


# --- Mercari / eBay / Facebook / StockX: verified-live status field mapping -

def test_mercari_on_sale_status_is_available(monkeypatch):
    monkeypatch.setattr(source_listing, "cli", lambda args: {"status": "on_sale"})
    result = checks.check_mercari(_deal("mercari|m1"))
    assert result.status == "available"


def test_mercari_sold_out_status_is_gone(monkeypatch):
    monkeypatch.setattr(source_listing, "cli", lambda args: {"status": "sold_out"})
    result = checks.check_mercari(_deal("mercari|m1"))
    assert result.status == "gone"


def test_mercari_trading_with_sale_time_is_gone(monkeypatch):
    monkeypatch.setattr(
        source_listing, "cli",
        lambda args: {"status": "trading", "lastSoldAt": 1786467446},
    )
    result = checks.check_mercari(_deal("mercari|m1"))
    assert result.status == "gone"
    assert "lastSoldAt=1786467446" in result.detail


def test_mercari_trading_without_sale_time_stays_fail_closed(monkeypatch):
    monkeypatch.setattr(source_listing, "cli", lambda args: {"status": "trading"})
    result = checks.check_mercari(_deal("mercari|m1"))
    assert result.status == "error"


def test_mercari_timeout_is_error_not_gone(monkeypatch):
    """A genuinely removed Mercari listing was observed live (2026-08-08) to
    time out the CLI rather than answer cleanly -- that is NOT the same
    signal as a clean `sold_out` response and must not be guessed as gone."""
    def _raise(args):
        raise source_listing.Undetermined("Error: Timed out capturing Mercari item 'm1'.")
    monkeypatch.setattr(source_listing, "cli", _raise)
    result = checks.check_mercari(_deal("mercari|m1"))
    assert result.status == "error"
    assert result.stop_source is False


def test_mercari_cloudflare_challenge_stops_the_source(monkeypatch):
    def _raise(args):
        raise source_listing.Undetermined(
            "Error: Mercari page did not finish loading (possible Cloudflare challenge).")
    monkeypatch.setattr(source_listing, "cli", _raise)
    result = checks.check_mercari(_deal("mercari|m1"))
    assert result.status == "blocked"
    assert result.stop_source is True


def test_mercari_batch_maps_typed_results(monkeypatch):
    monkeypatch.setattr(
        source_listing,
        "cli",
        lambda args: [
            {
                "item_id": "m1",
                "status": "ok",
                "item": {"status": "on_sale"},
            },
            {
                "item_id": "m2",
                "status": "ok",
                "item": {"status": "trading", "lastSoldAt": 1786467446},
            },
            {
                "item_id": "m3",
                "status": "error",
                "error_kind": "not_found",
                "error": "Mercari item 'm3' not found.",
            },
            {
                "item_id": "m4",
                "status": "error",
                "error_kind": "unreadable",
                "error": "router timeout",
            },
        ],
    )
    results = checks.check_mercari_batch([
        _deal("mercari|m1"),
        _deal("mercari|m2"),
        _deal("mercari|m3"),
        _deal("mercari|m4"),
    ])
    assert [results["mercari|m%d" % index].status for index in range(1, 5)] \
        == ["available", "gone", "gone", "error"]


def test_mercari_batch_human_challenge_returns_one_source_blocker(monkeypatch):
    def _raise(args):
        raise source_listing.Undetermined(
            "Error: Mercari presented a human verification challenge.")
    monkeypatch.setattr(source_listing, "cli", _raise)
    results = checks.check_mercari_batch([
        _deal("mercari|m1"), _deal("mercari|m2")])
    assert list(results) == ["mercari|m1"]
    assert results["mercari|m1"].status == "blocked"
    assert results["mercari|m1"].stop_source is True


def test_mercari_batch_rejects_missing_coverage(monkeypatch):
    monkeypatch.setattr(
        source_listing,
        "cli",
        lambda args: [{
            "item_id": "m1", "status": "ok", "item": {"status": "on_sale"},
        }],
    )
    results = checks.check_mercari_batch([
        _deal("mercari|m1"), _deal("mercari|m2")])
    assert set(results) == {"mercari|m1", "mercari|m2"}
    assert all(result.status == "error" for result in results.values())
    assert all("expected 2 ordered records" in result.detail for result in results.values())


def test_ebay_ended_true_is_gone(monkeypatch):
    calls = []
    monkeypatch.setattr(
        source_listing, "cli",
        lambda args: calls.append(args) or {"ended": True})
    result = checks.check_ebay(_deal("ebay|1"))
    assert result.status == "gone"
    assert calls == [["ebay", "listings", "status", "1"]]


def test_ebay_ended_false_is_available(monkeypatch):
    monkeypatch.setattr(source_listing, "cli", lambda args: {"ended": False})
    result = checks.check_ebay(_deal("ebay|1"))
    assert result.status == "available"


def test_ebay_not_found_cli_error_is_gone(monkeypatch):
    def _raise(args):
        raise source_listing.Undetermined(
            "eBay item 1 was not found or the listing was removed", gone=True)
    monkeypatch.setattr(source_listing, "cli", _raise)
    result = checks.check_ebay(_deal("ebay|1"))
    assert result.status == "gone"


def test_facebook_sold_availability_is_gone(monkeypatch):
    calls = []
    monkeypatch.setattr(
        source_listing, "cli",
        lambda args: calls.append(args) or {
            "status": "gone", "availability": "Sold"})
    result = checks.check_facebook(_deal("facebook|1"))
    assert result.status == "gone"
    assert calls == [["facebook", "marketplace", "status", "1"]]


def test_facebook_available_is_available(monkeypatch):
    monkeypatch.setattr(
        source_listing, "cli",
        lambda args: {"status": "available", "availability": "Available"})
    result = checks.check_facebook(_deal("facebook|1"))
    assert result.status == "available"


def test_facebook_pending_is_available(monkeypatch):
    monkeypatch.setattr(
        source_listing, "cli",
        lambda args: {"status": "available", "availability": "Pending"})
    result = checks.check_facebook(_deal("facebook|1"))
    assert result.status == "available"


def test_facebook_checkpoint_is_blocked_not_raised(monkeypatch):
    def _raise(args):
        raise source_listing.Undetermined("Error: Facebook checkpoint required for this account.")
    monkeypatch.setattr(source_listing, "cli", _raise)
    result = checks.check_facebook(_deal("facebook|1"))
    assert result.status == "blocked"


def test_stockx_resolves_successfully_is_available(monkeypatch):
    monkeypatch.setattr(source_listing, "cli", lambda args: {"market": {}})
    result = checks.check_stockx(_deal("stockx|shoe"))
    assert result.status == "available"


def test_stockx_404_gone_detection_is_gone(monkeypatch):
    def _raise(args):
        raise source_listing.Undetermined("StockX product not found for 'shoe'", gone=True)
    monkeypatch.setattr(source_listing, "cli", _raise)
    result = checks.check_stockx(_deal("stockx|shoe"))
    assert result.status == "gone"


# --- Missing-CLI resolution --------------------------------------------------
#
# The sweep forks one child per check batch, and a forked child inherits
# exactly the PATH its parent had -- which a stripped launch environment can
# lack the uv install dir (~/.local/bin) in entirely. Two contract points:
#
#   1. CLI resolution must find an installed CLI even when PATH lacks the
#      install dir, and hand subprocess.run an ABSOLUTE path.
#   2. A genuinely-missing CLI must be a per-row `error` (the retried-next-run
#      check_failed bucket) that NAMES the executable -- never a raw
#      FileNotFoundError escaping a forked child and aborting the whole sweep
#      mid-run (the live failure: ~24 of 473 checks, then exit non-zero).

_NO_CLI_DIRS = ("/nonexistent-cli-dir",)


def _strip_path(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")


def _fake_cli_dir(tmp_path, name, body):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / name
    fake.write_text(body)
    fake.chmod(0o755)
    return fake


def test_resolve_cli_executable_searches_install_dirs_when_path_lacks_them(
    tmp_path, monkeypatch,
):
    fake = _fake_cli_dir(tmp_path, "mercari", "#!/bin/sh\necho '{}'\n")
    monkeypatch.setattr(
        source_listing, "_EXTRA_CLI_DIRS", (str(fake.parent),), raising=False)
    _strip_path(monkeypatch)

    assert source_listing.resolve_cli_executable("mercari") == str(fake)


def test_resolve_cli_executable_names_the_missing_executable(monkeypatch):
    _strip_path(monkeypatch)
    monkeypatch.setattr(
        source_listing, "_EXTRA_CLI_DIRS", _NO_CLI_DIRS, raising=False)

    with pytest.raises(source_listing.Undetermined) as caught:
        source_listing.resolve_cli_executable("mercari")
    assert "mercari" in str(caught.value)


def test_check_mercari_uses_the_resolved_absolute_path(tmp_path, monkeypatch):
    fake = _fake_cli_dir(tmp_path, "mercari", "#!/bin/sh\necho '{\"status\": \"on_sale\"}'\n")
    monkeypatch.setattr(
        source_listing, "_EXTRA_CLI_DIRS", (str(fake.parent),), raising=False)
    _strip_path(monkeypatch)

    result = checks.check_mercari(_deal("mercari|123"))

    assert result.status == "available"


def test_missing_cli_is_a_per_row_error_naming_the_executable(monkeypatch):
    _strip_path(monkeypatch)
    monkeypatch.setattr(
        source_listing, "_EXTRA_CLI_DIRS", _NO_CLI_DIRS, raising=False)

    result = checks.check_mercari(_deal("mercari|123"))

    assert result.status == "error"
    assert "mercari" in result.detail


def test_missing_cli_batch_is_per_row_errors_naming_the_executable(monkeypatch):
    _strip_path(monkeypatch)
    monkeypatch.setattr(
        source_listing, "_EXTRA_CLI_DIRS", _NO_CLI_DIRS, raising=False)
    deals = [_deal("mercari|%d" % index) for index in range(3)]

    results = checks.check_mercari_batch(deals)

    assert set(results) == {deal["listing_key"] for deal in deals}
    assert all(result.status == "error" for result in results.values())
    assert all("mercari" in result.detail for result in results.values())


def test_check_shopgoodwill_missing_cli_is_a_row_error_naming_the_executable(
    monkeypatch,
):
    _strip_path(monkeypatch)
    monkeypatch.setattr(
        source_listing, "_EXTRA_CLI_DIRS", _NO_CLI_DIRS, raising=False)

    result = checks.check_shopgoodwill(_deal("shopgoodwill|42"))

    assert result.status == "error"
    assert "shopgoodwill" in result.detail


def test_bounded_batch_survives_a_missing_cli_instead_of_crashing(monkeypatch):
    """The live failure, reproduced: a forked child's FileNotFoundError for an
    absent CLI used to abort the whole sweep. Every row must come back as a
    per-row error naming the executable instead."""
    _strip_path(monkeypatch)
    monkeypatch.setattr(
        source_listing, "_EXTRA_CLI_DIRS", _NO_CLI_DIRS, raising=False)
    deals = [_deal("mercari|%02d" % index) for index in range(25)]

    results = sweep._bounded_dispatch_batch(
        deals,
        listing_timeout_seconds=10.0,
        total_deadline=time.monotonic() + 30.0,
        max_workers=2,
        dispatch_fn=checks.dispatch,
        batch_dispatch_fn=checks.dispatch_batch,
    )

    assert set(results) == {deal["listing_key"] for deal in deals}
    assert all(results[deal["listing_key"]].status == "error" for deal in deals)
    assert all("mercari" in results[deal["listing_key"]].detail for deal in deals)


def test_forked_batch_children_resolve_clis_from_install_dirs_with_stripped_path(
    tmp_path, monkeypatch,
):
    fake = _fake_cli_dir(tmp_path, "mercari", (
        "#!/bin/sh\n"
        "shift 2\n"
        "printf '['\n"
        "first=1\n"
        'for id in "$@"; do\n'
        '  [ "$first" -eq 1 ] || printf \',\'\n'
        '  printf \'{"item_id":"%s","status":"ok","item":{"status":"on_sale"}}\' "$id"\n'
        "  first=0\n"
        "done\n"
        "printf ']\n'\n"
    ))
    monkeypatch.setattr(
        source_listing, "_EXTRA_CLI_DIRS", (str(fake.parent),), raising=False)
    _strip_path(monkeypatch)
    deals = [_deal("mercari|%02d" % index) for index in range(4)]

    results = sweep._bounded_dispatch_batch(
        deals,
        listing_timeout_seconds=10.0,
        total_deadline=time.monotonic() + 30.0,
        max_workers=1,
        dispatch_fn=checks.dispatch,
        batch_dispatch_fn=checks.dispatch_batch,
    )

    assert set(results) == {deal["listing_key"] for deal in deals}
    assert all(results[deal["listing_key"]].status == "available" for deal in deals)
