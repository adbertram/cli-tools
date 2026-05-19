"""Unit tests for ata_blog_cli.ads_scanner.

All tests mock PlaywrightService via the _service_factory seam. Zero network.
"""
import copy
import re
import time
from unittest.mock import MagicMock, patch

import pytest

from ata_blog_cli import ads_scanner
from ata_blog_cli.ads_scanner import scan_page, scan_pages, SCANNER_DEFAULTS


# ---------- helpers ----------

def _scripted_evaluate(payloads):
    """Return a side_effect function that yields each payload then repeats the last.

    Ignores scroll/warm-page evaluate calls (returns None for them) so they don't
    exhaust the scripted GPT-poll payload queue.
    """
    items = list(payloads)

    def _side_effect(*args, **kwargs):
        js = args[0] if args else ""
        if "scrollBy" in js or "scrollTo" in js:
            return None  # warm-page call; don't consume a payload
        if len(items) == 1:
            return copy.deepcopy(items[0])
        return copy.deepcopy(items.pop(0))

    return _side_effect


def _service_with_evaluate(side_effect):
    svc = MagicMock()
    svc.__enter__ = MagicMock(return_value=svc)
    svc.__exit__ = MagicMock(return_value=False)
    svc.evaluate.side_effect = side_effect
    return svc


# ---------- tests ----------

def test_scan_page_no_gpt_returns_empty():
    svc = _service_with_evaluate(_scripted_evaluate([{"gptDetected": False, "slots": []}]))
    result = scan_page(
        "https://adamtheautomator.com/x", checks=1, interval=0, per_check_timeout=1,
        _service_factory=lambda: svc,
    )
    assert result["gpt_detected"] is False
    assert result["unique_advertisers"] == []
    assert result["total_impressions"] == 0
    assert result["checks_completed"] == 1


def test_scan_page_gpt_becomes_ready_after_first_poll(slot_payload_multi):
    # First poll: no GPT. Subsequent polls: stable slot count (3, 3) -> returns.
    payloads = [
        {"gptDetected": False, "slots": []},
        slot_payload_multi,
        slot_payload_multi,
    ]
    svc = _service_with_evaluate(_scripted_evaluate(payloads))
    result = scan_page(
        "https://adamtheautomator.com/x", checks=1, interval=0, per_check_timeout=5,
        _service_factory=lambda: svc,
    )
    assert result["gpt_detected"] is True
    assert result["total_impressions"] >= 1


def test_scan_page_gpt_never_ready_returns_empty():
    svc = _service_with_evaluate(_scripted_evaluate([{"gptDetected": False, "slots": []}]))
    start = time.perf_counter()
    result = scan_page(
        "https://adamtheautomator.com/x", checks=1, interval=0, per_check_timeout=1,
        _service_factory=lambda: svc,
    )
    elapsed = time.perf_counter() - start
    assert result["gpt_detected"] is False
    assert elapsed < 2.0, f"scanner exceeded per_check_timeout: {elapsed:.2f}s"


def test_scan_page_partial_gpt_detection(slot_payload_multi):
    # Check 1: stable GPT. Check 2: no GPT.
    # Use a side_effect function that produces a long enough stream.
    check1_payloads = [slot_payload_multi, slot_payload_multi]  # stable
    check2_payloads = [{"gptDetected": False, "slots": []}]
    stream = check1_payloads + check2_payloads
    svc = _service_with_evaluate(_scripted_evaluate(stream))
    result = scan_page(
        "https://adamtheautomator.com/x", checks=2, interval=0, per_check_timeout=1,
        _service_factory=lambda: svc,
    )
    assert result["gpt_detected"] is True  # seen at least once
    # Only check 1's 3 records count
    assert result["total_impressions"] == 3


def test_scan_page_deduplicates_across_checks(slot_payload_multi):
    # Same payload on every poll. Stable after 2 polls per check, 2 checks -> 6 records total.
    svc = _service_with_evaluate(_scripted_evaluate([slot_payload_multi]))
    result = scan_page(
        "https://adamtheautomator.com/x", checks=2, interval=0, per_check_timeout=2,
        _service_factory=lambda: svc,
    )
    assert result["gpt_detected"] is True
    # 3 records per check * 2 checks = 6 total impressions
    assert result["total_impressions"] == 6
    adv = result["unique_advertisers"]
    # digicert appears twice per check * 2 checks = 4; datadog appears once per check * 2 checks = 2
    assert len(adv) == 2
    by_domain = {a["domain"]: a for a in adv}
    assert by_domain["digicert.com"]["appearances"] == 4
    assert by_domain["datadoghq.com"]["appearances"] == 2


def test_scan_page_dedupe_same_advertiser_different_creatives():
    payload = {
        "gptDetected": True,
        "slots": [
            {"slotId": "s1", "advertiserId": "42", "creativeId": "100", "lineItemId": "L1", "domain": "example.com"},
            {"slotId": "s2", "advertiserId": "42", "creativeId": "200", "lineItemId": "L2", "domain": "example.com"},
        ],
    }
    svc = _service_with_evaluate(_scripted_evaluate([payload]))
    result = scan_page(
        "https://adamtheautomator.com/x", checks=1, interval=0, per_check_timeout=2,
        _service_factory=lambda: svc,
    )
    assert len(result["unique_advertisers"]) == 1
    entry = result["unique_advertisers"][0]
    assert entry["appearances"] == 2
    assert set(entry["creative_ids"]) == {"100", "200"}


def test_scan_page_dedupe_falls_back_to_slot_id_when_advertiser_and_domain_missing():
    payload = {
        "gptDetected": True,
        "slots": [
            {"slotId": "slot-1", "advertiserId": None, "creativeId": None, "lineItemId": None, "domain": None},
            {"slotId": "slot-2", "advertiserId": None, "creativeId": None, "lineItemId": None, "domain": None},
            {"slotId": "slot-3", "advertiserId": None, "creativeId": None, "lineItemId": None, "domain": None},
        ],
    }
    svc = _service_with_evaluate(_scripted_evaluate([payload]))
    result = scan_page(
        "https://adamtheautomator.com/x", checks=1, interval=0, per_check_timeout=2,
        _service_factory=lambda: svc,
    )
    # 3 distinct slotIds => 3 entries, NOT collapsed.
    assert len(result["unique_advertisers"]) == 3


def test_scan_page_preserves_advertiser_id_zero():
    payload = {
        "gptDetected": True,
        "slots": [
            {"slotId": "s1", "advertiserId": "0", "creativeId": "c1", "lineItemId": "L1", "domain": "house.example"},
            {"slotId": "s2", "advertiserId": None, "creativeId": "c2", "lineItemId": "L2", "domain": "other.example"},
        ],
    }
    svc = _service_with_evaluate(_scripted_evaluate([payload]))
    result = scan_page(
        "https://adamtheautomator.com/x", checks=1, interval=0, per_check_timeout=2,
        _service_factory=lambda: svc,
    )
    # advertiser_id '0' (house ad) is distinct from None (unknown).
    advs = result["unique_advertisers"]
    assert len(advs) == 2
    ids = {a["advertiser_id"] for a in advs}
    assert "0" in ids
    assert None in ids


def test_scan_page_share_exact():
    payload = {
        "gptDetected": True,
        "slots": [
            {"slotId": "s1", "advertiserId": "A", "creativeId": "c1", "lineItemId": None, "domain": "a.example"},
            {"slotId": "s2", "advertiserId": "A", "creativeId": "c1", "lineItemId": None, "domain": "a.example"},
            {"slotId": "s3", "advertiserId": "B", "creativeId": "c2", "lineItemId": None, "domain": "b.example"},
        ],
    }
    svc = _service_with_evaluate(_scripted_evaluate([payload]))
    result = scan_page(
        "https://adamtheautomator.com/x", checks=1, interval=0, per_check_timeout=2,
        _service_factory=lambda: svc,
    )
    by_adv = {a["advertiser_id"]: a for a in result["unique_advertisers"]}
    assert by_adv["A"]["share"] == pytest.approx(0.667, abs=0.001)
    assert by_adv["B"]["share"] == pytest.approx(0.333, abs=0.001)
    assert sum(a["share"] for a in result["unique_advertisers"]) == pytest.approx(1.0, abs=0.01)


def test_scan_page_single_advertiser_share_is_one():
    payload = {
        "gptDetected": True,
        "slots": [
            {"slotId": "s1", "advertiserId": "A", "creativeId": "c1", "lineItemId": None, "domain": "a.example"},
            {"slotId": "s2", "advertiserId": "A", "creativeId": "c1", "lineItemId": None, "domain": "a.example"},
            {"slotId": "s3", "advertiserId": "A", "creativeId": "c1", "lineItemId": None, "domain": "a.example"},
        ],
    }
    svc = _service_with_evaluate(_scripted_evaluate([payload]))
    result = scan_page(
        "https://adamtheautomator.com/x", checks=1, interval=0, per_check_timeout=2,
        _service_factory=lambda: svc,
    )
    assert result["unique_advertisers"][0]["share"] == 1.0


def test_scan_page_respects_per_check_timeout(slot_payload_multi):
    # Alternate slot count to defeat stability -> scanner must exit on timeout.
    # Build a long alternating stream; side_effect cycles once exhausted.
    payloads = [
        {"gptDetected": True, "slots": slot_payload_multi["slots"]},
        {"gptDetected": True, "slots": slot_payload_multi["slots"][:2]},
    ]
    idx = {"i": 0}

    def side_effect(*a, **kw):
        p = payloads[idx["i"] % len(payloads)]
        idx["i"] += 1
        return copy.deepcopy(p)

    svc = _service_with_evaluate(side_effect)
    start = time.perf_counter()
    result = scan_page(
        "https://adamtheautomator.com/x", checks=1, interval=0, per_check_timeout=1,
        _service_factory=lambda: svc,
    )
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"scanner exceeded per_check_timeout + buffer: {elapsed:.2f}s"
    # Should have recorded something from the last poll
    assert result["gpt_detected"] is True


def test_scan_page_stable_with_zero_slots_exits_promptly(slot_payload_empty_with_gpt, monkeypatch):
    """Stable-at-zero exits within a few poll cycles when min_initial_wait_s is 0.
    (Live scans keep the wait gate so late-rendering ads aren't missed.)
    """
    monkeypatch.setitem(ads_scanner.SCANNER_DEFAULTS, "min_initial_wait_s", 0)
    svc = _service_with_evaluate(_scripted_evaluate([slot_payload_empty_with_gpt]))
    start = time.perf_counter()
    result = scan_page(
        "https://adamtheautomator.com/x", checks=1, interval=0, per_check_timeout=5,
        _service_factory=lambda: svc,
    )
    elapsed = time.perf_counter() - start
    assert elapsed < 3.0, f"zero-slot stability took too long: {elapsed:.2f}s"
    assert result["gpt_detected"] is True
    assert result["unique_advertisers"] == []


def test_scan_page_min_initial_wait_delays_zero_stability(slot_payload_empty_with_gpt, monkeypatch):
    """When min_initial_wait_s > 0, stable-at-zero waits at least that long."""
    monkeypatch.setitem(ads_scanner.SCANNER_DEFAULTS, "min_initial_wait_s", 2)
    svc = _service_with_evaluate(_scripted_evaluate([slot_payload_empty_with_gpt]))
    start = time.perf_counter()
    scan_page(
        "https://adamtheautomator.com/x", checks=1, interval=0, per_check_timeout=5,
        _service_factory=lambda: svc,
    )
    elapsed = time.perf_counter() - start
    # Should wait ~2s before accepting stable-at-zero (not exit immediately)
    assert elapsed >= 1.8, f"zero-stability accepted too early: {elapsed:.2f}s"
    assert elapsed < 4.0, f"zero-stability waited too long: {elapsed:.2f}s"


def test_scan_page_stability_criterion(slot_payload_multi):
    # Two identical polls in a row -> stable -> exit before hard timeout.
    svc = _service_with_evaluate(_scripted_evaluate([slot_payload_multi]))
    start = time.perf_counter()
    scan_page(
        "https://adamtheautomator.com/x", checks=1, interval=0, per_check_timeout=10,
        _service_factory=lambda: svc,
    )
    elapsed = time.perf_counter() - start
    assert elapsed < 3.0


def test_scan_page_sets_metadata_fields(slot_payload_multi):
    svc = _service_with_evaluate(_scripted_evaluate([slot_payload_multi]))
    result = scan_page(
        "https://adamtheautomator.com/x", checks=2, interval=0, per_check_timeout=2,
        _service_factory=lambda: svc,
    )
    assert result["url"] == "https://adamtheautomator.com/x"
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", result["scanned_at"])
    assert isinstance(result["duration_seconds"], float)
    assert result["duration_seconds"] >= 0.0
    assert result["checks_completed"] == 2
    assert isinstance(result["gpt_detected"], bool)


def test_scan_page_network_failure_raises():
    from cli_tools_shared.browser import PlaywrightServiceError

    def boom_factory():
        raise PlaywrightServiceError("browser failed to open")

    with pytest.raises(PlaywrightServiceError):
        scan_page(
            "https://adamtheautomator.com/x", checks=1, interval=0, per_check_timeout=1,
            _service_factory=boom_factory,
        )


def test_scan_page_invalid_url_raises():
    with pytest.raises(ValueError):
        scan_page("not a url", checks=1, interval=0, per_check_timeout=1)


def test_scan_page_rejects_non_positive_params(slot_payload_multi):
    svc = _service_with_evaluate(_scripted_evaluate([slot_payload_multi]))
    url = "https://adamtheautomator.com/x"
    with pytest.raises(ValueError):
        scan_page(url, checks=0, _service_factory=lambda: svc)
    with pytest.raises(ValueError):
        scan_page(url, checks=-1, _service_factory=lambda: svc)
    with pytest.raises(ValueError):
        scan_page(url, interval=-1, _service_factory=lambda: svc)
    with pytest.raises(ValueError):
        scan_page(url, per_check_timeout=0, _service_factory=lambda: svc)
    # interval=0 is allowed (no sleep)
    scan_page(url, checks=1, interval=0, per_check_timeout=1, _service_factory=lambda: svc)


def test_scan_pages_shares_browser(slot_payload_multi):
    """scan_pages opens PlaywrightService exactly once across N URLs."""
    svc = _service_with_evaluate(_scripted_evaluate([slot_payload_multi]))
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        return svc

    urls = [
        "https://adamtheautomator.com/a",
        "https://adamtheautomator.com/b",
        "https://adamtheautomator.com/c",
    ]
    results = scan_pages(urls, checks=1, interval=0, per_check_timeout=2, _service_factory=factory)
    assert calls["n"] == 1, "scan_pages should construct PlaywrightService exactly once"
    assert len(results) == 3
    # First URL should open browser; subsequent should navigate.
    assert svc.browser_open.call_count == 1
    assert svc.page_goto.call_count == 2  # URLs 2 and 3


def test_scanner_overrides_flow_through(slot_payload_multi):
    """Flags passed to scan_page should actually reach the loop (not silently ignored)."""
    svc = _service_with_evaluate(_scripted_evaluate([slot_payload_multi]))
    # checks=5 means 5 reloads
    result = scan_page(
        "https://adamtheautomator.com/x", checks=5, interval=0, per_check_timeout=2,
        _service_factory=lambda: svc,
    )
    assert result["checks_completed"] == 5
    # reload called 4 times (first check does NOT reload; checks 2..5 do)
    assert svc.reload.call_count == 4


def test_scan_page_interval_zero_does_not_sleep(slot_payload_multi, monkeypatch):
    """interval=0 should NOT call time.sleep(0) between reloads (gated by `if interval > 0`)."""
    sleep_calls = []

    def tracking_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(ads_scanner.time, "sleep", tracking_sleep)

    svc = _service_with_evaluate(_scripted_evaluate([slot_payload_multi]))
    scan_page(
        "https://adamtheautomator.com/x", checks=3, interval=0, per_check_timeout=2,
        _service_factory=lambda: svc,
    )
    # Poll-cycle sleeps use poll_ms/1000 (0.5s) — those are fine and non-zero.
    # Between-reload sleeps are gated on `if interval > 0` so sleep(0) must never appear.
    assert 0 not in sleep_calls


def test_gpt_poll_js_is_parseable():
    js = ads_scanner._GPT_POLL_JS
    # Must be an arrow function accepting an arg
    assert js.strip().startswith("(arg) =>")
    # Key identifiers present
    for kw in ("googletag", "getResponseInformation", "advertiserId", "creativeId", "slotId"):
        assert kw in js, f"missing keyword: {kw}"
    # Balanced braces and parens
    assert js.count("{") == js.count("}"), "unbalanced braces"
    assert js.count("(") == js.count(")"), "unbalanced parens"


def test_default_factory_constructs_stealth_browser():
    """Without _service_factory, scan_page should build a StealthBrowser with configured session."""
    with patch("ata_blog_cli.ads_scanner.StealthBrowser") as MockBrowser:
        svc_instance = MagicMock()
        svc_instance.__enter__ = MagicMock(return_value=svc_instance)
        svc_instance.__exit__ = MagicMock(return_value=False)
        svc_instance.evaluate.return_value = {"gptDetected": True, "slots": []}
        MockBrowser.return_value = svc_instance

        scan_page(
            "https://adamtheautomator.com/x",
            checks=1, interval=0, per_check_timeout=2,
        )

        MockBrowser.assert_called_once()
        args, kwargs = MockBrowser.call_args
        assert kwargs.get("session") == SCANNER_DEFAULTS["session"]
        assert kwargs.get("timeout") == 2


def test_scanner_defaults_not_mutated_by_scan_page(slot_payload_multi):
    snap = copy.deepcopy(SCANNER_DEFAULTS)
    svc = _service_with_evaluate(_scripted_evaluate([slot_payload_multi]))
    scan_page(
        "https://adamtheautomator.com/x", checks=5, interval=1, per_check_timeout=3,
        _service_factory=lambda: svc,
    )
    assert SCANNER_DEFAULTS == snap
