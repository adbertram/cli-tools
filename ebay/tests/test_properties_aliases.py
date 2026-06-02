"""Regression tests for per-command property aliases used by compliance."""

from ebay_cli.properties import add_image_property_aliases, add_template_property_aliases


def test_template_property_aliases_include_id_and_name():
    templates = [
        {
            "name": "vintage-camera",
            "description": "Template for cameras",
        }
    ]

    aliased = add_template_property_aliases(templates)

    assert aliased == [
        {
            "id": "vintage-camera",
            "name": "vintage-camera",
            "description": "Template for cameras",
        }
    ]


def test_image_property_aliases_include_id_and_name_from_source():
    images = [
        {
            "image_id": "IMG-123",
            "original": "/tmp/photos/main-shot.jpg",
            "imageUrl": "https://example.test/image.jpg",
        },
        {
            "image_id": "IMG-456",
            "original": "https://cdn.example.test/uploads/hero.png",
            "imageUrl": "https://example.test/hero.png",
        },
    ]

    aliased = add_image_property_aliases(images)

    assert aliased[0]["id"] == "IMG-123"
    assert aliased[0]["name"] == "main-shot.jpg"
    assert aliased[1]["id"] == "IMG-456"
    assert aliased[1]["name"] == "hero.png"
