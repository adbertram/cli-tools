"""Regression tests for the Marketplace availability-only status path."""

import json
from contextlib import contextmanager

import pytest
from cli_tools_shared.exceptions import ClientError
from typer.testing import CliRunner

from facebook_cli.client import (
    INSTALL_DELIVERY_CAPTURE_JS,
    MARKETPLACE_STATUS_PAGE_JS,
    READ_DELIVERY_CAPTURE_JS,
    FacebookClient,
)
from facebook_cli.commands import marketplace as marketplace_commands


def _capture_stub(**overrides) -> dict:
    capture = {
        "deliveryTypes": {},
        "locationText": {},
        "availability": {},
        "primaryImage": {},
        "seller": {},
        "aliases": {},
        "conflicts": {},
        "availabilityConflicts": {},
        "aliasConflicts": {},
        "payloads": 1,
        "parseErrors": 0,
    }
    capture.update(overrides)
    return capture


class _FakePage:
    def __init__(self, results: dict):
        self._results = results

    def evaluate(self, js, arg=None):
        if js not in self._results:
            raise AssertionError(f"unexpected evaluate() call: {js[:60]!r}")
        return self._results[js]


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"is_sold": False, "is_pending": False, "is_live": True}, "Available"),
        ({"is_sold": True, "is_pending": False, "is_live": False}, "Sold"),
        ({"is_sold": False, "is_pending": True, "is_live": True}, "Pending"),
    ],
)
def test_status_reads_availability_when_delivery_types_are_absent(state, expected):
    page = _FakePage({
        MARKETPLACE_STATUS_PAGE_JS: {
            "unavailableProduct": False,
            "unavailableMessage": False,
        },
        INSTALL_DELIVERY_CAPTURE_JS: {"installed": True, "listings": 0},
        READ_DELIVERY_CAPTURE_JS: _capture_stub(availability={"999": state}),
    })
    client = FacebookClient.__new__(FacebookClient)

    assert client._extract_listing_status(page, "999") == {
        "item_id": "999",
        "status": "gone" if expected == "Sold" else "available",
        "availability": expected,
        "status_source": "listing_state",
        "url": "/marketplace/item/999/",
    }


def test_pending_status_remains_available_for_expiry_checks():
    page = _FakePage({
        MARKETPLACE_STATUS_PAGE_JS: {
            "unavailableProduct": False,
            "unavailableMessage": False,
        },
        INSTALL_DELIVERY_CAPTURE_JS: {"installed": True, "listings": 0},
        READ_DELIVERY_CAPTURE_JS: _capture_stub(
            availability={
                "999": {
                    "is_sold": False,
                    "is_pending": True,
                    "is_live": False,
                }
            }
        ),
    })
    client = FacebookClient.__new__(FacebookClient)

    result = client._extract_listing_status(page, "999")
    assert result["availability"] == "Pending"
    assert result["status"] == "available"


def test_status_resolves_a_post_id_through_the_availability_map():
    page = _FakePage({
        MARKETPLACE_STATUS_PAGE_JS: {
            "unavailableProduct": False,
            "unavailableMessage": False,
        },
        INSTALL_DELIVERY_CAPTURE_JS: {"installed": True, "listings": 0},
        READ_DELIVERY_CAPTURE_JS: _capture_stub(
            availability={
                "listing-id": {
                    "is_sold": True,
                    "is_pending": False,
                    "is_live": False,
                }
            },
            aliases={"post-id": "listing-id"},
        ),
    })
    client = FacebookClient.__new__(FacebookClient)

    assert client._extract_listing_status(page, "post-id")["availability"] == "Sold"


def test_status_fails_loudly_when_availability_is_absent():
    page = _FakePage({
        MARKETPLACE_STATUS_PAGE_JS: {
            "unavailableProduct": False,
            "unavailableMessage": False,
        },
        INSTALL_DELIVERY_CAPTURE_JS: {"installed": True, "listings": 1},
        READ_DELIVERY_CAPTURE_JS: _capture_stub(deliveryTypes={"999": ["IN_PERSON"]}),
    })
    client = FacebookClient.__new__(FacebookClient)

    with pytest.raises(ClientError, match="did not describe availability"):
        client._extract_listing_status(page, "999")


def test_status_accepts_facebooks_explicit_unavailable_page_without_listing_data():
    page = _FakePage({
        MARKETPLACE_STATUS_PAGE_JS: {
            "unavailableProduct": True,
            "unavailableMessage": True,
            "currentUrl": "https://www.facebook.com/marketplace/evansville/?unavailable_product=1",
        },
    })
    client = FacebookClient.__new__(FacebookClient)

    assert client._extract_listing_status(page, "999") == {
        "item_id": "999",
        "status": "gone",
        "availability": "Unavailable",
        "status_source": "unavailable_product_page",
        "url": "/marketplace/item/999/",
    }


def test_status_rejects_conflicting_unavailable_page_evidence():
    page = _FakePage({
        MARKETPLACE_STATUS_PAGE_JS: {
            "unavailableProduct": True,
            "unavailableMessage": False,
        },
    })
    client = FacebookClient.__new__(FacebookClient)

    with pytest.raises(ClientError, match="conflicting unavailable-page evidence"):
        client._extract_listing_status(page, "999")


def test_get_item_status_skips_full_detail_and_fulfillment_readers(monkeypatch):
    client = FacebookClient.__new__(FacebookClient)
    page = object()
    calls = []

    monkeypatch.setattr(client, "_get_page", lambda url: page)
    monkeypatch.setattr(client, "_dismiss_marketplace_login_dialog", lambda current: calls.append(("dismiss", current)))
    monkeypatch.setattr(client, "_assert_marketplace_authenticated", lambda current, url, label: calls.append(("auth", current, url, label)))
    monkeypatch.setattr(
        client,
        "_extract_listing_status",
        lambda current, item_id: {
            "item_id": item_id,
            "status": "available",
            "availability": "Available",
            "status_source": "listing_state",
            "url": f"/marketplace/item/{item_id}/",
        },
    )
    monkeypatch.setattr(client, "_extract_detail_page_info", lambda current: pytest.fail("full detail reader was called"))
    monkeypatch.setattr(client, "_extract_listing_fulfillment", lambda current, item_id: pytest.fail("fulfillment reader was called"))

    assert client.get_item_status("999")["availability"] == "Available"
    assert calls[0] == ("dismiss", page)
    assert calls[1][0] == "auth"


def test_marketplace_status_command_outputs_the_status_contract(monkeypatch):
    class _Client:
        def get_item_status(self, item_id):
            return {
                "item_id": item_id,
                "status": "gone",
                "availability": "Sold",
                "status_source": "listing_state",
                "url": f"/marketplace/item/{item_id}/",
            }

    @contextmanager
    def fake_client_session():
        yield _Client()

    monkeypatch.setattr(marketplace_commands, "client_session", fake_client_session)
    runner = CliRunner()
    result = runner.invoke(marketplace_commands.app, ["status", "999"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "item_id": "999",
        "status": "gone",
        "availability": "Sold",
        "status_source": "listing_state",
        "url": "/marketplace/item/999/",
    }
    assert marketplace_commands.COMMAND_CREDENTIALS["status"] == ["browser_session"]
