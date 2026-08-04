"""Parser tests against real captured Vinted data."""

import json
from pathlib import Path

import pytest
from cli_tools_shared.exceptions import ClientError

from vinted_cli.parsers import normalize_listing, parse_item_page, parse_shipping

FIXTURE = Path(__file__).parent / "fixtures" / "item_page.html"


def _rsc(*payloads):
    """Wrap payload text the way an item page ships its data chunks."""
    return "".join(
        f"<script>self.__next_f.push([1,{json.dumps(payload)}])</script>"
        for payload in payloads
    )


# One real record from GET /api/v2/catalog/items, trimmed to the fields the
# normalizer reads.
CATALOG_ITEM = {
    "id": 9571854910,
    "title": "Lego instructions manuals",
    "url": "https://www.vinted.com/items/9571854910-lego-instructions-manuals",
    "price": {"amount": "12.0", "currency_code": "USD"},
    "total_item_price": {"amount": "13.05", "currency_code": "USD"},
    "brand_title": "LEGO",
    "size_title": None,
    "status": "Good",
    "favourite_count": 3,
    "view_count": 41,
    "is_visible": True,
    "promoted": False,
    "user": {
        "id": 3158562024,
        "login": "jamesy593",
        "profile_url": "https://www.vinted.com/member/3158562024-jamesy593",
    },
    "photo": {
        "url": "https://images1.vinted.net/t/05_02053/f800/1779885202.jpeg",
        "high_resolution": {"id": "05_02053", "timestamp": 1785850326},
    },
}


def test_normalize_listing_flattens_nested_api_fields():
    record = normalize_listing(CATALOG_ITEM)

    assert record == {
        "id": 9571854910,
        "title": "Lego instructions manuals",
        "url": "https://www.vinted.com/items/9571854910-lego-instructions-manuals",
        "listed_at": "2026-08-04T13:32:06+00:00",
        "price": "12.0",
        "currency": "USD",
        "total_price": "13.05",
        "brand": "LEGO",
        "size": None,
        "condition": "Good",
        "favourite_count": 3,
        "view_count": 41,
        "is_visible": True,
        "promoted": False,
        "seller_id": 3158562024,
        "seller_login": "jamesy593",
        "seller_url": "https://www.vinted.com/member/3158562024-jamesy593",
        "photo_url": "https://images1.vinted.net/t/05_02053/f800/1779885202.jpeg",
    }


def test_listed_at_is_the_recency_signal_the_default_sort_follows():
    """Vinted's `newest_first` order follows photo.high_resolution.timestamp.

    The listing ID does not track recency, so this field is how a caller
    verifies that results really are newest first.
    """
    newest = normalize_listing({
        **CATALOG_ITEM,
        "photo": {"high_resolution": {"timestamp": 1785850326}},
    })
    older = normalize_listing({
        **CATALOG_ITEM,
        "photo": {"high_resolution": {"timestamp": 1785849952}},
    })

    assert newest["listed_at"] == "2026-08-04T13:32:06+00:00"
    assert newest["listed_at"] > older["listed_at"]


@pytest.mark.parametrize(
    "photo",
    [
        {},
        {"high_resolution": {}},
        {"high_resolution": None},
        {"high_resolution": {"timestamp": None}},
        {"high_resolution": {"timestamp": "1785850326"}},
        {"high_resolution": {"timestamp": True}},
    ],
)
def test_listed_at_is_none_when_the_timestamp_is_absent_or_wrong_typed(photo):
    assert normalize_listing({**CATALOG_ITEM, "photo": photo})["listed_at"] is None


def test_normalize_listing_maps_size_from_size_title():
    record = normalize_listing({**CATALOG_ITEM, "size_title": "M"})

    assert record["size"] == "M"


def test_normalize_listing_tolerates_absent_nested_objects():
    record = normalize_listing({"id": 5})

    assert record["id"] == 5
    assert record["price"] is None
    assert record["seller_login"] is None


def test_normalize_listing_blames_vinted_for_a_listing_with_no_id():
    """A ClientError names the service. A bare KeyError reads as a CLI bug."""
    with pytest.raises(ClientError, match="Vinted returned a catalog listing with no id"):
        normalize_listing({"title": "no id"})


@pytest.mark.parametrize(
    "field, bad_value",
    [
        ("price", "12.00"),
        ("price", [{"amount": "12.0"}]),
        ("total_item_price", "13.05"),
        ("user", [{"id": 1}]),
        ("user", "jamesy593"),
        ("photo", "https://images1.vinted.net/x.jpg"),
    ],
)
def test_normalize_listing_survives_a_wrong_typed_nested_field(field, bad_value):
    """One malformed record must not raise and kill the other 95 on the page."""
    record = normalize_listing({**CATALOG_ITEM, field: bad_value})

    assert record["id"] == 9571854910


def test_parse_item_page_reads_the_page_that_has_no_ld_json():
    """The fixture is listing 9573431534, captured live.

    That listing is hidden, so Vinted served no `application/ld+json` block at
    all. The old parser failed on it. The payload carries every field.
    """
    record = parse_item_page(
        FIXTURE.read_text(encoding="utf-8"),
        "9573431534",
        "https://www.vinted.com/items/9573431534-lego-21348",
    )

    assert record == {
        "id": "9573431534",
        "title": "LEGO 21348",
        "url": "https://www.vinted.com/items/9573431534-lego-21348",
        "description": (
            "[New] LEGO 21348 IDEAS DUNGEONS & DRAGONS Red Dragon's Tale "
            "CINDERHOWL WOTC RARE"
        ),
        "price": "180",
        "currency": "USD",
        "total_price": "189.7",
        "brand": "LEGO",
        "category": "Kids / Toys / Blocks & building toys",
        "catalog_id": 1767,
        "seller_id": 3173484089,
        "size": "Preemie",
        "condition": "Very good",
        "color": "Multi, Black",
        "is_reserved": False,
        "is_hidden": True,
        "is_closed": False,
        "shipping": {
            "price": "0",
            "currency": "USD",
            "discount": None,
            "free": True,
            "pickup_only": False,
            "multiple_options": True,
        },
        "photo_url": (
            "https://images1.vinted.net/t/01_00173_ffp4dpXGQJZG2xN82bFEvzx2/f800/"
            "1785854280.webp?s=3226df50587e2d4bf2c461b1e32e93e02e26f472"
        ),
    }


def test_parse_item_page_keeps_the_url_the_request_landed_on():
    record = parse_item_page(FIXTURE.read_text(encoding="utf-8"), "9573431534", "https://x/1")

    assert record["url"] == "https://x/1"


def test_parse_item_page_fails_when_the_item_data_is_gone():
    with pytest.raises(ClientError, match="no item data"):
        parse_item_page("<html><body>no data</body></html>", "1", "https://x/1")


def test_parse_item_page_fails_when_the_payload_is_for_another_listing():
    """The marker carries the listing ID, so a wrong page cannot pass silently."""
    with pytest.raises(ClientError, match="no item data"):
        parse_item_page(FIXTURE.read_text(encoding="utf-8"), "1", "https://x/1")


def test_parse_item_page_reports_a_missing_plugin_as_null():
    """Vinted omits a plugin the listing does not use. That is not an error."""
    html = _rsc('{"item":{"id":1,"title":"x","currency":"USD"}}')

    record = parse_item_page(html, "1", "https://x/1")

    assert record["title"] == "x"
    assert record["currency"] == "USD"
    for field in ("description", "category", "size", "condition", "color",
                  "photo_url", "shipping", "price", "total_price", "brand"):
        assert record[field] is None, field


def test_parse_item_page_drops_the_brand_scoped_breadcrumb():
    """The last breadcrumb repeats the category with the brand in front."""
    html = _rsc(
        '{"item":{"id":1,"title":"x"}}'
        '{"name":"breadcrumbs","type":"breadcrumbs","data":{"breadcrumbs":['
        '{"title":"Kids","url":"/catalog/1193-kids"},'
        '{"title":"Toys","url":"/catalog/1499-toys"},'
        '{"title":"LEGO Toys","url":"/catalog/1499-toys/brand/89162-lego"}]}}'
    )

    assert parse_item_page(html, "1", "https://x/1")["category"] == "Kids / Toys"


def test_parse_item_page_reads_only_the_attribute_codes_it_reports():
    html = _rsc(
        '{"item":{"id":1,"title":"x"}}'
        '{"name":"attributes","type":"attributes","data":{"attributes":['
        '{"type":"favouritable","code":"brand","data":{"value":"IGNORED"}},'
        '{"type":"faq","code":"size","data":{"value":"M"}},'
        '{"type":"faq","code":"status","data":{"value":"Good"}},'
        '{"type":"text","code":"color","data":{"value":"Red"}},'
        '{"type":"text","code":"upload_date","data":{"value":"19 min ago"}}]}}'
    )

    record = parse_item_page(html, "1", "https://x/1")

    assert (record["size"], record["condition"], record["color"]) == ("M", "Good", "Red")
    # `brand` comes from the item object, never from the attribute list.
    assert record["brand"] is None


def test_parse_item_page_survives_a_wrong_typed_plugin_payload():
    html = _rsc(
        '{"item":{"id":1,"title":"x","brand_dto":"LEGO"}}'
        '{"name":"attributes","type":"attributes","data":{"attributes":"gone"}}'
        '{"name":"breadcrumbs","type":"breadcrumbs","data":"gone"}'
        '{"name":"gallery","type":"gallery","data":{"photos":[null,7]}}'
    )

    record = parse_item_page(html, "1", "https://x/1")

    assert record["brand"] is None
    assert record["size"] is None
    assert record["category"] is None
    assert record["photo_url"] is None


def test_parse_item_page_preserves_unicode_content():
    html = _rsc(
        '{"item":{"id":1,"title":"Lego Gr\\u00f6\\u00dfe 42"}}'
        '{"name":"description","type":"description","data":{"description":"na\\u00efve & more"}}'
    )

    record = parse_item_page(html, "1", "https://x/1")

    assert record["title"] == "Lego Größe 42"
    assert record["description"] == "naïve & more"


def test_parse_item_page_reports_an_unreadable_money_value():
    html = _rsc('{"item":{"id":1,"title":"x"}}{"originalAskingAmount":oops}')

    with pytest.raises(ClientError, match="unreadable value for originalAskingAmount"):
        parse_item_page(html, "1", "https://x/1")


# --- shipping figures ------------------------------------------------------
#
# `shippingDetails` is the buyer facing summary Vinted renders. The object below
# is copied from a live item page. Vinted also renders a lower level shipping
# object twice, with two different undiscounted prices, so the parser reads this
# summary instead. Verified live on listing 9573431534: the two lower level
# objects reported 5.68 and 8.45 while both summaries reported the same figures.

_FREE = (
    '{"isPickupOnly":false,"areMultipleShippingOptionsAvailable":true,'
    '"isFreeShipping":true,"price":{"amount":"0","currencyCode":"USD"},'
    '"discount":null}'
)
_PRICED = (
    '{"isPickupOnly":false,"areMultipleShippingOptionsAvailable":true,'
    '"isFreeShipping":false,"price":{"amount":"4.99","currencyCode":"GBP"},'
    '"discount":{"amount":"1.70","currencyCode":"GBP"}}'
)
_PICKUP = (
    '{"isPickupOnly":true,"areMultipleShippingOptionsAvailable":false,'
    '"isFreeShipping":false,"price":null,"discount":null}'
)


def test_parse_shipping_reads_the_live_free_summary():
    result = parse_shipping(_rsc('{"shippingDetails":' + _FREE + "}"))

    assert result == {
        "price": "0",
        "currency": "USD",
        "discount": None,
        "free": True,
        "pickup_only": False,
        "multiple_options": True,
    }


def test_parse_shipping_reads_a_priced_summary():
    result = parse_shipping(_rsc('{"shippingDetails":' + _PRICED + "}"))

    assert result == {
        "price": "4.99",
        "currency": "GBP",
        "discount": "1.70",
        "free": False,
        "pickup_only": False,
        "multiple_options": True,
    }


def test_parse_shipping_reports_a_pickup_only_listing():
    result = parse_shipping(_rsc('{"shippingDetails":' + _PICKUP + "}"))

    assert result["pickup_only"] is True
    assert result["price"] is None


def test_parse_shipping_joins_a_summary_split_across_chunks():
    """A React Server Component chunk can end in the middle of the object."""
    body = '{"shippingDetails":' + _FREE + "}"
    split = len(body) // 2

    assert parse_shipping(_rsc(body[:split], body[split:]))["price"] == "0"


def test_parse_shipping_ignores_a_push_that_is_not_a_data_chunk():
    html = "<script>self.__next_f.push([0])</script>" + _rsc(
        '{"shippingDetails":' + _FREE + "}"
    )

    assert parse_shipping(html)["free"] is True


def test_parse_shipping_steps_past_a_push_it_cannot_decode():
    html = "<script>self.__next_f.push(window.x)</script>" + _rsc(
        '{"shippingDetails":' + _FREE + "}"
    )

    assert parse_shipping(html)["free"] is True


def test_parse_shipping_returns_none_without_a_summary():
    """Verified live: a listing with no shipping carries no summary."""
    assert parse_shipping(_rsc('{"item":{"id":1}}')) is None


def test_parse_shipping_returns_none_for_a_page_with_no_payload():
    assert parse_shipping("<html><body>nothing here</body></html>") is None


def test_parse_shipping_survives_a_money_field_that_changed_type():
    html = _rsc('{"shippingDetails":{"price":"0","isFreeShipping":true}}')

    result = parse_shipping(html)

    assert result["price"] is None
    assert result["currency"] is None
    assert result["free"] is True


def test_parse_item_page_includes_the_shipping_figures():
    html = _rsc('{"item":{"id":1,"title":"x"}}{"shippingDetails":' + _FREE + "}")

    record = parse_item_page(html, "1", "https://x/1")

    assert record["shipping"]["price"] == "0"
    assert record["shipping"]["free"] is True
