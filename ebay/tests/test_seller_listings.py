"""Regression tests for seller listing reads."""

import json
from unittest.mock import MagicMock

import pytest

from ebay_cli.client import EbayClient, ClientError
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
    monkeypatch.setattr(listings, "_fetch_all_active_listings", lambda client, limit: [])

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
    monkeypatch.setattr(listings, "_fetch_all_active_listings", lambda client, limit: [])

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


def test_should_reject_sku_when_published_offer_and_active_listing_differ(monkeypatch):
    # Agent-issues #226: the same SKU on an Inventory API offer and on a
    # different Trading API active listing is two records. Preferring the offer
    # silently (the old behaviour) is what let `update` write to the wrong one.
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

    with pytest.raises(
        ClientError,
        match=(
            "^SKU EBAY-20260804130425 resolves to different records: "
            r"Inventory API offer offer-auction \(item current-item\) "
            "and Trading API active listing different-item$"
        ),
    ):
        listings._get_listing_by_sku(client, "EBAY-20260804130425")


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


# --- listing_from_offer pricing (agent-issues #610) ---------------------------

from ebay_cli.models.listing import Listing, listing_from_offer


def _offer_with_pricing(*, offer_format: str, pricing: dict) -> dict:
    return {
        "offerId": "offer-1",
        "sku": "EBAY-20260915185427",
        "status": "PUBLISHED",
        "format": offer_format,
        "listing": {"listingId": "266884257011"},
        "pricingSummary": pricing,
        "availableQuantity": 1,
    }


def test_auction_with_bin_reports_starting_bid_as_price():
    # Regression for #610: AUCTION+BIN offers carry both price (Buy It Now) and
    # auctionStartPrice (starting bid). The headline price must be the starting
    # bid, and the Buy It Now price must be preserved as bin_price.
    offer = _offer_with_pricing(
        offer_format="AUCTION",
        pricing={
            "price": {"value": "99.0", "currency": "USD"},
            "auctionStartPrice": {"value": "24.99", "currency": "USD"},
        },
    )

    listing = listing_from_offer(offer)

    assert listing.format == "auction"
    assert listing.price == "24.99"
    assert listing.bin_price == "99.0"


def test_plain_auction_reports_starting_bid_and_no_bin_price():
    offer = _offer_with_pricing(
        offer_format="AUCTION",
        pricing={"auctionStartPrice": {"value": "24.99", "currency": "USD"}},
    )

    listing = listing_from_offer(offer)

    assert listing.price == "24.99"
    assert listing.bin_price is None
    # bin_price is None -> excluded from JSON output.
    assert "bin_price" not in listing.to_dict()


def test_fixed_price_reports_price_and_no_bin_price():
    offer = _offer_with_pricing(
        offer_format="FIXED_PRICE",
        pricing={"price": {"value": "99.0", "currency": "USD"}},
    )

    listing = listing_from_offer(offer)

    assert listing.format == "fixed_price"
    assert listing.price == "99.0"
    assert listing.bin_price is None


# --- SKU collisions across the two APIs, and legacy writes (agent-issues #226) --

# The report's records: one SKU naming an orphaned, unpublished Inventory API
# offer (item 188900455705) and a live legacy Trading API listing (item
# 188900460802) at the same time.
COLLIDING_SKU = "EBAY-20260907153633"
COLLIDING_OFFER_ID = "258713810011"
COLLIDING_OFFER_ITEM_ID = "188900455705"
COLLIDING_LEGACY_ITEM_ID = "188900460802"

REVISE_SUCCESS_XML = """<?xml version="1.0" encoding="utf-8"?>
<ReviseFixedPriceItemResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Success</Ack>
  <ItemID>188900460802</ItemID>
</ReviseFixedPriceItemResponse>
"""

REVISE_FAILURE_XML = """<?xml version="1.0" encoding="utf-8"?>
<ReviseFixedPriceItemResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Failure</Ack>
  <Errors>
    <ShortMessage>Invalid item ID</ShortMessage>
    <LongMessage>Invalid item ID 188900460802.</LongMessage>
    <ErrorCode>17</ErrorCode>
  </Errors>
</ReviseFixedPriceItemResponse>
"""


def _colliding_draft_offer() -> dict:
    offer = _draft_offer(
        offer_id=COLLIDING_OFFER_ID,
        item_id=COLLIDING_OFFER_ITEM_ID,
        format_type="FIXED_PRICE",
    )
    offer["sku"] = COLLIDING_SKU
    return offer


def _colliding_legacy_active_item() -> dict:
    item = _active_trading_item(item_id=COLLIDING_LEGACY_ITEM_ID, price="79.99")
    item["sku"] = COLLIDING_SKU
    item["listing_type"] = "FixedPriceItem"
    return item


def _legacy_active_listing() -> Listing:
    return Listing(
        sku=COLLIDING_SKU,
        item_id=COLLIDING_LEGACY_ITEM_ID,
        title="Wood LEGO Brick Sorter 6-Tray Piece Sorting Box Graduated Holes Large",
        price="79.99",
        currency="USD",
        quantity=1,
        status="active",
        format="fixed_price",
    )


def _client_with_colliding_sku() -> MagicMock:
    client = MagicMock()
    client.get_offers.return_value = {"offers": [_colliding_draft_offer()], "size": 1}
    client.get_inventory_item.return_value = _inventory_item()
    return client


def test_should_reject_sku_that_names_an_offer_and_a_legacy_active_listing(monkeypatch):
    client = _client_with_colliding_sku()
    monkeypatch.setattr(
        listings,
        "_fetch_all_active_listings",
        lambda client, limit: [_colliding_legacy_active_item()],
    )

    with pytest.raises(
        ClientError,
        match=(
            "^SKU EBAY-20260907153633 resolves to different records: Inventory API offer "
            r"258713810011 \(item 188900455705\) and Trading API active listing 188900460802$"
        ),
    ):
        listings._get_listing_by_sku(client, COLLIDING_SKU)


def test_should_emit_cross_api_sku_collision_at_seller_get_command_boundary(monkeypatch, runner):
    client = _client_with_colliding_sku()
    monkeypatch.setattr(listings, "get_client", lambda: client)
    monkeypatch.setattr(
        listings,
        "_fetch_all_active_listings",
        lambda client, limit: [_colliding_legacy_active_item()],
    )

    result = runner.invoke(app, ["seller", "listings", "get", COLLIDING_SKU])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == (
        "Error: SKU EBAY-20260907153633 resolves to different records: Inventory API offer "
        "258713810011 (item 188900455705) and Trading API active listing 188900460802\n"
    )


def test_should_refuse_update_when_sku_collides_across_apis(monkeypatch, runner):
    client = _client_with_colliding_sku()
    monkeypatch.setattr(listings, "get_client", lambda: client)
    monkeypatch.setattr(
        listings,
        "_fetch_all_active_listings",
        lambda client, limit: [_colliding_legacy_active_item()],
    )

    result = runner.invoke(
        app,
        ["seller", "listings", "update", COLLIDING_SKU, "--price", "69.99"],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "resolves to different records" in result.stderr
    client.update_offer.assert_not_called()
    client.create_or_update_inventory_item.assert_not_called()
    client.revise_fixed_price_item.assert_not_called()


def test_should_build_revise_fixed_price_item_request_for_legacy_listing():
    client = MagicMock()

    EbayClient.revise_fixed_price_item(
        client,
        COLLIDING_LEGACY_ITEM_ID,
        title="Wood LEGO Brick Sorter",
        description="Tray & <b>holes</b>",
        start_price="69.99",
        currency="USD",
        quantity=3,
        best_offer_enabled=True,
    )

    call_name, request_xml = client._make_trading_api_request.call_args.args
    assert call_name == "ReviseFixedPriceItem"
    assert f"<ItemID>{COLLIDING_LEGACY_ITEM_ID}</ItemID>" in request_xml
    assert "<Title>Wood LEGO Brick Sorter</Title>" in request_xml
    assert "<Description>Tray &amp; &lt;b&gt;holes&lt;/b&gt;</Description>" in request_xml
    assert '<StartPrice currencyID="USD">69.99</StartPrice>' in request_xml
    assert "<Quantity>3</Quantity>" in request_xml
    assert (
        "<BestOfferDetails><BestOfferEnabled>true</BestOfferEnabled></BestOfferDetails>"
        in request_xml
    )


def test_should_send_only_requested_fields_in_revise_fixed_price_item():
    client = MagicMock()

    EbayClient.revise_fixed_price_item(
        client,
        COLLIDING_LEGACY_ITEM_ID,
        best_offer_enabled=False,
    )

    request_xml = client._make_trading_api_request.call_args.args[1]
    assert "<BestOfferDetails><BestOfferEnabled>false</BestOfferEnabled></BestOfferDetails>" in request_xml
    for absent in ("<Title>", "<Description>", "<StartPrice", "<Quantity>"):
        assert absent not in request_xml


def test_should_revise_legacy_listing_through_trading_api(monkeypatch, runner):
    client = MagicMock()
    client.revise_fixed_price_item.return_value = REVISE_SUCCESS_XML
    monkeypatch.setattr(listings, "get_client", lambda: client)
    monkeypatch.setattr(
        listings,
        "_get_listing_by_sku",
        lambda _client, _sku: _legacy_active_listing(),
    )

    result = runner.invoke(
        app,
        [
            "seller",
            "listings",
            "update",
            COLLIDING_SKU,
            "--title",
            "Wood LEGO Brick Sorter 6-Tray",
            "--description",
            "Sorted trays.",
            "--price",
            "69.99",
            "--quantity",
            "3",
            "--best-offer",
        ],
    )

    assert result.exit_code == 0, result.stderr
    client.revise_fixed_price_item.assert_called_once_with(
        COLLIDING_LEGACY_ITEM_ID,
        title="Wood LEGO Brick Sorter 6-Tray",
        description="Sorted trays.",
        start_price="69.99",
        currency="USD",
        quantity=3,
        best_offer_enabled=True,
    )
    client.update_offer.assert_not_called()
    client.create_or_update_inventory_item.assert_not_called()
    assert json.loads(result.stdout)["item_id"] == COLLIDING_LEGACY_ITEM_ID


def test_should_refuse_options_a_legacy_listing_cannot_carry(monkeypatch, runner):
    client = MagicMock()
    monkeypatch.setattr(listings, "get_client", lambda: client)
    monkeypatch.setattr(
        listings,
        "_get_listing_by_sku",
        lambda _client, _sku: _legacy_active_listing(),
    )

    result = runner.invoke(
        app,
        ["seller", "listings", "update", COLLIDING_SKU, "--category", "261329", "--price", "69.99"],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == (
        "Error: Legacy Trading API listing EBAY-20260907153633 supports --title, --description, "
        "--price, --quantity and --best-offer only; unsupported: --category\n"
    )
    client.revise_fixed_price_item.assert_not_called()


def test_should_warn_without_revising_when_legacy_update_requests_nothing(monkeypatch, runner):
    client = MagicMock()
    monkeypatch.setattr(listings, "get_client", lambda: client)
    monkeypatch.setattr(
        listings,
        "_get_listing_by_sku",
        lambda _client, _sku: _legacy_active_listing(),
    )

    result = runner.invoke(app, ["seller", "listings", "update", COLLIDING_SKU])

    assert result.exit_code == 0
    assert result.stderr == "Warning: No updates provided.\n"
    client.revise_fixed_price_item.assert_not_called()


def test_should_surface_revise_failure_for_legacy_listing(monkeypatch, runner):
    client = MagicMock()
    client.revise_fixed_price_item.return_value = REVISE_FAILURE_XML
    monkeypatch.setattr(listings, "get_client", lambda: client)
    monkeypatch.setattr(
        listings,
        "_get_listing_by_sku",
        lambda _client, _sku: _legacy_active_listing(),
    )

    result = runner.invoke(
        app,
        ["seller", "listings", "update", COLLIDING_SKU, "--best-offer"],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == (
        f"Revising legacy Trading API listing {COLLIDING_LEGACY_ITEM_ID}...\n"
        "Error: ReviseFixedPriceItem failed: 17: Invalid item ID 188900460802.\n"
    )


def test_should_refuse_best_offer_for_inventory_backed_listing(monkeypatch, runner):
    client = MagicMock()
    client.get_offers.return_value = {"offers": [_draft_offer()], "size": 1}
    client.get_inventory_item.return_value = _inventory_item()
    monkeypatch.setattr(listings, "get_client", lambda: client)
    monkeypatch.setattr(listings, "_fetch_all_active_listings", lambda client, limit: [])

    result = runner.invoke(
        app,
        ["seller", "listings", "update", "EBAY-20260804130425", "--best-offer"],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == (
        "Error: Best Offer is not supported for Inventory API listing EBAY-20260804130425 "
        "(offer offer-auction); --best-offer applies to legacy Trading API listings only\n"
    )
    client.update_offer.assert_not_called()
    client.create_or_update_inventory_item.assert_not_called()
