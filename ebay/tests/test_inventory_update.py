"""Regression coverage for inventory image replacement."""

import json
from copy import deepcopy
from unittest.mock import MagicMock, patch

from ebay_cli.commands import inventory
from ebay_cli.models.image import MAX_IMAGES_PER_LISTING


def _inventory_item(image_urls: list[str]) -> dict:
    return {
        "sku": "EBAY-IMAGE-UPDATE",
        "locale": "en_US",
        "condition": "USED_GOOD",
        "availability": {"shipToLocationAvailability": {"quantity": 1}},
        "product": {
            "title": "Image replacement test item",
            "imageUrls": image_urls,
        },
    }


def test_inventory_update_replaces_images_and_returns_verified_item_json(runner):
    old_urls = ["https://example.test/old-1.jpg", "https://example.test/old-2.jpg"]
    new_urls = [
        f"https://example.test/new-{index}.jpg"
        for index in range(MAX_IMAGES_PER_LISTING)
    ]
    client = MagicMock()
    client.get_inventory_item.side_effect = [
        _inventory_item(old_urls),
        _inventory_item(new_urls),
    ]

    with patch("ebay_cli.commands.inventory.get_client", return_value=client):
        result = runner.invoke(
            inventory.app,
            ["update", "EBAY-IMAGE-UPDATE", "--images", ",".join(new_urls)],
        )

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["product"]["imageUrls"] == new_urls
    client.create_or_update_inventory_item.assert_called_once_with(
        "EBAY-IMAGE-UPDATE",
        {
            "condition": "USED_GOOD",
            "availability": {"shipToLocationAvailability": {"quantity": 1}},
            "product": {
                "title": "Image replacement test item",
                "imageUrls": new_urls,
            },
        },
    )


def test_inventory_update_fails_when_image_readback_does_not_match(runner):
    old_urls = ["https://example.test/old-1.jpg", "https://example.test/old-2.jpg"]
    new_urls = ["https://example.test/new-1.jpg", "https://example.test/new-2.jpg"]
    client = MagicMock()
    client.get_inventory_item.side_effect = [
        _inventory_item(old_urls),
        deepcopy(_inventory_item(old_urls)),
    ]

    with patch("ebay_cli.commands.inventory.get_client", return_value=client):
        result = runner.invoke(
            inventory.app,
            ["update", "EBAY-IMAGE-UPDATE", "--images", ",".join(new_urls), "--table"],
        )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "image update was not applied" in result.stderr
