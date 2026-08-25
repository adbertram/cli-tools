#!/usr/bin/env python3
"""Regenerate pickup_area.json -- the ZIPs and towns Adam can drive to.

Adam can only collect a local-pickup-only lot himself; everything else has to
ship. This resolves "can he pick it up?" to a fixed geography instead of a
judgement call per listing, so a source worker never has to guess whether a
town is close enough.

A ZIP carries ONE primary city label, and that label is not the only name a
seller uses. ZIP 47725 is labelled "Evansville", but the town at that ZIP is
Darmstadt, IN. A town index built from primary labels alone reports Darmstadt
as out of range and hard-rejects a pickup 0 miles away. So the town index draws
on four sources, and a town keeps the SHORTEST distance any source gives it:

  1. ZIP centroids -- the ZIP table, plus each ZIP's primary city label.
  2. Census ZCTA-to-place -- every incorporated place and CDP that overlaps an
     in-radius ZIP. This is what puts Darmstadt at ZIP 47725's own distance.
  3. Census place gazetteer -- the name and state behind each place ID in (2).
  4. GeoNames populated places -- unincorporated communities and localities
     that no ZIP labels and no census place covers, at their own coordinates.

Every source is required. A source that fails to load stops the run; there is
no partial table, because a partial table reads exactly like a complete one at
the pickup gate.

Run only when the radius or the origin changes:

    legoscout pricing rebuild-pickup-area --radius-miles 30
    legoscout pricing rebuild-pickup-area --radius-miles 60 --out /path/to/prospect_area.json

The output is committed alongside this script so the runtime path
(pickup_area.py) never touches the network.
"""
from .. import paths
import argparse
import contextlib
import csv
import io
import json
import math
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile

from . import pickup_area  # noqa: E402  -- one normalizer, shared with the resolver

OUT = paths.PICKUP_AREA_JSON

ZIP_CSV_URL = ("https://raw.githubusercontent.com/midwire/free_zipcode_data/"
               "master/all_us_zipcodes.csv")
ZCTA_PLACE_URL = ("https://www2.census.gov/geo/docs/maps-data/data/rel2020/"
                  "zcta520/tab20_zcta520_place20_natl.txt")
PLACE_GAZ_URL = ("https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
                 "2023_Gazetteer/2023_Gaz_place_national.zip")
GEONAMES_URL = "https://download.geonames.org/export/dump/US.zip"

ORIGIN_ZIP = paths.DEST_ZIP   # Adam's ship-to / home ZIP, per legoscout-pricing
EARTH_MILES = 3958.7613

# A census place name carries its legal or statistical suffix -- "Darmstadt
# town". The LSAD column names that suffix, so the strip is exact instead of a
# guess that would turn "Oakland City city" into "Oakland". Every code below is
# one the gazetteer file actually uses.
LSAD_SUFFIX = {
    "00": "",
    "21": " borough",
    "25": " city",
    "35": " metro township",
    "37": " municipality",
    "43": " town",
    "47": " village",
    "53": " city and borough",
    "55": " comunidad",
    "57": " CDP",
    "62": " zona urbana",
    "CG": " consolidated government",
    "CN": " corporation",
    "MG": " metropolitan government",
    "UC": " urban county",
    "UG": " unified government",
}

# GeoNames marks places that no longer exist. A seller cannot stand in one.
DEAD_PLACE_CODES = {"PPLQ", "PPLH", "PPLW"}


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_MILES * math.asin(math.sqrt(a))


@contextlib.contextmanager
def source(location, member, encoding):
    """Open one source as a text stream.

    `location` is a URL or a local path, and either plain text or a zip archive
    holding `member`. A local path lets the test suite run the whole builder
    offline against fixtures.
    """
    tmp = None
    try:
        if location.startswith(("http://", "https://")):
            tmp = tempfile.NamedTemporaryFile(delete=False)
            with urllib.request.urlopen(location, timeout=300) as resp:
                shutil.copyfileobj(resp, tmp)
            tmp.close()
            path = tmp.name
        else:
            path = location
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as zf:
                names = [n for n in zf.namelist() if n.endswith(member)]
                if len(names) != 1:
                    sys.exit("%s: expected exactly one %s inside, found %r"
                             % (location, member, zf.namelist()))
                with zf.open(names[0]) as raw:
                    yield io.TextIOWrapper(raw, encoding=encoding, newline="")
        else:
            with open(path, encoding=encoding, newline="") as fh:
                yield fh
    finally:
        if tmp is not None:
            os.unlink(tmp.name)


def add_town(towns, city, state, miles):
    """Record a town at `miles`, keeping the shortest distance seen for it.

    The key is normalized exactly as pickup_area.resolve() normalizes a
    listing's stated location, so "St. Joseph" and "Saint Joseph" land on the
    same entry from either side.
    """
    key = "%s, %s" % (pickup_area.normalize_city(city), state.upper())
    if key not in towns or miles < towns[key]:
        towns[key] = miles


def read_zip_centroids(location):
    recs = []
    with source(location, "all_us_zipcodes.csv", "utf-8") as fh:
        for r in csv.DictReader(fh):
            lat, lon = r.get("lat"), r.get("lon")
            if not lat or not lon:
                continue
            recs.append((r["code"].strip(), r["city"].strip(), r["state"].strip(),
                         float(lat), float(lon)))
    if not recs:
        sys.exit("ZIP centroid source returned no usable rows")
    return recs


def read_place_names(location):
    """Return place GEOID -> (name without its LSAD suffix, state)."""
    places = {}
    with source(location, "_Gaz_place_national.txt", "utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        reader.fieldnames = [h.strip() for h in reader.fieldnames]
        for r in reader:
            name, lsad = r["NAME"].strip(), r["LSAD"].strip()
            if lsad not in LSAD_SUFFIX:
                sys.exit("place gazetteer used LSAD %r on %r; add it to "
                         "LSAD_SUFFIX" % (lsad, name))
            suffix = LSAD_SUFFIX[lsad]
            if suffix:
                if not name.endswith(suffix):
                    sys.exit("place %r does not end in the %r that its LSAD %s "
                             "declares" % (name, suffix, lsad))
                name = name[: -len(suffix)]
            places[r["GEOID"].strip()] = (name, r["USPS"].strip())
    if not places:
        sys.exit("place gazetteer returned no rows")
    return places


def add_zcta_places(towns, location, zips, places):
    """Add every census place that overlaps an in-radius ZIP.

    A place takes its ZIP's distance, not its own centroid distance: a seller
    who writes "Darmstadt, IN" sits at ZIP 47725, and 47725 is the origin.
    """
    added = 0
    with source(location, "tab20_zcta520_place20_natl.txt", "utf-8-sig") as fh:
        for r in csv.DictReader(fh, delimiter="|"):
            zcta = r["GEOID_ZCTA5_20"].strip()
            geoid = r["GEOID_PLACE_20"].strip()
            if zcta not in zips or not geoid:
                continue
            if geoid not in places:
                sys.exit("ZCTA-to-place named place %r, which the gazetteer "
                         "does not list" % geoid)
            name, state = places[geoid]
            add_town(towns, name, state, zips[zcta])
            added += 1
    if not added:
        sys.exit("ZCTA-to-place matched none of the in-radius ZIPs")


def add_geonames_places(towns, location, o_lat, o_lon, radius_miles):
    """Add populated places that no ZIP label and no census place covers."""
    added = 0
    with source(location, "US.txt", "utf-8") as fh:
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if len(f) < 11 or f[6] != "P" or f[7] in DEAD_PLACE_CODES:
                continue
            state = f[10].strip()
            if not state:
                continue
            miles = haversine(o_lat, o_lon, float(f[4]), float(f[5]))
            if miles > radius_miles:
                continue
            add_town(towns, f[1].strip(), state, round(miles, 1))
            added += 1
    if not added:
        sys.exit("GeoNames returned no populated places inside the radius")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--radius-miles", type=float, default=30.0)
    ap.add_argument("--csv", default=ZIP_CSV_URL,
                    help="local copy of the ZIP centroid CSV")
    ap.add_argument("--zcta-place", default=ZCTA_PLACE_URL,
                    help="local copy of the census ZCTA-to-place file")
    ap.add_argument("--place-gazetteer", default=PLACE_GAZ_URL,
                    help="local copy of the census place gazetteer")
    ap.add_argument("--geonames", default=GEONAMES_URL,
                    help="local copy of the GeoNames US dump")
    ap.add_argument("--out", default=OUT,
                    help="output path (default: %(default)s)")
    a = ap.parse_args()

    recs = read_zip_centroids(a.csv)
    origin = next((x for x in recs if x[0] == ORIGIN_ZIP), None)
    if origin is None:
        sys.exit("origin ZIP %s not present in the centroid source" % ORIGIN_ZIP)
    _, o_city, o_state, o_lat, o_lon = origin

    zips, towns = {}, {}
    for code, city, state, lat, lon in recs:
        miles = haversine(o_lat, o_lon, lat, lon)
        if miles > a.radius_miles:
            continue
        zips[code] = round(miles, 1)
        add_town(towns, city, state, zips[code])

    places = read_place_names(a.place_gazetteer)
    add_zcta_places(towns, a.zcta_place, zips, places)
    add_geonames_places(towns, a.geonames, o_lat, o_lon, a.radius_miles)

    doc = {
        "_doc": ("ZIPs and towns within radius_miles of Adam's origin ZIP. A "
                 "local-pickup-only listing is actionable only if its stated "
                 "location resolves into this set; anything else must ship. A "
                 "town carries the shortest distance any source gives it, and "
                 "the town names cover ZIP labels, census places and GeoNames "
                 "localities alike. Regenerate with build_pickup_area.py -- do "
                 "not hand-edit."),
        "origin_zip": ORIGIN_ZIP,
        "origin_city": o_city,
        "origin_state": o_state,
        "radius_miles": a.radius_miles,
        "sources": [a.csv, a.zcta_place, a.place_gazetteer, a.geonames],
        "zips": dict(sorted(zips.items())),
        "towns": dict(sorted(towns.items())),
    }
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, sort_keys=False)
        fh.write("\n")
    print("wrote %s: %d ZIPs, %d towns within %.0f mi of %s"
          % (a.out, len(zips), len(towns), a.radius_miles, ORIGIN_ZIP))


if __name__ == "__main__":
    main()
