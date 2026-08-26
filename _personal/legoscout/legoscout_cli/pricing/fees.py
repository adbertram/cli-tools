#!/usr/bin/env python3
"""Landed-cost math for LEGO Scout, driven by legoscout-sources' registry.

Landed = hammer + premium + tax + shipping/handling

where premium and tax are per-source (and, on auction platforms, per-auction-
house). Before 2026-07-25 the pipeline folded a buyer's premium into
`estimated_total` only when a worker happened to remember, applied no sales tax
anywhere, and left AuctionNinja rows with a null landed cost entirely -- so
those set profits were computed against roughly zero cost.

The premium is PER-AUCTION-HOUSE on every auction platform. A rate read off the
lot page always wins; `premium_pct_default` is a last-resort fallback and any
row using it is flagged so it can be shown as an estimate rather than a fact.

CLI:
    legoscout pricing landed-cost --source proxibid --hammer 30 --shipping 12
    legoscout pricing landed-cost --source auctionninja --hammer 25 --premium-pct 0.18
"""
import argparse
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
from ..sources import registry  # noqa: E402

# Every rate here is a FRACTION: 0.18 is an 18% buyer's premium. The highest
# rate in the registry is LiveAuctioneers at 0.25, and the highest US combined
# sales tax is under 0.12, so a rate above 1.00 is never a real rate -- it is a
# percentage passed as a whole number (`--premium-pct 18` = 1800%), or garbage.
MAX_RATE = 1.0


def _finite(name, value):
    """A number that is a quantity. `nan` and `inf` are neither.

    They are also not JSON: `json.dumps` writes the bare tokens `NaN` and
    `Infinity`, so a single one of them turned this command's stdout -- which is
    contracted to be one parseable JSON object -- into text no parser reads.
    """
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(
            "%s is %r, which is not an amount. `nan` and `inf` are not "
            "quantities, every total computed from one is `nan`, and neither "
            "survives JSON." % (name, value))
    return number


def _money(name, value):
    """A dollar amount. Negative money is not a cost, it is a sign error."""
    number = _finite(name, value)
    if number < 0:
        raise ValueError(
            "%s is %s. A landed cost is built from what Adam PAYS, so a "
            "negative %s just subtracts from the total and reports a bargain "
            "that does not exist." % (name, number, name))
    return number


def _rate(name, value):
    """A percentage, expressed as a fraction of 1."""
    number = _finite(name, value)
    if not 0.0 <= number <= MAX_RATE:
        raise ValueError(
            "%s is %s. Rates are FRACTIONS of 1: 0.18 is 18%%. Anything "
            "outside 0..%s is a percentage passed as a whole number or a sign "
            "error -- a negative tax rate reads as a refund and pays for the "
            "lot." % (name, number, MAX_RATE))
    return number


def source_key(listing_key_or_source):
    """The registry key for a listing_key, namespace, display name, or alias.

    This used to be `lower()` plus dropping spaces and dots, which turns
    "EstateSales.NET" into `estatesalesnet` -- not a key in the table -- so
    every caller that passed that display name silently got the zero-fee
    defaults. registry.py resolves display names through an index built from
    the data instead, and raises on a stranger.
    """
    return registry.sources.key(listing_key_or_source)


def config(source):
    return registry.fee_config(source)


def landed_cost(source, hammer, shipping, handling=0.0,
                premium_pct=None, sales_tax_pct=None, premium_fixed=None,
                buyer_protection_fee=None):
    """Return a dict with the full cost breakdown.

    `shipping` is REQUIRED and has no default. It used to default to 0.0, which
    meant any caller that simply forgot it got a landed cost that silently
    priced inbound freight at nothing -- the 2026-07-26 sweep wrote
    `shipping_handling: 0.0` on all 52 live HiBid lots, every one of which ships
    at the buyer's expense through a third party. Pass a number when the cost is
    known or estimated, or pass None to DECLARE it unknown: the breakdown then
    carries `shipping_handling: None`, `shipping_unknown: True` and
    `landed_is_floor: True`, so downstream can show "unknown" instead of "free".

    `premium_pct` / `sales_tax_pct` are the LOT-STATED rates when known; pass
    None to fall back to the source default (which sets `*_is_default` so the
    caller can mark the figure as an estimate).

    `premium_fixed` covers buyer fees with a flat component alongside the
    percentage -- Depop's buyer Marketplace fee is 5% + $1, so a percent-only
    model understates every row and understates cheap rows the most (on a $6
    item the flat $1 is bigger than the 5%).
    """
    if hammer is None:
        return None
    # Every input is checked BEFORE any arithmetic. A `nan` hammer used to reach
    # `round(hammer * prem + fixed, 2)` and turn every derived figure into a
    # `NaN` token on stdout, at exit 0; a negative one produced a negative
    # landed cost that read as free money.
    hammer = _money("hammer", hammer)
    cfg = config(source)

    prem_default = premium_pct is None
    prem = cfg.get("premium_pct_default", 0.0) if prem_default else premium_pct
    prem = _rate("premium_pct", prem or 0.0)

    tax_default = sales_tax_pct is None
    if tax_default:
        rule = cfg.get("sales_tax_rule", "none")
        if rule == "none":
            tax = 0.0
        elif rule == "buyer_state":
            tax = float(registry.fee_buyer()["state_sales_tax_pct"])
        else:  # seller_location -- default is an observed sample, not a constant
            sample = cfg["sales_tax_pct_default"]
            # AuctionNinja records this as null: the rate is per-seller and no
            # sample was ever taken. `cfg.get(key, 0.0)` returned that null --
            # the key EXISTS -- and float(None) raised TypeError with no clue
            # what to do. Say what is needed instead.
            if sample is None:
                raise ValueError(
                    "%s taxes by seller location and has no sampled rate. Read "
                    "the rate off the lot's own authorize/checkout page and "
                    "pass --sales-tax-pct, or record a sample in the registry."
                    % cfg["_key"])
            tax = sample
        tax = _rate("sales_tax_pct", tax)
    else:
        tax = _rate("sales_tax_pct", sales_tax_pct or 0.0)

    fixed_default = premium_fixed is None
    fixed = cfg.get("premium_fixed", 0.0) if fixed_default else premium_fixed
    fixed = _money("premium_fixed", fixed or 0.0)

    if cfg.get("buyer_fee_already_in_total") and buyer_protection_fee is None:
        raise ValueError(
            "%s requires its numeric Buyer Protection fee. Read it from "
            "priceSummary.totalPrice minus the item price and shipping, then "
            "pass --buyer-protection-fee. It cannot be derived from the "
            "observed percentage range." % cfg["_key"])
    protection_fee = _money(
        "buyer_protection_fee",
        0.0 if buyer_protection_fee is None else buyer_protection_fee)

    # An unknown shipping cost is not a zero one. Everything downstream of here
    # is then a floor: the true landed total is this plus whatever the seller
    # invoices for freight.
    ship_unknown = shipping is None
    ship = ((0.0 if ship_unknown else _money("shipping", shipping))
            + _money("handling", handling or 0.0))
    premium_amt = round(hammer * prem + fixed, 2)

    basis = cfg.get("tax_basis", "hammer_plus_premium")
    if basis == "hammer_plus_premium":
        taxable = hammer + premium_amt
    elif basis == "hammer_plus_shipping":
        # Marketplace-facilitator sales tax applies to the item and delivery
        # charge, not to the platform's own buyer-protection fee.
        taxable = hammer + ship
    else:
        taxable = hammer
    tax_amt = round(taxable * tax, 2)

    total = round(hammer + premium_amt + protection_fee + tax_amt + ship, 2)
    return {
        "source": cfg["_key"],
        "hammer": round(hammer, 2),
        "premium_pct": prem,
        "premium_fixed": fixed,
        "premium_amount": premium_amt,
        "premium_is_default": (prem_default and prem > 0) or (fixed_default and fixed > 0),
        "buyer_protection_fee": round(protection_fee, 2),
        "sales_tax_pct": tax,
        "sales_tax_amount": tax_amt,
        "sales_tax_rule": cfg.get("sales_tax_rule", "none"),
        "sales_tax_is_default": tax_default and tax > 0,
        "tax_basis": basis,
        "shipping_handling": None if ship_unknown else round(ship, 2),
        "shipping_unknown": ship_unknown,
        "landed_is_floor": ship_unknown,
        "landed_total": total,
        "fee_multiple": round(total / hammer, 4) if hammer else None,
        "confidence_note": cfg.get("confidence", "unknown"),
    }


def explain(b):
    if not b:
        return "no hammer price -- landed cost not computable"
    bits = ["$%.2f hammer" % b["hammer"]]
    if b["premium_amount"]:
        rate = "%.1f%%" % (b["premium_pct"] * 100)
        if b.get("premium_fixed"):
            rate += " + $%.2f" % b["premium_fixed"]
        bits.append("+$%.2f premium (%s%s)" % (
            b["premium_amount"], rate,
            ", source default" if b["premium_is_default"] else ""))
    if b.get("buyer_protection_fee"):
        bits.append("+$%.2f buyer protection" % b["buyer_protection_fee"])
    if b["sales_tax_amount"]:
        bits.append("+$%.2f tax (%.2f%% %s%s)" % (
            b["sales_tax_amount"], b["sales_tax_pct"] * 100,
            b["sales_tax_rule"],
            ", default" if b["sales_tax_is_default"] else ""))
    if b["shipping_handling"]:
        bits.append("+$%.2f shipping/handling" % b["shipping_handling"])
    if b.get("shipping_unknown"):
        bits.append("+ UNKNOWN shipping")
        return " ".join(bits) + " = $%.2f landed FLOOR" % b["landed_total"]
    return " ".join(bits) + " = $%.2f landed" % b["landed_total"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--hammer", type=float, required=True)
    # No default: a forgotten --shipping used to become $0.00 freight. State the
    # number or state that it is unknown -- there is no third option.
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--shipping", type=float)
    g.add_argument("--shipping-unknown", action="store_true",
                   help="inbound freight is not quotable for this lot")
    ap.add_argument("--handling", type=float, default=0.0)
    ap.add_argument("--premium-pct", type=float, default=None)
    ap.add_argument("--sales-tax-pct", type=float, default=None)
    ap.add_argument("--buyer-protection-fee", type=float, default=None)
    a = ap.parse_args()
    b = landed_cost(a.source, a.hammer,
                    None if a.shipping_unknown else a.shipping, a.handling,
                    a.premium_pct, a.sales_tax_pct,
                    buyer_protection_fee=a.buyer_protection_fee)
    # allow_nan=False: stdout is contracted to be ONE parseable JSON object, and
    # Python's default writes `NaN` / `Infinity`, which no other parser reads.
    # The input validation above is what keeps this from ever firing; this is
    # the assertion that it did.
    print(json.dumps(b, indent=2, allow_nan=False))
    # The one-line explanation goes to STDERR. On stdout it followed the JSON
    # object, so `legoscout pricing landed-cost ... | json.loads` raised
    # `Extra data: line 20 column 1`, and every caller that parsed this command
    # had to strip the last line by hand.
    print(explain(b), file=sys.stderr)


if __name__ == "__main__":
    main()
