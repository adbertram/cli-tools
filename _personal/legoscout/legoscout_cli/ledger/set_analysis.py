#!/usr/bin/env python3
"""The one reader and normalizer of a deal record's `set_analysis`.

`set_analysis` is the BrickLink evidence behind a set row: catalog metadata plus
six-month sold summaries, one entry per detected set. The producer is
``legoscout pricing set-sales``, whose `summarize_set()` returns
exactly ONE per-set object; the appraiser calls it once per detected set and
collects the results. So the canonical stored shape is an ARRAY of per-set
objects, or `null` when no set was priced.

It was not always. On 2026-08-05 the ledger held three top-level shapes at once:
1,364 `null`, 493 `dict`, and 331 `array`. `deal_schema.json` typed the field
`object|null`, so the 331 array rows failed the schema the moment it became
executable. The dicts came in four families, and this module converts every one
of them:

    {"sets": [...], ...}          an aggregate wrapper around the real entries
    {"75192-1": {...}, ...}       keyed by set number instead of listed
    {"set_no": "75192-1", ...}    one bare per-set object, never wrapped
    {...}                         one unkeyed appraisal blob, or a refusal note

Each ENTRY had the same problem one level down: 989 stored entries used 152
distinct keys for the producer's eleven facts. A set's name was at `name`,
`catalog_name`, `set_name` or `catalog.name`; its profit at `potential_profit`,
`profit` or `set_profit`; its comp depth at any of eight keys. Every reader
therefore carried its own list of spellings, and each list was different and
incomplete -- `legoscout display rows` read only `potential_profit`, so 64 fully priced
rows rendered as "profit incomplete".

`normalize_entry` settles that too. The thirteen `ENTRY_FIELDS` are present on
every entry, so a reader names one key per fact. A key this module cannot map to
one of them is kept VERBATIM: an equivalence that has not been proven against
the stored data is not asserted, and provenance is not thrown away to make the
shape tidy. That took 152 keys to 79.

Read it only through this module -- `entries()`, `names()`, `sold_count()`,
`profit_of()`, `normalize()` -- the same way `available_fulfillment.py` and
`shipping_estimate.py` own their fields. Nothing else in the pipeline may decide
what shape it is looking at.

## Why the wrapper's own keys are dropped

An aggregate wrapper carried lot-level values beside its `sets` list:
`potential_profit_total`, `purchase_price`, `used_avg_6mo`, `set_numbers`. Every
one of those facts already has a top-level ledger column that every reader
actually uses -- `score_deal._net_resale` reads `record["potential_profit"]`,
`legoscout display rows` reads `d.potential_profit`. They were a second copy, and a
second copy drifts: on 7 multi-set rows the wrapper's `potential_profit_total`
already disagreed with the record's own `potential_profit` (up to $20.59 apart on
`shopgoodwill|271135286`). Dropping them removes a stale duplicate rather than
losing a fact. `OWNED_BY_COLUMN` below names the column that owns each one.

Every other wrapper key -- `fee_rate`, `looked_up_at`, `allocation`, `notes`,
`status` -- is a fact ABOUT the lookup that has no column, so it is copied onto
each entry it describes and nothing is lost.
"""
from __future__ import annotations

import re

# A BrickLink set number used as a dict KEY: `75192-1`, `4184-1`, `8002-1`.
# Matched against keys only, and only when the value is an object, so a scalar
# field can never be mistaken for a set.
SET_NUMBER_KEY = re.compile(r"^\d+[a-zA-Z]*-\d+$")

# Wrapper keys whose fact is already a top-level ledger column. Dropped rather
# than copied onto an entry: they are per-LOT values, so attributing one to a
# single set states something false on a multi-set lot, and they have already
# gone stale against the column that owns them. Value = the owning column.
OWNED_BY_COLUMN: dict[str, str] = {
    "potential_profit_total": "potential_profit",
    "combined_potential_profit": "potential_profit",
    "aggregate_potential_profit": "potential_profit",
    "profit_incomplete": "profit_incomplete",
    "purchase_price": "estimated_total",
    "purchase_price_before_shipping": "estimated_total",
    "allocated_purchase_cost": "estimated_total",
    # Net RESALE, not profit -- no cost is subtracted. The record derives it
    # the same way `score_deal._net_resale` does, from two columns at once.
    "net_resale_after_fees": "potential_profit + estimated_total",
    "net_resale_after_fee": "potential_profit + estimated_total",
    "gross_resale_6mo_used": "potential_profit + estimated_total",
    "used_avg_6mo": "used_avg_6mo",
    "new_avg_6mo": "new_avg_6mo",
    "set_numbers": "set_numbers",
}

# ---------------------------------------------------------------------------
# The canonical per-set ENTRY
# ---------------------------------------------------------------------------
#
# `lookup_set_sales.summarize_set()` is the producer, so its return value is the
# shape. 989 stored entries used 152 distinct keys for these same eleven facts.
#
# An alias is listed ONLY where the two keys were verified to mean the same
# thing on the stored data. Three that look like profit are NOT profit and are
# deliberately absent: `net_after_fees`, `net_resale` and `net_resale_after_fees`
# are resale AFTER FEES with no cost subtracted. On `hibid|315885404` the entry
# records `net_resale_after_fees: 69.34` against a used average of 79.70 (79.70
# x 0.87), while `poshmark|6a71c171af9ad154b1617dd6` shows the difference: its
# `profit` of -1038.08 is that same resale figure less a 1076.49 purchase price.
# Reading one as the other would turn a $69 resale into a $69 profit.
ENTRY_FIELDS: tuple[str, ...] = (
    "set_no", "lookup_status", "catalog", "condition", "purchase_price",
    "fee_rate", "used", "new", "selected_condition_summary",
    "selected_condition_priced", "potential_profit",
    # `blended_avg_sold_price`/`comp_basis` are new, added when
    # `_apply_comps` started pricing off a comp-count-weighted blend of
    # BrickLink and eBay rather than BrickLink alone -- the actual number
    # `potential_profit` was computed against, and its plain-English
    # derivation. No legacy spelling exists for either; they were never
    # among the 152 historical spellings of the original eleven facts.
    "blended_avg_sold_price", "comp_basis",
)

_ENTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "set_no": ("set_number", "listed_set_number"),
    # An allocated share of the lot's landed cost. That IS what the appraiser
    # passes to `lookup_set_sales.py --purchase-price`.
    "purchase_price": ("allocated_cost", "allocated_purchase_cost",
                       "allocated_purchase_price", "purchase_price_allocated",
                       "allocated_purchase"),
    "fee_rate": ("fee_rate_applied",),
    # Which condition the profit was priced against. Every spelling already
    # holds `N` or `U`; no vocabulary conversion is involved.
    "condition": ("inferred_condition", "condition_priced", "condition_used",
                  "condition_used_for_profit", "condition_inferred",
                  "set_condition"),
    # Resale after fees LESS cost. Verified on the stored rows.
    "potential_profit": ("profit", "set_profit"),
    "selected_condition_priced": ("priced",),
    "catalog": ("bricklink_catalog",),
}

# `catalog` is BrickLink's own record. Where an entry never stored one, these
# flat keys hold the parts of it that were kept, and they rebuild a PARTIAL
# catalog -- present keys only, nothing invented.
_CATALOG_FROM_FLAT: dict[str, tuple[str, ...]] = {
    "no": ("set_no", "set_number"),
    "name": ("name", "catalog_name", "set_name"),
    "year_released": ("year_released", "year"),
    "weight": ("catalog_weight_grams", "catalog_weight_g", "weight_g"),
    "type": ("type",),
}

# ---------------------------------------------------------------------------
# The canonical price SUMMARY, from `lookup_set_sales.normalize_price_summary`
# ---------------------------------------------------------------------------

SUMMARY_FIELDS: tuple[str, ...] = (
    "condition", "guide_type", "sold_window", "six_month_avg_sold_price",
    "avg_price", "qty_avg_price", "min_price", "max_price", "total_quantity",
    "unit_quantity", "currency_code", "price_detail_count",
)

# True of any summary this module builds, by definition of the slot it fills.
# `used`/`new` hold a BrickLink SOLD guide average over the last six months --
# every historical key says so in its own name (`used_avg_6mo`,
# `used_six_month_avg_sold_price`). Nothing else is assumed: a value the row did
# not record stays None, which is exactly what `normalize_price_summary` writes
# when BrickLink reports nothing.
_GUIDE_TYPE = "sold"
_SOLD_WINDOW = "bricklink_sold_guide_last_6_months"

# Flat per-condition keys, by the summary field they carry. Prefixed with
# `used_`/`new_` on the entry.
_SUMMARY_FROM_FLAT: dict[str, tuple[str, ...]] = {
    "six_month_avg_sold_price": (
        "avg_6mo", "6mo_avg_sold", "six_month_avg_sold_price", "6mo", "avg"),
    # How many individual sold LISTINGS backed the average.
    "price_detail_count": (
        "price_detail_count", "comp_count", "sold_count", "sale_count",
        "6mo_comp_count", "detail_count", "6mo_price_detail_count"),
    # How many UNITS those listings moved. A different number, and the producer
    # keeps them apart.
    "total_quantity": ("qty_6mo", "sold_quantity_6mo"),
    "min_price": ("min_price",),
    "max_price": ("max_price",),
    "qty_avg_price": ("qty_avg_price", "qty_avg"),
}

# Sub-keys inside an already-nested summary, mapped onto the canonical name.
# `median_price_6mo` has no canonical home and is kept verbatim rather than
# dropped -- see _normalize_summary.
_SUMMARY_SUBKEY_ALIASES: dict[str, tuple[str, ...]] = {
    "six_month_avg_sold_price": ("avg_price_6mo",),
    "price_detail_count": ("sales_count_6mo",),
    "min_price": ("min_price_6mo",),
    "max_price": ("max_price_6mo",),
}

# Where the SELECTED condition's average was kept flat.
_SELECTED_AVG_KEYS = ("selected_condition_avg_6mo", "selected_condition_6mo_avg_sold",
                      "selected_condition_avg", "six_month_avg_sold_price", "avg_price")
_SELECTED_COUNT_KEYS = ("selected_condition_count", "price_detail_count")


class Unreadable(ValueError):
    """A `set_analysis` value in a shape this module does not recognise."""


def _first(source: dict, keys) -> tuple[bool, object]:
    """The first key present, and whether any was. `None` is a recorded answer,
    so presence is reported separately from the value."""
    for key in keys:
        if key in source:
            return True, source[key]
    return False, None


def _normalize_summary(raw, condition: str | None) -> dict | None:
    """One `used`/`new` price summary in the producer's shape.

    A key the row never recorded stays `None` -- the same value
    `normalize_price_summary` writes when BrickLink reports nothing for it. Only
    `condition`, `guide_type` and `sold_window` are filled in, and only because
    the slot itself guarantees them: a `used` summary is a used summary, and
    every historical key names a six-month SOLD average.

    A sub-key with no canonical home (`median_price_6mo`) is kept verbatim
    beside the canonical ones rather than dropped.
    """
    if not isinstance(raw, dict):
        return None
    out: dict = {}
    for field in SUMMARY_FIELDS:
        found, value = _first(raw, (field,) + _SUMMARY_SUBKEY_ALIASES.get(field, ()))
        out[field] = value if found else None
    if out["condition"] is None:
        out["condition"] = condition
    if out["guide_type"] is None:
        out["guide_type"] = _GUIDE_TYPE
    if out["sold_window"] is None:
        out["sold_window"] = _SOLD_WINDOW
    # `avg_price` and `six_month_avg_sold_price` are one fact:
    # `normalize_price_summary` sets both from the same BrickLink number.
    if out["six_month_avg_sold_price"] is None:
        out["six_month_avg_sold_price"] = out["avg_price"]
    if out["avg_price"] is None:
        out["avg_price"] = out["six_month_avg_sold_price"]
    mapped = set(SUMMARY_FIELDS)
    for aliases in _SUMMARY_SUBKEY_ALIASES.values():
        mapped.update(aliases)
    for key, value in raw.items():
        if key not in mapped:
            out[key] = value
    return out


def _summary_from_flat(entry: dict, prefix: str, condition: str | None) -> dict | None:
    """A summary built from the `used_*` / `new_*` keys an entry kept flat."""
    values: dict = {}
    for field, suffixes in _SUMMARY_FROM_FLAT.items():
        candidates = tuple(prefix + "_" + s for s in suffixes)
        if field == "price_detail_count":
            # `price_detail_count_used` inverts the usual order.
            candidates += ("price_detail_count_" + prefix,)
        if field == "six_month_avg_sold_price":
            candidates += ("bricklink_%s_six_month_avg_sold" % prefix,)
        found, value = _first(entry, candidates)
        if found:
            values[field] = value
    if not values:
        return None
    values["condition"] = "U" if prefix == "used" else "N"
    return _normalize_summary(values, values["condition"])


def _selected_summary(entry: dict, used, new, condition: str | None) -> dict | None:
    """The summary the profit was computed against.

    It is the `used` or `new` summary the entry's own `condition` names -- not a
    third opinion. Where a row kept only a flat selected-condition average and
    no per-condition detail, that average becomes the summary.
    """
    found, stored = _first(entry, ("selected_condition_summary",))
    if found and isinstance(stored, dict):
        return _normalize_summary(stored, entry.get("selected_condition") or condition)
    picked = used if condition == "U" else new if condition == "N" else None
    if picked is not None:
        return picked
    found, avg = _first(entry, _SELECTED_AVG_KEYS)
    if not found:
        return None
    values = {"six_month_avg_sold_price": avg}
    count_found, count = _first(entry, _SELECTED_COUNT_KEYS)
    if count_found:
        values["price_detail_count"] = count
    return _normalize_summary(values, entry.get("selected_condition") or condition)


def _catalog_from_flat(entry: dict, set_no=None) -> dict | None:
    """A PARTIAL BrickLink catalog record from the pieces an entry kept flat.

    Present keys only. `names()` then reads exactly `catalog.name` instead of
    trying four spellings, which is the whole point.

    Returns None unless the entry recorded something BEYOND the set number. A
    catalog holding only `no` restates `set_no` and adds nothing -- and building
    one made normalize() non-idempotent, because the second pass had a `set_no`
    the first pass had to resolve from `listed_set_number`.
    """
    out: dict = {}
    for field, keys in _CATALOG_FROM_FLAT.items():
        found, value = _first(entry, keys)
        if found and value is not None:
            out[field] = value
    if not (set(out) - {"no"}):
        return None
    if "no" not in out and set_no is not None:
        out["no"] = set_no
    return out


def normalize_entry(entry: dict) -> dict:
    """One per-set entry in the producer's shape.

    The thirteen `ENTRY_FIELDS` are always present, so a reader names one key per
    fact. Every key this module cannot map is kept verbatim beside them: an
    equivalence that has not been proven is not asserted, and provenance the
    ledger recorded is not thrown away to make the shape tidy.
    """
    if not isinstance(entry, dict):
        raise Unreadable("a set_analysis entry must be an object, got %s: %r"
                         % (type(entry).__name__, entry))

    # 12 entries nested the whole producer result one level down under `lookup`.
    source = dict(entry)
    nested = source.pop("lookup", None)
    if isinstance(nested, dict):
        source = {**nested, **source}

    out: dict = {}
    for field in ENTRY_FIELDS:
        found, value = _first(source, (field,) + _ENTRY_ALIASES.get(field, ()))
        out[field] = value if found else None

    if not isinstance(out["catalog"], dict):
        out["catalog"] = _catalog_from_flat(source, out["set_no"])
    elif "name" not in out["catalog"]:
        # A stored catalog that never carried the name the entry kept flat.
        rebuilt = _catalog_from_flat(source, out["set_no"]) or {}
        if "name" in rebuilt:
            out["catalog"] = {**out["catalog"], "name": rebuilt["name"]}

    condition = out["condition"]
    sales = source.get("sales")
    for slot, prefix in (("used", "used"), ("new", "new")):
        summary = _normalize_summary(out[slot], "U" if prefix == "used" else "N")
        if summary is None and isinstance(sales, dict):
            summary = _normalize_summary(sales.get(prefix),
                                         "U" if prefix == "used" else "N")
        if summary is None:
            summary = _normalize_summary(
                source.get("bricklink_sold_%s" % prefix),
                "U" if prefix == "used" else "N")
        if summary is None:
            summary = _summary_from_flat(source, prefix, condition)
        out[slot] = summary

    # A single unprefixed average belongs to the condition the entry names, and
    # that is the used or new average by definition of which condition it is.
    if out["used"] is None and out["new"] is None and condition in ("U", "N"):
        found, avg = _first(source, ("six_month_avg_sold_price", "avg_price"))
        if found:
            values = {"six_month_avg_sold_price": avg}
            count_found, count = _first(source, ("price_detail_count",))
            if count_found:
                values["price_detail_count"] = count
            out["used" if condition == "U" else "new"] = _normalize_summary(
                values, condition)

    out["selected_condition_summary"] = _selected_summary(
        source, out["used"], out["new"], condition)

    mapped = set(ENTRY_FIELDS) | {"sales"}
    for aliases in _ENTRY_ALIASES.values():
        mapped.update(aliases)
    for keys in _CATALOG_FROM_FLAT.values():
        mapped.update(keys)
    for prefix in ("used", "new"):
        for suffixes in _SUMMARY_FROM_FLAT.values():
            mapped.update(prefix + "_" + s for s in suffixes)
        mapped.add("price_detail_count_" + prefix)
        mapped.add("bricklink_sold_" + prefix)
    mapped.update(_SELECTED_AVG_KEYS)
    mapped.update(_SELECTED_COUNT_KEYS)
    mapped.update(("selected_condition", "bricklink_used_six_month_avg_sold",
                   "bricklink_new_six_month_avg_sold"))
    for key, value in source.items():
        if key not in mapped:
            out[key] = value
    return out


def _entry_from(value, set_no: str | None = None) -> dict:
    # Four Poshmark rows stored `sets` as a list of bare set-number STRINGS,
    # with the comps at wrapper level. The number is the whole entry; the
    # wrapper's own keys reach it through _carry_down.
    if isinstance(value, str) and SET_NUMBER_KEY.match(value):
        return {"set_no": value}
    if not isinstance(value, dict):
        raise Unreadable(
            "a set_analysis entry must be an object or a set number, got %s: %r"
            % (type(value).__name__, value))
    if set_no is None or "set_no" in value:
        return dict(value)
    return {"set_no": set_no, **value}


def _carry_down(entries: list[dict], wrapper: dict) -> list[dict]:
    """Copy the wrapper's own keys onto each entry it describes.

    An entry's own value always wins: on a multi-set lot the entry's
    `purchase_price` is its allocated share, and the wrapper's is the whole lot.
    Keys in OWNED_BY_COLUMN are never copied -- see the module docstring.
    """
    carried = {k: v for k, v in wrapper.items()
               if k != "sets" and k not in OWNED_BY_COLUMN}
    if not carried:
        return entries
    return [{**carried, **entry} for entry in entries]


def _unwrap(value):
    """The historical top-level shape as a plain list of raw entry dicts."""
    if isinstance(value, list):
        return [_entry_from(item) for item in value]

    # An aggregate wrapper. Its `sets` list holds the real entries.
    if isinstance(value.get("sets"), list):
        entries = [_entry_from(item) for item in value["sets"]]
        if not entries:
            # `sets: []` with wrapper keys is a lookup that ran and found
            # nothing to price. The wrapper's own notes are the whole answer.
            leftover = {k: v for k, v in value.items()
                        if k != "sets" and k not in OWNED_BY_COLUMN}
            return [leftover] if leftover else []
        return _carry_down(entries, value)

    # Keyed by set number rather than listed. Every other key is wrapper metadata.
    keyed = [k for k, v in value.items()
             if SET_NUMBER_KEY.match(k) and isinstance(v, dict)]
    if keyed:
        entries = [_entry_from(value[k], set_no=k) for k in keyed]
        wrapper = {k: v for k, v in value.items() if k not in keyed}
        return _carry_down(entries, wrapper)

    # One bare per-set object, or one unkeyed appraisal blob / refusal note.
    return [dict(value)]


def normalize(value):
    """Any historical `set_analysis` value as the canonical list, or None.

    Two passes. `_unwrap` settles the TOP-LEVEL shape -- five spellings, from a
    `sets` wrapper to a dict keyed by set number. `normalize_entry` then settles
    each ENTRY -- 152 distinct keys across 989 stored entries for the producer's
    eleven facts.

    Raises `Unreadable` rather than guessing: a shape nobody has seen is a bug in
    whatever wrote it, and silently accepting one is how the field reached this
    many spellings in the first place.
    """
    if value is None:
        return None

    if not isinstance(value, (list, dict)):
        raise Unreadable(
            "set_analysis must be an array or null, got %s: %r"
            % (type(value).__name__, value))

    if not value:
        # `[]`, `{}` and `null` are the same answer -- no set was priced -- and
        # the ledger held all three. One spelling, so no reader tests for three.
        return None

    return [normalize_entry(entry) for entry in _unwrap(value)] or None


def entries(record: dict) -> list[dict]:
    """The per-set entries on a record, normalizing a legacy shape on read."""
    return normalize(record.get("set_analysis")) or []


def names(record: dict) -> list[str]:
    """Each detected set's display name, in entry order.

    ONE key. It carried a four-spelling lookup (`name`, `catalog_name`,
    `set_name`, `catalog.name`) until `normalize_entry` started folding all four
    into the producer's `catalog`. An entry with no recorded name contributes
    nothing rather than an empty string, so a caller cannot mistake "not
    recorded" for a set actually called "".
    """
    out = []
    for entry in entries(record):
        catalog = entry.get("catalog")
        name = catalog.get("name") if isinstance(catalog, dict) else None
        if isinstance(name, str) and name.strip():
            out.append(name.strip())
    return out


def sold_count(record: dict) -> int | None:
    """The deepest six-month sold-comp count backing any of this record's sets.

    Comp DEPTH, which `legoscout-deal-scoring` turns into a multiplier. It reads
    `price_detail_count` -- how many individual sold listings BrickLink reported
    -- and never `total_quantity`, which counts units and is a larger number for
    the same evidence. `None` when no entry recorded a count.
    """
    counts = []
    for entry in entries(record):
        for slot in ("used", "new", "selected_condition_summary"):
            summary = entry.get(slot)
            if not isinstance(summary, dict):
                continue
            value = summary.get("price_detail_count")
            if isinstance(value, int) and not isinstance(value, bool):
                counts.append(value)
    return max(counts) if counts else None


def profit_of(entry: dict):
    """One entry's own net-of-fees profit, or None.

    ONE key. `profit`, `set_profit` and `potential_profit` all meant this and
    `normalize_entry` folds them together. `net_after_fees`, `net_resale` and
    `net_resale_after_fees` deliberately do NOT: they are resale before any cost
    is subtracted, and reading one as profit overstates a lot by its full
    purchase price.
    """
    value = entry.get("potential_profit")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


if __name__ == "__main__":
    raise SystemExit(
        "set_analysis.py is a library -- import normalize()/entries()/names() "
        "rather than running this file directly.")
