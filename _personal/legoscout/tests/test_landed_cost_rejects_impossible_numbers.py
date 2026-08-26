#!/usr/bin/env python3
"""`landed-cost` computes nothing from a number that is not an amount.

`--hammer`, `--premium-pct` and `--sales-tax-pct` took any float with no
finiteness or sign check, and every one of these exited 0:

    --hammer nan          "hammer": NaN, "landed_total": NaN
    --hammer inf          "hammer": Infinity
    --hammer -45          $-45.00 hammer ... = $-38.15 landed
    --sales-tax-pct -1    +$-115.00 tax (-100.00%) = $10.00 landed on a $100 lot
    --premium-pct 18      +$1800.00 premium (1800.0%)

Two separate failures. `NaN` and `Infinity` are Python-only JSON tokens, so
stdout -- contracted to be ONE parseable JSON object -- became text no other
parser reads. And a negative cost or a negative rate SUBTRACTS from the landed
total, so the command reports a bargain that does not exist, at exit 0, on the
number every downstream score is denominated in.

This is the upstream feed for the deals page: `estimated_total` is written from
this breakdown, and one non-finite value there took the whole page down at
`await res.json()`.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

import pytest

from legoscout_cli import paths
from legoscout_cli.pricing import fees
from legoscout_cli.sources import registry

NOT_AN_AMOUNT = (float("nan"), float("inf"), float("-inf"))


@pytest.fixture(scope="module", autouse=True)
def registry_copy(tmp_path_factory):
    """Point the source registry at a scratch copy of the ledger.

    `fee_config()` opens the ledger through `ledger_db.connect()`, which
    migrates columns and indexes on the way in. That is a WRITE, so these tests
    must not aim it at Adam's ledger.
    """
    real = paths.DB_PATH
    if not os.path.isfile(real):
        raise FileNotFoundError(
            "the ledger is missing at %s, and it holds the source fee registry "
            "these rates come from. Restore it from Dropbox rather than "
            "letting this suite skip." % real)
    copy = str(tmp_path_factory.mktemp("registry") / "found_deals.db")
    source = sqlite3.connect("file:%s?mode=ro" % real, uri=True)
    target = sqlite3.connect(copy)
    try:
        with target:
            source.backup(target)
    finally:
        source.close()
        target.close()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(registry.sources, "path", copy)
        yield copy


# --------------------------------------------------------------------------
# Nothing that is not a quantity
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value", NOT_AN_AMOUNT)
def test_a_non_finite_hammer_is_refused(value):
    with pytest.raises(ValueError, match="hammer"):
        fees.landed_cost("ebay", value, 0.0)


@pytest.mark.parametrize("value", NOT_AN_AMOUNT)
def test_a_non_finite_shipping_cost_is_refused(value):
    with pytest.raises(ValueError, match="shipping"):
        fees.landed_cost("ebay", 45.0, value)


@pytest.mark.parametrize("value", NOT_AN_AMOUNT)
def test_a_non_finite_rate_is_refused(value):
    with pytest.raises(ValueError, match="premium_pct"):
        fees.landed_cost("ebay", 45.0, 10.0, premium_pct=value)
    with pytest.raises(ValueError, match="sales_tax_pct"):
        fees.landed_cost("ebay", 45.0, 10.0, sales_tax_pct=value)


# --------------------------------------------------------------------------
# Nothing negative, and no rate outside 0..1
# --------------------------------------------------------------------------

def test_a_negative_hammer_is_refused():
    """`$-45.00 hammer ... = $-38.15 landed` is not a cheap lot."""
    with pytest.raises(ValueError, match="hammer"):
        fees.landed_cost("ebay", -45.0, 10.0)


def test_a_negative_shipping_or_handling_cost_is_refused():
    with pytest.raises(ValueError, match="shipping"):
        fees.landed_cost("ebay", 45.0, -5.0)
    with pytest.raises(ValueError, match="handling"):
        fees.landed_cost("ebay", 45.0, 10.0, handling=-5.0)


def test_a_negative_tax_rate_is_refused():
    """-100% tax paid for the lot: $100 hammer + $15 premium came back $10."""
    with pytest.raises(ValueError, match="sales_tax_pct"):
        fees.landed_cost("hibid", 100.0, 10.0, sales_tax_pct=-1.0)


@pytest.mark.parametrize("rate", [1.0001, 18.0, 100.0])
def test_a_percentage_passed_as_a_whole_number_is_refused(rate):
    """Rates are fractions. `--premium-pct 18` is 1800%, and it priced a $100
    lot at $2043.00 landed without a word."""
    with pytest.raises(ValueError, match="premium_pct"):
        fees.landed_cost("hibid", 100.0, 10.0, premium_pct=rate)


def test_every_registered_source_still_prices_inside_the_bounds():
    """The check sits on the RESOLVED rate, so a bad registry entry fails here
    too rather than only a bad flag. Nothing is skipped silently: a source with
    no researched fee structure, and AuctionNinja's documented missing tax
    sample, both raise their own named error and are asserted as such.
    """
    priced = 0
    for namespace in registry.active_namespaces():
        try:
            cfg = fees.config(namespace)
            buyer_fee = 4.0 if cfg.get("buyer_fee_already_in_total") else None
            breakdown = fees.landed_cost(
                namespace, 100.0, 10.0,
                buyer_protection_fee=buyer_fee)
        except registry.UnknownEntry as exc:
            assert "no researched fee structure" in str(exc), namespace
            continue
        except ValueError as exc:
            assert "no sampled rate" in str(exc), namespace
            continue
        priced += 1
        assert breakdown["source"] == namespace
        assert 0.0 <= breakdown["premium_pct"] <= fees.MAX_RATE, namespace
        assert 0.0 <= breakdown["sales_tax_pct"] <= fees.MAX_RATE, namespace
        assert breakdown["landed_total"] >= 100.0, namespace
    assert priced > 0, "no source priced at all -- the registry copy is empty"


# --------------------------------------------------------------------------
# The good paths are unchanged
# --------------------------------------------------------------------------

def test_a_real_hammer_still_prices():
    breakdown = fees.landed_cost("hibid", 100.0, 10.0)
    assert breakdown["premium_amount"] == 15.0
    assert breakdown["landed_total"] == 133.05


def test_a_zero_hammer_is_a_real_price():
    """$0.00 is an amount. Only `nan`, `inf` and negatives are not."""
    breakdown = fees.landed_cost("ebay", 0.0, None)
    assert breakdown["landed_total"] == 0.0
    assert breakdown["shipping_unknown"] is True


def test_the_breakdown_is_parseable_json():
    """`allow_nan=False` is the contract stdout promises."""
    breakdown = fees.landed_cost("hibid", 100.0, 10.0)
    assert json.loads(json.dumps(breakdown, allow_nan=False))["landed_total"] == 133.05


def test_mercari_requires_and_prices_the_published_buyer_fee():
    with pytest.raises(ValueError, match="--buyer-protection-fee"):
        fees.landed_cost("mercari", 120.0, 0.0)

    breakdown = fees.landed_cost(
        "mercari", 120.0, 0.0, buyer_protection_fee=4.32)

    assert breakdown["buyer_protection_fee"] == 4.32
    assert breakdown["sales_tax_amount"] == 8.4
    assert breakdown["landed_total"] == 132.72
    assert "+$4.32 buyer protection" in fees.explain(breakdown)


def test_a_negative_buyer_protection_fee_is_refused():
    with pytest.raises(ValueError, match="buyer_protection_fee"):
        fees.landed_cost(
            "mercari", 120.0, 0.0, buyer_protection_fee=-4.32)


def test_landed_cost_cli_writes_only_json_to_stdout(monkeypatch, capsys):
    """The human summary is stderr-only, so stdout is one JSON document."""
    monkeypatch.setattr(sys, "argv", [
        "fees",
        "--source", "poshmark",
        "--hammer", "15",
        "--shipping", "6.49",
    ])

    fees.main()

    captured = capsys.readouterr()
    breakdown = json.loads(captured.out)
    assert captured.out == json.dumps(breakdown, indent=2, allow_nan=False) + "\n"
    assert breakdown["landed_total"] == 22.54
    assert captured.err == fees.explain(breakdown) + "\n"
