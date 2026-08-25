"""Contract between legoscout-classifier's hand-off and legoscout-appraiser's input,
and the one step further downstream where that hand-off actually gets consumed:
the orchestrator's comps validation and synthesis build.

legoscout-classifier.md documents that a `set` candidate whose set number was
never identified (text and vision both exhausted) hands off NO `set_numbers`
field at all -- never an empty list -- so legoscout-appraiser.md can tell
"never identified" apart from "zero sets to price" and skip the CLI call
rather than call `legoscout pricing comps` with zero `--set-no` flags. A
2026-08-20 review found that failure mode undocumented in both agent files
and reproduced it live: `legoscout pricing comps --condition N --description
"test"` (zero `--set-no`) exits 1. These tests pin that CLI-level rejection
and the `listing_category` schema field both agent files depend on for mode
selection, so a change to either breaks a test instead of only being
discovered live mid-run.

A follow-up review the same day traced the fix one hop further: the
classifier/appraiser prose fix (write a `blocked: true` comps result instead
of calling the CLI) had no shape `legoscout_cli.orchestrator.validate_comps_result`
would accept, so ONE blocked candidate in a batch of 25 failed the whole
batch's `synthesis_coverage` check with a key-mismatch error, never reaching
the per-candidate `build_errors` path every other malformed appraisal gets.
`test_orchestrator_accepts_a_blocked_comps_result_without_failing_the_whole_batch`
pins the fix: `validate_comps_result`/`_apply_comps` now treat `blocked: true`
as a real, scoreable "stays unpriced" outcome. `test_build_record_comps.py`
covers `_apply_comps`'s side of the same fix directly.

A second follow-up review the same day found the *fix itself* only widened
the batch-level gate to accept exactly one new shape: any OTHER malformed
comps entry (a typo, a wrong mode, a missing key) still failed the WHOLE
batch, reproducing the original symptom via a different trigger. It also
found `validate_comps_result` never cross-checked a comps result's `mode`
against the candidate's own `listing_category` -- a bulk-shaped comps result
handed to a SET candidate (or the reverse) passed validation cleanly and
`_apply_comps` then silently no-opped instead of raising, writing a
materially wrong `ebay_avg_sold_price` onto a SET record with
`profit_incomplete` left unset. `validate_comps_result` moved out of
`validate_comps_batch`'s up-front loop (which now checks key coverage only)
and into `synthesis_coverage`'s per-candidate try/except -- one candidate's
bad shape is now that candidate's own `build_errors` entry, not a batch
failure -- and gained an `expected_category` parameter for the mode
cross-check. `test_run_manifest_comps.py`'s
`test_one_malformed_comps_entry_does_not_block_a_sibling_candidate` and
`test_comps_mode_mismatched_with_listing_category_is_rejected` cover both
through the full `build_run_manifest` path; the two tests below cover the
same fixes directly against `validate_comps_result`.

A third follow-up review the same day found the `expected_category`
cross-check's `is not None` guard conflated two different states: a
legitimately `blocked` comps result (no `mode` to compare, correctly exempt)
and an appraisal record that simply never set `listing_category` at all
(also resolves to `expected_category=None`, gets the same exemption it
should not get). The missing field then surfaced three call-frames
downstream as a confusing `score_record` enum error over the phantom
`"unknown"` sentinel `build_record._typed_default` fills in, never naming
the actual defect. `validate_appraisal_result` now requires
`listing_category` to be `"bulk"` or `"set"` -- catching the classifier
hand-off defect at the gate built for exactly this, before
`synthesis_coverage` ever computes `expected_category`.
`test_appraisal_result_requires_listing_category` pins it.

A fourth follow-up review the same day found a repeated `set_no` within one
`sets[]` array silently double-counts that set's resale value: `_apply_comps`
divides `estimated_total` by `len(sets)` to allocate landed cost per entry,
but sums each entry's FULL comp into the record total -- a duplicate entry
for the same set is credited its whole resale value again against only a
fractional cost share, inflating `potential_profit` (demonstrated: an
85-dollar, 3.4x inflation from one repeated set number, reproduced through
the real `legoscout pricing comps` CLI end-to-end). Fixed at both the CLI
surface the appraiser actually calls (`comps.set_comps` rejects a repeated
`set_no`) and as defense in depth at the orchestrator gate
(`validate_comps_result` rejects a duplicate `set_no` inside `sets[]`, the
same way `_duplicates()` already guards duplicate `listing_key`s at the
batch level). `test_set_comps_rejects_duplicate_set_numbers` and
`test_validate_comps_result_rejects_duplicate_set_no_in_sets` pin both.

A fifth follow-up review the same day found the fourth's fix incomplete: both
guards sat on the CLI generator and `synthesis_coverage`'s dry-proof path,
neither of which the orchestrator's own SKILL.md documents as the real
production call -- `build_deal_record(candidate, appraisal, comps=...)`,
called directly, never imports or calls `validate_comps_result`. A comps
result assembled some other way (e.g. an appraiser concatenating two
`legoscout pricing comps` calls' `sets[]` arrays for one candidate on a
retry) reached `build_deal_record` and the one mandated pre-ledger-write gate
(`legoscout deals validate --strict`) with zero errors, at a demonstrated
4.22x profit inflation. `build_deal_record` now calls `validate_comps_result`
unconditionally whenever `comps` is not `None`, before doing anything else --
the guard travels with the computation regardless of caller.
`legoscout_cli.ledger.validate.check()` (the actual `--strict` gate) also
gained an independent `set_analysis` duplicate-`set_no` check, so a record
that reaches the ledger some other way is still caught before writing.
`test_build_deal_record_rejects_duplicate_set_no_in_comps` and
`test_ledger_validate_rejects_duplicate_set_no_in_set_analysis` pin both.

A sixth follow-up review the same day found the fifth's fix STILL incomplete:
`build_deal_record`'s guard only protects callers that go through it.
`legoscout_cli.ledger.db.save()`/`upsert_deals()` -- the actual persistence
functions every OTHER writer (`rescore.py`, `ledger/sweep.py`,
`invalidate/sweep.py`) calls directly, bypassing `build_deal_record`
entirely -- ran only `deal_schema.validate()` (shape/type only, no
uniqueness rule) before writing. The review found 10 rows already
persisted in the live ledger with this exact defect (5 active, up to 8x
profit inflation on one row) that no code path had ever caught. The
duplicate-set_no check was factored into one shared function,
`legoscout_cli.ledger.schema.duplicate_set_analysis_set_numbers()`, so
`validate.py`'s `--strict` audit and `db.py`'s write-time gate cannot drift
from each other the way the original three separate copies of "never buy,
bid, message..." did earlier this same day. `db._validate_deals()` (the one
function `save()` and `upsert_deals()` both actually call) now calls it
unconditionally per record, alongside the existing schema check.
`test_upsert_deals_rejects_duplicate_set_no_in_set_analysis` pins the actual
persistence-layer gate directly -- not `build_deal_record`, not
`validate.check()`, but the function every writer in the codebase funnels
through.
"""
from __future__ import annotations

import sqlite3

import pytest
from typer.testing import CliRunner

import legoscout_cli.orchestrator as orchestrator
from legoscout_cli.ledger import build_record, db as ledger_db, schema as deal_schema, validate as ledger_validate
from legoscout_cli.main import app
from legoscout_cli.orchestrator import (
    AppraisalBatchKeyError,
    synthesis_coverage,
    validate_appraisal_result,
    validate_comps_result,
)
from legoscout_cli.pricing import comps


def test_comps_command_rejects_zero_set_no_flags():
    runner = CliRunner()
    result = runner.invoke(
        app, ["pricing", "comps", "--condition", "N", "--description", "test"]
    )
    assert result.exit_code != 0
    assert "--set-no" in result.output


def test_set_comps_rejects_empty_set_numbers_list_directly():
    with pytest.raises(ValueError, match="non-empty list"):
        comps.set_comps([], "N")


def test_set_comps_rejects_duplicate_set_numbers():
    # A 2026-08-20 review demonstrated a repeated set_no double-counting its
    # resale value against a single fractional cost allocation (85-dollar,
    # 3.4x profit inflation) -- _apply_comps divides landed cost by
    # len(sets) but sums each entry's full comp, so this must never reach it.
    with pytest.raises(ValueError, match="duplicate entries"):
        comps.set_comps(["75192", "75192"], "N")


def test_validate_comps_result_rejects_duplicate_set_no_in_sets():
    bad = {"listing_key": "x|1", "mode": "set",
           "sets": [{"set_no": "75192", "bricklink": None, "ebay": None},
                    {"set_no": "75192", "bricklink": None, "ebay": None}]}
    with pytest.raises(AppraisalBatchKeyError, match="duplicate set_no"):
        validate_comps_result(bad)


def test_appraisal_schema_declares_listing_category():
    assert "listing_category" in deal_schema.fields_for_phase("appraisal")


def test_validate_comps_result_accepts_blocked_shape_with_a_blocker():
    validate_comps_result({"listing_key": "x|1", "mode": "set",
                            "blocked": True, "blocker": "no set # in listing"})


def test_validate_comps_result_rejects_blocked_with_no_blocker():
    with pytest.raises(AppraisalBatchKeyError, match="no non-empty blocker"):
        validate_comps_result({"listing_key": "x|1", "blocked": True})


def test_validate_comps_result_rejects_mode_mismatched_with_expected_category():
    bulk_shaped = {"listing_key": "x|1", "mode": "bulk", "bricklink": None,
                   "ebay": {"available": True, "avg_sold_price": 40.0}}
    with pytest.raises(AppraisalBatchKeyError, match="listing_category"):
        validate_comps_result(bulk_shaped, expected_category="set")


def test_validate_comps_result_blocked_is_exempt_from_category_cross_check():
    # A blocked record has no set/bulk pricing shape to mismatch -- the
    # cross-check only applies to a real, non-blocked comps result.
    validate_comps_result({"listing_key": "x|1", "blocked": True, "blocker": "no set # in listing"},
                          expected_category="set")


def _candidate(key, listing_category):
    return {"listing_key": key, "source": key.split("|", 1)[0],
            "listing_type": "fixed", "price_basis": "current_price",
            "current_price": 25.0, "available_fulfillment": ["shipping"],
            "status": "active", "fee_breakdown": {"hammer": 25.0},
            "listing_category": listing_category}


def _appraisal(key, listing_category):
    return {"listing_key": key, "listing_category": listing_category,
            "estimated_total": 300.0,
            "observations": {"model_score": 50, "model_rationale": "fixture"}}


def test_orchestrator_accepts_a_blocked_comps_result_without_failing_the_whole_batch():
    # One priceable bulk candidate and one classifier-unidentified set
    # candidate in the same batch -- the bug this pins: a single blocked
    # entry used to fail validate_comps_batch for BOTH candidates, before
    # synthesis_coverage's per-candidate build loop ever ran.
    source_candidates = [_candidate("ebay|1", "bulk"), _candidate("ebay|2", "set")]
    appraisal_results = [_appraisal("ebay|1", "bulk"), _appraisal("ebay|2", "set")]
    comps_results = [
        {"listing_key": "ebay|1", "mode": "bulk", "bricklink": None,
         "ebay": {"available": False, "reason": "ebay_auth_required"}},
        {"listing_key": "ebay|2", "mode": "set", "blocked": True,
         "blocker": "no set # in listing after text+vision"},
    ]

    report = synthesis_coverage(source_candidates, appraisal_results, comps_results)

    assert report["complete"] is True, report
    assert report["buildable_count"] == 2
    assert report["build_errors"] == []


def test_orchestrator_one_malformed_comps_entry_does_not_block_a_sibling_candidate():
    # A malformed shape (not the blessed `blocked` shape) for ONE candidate
    # must surface as that candidate's own build_errors entry, not fail the
    # whole batch -- the bug this pins: validate_comps_result used to run
    # eagerly over every entry inside validate_comps_batch, so one bad entry
    # raised before synthesis_coverage's per-candidate build loop ever ran.
    source_candidates = [_candidate("ebay|1", "bulk"), _candidate("ebay|2", "set")]
    appraisal_results = [_appraisal("ebay|1", "bulk"), _appraisal("ebay|2", "set")]
    comps_results = [
        {"listing_key": "ebay|1", "mode": "bulk", "bricklink": None,
         "ebay": {"available": False, "reason": "ebay_auth_required"}},
        {"listing_key": "ebay|2", "mode": "set"},  # missing 'sets' -- malformed, not blocked
    ]

    report = synthesis_coverage(source_candidates, appraisal_results, comps_results)

    assert report["complete"] is False
    assert report["buildable_count"] == 1
    assert len(report["build_errors"]) == 1
    assert report["build_errors"][0]["listing_key"] == "ebay|2"


def test_minifigure_handoff_uses_identification_not_comps():
    with pytest.raises(AppraisalBatchKeyError, match="must be 'set', 'bulk'"):
        validate_comps_result({
            "listing_key": "ebay|1",
            "mode": "minifigure",
            "bricklink": None,
            "ebay": {"available": True},
        })
    orchestrator.validate_identification_result({
        "listing_key": "ebay|1",
        "blocked": True,
        "blocker": "no detector crops",
        "minifig_analysis": None,
        "figure_count": None,
        "figure_count_source": None,
        "identified_count": 0,
        "unknown_count": 0,
        "priced_subtotal": 0.0,
        "sold_count": None,
        "pricing_complete": False,
        "status": "blocked",
    })


def test_appraisal_result_requires_listing_category():
    # A missing listing_category used to resolve expected_category=None in
    # synthesis_coverage, the SAME exemption a legitimately blocked comps
    # result gets -- silently skipping the mode cross-check instead of
    # failing here, at the gate built for exactly this classifier-hand-off
    # defect, with a message naming the actual field.
    record = {"listing_key": "ebay|1",
              "observations": {"model_score": 50, "model_rationale": "fixture"}}
    with pytest.raises(AppraisalBatchKeyError, match="listing_category"):
        validate_appraisal_result(record)


def test_appraisal_result_rejects_invalid_listing_category():
    record = {"listing_key": "ebay|1", "listing_category": "unknown",
              "observations": {"model_score": 50, "model_rationale": "fixture"}}
    with pytest.raises(AppraisalBatchKeyError, match="listing_category"):
        validate_appraisal_result(record)


def _bricklink_found(set_no="75192-1", avg_price=500.0, count=10):
    summary = {"condition": "U", "guide_type": "sold", "sold_window": "x",
              "six_month_avg_sold_price": avg_price, "avg_price": avg_price,
              "price_detail_count": count}
    return {"set_no": set_no, "lookup_status": "found",
           "catalog": {"no": set_no, "name": "Millennium Falcon"},
           "condition": "U", "purchase_price": None, "fee_rate": None,
           "used": summary, "new": None, "selected_condition_summary": summary,
           "selected_condition_priced": True, "potential_profit": None}


def test_build_deal_record_rejects_duplicate_set_no_in_comps():
    # The production path itself: the orchestrator's own SKILL.md instructs
    # calling build_deal_record(candidate, appraisal, comps=...) directly --
    # not through synthesis_coverage's dry-proof path. A comps result
    # assembled some other way (e.g. two `legoscout pricing comps` calls'
    # sets[] arrays concatenated for one candidate) must be caught HERE.
    candidate = {"listing_key": "ebay|1", "source": "ebay", "listing_type": "fixed",
                "price_basis": "current_price", "current_price": 25.0,
                "available_fulfillment": ["shipping"], "status": "active",
                "fee_breakdown": {"hammer": 25.0}}
    appraisal = {"listing_key": "ebay|1", "listing_category": "set",
                "estimated_total": 300.0,
                "observations": {"model_score": 50, "model_rationale": "fixture"}}
    entry = {"set_no": "75192-1", "bricklink": _bricklink_found(),
            "ebay": {"available": False, "reason": "ebay_auth_required"}}
    comps = {"mode": "set", "sets": [entry, entry]}

    with pytest.raises(AppraisalBatchKeyError, match="duplicate set_no"):
        build_record.build_deal_record(
            candidate, appraisal, first_seen_at="2026-08-20T00:00:00Z",
            last_seen_at="2026-08-20T00:00:00Z", comps=comps, fee_rate=0.13)


def test_ledger_validate_rejects_duplicate_set_no_in_set_analysis():
    # Defense in depth at legoscout deals validate --strict, the one gate
    # that runs on the record itself regardless of how it was assembled.
    record = {
        "listing_key": "ebay|1", "source": "ebay", "status": "active",
        "listing_type": "fixed", "price_basis": "static_price",
        "static_price": 25.0, "available_fulfillment": ["shipping"],
        "item_location": "Indiana", "pickup_miles": None,
        "fee_breakdown": {"hammer": 25.0, "shipping_handling": 5.0},
        "set_analysis": [{"set_no": "75192-1", "potential_profit": 135.0},
                         {"set_no": "75192-1", "potential_profit": 135.0}],
    }

    _, errors, _ = ledger_validate.check(record)

    assert any("duplicate set_no" in e for e in errors), errors


def test_upsert_deals_rejects_duplicate_set_no_in_set_analysis(tmp_path):
    # The actual persistence-layer gate: every writer in the codebase
    # (build_deal_record, rescore, ledger/sweep, invalidate/sweep) calls
    # save()/upsert_deals() to reach storage, so THIS is the one place a
    # check cannot be bypassed by skipping build_deal_record. A 2026-08-20
    # review found this gate ran only deal_schema.validate() (shape/type,
    # no uniqueness rule) and found 10 rows already persisted in the live
    # ledger with this exact defect as a result.
    path = str(tmp_path / "scratch.db")
    conn = sqlite3.connect(path)
    conn.executescript(ledger_db._schema_sql())
    conn.commit()
    conn.close()

    record = {
        "listing_key": "ebay|dup-test-1", "source": "ebay", "status": "active",
        "listing_type": "fixed", "price_basis": "static_price",
        "static_price": 25.0, "available_fulfillment": ["shipping"],
        "fee_breakdown": {"hammer": 25.0},
        "set_analysis": [{"set_no": "75192", "potential_profit": 285.0},
                         {"set_no": "75192", "potential_profit": 285.0}],
        "potential_profit": 570.0,
    }

    with pytest.raises(deal_schema.Invalid, match="duplicate set_no"):
        ledger_db.upsert_deals([record], path=path)
