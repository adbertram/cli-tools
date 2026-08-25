#!/usr/bin/env python3
"""The one reader of `deal_schema.json`.

The schema tags every deal-record field with the phase that produces it --
`crawl`, `appraisal`, or `synthesis`. This module turns that tag into a query
so a phase's field set is computed from the schema, never hand-copied into a
skill file where it can drift from the record it describes.

    legoscout deals schema                # every field, one line each
    legoscout deals schema crawl           # field names for one phase
"""
from __future__ import annotations

from .. import paths
import argparse
import functools
import json
import math
import os
import sys

SCHEMA = paths.DEAL_SCHEMA_JSON

PHASES = ("crawl", "appraisal", "synthesis")

# Which stored price `price_basis` names. Every downstream number -- landed cost,
# $/lb, set profit, the score -- is denominated in this one, so reading the wrong
# field understates cost silently: a 2026-07-23 run priced an eBay lot off its
# $12 bid instead of its $30 BIN and understated $/lb by ~40%.
#
# This table once had separate copies in record assembly and validation. Each
# copy could disagree about which number was authoritative.
#
# This is the WHOLE `price_basis` vocabulary, and the stored column each value
# names. It is one table rather than a partial map beside a separate enum,
# because that gap is where two defects lived at once on 2026-08-06:
#
#   * `ask_price` named `current_price` here while the rows that used it held
#     the amount in `static_price`, so `priced_amount()` returned None on 256 of
#     484 ask_price rows -- 234 of Depop's 303 -- and each dropped out of landed
#     cost, $/lb, fees, tax, profit and the score while still looking populated.
#     RETIRED: a fixed ask IS a static price, so there is now one basis for it
#     rather than two that disagree. See `listing.PRICE_BASIS_RULE` branch (3).
#   * `estimated` was in the schema enum and in `validate.PRICE_BASES` but was
#     never a key here, so a record holding a real $45.00 `buy_now_price` under
#     `price_basis: estimated` stored `last_price: "unknown"`, returned None
#     from `priced_amount()`, and made `validate.check` skip the hammer rule
#     entirely -- `--strict` reported a $999 hammer on a $45 listing as clean.
#     RETIRED: an estimated price is an invented price, and this project records
#     no invented prices.
#
# `unknown` is the ONE value that names no column. It means "this listing was
# not read", so `priced_amount()` returning None is the honest answer -- and
# `validate.check` errors on a row that claims it while storing a number.
PRICE_BASIS_COLUMNS = {
    "buy_now": "buy_now_price",
    "static_price": "static_price",
    "current_price": "current_price",
    "unknown": None,
}

# The priceable subset. DERIVED, never hand-listed: `PRICE_FIELD_BY_BASIS`,
# `deal_schema.json`'s enum and `validate.PRICE_BASES` were three hand-kept
# copies of one vocabulary, and both retirements above are drift between them.
PRICE_FIELD_BY_BASIS = {basis: column
                        for basis, column in PRICE_BASIS_COLUMNS.items()
                        if column is not None}


def num(value):
    """A real number, or None. Excludes bool, which is an int in Python and
    would make `True` read as a $1.00 price."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def priced_amount(record: dict):
    """The numeric price `price_basis` names, or None."""
    field = PRICE_FIELD_BY_BASIS.get(record.get("price_basis"))
    return None if field is None else num(record.get(field))


def _stamp(path: str) -> tuple:
    """(size, mtime) of the schema file, so an edit invalidates every cache."""
    st = os.stat(path)
    return (st.st_size, st.st_mtime_ns)


@functools.lru_cache(maxsize=8)
def _load_cached(path: str, stamp: tuple) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load(path: str = SCHEMA) -> dict:
    """The parsed schema. Cached on (path, size, mtime).

    `ledger_db.save()` validates every record field by field, so an uncached
    read re-opened and re-parsed this file 57 times per record -- 125,000 file
    reads and 20.8 seconds on a 2,188-row ledger. The stamp is part of the key
    so a test that rewrites the file still sees its own edit.
    """
    return _load_cached(path, _stamp(path))


@functools.lru_cache(maxsize=512)
def _validator(path: str, stamp: tuple, field: str):
    """One compiled jsonschema validator per field.

    Compiling is the other half of the cost: `jsonschema.validate()` builds a
    validator class, resolves `$schema`, and check_schema()s the subschema on
    every single call.
    """
    import jsonschema

    spec = _load_cached(path, stamp)["properties"].get(field)
    if spec is None:
        raise KeyError("%r is not a field in deal_schema.json" % field)
    return jsonschema.validators.validator_for(spec)(spec)


class Invalid(ValueError):
    """A record or field that does not match `deal_schema.json`."""


def price_bases(path: str = SCHEMA) -> tuple:
    """The `price_basis` vocabulary, proven identical on both sides. Raises.

    `deal_schema.json` decides what may be STORED; `PRICE_BASIS_COLUMNS` decides
    what can be PRICED. When they disagree, the extra value looks legal all the
    way into the ledger and then reads as no price at all -- which is exactly
    how `estimated` hid a $999 hammer on a $45 listing from `--strict`. Callers
    read the vocabulary through here so the drift cannot survive an import.
    """
    enum = tuple(load(path)["properties"]["price_basis"]["enum"])
    extra = sorted(set(enum) - set(PRICE_BASIS_COLUMNS))
    missing = sorted(set(PRICE_BASIS_COLUMNS) - set(enum))
    if extra or missing:
        raise Invalid(
            "price_basis vocabulary has drifted: deal_schema.json allows %s "
            "that PRICE_BASIS_COLUMNS cannot price, and PRICE_BASIS_COLUMNS "
            "prices %s that deal_schema.json will not store"
            % (extra or "nothing", missing or "nothing"))
    return enum


def _reject_non_finite(field: str, value) -> None:
    """`inf` and `nan` are floats, so JSON Schema `"type": "number"` accepts them.

    They are not prices, weights or distances. An `inf` weight survives the save
    and then poisons every figure derived from it: `per_lb_price` goes `nan`,
    and the rescore aborts the WHOLE ledger with `curve lookup fell through for
    x=nan` -- a message that names no field and no listing. Rejected at the one
    gate every stored value passes through, rather than defended against at
    each of the dozen places that divide by one.

    Walks nested objects and arrays too: `fee_breakdown.hammer` and a
    `set_analysis` entry's numbers reach the same arithmetic that a top-level
    price does.
    """
    if isinstance(value, float) and not math.isfinite(value):
        raise Invalid(
            "%s: %r is not a finite number. `inf` and `nan` pass JSON Schema's "
            "`number` type but are not a quantity; the arithmetic downstream "
            "produces `nan` and the rescore aborts on it." % (field, value))
    if isinstance(value, dict):
        for name, child in value.items():
            _reject_non_finite("%s.%s" % (field, name), child)
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_non_finite("%s[%d]" % (field, index), child)


def validate_field(field: str, value, path: str = SCHEMA) -> None:
    """Check one field against its own subschema.

    The schema was documentation for its whole life -- 60 typed properties that
    nothing ever ran, while `build_deal_record._require_scalar_types`
    re-implemented JSON Schema type dispatch in Python by reading `spec["type"]`
    out of this very file. This runs it instead.
    """
    import jsonschema

    try:
        _validator(path, _stamp(path), field).validate(value)
    except jsonschema.ValidationError as exc:
        raise Invalid("%s: %s" % (field, exc.message)) from None
    _reject_non_finite(field, value)


def validate(record: dict, *, fields=None, path: str = SCHEMA) -> None:
    """Check a record field by field, naming the LISTING and the field.

    Field-by-field rather than one whole-document call on purpose: a single
    top-level failure reports one message for a 59-field record, and the message
    that matters is which field on which listing is wrong. One appraiser batch
    returned `risks_unknowns` as a list on 20 records, and the only symptom was
    `Error binding parameter 41: type 'list' is not supported` -- a column index,
    no field, no listing, and the whole ledger write aborted rather than one row.
    """
    problems = []
    for field in (fields if fields is not None else load(path)["properties"]):
        if field not in record:
            continue
        try:
            validate_field(field, record[field], path)
        except Invalid as exc:
            problems.append(str(exc))
    if problems:
        raise Invalid("%s: %s" % (record.get("listing_key", "<no listing_key>"),
                                  "; ".join(problems)))


def duplicate_set_analysis_set_numbers(record: dict) -> list[str]:
    """`set_no` values that appear more than once in `record["set_analysis"]`.

    `build_record._apply_comps` divides landed cost by `len(sets)` to
    allocate each set's cost share, but sums each entry's FULL resale comp
    into the record total -- a duplicate `set_no` (from a comps result
    assembled outside `build_deal_record`, or a legacy row written before
    this check existed) double-counts that set's resale value against a
    single fractional cost share. A 2026-08-20 review demonstrated this
    reaching a live ledger write with zero errors, at up to 8x profit
    inflation on already-persisted rows, because `db.py`'s write-time
    validation and `validate.py`'s `--strict` audit each had their own
    inline copy of this rule -- shared here so neither can drift from the
    other or be forgotten by a third caller.
    """
    set_analysis = record.get("set_analysis")
    if not isinstance(set_analysis, list):
        return []
    set_nos = [entry.get("set_no") for entry in set_analysis if isinstance(entry, dict)]
    return sorted({n for n in set_nos if n and set_nos.count(n) > 1})


def fields_for_phase(phase: str, path: str = SCHEMA) -> list[str]:
    """Field names whose schema `phase` matches, in schema order."""
    if phase not in PHASES:
        raise ValueError("phase must be one of %s, got %r" % (PHASES, phase))
    doc = load(path)
    return [name for name, prop in doc["properties"].items() if prop["phase"] == phase]


def phase_of(field: str, path: str = SCHEMA) -> str:
    doc = load(path)
    props = doc["properties"]
    if field not in props:
        raise KeyError("%r is not a field in deal_schema.json" % field)
    return props[field]["phase"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phase", nargs="?", choices=PHASES,
                    help="print only this phase's fields")
    ap.add_argument("--json", action="store_true",
                    help="the raw JSON Schema properties, for a machine caller")
    a = ap.parse_args()

    doc = load()
    props = doc["properties"]
    names = fields_for_phase(a.phase) if a.phase else list(props)

    if a.json:
        print(json.dumps({n: props[n] for n in names}, indent=2))
        return 0

    # The TYPE is the half that was missing. Naming a phase used to print bare
    # field names and nothing else, so an agent filling a record could not learn
    # that `auction_end_date` is a string whose non-auction value is the literal
    # `not-an-auction`, nor that `set_analysis` is an array. On 2026-08-06 that
    # cost a whole run: all 153 appraised candidates were rejected by
    # `build_deal_record`, after every crawl and BrickLink call had been paid
    # for, on `None is not of type 'string'` and `set_analysis must be an array`.
    for name in names:
        prop = props[name]
        print("%-26s %-10s %-8s %s"
              % (name, prop["phase"], prop.get("type", "-"),
                 prop["description"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
