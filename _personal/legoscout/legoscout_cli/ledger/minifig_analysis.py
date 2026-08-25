#!/usr/bin/env python3
"""The one reader, validator, and normalizer of a deal record's
`minifig_analysis`.

`minifig_analysis` is the per-figure evidence behind a minifigure row: one
entry per provisional match group the identifier produced. The producer chain
is ``legoscout minifig detect`` -> ``identify`` -> agent verification ->
``price``; the stored shape is an ARRAY of group objects, or `null` when no
identification ran (every legacy row). It is typed `array|null` and stays that
way: unlike `set_analysis`, this field never grew historical spellings, so
there is nothing to unwrap and no guessing is ever needed.

Read it only through this module -- `entries()`, `figure_count()`,
`priced_subtotal()`, `sold_count()`, `crop_refs()`,
`identified_entries()`/`unknown_entries()`, `normalize()` -- the same way
`set_analysis.py` owns its field. Nothing else in the pipeline may decide what
shape it is looking at.

## Validation ownership

This module is the SOLE owner of normalized entry semantics (the plan's
Validation-ownership section): field presence, verification-to-fig_no/catalog
coupling, quantity rules, value consistency, duplicate ID rejection.
`ledger/validate.py` calls `entry_errors()`/`batch_errors()` from here and
adds only record-level rules of its own (category, provenance pairing,
count-equals-sum). The Phase F price finalizer calls the same functions before
pricing. Never add an entry invariant in a second place.
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import TypeGuard

# ---------------------------------------------------------------------------
# The canonical per-group ENTRY
# ---------------------------------------------------------------------------
#
# Locked in plans/plan-minifig-identification.md and its decisions reference.
# Every key is present on every normalized entry; a key the producer did not
# record holds None -- "not recorded" -- exactly like set_analysis's fields.

ENTRY_FIELDS: tuple[str, ...] = (
    "match_group_id",
    "detections",
    "representative_crop_ref",
    "brickognize_candidates",
    "verification",
    "fig_no",
    "catalog",
    "quantity",
    "condition_notes",
    "used",
    "unit_value",
    "extended_value",
    "null_value_reason",
    "errors",
)

# Verification statuses the identifier contract defines.
VERIFICATION_STATUSES = ("verified", "unknown", "unverifiable")

_PROTOCOL_RELATIVE_PREFIX = "//"


class Unreadable(ValueError):
    """A `minifig_analysis` value in a shape or with content this module does
    not accept. Raised rather than guessed at: a silently mis-read artifact is
    how invented numbers reach Adam's money."""


def _is_number(value) -> TypeGuard[float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_finite(value) -> TypeGuard[float]:
    return _is_number(value) and math.isfinite(value)


def round_cents(value) -> float:
    """Half-up cents rounding, idempotent on already-rounded values.

    The ONE rounding point for minifig money: producers call it when they set
    `unit_value`/`extended_value`; readers never re-round stored rows.
    """
    return float(Decimal(str(value)).quantize(Decimal("0.01"),
                                              rounding=ROUND_HALF_UP))


def _https_url(value):
    """Protocol-relative BrickLink image URLs become https; everything else
    passes through untouched."""
    if isinstance(value, str) and value.startswith(_PROTOCOL_RELATIVE_PREFIX):
        return "https:" + value
    if isinstance(value, list):
        return [_https_url(item) for item in value]
    if isinstance(value, dict):
        return {k: _https_url(v) for k, v in value.items()}
    return value


def normalize_entry(entry: dict) -> dict:
    """One per-group entry in the canonical shape.

    The fourteen `ENTRY_FIELDS` are always present, so a reader names one key
    per fact. Keys this module does not own are kept verbatim beside them --
    unmapped provenance is preserved, not dropped to tidy the shape.

    Raises `Unreadable` on malformed structure (non-dict entry, non-list
    detections, detection without a crop ref) or invalid numerics (boolean,
    NaN/infinite, zero/negative quantity or unit value). Structure and numeric
    TYPE problems raise here; cross-field RELATIONSHIPS are reported by
    `entry_errors()` below so one bad entry reports every defect instead of
    only its first.
    """
    if not isinstance(entry, dict):
        raise Unreadable(
            "a minifig_analysis entry must be an object, got %s: %r"
            % (type(entry).__name__, entry))

    out: dict = {}
    for field in ENTRY_FIELDS:
        out[field] = entry.get(field)

    # Unmapped provenance survives verbatim beside the canonical keys.
    for key, value in entry.items():
        if key not in out:
            out[key] = value

    detections = out["detections"]
    if detections is not None:
        if not isinstance(detections, list):
            raise Unreadable("detections must be a list, got %r" % (detections,))
        seen_crop_ids: set = set()
        for det in detections:
            if not isinstance(det, dict) or not det.get("crop_ref"):
                raise Unreadable(
                    "each detection needs an object with crop_ref, got %r"
                    % (det,))
            crop_id = det["crop_ref"]
            if not isinstance(crop_id, str):
                raise Unreadable(
                    "detection crop_ref must be a string, got %r" % (crop_id,))

    quantity = out["quantity"]
    if quantity is not None:
        if not _is_finite(quantity) or quantity <= 0:
            raise Unreadable(
                "quantity must be a positive finite number, got %r" % (quantity,))
        if quantity != int(quantity):
            raise Unreadable(
                "quantity must be a whole number, got %r" % (quantity,))

    for field in ("unit_value", "extended_value"):
        value = out[field]
        if value is not None and not _is_finite(value):
            raise Unreadable("%s must be a finite number or null, got %r"
                             % (field, value))
    unit_value = out["unit_value"]
    if unit_value is not None and unit_value < 0:
        raise Unreadable("unit_value must be >= 0, got %r" % (unit_value,))

    out["catalog"] = _https_url(out["catalog"])

    verification = out["verification"]
    if verification is not None and not isinstance(verification, dict):
        raise Unreadable("verification must be an object or null, got %r"
                         % (verification,))

    return out


# ---------------------------------------------------------------------------
# Canonical cross-field invariants (the sole owner)
# ---------------------------------------------------------------------------


def entry_errors(entry: dict) -> list[str]:
    """Every cross-field defect on one normalized entry, named precisely.

    Called by `ledger/validate.py` (record-level rules live there), by the
    Phase F price finalizer before pricing, and by display/scoring guards. An
    empty list means the entry is internally consistent -- NOT that pricing
    succeeded; check status/value fields for that.
    """
    errors: list[str] = []
    fig_no = entry.get("fig_no")
    catalog = entry.get("catalog")
    catalog_no = catalog.get("no") if isinstance(catalog, dict) else None
    verification = entry.get("verification") or {}
    status = verification.get("status")

    if status is not None and status not in VERIFICATION_STATUSES:
        errors.append("verification.status=%r is not one of %s"
                      % (status, "|".join(VERIFICATION_STATUSES)))

    if status == "verified":
        if not isinstance(fig_no, str) or not fig_no.strip():
            errors.append(
                "verified entry requires a non-empty exact fig_no")
        elif not isinstance(catalog_no, str) \
                or fig_no.strip() != catalog_no.strip():
            errors.append(
                "verified fig_no=%r does not match the stored catalog "
                "number %r" % (fig_no, catalog_no))
    elif status in ("unknown", "unverifiable"):
        leaked = [k for k in ("fig_no", "catalog", "used", "unit_value",
                              "extended_value") if entry.get(k) is not None]
        if leaked:
            errors.append(
                "%s entry must not carry priced identity fields: %s"
                % (status, ", ".join(leaked)))
        if not entry.get("null_value_reason"):
            errors.append(
                "unknown/unverifiable entry requires null_value_reason")

    if entry.get("null_value_reason") is not None \
            and entry.get("extended_value") is not None:
        errors.append(
            "null_value_reason=%r but extended_value=%r -- a valued entry "
            "has no reason to be null-valued"
            % (entry.get("null_value_reason"), entry.get("extended_value")))

    quantity = entry.get("quantity")
    if quantity is None:
        errors.append("quantity missing")
    elif not _is_number(quantity) or quantity < 1:
        errors.append("quantity must be a positive integer, got %r" % (quantity,))

    unit_value = entry.get("unit_value")
    extended = entry.get("extended_value")
    if unit_value is not None and extended is None:
        if entry.get("null_value_reason") is None:
            errors.append(
                "unit_value present but without a value overall: "
                "extended_value is null and null_value_reason is unset")
    if unit_value is not None and extended is not None:
        if _is_number(quantity) and quantity >= 1:
            expected = round_cents(unit_value * int(quantity))
            if abs(extended - expected) > 0.005:
                errors.append(
                    "extended_value=%r does not equal unit_value x quantity "
                    "(%r)" % (extended, expected))

    rep = entry.get("representative_crop_ref")
    detections = entry.get("detections") or []
    crop_ids = [d.get("crop_ref") for d in detections if isinstance(d, dict)]
    if rep is not None and rep not in crop_ids:
        errors.append(
            "representative_crop_ref=%r is not one of its detections' "
            "crop_refs" % (rep,))
    if len(set(crop_ids)) != len(crop_ids):
        errors.append("duplicate crop_ref within detections: %r" % (crop_ids,))

    if status == "verified" and fig_no \
            and not entry.get("null_value_reason") \
            and unit_value is None and extended is None:
        if not entry.get("errors"):
            errors.append(
                "verified entry without a value: unit_value/extended_value "
                "are null and neither null_value_reason nor errors explains "
                "why")

    return errors


def batch_errors(analysis: list[dict]) -> list[str]:
    """Batch-level defects across entries: duplicate match_group_id."""
    ids = [i for i in (e.get("match_group_id") for e in analysis)
           if isinstance(i, str)]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        return ["duplicate match_group_id: %s" % ", ".join(map(str, dupes))]
    return []


# ---------------------------------------------------------------------------
# Top-level normalization
# ---------------------------------------------------------------------------


def normalize(value):
    """A stored `minifig_analysis` value as the canonical list, or None.

    Raises `Unreadable` rather than guessing on any shape other than array or
    null -- this field is new and has no legacy spellings to accommodate.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        raise Unreadable(
            "minifig_analysis must be an array or null, got %s: %r"
            % (type(value).__name__, value))
    if not value:
        # [] is the same answer as null -- no identification ran.
        return None
    return [normalize_entry(entry) for entry in value] or None


def entries(record: dict) -> list[dict]:
    """The per-figure groups on a record, normalizing on read."""
    try:
        return normalize(record.get("minifig_analysis")) or []
    except Unreadable:
        # A malformed stored artifact must not take down display/scoring of
        # unrelated rows; callers that need strictness validate first via
        # ledger validate --strict. Re-raise context for callers that care.
        raise


def identified_entries(analysis: list[dict]) -> list[dict]:
    """Entries whose verification resolved to a verified identity."""
    return [e for e in analysis
            if isinstance(e, dict)
            and (e.get("verification") or {}).get("status") == "verified"]


def unknown_entries(analysis: list[dict]) -> list[dict]:
    """Entries left unknown/unverifiable -- still visible, never valued."""
    return [e for e in analysis
            if isinstance(e, dict)
            and (e.get("verification") or {}).get("status")
            in ("unknown", "unverifiable")]


def figure_count(analysis: list[dict]) -> int | None:
    """Sum of entry quantities. Returns None when quantities are unreadable;
    raises Unreadable only when an entry is structurally malformed."""
    total = 0
    for e in analysis:
        q = e.get("quantity")
        if q is None:
            continue
        if not _is_number(q) or q != int(q) or q < 1:
            raise Unreadable(
                "quantity must be a positive integer, got %r" % (q,))
        total += int(q)
    return total or None


def priced_subtotal(analysis: list[dict]) -> float:
    """Sum of numeric extended_values. Unpriced entries contribute ZERO, never
    an estimate -- the conservative floor policy."""
    total = 0.0
    for e in analysis:
        v = e.get("extended_value")
        if _is_finite(v):
            total += float(v)
    return total


def sold_count(analysis: list[dict]):
    """The MAXIMUM per-entry used.price_detail_count -- never the sum.

    Summing different identities would present several distinct markets as
    one deeper evidence pool. Depth is the deepest single identity's market.
    """
    counts = []
    for e in analysis:
        used = e.get("used")
        count = used.get("price_detail_count") if isinstance(used, dict) else None
        if _is_number(count):
            counts.append(count)
    return max(counts) if counts else None


def crop_refs(analysis: list[dict]) -> list[str]:
    """Representative crop refs in entry order."""
    out = []
    for e in analysis:
        rep = e.get("representative_crop_ref")
        if isinstance(rep, str) and rep:
            out.append(rep)
    return out
