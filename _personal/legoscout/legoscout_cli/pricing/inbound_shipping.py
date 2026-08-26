#!/usr/bin/env python3
"""Estimate inbound shipping to Evansville IN 47725 for lots whose seller ships
but does not quote a price at bid time.

Common on auction platforms: AuctionNinja, Proxibid, HiBid, AuctionZip and
K-BID sellers routinely say "we ship" and then invoice postage after the sale,
which leaves the real landed cost unknown exactly when the bid decision is
made. This quotes a live carrier rate for the origin/weight so the row gets a
defensible number instead of a null.

IMPORTANT -- this is a FLOOR, not a quote. The rate comes back at Adam's own
Shippo commercial pricing. A seller shipping to him pays their own rate (often
retail) and nearly always adds a handling/packing fee, so the estimate applies
a handling assumption on top and is still labelled an estimate. Never present
the output as the seller's actual charge.

    legoscout pricing shipping --origin-zip 57064 --weight-lbs 5
    legoscout pricing shipping --house "VanBeek Auction" --weight-lbs 5
    legoscout pricing shipping --hibid-lot 313898136 --weight-lbs 5

`--hibid-lot` reads the origin straight off the lot: HiBid's state blob already
carries the auction house's city/state/postal code, so no HiBid lot needs a
hand-curated entry in seller_origins.json to get an estimate.
"""
from .. import paths
import argparse
import json
import subprocess
import sys

ORIGINS = paths.SELLER_ORIGINS_JSON
CACHE = paths.SHIPPING_RATE_CACHE

DEST = paths.DEST

# Auction houses commonly add a packing/handling fee on top of postage.
# Observed this run: K-BID sellers $5-15, AuctionZip $25 admin on one house.
DEFAULT_HANDLING = 8.00


from . import json_cache  # noqa: E402  -- the one reader/writer of a JSON cache


def hibid_origin(lot):
    """Origin city/state/ZIP of the auction house holding a HiBid lot.

    Raises when the house publishes no postal code -- a guessed ZIP produces a
    confidently wrong landed cost, which is worse than an honest unknown.
    """
    from ..sources import hibid as hibid_lot_state
    st = hibid_lot_state.lot_state(lot)
    zip_ = (st.get("postal_code") or "").strip()
    if not zip_:
        raise ValueError("HiBid lot %s: house %r publishes no postal code"
                         % (st["lot_id"], st.get("house")))
    return zip_, st.get("city") or "", st.get("state") or "", st.get("house")


def box_for(weight_lbs):
    """Rough parcel dims by weight -- LEGO is dense, so boxes stay compact."""
    w = float(weight_lbs)
    if w <= 2:
        return 10, 8, 4
    if w <= 6:
        return 14, 10, 6
    if w <= 15:
        return 16, 12, 10
    if w <= 30:
        return 18, 14, 12
    return 20, 16, 14


def quote(origin_zip, origin_city, origin_state, weight_lbs, no_cache=False):
    key = "%s|%s" % (origin_zip, round(float(weight_lbs), 1))
    cache = json_cache.read(CACHE)
    if not no_cache and key in cache:
        out = dict(cache[key])
        out["cached"] = True
        return out

    L, W, H = box_for(weight_lbs)
    cmd = ["shippo", "shipments", "create",
           "--from-name", "Auction Seller", "--from-address", "100 Main St",
           "--from-city", origin_city or "Unknown", "--from-state", origin_state or "",
           "--from-zip", str(origin_zip),
           "--to-name", DEST["name"], "--to-address", DEST["address"],
           "--to-city", DEST["city"], "--to-state", DEST["state"],
           "--to-zip", DEST["zip"],
           "--weight", str(round(float(weight_lbs) * 16, 1)),
           "--length", str(L), "--width", str(W), "--height", str(H)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return {"error": "shippo failed rc=%d: %s" % (proc.returncode,
                                                      proc.stderr.strip()[:200])}
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return {"error": "shippo returned non-JSON: %s" % proc.stdout[:160]}

    rates = data.get("rates") or data.get("data", {}).get("rates") or []
    parsed = []
    for r in rates:
        try:
            amt = float(r.get("amount"))
        except (TypeError, ValueError):
            continue
        parsed.append({"amount": amt, "provider": r.get("provider"),
                       "service": (r.get("servicelevel") or {}).get("name"),
                       "days": r.get("estimated_days")})
    if not parsed:
        return {"error": "no rates returned for %s at %s lb"
                         % (origin_zip, weight_lbs)}
    parsed.sort(key=lambda x: x["amount"])
    # Cheapest ground-ish option; skip express tiers as unrealistic for a lot.
    ground = [p for p in parsed
              if "express" not in (p["service"] or "").lower()] or parsed
    best = ground[0]
    out = {
        "origin_zip": str(origin_zip),
        "weight_lbs": round(float(weight_lbs), 2),
        "parcel_in": [L, W, H],
        # A carrier bills the GREATER of actual and dimensional weight, so
        # every weight inside one box size that sits below the box's
        # dimensional weight quotes the same rate. 8, 11 and 14 lb in a
        # 16x12x10 all came back at $12.71 from a live Shippo call on
        # 2026-08-06, and 15 lb at $13.07. That looked like the tool ignoring
        # weight; these two fields are what make it legible.
        "parcel_cubic_inches": L * W * H,
        "rate_varies_with_weight_above_lbs": round((L * W * H) / 166.0, 1),
        "carrier_rate": round(best["amount"], 2),
        "carrier": best["provider"],
        "service": best["service"],
        "transit_days": best["days"],
        "handling_assumed": DEFAULT_HANDLING,
        "estimated_total": round(best["amount"] + DEFAULT_HANDLING, 2),
        "basis": "shippo_commercial_rate_plus_assumed_handling",
        "confidence": "estimate -- floor, not a seller quote",
        "all_rates": parsed[:5],
        "cached": False,
    }
    # Locked re-read-merge-write. `cache` above is stale by now -- the shippo
    # call took seconds, and a concurrent appraiser may have written its own
    # quote in that window. update() merges into whatever is on disk NOW, so
    # that entry survives instead of being overwritten by this whole-dict write.
    json_cache.update(CACHE, {key: {k: v for k, v in out.items() if k != "cached"}})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--origin-zip")
    ap.add_argument("--origin-city", default="")
    ap.add_argument("--origin-state", default="")
    ap.add_argument("--house", help="Known auction house from seller_origins.json")
    ap.add_argument("--hibid-lot", help="HiBid lot id or URL; reads the house's "
                                        "own city/state/ZIP off the lot page")
    ap.add_argument("--weight-lbs", type=float, required=True)
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()

    zip_, city, state = a.origin_zip, a.origin_city, a.origin_state
    if a.hibid_lot:
        try:
            zip_, city, state, house = hibid_origin(a.hibid_lot)
        except (ValueError, OSError) as exc:
            print("hibid origin: %s" % exc, file=sys.stderr)
            return 1
        print("origin: %s -- %s, %s %s" % (house, city, state, zip_),
              file=sys.stderr)
    if a.house:
        # seller_origins.json is curated data, not a cache. A missing or
        # unparseable file is a broken checkout, so it raises here rather than
        # reading as "no houses known" and reporting every house as unknown.
        with open(ORIGINS) as fh:
            origins = json.load(fh)["houses"]
        h = origins.get(a.house) or origins.get(a.house.lower())
        if not h:
            print("unknown house %r; known: %s"
                  % (a.house, ", ".join(sorted(origins))), file=sys.stderr)
            return 1
        zip_, city, state = h["zip"], h.get("city", ""), h.get("state", "")
    if not zip_:
        print("need --origin-zip or --house", file=sys.stderr)
        return 1

    out = quote(zip_, city, state, a.weight_lbs, a.no_cache)
    print(json.dumps(out, indent=2))
    if "error" not in out:
        # STDERR, so stdout stays one parseable JSON object. On stdout this
        # line followed the object and made `json.loads` raise Extra data.
        print("\n$%.2f %s %s + $%.2f assumed handling = $%.2f estimated inbound"
              % (out["carrier_rate"], out["carrier"], out["service"],
                 out["handling_assumed"], out["estimated_total"]),
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
