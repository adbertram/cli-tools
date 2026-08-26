#!/usr/bin/env python3
"""Live-check dispatch table for the expired-listing sweep (`invalidate/sweep.py`).

A row only ever reaches this module when its `auction_end_date` carries no
usable date -- a real past or future date resolves `sweep.py` on the date
alone, no live check involved. Every function here answers exactly one
question for exactly one row: is this listing still there right now.

Every check is tried in this fixed order, matching the hierarchy the
`legoscout-deal-invalidate` skill documents: CLI (subprocess) -> plain HTTP
fetch -> headless `playwright-cli`. Nothing here ever clicks through, solves,
or waits out a CAPTCHA/bot-wall -- a detected wall is a `blocked` verdict, not
an obstacle to route around. Per the project's hard rule
(`~/Dropbox/GitRepos/Agents/LegoScout/CLAUDE.md`): "CAPTCHA or bot check
appears -> stop that source immediately... never attempt to bypass one."

`CHECKS` covers every namespace this sweep has a real signal for. A namespace
NOT in `CHECKS` falls through to `check_generic`, which `dispatch()` applies
automatically -- there is no namespace this dispatch table can raise a
`KeyError` on.

Two sources are structural exceptions, each confirmed live on 2026-08-08:

  * Reddit (`check_reddit`) never makes a network call. Its own reader
    (`sources/readers/reddit.py`) says outright "DORMANT and hard-blocked...
    Do not probe" -- so this function honours that instead of re-discovering
    the same block on every run.
  * LiveAuctioneers (`check_liveauctioneers`) hit an Incapsula wall on a
    plain fetch AND an hCaptcha "I am human" challenge on a headless
    `playwright-cli goto`, live, on 2026-08-08 -- both tiers, no bypass
    attempted. Its own reader docstring claims "WebFetch renders it fine",
    but WebFetch is an Anthropic-infrastructure fetch this package cannot
    call from a subprocess; it is not a signal `checks.py` can reproduce.

Proxibid (`check_proxibid`) is NOT a confirmed structural exception the way
the other two are: a plain fetch of both the lot page and the category page
succeeded four times in a row, live, on 2026-08-08, with real bidding content
(`proxibid.py`'s own docstring claims a permanent Imperva wall, "re-verified
2026-08-06" -- that finding did not reproduce two days later, which reads as
an intermittent/probabilistic WAF rather than a hard block). `check_proxibid`
therefore genuinely attempts the tiered fetch and classifies whatever it
gets: real content is parsed for the lot's own state, and an Imperva "Error
15" wall -- if one appears on a future run -- is still classified `blocked`,
never bypassed.
"""
from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Literal

from ..sources import listing as source_listing  # noqa: E402
from ..sources import hibid as hibid_reader  # noqa: E402

Status = Literal["gone", "available", "error", "blocked"]

# Mercari can reuse one browser client across multiple item reads. The sweep
# uses this size to keep each batch below its 180-second worker limit.
BATCH_SIZES = {"mercari": 20}


@dataclass(frozen=True)
class CheckResult:
    """One live check's verdict. `detail` is the evidence a report/ledger note carries."""

    status: Status
    detail: str
    stop_source: bool = False


def namespace(listing_key: str) -> str:
    """The marketplace namespace a `listing_key` belongs to: the first `|`
    segment, lowercased. `invalidate/sweep.py` imports this rather than
    keeping a second copy -- one function, one home."""
    return (listing_key or "").split("|", 1)[0].lower()


# ---------------------------------------------------------------------------
# Shared plumbing: CLI failure classification, HTTP with a status code,
# headless-browser text, and bot-wall detection every source-specific
# function draws on.
# ---------------------------------------------------------------------------

# Signatures of an actual bot-wall/CAPTCHA page or CLI error, observed live
# on 2026-08-08 (Imperva on Proxibid, Incapsula + hCaptcha on
# LiveAuctioneers) plus the well-known signatures of the other walls this
# project's sources are documented to hit. Matched case-insensitively against
# whatever text a tier produced. A false positive here just means an
# ordinary page gets classified `blocked` instead of `available` -- the safe
# direction to be wrong in. A false NEGATIVE would mean treating a wall as
# ordinary content and risking a bypass attempt, which is the direction that
# is never acceptable.
_WALL_SIGNATURES = (
    "error 15 - access denied",  # Imperva (Proxibid)
    "incapsula incident id",  # Incapsula (LiveAuctioneers)
    "request unsuccessful",  # generic Incapsula placeholder page
    "i am human",  # hCaptcha checkbox prompt (LiveAuctioneers)
    "hcaptcha",
    "recaptcha",
    "checkpoint",  # Facebook checkpoint/verification page
    "please verify you are a human",
    "unusual traffic",  # Google-style automated-query block
    "access to this page has been denied",
    "attention required",  # Cloudflare challenge title
    "checking your browser",  # Cloudflare interstitial
    "checking if the connection is secure",  # Cloudflare challenge page
    "cloudflare challenge",  # service CLI error after a challenge timeout
    "human verification challenge",  # verified service CLI challenge
)


def _detect_wall(text: Any) -> str | None:
    """The first bot-wall signature found in `text`, or None."""
    if not text:
        return None
    lowered = str(text).lower()
    for signature in _WALL_SIGNATURES:
        if signature in lowered:
            return signature
    return None


def _source_wall(detail: str) -> CheckResult:
    """Return the one blocker verdict that also stops later source checks."""
    return CheckResult("blocked", detail, stop_source=True)


def _from_cli_error(exc: source_listing.Undetermined) -> CheckResult:
    """Classify a reader-layer `Undetermined` raised by `source_listing.cli()`.

    `exc.gone` is `listing.cli()`'s own 404/"not found"/"no longer available"
    detection -- trust it directly rather than re-deriving it. Otherwise check
    for a bot-wall signature in the failure text; anything left over is a
    plain failure (timeout, malformed payload, CLI bug), which is `error`
    (retried next run), never guessed as `gone`.
    """
    detail = str(exc)
    if exc.gone:
        return CheckResult("gone", detail)
    wall = _detect_wall(detail)
    if wall:
        return _source_wall("%s (matched wall signature %r)" % (detail, wall))
    return CheckResult("error", detail)


def _http_get(url: str, timeout: int = 45) -> tuple[int, str]:
    """(status, body) for a plain fetch with the shared reader UA.

    Unlike `source_listing.http()`, this never raises for an HTTP error
    status -- `check_generic` needs the code itself (404/410 is its own
    `gone` signal) rather than only the fact that something went wrong.
    """
    request = urllib.request.Request(url, headers={"User-Agent": source_listing.UA})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return exc.code, body


_PLAYWRIGHT_BIN = "playwright-cli"
_EVAL_RESULT_RE = re.compile(r"### Result\n(.*?)\n### ", re.S)


def _run_playwright(args: list[str], timeout: int = 60) -> tuple[str | None, str | None]:
    """(stdout, None) on a clean exit, (None, detail) otherwise."""
    try:
        proc = subprocess.run(
            [source_listing.resolve_cli_executable(_PLAYWRIGHT_BIN), *args],
            capture_output=True, text=True, timeout=timeout)
    except source_listing.Undetermined as exc:
        return None, "playwright-cli %s failed to run: %s" % (" ".join(args), exc)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, "playwright-cli %s failed to run: %s" % (" ".join(args), exc)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()[:300]
        return None, "playwright-cli %s exited %d: %s" % (" ".join(args), proc.returncode, detail)
    return proc.stdout, None


def _playwright_session_name() -> str:
    """A short session name unique to one headless page read."""
    return "ls%s" % uuid.uuid4().hex[:8]


def _playwright_text(url: str) -> tuple[bool, str]:
    """Open `url`, read `document.body.innerText`, then close the browser.

    `goto` only works after `open`, so this single-shot helper owns the full
    browser lifecycle. It never clicks a "Verify you are human" box, never
    solves a captcha, never waits one out. Returns (True, page_text) on
    success, (False, detail) otherwise.
    """
    session_arg = "-s=%s" % _playwright_session_name()
    _, err = _run_playwright([session_arg, "open", url])
    if err:
        return False, err
    out, err = _run_playwright([
        session_arg, "eval", "() => document.body.innerText"])
    _, close_err = _run_playwright([session_arg, "close"])
    if err:
        if close_err:
            err = "%s; cleanup also failed: %s" % (err, close_err)
        return False, err
    if close_err:
        return False, close_err
    match = _EVAL_RESULT_RE.search(out or "")
    if not match:
        return False, "playwright-cli eval returned no ### Result block: %s" % (out or "")[:300]
    raw = match.group(1).strip()
    try:
        return True, json.loads(raw)
    except json.JSONDecodeError:
        return True, raw


def _tiered_fetch(url: str):
    """Yield (tier, text_or_None, detail_or_None): plain HTTP, then playwright.

    A caller inspects each tier in order and stops at the first one that
    resolves the question; this generator does not decide anything itself.
    """
    try:
        yield "http", source_listing.http(url), None
    except Exception as exc:  # noqa: BLE001 - the network is inherently flaky here
        yield "http", None, "plain HTTP fetch failed: %s" % exc
    ok, text_or_detail = _playwright_text(url)
    if ok:
        yield "playwright", text_or_detail, None
    else:
        yield "playwright", None, text_or_detail


# ---------------------------------------------------------------------------
# Reused near-unchanged from the old sweep.py: ShopGoodwill and Shop The
# Salvation Army are CLI-based and already reliable. HiBid is upgraded to the
# richer, already-existing `sources/hibid.py::lot_state()` (5-attempt
# exponential backoff) rather than the old sweep's single-attempt regex
# scrape of the same blob that module already parses properly.
#
# All three now only fire for the rare case a normally-dated source's row
# has an uncaptured (`unknown`) date -- a real past date short-circuits in
# `sweep.py` before ever reaching this dispatch table.
# ---------------------------------------------------------------------------

def _run_cli_json(args: list[str], timeout: int = 30) -> dict[str, Any] | None:
    # Resolution happens HERE, at dispatch time, so a forked sweep child never
    # re-resolves a bare name against whatever PATH it inherited -- and a
    # genuinely-missing CLI raises `Undetermined` naming the executable, which
    # each caller below files as that row's `error` verdict instead of letting
    # an OSError escape and abort the whole sweep.
    try:
        out = subprocess.run(
            [source_listing.resolve_cli_executable(args[0]), *args[1:]],
            capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return None


def check_shopgoodwill(deal: dict[str, Any]) -> CheckResult:
    item_id = source_listing.lot_id(deal)
    try:
        data = _run_cli_json(["shopgoodwill", "search", "get", item_id])
    except source_listing.Undetermined as exc:
        return CheckResult("error", str(exc))
    if data is None:
        return CheckResult("error", "CLI call failed or non-JSON output")
    # A MISSING `available` key is not the same signal as an explicit
    # `false` -- the former is a payload the CLI never actually answered
    # (shape drift, a partial response), and guessing `gone` from that is
    # exactly the "weak signal -> destructive write" shape that caused a
    # 15-row incident elsewhere in this file. `data.get("available")` alone
    # cannot tell the two apart (both read as `None`/falsy), so the key's
    # presence is checked explicitly. An explicit `available: false` still
    # resolves `gone`, same as before.
    if "available" not in data:
        expired = data.get("isItemEndTimeExpire")
        detail = "no 'available' key in payload; isItemEndTimeExpire=%r, remainingTime=%r" % (
            expired, data.get("remainingTime"))
        return CheckResult("error", detail)
    available = data["available"]
    expired = data.get("isItemEndTimeExpire")
    detail = "available=%r, isItemEndTimeExpire=%r, remainingTime=%r" % (
        available, expired, data.get("remainingTime"))
    return CheckResult("available" if available else "gone", detail)


def check_shopsalvationarmy(deal: dict[str, Any]) -> CheckResult:
    item_id = source_listing.lot_id(deal)
    try:
        data = _run_cli_json(["shopsalvationarmy", "search", "get", item_id])
    except source_listing.Undetermined as exc:
        return CheckResult("error", str(exc))
    if data is None:
        return CheckResult("error", "CLI call failed or non-JSON output")
    auction_status = data.get("auction_status")
    bin_price = data.get("buy_it_now_price")
    ended_no_bin = auction_status == "ended" and not bin_price
    detail = "auction_status=%r, buy_it_now_price=%r" % (auction_status, bin_price)
    return CheckResult("gone" if ended_no_bin else "available", detail)


def check_hibid(deal: dict[str, Any]) -> CheckResult:
    lot_id = source_listing.lot_id(deal)
    try:
        state = hibid_reader.lot_state(lot_id)
    except (ValueError, OSError) as exc:
        detail = str(exc)
        wall = _detect_wall(detail)
        if wall:
            return _source_wall("%s (matched wall signature %r)" % (detail, wall))
        return CheckResult("error", detail)
    is_closed = state.get("is_closed")
    detail = "isClosed=%r, auction_status=%r, isArchived=%r" % (
        is_closed, state.get("auction_status"), state.get("is_archived"))
    return CheckResult("gone" if is_closed else "available", detail)


# ---------------------------------------------------------------------------
# Mercari -- CLI. `mercari listings get <id>` -> `status`. Verified live
# 2026-08-08 against real active rows: `on_sale` (available) and, on a
# different active row, `sold_out` (gone) both came back cleanly with exit 0.
# A genuinely REMOVED listing (mercari|m17725839152, marked unavailable
# earlier today by manual page verification) instead makes the CLI time out
# ("Error: Timed out capturing Mercari item ..."), which is NOT the same
# signal as a clean `sold_out` response and is not treated as `gone` here --
# a timeout cannot be told apart from a network hiccup, so it is `error`.
# ---------------------------------------------------------------------------

def check_mercari(deal: dict[str, Any]) -> CheckResult:
    item_id = source_listing.lot_id(deal)
    try:
        payload = source_listing.cli(["mercari", "listings", "get", item_id])
    except source_listing.Undetermined as exc:
        return _from_cli_error(exc)
    return _mercari_payload_result(payload)


def _mercari_payload_result(payload: dict[str, Any]) -> CheckResult:
    status = payload.get("status")
    if status == "on_sale":
        return CheckResult("available", "status=%r" % status)
    if status == "sold_out":
        return CheckResult("gone", "status=%r" % status)
    if status == "trading" and isinstance(payload.get("lastSoldAt"), int):
        return CheckResult(
            "gone", "status=%r, lastSoldAt=%r" % (status, payload["lastSoldAt"]))
    return CheckResult("error", "unrecognized mercari status=%r -- not guessed either way" % status)


def check_mercari_batch(
    deals: list[dict[str, Any]],
) -> dict[str, CheckResult]:
    item_ids = [source_listing.lot_id(deal) for deal in deals]
    try:
        rows = source_listing.cli(
            ["mercari", "listings", "get-many", *item_ids])
    except source_listing.Undetermined as exc:
        result = _from_cli_error(exc)
        if result.stop_source:
            return {deals[0]["listing_key"]: result}
        return {deal["listing_key"]: result for deal in deals}

    def contract_error(detail: str) -> dict[str, CheckResult]:
        result = CheckResult("error", "mercari get-many contract error: %s" % detail)
        return {deal["listing_key"]: result for deal in deals}

    if not isinstance(rows, list) or len(rows) != len(deals):
        return contract_error(
            "expected %d ordered records, received %r"
            % (len(deals), type(rows).__name__ if not isinstance(rows, list) else len(rows)))
    results: dict[str, CheckResult] = {}
    for deal, item_id, row in zip(deals, item_ids, rows):
        if not isinstance(row, dict) or row.get("item_id") != item_id:
            return contract_error("record order or item_id does not match %r" % item_id)
        row_status = row.get("status")
        if row_status == "ok" and isinstance(row.get("item"), dict):
            results[deal["listing_key"]] = _mercari_payload_result(row["item"])
            continue
        if row_status == "error" and row.get("error_kind") == "not_found":
            results[deal["listing_key"]] = CheckResult("gone", str(row.get("error") or "not found"))
            continue
        if row_status == "error" and row.get("error_kind") == "unreadable":
            results[deal["listing_key"]] = CheckResult("error", str(row.get("error") or "unreadable"))
            continue
        return contract_error("record for %r has an invalid result shape" % item_id)
    return results


# ---------------------------------------------------------------------------
# eBay -- CLI. `ebay listings status <id>` -> `ended` (bool). This status-only
# path does not parse shipping or pickup fields. Full `listings get` retains
# its strict fulfillment contract.
# ---------------------------------------------------------------------------

def check_ebay(deal: dict[str, Any]) -> CheckResult:
    item_id = source_listing.lot_id(deal)
    try:
        payload = source_listing.cli(["ebay", "listings", "status", item_id])
    except source_listing.Undetermined as exc:
        return _from_cli_error(exc)
    ended = payload.get("ended")
    if ended is True:
        return CheckResult("gone", "ended=%r" % ended)
    if ended is False:
        return CheckResult("available", "ended=%r" % ended)
    return CheckResult("error", "ebay payload carries no boolean 'ended' field")


# ---------------------------------------------------------------------------
# Facebook Marketplace -- CLI. `facebook marketplace status <id>` returns the
# normalized status from Facebook's own listing state or its explicit
# unavailable-page markers. The status-only path does not require
# `delivery_types`; full `marketplace get` retains that strict contract. A
# checkpoint/CAPTCHA response is a `blocked` verdict for this row only.
# ---------------------------------------------------------------------------

def check_facebook(deal: dict[str, Any]) -> CheckResult:
    item_id = source_listing.lot_id(deal)
    try:
        payload = source_listing.cli(["facebook", "marketplace", "status", item_id])
    except source_listing.Undetermined as exc:
        return _from_cli_error(exc)
    status = payload.get("status")
    availability = payload.get("availability")
    if status == "gone":
        return CheckResult("gone", "status=%r availability=%r" % (status, availability))
    if status == "available":
        return CheckResult(
            "available", "status=%r availability=%r" % (status, availability))
    return CheckResult(
        "error", "unrecognized facebook status=%r -- not guessed either way" % status)


# ---------------------------------------------------------------------------
# StockX -- CLI. `stockx products market <url_key>` succeeding at all is the
# signal: StockX is a standing catalog/order-book, not a single seller's
# listing, so "the product page still resolves" is what `available` means
# here (per plan direction) rather than any particular ask/bid value. A
# missing product 404s through `source_listing.cli()`'s own gone detection.
# Verified live 2026-08-08: a real product resolved cleanly; a bogus url_key
# raised Undetermined with gone=False (its error text does not match
# `_GONE_RE`), which correctly falls through to `error` here, not `gone`.
# ---------------------------------------------------------------------------

def check_stockx(deal: dict[str, Any]) -> CheckResult:
    lot = source_listing.lot_id(deal)
    try:
        source_listing.cli(["stockx", "products", "market", lot])
    except source_listing.Undetermined as exc:
        return _from_cli_error(exc)
    return CheckResult("available", "stockx market data resolved for %r" % lot)


# ---------------------------------------------------------------------------
# Depop -- one direct-URL request. The response status and body are both
# required because Depop currently returns a Cloudflare challenge as HTTP
# 403. `source_listing.http()` raised before callers could inspect that body,
# so the old checker discarded the wall and ran two unrelated fallbacks.
#
# A 200 response still uses the verified schema.org Product JSON-LD signal.
# A 404/410 is gone. A confirmed wall stops this source. Any other response
# or parser miss remains one row's error and does not stop the source.
# ---------------------------------------------------------------------------

def check_depop(deal: dict[str, Any]) -> CheckResult:
    url = source_listing.direct_url(deal)
    try:
        status, text = _http_get(url)
    except Exception as exc:  # noqa: BLE001 - network errors are row errors
        return CheckResult("error", "direct URL fetch failed: %s" % exc)
    if status in (404, 410):
        return CheckResult("gone", "HTTP %d" % status)
    wall = _detect_wall(text)
    if status == 403:
        detail = "HTTP 403 direct URL denied source access"
        if wall:
            detail += " (matched wall signature %r)" % wall
        return _source_wall(detail)
    if wall:
        return _source_wall(
            "HTTP %d direct URL hit a bot wall (%r)" % (status, wall))
    if status != 200:
        return CheckResult(
            "error", "direct URL returned HTTP %d without a bot-wall signature" % status)
    result = _parse_ld_json_availability(text)
    if result is not None:
        return result
    return CheckResult(
        "error", "HTTP 200 direct URL returned no Product JSON-LD availability field")


# ---------------------------------------------------------------------------
# Shared schema.org Product/Offer JSON-LD availability parser -- Poshmark and
# Depop both publish this block on a real listing page, verified live
# 2026-08-08 for each: a plain fetch of a real active listing returns 200
# with a JSON-LD block whose `offers.availability` reads
# `https://schema.org/InStock`. Naive substring text scanning for "sold" was
# tried for Poshmark and REJECTED: the page's own stylesheet defines CSS
# classes like `icon.sold-tag` on every Poshmark page regardless of that
# listing's real state, so "sold" appears in the raw HTML of an ordinary
# in-stock listing too. Only the structured JSON-LD field is used, by both
# functions that call this parser -- one home for the logic, not two copies
# that could drift.
# ---------------------------------------------------------------------------

_LD_JSON_RE = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


def _parse_ld_json_availability(html: str) -> CheckResult | None:
    for match in _LD_JSON_RE.finditer(html):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if data.get("@type") != "Product":
            continue
        availability = (data.get("offers") or {}).get("availability") or ""
        if "InStock" in availability:
            return CheckResult("available", "schema.org availability=%r" % availability)
        if any(token in availability for token in ("OutOfStock", "SoldOut", "Discontinued")):
            return CheckResult("gone", "schema.org availability=%r" % availability)
        return CheckResult("error", "unrecognized schema.org availability=%r" % availability)
    return None


# ---------------------------------------------------------------------------
# Poshmark -- plain HTTP, then playwright-cli. No per-item CLI lookup exists
# (`poshmark listings` only offers `search`).
# ---------------------------------------------------------------------------

def check_poshmark(deal: dict[str, Any]) -> CheckResult:
    url = source_listing.direct_url(deal)
    last_detail = None
    for tier, text, detail in _tiered_fetch(url):
        if text is None:
            last_detail = detail
            continue
        wall = _detect_wall(text)
        if wall:
            return _source_wall("%s tier hit a bot wall (%r)" % (tier, wall))
        result = _parse_ld_json_availability(text)
        if result is not None:
            return result
        last_detail = "%s tier returned content with no Product JSON-LD availability field" % tier
    return CheckResult("error", last_detail or "both fetch tiers produced nothing")


# ---------------------------------------------------------------------------
# AuctionNinja -- plain HTTP, then playwright-cli. `NEEDS_PAGE_READ` says the
# CLOSE COUNTDOWN is client-rendered, but the open/closed state itself is
# not: verified live 2026-08-08, a plain fetch of a real active lot already
# carries server-rendered "Bid Now" and "Current Bid" text with no browser
# needed. The closed-lot phrases below are UNVERIFIED live (every active
# AuctionNinja row today has a real future auction_end_date, so none reaches
# this dispatch table) and are covered instead by a fixture-based unit test.
# ---------------------------------------------------------------------------

_AUCTIONNINJA_GONE_PHRASES = (
    "bidding has ended",
    "this auction has ended",
    "auction has ended",
    "this item is no longer available",
    "lot has closed",
)


def _parse_auctionninja_state(text: str) -> CheckResult | None:
    lowered = text.lower()
    if any(phrase in lowered for phrase in _AUCTIONNINJA_GONE_PHRASES):
        return CheckResult("gone", "page text matched a closed-auction phrase")
    if "bid now" in lowered:
        return CheckResult("available", "page text shows an active 'Bid Now' control")
    return None


def check_auctionninja(deal: dict[str, Any]) -> CheckResult:
    url = source_listing.direct_url(deal)
    last_detail = None
    for tier, text, detail in _tiered_fetch(url):
        if text is None:
            last_detail = detail
            continue
        wall = _detect_wall(text)
        if wall:
            return _source_wall("%s tier hit a bot wall (%r)" % (tier, wall))
        result = _parse_auctionninja_state(text)
        if result is not None:
            return result
        last_detail = "%s tier returned content with neither a 'Bid Now' control nor a closed-auction phrase" % tier
    return CheckResult("error", last_detail or "both fetch tiers produced nothing")


# ---------------------------------------------------------------------------
# LiveAuctioneers -- STRUCTURAL EXCEPTION, confirmed live 2026-08-08. A plain
# fetch of a real active item page returned the 960-byte Incapsula
# placeholder ("Request unsuccessful. Incapsula incident ID: ..."), and a
# headless `playwright-cli goto` of the SAME url rendered an hCaptcha "I am
# human" challenge page instead of the listing. Both tiers hit a wall; per
# the project's hard rule, this is `blocked`, not bypassed. The parsing
# helper below exists in case a future run's network path avoids the wall
# (Adam's own IP/session may not trip it the way this run's did), and is
# unit-tested against fixture text since it could not be exercised live.
# ---------------------------------------------------------------------------

_LIVEAUCTIONEERS_GONE_PHRASES = (
    "lot has closed",
    "bidding has closed",
    "this auction has ended",
    "this lot has ended",
)
_LIVEAUCTIONEERS_OPEN_PHRASES = ("open for bidding", "place bid", "current bid")


def _parse_liveauctioneers_state(text: str) -> CheckResult | None:
    lowered = text.lower()
    if any(phrase in lowered for phrase in _LIVEAUCTIONEERS_GONE_PHRASES):
        return CheckResult("gone", "page text matched a closed-lot phrase")
    if any(phrase in lowered for phrase in _LIVEAUCTIONEERS_OPEN_PHRASES):
        return CheckResult("available", "page text shows an open-bidding signal")
    return None


def check_liveauctioneers(deal: dict[str, Any]) -> CheckResult:
    url = source_listing.direct_url(deal)
    last_detail = None
    for tier, text, detail in _tiered_fetch(url):
        if text is None:
            last_detail = detail
            continue
        wall = _detect_wall(text)
        if wall:
            return _source_wall("%s tier hit a bot wall (%r)" % (tier, wall))
        result = _parse_liveauctioneers_state(text)
        if result is not None:
            return result
        last_detail = "%s tier returned content with no recognizable auction-state signal" % tier
    return CheckResult("error", last_detail or "both fetch tiers produced nothing")


# ---------------------------------------------------------------------------
# Proxibid -- NOT confirmed as a structural exception, despite
# `proxibid.py`'s own docstring. Live-tested 2026-08-08: a plain fetch of
# BOTH the lot page and the category page succeeded four times in a row with
# real content, including the lot's own `LotTimeRem.push("<lot_id>,<seconds>")`
# countdown value server-embedded for client-side rendering. The Imperva
# wall the reader's docstring documents (re-verified 2026-08-06) did not
# reproduce -- read as an intermittent/probabilistic WAF rather than a
# permanent block, so this function genuinely attempts the fetch rather than
# pre-declaring `blocked`. If the wall DOES appear on a future run,
# `_detect_wall` still classifies it, never bypasses it. The "auction ended"
# text path is unverified live (no ended Proxibid lot was available to test
# against) and is covered by a fixture-based unit test.
# ---------------------------------------------------------------------------

_LOT_TIME_REM_RE = re.compile(r'LotTimeRem\.push\("(\d+),(-?\d+)"\)')
_PROXIBID_GONE_PHRASES = ("lot has closed", "bidding has ended", "auction has ended", "this lot is closed")


def _parse_proxibid_state(text: str) -> CheckResult | None:
    lowered = text.lower()
    if any(phrase in lowered for phrase in _PROXIBID_GONE_PHRASES):
        return CheckResult("gone", "page text matched a closed-lot phrase")
    match = _LOT_TIME_REM_RE.search(text)
    if match:
        seconds_remaining = int(match.group(2))
        if seconds_remaining > 0:
            return CheckResult("available", "LotTimeRem seconds_remaining=%d" % seconds_remaining)
        return CheckResult(
            "gone", "LotTimeRem seconds_remaining=%d (the bidding window has elapsed)" % seconds_remaining)
    return None


def check_proxibid(deal: dict[str, Any]) -> CheckResult:
    url = source_listing.direct_url(deal)
    last_detail = None
    for tier, text, detail in _tiered_fetch(url):
        if text is None:
            last_detail = detail
            continue
        wall = _detect_wall(text)
        if wall:
            return _source_wall(
                "%s tier hit a bot wall (%r) -- per the project's hard rule, "
                "stopped rather than bypassed" % (tier, wall))
        result = _parse_proxibid_state(text)
        if result is not None:
            return result
        last_detail = "%s tier returned content with no LotTimeRem countdown or closed-lot phrase" % tier
    return CheckResult("error", last_detail or "both fetch tiers produced nothing")


# ---------------------------------------------------------------------------
# Reddit -- STRUCTURAL EXCEPTION. Its own reader (`sources/readers/reddit.py`)
# says outright: "DORMANT and hard-blocked. Do not probe." There are 0 active
# Reddit rows in the ledger today (source status is `dormant`, not `active`),
# so this path is untested live by construction; it is unit-tested with a
# mocked/fixture scenario instead, asserting no network call is ever made.
# ---------------------------------------------------------------------------

def check_reddit(deal: dict[str, Any]) -> CheckResult:
    return _source_wall(
        "reddit is dormant; every access path is blocked pending a Reddit "
        "OAuth 'script' credential (see sources/readers/reddit.py's own "
        "docstring) -- not probed, per that module's explicit instruction")


# ---------------------------------------------------------------------------
# Generic fallback -- every namespace not explicitly listed above
# (americasthriftsupply, auctionzip, craigslist, estatesales, estatesalesorg,
# govdeals, k-bid, nextdoor, offerup, palletliquidation, and anything future).
# Plain HTTP first (with the real HTTP status, unlike `source_listing.http()`),
# then playwright-cli, tried whenever the first tier's content is AMBIGUOUS --
# not only on an outright fetch failure or a detected wall -- matching how
# every other tiered check in this file (Poshmark/AuctionNinja/
# LiveAuctioneers/Proxibid) already behaves.
#
# Only a clean structural signal is trusted in EITHER direction: HTTP
# 404/410 or an unambiguous removal phrase for `gone`; a real HTTP 200 with
# substantial, listing-shaped visible text (and no removal phrase, wall
# signature, or error-page shape) for `available`. Anything in between --
# an empty/near-empty body, an obvious error-page shape (a 503 "Service
# Temporarily Unavailable" page, an unrendered SPA shell like
# `<div id="root"></div>`) -- is AMBIGUOUS and defaults to `error`, never
# guessed either way. Confirmed live/reproduced 2026-08-08: this fallback
# used to return `available` for both a mocked 503 body and a blank SPA
# shell, which is the wrong direction to guess -- a genuinely gone listing
# behind either shape would never expire.
# ---------------------------------------------------------------------------

_GENERIC_GONE_PHRASES = (
    "no longer available",
    "this listing has been removed",
    "item sold",
    "this post has been deleted",
    "this posting has been deleted",
    "posting has been flagged for removal",
    "listing not found",
)

# Common error-page/maintenance-page phrasing. None of these says anything
# about the LISTING -- they say the SERVER did not answer normally -- so a
# match here is ambiguous (`error`), not `gone` and not `available`.
_GENERIC_ERROR_PAGE_PHRASES = (
    "service unavailable",
    "service temporarily unavailable",
    "internal server error",
    "bad gateway",
    "gateway timeout",
    "an error occurred",
    "something went wrong",
    "site is currently unavailable",
    "under maintenance",
    "we'll be right back",
    "we will be right back",
)

# Strips <script>/<style> block CONTENTS, not just their tags -- a page's
# own stylesheet or client bundle is not "visible" text a human reading the
# page would see, and counting it let boilerplate (e.g. Poshmark's
# `icon.sold-tag` CSS class, present on every page regardless of listing
# state) pad an otherwise-empty body past the length check below.
_SCRIPT_OR_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")

# Below this many characters of real visible text, a page is treated as an
# empty/near-empty shell (an unrendered SPA root, a blank error page) rather
# than confirmed listing content -- conservative on purpose, since the cost
# of guessing wrong here is a listing that can never expire.
_MIN_VISIBLE_LISTING_CHARS = 120


def _visible_text(html: str) -> str:
    """The text a human reading the rendered page would see, roughly."""
    stripped = _SCRIPT_OR_STYLE_RE.sub(" ", html)
    stripped = _TAG_RE.sub(" ", stripped)
    return re.sub(r"\s+", " ", stripped).strip()


def _classify_generic_text(tier: str, text: str) -> CheckResult:
    wall = _detect_wall(text)
    if wall:
        return _source_wall("%s tier hit a bot wall (%r)" % (tier, wall))
    lowered = text.lower()
    gone_match = next((phrase for phrase in _GENERIC_GONE_PHRASES if phrase in lowered), None)
    if gone_match:
        return CheckResult("gone", "%s tier page text matched removal phrase %r" % (tier, gone_match))
    error_match = next((phrase for phrase in _GENERIC_ERROR_PAGE_PHRASES if phrase in lowered), None)
    if error_match:
        return CheckResult(
            "error",
            "%s tier page text matched error-page phrase %r -- ambiguous, not "
            "the listing's own state" % (tier, error_match))
    visible = _visible_text(text)
    if len(visible) < _MIN_VISIBLE_LISTING_CHARS:
        return CheckResult(
            "error",
            "%s tier returned only %d chars of visible content -- too thin to "
            "trust as confirmed listing content, not guessed available"
            % (tier, len(visible)))
    return CheckResult(
        "available",
        "%s tier fetched %d chars of visible page content; no removal "
        "phrase, error-page shape, or wall signature" % (tier, len(visible)))


def check_generic(deal: dict[str, Any]) -> CheckResult:
    url = source_listing.direct_url(deal)
    try:
        status, text = _http_get(url)
    except Exception as exc:  # noqa: BLE001 - the network is inherently flaky here
        ok, pw_text = _playwright_text(url)
        if not ok:
            return CheckResult(
                "error", "http fetch failed (%s); playwright-cli also failed (%s)" % (exc, pw_text))
        return _classify_generic_text("playwright", pw_text)
    if status in (404, 410):
        return CheckResult("gone", "HTTP %d" % status)
    result = _classify_generic_text("http", text)
    if result.status != "error":
        return result
    # The http tier's content was AMBIGUOUS (not an outright failure) --
    # attempt the playwright fallback tier before giving up, the same way
    # every other tiered check in this file already does.
    ok, pw_text = _playwright_text(url)
    if not ok:
        return CheckResult(
            "error",
            "http tier ambiguous (%s); playwright-cli also failed (%s)"
            % (result.detail, pw_text))
    return _classify_generic_text("playwright", pw_text)


# ---------------------------------------------------------------------------
# Dispatch. Every namespace this project's live source registry (`legoscout
# sources list`) carries is either named here explicitly or falls through to
# `check_generic` -- there is no namespace `dispatch()` can KeyError on.
# ---------------------------------------------------------------------------

CHECKS: dict[str, Callable[[dict[str, Any]], CheckResult]] = {
    "shopgoodwill": check_shopgoodwill,
    "shopsalvationarmy": check_shopsalvationarmy,
    "hibid": check_hibid,
    "mercari": check_mercari,
    "poshmark": check_poshmark,
    "depop": check_depop,
    "stockx": check_stockx,
    "ebay": check_ebay,
    "facebook": check_facebook,
    "auctionninja": check_auctionninja,
    "liveauctioneers": check_liveauctioneers,
    "proxibid": check_proxibid,
    "reddit": check_reddit,
}


def dispatch(deal: dict[str, Any]) -> CheckResult:
    """The live-check verdict for one deal, routed by its listing_key's namespace."""
    check = CHECKS.get(namespace(deal.get("listing_key", "")), check_generic)
    return check(deal)


def dispatch_batch(deals: list[dict[str, Any]]) -> dict[str, CheckResult]:
    """Dispatch one same-source batch. Source-specific batching belongs here."""
    if deals and namespace(deals[0].get("listing_key", "")) == "mercari":
        return check_mercari_batch(deals)
    return {deal["listing_key"]: dispatch(deal) for deal in deals}
