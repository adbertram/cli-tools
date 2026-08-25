"""`legoscout pricing comps-batch`: the whole appraiser batch in ONE process.

Covers the three contracts the appraiser relies on:
  * hand-off parsing rejects envelopes, keyless rows, and duplicate keys loudly;
  * every candidate gets exactly one result, priced by the SAME functions the
    single-candidate `pricing comps` command calls, in INPUT ORDER;
  * candidates price CONCURRENTLY (a serial loop cannot release a Barrier that
    requires every worker to arrive), one candidate's failure never fails the
    batch, and the batch reports honest wall vs serial-equivalent timing.
"""
from __future__ import annotations

import json
import threading

import pytest

from legoscout_cli.pricing import comps_batch


# --------------------------------------------------------------------------
# Hand-off parsing.
# --------------------------------------------------------------------------

def test_parse_handoff_accepts_a_well_formed_array(tmp_path):
    path = tmp_path / "handoff.json"
    path.write_text(json.dumps([
        {"listing_key": "ebay|1", "listing_category": "bulk",
         "description": "lego bulk lot", "dollars_per_lb": 3.0},
        {"listing_key": "shopgoodwill|2", "listing_category": "set",
         "set_numbers": ["75192"], "condition": "U", "description": "Falcon"},
    ]), encoding="utf-8")
    parsed = comps_batch.parse_handoff(str(path))
    assert [entry["listing_key"] for entry in parsed] == ["ebay|1", "shopgoodwill|2"]


def test_parse_handoff_rejects_an_object_envelope(tmp_path):
    path = tmp_path / "envelope.json"
    path.write_text(json.dumps({"candidate_records": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="root must be an array"):
        comps_batch.parse_handoff(str(path))


def test_parse_handoff_names_the_row_missing_its_key(tmp_path):
    path = tmp_path / "keyless.json"
    path.write_text(json.dumps([{"listing_category": "bulk"}]), encoding="utf-8")
    with pytest.raises(ValueError, match=r"hand-off\[0\] has no non-empty listing_key"):
        comps_batch.parse_handoff(str(path))


def test_parse_handoff_rejects_duplicate_keys(tmp_path):
    path = tmp_path / "dupes.json"
    path.write_text(json.dumps([
        {"listing_key": "ebay|1", "listing_category": "bulk", "description": "x"},
        {"listing_key": "ebay|1", "listing_category": "bulk", "description": "y"},
    ]), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate listing_key"):
        comps_batch.parse_handoff(str(path))


def test_parse_handoff_reports_an_unreadable_file(tmp_path):
    with pytest.raises(ValueError, match="not readable"):
        comps_batch.parse_handoff(str(tmp_path / "absent.json"))


# --------------------------------------------------------------------------
# One candidate, one result: the same functions `pricing comps` calls.
# --------------------------------------------------------------------------

@pytest.fixture()
def fake_comps(monkeypatch):
    """Replace the two comps entry points; record how each was called."""
    calls = []

    def set_comps(set_numbers, condition, description=None, limit=50):
        calls.append(("set", list(set_numbers), condition, description, limit))
        return {
            "mode": "set", "condition": condition,
            "sets": [{"set_no": n, "bricklink": {}, "ebay": {}}
                     for n in set_numbers],
        }

    def bulk_comps(description, dollars_per_lb=None, limit=50):
        calls.append(("bulk", description, dollars_per_lb, limit))
        return {"mode": "bulk", "bricklink": None, "ebay": {"available": True}}

    monkeypatch.setattr(comps_batch.comps_module, "set_comps", set_comps)
    monkeypatch.setattr(comps_batch.comps_module, "bulk_comps", bulk_comps)
    return calls


def test_set_candidate_calls_set_comps_once_with_every_set_number(fake_comps):
    result = comps_batch.price_one(
        {"listing_key": "k1", "listing_category": "set",
         "set_numbers": ["75192", "6868"], "condition": "U",
         "description": "two sets"}, limit=25)
    assert fake_comps == [("set", ["75192", "6868"], "U", "two sets", 25)]
    assert result["mode"] == "set"
    assert result["listing_key"] == "k1"
    assert len(result["sets"]) == 2
    assert "blocked" not in result


def test_bulk_candidate_passes_dollars_per_lb_through(fake_comps):
    result = comps_batch.price_one(
        {"listing_key": "k2", "listing_category": "bulk",
         "description": "lego bulk lot 4 lbs", "dollars_per_lb": 2.5}, limit=50)
    assert fake_comps == [("bulk", "lego bulk lot 4 lbs", 2.5, 50)]
    assert result["mode"] == "bulk"
    assert result["listing_key"] == "k2"


def test_set_candidate_without_set_numbers_is_blocked_not_failed(fake_comps):
    result = comps_batch.price_one(
        {"listing_key": "k3", "listing_category": "set"}, limit=50)
    assert result == {
        "listing_key": "k3", "mode": "set", "blocked": True,
        "blocker": ("classifier handed off no set_numbers -- the candidate "
                    "was never identified"),
    }
    assert fake_comps == []


def test_minifigure_candidate_is_not_dispatched_by_comps_batch(fake_comps):
    result = comps_batch.price_one({
        "listing_key": "k-mf",
        "listing_category": "minifigure",
        "description": "star wars lot",
    }, limit=50)
    assert result == {
        "listing_key": "k-mf",
        "mode": "minifigure",
        "blocked": True,
        "blocker": (
            "minifigure pricing moved to legoscout minifig detect|identify|price"
        ),
    }
    assert fake_comps == []


def test_unknown_listing_category_is_never_guessed(fake_comps):
    result = comps_batch.price_one(
        {"listing_key": "k4", "listing_category": "minifig"}, limit=50)
    assert result["blocked"] is True
    assert "never guess the mode" in result["blocker"]
    assert fake_comps == []


def test_bad_condition_is_blocked_before_any_lookup(fake_comps):
    result = comps_batch.price_one(
        {"listing_key": "k5", "listing_category": "set",
         "set_numbers": ["75192"], "condition": "used"}, limit=50)
    assert result["blocked"] is True
    assert "condition must be 'N' or 'U'" in result["blocker"]
    assert fake_comps == []


def test_bulk_without_description_is_blocked(fake_comps):
    result = comps_batch.price_one(
        {"listing_key": "k6", "listing_category": "bulk"}, limit=50)
    assert result["blocked"] is True
    assert "--description is required" in result["blocker"]
    assert fake_comps == []


def test_one_candidates_failure_does_not_fail_its_sibling(fake_comps, monkeypatch):
    """The old serial loop died mid-batch and lost the rest of its work; a
    per-candidate defect now becomes that candidate's own blocked result."""
    def broken_bulk(description, dollars_per_lb=None, limit=50):
        raise RuntimeError("ebay subprocess exploded")

    working_bulk = comps_batch.comps_module.bulk_comps
    monkeypatch.setattr(comps_batch.comps_module, "bulk_comps", broken_bulk)
    failed = comps_batch.price_one(
        {"listing_key": "bad", "listing_category": "bulk",
         "description": "lego bulk lot"}, limit=50)
    monkeypatch.setattr(comps_batch.comps_module, "bulk_comps", working_bulk)
    good = comps_batch.price_one(
        {"listing_key": "good", "listing_category": "bulk",
         "description": "lego bulk lot"}, limit=50)
    assert failed["blocked"] is True
    assert "RuntimeError: ebay subprocess exploded" in failed["blocker"]
    assert good.get("blocked") is not True
    assert good["mode"] == "bulk"
    assert good["listing_key"] == "good"


# --------------------------------------------------------------------------
# The batch: concurrent, ordered, timed.
# --------------------------------------------------------------------------

def _candidates(count):
    return [{"listing_key": "src|%02d" % i, "listing_category": "set",
             "set_numbers": ["75192"], "condition": "U"} for i in range(count)]


def test_batch_prices_concurrently_and_preserves_input_order(monkeypatch):
    """A serial loop cannot release a Barrier sized to the whole batch."""
    workers = 4
    barrier = threading.Barrier(workers, timeout=15)

    def set_comps(set_numbers, condition, description=None, limit=50):
        barrier.wait()
        return {"mode": "set", "condition": condition,
                "sets": [{"set_no": n, "bricklink": {}, "ebay": {}}
                         for n in set_numbers]}

    monkeypatch.setattr(comps_batch.comps_module, "set_comps", set_comps)
    report = comps_batch.run_batch(_candidates(workers), workers=workers, limit=50)

    assert report["timings"]["candidates"] == workers
    assert report["timings"]["blocked_count"] == 0
    assert report["timings"]["wall_seconds"] >= 0
    assert [r["listing_key"] for r in report["results"]] == \
        ["src|%02d" % i for i in range(workers)]
    assert all("blocked" not in r for r in report["results"])
    assert report["timings"]["serial_equivalent_seconds"] > 0


def test_batch_timing_aggregates_are_self_consistent(monkeypatch):
    def set_comps(set_numbers, condition, description=None, limit=50):
        return {"mode": "set", "condition": condition,
                "sets": [{"set_no": set_numbers[0], "bricklink": {}, "ebay": {}}]}

    monkeypatch.setattr(comps_batch.comps_module, "set_comps", set_comps)
    mixed = _candidates(2) + [
        {"listing_key": "src|blk", "listing_category": "bulk",
         "description": "lego bulk lot"},
        {"listing_key": "src|bad", "listing_category": "nope"},
    ]
    report = comps_batch.run_batch(mixed, workers=2, limit=50)
    timings = report["timings"]
    assert timings["candidates"] == 4
    assert timings["blocked_count"] == 1
    assert timings["serial_equivalent_seconds"] > 0
    assert timings["speedup_vs_serial"] is None or timings["speedup_vs_serial"] > 0


# --------------------------------------------------------------------------
# main(): argv -> files, with loud argument errors.
# --------------------------------------------------------------------------

def _write_input(tmp_path, entries):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return str(path)


def test_main_writes_the_full_report_and_prints_a_summary(fake_comps, tmp_path, capsys):
    src = _write_input(tmp_path, _candidates(2))
    out = str(tmp_path / "comps-1.json")
    rc = comps_batch.main(["--input", src, "--output", out])
    assert rc == 0
    written = json.loads(open(out, encoding="utf-8").read())
    assert written["mode"] == "batch"
    assert len(written["results"]) == 2
    assert "timings" in written
    summary = json.loads(capsys.readouterr().out)
    assert summary["candidates"] == 2
    assert summary["output"] == out


def test_main_rejects_zero_workers(fake_comps, tmp_path, capsys):
    src = _write_input(tmp_path, _candidates(1))
    rc = comps_batch.main(["--input", src, "--output", str(tmp_path / "o.json"),
                           "--workers", "0"])
    assert rc == 1
    assert "--workers must be >= 1" in capsys.readouterr().err


def test_main_rejects_a_malformed_input_loudly(fake_comps, tmp_path, capsys):
    src = tmp_path / "bad.json"
    src.write_text(json.dumps({"candidate_records": []}), encoding="utf-8")
    rc = comps_batch.main(["--input", str(src),
                           "--output", str(tmp_path / "o.json")])
    assert rc == 1
    assert "root must be an array" in capsys.readouterr().err
