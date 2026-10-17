"""Shared pytest fixtures for the mercor CLI tests.

Fixtures load the REAL captured API and DOM snapshots under
``tests/fixtures/`` (captured live 2026-09-03 from Adam's authenticated Mercor
worker session; see README for provenance), so parser tests exercise real
records rather than synthetic ones.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def listings_payload() -> dict:
    """The API envelope: ``{"listings": [<8 real records>]}``."""
    return json.loads(
        (FIXTURES / "listings_explore_page.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def listing_records(listings_payload: dict) -> list:
    records = listings_payload["listings"]
    assert isinstance(records, list) and records, "fixture must hold listings"
    return records
