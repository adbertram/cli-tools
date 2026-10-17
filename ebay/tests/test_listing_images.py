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


# =============================================================================
# Upload retry and fail-before-offer (a dropped hero image must stop the create)
# =============================================================================


def _uploaded(name: str) -> dict:
    return {
        "image_id": f"id-{name}",
        "imageUrl": f"https://i.ebayimg.test/{name}",
        "expirationDate": "2026-12-31T00:00:00.000Z",
    }


def _write_images(tmp_path, *names: str) -> list[str]:
    paths = []
    for name in names:
        path = tmp_path / name
        path.write_bytes(b"jpeg")
        paths.append(str(path))
    return paths


TIMEOUT = ConnectionError(
    "('Connection aborted.', TimeoutError('The write operation timed out'))"
)


def _upload(client, paths):
    client.get_inventory_item.return_value = {"product": {"imageUrls": []}}
    with patch("ebay_cli.storage.ImageStorage"):
        return listings._upload_images_for_listing(client, "SKU-RETRY", ",".join(paths), None)


def test_image_upload_succeeds_first_try_without_retry(tmp_path):
    paths = _write_images(tmp_path, "01-main.jpeg")
    client = MagicMock()
    client.upload_image_from_file.side_effect = [_uploaded("main")]

    uploaded_urls, errors = _upload(client, paths)

    assert errors == []
    assert uploaded_urls == ["https://i.ebayimg.test/main"]
    assert client.upload_image_from_file.call_count == 1


def test_image_upload_retries_once_after_timeout_and_keeps_the_image(tmp_path, capsys):
    paths = _write_images(tmp_path, "01-00-main-IMG_0090.jpeg", "02-side.jpeg")
    client = MagicMock()
    client.upload_image_from_file.side_effect = [TIMEOUT, _uploaded("main"), _uploaded("side")]

    uploaded_urls, errors = _upload(client, paths)

    assert errors == []
    assert uploaded_urls == ["https://i.ebayimg.test/main", "https://i.ebayimg.test/side"]
    assert [c.args[0] for c in client.upload_image_from_file.call_args_list] == [
        paths[0], paths[0], paths[1]
    ]
    assert "(attempt 1/2)" in capsys.readouterr().err


def test_image_upload_reports_failure_after_second_attempt(tmp_path):
    paths = _write_images(tmp_path, "01-00-main-IMG_0090.jpeg", "02-side.jpeg")
    client = MagicMock()
    client.upload_image_from_file.side_effect = [TIMEOUT, TIMEOUT, _uploaded("side")]

    uploaded_urls, errors = _upload(client, paths)

    assert uploaded_urls == ["https://i.ebayimg.test/side"]
    assert errors == [{"source": paths[0], "error": str(TIMEOUT)}]
    assert client.upload_image_from_file.call_count == 3


def _create_args(image_paths: list[str]) -> list[str]:
    return [
        "create",
        "--sku", "SKU-RETRY",
        "--title", "Retry test listing",
        "--description", "Testing image retry",
        "--price", "19.99",
        "--category", "175673",
        "--format", "FIXED_PRICE",
        "--fulfillment-policy", "F-POLICY",
        "--payment-policy", "P-POLICY",
        "--return-policy", "R-POLICY",
        "--location", "warehouse-1",
        "--condition", "USED_GOOD",
        "--weight", "1",
        "--dimensions", "10x8x6",
        "--image", ",".join(image_paths),
        "--publish",
    ]


def _create_client(upload_side_effect) -> MagicMock:
    client = MagicMock()
    client.upload_image_from_file.side_effect = upload_side_effect
    client.get_inventory_item.return_value = {"product": {"imageUrls": []}}
    client.create_offer.return_value = {"offerId": "OFFER-1"}
    client.publish_offer.return_value = {"listingId": "110000000001"}
    return client


def test_listings_create_exits_before_offer_when_an_image_fails_twice(runner, tmp_path):
    paths = _write_images(tmp_path, "01-00-main-IMG_0090.jpeg", "02-side.jpeg")
    client = _create_client([TIMEOUT, TIMEOUT, _uploaded("side")])

    with patch("ebay_cli.commands.listings.get_client", return_value=client), patch(
        "ebay_cli.commands.listings._validate_condition_for_category"
    ), patch("ebay_cli.storage.ImageStorage"):
        result = runner.invoke(listings.app, _create_args(paths))

    assert result.exit_code == 1
    assert paths[0] in result.stderr
    assert "no offer was created or published" in result.stderr
    client.create_offer.assert_not_called()
    client.publish_offer.assert_not_called()


def test_listings_create_publishes_when_retry_recovers_the_image(runner, tmp_path):
    paths = _write_images(tmp_path, "01-00-main-IMG_0090.jpeg")
    client = _create_client([TIMEOUT, _uploaded("main")])

    with patch("ebay_cli.commands.listings.get_client", return_value=client), patch(
        "ebay_cli.commands.listings._validate_condition_for_category"
    ), patch("ebay_cli.storage.ImageStorage"):
        result = runner.invoke(listings.app, _create_args(paths))

    assert result.exit_code == 0, result.stderr
    client.create_offer.assert_called_once()
    client.publish_offer.assert_called_once_with("OFFER-1")
