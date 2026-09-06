"""eBay comps never raise on an auth lapse, match sets by exact token only,
and price bulk lots only where a weight actually parsed."""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from legoscout_cli.pricing import ebay_comps


def _listing(item_id, title, price):
    return {"item_id": item_id, "title": title, "price": price, "url": "https://ebay.com/itm/" + item_id}


def test_set_comps_matches_exact_token_only():
    listings = [
        _listing("1", "LEGO Star Wars 75192 Millennium Falcon UCS Complete", "750.00"),
        _listing("2", "LEGO 751920 unrelated knockoff part", "5.00"),
        _listing("3", "LEGO 75192 Millennium Falcon Complete Boxed", "820.00"),
    ]

    def runner(args):
        assert args[:2] == ["listings", "search"]
        return listings

    result = ebay_comps.search_set_comps("75192-1", "U", runner=runner)

    assert result["available"] is True
    assert result["matched_count"] == 2
    assert {row["item_id"] for row in result["listings"]} == {"1", "3"}
    assert result["avg_sold_price"] == round((750.0 + 820.0) / 2, 2)


def test_set_comps_excludes_denylisted_titles():
    listings = [
        _listing("1", "LEGO 75192 for parts incomplete", "100.00"),
        _listing("2", "LEGO 75192 Millennium Falcon Complete", "800.00"),
    ]

    result = ebay_comps.search_set_comps("75192", "U", runner=lambda args: listings)

    assert result["matched_count"] == 1
    assert result["listings"][0]["item_id"] == "2"
    assert "for parts" in result["excluded_reasons"]
    assert "incomplete" in result["excluded_reasons"]


def test_set_comps_condition_maps_to_ebay_vocabulary():
    seen = {}

    def runner(args):
        seen["args"] = args
        return []

    ebay_comps.search_set_comps("75192", "N", runner=runner)
    assert "--condition" in seen["args"]
    assert seen["args"][seen["args"].index("--condition") + 1] == "new"


def test_set_comps_rejects_bad_condition():
    with pytest.raises(ebay_comps.LookupFailed, match="condition must be"):
        ebay_comps.search_set_comps("75192", "X", runner=lambda args: [])


def test_auth_failure_degrades_to_unavailable_never_raises():
    def runner(args):
        raise ebay_comps.LookupFailed(
            "ebay listings search exited 1: Error: No browser session found. "
            "Run 'ebay auth login --credential-type browser_session' first.")

    result = ebay_comps.search_set_comps("75192", "U", runner=runner)

    assert result["available"] is False
    assert result["reason"] == "ebay_auth_required"
    assert result["avg_sold_price"] is None
    assert result["listings"] == []


def test_bulk_auth_failure_also_degrades():
    def runner(args):
        raise ebay_comps.LookupFailed("exited 1: No browser session found.")

    result = ebay_comps.search_bulk_comps("mixed bricks 10 lbs", runner=runner)

    assert result["available"] is False
    assert result["avg_price_per_lb"] is None


def test_bulk_comps_only_averages_listings_with_a_parseable_weight():
    listings = [
        _listing("1", "LEGO bulk lot 10 lbs mixed bricks", "50.00"),
        _listing("2", "LEGO bulk lot mixed bricks no weight stated", "30.00"),
        _listing("3", "LEGO bulk lot 5 lbs technic pieces", "20.00"),
    ]

    result = ebay_comps.search_bulk_comps("mixed bricks", dollars_per_lb=4.0,
                                          runner=lambda args: listings)

    assert result["matched_count"] == 2
    assert "no parseable weight" in result["excluded_reasons"]
    # 50/10 = 5.0/lb, 20/5 = 4.0/lb -> avg 4.5
    assert result["avg_price_per_lb"] == 4.5
    assert result["target_vs_comp_delta_pct"] == round((4.0 - 4.5) / 4.5 * 100, 2)


def test_bulk_comps_has_no_category_filter():
    seen = {}

    def runner(args):
        seen["args"] = args
        return []

    ebay_comps.search_bulk_comps("mixed bricks", runner=runner)
    assert "--category" not in seen["args"]


def test_real_ebay_subprocesses_serialize_on_shared_browser_profile(
        monkeypatch, tmp_path):
    active = 0
    maximum_active = 0
    state_lock = threading.Lock()

    def fake_run(*_args, **_kwargs):
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.02)
        with state_lock:
            active -= 1
        return SimpleNamespace(returncode=0, stdout=json.dumps([]), stderr="")

    monkeypatch.setattr(ebay_comps, "EBAY_BROWSER_LOCK", str(tmp_path / "ebay.lock"))
    monkeypatch.setattr(ebay_comps.shutil, "which", lambda _command: "/fake/ebay")
    monkeypatch.setattr(ebay_comps.subprocess, "run", fake_run)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(
            lambda index: ebay_comps.run_ebay_json(["search", str(index)]),
            range(4),
        ))

    assert results == [[], [], [], []]
    assert maximum_active == 1


def test_shared_browser_profile_wait_has_clear_bounded_timeout(
        monkeypatch, tmp_path):
    lock_path = tmp_path / "ebay.lock"
    monkeypatch.setattr(ebay_comps, "EBAY_BROWSER_LOCK", str(lock_path))
    monkeypatch.setattr(ebay_comps, "EBAY_BROWSER_LOCK_TIMEOUT_SECONDS", 0.0)
    with open(lock_path, "a+") as held:
        ebay_comps.fcntl.flock(held.fileno(), ebay_comps.fcntl.LOCK_EX)
        with pytest.raises(
                ebay_comps.LookupFailed,
                match="timed out after 0 seconds waiting for the shared eBay browser profile"):
            with ebay_comps._ebay_browser_slot():
                pass
