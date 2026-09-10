"""Quota protection: sold-comp search is cached, active search never is.

The SoldComps plan is metered (2,000 requests a month on Starter), so an
uncached repeat price check is the main way to burn quota for nothing. Sold
comps are historical — a listing that ended last Tuesday still ended last
Tuesday tomorrow — so an identical repeat must cost zero requests, while
`--no-cache` must still reach the API. Active listings are the opposite: their
whole value is "what is live right now", so they are never served from disk.
"""

import json

import pytest

from cli_tools_shared.credentials import CredentialType

from ebay_cli import soldcomps_client as soldcomps_module
from ebay_cli.soldcomps_client import SoldCompsClient


class CountingResponse:
    def __init__(self, payload):
        self.status_code = 200
        self.ok = True
        self.headers = {"X-Usage-Remaining": "1873"}
        self.url = "https://api.sold-comps.com/v1/scrape"
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class CountingSession:
    """Answers every request identically and counts how many arrived."""

    def __init__(self, payload):
        self.payload = payload
        self.request_count = 0

    def get(self, url, params=None, headers=None, timeout=None):
        self.request_count += 1
        return CountingResponse(self.payload)

    def close(self):
        pass


class MixedCredentialConfig:
    """eBay's real shape: OAuth *and* a browser session, with no session saved.

    The shared cache decorator used to refuse every cached read on a config like
    this whenever no browser login existed, which would have spent a paid
    request on every repeat search.
    """

    CREDENTIAL_TYPES = [
        CredentialType.OAUTH_AUTHORIZATION_CODE,
        CredentialType.BROWSER_SESSION,
    ]

    def __init__(self, storage_dir):
        self.storage_dir = storage_dir

    def has_saved_session(self) -> bool:
        return False


ITEM = {
    "itemId": "226554128899",
    "title": "LEGO Star Wars 75192 Millennium Falcon UCS",
    "url": "https://www.ebay.com/itm/226554128899",
    "listingType": "sold",
    "buyingFormat": "buyItNow",
    "soldPrice": 612,
    "soldCurrency": "USD",
    "endedAt": "2026-08-30",
}
ENVELOPE = {"keyword": "LEGO 75192", "page": 1, "hasNextPage": False, "items": [ITEM]}

ACTIVE_ITEM = dict(ITEM, listingType="active", currentPrice=41.25, currentCurrency="USD")
ACTIVE_ENVELOPE = {"keyword": "x", "page": 1, "hasNextPage": False, "items": [ACTIVE_ITEM]}


@pytest.fixture
def counted(tmp_path, monkeypatch):
    """A client whose HTTP requests are counted, with caching switched on."""
    monkeypatch.setenv("CACHE_ENABLED", "true")
    monkeypatch.delenv("CACHE_TTL", raising=False)
    monkeypatch.setattr(
        soldcomps_module, "read_cli_tool_secret", lambda name: "sc_test_key"
    )

    def build(payload):
        client = SoldCompsClient(config=MixedCredentialConfig(tmp_path))
        client._session = CountingSession(payload)
        return client

    return build


def test_repeating_a_sold_search_spends_no_second_request(counted):
    client = counted(ENVELOPE)

    first = client.search_sold(keywords="LEGO 75192", limit=5)
    second = client.search_sold(keywords="LEGO 75192", limit=5)

    assert client._session.request_count == 1
    assert [row.to_dict() for row in first] == [row.to_dict() for row in second]


def test_no_cache_forces_the_second_request(counted, monkeypatch):
    """The global --no-cache flag sets CACHE_ENABLED=false for the run."""
    client = counted(ENVELOPE)
    client.search_sold(keywords="LEGO 75192", limit=5)
    assert client._session.request_count == 1

    monkeypatch.setenv("CACHE_ENABLED", "false")
    client.search_sold(keywords="LEGO 75192", limit=5)
    assert client._session.request_count == 2


def test_a_different_search_is_not_served_from_another_searchs_cache(counted):
    """A narrowed search must never read a broader search's stored answer."""
    client = counted(ENVELOPE)

    client.search_sold(keywords="LEGO 75192", limit=5)
    client.search_sold(keywords="LEGO 75192", limit=5, us_only=True)
    client.search_sold(keywords="LEGO 75193", limit=5)
    client.search_sold(keywords="LEGO 75192", limit=6)
    client.search_sold(keywords="LEGO 75192", limit=5, sort_order="pricePlusPostageLowest")

    assert client._session.request_count == 5


def test_active_search_is_never_served_from_disk(counted):
    client = counted(ACTIVE_ENVELOPE)

    client.search_active(keywords="LEGO bulk lot", limit=5)
    client.search_active(keywords="LEGO bulk lot", limit=5)

    assert client._session.request_count == 2
