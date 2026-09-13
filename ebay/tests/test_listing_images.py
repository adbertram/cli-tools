"""Regression coverage for ordinary listing image capacity."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from ebay_cli.commands import listings
from ebay_cli.models.image import Image, MAX_IMAGES_PER_LISTING
from ebay_cli.models.inventory import Product
from ebay_cli.models.listing import Listing


def _image_urls(count: int) -> list[str]:
    return [f"https://example.test/image-{index}.jpg" for index in range(count)]


def test_ordinary_listing_models_accept_24_images_and_reject_25():
    urls = _image_urls(MAX_IMAGES_PER_LISTING)

    assert MAX_IMAGES_PER_LISTING == 24
    assert len(Product(title="Twenty-four images", image_urls=urls).image_urls) == 24
    assert len(
        Listing(
            sku="SKU-24-IMAGES",
            images=[Image(url=url, position=index) for index, url in enumerate(urls)],
        ).images
    ) == 24

    with pytest.raises(ValidationError):
        Image(url="https://example.test/image-24.jpg", position=24)

    with pytest.raises(ValidationError):
        Product(title="Too many images", image_urls=_image_urls(25))

    with pytest.raises(ValidationError):
        Listing(
            sku="SKU-25-IMAGES",
            images=[
                Image(url=url, position=index)
                for index, url in enumerate(_image_urls(25))
            ],
        )


def test_image_upload_attaches_all_24_ordinary_listing_images():
    urls = _image_urls(24)
    client = MagicMock()
    client.upload_image_from_url.side_effect = [
        {
            "image_id": f"image-{index}",
            "imageUrl": url,
            "expirationDate": "2026-12-31T00:00:00.000Z",
        }
        for index, url in enumerate(urls)
    ]
    client.get_inventory_item.return_value = {"product": {"imageUrls": []}}

    with patch("ebay_cli.storage.ImageStorage"):
        uploaded_urls, errors = listings._upload_images_for_listing(
            client,
            "SKU-24-IMAGES",
            None,
            ",".join(urls),
        )

    assert errors == []
    assert uploaded_urls == urls
    assert client.upload_image_from_url.call_count == 24
    update_payload = client.create_or_update_inventory_item.call_args.args[1]
    assert update_payload["product"]["imageUrls"] == urls
