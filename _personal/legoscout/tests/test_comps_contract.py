"""The combined comps lookup: one 'sets' entry per detected set number,
BrickLink and eBay each degrading independently within every entry."""
from __future__ import annotations

import pytest

from legoscout_cli.pricing import comps, ebay_comps, set_sales


def test_set_comps_merges_both_sources_for_a_single_set(monkeypatch):
    monkeypatch.setattr(set_sales, "summarize_set",
                        lambda set_no, condition: {"lookup_status": "found", "used": {}})
    monkeypatch.setattr(ebay_comps, "search_set_comps",
                        lambda set_no, condition, description=None, limit=50:
                        {"available": True, "avg_sold_price": 800.0})

    result = comps.set_comps(["75192"], "U", description="Millennium Falcon")

    assert result["mode"] == "set"
    assert len(result["sets"]) == 1
    entry = result["sets"][0]
    assert entry["set_no"] == "75192"
    assert entry["bricklink"]["lookup_status"] == "found"
    assert entry["ebay"]["avg_sold_price"] == 800.0


def test_set_comps_prices_every_detected_set_on_a_multi_set_listing(monkeypatch):
    calls = []

    def fake_summarize(set_no, condition):
        calls.append(set_no)
        return {"lookup_status": "found", "set_no": set_no}

    monkeypatch.setattr(set_sales, "summarize_set", fake_summarize)
    monkeypatch.setattr(ebay_comps, "search_set_comps",
                        lambda set_no, condition, description=None, limit=50:
                        {"available": True, "avg_sold_price": 100.0})

    result = comps.set_comps(["75192", "6868"], "U")

    assert calls == ["75192", "6868"]
    assert [entry["set_no"] for entry in result["sets"]] == ["75192", "6868"]
    assert all(entry["bricklink"]["lookup_status"] == "found" for entry in result["sets"])


def test_set_comps_rejects_empty_set_list():
    with pytest.raises(ValueError, match="non-empty list"):
        comps.set_comps([], "U")


def test_one_set_not_found_does_not_block_the_others(monkeypatch):
    def fake_summarize(set_no, condition):
        if set_no == "99999999":
            raise set_sales.LookupNotFound("RESOURCE_NOT_FOUND")
        return {"lookup_status": "found", "set_no": set_no}

    monkeypatch.setattr(set_sales, "summarize_set", fake_summarize)
    monkeypatch.setattr(ebay_comps, "search_set_comps",
                        lambda set_no, condition, description=None, limit=50:
                        {"available": True, "avg_sold_price": 100.0})

    result = comps.set_comps(["99999999", "75192"], "U")

    by_no = {entry["set_no"]: entry for entry in result["sets"]}
    assert by_no["99999999"]["bricklink"]["lookup_status"] == "not_found"
    assert by_no["75192"]["bricklink"]["lookup_status"] == "found"


def test_bricklink_not_found_does_not_block_ebay(monkeypatch):
    def raise_not_found(set_no, condition):
        raise set_sales.LookupNotFound("RESOURCE_NOT_FOUND")

    monkeypatch.setattr(set_sales, "summarize_set", raise_not_found)
    monkeypatch.setattr(ebay_comps, "search_set_comps",
                        lambda set_no, condition, description=None, limit=50:
                        {"available": True, "avg_sold_price": 800.0})

    result = comps.set_comps(["99999999"], "U")

    entry = result["sets"][0]
    assert entry["bricklink"]["lookup_status"] == "not_found"
    assert entry["ebay"]["avg_sold_price"] == 800.0


def test_ebay_auth_lapse_does_not_block_bricklink(monkeypatch):
    monkeypatch.setattr(set_sales, "summarize_set",
                        lambda set_no, condition: {"lookup_status": "found", "used": {}})
    monkeypatch.setattr(ebay_comps, "search_set_comps",
                        lambda set_no, condition, description=None, limit=50:
                        {"available": False, "reason": "ebay_auth_required"})

    result = comps.set_comps(["75192"], "U")

    entry = result["sets"][0]
    assert entry["bricklink"]["lookup_status"] == "found"
    assert entry["ebay"]["available"] is False


def test_bulk_comps_has_no_bricklink_call(monkeypatch):
    called = {"summarize_set": False}
    monkeypatch.setattr(set_sales, "summarize_set",
                        lambda *a, **k: called.__setitem__("summarize_set", True))
    monkeypatch.setattr(ebay_comps, "search_bulk_comps",
                        lambda description, dollars_per_lb=None, limit=50:
                        {"available": True, "avg_price_per_lb": 4.5})

    result = comps.bulk_comps("mixed bricks", dollars_per_lb=4.0)

    assert result["bricklink"] is None
    assert result["ebay"]["avg_price_per_lb"] == 4.5
    assert called["summarize_set"] is False
