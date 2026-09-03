"""Parser tests backed by the REAL captured `/listings-explore-page` records.

Fixture: tests/fixtures/listings_explore_page.json -- the first eight records
of the live 402-listing response captured 2026-09-03 from
`GET https://aws.api.mercor.com/work/listings-explore-page` on Adam's
authenticated Mercor worker session (see fixtures README notes in the parent
CLI docs). No value below is invented: assertions compare derived fields
against the real record values in the fixture.
"""

from __future__ import annotations

import math

import pytest

from mercor_cli.parsers import (
    listing_url,
    normalize_listing,
    normalize_listings,
)


def test_real_records_normalize_with_derived_fields(listing_records):
    rows = normalize_listings(listing_records)
    assert len(rows) == len(listing_records)
    for raw, row in zip(listing_records, rows):
        assert row["id"] == raw["listingId"]
        assert row["title"] == raw["title"]
        assert row["url"] == listing_url(raw["listingId"])
        assert row["url"].startswith("https://work.mercor.com/explore?listingId=")
        assert raw["listingId"] in row["url"]


def test_real_records_keep_every_api_field(listing_records):
    """The output record is the raw API record plus derived fields -- no
    filtering, so the documented 'all data the API provides' contract holds."""
    rows = normalize_listings(listing_records)
    for raw, row in zip(listing_records, rows):
        for key, value in raw.items():
            assert key in row, f"raw field {key} dropped from normalized record"
            assert row[key] == value, f"raw field {key} altered by normalization"


def test_real_records_are_strict_json_numbers(listing_records):
    """Records must be strict JSON: every number finite (no NaN/Infinity)."""
    rows = normalize_listings(listing_records)
    for row in rows:
        for key, value in row.items():
            if isinstance(value, float):
                assert math.isfinite(value), f"{key} is not finite: {value}"
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, float):
                        assert math.isfinite(item), f"{key} holds non-finite {item}"


def test_fixture_covers_pay_shapes(listing_records):
    """The fixture exercises hourly, per-task and one-time pay listings so the
    adapter's pay handling is tested against real shapes."""
    frequencies = {r.get("payRateFrequency") for r in listing_records}
    assert "hourly" in frequencies
    assert frequencies <= {"hourly", "per-task", "one-time", "yearly"}


def test_normalize_listing_drops_nothing_and_adds_id_url():
    raw = {"listingId": "list_abc", "title": "Role", "rateMin": 10.0}
    row = normalize_listing(raw)
    assert row == {
        "listingId": "list_abc",
        "title": "Role",
        "rateMin": 10.0,
        "id": "list_abc",
        "url": "https://work.mercor.com/explore?listingId=list_abc",
    }


def test_normalize_listing_rejects_non_dict():
    with pytest.raises(TypeError):
        normalize_listing(["not", "a", "dict"])


@pytest.mark.parametrize("bad", [None, "", "   ", 42, True])
def test_normalize_listing_rejects_unusable_listing_id(bad):
    with pytest.raises(ValueError):
        normalize_listing({"listingId": bad, "title": "Role"})


def test_normalize_listings_accepts_none_and_rejects_non_list():
    assert normalize_listings(None) == []
    with pytest.raises(TypeError):
        normalize_listings({"listings": []})


def test_normalize_listings_skips_non_dict_items():
    rows = normalize_listings([{"listingId": "x", "title": "t"}, "junk", None])
    assert [r["id"] for r in rows] == ["x"]
