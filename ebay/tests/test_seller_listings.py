"""Regression tests for seller listing reads."""

import json
from unittest.mock import MagicMock

import pytest

from ebay_cli.client import ClientError
from ebay_cli.commands import listings
from ebay_cli.main import app


SOLD_LIST_XML = """<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Success</Ack>
  <SoldList>
    <OrderTransactionArray>
      <OrderTransaction>
        <Transaction>
          <Item>
            <ItemID>178374167880</ItemID>
            <SKU>EBAY-20260804130425</SKU>
            <Title>LEGO Wheel</Title>
            <ListingType>Chinese</ListingType>
            <SellingStatus>
              <CurrentPrice currencyID="USD">17.5</CurrentPrice>
              <QuantitySold>1</QuantitySold>
            </SellingStatus>
          </Item>
        </Transaction>
      </OrderTransaction>
    </OrderTransactionArray>
    <PaginationResult>
      <TotalNumberOfPages>1</TotalNumberOfPages>
    </PaginationResult>
  </SoldList>
</GetMyeBaySellingResponse>
"""

EMPTY_SOLD_LIST_XML = """<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Success</Ack>
  <SoldList>
    <OrderTransactionArray />
    <PaginationResult>
      <TotalNumberOfPages>1</TotalNumberOfPages>
    </PaginationResult>
  </SoldList>
</GetMyeBaySellingResponse>
"""

ACK_FAILURE_XML = """<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Failure</Ack>
  <Errors><LongMessage>Invalid token</LongMessage></Errors>
</GetMyeBaySellingResponse>
"""

SOLD_LIST_MIXED_TRANSACTION_XML = """<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Success</Ack>
  <SoldList>
    <OrderTransactionArray>
      <OrderTransaction>
        <Transaction>
          <Item>
            <ItemID>100000000001</ItemID>
            <Title>First item without a SKU</Title>
            <ListingType>FixedPriceItem</ListingType>
            <SellingStatus>
              <CurrentPrice currencyID="USD">10.00</CurrentPrice>
              <QuantitySold>1</QuantitySold>
            </SellingStatus>
          </Item>
        </Transaction>
      </OrderTransaction>
      <OrderTransaction>
        <Order>
          <TransactionArray>
            <Transaction>
              <Item>
                <ItemID>100000000002</ItemID>
                <SKU>SECOND-SKU</SKU>
                <Title>Second nested order item</Title>
                <ListingType>Chinese</ListingType>
                <SellingStatus>
                  <CurrentPrice currencyID="USD">20.00</CurrentPrice>
                  <QuantitySold>2</QuantitySold>
                </SellingStatus>
              </Item>
            </Transaction>
          </TransactionArray>
        </Order>
      </OrderTransaction>
    </OrderTransactionArray>
    <PaginationResult>
      <TotalNumberOfPages>1</TotalNumberOfPages>
    </PaginationResult>
  </SoldList>
</GetMyeBaySellingResponse>
"""

UNSOLD_LIST_XML = """<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Success</Ack>
  <UnsoldList>
    <ItemArray>
      <Item>
        <ItemID>188888888888</ItemID>
        <SKU>UNSOLD-SKU</SKU>
        <Title>Unsold LEGO Wheel</Title>
        <ListingType>FixedPriceItem</ListingType>
        <SellingStatus>
          <CurrentPrice currencyID="USD">12.00</CurrentPrice>
          <QuantitySold>0</QuantitySold>
        </SellingStatus>
      </Item>
    </ItemArray>
    <PaginationResult>
      <TotalNumberOfPages>1</TotalNumberOfPages>
    </PaginationResult>
  </UnsoldList>
</GetMyeBaySellingResponse>
"""


def _client_for_xml(xml: str):
    client = MagicMock()
    client._make_trading_api_request.return_value = xml
    return client


def _draft_offer(
    *,
    offer_id: str = "offer-auction",
    item_id: str = "178374156402",
    format_type: str = "AUCTION",
) -> dict:
    price_key = "auctionStartPrice" if format_type == "AUCTION" else "price"
    return {
        "offerId": offer_id,
        "sku": "EBAY-20260804130425",
        "status": "UNPUBLISHED",
        "format": format_type,
        "listing": {"listingId": item_id},
        "pricingSummary": {
            price_key: {"value": "75.0", "currency": "USD"},
        },
        "availableQuantity": 1,
    }


def _active_offer(*, item_id: str = "current-item") -> dict:
    offer = _draft_offer(item_id=item_id)
    offer["status"] = "PUBLISHED"
    return offer


def _ambiguous_offers() -> dict:
    return {
        "offers": [
            _draft_offer(),
            _draft_offer(
                offer_id="offer-fixed",
                item_id="178374156403",
                format_type="FIXED_PRICE",
            ),
        ],
        "size": 2,
    }


def _inventory_item() -> dict:
    return {
        "product": {"title": "LEGO Wheel", "description": "Wheel listing"},
        "condition": "USED_GOOD",
        "availability": {"shipToLocationAvailability": {"quantity": 1}},
    }


def _active_trading_item(*, item_id: str, price: str = "17.5") -> dict:
    return {
        "item_id": item_id,
        "sku": "EBAY-20260804130425",
        "title": "LEGO Wheel",
        "listing_type": "Chinese",
        "price": price,
        "currency": "USD",
        "quantity": 1,
        "quantity_sold": 1,
        "url": f"https://www.ebay.com/itm/{item_id}",
    }


def test_should_preserve_sold_format_and_current_price_from_get_my_ebay_selling():
    client = _client_for_xml(SOLD_LIST_XML)

    items = listings._fetch_sold_listings(client, limit=1)

    assert items == [
        {
            "item_id": "178374167880",
            "sku": "EBAY-20260804130425",
            "title": "LEGO Wheel",
            "listing_type": "Chinese",
            "price": "17.5",
            "currency": "USD",
            "quantity_sold": 1,
        }
    ]


def test_should_keep_sold_item_fields_aligned_across_transaction_shapes():
    client = _client_for_xml(SOLD_LIST_MIXED_TRANSACTION_XML)

    items = listings._fetch_sold_listings(client, limit=2)

    assert [
        (
            item["item_id"],
            item["sku"],
            item["title"],
            item["listing_type"],
            item["price"],
            item["quantity_sold"],
        )
        for item in items
    ] == [
        (
            "100000000001",
            "",
            "First item without a SKU",
            "FixedPriceItem",
            "10.00",
            1,
        ),
        (
            "100000000002",
            "SECOND-SKU",
            "Second nested order item",
            "Chinese",
            "20.00",
            2,
        ),
    ]


def test_should_parse_unsold_item_array_per_item():
    client = _client_for_xml(UNSOLD_LIST_XML)

    items = listings._fetch_unsold_listings(client, limit=1)

    assert items == [
        {
            "item_id": "188888888888",
            "sku": "UNSOLD-SKU",
            "title": "Unsold LEGO Wheel",
            "listing_type": "FixedPriceItem",
            "price": "12.00",
            "currency": "USD",
            "quantity_sold": 0,
        }
    ]


def test_should_use_shared_trading_request_path_with_required_selectors(monkeypatch):
    client = _client_for_xml(EMPTY_SOLD_LIST_XML)
    direct_post = MagicMock(side_effect=AssertionError("direct HTTP path used"))
    monkeypatch.setattr("requests.post", direct_post)

    assert listings._fetch_sold_listings(client, limit=1) == []

    client._make_trading_api_request.assert_called_once()
    call_name, request_xml = client._make_trading_api_request.call_args.args
    assert call_name == "GetMyeBaySelling"
    assert "<OutputSelector>ListingType</OutputSelector>" in request_xml
    assert "<OutputSelector>SellingStatus</OutputSelector>" in request_xml
    assert "<RequesterCredentials>" not in request_xml
    direct_post.assert_not_called()


def test_should_surface_get_my_ebay_selling_transport_failure(monkeypatch):
    error = ClientError("Trading transport failed")
    client = MagicMock()
    client._make_trading_api_request.side_effect = error
    monkeypatch.setattr("requests.post", MagicMock(side_effect=error))

    with pytest.raises(ClientError, match="Trading transport failed"):
        listings._fetch_sold_listings(client, limit=1)


def test_should_surface_get_my_ebay_selling_ack_failure():
    client = _client_for_xml(ACK_FAILURE_XML)

    with pytest.raises(ClientError, match="^GetMyeBaySelling failed: Invalid token$"):
        listings._fetch_sold_listings(client, limit=1)


def test_should_surface_short_message_from_get_my_ebay_selling_failure():
    xml = """<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Failure</Ack>
  <Errors><ShortMessage>Token expired</ShortMessage></Errors>
</GetMyeBaySellingResponse>
"""
    client = _client_for_xml(xml)

    with pytest.raises(ClientError, match="^GetMyeBaySelling failed: Token expired$"):
        listings._fetch_sold_listings(client, limit=1)


def test_should_surface_malformed_get_my_ebay_selling_xml():
    client = _client_for_xml("<GetMyeBaySellingResponse>")

    with pytest.raises(ClientError, match="^Invalid GetMyeBaySelling XML:"):
        listings._fetch_sold_listings(client, limit=1)


def test_should_reject_unsupported_sold_listing_type():
    xml = SOLD_LIST_XML.replace(
        "<ListingType>Chinese</ListingType>",
        "<ListingType>AdType</ListingType>",
    )
    client = _client_for_xml(xml)

    with pytest.raises(
        ClientError,
        match="^Sold listing 178374167880 has unsupported ListingType: AdType$",
    ):
        listings._fetch_sold_listings(client, limit=1)


@pytest.mark.parametrize(
    ("xml", "missing_field"),
    [
        (
            SOLD_LIST_XML.replace("<ListingType>Chinese</ListingType>", ""),
            "ListingType",
        ),
        (
            SOLD_LIST_XML.replace(
                '<CurrentPrice currencyID="USD">17.5</CurrentPrice>',
                "",
            ),
            "SellingStatus.CurrentPrice",
        ),
        (
            SOLD_LIST_XML.replace(' currencyID="USD"', ""),
            "SellingStatus.CurrentPrice.currencyID",
        ),
        (
            SOLD_LIST_XML.replace("<QuantitySold>1</QuantitySold>", ""),
            "SellingStatus.QuantitySold",
        ),
    ],
    ids=["listing-type", "current-price", "currency", "quantity-sold"],
)
def test_should_surface_missing_required_sold_fields(
    xml,
    missing_field,
):
    client = _client_for_xml(xml)

    with pytest.raises(
        ClientError,
        match=f"^Sold listing 178374167880 is missing {missing_field}$",
    ):
        listings._fetch_sold_listings(client, limit=1)


def test_should_emit_sold_values_at_seller_list_command_boundary(
    monkeypatch,
    runner,
):
    client = _client_for_xml(SOLD_LIST_XML)
    monkeypatch.setattr(listings, "get_client", lambda: client)

    result = runner.invoke(
        app,
        [
            "seller",
            "listings",
            "list",
            "--status",
            "sold",
            "--filter",
            "sku:eq:EBAY-20260804130425",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["count"] == 1
    assert payload["listings"][0]["item_id"] == "178374167880"
    assert payload["listings"][0]["sku"] == "EBAY-20260804130425"
    assert payload["listings"][0]["status"] == "sold"
    assert payload["listings"][0]["format"] == "auction"
    assert payload["listings"][0]["price"] == "17.5"
    assert payload["listings"][0]["currency"] == "USD"
    assert payload["listings"][0]["quantity_sold"] == 1
    client._make_trading_api_request.assert_called_once()


def test_should_emit_ack_failure_at_seller_list_command_boundary(
    monkeypatch,
    runner,
):
    client = _client_for_xml(ACK_FAILURE_XML)
    monkeypatch.setattr(listings, "get_client", lambda: client)

    result = runner.invoke(
        app,
        ["seller", "listings", "list", "--status", "sold"],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == (
        "Fetching listings...\n"
        "Error: GetMyeBaySelling failed: Invalid token\n"
    )


def test_should_return_unique_current_draft_for_sku(monkeypatch):
    client = MagicMock()
    client.get_offers.return_value = {"offers": [_draft_offer()], "size": 1}
    client.get_inventory_item.return_value = _inventory_item()

    listing = listings._get_listing_by_sku(client, "EBAY-20260804130425")

    client.get_offers.assert_called_once_with(
        sku="EBAY-20260804130425",
        limit=200,
        offset=0,
    )
    assert listing.item_id == "178374156402"
    assert listing.status == "draft"
    assert listing.format == "auction"
    assert listing.price == "75.0"
    assert listing.currency == "USD"


def test_should_emit_unique_current_draft_at_seller_get_command_boundary(
    monkeypatch,
    runner,
):
    client = MagicMock()
    client.get_offers.return_value = {"offers": [_draft_offer()], "size": 1}
    client.get_inventory_item.return_value = _inventory_item()
    monkeypatch.setattr(listings, "get_client", lambda: client)

    result = runner.invoke(
        app,
        ["seller", "listings", "get", "EBAY-20260804130425"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["item_id"] == "178374156402"
    assert payload["status"] == "draft"
    assert payload["format"] == "auction"
    assert payload["price"] == "75.0"
    assert payload["currency"] == "USD"


def test_should_reject_sku_get_when_two_current_offers_exist():
    client = MagicMock()
    client.get_offers.return_value = _ambiguous_offers()

    with pytest.raises(
        ClientError,
        match=(
            "^SKU EBAY-20260804130425 has multiple current offers: "
            r"offer-auction \(AUCTION\), offer-fixed \(FIXED_PRICE\)$"
        ),
    ):
        listings._get_listing_by_sku(client, "EBAY-20260804130425")

    client.get_inventory_item.assert_not_called()


def test_should_emit_ambiguous_offer_error_at_seller_get_command_boundary(
    monkeypatch,
    runner,
):
    client = MagicMock()
    client.get_offers.return_value = _ambiguous_offers()
    monkeypatch.setattr(listings, "get_client", lambda: client)

    result = runner.invoke(
        app,
        ["seller", "listings", "get", "EBAY-20260804130425"],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == (
        "Error: SKU EBAY-20260804130425 has multiple current offers: "
        "offer-auction (AUCTION), offer-fixed (FIXED_PRICE)\n"
    )


def test_should_merge_active_data_only_when_listing_ids_match(monkeypatch):
    client = MagicMock()
    client.get_inventory_item.return_value = _inventory_item()
    monkeypatch.setattr(
        listings,
        "_fetch_all_offers",
        lambda client, limit: [_active_offer(item_id="matching-item")],
    )
    monkeypatch.setattr(
        listings,
        "_fetch_all_active_listings",
        lambda client, limit: [
            _active_trading_item(item_id="matching-item", price="17.5"),
        ],
    )
    monkeypatch.setattr(listings, "_fetch_unsold_listings", lambda client, limit: [])
    monkeypatch.setattr(listings, "_fetch_sold_listings", lambda client, limit: [])

    merged = listings._get_merged_listings(client, limit=10)

    assert len(merged) == 1
    assert merged[0].item_id == "matching-item"
    assert merged[0].price == "17.5"
    assert merged[0].quantity_sold == 1


def test_should_keep_distinct_active_items_when_only_sku_matches(monkeypatch):
    client = MagicMock()
    client.get_inventory_item.return_value = _inventory_item()
    monkeypatch.setattr(
        listings,
        "_fetch_all_offers",
        lambda client, limit: [_active_offer(item_id="current-item")],
    )
    monkeypatch.setattr(
        listings,
        "_fetch_all_active_listings",
        lambda client, limit: [
            _active_trading_item(item_id="different-item", price="17.5"),
        ],
    )
    monkeypatch.setattr(listings, "_fetch_unsold_listings", lambda client, limit: [])
    monkeypatch.setattr(listings, "_fetch_sold_listings", lambda client, limit: [])

    merged = listings._get_merged_listings(client, limit=10)

    assert [(item.item_id, item.price) for item in merged] == [
        ("current-item", "75.0"),
        ("different-item", "17.5"),
    ]


def test_should_emit_distinct_active_item_ids_at_list_command_boundary(
    monkeypatch,
    runner,
):
    client = MagicMock()
    client.get_inventory_item.return_value = _inventory_item()
    monkeypatch.setattr(listings, "get_client", lambda: client)
    monkeypatch.setattr(
        listings,
        "_fetch_all_offers",
        lambda client, limit: [_active_offer(item_id="current-item")],
    )
    monkeypatch.setattr(
        listings,
        "_fetch_all_active_listings",
        lambda client, limit: [
            _active_trading_item(item_id="different-item", price="17.5"),
        ],
    )

    result = runner.invoke(
        app,
        ["seller", "listings", "list", "--status", "active"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert [
        (item["item_id"], item["price"])
        for item in payload["listings"]
    ] == [
        ("current-item", "75.0"),
        ("different-item", "17.5"),
    ]


def test_should_not_merge_active_data_by_sku_in_single_get(monkeypatch):
    client = MagicMock()
    client.get_offers.return_value = {
        "offers": [_active_offer(item_id="current-item")],
        "size": 1,
    }
    client.get_inventory_item.return_value = _inventory_item()
    monkeypatch.setattr(
        listings,
        "_fetch_all_active_listings",
        lambda client, limit: [
            _active_trading_item(item_id="different-item", price="17.5"),
        ],
    )

    listing = listings._get_listing_by_sku(client, "EBAY-20260804130425")

    assert listing.item_id == "current-item"
    assert listing.price == "75.0"
    assert listing.quantity_sold == 0


def test_should_surface_active_lookup_failure_for_published_offer(monkeypatch):
    client = MagicMock()
    client.get_offers.return_value = {
        "offers": [_active_offer(item_id="current-item")],
        "size": 1,
    }
    client.get_inventory_item.return_value = _inventory_item()
    monkeypatch.setattr(
        listings,
        "_fetch_all_active_listings",
        MagicMock(side_effect=ClientError("active Trading lookup failed")),
    )

    with pytest.raises(ClientError, match="^active Trading lookup failed$"):
        listings._get_listing_by_sku(client, "EBAY-20260804130425")


def test_should_reject_sku_get_when_two_legacy_active_listings_exist(monkeypatch):
    client = MagicMock()
    client.get_offers.return_value = {"offers": [], "size": 0}
    client.get_inventory_item.return_value = _inventory_item()
    monkeypatch.setattr(
        listings,
        "_fetch_all_active_listings",
        lambda client, limit: [
            _active_trading_item(item_id="legacy-fixed"),
            _active_trading_item(item_id="legacy-auction"),
        ],
    )

    with pytest.raises(
        ClientError,
        match=(
            "^SKU EBAY-20260804130425 has multiple active listings: "
            "legacy-auction, legacy-fixed$"
        ),
    ):
        listings._get_listing_by_sku(client, "EBAY-20260804130425")


def test_should_keep_sold_history_separate_from_current_draft(monkeypatch):
    client = MagicMock()
    client.get_inventory_item.return_value = _inventory_item()
    monkeypatch.setattr(listings, "_fetch_all_active_listings", lambda client, limit: [])
    monkeypatch.setattr(
        listings,
        "_fetch_all_offers",
        lambda client, limit: [_draft_offer()],
    )
    monkeypatch.setattr(listings, "_fetch_unsold_listings", lambda client, limit: [])
    monkeypatch.setattr(
        listings,
        "_fetch_sold_listings",
        lambda client, limit: [
            {
                "item_id": "178374167880",
                "sku": "EBAY-20260804130425",
                "title": "LEGO Wheel",
                "listing_type": "Chinese",
                "price": "17.5",
                "currency": "USD",
                "quantity_sold": 1,
            }
        ],
    )

    merged = listings._get_merged_listings(client, limit=10)

    assert [
        (
            item.item_id,
            item.status,
            item.format,
            item.price,
            item.quantity_sold,
        )
        for item in merged
    ] == [
        ("178374156402", "draft", "auction", "75.0", 0),
        ("178374167880", "sold", "auction", "17.5", 1),
    ]
