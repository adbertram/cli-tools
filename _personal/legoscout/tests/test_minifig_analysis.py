"""`minifig_analysis`: the canonical per-figure evidence behind a minifig row.

Mirror of `set_analysis.py` for the identifier pipeline: ONE reader and
normalizer of the nested per-figure artifact the identifier produces. The
producer chain is `legoscout minifig detect` -> `identify` -> agent
verification -> `price`; the stored shape is an ARRAY of per-figure group
objects, or null when no identification ran (legacy rows).

Read it only through this module -- `entries()`, `figure_count()`,
`priced_subtotal()`, `sold_count()`, `crop_refs()`, `normalize()` -- the same
way `set_analysis.py` owns its field. Nothing else in the pipeline may decide
what shape it is looking at.

Contract covered here:
- the locked fourteen-key `ENTRY_FIELDS` tuple, present on EVERY entry;
- unmapped provenance preserved verbatim, never dropped to tidy the shape;
- protocol-relative BrickLink image URLs normalized to https;
- idempotence: normalizing a normalized entry changes nothing;
- `Unreadable` on malformed nested artifacts instead of silent zero totals;
- the canonical cross-field invariant validator (sole owner per the plan's
  Validation-ownership section) -- `ledger/validate.py` calls it and adds only
  record-level rules;
- cents math rounds exactly once and is idempotent.
"""
from __future__ import annotations

import math

import pytest

from legoscout_cli.ledger import minifig_analysis as mfa


def _verified(**overrides):
    """One fully-priced verified group in the producer's shape."""
    entry = {
        "match_group_id": "g1",
        "detections": [
            {"crop_ref": "abc123#0", "confidence": 0.94},
            {"crop_ref": "def456#0", "confidence": 0.88},
        ],
        "representative_crop_ref": "abc123#0",
        "brickognize_candidates": [
            {"item_no": "sw0001a", "similarity": 0.91},
            {"item_no": "sw0217", "similarity": 0.74},
        ],
        "verification": {
            "status": "verified",
            "catalog_checked_at": "2026-08-25T12:00:00Z",
        },
        "fig_no": "sw0001a",
        "catalog": {
            "no": "sw0001a",
            "name": "Luke Skywalker",
            "thumbnail_url": "//img.bricklink.com/M/sw0001a.jpg",
        },
        "quantity": 2,
        "condition_notes": "minor play wear",
        "used": {"avg_price": 12.34, "price_detail_count": 7},
        "unit_value": 12.34,
        "extended_value": 24.68,
        "null_value_reason": None,
        "errors": None,
    }
    entry.update(overrides)
    return entry


def _unknown(**overrides):
    entry = _verified(**{
        "verification": {"status": "unknown"},
        "fig_no": None,
        "catalog": None,
        "used": None,
        "unit_value": None,
        "extended_value": None,
        "null_value_reason": "no usable Brickognize candidates",
        **overrides,
    })
    return entry


# --- the locked entry tuple --------------------------------------------------


def test_entry_fields_are_exactly_the_locked_tuple():
    assert mfa.ENTRY_FIELDS == (
        "match_group_id", "detections", "representative_crop_ref",
        "brickognize_candidates", "verification", "fig_no", "catalog",
        "quantity", "condition_notes", "used", "unit_value",
        "extended_value", "null_value_reason", "errors",
    )


# --- normalize_entry ---------------------------------------------------------


def test_every_canonical_key_is_present_after_normalize():
    out = mfa.normalize_entry(_verified())
    for field in mfa.ENTRY_FIELDS:
        assert field in out


def test_unmapped_keys_are_preserved_verbatim():
    raw = _verified(some_future_producer_key={"nested": 1})
    out = mfa.normalize_entry(raw)
    assert out["some_future_producer_key"] == {"nested": 1}


def test_normalize_is_idempotent():
    once = mfa.normalize_entry(_verified())
    twice = mfa.normalize_entry(once)
    assert once == twice


def test_protocol_relative_catalog_urls_become_https():
    out = mfa.normalize_entry(_verified())
    assert out["catalog"]["thumbnail_url"] == \
        "https://img.bricklink.com/M/sw0001a.jpg"


def test_non_dict_entry_raises_unreadable():
    with pytest.raises(mfa.Unreadable):
        mfa.normalize_entry("sw0001a")


def test_detections_not_a_list_raises_unreadable():
    with pytest.raises(mfa.Unreadable):
        mfa.normalize_entry(_verified(detections="two boxes"))


def test_detection_without_crop_ref_raises_unreadable():
    with pytest.raises(mfa.Unreadable):
        mfa.normalize_entry(_verified(detections=[{"confidence": 0.9}]))


def test_boolean_quantity_raises_unreadable():
    with pytest.raises(mfa.Unreadable):
        mfa.normalize_entry(_verified(quantity=True))


def test_zero_quantity_raises_unreadable():
    with pytest.raises(mfa.Unreadable):
        mfa.normalize_entry(_verified(quantity=0))


def test_nan_unit_value_raises_unreadable():
    with pytest.raises(mfa.Unreadable):
        mfa.normalize_entry(_verified(unit_value=float("nan")))


def test_negative_unit_value_raises_unreadable():
    with pytest.raises(mfa.Unreadable):
        mfa.normalize_entry(_verified(unit_value=-0.01))


# --- normalize (top level) ---------------------------------------------------


def test_none_and_empty_both_mean_no_analysis():
    assert mfa.normalize(None) is None
    assert mfa.normalize([]) is None


def test_top_level_object_shape_raises_instead_of_guessing():
    # set_analysis grew five historical top-level spellings because readers
    # guessed. This field is new: the only legal shapes are array and null.
    with pytest.raises(mfa.Unreadable):
        mfa.normalize({"g1": _verified()})


def test_scalar_top_level_raises():
    with pytest.raises(mfa.Unreadable):
        mfa.normalize("nope")


# --- helpers -----------------------------------------------------------------


def test_entries_reads_from_record():
    record = {"minifig_analysis": [_verified(), _unknown()]}
    out = mfa.entries(record)
    assert [e["match_group_id"] for e in out] == ["g1", "g1"]


def test_entries_on_legacy_record_without_analysis_is_empty():
    assert mfa.entries({"minifig_analysis": None}) == []
    assert mfa.entries({}) == []


def test_figure_count_sums_quantities():
    analysis = [_verified(quantity=2), _verified(quantity=3)]
    assert mfa.figure_count(analysis) == 5


def test_priced_subtotal_sums_numeric_extended_only():
    analysis = [_verified(extended_value=24.68), _unknown()]
    assert mfa.priced_subtotal(analysis) == 24.68


def test_sold_count_is_max_not_sum():
    # Summing different identities would present several markets as one
    # deeper evidence pool. Depth is the deepest single identity's market.
    analysis = [
        _verified(),
        _verified(fig_no="sw0217", used={"avg_price": 4.0, "price_detail_count": 31}),
    ]
    assert mfa.sold_count(analysis) == 31


def test_sold_count_without_any_sales_is_none():
    assert mfa.sold_count([_unknown()]) is None


def test_crop_refs_preserve_order():
    analysis = [
        _verified(representative_crop_ref="abc123#0"),
        _unknown(representative_crop_ref="fff000#1"),
    ]
    assert mfa.crop_refs(analysis) == ["abc123#0", "fff000#1"]


def test_identified_split_by_verification_status():
    analysis = [_verified(), _unknown()]
    assert len(mfa.identified_entries(analysis)) == 1
    assert len(mfa.unknown_entries(analysis)) == 1


def test_helper_raises_unreadable_on_malformed_artifact_not_zero_total():
    # A silent zero here would make a broken lot look like an empty lot.
    with pytest.raises(mfa.Unreadable):
        mfa.figure_count([_verified(quantity="three")])


# --- cents math --------------------------------------------------------------


def test_extended_value_must_match_unit_times_quantity_within_a_cent():
    out = mfa.normalize_entry(_verified(extended_value=25.00))
    assert any("extended_value" in e for e in mfa.entry_errors(out))


def test_extended_value_consistent_with_rounded_unit_times_quantity_is_clean():
    assert mfa.entry_errors(mfa.normalize_entry(_verified())) == []


def test_stored_values_are_never_mutated_by_re_normalization():
    # Rounding happens exactly once, at production, through round_cents().
    # Re-normalizing a stored row must not drift a stored cent.
    out = mfa.normalize_entry(_verified())
    again = mfa.normalize_entry(out)
    assert again == out


def test_round_cents_is_half_up_and_idempotent():
    assert mfa.round_cents(37.035) == 37.04
    assert mfa.round_cents(mfa.round_cents(37.035)) == 37.04


# --- canonical entry invariants (the sole owner) -----------------------------


def test_clean_verified_entry_has_no_errors():
    assert mfa.entry_errors(mfa.normalize_entry(_verified())) == []


def test_clean_unknown_entry_has_no_errors():
    assert mfa.entry_errors(mfa.normalize_entry(_unknown())) == []


def test_verified_requires_fig_no_matching_catalog_number():
    out = mfa.normalize_entry(_verified(fig_no="sw0001a"))
    out["catalog"]["no"] = "sw0217"
    errors = mfa.entry_errors(out)
    assert len(errors) == 1 and "fig_no" in errors[0]


def test_verified_without_fig_no_errors():
    out = mfa.normalize_entry(_verified(fig_no=None))
    assert any("fig_no" in e for e in mfa.entry_errors(out))


def test_unknown_must_not_carry_priced_identity_fields():
    out = mfa.normalize_entry(_unknown(fig_no="sw0001a"))
    assert any("unknown" in e for e in mfa.entry_errors(out))
    out = mfa.normalize_entry(_unknown(catalog={"no": "sw0001a"}))
    assert any("unknown" in e for e in mfa.entry_errors(out))


def test_null_value_reason_demands_null_extended_value():
    out = mfa.normalize_entry(_unknown(null_value_reason="why"))
    out["extended_value"] = 5.0
    assert any("null_value_reason" in e for e in mfa.entry_errors(out))


def test_verified_without_value_needs_reason_or_errors():
    out = mfa.normalize_entry(_verified(unit_value=None, extended_value=None,
                                        null_value_reason=None))
    assert any("without a value" in e for e in mfa.entry_errors(out))
    out = mfa.normalize_entry(_verified(unit_value=None, extended_value=None,
                                        errors=["transient lookup failure"]))
    assert mfa.entry_errors(out) == []


def test_representative_crop_ref_must_be_one_of_its_detections():
    out = mfa.normalize_entry(_verified(representative_crop_ref="nope#9"))
    assert any("representative_crop_ref" in e for e in mfa.entry_errors(out))


def test_batch_flags_duplicate_match_group_ids():
    analysis = [_verified(match_group_id="g1"),
                _verified(match_group_id="g1", fig_no="sw0217")]
    assert len(mfa.batch_errors(analysis)) == 1


def test_batch_flags_duplicate_crop_ids_within_an_entry():
    out = mfa.normalize_entry(_verified(
        detections=[{"crop_ref": "same#0", "confidence": 0.9},
                    {"crop_ref": "same#0", "confidence": 0.8}]))
    assert any("crop_ref" in e for e in mfa.entry_errors(out))


def test_batch_with_unique_ids_is_clean():
    analysis = [_verified(match_group_id="g1"),
                _verified(match_group_id="g2", fig_no="sw0217")]
    assert mfa.batch_errors(analysis) == []


def test_normalize_propagates_unreadable_from_bad_nested_entry():
    with pytest.raises(mfa.Unreadable):
        mfa.normalize([_verified(), {"quantity": True}])
