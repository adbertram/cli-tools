"""Tests for Best Offer commands.

Tests the GetBestOffers and RespondToBestOffer Trading API integrations,
including XML parsing, pagination, and command-line validation.
"""

from unittest.mock import MagicMock
import pytest

from ebay_cli.commands import offers
from ebay_cli.main import app

# Sample GetBestOffers XML response with active offers
GET_BEST_OFFERS_SUCCESS_RESPONSE = """<?xml version="1.0" encoding="utf-8"?>
<GetBestOffersResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Success</Ack>
  <BestOfferArray>
    <BestOffer>
      <BestOfferID>1234567890</BestOfferID>
      <ExpirationTime>2026-10-30T12:00:00.000Z</ExpirationTime>
      <Price>35.00</Price>
      <Status>Active</Status>
      <Quantity>1</Quantity>
      <BestOfferCodeType>BuyerBestOffer</BestOfferCodeType>
      <BuyerMessage>Would you consider $35?</BuyerMessage>
      <Buyer>
        <UserID>testbuyer123</UserID>
        <FeedbackScore>150</FeedbackScore>
        <PositiveFeedbackPercent>98.5</PositiveFeedbackPercent>
      </Buyer>
      <ItemArray>
        <Item>
          <ItemID>123456789012</ItemID>
          <Title>LEGO Star Wars Set</Title>
          <SellingStatus>
            <CurrentPrice>50.00</CurrentPrice>
          </SellingStatus>
        </Item>
      </ItemArray>
    </BestOffer>
    <BestOffer>
      <BestOfferID>1234567891</BestOfferID>
      <ExpirationTime>2026-10-29T18:30:00.000Z</ExpirationTime>
      <Price>42.50</Price>
      <Status>Active</Status>
      <Quantity>2</Quantity>
      <BestOfferCodeType>BuyerCounterOffer</BestOfferCodeType>
      <BuyerMessage>How about $42.50 for 2?</BuyerMessage>
      <Buyer>
        <UserID>anotherbuyer</UserID>
        <FeedbackScore>75</FeedbackScore>
        <PositiveFeedbackPercent>100.0</PositiveFeedbackPercent>
      </Buyer>
      <ItemArray>
        <Item>
          <ItemID>987654321098</ItemID>
          <Title>Vintage Camera Bundle</Title>
          <SellingStatus>
            <CurrentPrice>60.00</CurrentPrice>
          </SellingStatus>
        </Item>
      </ItemArray>
    </BestOffer>
  </BestOfferArray>
  <PaginationResult>
    <TotalNumberOfEntries>2</TotalNumberOfEntries>
    <TotalNumberOfPages>1</TotalNumberOfPages>
  </PaginationResult>
</GetBestOffersResponse>
"""

# Empty response when no offers
GET_BEST_OFFERS_EMPTY_RESPONSE = """<?xml version="1.0" encoding="utf-8"?>
<GetBestOffersResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Success</Ack>
  <PaginationResult>
    <TotalNumberOfEntries>0</TotalNumberOfEntries>
    <TotalNumberOfPages>0</TotalNumberOfPages>
  </PaginationResult>
</GetBestOffersResponse>
"""

# Error response
GET_BEST_OFFERS_ERROR_RESPONSE = """<?xml version="1.0" encoding="utf-8"?>
<GetBestOffersResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Failure</Ack>
  <Errors>
    <ShortMessage>Invalid item ID</ShortMessage>
    <LongMessage>The item ID provided is not valid or does not belong to this seller.</LongMessage>
  </Errors>
</GetBestOffersResponse>
"""

# RespondToBestOffer success response
RESPOND_TO_BEST_OFFER_SUCCESS = """<?xml version="1.0" encoding="utf-8"?>
<RespondToBestOfferResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Success</Ack>
  <RespondToBestOffer>
    <BestOfferID>1234567890</BestOfferID>
  </RespondToBestOffer>
</RespondToBestOfferResponse>
"""


def _client_with(monkeypatch, get_best_offers_response: str, respond_response: str = RESPOND_TO_BEST_OFFER_SUCCESS) -> MagicMock:
    """Create a mocked client with predefined responses."""
    client = MagicMock()
    client.get_best_offers.return_value = get_best_offers_response
    client.respond_to_best_offer.return_value = respond_response
    monkeypatch.setattr(offers, "get_client", lambda: client)
    return client


def test_offers_list_success(monkeypatch, runner):
    """Test listing Best Offers successfully."""
    client = _client_with(monkeypatch, GET_BEST_OFFERS_SUCCESS_RESPONSE)

    result = runner.invoke(app, ["seller", "offers", "list"])

    assert result.exit_code == 0, result.stderr
    assert client.get_best_offers.called
    # Check JSON output contains offers
    assert "offers" in result.stdout
    assert "1234567890" in result.stdout
    assert "testbuyer123" in result.stdout


def test_offers_list_table_format(monkeypatch, runner):
    """Test listing offers in table format."""
    client = _client_with(monkeypatch, GET_BEST_OFFERS_SUCCESS_RESPONSE)

    result = runner.invoke(app, ["seller", "offers", "list", "--table"])

    assert result.exit_code == 0, result.stderr
    assert "Offer ID" in result.stdout
    assert "Buyer" in result.stdout
    assert "1234567890" in result.stdout
    assert "testbuyer123" in result.stdout


def test_offers_list_empty(monkeypatch, runner):
    """Test listing when no offers exist."""
    client = _client_with(monkeypatch, GET_BEST_OFFERS_EMPTY_RESPONSE)

    result = runner.invoke(app, ["seller", "offers", "list"])

    assert result.exit_code == 0, result.stderr
    assert '"total": 0' in result.stdout


def test_offers_list_with_item_filter(monkeypatch, runner):
    """Test filtering offers by item ID."""
    client = _client_with(monkeypatch, GET_BEST_OFFERS_SUCCESS_RESPONSE)

    result = runner.invoke(app, ["seller", "offers", "list", "--item-id", "123456789012"])

    assert result.exit_code == 0, result.stderr
    assert client.get_best_offers.called
    call_kwargs = client.get_best_offers.call_args.kwargs
    assert call_kwargs["item_id"] == "123456789012"


def test_offers_list_pagination(monkeypatch, runner):
    """Test pagination parameters."""
    client = _client_with(monkeypatch, GET_BEST_OFFERS_SUCCESS_RESPONSE)

    result = runner.invoke(app, ["seller", "offers", "list", "--limit", "50", "--offset", "100"])

    assert result.exit_code == 0, result.stderr
    call_kwargs = client.get_best_offers.call_args.kwargs
    assert call_kwargs["entries_per_page"] == 50
    # Page number should be calculated from offset
    assert call_kwargs["page_number"] == 3  # (100 // 50) + 1


def test_offers_get_success(monkeypatch, runner):
    """Test getting a specific offer."""
    client = _client_with(monkeypatch, GET_BEST_OFFERS_SUCCESS_RESPONSE)

    result = runner.invoke(app, ["seller", "offers", "get", "1234567890"])

    assert result.exit_code == 0, result.stderr
    assert "1234567890" in result.stdout
    assert "testbuyer123" in result.stdout


def test_offers_get_not_found(monkeypatch, runner):
    """Test getting a non-existent offer."""
    client = _client_with(monkeypatch, GET_BEST_OFFERS_SUCCESS_RESPONSE)

    result = runner.invoke(app, ["seller", "offers", "get", "9999999999"])

    assert result.exit_code == 1
    assert "not found" in result.stderr


def test_offers_get_table_format(monkeypatch, runner):
    """Test getting an offer in table format."""
    client = _client_with(monkeypatch, GET_BEST_OFFERS_SUCCESS_RESPONSE)

    result = runner.invoke(app, ["seller", "offers", "get", "1234567890", "--table"])

    assert result.exit_code == 0, result.stderr
    assert "Best Offer Details" in result.stdout
    assert "Offer ID:" in result.stdout
    assert "testbuyer123" in result.stdout


def test_offers_accept_with_confirmation(monkeypatch, runner):
    """Test accepting an offer with confirmation."""
    client = _client_with(monkeypatch, GET_BEST_OFFERS_SUCCESS_RESPONSE)

    result = runner.invoke(
        app,
        ["seller", "offers", "accept", "1234567890", "--item-id", "123456789012"],
        input="y\n"  # Confirm
    )

    assert result.exit_code == 0, result.stderr
    assert client.respond_to_best_offer.called
    call_kwargs = client.respond_to_best_offer.call_args.kwargs
    assert call_kwargs["best_offer_id"] == "1234567890"
    assert call_kwargs["item_id"] == "123456789012"
    assert call_kwargs["action"] == "Accept"


def test_offers_accept_with_yes_flag(monkeypatch, runner):
    """Test accepting an offer with --yes flag."""
    client = _client_with(monkeypatch, GET_BEST_OFFERS_SUCCESS_RESPONSE)

    result = runner.invoke(
        app,
        ["seller", "offers", "accept", "1234567890", "--item-id", "123456789012", "--yes"]
    )

    assert result.exit_code == 0, result.stderr
    assert client.respond_to_best_offer.called


def test_offers_accept_with_message(monkeypatch, runner):
    """Test accepting an offer with a message."""
    client = _client_with(monkeypatch, GET_BEST_OFFERS_SUCCESS_RESPONSE)

    result = runner.invoke(
        app,
        [
            "seller", "offers", "accept", "1234567890",
            "--item-id", "123456789012",
            "--message", "Thanks for your offer!",
            "--yes"
        ]
    )

    assert result.exit_code == 0, result.stderr
    call_kwargs = client.respond_to_best_offer.call_args.kwargs
    assert call_kwargs["seller_response"] == "Thanks for your offer!"


def test_offers_accept_cancelled(monkeypatch, runner):
    """Test cancelling an accept operation."""
    client = _client_with(monkeypatch, GET_BEST_OFFERS_SUCCESS_RESPONSE)

    result = runner.invoke(
        app,
        ["seller", "offers", "accept", "1234567890", "--item-id", "123456789012"],
        input="n\n"  # Decline confirmation
    )

    assert result.exit_code == 0
    assert not client.respond_to_best_offer.called
    assert "Cancelled" in result.stdout


def test_offers_decline_with_message(monkeypatch, runner):
    """Test declining an offer with a message."""
    client = _client_with(monkeypatch, GET_BEST_OFFERS_SUCCESS_RESPONSE)

    result = runner.invoke(
        app,
        [
            "seller", "offers", "decline", "1234567890",
            "--item-id", "123456789012",
            "--message", "Sorry, price is too low",
            "--yes"
        ]
    )

    assert result.exit_code == 0, result.stderr
    call_kwargs = client.respond_to_best_offer.call_args.kwargs
    assert call_kwargs["action"] == "Decline"
    assert call_kwargs["seller_response"] == "Sorry, price is too low"


def test_offers_counter_success(monkeypatch, runner):
    """Test sending a counter offer."""
    client = _client_with(monkeypatch, GET_BEST_OFFERS_SUCCESS_RESPONSE)

    result = runner.invoke(
        app,
        [
            "seller", "offers", "counter", "1234567890",
            "--item-id", "123456789012",
            "--price", "40.00",
            "--yes"
        ]
    )

    assert result.exit_code == 0, result.stderr
    call_kwargs = client.respond_to_best_offer.call_args.kwargs
    assert call_kwargs["action"] == "Counter"
    assert call_kwargs["counter_offer_price"] == "40.00"


def test_offers_counter_with_quantity(monkeypatch, runner):
    """Test counter offer with quantity."""
    client = _client_with(monkeypatch, GET_BEST_OFFERS_SUCCESS_RESPONSE)

    result = runner.invoke(
        app,
        [
            "seller", "offers", "counter", "1234567890",
            "--item-id", "123456789012",
            "--price", "40.00",
            "--quantity", "2",
            "--yes"
        ]
    )

    assert result.exit_code == 0, result.stderr
    call_kwargs = client.respond_to_best_offer.call_args.kwargs
    assert call_kwargs["counter_offer_quantity"] == 2


def test_offers_counter_with_message(monkeypatch, runner):
    """Test counter offer with a message."""
    client = _client_with(monkeypatch, GET_BEST_OFFERS_SUCCESS_RESPONSE)

    result = runner.invoke(
        app,
        [
            "seller", "offers", "counter", "1234567890",
            "--item-id", "123456789012",
            "--price", "45.00",
            "--message", "Best I can do",
            "--yes"
        ]
    )

    assert result.exit_code == 0, result.stderr
    call_kwargs = client.respond_to_best_offer.call_args.kwargs
    assert call_kwargs["seller_response"] == "Best I can do"


def test_offers_counter_invalid_price(monkeypatch, runner):
    """Test counter offer with invalid price format."""
    client = _client_with(monkeypatch, GET_BEST_OFFERS_SUCCESS_RESPONSE)

    result = runner.invoke(
        app,
        [
            "seller", "offers", "counter", "1234567890",
            "--item-id", "123456789012",
            "--price", "not-a-number",
            "--yes"
        ]
    )

    assert result.exit_code == 1
    assert "Invalid price format" in result.stderr


def test_offers_counter_negative_price(monkeypatch, runner):
    """Test counter offer with negative price."""
    client = _client_with(monkeypatch, GET_BEST_OFFERS_SUCCESS_RESPONSE)

    result = runner.invoke(
        app,
        [
            "seller", "offers", "counter", "1234567890",
            "--item-id", "123456789012",
            "--price", "-10.00",
            "--yes"
        ]
    )

    assert result.exit_code == 1
    assert "must be greater than 0" in result.stderr


def test_offers_counter_formats_price(monkeypatch, runner):
    """Test that counter offer formats price to 2 decimals."""
    client = _client_with(monkeypatch, GET_BEST_OFFERS_SUCCESS_RESPONSE)

    result = runner.invoke(
        app,
        [
            "seller", "offers", "counter", "1234567890",
            "--item-id", "123456789012",
            "--price", "45.999",  # Should be rounded/truncated
            "--yes"
        ]
    )

    assert result.exit_code == 0, result.stderr
    call_kwargs = client.respond_to_best_offer.call_args.kwargs
    # Decimal formatting should produce "46.00"
    price = call_kwargs["counter_offer_price"]
    assert "." in price
    parts = price.split(".")
    assert len(parts[1]) == 2


def test_offers_api_error(monkeypatch, runner):
    """Test handling of API errors."""
    client = _client_with(monkeypatch, GET_BEST_OFFERS_ERROR_RESPONSE)

    result = runner.invoke(app, ["seller", "offers", "list"])

    assert result.exit_code == 1
    assert "Invalid item ID" in result.stderr or "not valid" in result.stderr


def test_offers_accept_not_found(monkeypatch, runner):
    """Test accepting a non-existent offer."""
    # Return an empty offer list
    client = _client_with(monkeypatch, GET_BEST_OFFERS_EMPTY_RESPONSE)

    result = runner.invoke(
        app,
        ["seller", "offers", "accept", "9999999999", "--item-id", "123456789012", "--yes"]
    )

    assert result.exit_code == 1
    assert "not found" in result.stderr


def test_parse_best_offers_handles_missing_buyer_feedback(monkeypatch, runner):
    """Test parsing offers when buyer feedback is missing."""
    response_without_feedback = """<?xml version="1.0" encoding="utf-8"?>
<GetBestOffersResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Success</Ack>
  <BestOfferArray>
    <BestOffer>
      <BestOfferID>1234567890</BestOfferID>
      <ExpirationTime>2026-10-30T12:00:00.000Z</ExpirationTime>
      <Price>35.00</Price>
      <Status>Active</Status>
      <Quantity>1</Quantity>
      <BestOfferCodeType>BuyerBestOffer</BestOfferCodeType>
      <Buyer>
        <UserID>testbuyer123</UserID>
      </Buyer>
      <ItemArray>
        <Item>
          <ItemID>123456789012</ItemID>
          <Title>Test Item</Title>
        </Item>
      </ItemArray>
    </BestOffer>
  </BestOfferArray>
  <PaginationResult>
    <TotalNumberOfEntries>1</TotalNumberOfEntries>
  </PaginationResult>
</GetBestOffersResponse>
"""

    client = _client_with(monkeypatch, response_without_feedback)

    result = runner.invoke(app, ["seller", "offers", "list"])

    assert result.exit_code == 0, result.stderr
    # Should still parse successfully even without feedback fields
    assert "testbuyer123" in result.stdout
