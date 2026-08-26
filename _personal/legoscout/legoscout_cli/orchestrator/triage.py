#!/usr/bin/env python3
"""Rank crawl candidates for appraisal, and reject the ones that cannot clear.

This exists because the crawl got roughly a thousand times wider than the
appraiser.

Facebook Marketplace's search URL takes a `deliveryMethod=shipping` parameter
that the CLI never sent, so every LegoScout run until 2026-08-18 saw one metro:
`https://www.facebook.com/marketplace/evansville/search/?query=...`. A local
`lego bulk` pass returns about 150 rows at a 21% LEGO hit rate. The same query
with `deliveryMethod=shipping` returns 800 unique rows without exhausting, at
98%, from Orangeburg SC, Harrisonburg VA, Chicago IL, West Olive MI, Wylie TX,
Centre AL, Fairborn OH and Avon IN. Four queries produced 1,174 unique LEGO
listings.

The crawl absorbs that fine -- it is minutes of paging. The appraiser does not:
one batch of 25 took 19 minutes of BrickLink comps and vision, so 1,174 is
roughly 15 hours. A run has to choose, and choosing at random wastes the budget
on lots whose economics were knowable before the first comp.

Two jobs, kept separate on purpose:

  * `reject()` answers a question with a PROVABLE no. A shipped bulk lot whose
    asking price ALONE already exceeds the walk-away $/lb can never clear,
    because freight only adds cost. That is arithmetic, not a guess, and it
    removed 77 of the 1,174 live listings.
  * `rank()` orders what survives. It never rejects on a rank signal -- a low
    rank means "appraise this after the better ones", never "this is bad". The
    ordering exists so a capped run spends its appraiser on the candidates whose
    economics are already visible.

Nothing here estimates a weight, invents a price, or decides a score. The
scorer owns every point value, the appraiser owns vision and comps, and this
module owns only the order they see things in.
"""
from __future__ import annotations

import re

from ..scoring.score import BULK_WALKAWAY_PER_LB

# A weight the SELLER stated in the title: "2 lbs", "4lb", "1.5 lb",
# "10 pounds", ".88 lb". The leading-decimal case is not hypothetical -- a first
# cut of this pattern read "LEGO .88 lb Lot" as 88 lb and turned a $10 listing
# into $0.11/lb, which is a reject promoted to the top of the run.
_WEIGHT = re.compile(r"(\d*\.?\d+)\s*(?:lbs?\b|pounds?\b)", re.I)

# A LEGO set number in the title. Deliberately loose: the appraiser resolves it
# against the BrickLink catalog and a miss costs one lookup, while a missed set
# costs the whole comp path. `weight_lbs`-style noise ("321 pcs") does not match
# because a piece count is not bounded to 4-7 digits often enough to matter, and
# a false positive here only reorders, never rejects.
_SET_NUMBER = re.compile(r"\b\d{4,7}\b")

# Words that mean "this is a quantity of loose brick", not a boxed set.
_BULK = re.compile(
    r"\bbulk\b|\blot\b|\bassorted\b|\bmixed\b|\brandom\b|\bpounds?\b|\blbs?\b", re.I)

# Rank tiers, best first. The names are the values `rank()` returns.
WEIGHT_CLEARS = "weight_clears"
SET_NUMBER = "set_number"
BULK_NO_WEIGHT = "bulk_no_weight"
OTHER = "other"

TIERS = (WEIGHT_CLEARS, SET_NUMBER, BULK_NO_WEIGHT, OTHER)


def stated_weight(title):
    """The weight the title states in pounds, or None when it states none.

    None is a real answer here and not a gap: 1,091 of 1,174 live listings
    stated no weight, and the appraiser's vision pass is what resolves those.
    """
    if not title:
        return None
    found = _WEIGHT.search(str(title))
    if found is None:
        return None
    weight = float(found.group(1))
    if weight <= 0:
        return None
    return weight


def price_per_lb(candidate):
    """Asking price per stated pound, or None when either half is missing.

    This is a LOWER BOUND on landed $/lb for a shipped listing, never the real
    figure: Facebook publishes no destination rate, so freight is on top of it.
    That is exactly what makes `reject()` sound in one direction only.
    """
    weight = stated_weight(candidate.get("title"))
    if weight is None:
        return None
    price = candidate.get("static_price")
    if not isinstance(price, (int, float)) or isinstance(price, bool):
        return None
    return price / weight


def reject(candidate):
    """Why this candidate can never clear, or None when it might.

    Only ONE rule, and it is arithmetic rather than judgement: the seller stated
    a weight, and the asking price alone already exceeds the walk-away $/lb. No
    freight quote can rescue that, because freight only adds cost. On the live
    pool this removed 77 listings, every one of them a 1-2 lb bag at $6-10/lb --
    small shipped lots are structurally dead, and they are most of what the
    nationwide search surfaces.

    Absolutely nothing else rejects here. A listing with no stated weight, no
    set number, or a title this module cannot read is a candidate the APPRAISER
    has to look at, not one to drop quietly. Dropping on a signal that is merely
    weak is how a run stops finding things.
    """
    per_lb = price_per_lb(candidate)
    if per_lb is None:
        return None
    if per_lb > BULK_WALKAWAY_PER_LB:
        return ("asking price alone is $%.2f/lb against a $%.2f/lb walk-away, "
                "before any freight -- shipping only adds cost, so this cannot "
                "clear" % (per_lb, BULK_WALKAWAY_PER_LB))
    return None


def rank(candidate):
    """Which appraisal tier this candidate belongs in. Never a rejection.

    The order is by how much of the economics is already visible:

      1. `weight_clears`  -- the seller stated a weight and the price already
         beats the walk-away. The best lots in the live pool were here: 21.5 lb
         at $2.33/lb, 20 lb at $3.00/lb.
      2. `set_number`     -- a set number the appraiser can comp against
         BrickLink sold data without needing vision at all.
      3. `bulk_no_weight` -- loose brick with no stated weight. Real inventory,
         but every figure waits on a vision weight estimate.
      4. `other`          -- everything else, appraised last rather than never.
    """
    if price_per_lb(candidate) is not None:
        return WEIGHT_CLEARS
    title = str(candidate.get("title") or "")
    if _SET_NUMBER.search(title):
        return SET_NUMBER
    if _BULK.search(title):
        return BULK_NO_WEIGHT
    return OTHER


def triage(candidates, limit=None):
    """Split candidates into what to appraise, in order, and what to drop.

    Returns `(appraise, rejected)`. `appraise` is ordered by tier, and within
    the `weight_clears` tier by cheapest $/lb first, because that tier is the
    only one whose members can be compared on evidence this module actually has.
    Order inside every other tier is the caller's, preserved.

    `limit` caps how many are handed to appraisers THIS RUN. It is not a filter:
    the overflow stays in `appraise` order for the next run, which reaches it
    through the same watermark and listing_key de-duplication every source uses.
    A capped run reports what it deferred rather than reporting a clean number
    that hides it -- see the no-silent-caps rule.

    The cap is spread ACROSS tiers, not taken off the top of a single ordering.
    Strict tier order starves whole categories: on the live pool a cap of 100
    filled with 6 `weight_clears` and 94 `set_number` rows and appraised ZERO
    bulk lots, because 482 set listings queued ahead of 321 bulk ones. Bulk
    LEGO by the pound is the thing this project buys, so a run that never
    reaches it is the wrong run however well-ordered it looks. `weight_clears`
    still fills first because it is tiny and already proven on price; the rest
    of the cap is split across the remaining non-empty tiers in proportion to
    their size, so every category gets looked at every run.
    """
    kept, rejected = [], []
    for candidate in candidates:
        reason = reject(candidate)
        if reason is None:
            kept.append(candidate)
        else:
            rejected.append((candidate, reason))

    by_tier = {tier: [] for tier in TIERS}
    for candidate in kept:
        by_tier[rank(candidate)].append(candidate)
    # The one tier whose members can be compared on evidence this module has.
    by_tier[WEIGHT_CLEARS].sort(key=price_per_lb)

    ordered = [c for tier in TIERS for c in by_tier[tier]]
    if limit is None:
        return ordered, rejected
    if limit < 0:
        raise ValueError("limit must be >= 0, got %r" % limit)

    return _allocate(by_tier, limit), rejected


def _allocate(by_tier, limit):
    """Spread `limit` across tiers so no category is starved. Order preserved.

    `weight_clears` is taken in full first -- it is the proven-on-price tier and
    it is small (6 of 1,174 live). What remains is divided among the other
    non-empty tiers in proportion to their size, with any rounding remainder
    handed out in tier order. A tier that cannot use its share gives it back,
    so a small tier never wastes budget a larger one could spend.
    """
    picked = list(by_tier[WEIGHT_CLEARS][:limit])
    remaining = limit - len(picked)
    if remaining <= 0:
        return picked

    rest = [t for t in TIERS if t != WEIGHT_CLEARS and by_tier[t]]
    if not rest:
        return picked

    pool = sum(len(by_tier[t]) for t in rest)
    shares = {t: min(len(by_tier[t]), remaining * len(by_tier[t]) // pool) for t in rest}

    # Hand out the rounding remainder, and any share a tier could not use.
    leftover = remaining - sum(shares.values())
    while leftover > 0:
        grew = False
        for tier in rest:
            if leftover == 0:
                break
            if shares[tier] < len(by_tier[tier]):
                shares[tier] += 1
                leftover -= 1
                grew = True
        if not grew:
            break

    for tier in rest:
        picked.extend(by_tier[tier][:shares[tier]])
    return picked


def deferred(candidates, limit):
    """The candidates a `limit` pushed to a later run. Never silently dropped.

    Computed by DIFFERENCE against what the cap actually picked, not by slicing
    the full ordering. Since `_allocate` spreads the cap across tiers, the
    picked set is no longer a prefix of that ordering, and a prefix slice would
    report the wrong rows as deferred while quietly losing others.
    """
    if limit is None:
        return []
    ordered, _ = triage(candidates)
    picked = {id(c) for c in triage(candidates, limit=limit)[0]}
    return [c for c in ordered if id(c) not in picked]


def summary(candidates, limit=None):
    """Counts a run can report without re-deriving them. Read-only."""
    ordered, rejected = triage(candidates, limit=limit)
    tiers = {tier: 0 for tier in TIERS}
    for candidate in ordered:
        tiers[rank(candidate)] += 1
    return {
        "candidates": len(candidates),
        "rejected_cannot_clear": len(rejected),
        "appraise_now": len(ordered),
        "deferred_to_next_run": len(deferred(candidates, limit)),
        "tiers": tiers,
    }
