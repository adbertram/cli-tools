#!/usr/bin/env python3
"""Discover per-AUCTION-HOUSE fee/shipping facts for AuctionNinja lots.

AuctionNinja is a MARKETPLACE of independent auction houses, not a retailer, so
there is no such thing as an AuctionNinja fee rate. Every house sets its own
buyer's premium (12/18/19.5/20/22% observed) and, because lots are pickup-first,
charges sales tax at ITS OWN jurisdiction -- not Adam's, and not the platform's.

Treating any single observed pair as a platform default is therefore a bug, not
a shortcut: prior runs stamped 18% BP + a Renton-WA 10.5% tax onto every house,
which put a Washington tax rate on a New York lot (real rate 8.625%) and left
shipping null wherever the house used a third-party shipper. A wrong fee is
worse than a missing one, because it silently moves landed cost and flips a
bid/no-bid call.

So fees are discovered PER HOUSE and cached per house. A house with no
discovered rate reports null and is flagged -- never backfilled from another
house's numbers.

Both numbers are published, just not on the lot page. The lot page states only
the premium; the AUTHORIZE page behind the "Bid Now" button carries a clean,
authoritative Sale Details block with BOTH:

    Sale Details:  Buyer's Premium: 18%   Sales Tax: 8.625%

and its URL is fully derivable from the lot URL:

    lot   https://www.auctionninja.com/<store>/product/<slug>-<productId>.html
    auth  https://www.auctionninja.com/authorize-auction?store=<store>&product=<productId>

So this script reads the authorize page for premium + tax, and the lot page for
the pickup origin and shipping terms. (For the Ferrari lot the authorize page
returns 8.625% -- the Nassau County NY rate -- against a stored platform default
of 10.5%, which was a Renton WA rate carried over from an unrelated seller.)

Shipping is never quoted at bid time on this platform, so with a weight the
discovered origin feeds estimate_inbound_shipping.py to replace a null Ship cell
with a defensible estimate.

    legoscout --url <lot-url> --weight-lbs 6
    legoscout --url <lot-url> --register

--register writes the discovered seller into seller_origins.json so later runs
reuse the origin without re-fetching. Only verified page text is ever written.
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys

from . import inbound_shipping

_HERE = os.path.dirname(os.path.abspath(__file__))
ORIGINS = os.path.join(_HERE, "seller_origins.json")

STATE_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}

PREMIUM_RE = re.compile(r"Buyer'?s\s+Premium\s*:?\s*(\d{1,2}(?:\.\d+)?)\s*%", re.I)
# Authorize page: "Sale Details: Buyer's Premium: 18% Sales Tax: 8.625%"
SALES_TAX_RE = re.compile(r"Sales\s+Tax\s*:?\s*(\d{1,2}(?:\.\d+)?)\s*%", re.I)
LOT_URL_RE = re.compile(
    r"auctionninja\.com/([^/]+)/product/.*?-(\d+)\.html", re.I)
# "East Meadow, NY 11554" or "East Meadow, New York 11554"
CITY_STATE_ZIP_RE = re.compile(
    r"([A-Z][A-Za-z.'\-]*(?:\s+[A-Z][A-Za-z.'\-]*){0,3}),\s*"
    r"([A-Z]{2}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(\d{5})(?:-\d{4})?\b")
NO_SHIP_RE = re.compile(
    r"\bNO\s+SHIPPING\b|\bpick[\s-]?up\s+only\b|\bno\s+shipping\s+available\b", re.I)
SHIP_OK_RE = re.compile(
    r"\bShipping\s+Available\b|\bwe\s+ship\b|\b3rd\s+PARTY\s+SHIPPING\b|"
    r"\bThird\s+Party\s+Shipping\b", re.I)
THIRD_PARTY_RE = re.compile(
    r"(?:company\s+for\s+shipping\s+is|shipper\s+is)\s*:?\s*([^\d]{3,60}?)\s*(?:\d{3}-|\bCall\b|\bEmail\b)", re.I)
SELLER_RE = re.compile(r"Seller\s+Info\s+(.{3,60}?)\s+\d{1,4}\s+View\s+Seller", re.I)
WEIGHT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:lbs?|pounds?)\b", re.I)


def load(path):
    """The curated seller-origins file, or a raise.

    `seller_origins.json` is curated data, not a cache. A corrupt file used to
    be swallowed and replaced with an empty default, which silently discarded
    every recorded house origin and made every landed cost a floor. It raises
    now. `register()` is the one caller allowed to treat a MISSING file as a
    legitimate first-run state; corruption never is.
    """
    with open(path) as fh:
        return json.load(fh)


def fetch(url):
    """curl, not WebFetch -- WebFetch strips the JSON-LD and collapses the
    seller-instructions block where premium and pickup address live."""
    proc = subprocess.run(
        ["curl", "-sL", "--max-time", "60", "-A",
         "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36", url],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit("curl failed rc=%d: %s" % (proc.returncode, proc.stderr[:200]))
    if not proc.stdout.strip():
        raise SystemExit("empty response from %s" % url)
    return proc.stdout


def visible_text(raw):
    txt = re.sub(r"<script[^>]*>.*?</script>", " ", raw, flags=re.S | re.I)
    txt = re.sub(r"<style[^>]*>.*?</style>", " ", txt, flags=re.S | re.I)
    txt = html.unescape(re.sub(r"<[^>]+>", " ", txt))
    return re.sub(r"\s+", " ", txt).strip()


def seller_from_url(url):
    m = re.search(r"auctionninja\.com/([^/]+)/product/", url)
    if not m:
        return None
    return m.group(1).replace("-", " ").title()


def pick_origin(text):
    """Prefer the address in the pickup block; fall back to the first plausible
    City, ST ZIP. AuctionNinja footers list unrelated 'Top Auction Locations',
    so anchor on pickup wording rather than taking the first match on the page."""
    anchors = [
        r"WHERE\s+TO\s+PICK\s+UP\s*:?(.{0,200})",
        r"Shipping\s+Available(.{0,120})",
        r"ALTERNATE\s+PICK\s+UP\s*&?\s*SHIPPING\s*:?(.{0,160})",
        r"Pickup\s+Details(.{0,160})",
    ]
    for pat in anchors:
        for am in re.finditer(pat, text, re.I | re.S):
            m = CITY_STATE_ZIP_RE.search(am.group(1))
            if m:
                return m
    return CITY_STATE_ZIP_RE.search(text)


# Sellers prefix the pickup address with venue wording ("Private Residence
# East Meadow, NY"), which is not part of the city name.
VENUE_PREFIX_RE = re.compile(
    r"^(?:private\s+residence|residence|storage\s+unit|warehouse|"
    r"ready\s+spaces|the\s+home|home|office|gallery|shop|store)\s+", re.I)


def clean_city(raw):
    return VENUE_PREFIX_RE.sub("", (raw or "").strip()).strip() or None


def normalize_state(raw):
    raw = (raw or "").strip()
    if len(raw) == 2 and raw.isupper():
        return raw
    return STATE_ABBR.get(raw.lower(), raw[:2].upper() if raw else "")


def authorize_url(lot_url):
    """The Bid Now target, derived from the lot URL's store slug + product id."""
    m = LOT_URL_RE.search(lot_url)
    if not m:
        return None
    return ("https://www.auctionninja.com/authorize-auction?store=%s&product=%s"
            % (m.group(1), m.group(2)))


def discover(url):
    text = visible_text(fetch(url))
    out = {"url": url, "source": "auctionninja"}

    pm = PREMIUM_RE.search(text)
    out["premium_pct"] = round(float(pm.group(1)) / 100.0, 4) if pm else None
    out["premium_source"] = "lot page" if pm else "not stated on page"

    # The authorize page is the authoritative fee surface: it states premium AND
    # sales tax for this specific sale, so it overrides both the lot-page premium
    # and any platform default.
    out["authorize_url"] = auth = authorize_url(url)
    out["sales_tax_pct"] = None
    out["sales_tax_is_default"] = True
    out["sales_tax_basis"] = "not read"
    if auth:
        try:
            atext = visible_text(fetch(auth))
        except SystemExit as exc:
            out["authorize_error"] = str(exc)
            atext = ""
        if atext:
            sd = re.search(r"Sale\s+Details\s*:?(.{0,400})", atext, re.I | re.S)
            scope = sd.group(1) if sd else atext
            apm = PREMIUM_RE.search(scope)
            if apm:
                out["premium_pct"] = round(float(apm.group(1)) / 100.0, 4)
                out["premium_source"] = "authorize page Sale Details"
            atm = SALES_TAX_RE.search(scope)
            if atm:
                out["sales_tax_pct"] = round(float(atm.group(1)) / 100.0, 5)
                out["sales_tax_is_default"] = False
                out["sales_tax_basis"] = "authorize page Sale Details (per-sale, authoritative)"

    sm = SELLER_RE.search(text)
    out["seller"] = (sm.group(1).strip() if sm else None) or seller_from_url(url)

    om = pick_origin(text)
    if om:
        out["origin_city"] = clean_city(om.group(1))
        out["origin_state"] = normalize_state(om.group(2))
        out["origin_zip"] = om.group(3)
    else:
        out["origin_city"] = out["origin_state"] = out["origin_zip"] = None

    no_ship = bool(NO_SHIP_RE.search(text))
    out["ships"] = (not no_ship) and bool(SHIP_OK_RE.search(text))
    out["pickup_only"] = no_ship
    tp = THIRD_PARTY_RE.search(text)
    out["third_party_shipper"] = tp.group(1).strip() if tp else None
    out["shipping_quoted_on_page"] = False

    wm = WEIGHT_RE.search(text)
    out["weight_stated_lbs"] = float(wm.group(1)) if wm else None

    # No cross-house fallback. Each house sets its own rates, so borrowing another
    # house's number would be a fabricated fee, not a default. Report the gap.
    if out["sales_tax_pct"] is None:
        out["sales_tax_basis"] = (
            "UNKNOWN -- authorize page unreadable for this house; no cross-house "
            "fallback applied because AuctionNinja rates are per-house")
    if out["premium_pct"] is None:
        out["premium_source"] = (
            "UNKNOWN -- not stated on lot or authorize page for this house")
    out["fees_complete"] = (out["premium_pct"] is not None
                            and out["sales_tax_pct"] is not None)
    return out


def store_slug(url):
    m = LOT_URL_RE.search(url or "")
    return m.group(1).lower() if m else None


def lookup_house(slug, name):
    """Return a cached per-house record by store slug, falling back to name.
    Keyed entries stay under the display name so estimate_inbound_shipping.py's
    existing --house contract keeps working."""
    houses = load(ORIGINS).get("houses", {})
    if slug:
        for hname, h in houses.items():
            if h.get("store_slug") == slug:
                return hname, h
    if name and name in houses:
        return name, houses[name]
    return None, None


def register(found):
    """Persist the whole per-house record: origin AND its own fee rates."""
    if not found.get("seller"):
        return {"registered": False, "reason": "no seller discovered"}
    if not found.get("origin_zip") and not found.get("fees_complete"):
        return {"registered": False, "reason": "nothing verified to record"}
    # A missing file is a legitimate first run HERE and nowhere else.
    data = load(ORIGINS) if os.path.exists(ORIGINS) else {"houses": {}}
    houses = data.setdefault("houses", {})
    name = found["seller"]
    entry = dict(houses.get(name) or {})
    entry.update({
        "city": found.get("origin_city") or entry.get("city"),
        "state": found.get("origin_state") or entry.get("state"),
        "zip": found.get("origin_zip") or entry.get("zip"),
        "platform": "auctionninja",
        "store_slug": store_slug(found["url"]) or entry.get("store_slug"),
        # Per-house fees -- never reused across houses.
        "premium_pct": found.get("premium_pct"),
        "sales_tax_pct": found.get("sales_tax_pct"),
        "sales_tax_is_default": found.get("sales_tax_is_default"),
        "ships": found.get("ships"),
        "pickup_only": found.get("pickup_only"),
        "third_party_shipper": found.get("third_party_shipper"),
        "evidence": "Discovered %s -- premium %s, sales tax %s (%s); pickup %s; %s." % (
            found["url"],
            ("%.3g%%" % (found["premium_pct"] * 100)) if found.get("premium_pct") else "unknown",
            ("%.4g%%" % (found["sales_tax_pct"] * 100)) if found.get("sales_tax_pct") else "unknown",
            found.get("sales_tax_basis", "unknown"),
            "%s, %s %s" % (found.get("origin_city"), found.get("origin_state"),
                           found.get("origin_zip")),
            ("ships (3rd party: %s)" % found["third_party_shipper"])
            if found.get("third_party_shipper") else
            ("ships" if found.get("ships") else "pickup only")),
        "verified_at": "2026-07-26",
    })
    houses[name] = entry
    with open(ORIGINS, "w") as fh:
        json.dump(data, fh, indent=2)
    return {"registered": True, "house": name, "store_slug": entry.get("store_slug")}


def estimate(found, weight_lbs):
    if found.get("pickup_only"):
        return {"skipped": "pickup only -- no inbound shipping to estimate"}
    if not found.get("origin_zip"):
        return {"skipped": "no origin zip discovered"}
    return inbound_shipping.quote(
        found["origin_zip"],
        found.get("origin_city") or "",
        found.get("origin_state") or "",
        weight_lbs)


def run_one(url, weight_lbs=None, do_register=False):
    found = discover(url)
    result = {"discovered": found}
    if do_register:
        result["registration"] = register(found)
    weight = weight_lbs or found.get("weight_stated_lbs")
    if weight:
        result["shipping_estimate"] = estimate(found, weight)
        result["shipping_estimate_weight_lbs"] = weight
        result["shipping_estimate_weight_source"] = (
            "--weight-lbs" if weight_lbs else "stated on lot page")
    else:
        result["shipping_estimate"] = {"skipped": "no weight available"}
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="AuctionNinja lot URL")
    ap.add_argument("--batch", metavar="FILE",
                    help="File of lot URLs (one per line, optional ',weight' "
                         "suffix). One house is fetched once per distinct store.")
    ap.add_argument("--weight-lbs", type=float,
                    help="Weight for the inbound shipping estimate; "
                         "defaults to a weight stated on the page if present")
    ap.add_argument("--register", action="store_true",
                    help="Write the discovered per-house fees/origin to seller_origins.json")
    a = ap.parse_args()

    if not a.url and not a.batch:
        ap.error("need --url or --batch")

    if a.url:
        print(json.dumps(run_one(a.url, a.weight_lbs, a.register), indent=2))
        return 0

    with open(a.batch) as fh:
        lines = [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    results, seen_slugs = [], {}
    for ln in lines:
        parts = ln.split(",")
        url = parts[0].strip()
        w = float(parts[1]) if len(parts) > 1 and parts[1].strip() else a.weight_lbs
        slug = store_slug(url)
        # Fees are per house, so re-fetching another lot from the same house
        # cannot change them -- fetch each house once, then reuse.
        if slug and slug in seen_slugs:
            base = seen_slugs[slug]
            res = {"url": url, "reused_house": slug,
                   "discovered": dict(base["discovered"], url=url)}
            if w:
                res["shipping_estimate"] = estimate(base["discovered"], w)
                res["shipping_estimate_weight_lbs"] = w
        else:
            res = run_one(url, w, a.register)
            if slug:
                seen_slugs[slug] = res
        res["url"] = url
        results.append(res)

    houses = {}
    for r in results:
        d = r["discovered"]
        houses.setdefault(d.get("seller") or "unknown", {
            "store_slug": store_slug(d.get("url") or ""),
            "premium_pct": d.get("premium_pct"),
            "sales_tax_pct": d.get("sales_tax_pct"),
            "origin": "%s, %s %s" % (d.get("origin_city"), d.get("origin_state"),
                                     d.get("origin_zip")),
            "ships": d.get("ships"),
            "fees_complete": d.get("fees_complete"),
        })
    print(json.dumps({"lots": results, "houses": houses,
                      "house_count": len(houses), "lot_count": len(results)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
