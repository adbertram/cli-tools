"""Shared fixtures for ata-blog tests."""
import copy
import pytest
from unittest.mock import MagicMock

from ata_blog_cli import ads_scanner


@pytest.fixture(autouse=True)
def snapshot_scanner_defaults():
    """Prevent cross-test mutation of SCANNER_DEFAULTS."""
    snap = copy.deepcopy(ads_scanner.SCANNER_DEFAULTS)
    yield
    ads_scanner.SCANNER_DEFAULTS.clear()
    ads_scanner.SCANNER_DEFAULTS.update(snap)


@pytest.fixture(autouse=True)
def _warm_page_noop(monkeypatch, request):
    """Skip scroll-based warm-page in unit tests (real scroll + sleep blows timing budgets).

    Live e2e tests (`test_ads_scanner_live.py`) opt in by setting the
    `exercises_live_browser` marker.
    """
    if "exercises_live_browser" in request.keywords:
        return
    monkeypatch.setattr(ads_scanner, "_warm_page", lambda svc: None)


def _mk_service():
    svc = MagicMock()
    svc.__enter__ = MagicMock(return_value=svc)
    svc.__exit__ = MagicMock(return_value=False)
    return svc


@pytest.fixture
def mock_service():
    return _mk_service()


@pytest.fixture
def service_factory(mock_service):
    return lambda: mock_service


@pytest.fixture
def slot_payload_multi():
    """3 slots, 2 distinct advertisers (digicert repeats)."""
    return {
        "gptDetected": True,
        "slots": [
            {"slotId": "div-gpt-ad-h", "advertiserId": "4532817", "creativeId": "100", "lineItemId": "L1", "domain": "digicert.com"},
            {"slotId": "div-gpt-ad-s", "advertiserId": "5527701", "creativeId": "200", "lineItemId": "L2", "domain": "datadoghq.com"},
            {"slotId": "div-gpt-ad-i", "advertiserId": "4532817", "creativeId": "100", "lineItemId": "L1", "domain": "digicert.com"},
        ],
    }


@pytest.fixture
def slot_payload_empty_no_gpt():
    return {"gptDetected": False, "slots": []}


@pytest.fixture
def slot_payload_empty_with_gpt():
    return {"gptDetected": True, "slots": []}


@pytest.fixture
def sample_wp_post():
    return {
        "id": 26786,
        "slug": "how-to-sign-powershell-script",
        "title": "Sign PowerShell",
        "link": "https://adamtheautomator.com/how-to-sign-powershell-script",
    }


@pytest.fixture
def sample_wp_list():
    return [
        {"id": 1, "slug": "a", "link": "https://adamtheautomator.com/a"},
        {"id": 2, "slug": "b", "link": "https://adamtheautomator.com/b"},
        {"id": 3, "slug": "c", "link": "https://adamtheautomator.com/c"},
    ]
