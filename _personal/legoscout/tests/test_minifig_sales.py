"""`pricing/minifig_sales.py`: BrickLink used-sold pricing for ONE figure.

The identifier's verified `fig_no` prices through the SAME shared
`catalog price` cache as sets (`set_sales.cached_bricklink_json`); nothing
here duplicates subprocess or flock machinery.

The single-catalog-lookup rule: the identifier agent's `catalog minifig`
retrieval is THE catalog lookup. Its payload travels inside the identification
artifact; this module validates it (fig_no must match the stored record) and
invokes ONLY the price guide. Pricing never performs a second catalog fetch.

Contract covered here:
- suffix-preserving fig numbers (`sw0001a` never collapses to `sw0001`);
- exact price-guide command array;
- artifact-carried catalog payload validation;
- avg_price selection with distinct qty/units/depth evidence;
- zero-sales as a present null-valued answer, not $0 and not an exception;
- not-found vs transient failure stay distinct raised conditions;
- 7-day cache wiring, refresh bypass, one-fig failure isolation.
"""
from __future__ import annotations

import pytest

from legoscout_cli.pricing import minifig_sales, set_sales


def _catalog(no="sw0001a"):
    return {"no": no, "name": "Luke Skywalker",
            "thumbnail_url": "//img.bricklink.com/M/sw0001a.jpg"}


def _raw_prices(avg="12.34"):
    return {
        "avg_price": avg,
        "qty_avg_price": 11.90,
        "min_price": 8.0,
        "max_price": 20.0,
        "total_quantity": 34,
        "unit_quantity": 21,
        "currency_code": "USD",
        "price_detail": [{"a": 1}] * 7,
    }


def _recorder(results=None, error=None):
    calls = []

    def run(args):
        calls.append(list(args))
        if error is not None:
            raise error
        return results

    run.calls = calls
    return run


def _iso(tmp_path):
    """A per-test cache path. Unit tests must never read or write the real
    BrickLink call cache -- a warm entry would make results order-dependent
    and pollute live pricing data."""
    return str(tmp_path / "bricklink_calls.json")


# --- the command boundary ----------------------------------------------------


def test_suffix_preserving_fig_number_reaches_bricklink_verbatim(tmp_path):
    # Bare `sw0001` 404s while `sw0001a` resolves. Never normalize a fig no.
    rec = _recorder(_raw_prices())
    minifig_sales.summarize_fig(
        "sw0001a", _catalog(), runner=rec, cache_path=_iso(tmp_path))
    assert rec.calls[0][3] == "sw0001a"


def test_exact_price_guide_command_array(tmp_path):
    rec = _recorder(_raw_prices())
    minifig_sales.summarize_fig(
        "sw0001a", _catalog(), runner=rec, cache_path=_iso(tmp_path))
    assert rec.calls == [[
        "catalog", "price", "MINIFIG", "sw0001a",
        "--condition", "U", "--sold",
    ]]


def test_exactly_one_call_no_second_catalog_lookup(tmp_path):
    rec = _recorder(_raw_prices())
    minifig_sales.summarize_fig(
        "sw0001a", _catalog(), runner=rec, cache_path=_iso(tmp_path))
    assert len(rec.calls) == 1


def test_empty_or_non_string_fig_no_rejected_without_a_call():
    rec = _recorder(_raw_prices())
    with pytest.raises(set_sales.LookupFailed):
        minifig_sales.summarize_fig("", _catalog(), runner=rec)
    with pytest.raises(set_sales.LookupFailed):
        minifig_sales.summarize_fig(None, _catalog(), runner=rec)
    with pytest.raises(set_sales.LookupFailed):
        minifig_sales.summarize_fig(12345, _catalog(), runner=rec)
    assert rec.calls == []


# --- artifact-carried catalog validation -------------------------------------


def test_missing_catalog_payload_rejected():
    rec = _recorder(_raw_prices())
    with pytest.raises(set_sales.LookupFailed, match="catalog"):
        minifig_sales.summarize_fig("sw0001a", None, runner=rec)
    assert rec.calls == []


def test_catalog_number_mismatch_names_both_numbers():
    rec = _recorder(_raw_prices())
    with pytest.raises(set_sales.LookupFailed, match="sw0217"):
        minifig_sales.summarize_fig("sw0001a", _catalog("sw0217"), runner=rec)
    assert rec.calls == []


# --- evidence selection -------------------------------------------------------


def test_unit_value_is_the_used_sold_average(tmp_path):
    out = minifig_sales.summarize_fig(
        "sw0001a", _catalog(), runner=_recorder(_raw_prices()),
        cache_path=_iso(tmp_path))
    assert out["used"]["six_month_avg_sold_price"] == 12.34
    assert out["unit_value"] == 12.34


def test_qty_units_and_depth_stay_distinct_evidence(tmp_path):
    out = minifig_sales.summarize_fig(
        "sw0001a", _catalog(), runner=_recorder(_raw_prices()),
        cache_path=_iso(tmp_path))
    assert out["used"]["qty_avg_price"] == 11.90
    assert out["used"]["total_quantity"] == 34
    assert out["used"]["unit_quantity"] == 21
    assert out["used"]["price_detail_count"] == 7


def test_catalog_payload_travels_onto_the_result(tmp_path):
    cat = _catalog()
    out = minifig_sales.summarize_fig(
        "sw0001a", cat, runner=_recorder(_raw_prices()),
        cache_path=_iso(tmp_path))
    assert out["catalog"] is cat


# --- zero sales ----------------------------------------------------------------


def test_zero_sales_is_a_present_null_valued_answer(tmp_path):
    out = minifig_sales.summarize_fig(
        "sw0344", _catalog("sw0344"),
        runner=_recorder(_raw_prices(avg=None)), cache_path=_iso(tmp_path))
    assert out["lookup_status"] == "zero_sales"
    assert out["unit_value"] is None
    reason = out["null_value_reason"]
    assert isinstance(reason, str) and "sold" in reason.lower()


def test_zero_sales_is_not_zero_dollars_and_not_an_exception(tmp_path):
    out = minifig_sales.summarize_fig(
        "sw0344", _catalog("sw0344"),
        runner=_recorder(_raw_prices(avg=None)), cache_path=_iso(tmp_path))
    assert out["unit_value"] != 0.0


# --- failure vocabulary ---------------------------------------------------------


def test_not_found_propagates_as_lookup_not_found(tmp_path):
    rec = _recorder(error=set_sales.LookupNotFound("no such minifig"))
    with pytest.raises(set_sales.LookupNotFound):
        minifig_sales.summarize_fig("sw9999z", _catalog("sw9999z"),
                                    runner=rec, cache_path=_iso(tmp_path))


def test_transient_failure_propagates_uncached_as_lookup_failed(tmp_path):
    rec = _recorder(error=set_sales.LookupFailed("rate limited"))
    with pytest.raises(set_sales.LookupFailed):
        minifig_sales.summarize_fig("sw0001a", _catalog(),
                                    runner=rec, cache_path=_iso(tmp_path))


def test_one_figs_failure_does_not_poison_the_next(tmp_path):
    class Flaky:
        def __init__(self):
            self.calls = []

        def __call__(self, args):
            self.calls.append(args)
            if len(self.calls) == 1:
                raise set_sales.LookupFailed("transient")
            return _raw_prices()

    flaky = Flaky()
    iso = _iso(tmp_path)
    with pytest.raises(set_sales.LookupFailed):
        minifig_sales.summarize_fig("sw0001a", _catalog(),
                                    runner=flaky, cache_path=iso)
    out = minifig_sales.summarize_fig("sw0217", _catalog("sw0217"),
                                      runner=flaky, cache_path=iso)
    assert out["unit_value"] == 12.34


# --- shared-cache wiring ----------------------------------------------------------


def test_cache_wiring_forwards_path_now_and_refresh_to_shared_lookup(monkeypatch, tmp_path):
    seen = {}

    def spy(args, cache_path=None, now=None, refresh=False):
        seen["args"] = args
        seen["cache_path"] = cache_path
        seen["now"] = now
        seen["refresh"] = refresh
        return _raw_prices()

    monkeypatch.setattr(set_sales, "cached_bricklink_json", spy)
    stamp = object()
    minifig_sales.summarize_fig(
        "sw0001a", _catalog(), cache_path=str(tmp_path / "c.json"),
        now=stamp, refresh=True)
    assert seen["args"][0:4] == ["catalog", "price", "MINIFIG", "sw0001a"]
    assert seen["cache_path"] == str(tmp_path / "c.json")
    assert seen["now"] is stamp
    assert seen["refresh"] is True


def test_refresh_bypasses_a_warm_cache(tmp_path):
    import datetime
    path = str(tmp_path / "bricklink_calls.json")

    calls = []

    def fake_fetch(args):
        calls.append(args)
        return _raw_prices()

    first = set_sales.cached_bricklink_json(
        minifig_sales.price_guide_args("sw0001a"),
        runner=fake_fetch, cache_path=path)
    assert float(first["avg_price"]) == 12.34  # raw payload, pre-normalization
    assert len(calls) == 1

    # Warm cache serves without the fetcher.
    set_sales.cached_bricklink_json(
        minifig_sales.price_guide_args("sw0001a"),
        runner=fake_fetch, cache_path=path)
    assert len(calls) == 1

    # refresh=True forces a refetch and restores the cache.
    refreshed = set_sales.cached_bricklink_json(
        minifig_sales.price_guide_args("sw0001a"),
        runner=fake_fetch, cache_path=path, refresh=True)
    assert len(calls) == 2
    assert float(refreshed["avg_price"]) == 12.34

    # And the refreshed entry is cached again.
    set_sales.cached_bricklink_json(
        minifig_sales.price_guide_args("sw0001a"),
        runner=fake_fetch, cache_path=path)
    assert len(calls) == 2


def test_seven_day_ttl_shape_covers_the_minifig_call():
    # The shared per-shape TTL table must know `catalog price`; the guide is a
    # rolling six-month window and expires weekly.
    assert set_sales._ttl_days(["catalog", "price", "MINIFIG"]) == 7
