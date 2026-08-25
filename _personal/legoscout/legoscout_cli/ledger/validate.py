#!/usr/bin/env python3
"""Hard gate: a deal record is invalid unless it stores a usable numeric price.

Run this at synthesis, BEFORE writing the ledger. Every downstream number
-- landed cost, $/lb, set profit, fees, sales tax, the score -- reads the numeric
price fields. A row that carries its price only as prose ("$36 + $9.99
shipping") silently drops out of all of it while still looking populated on the
deals page, so the failure is invisible exactly where it matters.

The 2026-07-26 audit found 32 such rows. Nothing had flagged them because the
output contract described the numeric fields but nothing enforced them.

Rules, in order of how badly they mislead:

  ERROR  no numeric price on any of buy_now_price / static_price / current_price
  ERROR  price_basis says buy_now but buy_now_price is absent (and vice versa)
  ERROR  buy_now_price present but price_basis is current_price -- a BIN listing
         priced off a lower live bid understates cost (cost the 2026-07-23 run
         ~40% on one eBay lot)
  ERROR  a non-auction row priced at exactly $0.00 -- free is not a price
  ERROR  no available_fulfillment, so nothing knows whether the listing can be
         shipped at all -- and the pipeline must never assume it can
  ERROR  a local-pickup-only row outside the 30-mile pickup radius -- Adam
         cannot collect it, so it is not a deal at any price
  ERROR  $0.00 shipping on a row outside that radius -- free pickup is only
         real when Adam can drive to it
  ERROR  a shipping charge on a row the seller will not ship
  ERROR  image_urls and observations.vision.status disagree -- 'checked' with no
         URLs means the image pass had nothing to look at, and 'no_images' with
         URLs means it failed to read photos that exist. Both look identical to
         a listing that genuinely has no photos, which is why they are errors
  WARN   an active row reports an image verdict but records no image_urls
  WARN   auction row with no auction_end_date
  WARN   URL looks like a catalog/event page rather than a single lot, so no
         single price can exist
  WARN   `source` does not match source_names.CANONICAL for its listing_key
         namespace -- drift here silently splits one source into two in every
         per-source grouping ('hibid' vs 'HiBid' cost 65 records)

$0.00 IS valid on an auction: a zero opening bid is a real, meaningful price.

    legoscout deals validate                 # report
    legoscout deals validate --strict        # exit 1 if any ERROR
    legoscout deals validate --file some.db
"""
import argparse
import json
import re
import sys

from . import fulfillment as af
from . import schema as deal_schema
from . import db as ledger_db
from . import shipping as se
from . import source_names
from ..sources import readers as source_readers

LEDGER = ledger_db.DB_PATH
PRICE_FIELDS = ("buy_now_price", "static_price", "current_price")
SKIP_STATUS = {"unavailable", "blocked"}

# The three values legoscout_cli/display/rows.py accepts. The page
# THROWS on anything else, so an unenforced value here does not degrade a row --
# it takes the whole page down. On 2026-08-04, 185 active Mercari records held
# `listing_type: "bulk"` (a listing_category value), `--strict` exited 0 on all
# 1,661 checked records, and `node legoscout display rows` exited 1.
LISTING_TYPES = ("auction", "auction_with_buy_now", "fixed")

# The four values the classifier may tag a listing with. `excluded` is the
# one that keeps books, hardware, storage, displays, and any non-LEGO-piece
# listing out of the deals table entirely -- an `excluded` row must carry
# `status: rejected` (enforced in `_enum_errors` below) and a non-empty
# `exclusion_reason`. The page renders the value verbatim in the cat column,
# and the scorer raises on anything outside this vocabulary, so an
# unenforced value here is a run-defect, not a cosmetic one.
LISTING_CATEGORIES = ("bulk", "set", "minifigure", "excluded")

# The price_basis vocabulary. 13 active Shop The Salvation Army records held
# `price_basis: "auction"`, which is a listing_type word, not a price basis.
# Nothing flagged it, and the listing_type repair's auction test did not
# recognise it, so a blanket re-run would have demoted 13 live auctions to
# `fixed`. The correct value is `current_price`: the contract states that on an
# auction with no bids yet, the opening bid IS the current price.
#
# READ from deal_schema, not restated. This was a hand-kept third copy beside
# the JSON enum and `PRICE_FIELD_BY_BASIS`, and two values drifted between the
# three on 2026-08-06: `ask_price` (retired -- a fixed ask IS a static price)
# and `estimated` (retired -- an estimated price is an invented price, and it
# was legal here while naming no column, so a $45 listing carrying a $999
# hammer passed `--strict` clean). `price_bases()` raises rather than letting
# the two sides disagree again.
PRICE_BASES = deal_schema.price_bases()

# `auction_end_date` sentinels that mean "this listing is not an auction".
NOT_AN_AUCTION = ("not-an-auction",)
# Index/catalog/event URLs describe a SALE, not a lot -- they can never carry one
# price, so a deal record pointing at one is malformed rather than incomplete.
CATALOG_URL_RE = re.compile(
    r"/catalog\.asp|/catalog/\d+|estatesales\.net/[A-Z]{2}/|/auction-catalog|"
    r"/event-catalog/|catalog\.asp\?aid=", re.I)


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def is_auction(rec):
    """Read off `listing_type`, which is the only field that answers this.

    It used to fall back to `price_basis == "current_price"` and then to the
    presence of an end date. Both are the inference output_contract.md forbids:
    a not-yet-started auction has no current price, and a stored end date can
    itself be the broken field -- 53 live ShopGoodwill auctions carried
    `auction_end_date: 'not-an-auction'` while the source returned
    `isAuction: true`. `_enum_errors` now makes an illegal listing_type an
    ERROR, so there is a value to read.
    """
    return str(rec.get("listing_type") or "").startswith("auction")


def _enum_errors(rec):
    """The vocabularies the page and the scorer enforce and the ledger did not.

    Failures here look like populated fields. None of them degrade one row: an
    illegal `listing_type` throws in legoscout_cli/display/rows.py and takes the entire deals
    page down, an illegal `price_basis` makes every price-basis rule below
    silently match nothing, and an illegal `listing_category` raises in the
    scorer, which aborts a full-ledger rescore on one bad row.
    """
    out = []
    lt = rec.get("listing_type")
    if lt not in LISTING_TYPES:
        out.append("listing_type is %r, not one of %s -- the deals page throws "
                   "on this and stops building entirely"
                   % (lt, "/".join(LISTING_TYPES)))
    cat = rec.get("listing_category")
    if cat not in LISTING_CATEGORIES:
        out.append("listing_category is %r, not one of %s -- the scorer raises "
                   "on this and rescore aborts on one bad row; the classifier "
                   "may only tag bulk, set, minifigure, or excluded"
                   % (cat, "/".join(LISTING_CATEGORIES)))
    if cat == "excluded":
        if rec.get("status") != "rejected":
            out.append("listing_category=excluded but status=%r -- an excluded "
                       "listing (book, hardware, non-brick item) must never "
                       "appear as an active deal; record it rejected with the "
                       "reason in notes" % rec.get("status"))
        reason = rec.get("exclusion_reason")
        if not isinstance(reason, str) or not reason.strip():
            out.append("listing_category=excluded but exclusion_reason is "
                       "empty -- record WHY it was excluded, or nobody can "
                       "tell a book from a miscrawl")
    elif isinstance(rec.get("exclusion_reason"), str) and rec.get("exclusion_reason").strip():
        out.append("exclusion_reason=%r on a %r row -- the reason belongs to "
                   "an excluded row only; a priced listing carrying one is a "
                   "misclassified record" % (rec.get("exclusion_reason"), cat))
    basis = rec.get("price_basis")
    if basis not in PRICE_BASES:
        # RAISES rather than reporting. Every price-basis rule below this point
        # reads `priced_amount()`, which returns None for a basis outside the
        # vocabulary, so all of them match nothing and the row is reported
        # CLEAN. `deal_schema.json` gates the value on save, so reaching here
        # means the vocabulary itself drifted -- a code defect, not a data one,
        # and a report that says "clean" for it is a lie.
        raise deal_schema.Invalid(
            "%s: price_basis is %r, not one of %s. Every price-basis rule reads "
            "the price this names, so an unresolvable basis silently passes "
            "every one of them and the record is reported clean."
            % (rec.get("listing_key", "<no listing_key>"), basis,
               "/".join(PRICE_BASES)))
    # A row cannot be an auction and declare itself not an auction. When the two
    # disagree one of them is wrong, and a backfill that reads the wrong one
    # turns a single bad field into two.
    if lt in ("auction", "auction_with_buy_now") \
            and rec.get("auction_end_date") in NOT_AN_AUCTION:
        out.append("listing_type=%r but auction_end_date=%r -- the row claims "
                   "to be an auction and not an auction at once; re-read the "
                   "listing and fix whichever field is wrong"
                   % (lt, rec.get("auction_end_date")))
    out.extend(_figure_count_errors(rec, cat))
    out.extend(_minifig_analysis_errors(rec, cat))
    return out


# `detection` arrived with per-figure identification (2026-08): the
# identifier pipeline owns the count and `minifig_analysis` carries the
# evidence. `stated`/`photo_count` remain legal on legacy rows.
FIGURE_COUNT_SOURCES = ("stated", "photo_count", "unknown", "detection")


def _figure_count_errors(rec, cat):
    """`figure_count` and its provenance travel together.

    The minifigure pricing path multiplies the eBay $/fig average by
    `figure_count`, so a bare number with no provenance is exactly how an
    invented count reaches Adam's money: `stated` is the seller's own claim,
    `photo_count` is the mandatory image pass's exact count, and `unknown`
    means the images were inspected (they always are, on a minifigure
    candidate) but no exact count was determinable. A number with no source,
    or a source on a non-minifigure row, is a hand-off defect -- report it by
    name rather than letting pricing silently consume it.
    """
    out = []
    count = rec.get("figure_count")
    source = rec.get("figure_count_source")
    if isinstance(count, (int, float)) and not isinstance(count, bool):
        if source not in FIGURE_COUNT_SOURCES:
            out.append(
                "figure_count=%s has figure_count_source=%r -- a stated or "
                "photo-counted figure must say which; use 'stated', "
                "'photo_count', or 'unknown' so pricing knows whose word the "
                "count is" % (count, source))
        if cat != "minifigure":
            out.append(
                "figure_count=%s on a %r row -- a figure count belongs to a "
                "minifigure lot only; a priced listing carrying one is a "
                "misclassified record" % (count, cat))
    elif source not in (None, "unknown"):
        out.append(
            "figure_count_source=%r but figure_count=%r -- provenance without "
            "a count names nothing; null both when there is no count"
            % (source, count))
    analysis = rec.get("minifig_analysis")
    if source == "detection" and not isinstance(analysis, list):
        out.append(
            "figure_count_source='detection' but minifig_analysis is %r -- a "
            "detector-owned count needs its canonical per-figure analysis on "
            "the same row" % (analysis,))
    if isinstance(analysis, list) \
            and isinstance(count, (int, float)) and not isinstance(count, bool):
        quantities = []
        for entry in analysis:
            q = entry.get("quantity") if isinstance(entry, dict) else None
            if isinstance(q, (int, float)) and not isinstance(q, bool):
                quantities.append(int(q))
        total = sum(quantities)
        if count != total:
            out.append(
                "figure_count=%s disagrees with the minifig_analysis "
                "entries' quantity sum %s -- on identified rows figure_count "
                "IS the summed entry quantity; re-price or fix whichever is "
                "stale"
                % (count, total))
    return out


def _minifig_analysis_errors(rec, cat):
    """Record-level rules for the canonical per-figure artifact.

    Entry SEMANTICS live canonically in `minifig_analysis.entry_errors()` --
    this wrapper only decides whether the artifact belongs on the row at all,
    then reports each entry's defects named by index so one bad group never
    hides its siblings. A malformed stored artifact is reported, not raised:
    strict validation lists it, readers of unrelated rows keep working.
    """
    from legoscout_cli.ledger import minifig_analysis as mfa

    analysis = rec.get("minifig_analysis")
    if analysis is None:
        return []
    if cat != "minifigure":
        return [
            "minifig_analysis on a %r row -- per-figure identification "
            "belongs to minifigure lots only; a priced listing carrying one "
            "is a misclassified record" % (cat,)]
    try:
        normalized = mfa.normalize(analysis)
    except mfa.Unreadable as exc:
        return ["minifig_analysis unreadable: %s" % (exc,)]
    if not normalized:
        return []
    out = []
    for i, entry in enumerate(normalized):
        for err in mfa.entry_errors(entry):
            out.append("minifig_analysis[%d]: %s" % (i, err))
    out.extend(mfa.batch_errors(normalized))
    return out


def vision_status(rec):
    obs = rec.get("observations")
    vision = obs.get("vision") if isinstance(obs, dict) else None
    return vision.get("status") if isinstance(vision, dict) else None


def _image_url_errors(rec):
    """`no_images` must be a thing someone LOOKED FOR, not a thing that failed.

    The crawler captures `image_urls` through the source's authenticated CLI,
    because a plain fetch of the listing page returns 403 on Shop The Salvation
    Army, an Incapsula challenge on LiveAuctioneers, and a JS shell on Poshmark,
    Mercari and Depop. When that handoff breaks, the image pass finds nothing
    and writes `vision.status: "no_images"` -- a LEGAL value the scorer scores
    around. Nothing raises. Weight goes null, $/lb goes null, and the bare-title
    lots that legoscout-pricing calls disproportionately good deals go
    invisible.

    So `image_urls` and `vision.status` must agree, and the disagreement is an
    ERROR rather than a warning: a warning is exactly what this failure already
    looks like.

    Scoped to records that CARRY the field. A record written before the crawl
    captured it has no key, and re-litigating 1,989 of those says nothing about
    whether the pipeline works now.
    """
    if "image_urls" not in rec:
        return []
    urls, status = rec.get("image_urls"), vision_status(rec)
    if urls is not None and not isinstance(urls, list):
        return ["image_urls is %s, not a list of URLs" % type(urls).__name__]
    if status == "checked" and not urls:
        return ["observations.vision.status is 'checked' but image_urls is %r "
                "-- there was nothing to check, so the image pass did not run"
                % (urls,)]
    if status == "no_images" and urls:
        return ["observations.vision.status is 'no_images' but %d image URL(s) "
                "were captured -- the photos exist and the image pass failed to "
                "read them" % len(urls)]
    return []


def _image_url_warnings(rec):
    """The legacy gap, kept visible rather than silently accepted.

    An active row that reports an image verdict but records no URLs predates
    the crawl/appraise split. It cannot be re-checked, and it is not a defect in
    a current record, so it warns. Once the crawl agents are the only writer,
    this becomes unreachable.
    """
    if "image_urls" in rec or rec.get("status") != "active":
        return []
    if vision_status(rec) in ("checked", "no_images"):
        return ["reports observations.vision.status=%r but records no "
                "image_urls -- the verdict cannot be re-checked"
                % vision_status(rec)]
    return []


def shipping_errors(rec):
    """The source quoted a rate and the landed cost ignored it.

    `shipping_estimate` is what the marketplace published; `shipping_handling` is
    what the landed cost was built from, and it is the only one the deals page
    reads. When a quote exists and the cost math does not use it, the row shows
    Adam a landed total the source itself contradicts -- which is exactly what
    `shopgoodwill|272682584` did, at $29.99 against a published $18.23 of
    freight.

    `build_deal_record._resolve_shipping` makes this unreachable for records the
    pipeline assembles. It stays a rule because the ledger has other writers, and
    because the row that started this was written by a script that bypassed the
    pipeline entirely.
    """
    try:
        estimate = se.of(rec)
    except se.Unreadable as exc:
        return [str(exc).split(": ", 1)[-1]]
    if not estimate or estimate["status"] != se.QUOTED:
        return []
    # Adam has already acted on these, and their landed cost is history. The
    # pickup and $0.00-freight rules below exempt the same statuses for the same
    # reason: re-pricing a closed row cannot change a decision already taken.
    if rec.get("status") in ("rejected", "purchased", "inquired", "bid_placed"):
        return []
    breakdown = rec.get("fee_breakdown")
    if not isinstance(breakdown, dict):
        return []
    total = se.total_of(rec)
    # `shipping_handling` is freight PLUS handling. Where the source itemises its
    # own handling line the estimate already carries it; where it does not, the
    # separate `handling_fee` column does. Mercari is the second case -- 11.99
    # quoted, 2.23 in `handling_fee`, 14.22 landed -- and comparing without it
    # calls 16 correct rows defective.
    if se.of(rec).get("handling_price") is None:
        total += num(rec.get("handling_fee")) or 0.0
    stated = num(breakdown.get("shipping_handling"))
    if stated is None:
        return ["the source quotes $%.2f shipping but the landed cost records "
                "freight as unknown -- the quote was dropped, so the landed "
                "total is a floor that did not have to be one" % total]
    if abs(stated - total) > 0.005:
        return ["the source quotes $%.2f shipping but the landed cost was built "
                "on $%.2f -- one of the two reads is wrong and the deals page "
                "shows the second" % (total, stated)]
    return []


def _quotes_free_shipping(rec):
    """Return true only when the marketplace recorded a zero buyer rate."""
    try:
        estimate = se.of(rec)
    except se.Unreadable:
        return False
    return bool(
        estimate
        and estimate["status"] == se.QUOTED
        and estimate["shipping_price"] == 0
        and estimate["handling_price"] in (None, 0)
    )


def check(rec):
    errors, warns = [], []
    key = rec.get("listing_key", "<no listing_key>")

    # `source` is display text and nothing branches on it, which let it drift --
    # 'hibid' and 'HiBid' were counted as two sources by every per-source
    # grouping. source_names.CANONICAL is the registry; a new spelling is a bug.
    source_problem = source_names.check(rec)
    if source_problem:
        warns.append(source_problem)

    errors.extend(_enum_errors(rec))

    duplicate_set_nos = deal_schema.duplicate_set_analysis_set_numbers(rec)
    if duplicate_set_nos:
        errors.append(
            "set_analysis has duplicate set_no: %s -- each set's resale "
            "value must be counted at most once against its allocated "
            "cost share" % ", ".join(duplicate_set_nos))

    prices = {f: num(rec.get(f)) for f in PRICE_FIELDS}
    have = {f: v for f, v in prices.items() if v is not None}
    basis = rec.get("price_basis")
    auction = is_auction(rec)

    # A source whose reader states that exactly one basis can ever match must
    # not store another. Facebook Marketplace runs no bidding and publishes no
    # Buy It Now, so `buy_now` and `current_price` name prices the platform does
    # not have -- yet 55 of its 122 rows held one, in three waves, because the
    # rule lived only in prose that each run re-read and re-interpreted.
    # `readers.price_bases()` returns None for every source that legitimately
    # stores several, so this is silent on eBay, HiBid and StockX.
    allowed = source_readers.price_bases(
        str(rec.get("listing_key") or "").split("|")[0])
    if allowed and basis not in allowed and basis != "unknown":
        errors.append(
            "price_basis=%r, but sources/readers/%s.py declares PRICE_BASES=%s "
            "-- that source publishes no such price, so the basis names a "
            "column its listings never have"
            % (basis,
               str(rec.get("listing_key") or "").split("|")[0].replace("-", "_"),
               "/".join(allowed)))

    if not have:
        errors.append("no numeric price on any of %s (price_basis=%r, last_price=%r)"
                      % ("/".join(PRICE_FIELDS), basis,
                         str(rec.get("last_price"))[:60]))
    else:
        bn, cur = prices["buy_now_price"], prices["current_price"]
        # A BIN only outranks the live bid while it is still attainable. On
        # ShopGoodwill the BIN disappears once bidding passes it, so
        # current_price > buy_now_price means current_price is the RIGHT basis
        # and the BIN is stale. Only flag the case where a reachable BIN was
        # ignored in favour of a lower bid (understated an eBay lot ~40% on
        # 2026-07-23).
        if bn is not None and basis == "current_price" and (cur is None or bn >= cur):
            errors.append(
                "buy_now_price=%s is still attainable but price_basis=current_price"
                " -- a firm BIN must be priced off the BIN, not a lower live bid"
                % bn)
        # ONE rule over the whole vocabulary rather than a hand-written line per
        # basis. `priced_amount()` is the number every downstream figure reads;
        # when it comes back None while a price IS stored, the declared basis
        # names an empty column and landed cost, $/lb, fees, tax, profit and the
        # score are all computed from nothing. The three lines this replaces
        # covered buy_now, static_price and unknown, and left `current_price`
        # with an empty current_price uncovered -- the same silent-skip shape
        # that let a $999 hammer on a $45 listing pass `--strict` clean.
        if deal_schema.priced_amount(rec) is None:
            column = deal_schema.PRICE_BASIS_COLUMNS[basis]
            errors.append(
                "price_basis=%r names %s, which holds no number, while %s is "
                "stored -- every figure derived from the price is built from "
                "nothing"
                % (basis, column or "no price column at all",
                   ", ".join("%s=%s" % (f, v) for f, v in sorted(have.items()))))
        # $0 is only meaningful as an opening/current bid, so on a fixed-price
        # row it usually means the price failed to parse.
        #
        # Scoped to rows Adam has not closed. A giveaway is real -- Craigslist
        # runs a free section, and `craigslist|centerville|7950326128` is a free
        # LEGO table Adam already rejected. Re-litigating a closed row's price
        # cannot change anything and would fail --strict for good. This matches
        # the pickup gates below, which already exempt every actioned status.
        if not auction and all(v == 0 for v in have.values()) \
                and rec.get("status") not in ("rejected", "purchased",
                                              "inquired", "bid_placed"):
            errors.append("non-auction row priced at $0.00 -- free is not a price")

        # The cost math must be built from the SAME number price_basis names.
        # A stale BIN left in fee_breakdown.hammer after bidding passed it
        # understates landed cost on every derived figure.
        # Read through deal_schema, not a fourth inline copy of the table. This
        # one silently omitted the since-retired `ask_price` basis, so those
        # rows' hammers were never checked against their own price.
        basis_price = deal_schema.priced_amount(rec)
        hammer = num((rec.get("fee_breakdown") or {}).get("hammer"))
        # Live rows only, like every other cost rule here. Two closed Depop rows
        # carried a hammer built from `static_price` while `price_basis` said
        # `ask_price` and `current_price` held a different number; re-pricing a
        # row Adam has already rejected cannot change a decision he has already
        # taken.
        if basis_price is not None and hammer is not None \
                and rec.get("status") not in ("rejected", "purchased",
                                              "inquired", "bid_placed") \
                and abs(hammer - basis_price) > 0.005:
            errors.append(
                "fee_breakdown.hammer=%s disagrees with the %s of %s -- landed "
                "cost is computed from the wrong number"
                % (hammer, basis, basis_price))

    # A carried price_override must have BEEN applied. The schema proves the
    # object's shape; only this cross-check proves the record's numbers obey
    # it. An override whose stated ask disagrees with the stored basis price
    # means the correction was dropped on the way to the ledger -- every fee,
    # profit, and score below it is then denominated in the phantom price the
    # listing's own text contradicts (facebook|1024732190360342 scored 100 off
    # a $5 placeholder while its body said "NOT 5 DOLLARS").
    override = rec.get("price_override")
    if isinstance(override, dict):
        o_price = num(override.get("price"))
        o_evidence = override.get("evidence")
        if isinstance(o_evidence, bool) or not isinstance(o_evidence, str) \
                or not o_evidence.strip() \
                or not any(ch.isdigit() for ch in o_evidence):
            errors.append(
                "price_override.evidence must quote the listing's stated "
                "price(s) verbatim -- got %r; an unevidenced correction is an "
                "invented price" % o_evidence)
        elif o_price is None:
            # The classifier found no usable ask in the text: the crawl price
            # is contradicted and nothing replaced it. The candidate has no
            # cost basis at all -- build_deal_record raises on this shape, so
            # a record carrying it can never have come from a legitimate
            # assembly. Same bucket as every other price-less listing.
            errors.append(
                "price_override.price is null -- the listing text names no "
                "usable ask, so the row has no cost basis and must not be "
                "recorded (numeric-price contract)")
        else:
            basis_price = deal_schema.priced_amount(rec)
            if basis_price is None or abs(basis_price - o_price) > 0.005:
                errors.append(
                    "price_override.price=%s disagrees with the %s price %r "
                    "-- the override was recorded but never applied; landed "
                    "cost and score would be computed off the contradicted "
                    "crawl price"
                    % (o_price, basis, basis_price))

    # Adam can only collect a local-pickup-only lot inside the drive radius, so
    # an out-of-area pickup row is not a deal at any price, and a $0 shipping
    # figure on one is a landed cost that cannot happen. The 2026-07-26 audit
    # found all ten active Craigslist/Facebook/OfferUp rows in exactly that
    # state -- priced as free-pickup while sitting in other states.
    # Adam has already acted on inquired/bid_placed/purchased rows -- an
    # `inquired` row on an out-of-area pickup listing IS the sanctioned flow
    # (he asked the seller to ship), so the gate must not undo it.
    if rec.get("status") not in ("rejected", "purchased", "inquired", "bid_placed"):
        in_range = num(rec.get("pickup_miles")) is not None
        where = rec.get("item_location") or "an unrecorded location"
        ship = num((rec.get("fee_breakdown") or {}).get("shipping_handling"))

        # ONE field answers pickup-vs-ship, and it is read through its own
        # module rather than re-tested here. An unrecorded value is an ERROR,
        # not a warning: the previous WARN let a row with no answer at all sit
        # on the deals page priced as though it shipped for free.
        try:
            pickup_only = af.is_pickup_only(rec)
        except ValueError as exc:
            errors.append(str(exc).split(": ", 1)[-1])
            pickup_only = None

        if pickup_only:
            if not in_range:
                errors.append(
                    "local-pickup-only listing at %r is outside the pickup "
                    "radius -- Adam cannot collect it and the seller will not "
                    "ship" % where)
            if ship:
                errors.append(
                    "carries $%s shipping but available_fulfillment says the "
                    "seller does not ship -- that freight figure is fiction "
                    "and the landed total built on it is too" % ship)
        if af.is_recorded(rec) and af.offers_pickup(rec) and not rec.get("item_location"):
            warns.append("pickup is an option but no item_location was recorded")

        # $0.00 freight is checked whatever available_fulfillment says,
        # including when it says nothing. The 2026-07-26 sweep left every live
        # HiBid lot at `shipping_handling: 0.0` with no fulfillment recorded,
        # and an auction house that ships is precisely the case where freight
        # is a real cost the buyer pays. Free shipping is a thing a fixed-price
        # marketplace listing can genuinely offer; an auction lot cannot.
        if ship == 0 and not in_range and not pickup_only \
                and not _quotes_free_shipping(rec):
            msg = ("priced at $0.00 shipping from %r, which is not an in-radius "
                   "pickup -- estimate it with `legoscout deals refresh "
                   "shipping_estimated`, or record it as an explicit unknown "
                   "(shipping_handling: null)" % where)
            (errors if auction else warns).append(msg)

    errors.extend(shipping_errors(rec))
    errors.extend(_image_url_errors(rec))
    warns.extend(_image_url_warnings(rec))

    if auction and rec.get("auction_end_date") in (None, "", "unknown"):
        warns.append("auction row with no auction_end_date -- the page cannot "
                     "show when bidding closes")
    url = rec.get("url") or rec.get("direct_url") or ""
    if CATALOG_URL_RE.search(url):
        warns.append("URL is a catalog/event page, not a single lot: %s" % url[:80])
    return key, errors, warns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=LEDGER)
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any record has an ERROR")
    ap.add_argument("--include-inactive", action="store_true")
    a = ap.parse_args()

    led = ledger_db.load_document(a.file)
    deals = led.get("deals", led if isinstance(led, list) else [])
    bad, warned, checked = [], [], 0
    for rec in deals:
        if not a.include_inactive and rec.get("status") in SKIP_STATUS:
            continue
        checked += 1
        key, errors, warns = check(rec)
        if errors:
            bad.append({"listing_key": key, "errors": errors})
        if warns:
            warned.append({"listing_key": key, "warnings": warns})

    out = {"checked": checked, "invalid": len(bad), "with_warnings": len(warned),
           "errors": bad, "warnings": warned}
    print(json.dumps(out, indent=2))
    if a.strict and bad:
        print("\nFAIL: %d record(s) violate the price contract" % len(bad),
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
