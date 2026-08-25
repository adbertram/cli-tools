#!/usr/bin/env python3
"""What every source reader genuinely shares: fetching, and cutting text apart.

This is the small half of the retired `signal_reader.py`. The big half was a
571-line interpreter for 841 lines of JSON extraction recipes -- a homegrown
mini-language (`assemble`, `any_of`, `none_of`, `template`, `parts`, `format`,
`truncate_at`, `token_map`) that existed so per-source knowledge could live in
the registry as data. Adam's decision: a signal is not a standardized piece of
data. There is a deal record, and there is per-source code that fills it. So the
recipes became `sources/<namespace>.py` and only the plumbing stayed here.

Nothing in this module knows a marketplace. It fetches, it memoizes, and it
offers the four text operations the source modules need.

Every reader RAISES rather than returning a default. `Undetermined` means "this
listing did not answer"; it never means "assume the usual". That rule is why
`available_fulfillment` exists at all -- a 2026-07-26 audit found ten rows priced
as free in-radius pickup while sitting in other states, because a missing answer
had been read as shipping.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
# `legoscout-ledger` owns the shape of a shipping estimate; a source module only
# supplies the numbers a source published. Same direction as fees.py importing
# registry from here.

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")

# A state-qualified US locality: "Bremerton, WA 98312", "Medina, MN 55340".
# A bare town name is not an answer -- Chandler IN is 15 miles away and Chandler
# AZ is 1,500 -- so `pickup_area.resolve()` raises on one, and the readers here
# refuse to store one.
PATTERNS = {
    "city_state_zip": re.compile(
        r"[A-Za-z][A-Za-z.'\- ]*,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?"),
    "city_state": re.compile(r"[A-Za-z][A-Za-z.'\- ]*,\s*([A-Z]{2})\s*$"),
    "zip": re.compile(r"\b\d{5}(?:-\d{4})?\b"),
}

# A two-letter run before a ZIP is only a state if USPS says so. "US" in
# "Wilkes-Barre Twp, PA, US 18702" is a country, and reading it as the state
# stores "PA, US 18702" as the city/state/ZIP.
USPS_STATES = frozenset(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS "
    "MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV "
    "WI WY DC AS GU MP PR VI".split())

_ENTITIES = (("&nbsp;", " "), ("&amp;", "&"), ("&#39;", "'"),
             ("&quot;", '"'), ("&apos;", "'"))

# Which kind of published price names which `price_basis`, in the order a
# reader must test them. Ordered and EXHAUSTIVE: a live listing publishes a Buy
# It Now, or a live/current price, or a plain asking price, and nothing else.
#
# A TABLE rather than only prose, because prose alone left the third case
# unnamed until 2026-08-06. The rule text named buy_now_price and current_price
# and stopped there, so a fixed-ask source with neither -- every Facebook
# Marketplace post, every Craigslist post -- left the worker to invent an
# answer: 85 Facebook rows of ONE identical shape carried four different bases
# (current_price 36, ask_price 28, buy_now 19, unknown 2). `PRICE_BASIS_RULE` is
# now RENDERED from this table and `price_basis_for()` resolves from it, so the
# sentence a worker reads and the answer the code computes cannot drift apart.
#
# (column to fill, price_basis to record, what the listing published)
PRICE_BASIS_BRANCHES = (
    ("buy_now_price", "buy_now",
     "a Buy It Now or other firm purchase price, even when a lower live bid "
     "exists"),
    ("current_price", "current_price",
     "a live or current price, including a zero-bid auction's opening bid (a "
     "real number, never `estimated`)"),
    ("static_price", "static_price",
     "a plain asking price with no bidding and no separate Buy It Now -- a "
     "fixed ask, which is what every Facebook Marketplace and Craigslist post "
     "is"),
)

_RULE_HEAD = (
    "Take the FIRST branch below that matches what the listing itself "
    "publishes. The three are exhaustive, so `unknown` is never the answer for "
    "a listing you could read. ")

_RULE_TAIL = (
    " Write the number into the ONE column its branch names and leave the "
    "other two null. There is no separate basis for a fixed ask: the retired "
    "`ask_price` is not a value the schema allows, because a fixed ask IS a "
    "static price.")

PRICE_BASIS_RULE = _RULE_HEAD + " ".join(
    "(%d) The listing publishes %s -> record that number in `%s` and set "
    "price_basis: %s." % (n, published, column, basis)
    for n, (column, basis, published) in enumerate(PRICE_BASIS_BRANCHES, 1)
) + _RULE_TAIL


class Undetermined(Exception):
    """This listing did not answer. Never softened into a default.

    `gone` marks the sub-case where the source positively reported the listing
    no longer exists (an HTTP 404 behind the CLI). That is a FACT about the
    listing, not a failure to read it, and a caller may act on it -- see
    `ledger_sweep`. Everything else is an unread listing.
    """

    def __init__(self, message, gone=False):
        super().__init__(message)
        self.gone = gone


def price_basis_for(record):
    """The ONE `price_basis` that `PRICE_BASIS_RULE` names for these columns.

    Walks `PRICE_BASIS_BRANCHES` in order and returns the first branch whose
    column holds a real number, which is exactly what the rendered rule tells a
    worker to do. A record with no numeric price at all RAISES: an unpriced
    listing is not a `price_basis: unknown` row, it is a row that was never
    read. This is what makes "two workers cannot disagree" checkable -- the
    fixed-ask case resolves to `static_price` here and in the sentence, from the
    same table.
    """
    for column, basis, _ in PRICE_BASIS_BRANCHES:
        value = record.get(column)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return basis
    raise Undetermined(
        "%s holds no number in any of %s, so no branch of PRICE_BASIS_RULE "
        "matches and there is no basis to record -- re-read the listing"
        % (record.get("listing_key", "<no listing_key>"),
           "/".join(column for column, _, _ in PRICE_BASIS_BRANCHES)))


# ---------------------------------------------------------------------------
# Keys. The listing_key is the only identifier a reader starts with.
# ---------------------------------------------------------------------------

def lot_id(deal):
    """The lot id: the LAST pipe-separated segment, not everything after the first.

    HiBid keys carry the auction house in the middle
    (`hibid|agelessauctions|292219745`), and EstateSales.NET carries the sale
    (`estatesales|4975902|226831907`), so splitting once hands the reader
    `agelessauctions|292219745` and `hibid_lot_state` rejects it.
    """
    return str(deal["listing_key"]).split("|")[-1]


def auction_id(deal):
    """The parent auction id, for K-BID, whose `listing_key` is
    `k-bid|<auction>-<lot>` and whose removal address and seller live on the
    parent auction page rather than the lot page."""
    return lot_id(deal).split("-")[0]


def direct_url(deal):
    """The listing's own URL. RAISES when the record carries none.

    The `or ""` this replaced was a fallback: an empty string went straight to
    urllib, which answered `unknown url type: ''`. That message names neither
    the listing nor the missing field, and it is what `legoscout deals read`
    returned for every crawl-phase candidate that has no ledger row yet.
    """
    url = deal.get("direct_url") or deal.get("url")
    if not url:
        raise Undetermined(
            "%s carries no direct_url and no url, so there is no page to read. "
            "A crawl-phase candidate has no ledger row yet -- pass the listing "
            "URL explicitly with `legoscout deals read --url`."
            % deal.get("listing_key", "<no listing_key>"))
    return url


def title(deal):
    return (deal.get("title") or "lego")[:60]


# ---------------------------------------------------------------------------
# Acquisition. One payload per (listing, fetch), memoized for the process, so
# the six fields a ShopGoodwill lot answers cost one CLI call, not six.
# ---------------------------------------------------------------------------

_CACHE: dict = {}

# ShopGoodwill answers a removed item with `status 404`, exit 1 and empty
# stdout. That is the listing being gone, not an unreadable one.
_GONE_RE = re.compile(r"\b404\b|not found|no longer available", re.I)


def cached(key, fn):
    """`fn()`'s result, computed once per key per process.

    The key must identify the FETCH and nothing else. A key that is the same
    string for every lot on a source is a silent cross-listing leak: all HiBid
    lots once read back the first lot's house and returned Osprey, FL for a
    listing in North Fairfield, OH.
    """
    if key not in _CACHE:
        _CACHE[key] = fn()
    return _CACHE[key]


def clear_cache():
    _CACHE.clear()


# uv-installed service CLIs land in ~/.local/bin. A login shell's PATH carries
# that directory; a stripped launch environment (a daemon, a scheduler, another
# tool's subprocess) often does not -- and every multiprocessing-fork child of
# the expired-listing sweep inherits exactly the PATH its parent had, so a bare
# executable name can fail to resolve IN THE CHILD even though the CLI is
# installed. Resolution therefore searches the inherited PATH first and then
# these well-known install dirs, and `cli()` hands subprocess.run the resolved
# ABSOLUTE path, so no child ever re-resolves a bare name against whatever PATH
# it happened to inherit.
_EXTRA_CLI_DIRS = ("~/.local/bin",)


def cli_search_path() -> str:
    """The inherited PATH plus the well-known CLI install dirs it may lack."""
    parts = [os.environ.get("PATH", "")]
    parts.extend(os.path.expanduser(directory) for directory in _EXTRA_CLI_DIRS)
    return os.pathsep.join(part for part in parts if part)


def resolve_cli_executable(name: str) -> str:
    """A service CLI's absolute path, found from a possibly-stripped PATH.

    Raises `Undetermined` rather than returning None or letting subprocess
    raise FileNotFoundError: a genuinely-missing CLI must surface as a
    classified per-row failure that NAMES the executable (`_from_cli_error`
    in invalidate/checks.py files it under `check_failed`, retried next run),
    never as a raw OSError escaping a forked sweep child and aborting the
    whole sweep mid-run.
    """
    resolved = shutil.which(name, path=cli_search_path())
    if resolved is None:
        raise Undetermined(
            "%s executable was not located on PATH or in %s -- install the %s "
            "CLI so rows from this source can be read and live-checked"
            % (name, ", ".join(_EXTRA_CLI_DIRS), name))
    return resolved


def cli(argv):
    """Run a CLI and cut the JSON out of its stdout."""
    argv = [resolve_cli_executable(argv[0]), *argv[1:]]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    text = proc.stdout
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start < 0:
        detail = (proc.stderr or text).strip()[:200]
        raise Undetermined(
            "%s exited %d and printed no JSON: %s" % (argv[0], proc.returncode, detail),
            gone=bool(proc.returncode and _GONE_RE.search(detail)))
    return json.loads(text[start:])


def http(url):
    """Fetch page text with the shared user agent."""
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Reading a payload apart.
# ---------------------------------------------------------------------------

class _Missing:
    def __repr__(self):
        return "MISSING"

    def __bool__(self):
        return False


MISSING = _Missing()


def dig(payload, path):
    """A dotted-path lookup that returns `MISSING` rather than a default."""
    node = payload
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return MISSING
        node = node[part]
    return node


def require(payload, *paths):
    """Paths whose absence means the listing was not read, not that it said no.

    ShopGoodwill's `pickupOnly: false` is an answer, so `False` passes. `None`
    does not: a payload with no `pickupOnly` key, or a null one, is a CLI that
    changed shape, and reading that as "ships" is the exact bug
    `available_fulfillment` exists to prevent.

    Null matters for an assembled location too. Without this, a listing whose
    `pickupState` is null renders the literal text `None` into the stored
    location ("Hillsboro, None 97123").
    """
    for path in paths:
        value = dig(payload, path)
        if value is MISSING or value is None:
            raise Undetermined(
                "the payload carries no %s (%s) -- upgrade the source reader "
                "rather than reading its absence as an answer"
                % (path, "absent" if value is MISSING else "null"))


def truthy(payload, path):
    """Whether a dotted path holds a true answer.

    `"0"`, `"false"` and `"False"` are false, because several sources publish a
    boolean as the text of one. A STATE WORD is never read for truthiness --
    Shop The Salvation Army's `shipping_quote_status` is `quoted`,
    `unavailable`, `destination_required` or `not_applicable`, and every one of
    those is a non-empty string, so truthiness there calls a failed quote a
    successful one. Compare those explicitly.
    """
    value = dig(payload, path)
    return (value is not MISSING and bool(value)
            and value not in ("0", "false", "False"))


def flatten(markup):
    """Tags out, entities in, whitespace collapsed -- the text a human reads."""
    text = re.sub(r"<[^>]+>", " ", markup)
    for entity, char in _ENTITIES:
        text = text.replace(entity, char)
    return re.sub(r"\s+", " ", text).strip()


def window(text, after, size=None, last=True):
    """Narrow a page to the block that holds the answer.

    `after` uses the LAST occurrence by default, matching the two readers this
    replaces: AuctionNinja and K-BID both render a summary panel before the real
    one.
    """
    start = text.rfind(after) if last else text.find(after)
    if start < 0:
        raise Undetermined("the page carries no %r block" % after)
    return text[start:start + size] if size else text[start:]


def group(text, pattern, index=1):
    """One regex group out of a page, or `MISSING`. Never a default."""
    hit = re.search(pattern, text, re.S)
    if not hit:
        return MISSING
    return hit.group(index)


def json_after(text, marker):
    """The balanced JSON object that follows a marker in a page.

    EstateSales.org inlines `window.pageData` rather than exposing an endpoint,
    so its answer has to be cut out of the page by brace balance.
    """
    hit = re.search(marker, text)
    if not hit:
        raise Undetermined("no %r blob on the page" % marker)
    start = text.index("{", hit.start())
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise Undetermined("unbalanced %r blob" % marker)


def tidy(text):
    """Collapse whitespace and drop a trailing comma left by an empty part."""
    return re.sub(r"\s+", " ", text).strip().strip(",").strip()


def require_city_state_zip(text, full=False):
    """Refuse a bare town name.

    `full` is stricter on purpose. AuctionNinja's pickup panel puts its own
    labels ("Shipping Available", "Private Residence") immediately before the
    address, and a substring match happily swallows them into the city name.
    """
    test = "fullmatch" if full else "search"
    if not getattr(PATTERNS["city_state_zip"], test)(text):
        raise Undetermined(
            "location %r is not city_state_zip-qualified (must_%s); a bare town "
            "name cannot be resolved" % (text[:120], "fullmatch" if full else "match"))
    return text


def require_city_state(text):
    """Refuse a bare town name where the source publishes no ZIP at all.

    `require_city_state_zip` is the stricter sibling and stays the default: a
    ZIP is what `pickup_area.resolve()` prefers. But a peer-to-peer marketplace
    that deliberately blurs its sellers' locations never prints one -- Facebook
    Marketplace renders "Evansville, IN" plus "Location is approximate" and
    nothing more -- so demanding a ZIP there rejects the only answer the source
    has and leaves `item_location` unread. A state is the bar that actually
    matters: Chandler IN is 15 miles from ZIP 47725 and Chandler AZ is 1,500.

    The state must be a real USPS state for the same reason `USPS_STATES`
    exists on the ZIP path -- "Evansville, US" is a country, not a state.
    """
    match = PATTERNS["city_state"].search(text.strip())
    if not match:
        raise Undetermined(
            "location %r is not city_state-qualified; a bare town name cannot "
            "be resolved" % text[:120])
    state = match.group(1)
    if state not in USPS_STATES:
        raise Undetermined(
            "location %r ends in %r, which is not a USPS state" % (text[:120], state))
    return text


def trailing_city_state_zip(text):
    """The city/state/ZIP that ENDS a full street address, comma or not.

    `require_city_state_zip(full=True)` refuses a street address outright, and
    the shared pattern demands a comma before the state. AuctionNinja writes
    neither -- "465 Turnpike St, Canton MA 02021" -- so 8 of 26 lots lost their
    location on 2026-08-06 while the reader was quoting the right surface.

    The city is taken from the LAST comma-delimited segment only, which is what
    `full=True` was protecting: a panel label ("Private Residence") or a street
    line in front of the address can no longer be swallowed into the city name.
    Inside that segment the LONGEST 1-3 word city wins, so "East Meadow" and
    "Wilkes-Barre Twp" survive whole. Preferring the fewest tokens instead cut
    "East Meadow, NY 11554" down to "Meadow, NY 11554".
    """
    tail = re.search(r"\b([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\s*$", text)
    if not tail or tail.group(1) not in USPS_STATES:
        raise Undetermined(
            "location %r does not end in a USPS state and ZIP; a bare town "
            "name cannot be resolved" % text[:120])
    # The comma is what separates a street line, or a panel label, from the
    # city. Take the last comma-delimited segment, then the longest 1-3 word
    # city inside it so "East Meadow" and "Wilkes-Barre Twp" survive intact.
    head = text[:tail.start()].rstrip().rstrip(",").rstrip()
    tokens = head.split(",")[-1].split()
    for width in (3, 2, 1):
        if width > len(tokens):
            continue
        city = "%s, %s %s" % (" ".join(tokens[-width:]),
                              tail.group(1), tail.group(2))
        if PATTERNS["city_state_zip"].fullmatch(city):
            return city
    raise Undetermined(
        "location %r ends in %s %s but no 1-3 word city precedes it"
        % (text[:120], tail.group(1), tail.group(2)))


# US timezone abbreviations, as auction sites print them. An abbreviation that
# is not here RAISES: guessing an offset moves a closing time by hours, and a
# lot Adam thinks closes tomorrow morning may already be gone.
_TZ_OFFSETS = {
    "EST": -5, "EDT": -4, "CST": -6, "CDT": -5, "MST": -7, "MDT": -6,
    "PST": -8, "PDT": -7, "AKST": -9, "AKDT": -8, "HST": -10, "HDT": -9,
    "UTC": 0, "GMT": 0,
}
_MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}
# "August 9, 2026 8:00 AM EDT"  /  "Mon, Aug 3, 2026 9:47pm CDT"
_SPELLED_DATE = re.compile(
    r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})"
    r"(?:[\s,]+(\d{1,2}):(\d{2})\s*([AaPp])\.?[Mm]\.?)?"
    r"(?:\s+([A-Z]{2,4}))?")


def iso_end_date(text):
    """A spelled-out auction close time as `YYYY-MM-DDTHH:MM:SS+00:00`.

    `auction_end_date` has a consumer: `invalidate.sweep.parse_past` matches
    `YYYY-MM-DD` at the start of the string and calls anything else "not past".
    A reader that passed "August 3, 2026 4:00 PM EDT" straight through
    therefore stored a lot that could NEVER expire -- two AuctionZip rows sat
    that way. Normalising here is what makes the stored value answerable.

    Raises `Undetermined` rather than guessing any part of it.
    """
    hit = _SPELLED_DATE.search(str(text))
    if not hit:
        raise Undetermined(
            "close time %r is not a spelled-out date this parser reads "
            "(expected e.g. 'August 9, 2026 8:00 AM EDT')" % str(text)[:120])
    month = _MONTHS.get(hit.group(1).lower()) or _MONTHS.get(
        next((name for name in _MONTHS if name.startswith(hit.group(1).lower())),
             ""), None)
    if month is None:
        raise Undetermined("close time %r names no month this parser knows"
                           % str(text)[:120])

    hour, minute = 0, 0
    if hit.group(4):
        hour, minute = int(hit.group(4)), int(hit.group(5))
        if hit.group(6).upper() == "P" and hour != 12:
            hour += 12
        elif hit.group(6).upper() == "A" and hour == 12:
            hour = 0

    abbreviation = hit.group(7)
    if abbreviation and abbreviation not in _TZ_OFFSETS:
        raise Undetermined(
            "close time %r carries timezone %r, which has no known offset -- "
            "add it rather than assuming one" % (str(text)[:120], abbreviation))
    offset = _TZ_OFFSETS.get(abbreviation, 0)

    try:
        local = datetime.datetime(int(hit.group(3)), month, int(hit.group(2)),
                                  hour, minute)
    except ValueError as exc:
        raise Undetermined("close time %r is not a real date: %s"
                           % (str(text)[:120], exc)) from None
    utc = local - datetime.timedelta(hours=offset)
    return utc.replace(tzinfo=datetime.timezone.utc).isoformat()


def never_an_auction(why):
    """An `auction_end_date` reader for a source that runs no auction at all.

    `not-an-auction` is the schema's own value for this field on a fixed-price
    row, so a marketplace that only ever sells at a fixed price ANSWERS this
    field -- it does not fail to. 20 modules used to omit the reader and the
    `NEEDS_PAGE_READ` entry together, and `readers.where()` then told a worker
    the source "states nowhere to look". There is nowhere to look because there
    is nothing to find, and that is a different sentence.

    `why` states the business fact in one clause, for the evidence string.
    """
    def auction_end_date(deal):
        return "not-an-auction", why
    return auction_end_date


def never_quotes_shipping(reason):
    """A `shipping_estimate` reader for a source that publishes no rate at all.

    `shipping.unquoted(reason)` is the schema's own value for "no rate, and
    here is why", so a source that structurally never quotes one ANSWERS this
    field. HiBid houses invoice freight after the sale; K-BID and Facebook
    publish nothing; a pickup-only classified has no freight to quote. Stating
    that once, in the module that knows it, beats 17 workers each deciding
    whether a blank means "free" or "not looked at".
    """
    def shipping_estimate(deal):
        from ..ledger import shipping as se

        return se.unquoted(reason), reason
    return shipping_estimate


def require_zip(text):
    if not PATTERNS["zip"].search(text):
        raise Undetermined(
            "location %r is not zip-qualified (must_match); a bare town name "
            "cannot be resolved" % text[:120])
    return text
