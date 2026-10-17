"""Shared pytest fixtures for the trainee-digital CLI tests.

Fixture payloads are the real captured API responses under tests/fixtures/,
each saved as ``{"path": <requested path>, "status": <http status>,
"body": <parsed response body>}``. Captured live 2026-09-03 from Adam's
authenticated trainee.digital session (see the fixtures themselves for the
request paths).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str):
    with open(FIXTURES_DIR / name, encoding="utf-8") as fh:
        payload = json.load(fh)
    assert payload["status"] == 200, f"{name} fixture is not a 200 capture"
    return payload["body"]


@pytest.fixture(scope="session")
def orders_list_body():
    """Raw body of GET /api/orders (6 live records)."""
    return _load("orders_list.json")


@pytest.fixture(scope="session")
def order_detail_body():
    """Raw body of GET /api/orders/med-seg (full detail incl. guidelines)."""
    return _load("orders_detail_med-seg.json")
