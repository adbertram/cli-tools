"""Tests for Poshmark listing detail access."""

import pytest
from typer.testing import CliRunner

import cli_tools_shared.data_cache as data_cache
from poshmark_cli import client as client_module
from poshmark_cli import main
from poshmark_cli.parsers import normalize_item_detail


LISTING_URL = "https://poshmark.com/listing/example-6a8097f6721f58e5c2d0f19f"


def _raw_detail(availability="InStock"):
    return {
        "page_url": LISTING_URL,
        "login_required": False,
        "human_challenge": False,
        "seller_name": "timefortoys2014",
        "shipping_text": "$6.49 Shipping",
        "size": "One Size",
        "product": {
            "@type": "Product",
            "productID": "6a8097f6721f58e5c2d0f19f",
            "name": "LEGO Creator",
            "description": "Sealed new box",
            "image": "https://images.example/listing.jpg",
            "category": "Kids<Toys",
            "brand": {"@type": "Brand", "name": "Lego"},
            "offers": {
                "@type": "Offer",
                "price": "20.0",
                "priceCurrency": "USD",
                "availability": f"https://schema.org/{availability}",
                "itemCondition": "https://schema.org/NewCondition",
                "url": LISTING_URL,
            },
        },
    }


def test_normalize_item_detail_maps_live_product_shape():
    row = normalize_item_detail(_raw_detail())
    assert row["id"] == "6a8097f6721f58e5c2d0f19f"
    assert row["available"] is True
    assert row["available_fulfillment"] == ["shipping"]
    assert row["shipping_estimate"] == 6.49
    assert row["seller_name"] == "timefortoys2014"


def test_normalize_item_detail_maps_sold_product():
    row = normalize_item_detail(_raw_detail("OutOfStock"))
    assert row["available"] is False
    assert row["available_fulfillment"] == []


class _FakePage:
    def __init__(self, payload):
        self.payload = payload
        self.wait_call = None

    def wait_for_selector(self, *args, **kwargs):
        self.wait_call = (args, kwargs)
        return None

    def evaluate(self, script):
        return self.payload


class _FakeBrowser:
    def __init__(self, payload):
        self.payload = payload
        self.requested_url = None
        self.closed = False
        self.page = None

    def get_page(self, url):
        self.requested_url = url
        self.page = _FakePage(self.payload)
        return self.page

    def close(self):
        self.closed = True


def test_client_get_listing_uses_exact_direct_url(monkeypatch):
    monkeypatch.setattr(data_cache, "is_cache_enabled", lambda: False)
    browser = _FakeBrowser(_raw_detail())
    client = client_module.PoshmarkClient()
    client._browser = browser
    row = client.get_listing(LISTING_URL)
    assert browser.requested_url == LISTING_URL
    assert browser.page.wait_call == (
        ('script[type="application/ld+json"]',),
        {"state": "attached", "timeout": 30000},
    )
    assert row["available"] is True


def test_client_get_listing_rejects_non_listing_url(monkeypatch):
    monkeypatch.setattr(data_cache, "is_cache_enabled", lambda: False)
    client = client_module.PoshmarkClient()
    with pytest.raises(client_module.ClientError, match="24-character listing ID or direct https://poshmark.com/listing"):
        client.get_listing("https://example.com/item/1")


def test_client_get_listing_resolves_id_to_listing_url(monkeypatch):
    monkeypatch.setattr(data_cache, "is_cache_enabled", lambda: False)
    browser = _FakeBrowser(_raw_detail())
    client = client_module.PoshmarkClient()
    client._browser = browser

    row = client.get_listing("6a8097f6721f58e5c2d0f19f")

    assert browser.requested_url == "https://poshmark.com/listing/6a8097f6721f58e5c2d0f19f"
    assert row["id"] == "6a8097f6721f58e5c2d0f19f"


def test_client_get_listing_returns_structured_challenge(monkeypatch):
    monkeypatch.setattr(data_cache, "is_cache_enabled", lambda: False)
    payload = _raw_detail()
    payload["human_challenge"] = True
    browser = _FakeBrowser(payload)
    client = client_module.PoshmarkClient()
    client._browser = browser
    with pytest.raises(client_module.ListingDetailBlocked) as exc:
        client.get_listing(LISTING_URL)
    assert exc.value.as_dict()["blocker_type"] == "human_challenge"


def test_listings_get_routes_to_client_and_closes(monkeypatch):
    class _FakeClient:
        def __init__(self):
            self.closed = False

        def get_listing(self, listing_url):
            assert listing_url == LISTING_URL
            return normalize_item_detail(_raw_detail())

        def close(self):
            self.closed = True

    fake = _FakeClient()
    monkeypatch.setattr(main, "get_client", lambda: fake)
    result = CliRunner().invoke(main.app, ["listings", "get", LISTING_URL])
    assert result.exit_code == 0
    assert '"seller_name": "timefortoys2014"' in result.stdout
    assert fake.closed is True
