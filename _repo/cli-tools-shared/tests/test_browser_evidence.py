"""Monetary evidence must not turn dates or quantities into charge matches."""

import pytest

from cli_tools_shared.browser_evidence import evidence_matches


@pytest.mark.parametrize("text", [
    "ORDER PLACED\nSeptember 25, 2024\nTOTAL\n$17.11\nORDER # 112-2875707-4247433",
    "Product support window closed on July 25, 2026",
    "25 cartridges, 25 mg, SKU-25-0000000",
    "125.00 25.001 ABC25.00 25.00XYZ",
])
def test_amount_does_not_match_nonmonetary_numbers(text):
    snapshot = {"url": "https://example.com/orders", "title": "Orders", "texts": [text]}
    assert evidence_matches(snapshot, amount="25.00", date=None, query=None, limit=10) == []


@pytest.mark.parametrize("text", ["TOTAL\n$25", "$25.00", "25.00", "-$25.00", "+$25", "$ 25.00", "Total is $25.00."])
def test_amount_preserves_explicit_money_matches(text):
    snapshot = {"url": "https://example.com/orders", "title": "Orders", "texts": [text]}
    rows = evidence_matches(snapshot, amount="25.00", date=None, query=None, limit=10)
    assert len(rows) == 1
    assert rows[0]["matched_amount"] is True


def test_date_only_evidence_is_retained_without_claiming_amount_match():
    snapshot = {"url": "https://example.com/orders", "title": "Orders", "texts": [
        "ORDER PLACED\nSeptember 25, 2024\nTOTAL\n$17.11",
    ]}
    rows = evidence_matches(snapshot, amount="25.00", date="September 25, 2024", query=None, limit=10)
    assert len(rows) == 1
    assert rows[0]["matched_amount"] is False
    assert rows[0]["matched_terms"] == ["September 25, 2024"]
