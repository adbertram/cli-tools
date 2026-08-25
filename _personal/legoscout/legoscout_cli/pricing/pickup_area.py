#!/usr/bin/env python3
"""Decide whether a listing's stated location is close enough for Adam to
collect it himself.

A local-pickup-only lot is only actionable inside the drive radius; everywhere
else the seller has to ship or the deal is dead. Source workers call this
instead of eyeballing a town name.

    legoscout pricing pickup-area "Newburgh, IN"
    legoscout pricing pickup-area 47630
    legoscout pricing pickup-area "St. Louis, MO"

Exits 0 with a JSON verdict. An unresolvable location is an ERROR, not a
"no" -- a listing whose location cannot be pinned down must be sent back for a
real location rather than silently treated as out of range.
"""
from .. import paths
import argparse
import json
import re
import sys

AREA = paths.PICKUP_AREA_JSON
_ZIP = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
# "Newburgh, IN" / "Newburgh IN" / "Newburgh, Indiana"
_CITY_STATE = re.compile(r"^\s*(.+?)[,\s]+([A-Za-z]{2})\s*$")

STATES = {
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
    "district of columbia": "DC", "puerto rico": "PR",
}

# The one USPS list, imported rather than copied: `sources.listing` already
# holds it, and two copies of a state list is how "US" became a state.
from ..sources.listing import USPS_STATES  # noqa: E402

# A trailing country segment on a US address. eBay writes "United States" on
# every listing; the shorter spellings show up in hand-entered locations.
_COUNTRY = {"united states", "united states of america", "usa", "u.s.a.",
            "us", "u.s."}


def _strip_country(text):
    """`text` with a trailing US country segment removed, comma or not."""
    parts = [p.strip() for p in text.split(",")]
    while len(parts) > 1 and parts[-1].lower().rstrip(".") in {
            c.rstrip(".") for c in _COUNTRY}:
        parts.pop()
    return ", ".join(parts)


def area(path=AREA):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def normalize_city(city):
    # "St. Louis" and "Saint Louis" are the same place to a human and different
    # strings to a dict lookup. build_pickup_area.py keys the town index with
    # this same function, so both sides of the lookup agree.
    c = city.strip().lower().rstrip(".,")
    c = re.sub(r"^st\.?\s+", "saint ", c)
    return re.sub(r"\s+", " ", c)


def resolve(location, area_path=AREA):
    """Return a verdict dict. Raises ValueError if the location is unusable.

    Pass `area_path` to resolve against a different radius table (the
    prospector's 60-mile prospect_area.json); the default is the 30-mile deal
    gate.
    """
    if location is None or not str(location).strip():
        raise ValueError("no location given -- a pickup decision needs one")
    text = str(location).strip()
    a = area(area_path)

    # The LAST five-digit group, not the first: a US postal address ends with
    # its ZIP, and full addresses are exactly what the pickup backfills capture.
    # "10195 Main St, Ada, MI 49301" read left-to-right resolves as ZIP 10195,
    # a Brooklyn PO box 700 miles from the actual pickup counter.
    codes = _ZIP.findall(text)
    if codes:
        code = codes[-1]
        miles = a["zips"].get(code)
        return {"location": text, "basis": "zip", "matched": code,
                "eligible": miles is not None, "miles": miles,
                "radius_miles": a["radius_miles"]}

    # A US listing that names its country is still a US listing. eBay writes
    # every location as "City, State, United States", which reached neither
    # branch below and raised "has no state or ZIP" on a fully qualified
    # address. Dropping the country segment first is what makes it resolvable.
    asked, text = text, _strip_country(text)

    m = _CITY_STATE.match(text)
    state = None
    # The 2-letter regex must agree with USPS. "Wilkes-Barre Twp, PA, US" once
    # matched with state "US" and city "Wilkes-Barre Twp, PA", which no town
    # index holds -- so an in-radius pickup came back `eligible: false` with no
    # error at all. A 2-letter run that is not a state is not a state.
    if m and m.group(2).upper() in USPS_STATES:
        city, state = m.group(1), m.group(2).upper()
    else:
        parts = [p.strip() for p in text.split(",")]
        city = parts[0]
        if len(parts) > 1 and parts[-1].strip().lower() in STATES:
            state = STATES[parts[-1].strip().lower()]
    if not state:
        raise ValueError(
            "%r has no state or ZIP -- a bare town name is ambiguous "
            "(Chandler, IN is 15 miles away; Chandler, AZ is 1,500). "
            "Capture the listing's full stated location." % text)

    key = "%s, %s" % (normalize_city(city), state)
    miles = a["towns"].get(key)
    return {"location": asked, "basis": "town", "matched": key,
            "eligible": miles is not None, "miles": miles,
            "radius_miles": a["radius_miles"]}


def is_pickup_eligible(location):
    return resolve(location)["eligible"]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("location", help='"City, ST" or a 5-digit ZIP')
    a = ap.parse_args()
    try:
        print(json.dumps(resolve(a.location), indent=1))
    except ValueError as exc:
        sys.exit("pickup_area: %s" % exc)


if __name__ == "__main__":
    main()
