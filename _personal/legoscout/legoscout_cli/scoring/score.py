#!/usr/bin/env python3
"""The LEGO Scout deal scorer. Python owns every number here.

    score = quality x headroom

`quality` is price-free: how good the lot is on its own merits, 0-100. `headroom`
is 0-1: how far the current landed price sits below `max_price`, the most Adam
would pay for a lot of that quality. Multiplying them means a great lot ranks
high while it is cheap and collapses once bidding passes the walk-away number --
so a $1 opening bid ranks on merit and an overpriced listing stops being
highlighted, without the score ever needing to guess where an auction will close.

A model contributes OBSERVATIONS only -- enums, booleans, evidence strings. It
never returns a point value. Its own holistic verdict is recorded as
`model_score` and compared against this score, but never mixed into it: a >15
point divergence sets a flag, which is the signal that this formula is missing a
factor. See `<skill>/references/calibration.md` before changing any constant.
"""

from __future__ import annotations

import math
import sys

# `set_analysis` has ONE reader, and it lives with the ledger that stores the
# field. Importing it is cheaper than a second opinion here about which of the
# five historical shapes is in front of us -- the reason the theme lens only
# ever matched the `{"sets": [...]}` spelling and silently saw no set names on
# every array-shaped row.

from ..ledger import minifig_analysis, set_analysis  # noqa: E402
from . import text_signals  # noqa: E402

SCORER_VERSION = "1.2"

# ---------------------------------------------------------------------------
# Calibration constants. Every tunable number in the scorer lives in this block.
# ---------------------------------------------------------------------------

# Where a PLAIN bulk lot stops being worth buying, per landed pound. This is the
# walk-away, not the target: Adam likes to pay under $3/lb, and the headroom
# curve below is anchored so $2.50/lb on a plain lot reads as full value.
BULK_WALKAWAY_PER_LB = 4.00

# A lot with every signal firing is worth $8/lb -- 2.00 x the plain walk-away.
MAX_QUALITY_MULTIPLIER = 2.00
MIN_QUALITY_MULTIPLIER = 0.35

# A plain, clean, unremarkable bulk lot.
BULK_BASE_QUALITY = 75

# Margin Adam must clear on a set for the buy to be worth handling. `max_price`
# on a set is the net resale value less this.
SET_MIN_PROFIT = 15.00

# A score computed against a weight the model read off photos rather than one
# the seller stated cannot claim the top of the table.
ESTIMATED_WEIGHT_SCORE_CAP = 85

# How far the model's own verdict may sit from the computed score before the row
# is flagged for review.
DIVERGENCE_THRESHOLD = 15

# Applied as a final layer, after every other cap, to a deal from a seller
# Adam has favorited (sellers_db.is_favorite) -- ranking only, never max_price.
# Unconditional on bulk; gated on positive potential_profit on a set, so a
# favorited seller's losing set is never boosted into looking attractive. See
# _favorite_bonus_applies.
FAVORITE_SELLER_BONUS = 15

# Bulk signals. Each carries BOTH its quality delta and its price multiplier, so
# "how good is this lot" and "how much more would I pay for it" can never drift
# apart. Quality deltas are calibrated so: plain 75 -> +colours 82 -> +minifigs
# 88 -> +Star Wars 95 -> +retired 100.
BULK_SIGNALS: dict[str, dict[str, float]] = {
    "minifigs_present": {"quality": 6, "multiplier": 1.22},
    "star_wars": {"quality": 7, "multiplier": 1.20},
    "castle": {"quality": 4, "multiplier": 1.12},
    "technic": {"quality": 4, "multiplier": 1.12},
    "retired_sets": {"quality": 5, "multiplier": 1.15},
    "colors_strong": {"quality": 7, "multiplier": 1.15},
    "colors_moderate": {"quality": 4, "multiplier": 1.07},
    "colors_weak": {"quality": 1, "multiplier": 1.02},
    "duplo": {"quality": -12, "multiplier": 0.88},
    "no_minifigures": {"quality": -12, "multiplier": 0.85},
    "contamination": {"quality": -25, "multiplier": 0.70},
    "by_the_pound": {"quality": -35, "multiplier": 0.55},
    # A lot advertised by PIECE COUNT rather than weight has been counted, and
    # counting is what a seller does after sorting one -- the figs and good sets
    # are already gone and the ask prices the remainder as inventory (Adam,
    # 2026-08-24, facebook|28198740076450822). Lighter than by-the-pound: that
    # is a pricing model, this is evidence of pick-over. The penalty lands the
    # plain-lot walk-away at $2.88/lb, just under Adam's $3/lb preferred line.
    "piece_count_advertised": {"quality": -20, "multiplier": 0.72},
}

# Headroom as a function of price / max_price. Anchored so a plain lot at
# $2.50/lb (0.625 of the $4.00 walk-away) earns exactly full value, then decays
# through the walk-away and reaches zero 30% past it.
#
# Above 1.00 is the bargain band. Without it the curve saturated: a plain lot at
# $1.00/lb and one at $2.50/lb both scored 75, so being 2.5x cheaper bought
# nothing. It is capped at 1.20 rather than left open so a cheap plain lot
# cannot outrank a genuinely good one -- price is a multiplier on merit, not a
# substitute for it.
_HEADROOM_CURVE: tuple[tuple[float, float], ...] = (
    (0.100, 1.20),
    (0.300, 1.10),
    (0.625, 1.00),
    (0.850, 0.78),
    (1.000, 0.55),
    (1.300, 0.00),
)

# Set quality as a function of net resale value after fees. Anchored so that at
# full headroom a realized profit of ~$25 reads as "good" and ~$75 as "great".
_SET_QUALITY_CURVE: tuple[tuple[float, float], ...] = (
    (0.0, 0.0),
    (10.0, 35.0),
    (25.0, 66.0),
    (50.0, 82.0),
    (75.0, 90.0),
    (150.0, 96.0),
    (300.0, 99.0),
    (600.0, 100.0),
)

# Thin comps mean the profit figure itself is a guess, so they discount the
# quality of the opportunity rather than the price.
_COMP_DEPTH_MULTIPLIERS: tuple[tuple[int, float], ...] = (
    (15, 1.00),
    (8, 0.94),
    (4, 0.85),
    (2, 0.75),
    (1, 0.60),
)
_COMP_DEPTH_UNKNOWN = 0.55

_COMPLETENESS_MULTIPLIERS = {
    "complete": 0.94,
    "unknown": 0.78,
}
_SEALED_MULTIPLIER = 1.00

# Same profit on paper, very different time to cash.
_THEME_LIQUIDITY = {
    "star_wars": 1.05,
    "ucs": 1.05,
    "modular": 1.05,
    "creator_expert": 1.00,
    "technic": 1.00,
    "ideas": 1.00,
    "city": 0.88,
    "friends": 0.88,
    "duplo": 0.88,
    "juniors": 0.88,
}
_THEME_LIQUIDITY_UNKNOWN = 0.96

_LIQUID_CATEGORY_WORDS = (
    ("star_wars", ("star wars", "starwars")),
    ("ucs", ("ultimate collector",)),
    ("modular", ("modular",)),
    ("creator_expert", ("creator expert",)),
    ("technic", ("technic",)),
    ("ideas", ("lego ideas",)),
    ("city", ("lego city",)),
    ("friends", ("lego friends",)),
    ("duplo", ("duplo",)),
    ("juniors", ("juniors",)),
)


# ---------------------------------------------------------------------------
# Curve helpers
# ---------------------------------------------------------------------------


class ScoringInputError(ValueError):
    """A stored number this record cannot be scored from, NAMED by listing_key.

    The whole point of this class is the key. `score rescore` used to abort the
    entire ledger on a bare `AssertionError: curve lookup fell through for
    x=nan`, which named no listing, so the one corrupt row could not be found
    without bisecting the ledger by hand.
    """

    def __init__(self, listing_key, message: str):
        self.listing_key = listing_key
        super().__init__("%r: %s" % (listing_key, message))


def _interpolate(curve: tuple[tuple[float, float], ...], x: float) -> float:
    """Piecewise-linear lookup, clamped at both ends.

    `nan` satisfies neither clamp branch and neither side of `x0 <= x <= x1`, so
    an unguarded non-finite x walked the whole curve and fell out of the bottom
    of the loop. That is a corrupt input, not an impossible control path, and it
    is rejected here by name.
    """
    if not math.isfinite(x):
        raise ValueError(
            "curve lookup needs a finite x, got %r. `nan` and `inf` are not "
            "positions on a curve -- fix the number that produced this." % x)
    if x <= curve[0][0]:
        return curve[0][1]
    if x >= curve[-1][0]:
        return curve[-1][1]
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if x0 <= x <= x1:
            span = x1 - x0
            if span == 0:
                return y1
            return y0 + (y1 - y0) * (x - x0) / span
    raise AssertionError(f"curve lookup fell through for x={x}")


def headroom(price: float, max_price: float, listing_key) -> float:
    """How much room is left between the current price and the walk-away.

    `listing_key` is REQUIRED, and its only job is to be in the exception. An
    infinite `estimated_total` makes `price / max_price` = `inf / inf` = `nan`
    on a set, and the resulting failure has to say WHICH listing carries the
    corrupt number -- see ScoringInputError.
    """
    if not math.isfinite(price):
        raise ScoringInputError(
            listing_key,
            "landed price is %r, which is not an amount of money. Fix the "
            "record's estimated_total; it is not scorable as stored." % price)
    if not math.isfinite(max_price):
        raise ScoringInputError(
            listing_key,
            "max_price computed to %r, so the walk-away is undefined. Its "
            "inputs (weight_lbs on a bulk lot, potential_profit plus "
            "estimated_total on a set) hold a non-finite number." % max_price)
    if max_price <= 0:
        return 0.0
    return round(_interpolate(_HEADROOM_CURVE, price / max_price), 4)


# ---------------------------------------------------------------------------
# Observation reading
# ---------------------------------------------------------------------------


def _vision(observations: dict) -> dict:
    vision = observations.get("vision")
    if not isinstance(vision, dict):
        return {"status": "not_observed"}
    return vision


def _fired_bulk_signals(text: dict, vision: dict) -> dict[str, list[str]]:
    """Decide which bulk signals fire, and record why each one did.

    Text and vision are unioned: a theme counts whether it was named in the
    listing or seen in the photos, because a bare-title lot ("Lego cars") states
    nothing and is exactly the case worth catching.
    """
    fired: dict[str, list[str]] = {}

    def fire(signal: str, evidence: str) -> None:
        fired.setdefault(signal, []).append(evidence)

    vision_themes = vision.get("themes")
    vision_themes = vision_themes if isinstance(vision_themes, list) else []
    for theme in ("star_wars", "castle", "technic", "duplo"):
        if theme in text["themes"]:
            fire(theme, "listing text")
        if theme in vision_themes:
            fire(theme, "listing images")

    if text["no_minifigures"]:
        fire("no_minifigures", "listing text")
    else:
        minifigs = vision.get("minifigs")
        if minifigs in ("few", "many"):
            fire("minifigs_present", f"images: {minifigs}")
        elif text["minifigs_mentioned"]:
            fire("minifigs_present", "listing text")

    if text["retired"]:
        fire("retired_sets", "listing text")
    if vision.get("retired_sets_visible") is True:
        fire("retired_sets", "listing images")

    colors = vision.get("target_colors")
    if colors in ("strong", "moderate", "weak"):
        fire(f"colors_{colors}", f"images: {colors} target colour coverage")

    for term in text["contamination"]:
        fire("contamination", f"listing text: {term}")
    vision_contamination = vision.get("contamination")
    if isinstance(vision_contamination, list):
        for term in vision_contamination:
            fire("contamination", f"listing images: {term}")

    if text["by_the_pound"]:
        fire("by_the_pound", "listing text")
    if text.get("piece_count_advertised"):
        fire("piece_count_advertised", "listing text")

    return fired


# ---------------------------------------------------------------------------
# Bulk
# ---------------------------------------------------------------------------


def _score_bulk(record: dict, observations: dict, price: float) -> dict:
    weight, weight_source = _resolve_weight(record, observations)
    if weight is None:
        return _unscorable(
            "no weight stated and none estimated from images -- $/lb is undefined"
        )
    if weight <= 0:
        return _unscorable(f"weight is {weight} lbs, which cannot be priced per pound")

    text = observations["text"]
    fired = _fired_bulk_signals(text, _vision(observations))

    quality = float(BULK_BASE_QUALITY)
    multiplier = 1.0
    breakdown: dict[str, dict] = {}
    for signal, evidence in fired.items():
        spec = BULK_SIGNALS[signal]
        quality += spec["quality"]
        multiplier *= spec["multiplier"]
        breakdown[signal] = {
            "quality_delta": spec["quality"],
            "price_multiplier": spec["multiplier"],
            "evidence": evidence,
        }

    quality = max(0.0, min(100.0, quality))
    multiplier = max(MIN_QUALITY_MULTIPLIER, min(MAX_QUALITY_MULTIPLIER, multiplier))
    max_price = BULK_WALKAWAY_PER_LB * weight * multiplier
    head = headroom(price, max_price, record.get("listing_key"))

    return {
        "quality": round(quality),
        "max_price": round(max_price, 2),
        "headroom": head,
        "price_scored": round(price, 2),
        "weight_lbs": weight,
        "weight_source": weight_source,
        "quality_multiplier": round(multiplier, 4),
        "signals": breakdown,
        "basis": (
            f"${BULK_WALKAWAY_PER_LB:.2f}/lb x {weight} lb x "
            f"{multiplier:.2f} quality multiplier"
        ),
    }


def _resolve_weight(record: dict, observations: dict) -> tuple[float | None, str]:
    """Stated weight wins; a photo-derived estimate is used but marked as one."""
    stated = record.get("weight_lbs")
    if isinstance(stated, (int, float)) and stated > 0:
        return float(stated), "stated"
    estimated = _vision(observations).get("weight_estimate_lbs")
    if isinstance(estimated, (int, float)) and estimated > 0:
        return float(estimated), "estimated"
    return None, "unknown"


# ---------------------------------------------------------------------------
# Sets
# ---------------------------------------------------------------------------


def _score_set(record: dict, observations: dict, price: float) -> dict:
    completeness = record.get("set_completeness")
    if completeness == "incomplete":
        return _unscorable(
            "set is incomplete -- BrickLink comps price a complete set, so no "
            "resale value applies"
        )

    resale, sales_count, sets_priced = _net_resale(record)
    if resale is None:
        return _unscorable(
            "no potential_profit against a landed cost, so there is no resale "
            "value to score"
        )

    max_price = resale - SET_MIN_PROFIT
    if max_price <= 0:
        return {
            "quality": 0,
            "max_price": round(max_price, 2),
            "headroom": 0.0,
            "price_scored": round(price, 2),
            "net_resale": round(resale, 2),
            "signals": {},
            "basis": (
                f"net resale ${resale:.2f} cannot clear the ${SET_MIN_PROFIT:.2f} "
                "minimum margin at any price"
            ),
        }

    # Headroom FIRST, because it is the one call that carries the listing_key
    # into its exception. A corrupt `estimated_total` poisons `resale` as well,
    # and `_interpolate` below would then raise an anonymous curve error before
    # this record ever got named.
    head = headroom(price, max_price, record.get("listing_key"))

    base = _interpolate(_SET_QUALITY_CURVE, resale)
    comp_multiplier = _comp_depth_multiplier(sales_count)
    completeness_multiplier = _completeness_multiplier(record)
    theme_multiplier, theme = _theme_multiplier(record, observations)

    quality = base * comp_multiplier * completeness_multiplier * theme_multiplier
    quality = max(0.0, min(100.0, quality))

    return {
        "quality": round(quality),
        "max_price": round(max_price, 2),
        "headroom": head,
        "price_scored": round(price, 2),
        "net_resale": round(resale, 2),
        "sets_priced": sets_priced,
        "signals": {
            "resale_base": {"net_resale": round(resale, 2), "quality": round(base, 1)},
            "comp_depth": {"sales_6mo": sales_count, "multiplier": comp_multiplier},
            "completeness": {
                "value": completeness,
                "condition": record.get("set_condition"),
                "multiplier": completeness_multiplier,
            },
            "theme_liquidity": {"theme": theme, "multiplier": theme_multiplier},
        },
        "basis": (
            f"net resale ${resale:.2f} less ${SET_MIN_PROFIT:.2f} minimum margin"
        ),
    }


# ---------------------------------------------------------------------------
# Minifigure lots
# ---------------------------------------------------------------------------


def _score_minifigure(record: dict, observations: dict, price: float) -> dict:
    """Score a completely valued, identifier-backed minifigure lot."""
    if record.get("profit_incomplete") is True:
        return _unscorable(
            "minifigure valuation is incomplete -- unknown, zero-sales, or "
            "failed identities make the known subtotal only a conservative floor")
    resale, sales_count, _sets_priced = _net_resale(record)
    if resale is None:
        return _unscorable(
            "no potential_profit against a landed cost, so there is no resale "
            "value to score"
        )


    max_price = resale - SET_MIN_PROFIT
    if max_price <= 0:
        return {
            "quality": 0,
            "max_price": round(max_price, 2),
            "headroom": 0.0,
            "price_scored": round(price, 2),
            "net_resale": round(resale, 2),
            "signals": {},
            "basis": (
                f"net resale ${resale:.2f} cannot clear the ${SET_MIN_PROFIT:.2f} "
                "minimum margin at any price"
            ),
        }

    head = headroom(price, max_price, record.get("listing_key"))
    base = _interpolate(_SET_QUALITY_CURVE, resale)
    comp_multiplier = _comp_depth_multiplier(sales_count)
    theme_multiplier, theme = _theme_multiplier(record, observations)

    quality = base * comp_multiplier * theme_multiplier
    quality = max(0.0, min(100.0, quality))

    return {
        "quality": round(quality),
        "max_price": round(max_price, 2),
        "headroom": head,
        "price_scored": round(price, 2),
        "net_resale": round(resale, 2),
        "figure_count": record.get("figure_count"),
        "signals": {
            "resale_base": {"net_resale": round(resale, 2), "quality": round(base, 1)},
            "comp_depth": {"sales_6mo": sales_count, "multiplier": comp_multiplier},
            "theme_liquidity": {"theme": theme, "multiplier": theme_multiplier},
        },
        "basis": (
            f"net resale ${resale:.2f} less ${SET_MIN_PROFIT:.2f} minimum margin"
        ),
    }


def _net_resale(record: dict) -> tuple[float | None, int | None, int]:
    """Resale value after selling fees, and the comp depth backing it.

    Resale is read from the two NORMALISED record fields: `potential_profit`,
    which legoscout-pricing computes as net-of-fees resale less purchase cost,
    plus the landed total it was computed against. One path, one definition.
    Never from `set_analysis` -- three of its historical keys
    (`net_after_fees`, `net_resale`, `net_resale_after_fees`) hold resale BEFORE
    cost, and reading one as profit overstates a lot by its whole purchase price.

    Comp depth is a different matter -- it is only ever an observation, so it
    comes from `set_analysis.sold_count()`, which reads one named field on each
    normalized entry.
    """
    profit = record.get("potential_profit")
    landed = record.get("estimated_total")
    if not isinstance(profit, (int, float)) or not isinstance(landed, (int, float)):
        return None, None, 0
    if record.get("listing_category") == "minifigure":
        sales_count = minifig_analysis.sold_count(
            minifig_analysis.entries(record))
    else:
        sales_count = set_analysis.sold_count(record)
    return float(profit) + float(landed), sales_count, 1


def _comp_depth_multiplier(sales_count: int | None) -> float:
    if sales_count is None:
        return _COMP_DEPTH_UNKNOWN
    for threshold, multiplier in _COMP_DEPTH_MULTIPLIERS:
        if sales_count >= threshold:
            return multiplier
    return _COMP_DEPTH_UNKNOWN


def _completeness_multiplier(record: dict) -> float:
    if record.get("set_condition") == "N":
        return _SEALED_MULTIPLIER
    completeness = record.get("set_completeness")
    if completeness in _COMPLETENESS_MULTIPLIERS:
        return _COMPLETENESS_MULTIPLIERS[completeness]
    return _COMPLETENESS_MULTIPLIERS["unknown"]


def _theme_multiplier(record: dict, observations: dict) -> tuple[float, str]:
    haystack = text_signals.listing_text(record).lower()
    # A set's CATALOG name carries the theme the listing title often omits
    # ("Millennium Falcon - UCS" reads Star Wars; "LEGO 75192" does not). Read
    # through set_analysis.names(), which knows every place a name was recorded.
    for name in set_analysis.names(record):
        haystack += "\n" + name.lower()
    for theme, words in _LIQUID_CATEGORY_WORDS:
        if any(word in haystack for word in words):
            return _THEME_LIQUIDITY[theme], theme
    vision_themes = _vision(observations).get("themes")
    if isinstance(vision_themes, list):
        for theme, _words in _LIQUID_CATEGORY_WORDS:
            if theme in vision_themes:
                return _THEME_LIQUIDITY[theme], theme
    return _THEME_LIQUIDITY_UNKNOWN, "unknown"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _unscorable(reason: str) -> dict:
    return {"quality": None, "max_price": None, "headroom": None, "unscorable": reason}


def _favorite_bonus_applies(category: str, record: dict) -> bool:
    """Bulk: unconditional. Set: only when potential_profit is a positive
    number, so a favorited seller's losing set is never boosted into looking
    attractive -- Adam's explicit call, since bulk has no profit figure to
    gate on at all."""
    if category == "bulk":
        return True
    profit = record.get("potential_profit")
    return isinstance(profit, (int, float)) and not isinstance(profit, bool) and profit > 0


def _landed_price(record: dict) -> float | None:
    """The landed total is the only price the walk-away numbers are denominated in.

    A bare item price with unknown freight is not a landed cost and is not
    substituted for one -- the row is reported unscorable instead.
    """
    total = record.get("estimated_total")
    if isinstance(total, (int, float)) and total >= 0:
        return float(total)
    return None


def build_observations(record: dict, vision: dict | None = None) -> dict:
    """Assemble the observation object: Python's text scan plus the model's vision.

    `vision` is whatever the model returned for this listing, or None when no
    image pass ran -- in which case every vision-derived signal stays silent
    rather than being guessed at.
    """
    observations = {
        "text": text_signals.scan(text_signals.listing_text(record)),
        "vision": vision if isinstance(vision, dict) else {"status": "not_observed"},
    }
    existing = record.get("observations")
    if isinstance(existing, dict):
        for key in ("description", "model_score", "model_rationale"):
            if key in existing and key not in observations:
                observations[key] = existing[key]
        if vision is None and isinstance(existing.get("vision"), dict):
            observations["vision"] = existing["vision"]
    return observations


def score_record(
    record: dict, vision: dict | None = None, is_favorite_seller: bool = False
) -> dict:
    """Score one ledger record. Returns the `scoring` object, never a bare number."""
    category = record.get("listing_category")
    if category not in ("bulk", "set", "minifigure", "excluded"):
        raise ValueError(
            f"listing_category must be 'bulk', 'set', 'minifigure', or "
            f"'excluded', got {category!r} "
            f"on {record.get('listing_key')!r}"
        )

    observations = build_observations(record, vision)
    price = _landed_price(record)

    if category == "excluded":
        reason = record.get("exclusion_reason")
        result = _unscorable(
            "excluded at classification: %s"
            % (reason if isinstance(reason, str) and reason.strip() else "no reason recorded"))
    elif price is None:
        result = _unscorable("no landed cost -- price or shipping is unknown")
    elif category == "bulk":
        result = _score_bulk(record, observations, price)
    elif category == "minifigure":
        result = _score_minifigure(record, observations, price)
    else:
        result = _score_set(record, observations, price)

    scoring: dict = {"version": SCORER_VERSION, "category": category, **result}

    if result.get("unscorable"):
        scoring["score"] = None
    else:
        # The bargain band can push quality x headroom past 100; a lot cannot be
        # better than the best.
        raw = min(100.0, result["quality"] * result["headroom"])
        score = int(round(raw))
        caps: list[str] = []
        if result.get("weight_source") == "estimated" and score > ESTIMATED_WEIGHT_SCORE_CAP:
            score = ESTIMATED_WEIGHT_SCORE_CAP
            caps.append(
                f"capped at {ESTIMATED_WEIGHT_SCORE_CAP}: weight was estimated from images"
            )
        if is_favorite_seller and _favorite_bonus_applies(category, record):
            score = min(100, score + FAVORITE_SELLER_BONUS)
            scoring["favorite_seller_bonus_applied"] = True
        scoring["score"] = score
        if caps:
            scoring["caps"] = caps

    model_score = observations.get("model_score")
    if isinstance(model_score, (int, float)):
        scoring["model_score"] = int(model_score)
        if scoring["score"] is not None:
            divergence = int(model_score) - scoring["score"]
            scoring["divergence"] = divergence
            scoring["divergence_flag"] = abs(divergence) > DIVERGENCE_THRESHOLD

    return {"scoring": scoring, "observations": observations}


def main() -> int:
    """The argparse surface, lifted out of the `__main__` guard so the CLI
    can reach it. A guarded block never runs on import, so the ported module
    had no entry point at all."""
    import json

    if len(sys.argv) < 2:
        raise SystemExit("usage: legoscout score deal <listing_key> [<listing_key> ...]")

    from ..ledger import db as ledger_db  # noqa: E402

    for key in sys.argv[1:]:
        deal = ledger_db.get_deal(key)
        if deal is None:
            raise SystemExit(f"no such listing_key: {key}")
        # allow_nan=False: Python's default emits the bare tokens `NaN` and
        # `Infinity`, which no JSON parser accepts. A caller-facing payload that
        # cannot be parsed is worse than a loud failure here.
        print(json.dumps(score_record(deal), indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
