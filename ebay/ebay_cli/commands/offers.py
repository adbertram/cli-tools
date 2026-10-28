"""Best Offer commands for eBay CLI.

Uses the eBay Trading API to query and manage Best Offers from buyers.
"""
from cli_tools_shared.output import command

COMMAND_CREDENTIALS = {
    "list": ["oauth_authorization_code"],
    "get": ["oauth_authorization_code"],
    "accept": ["oauth_authorization_code"],
    "decline": ["oauth_authorization_code"],
    "counter": ["oauth_authorization_code"],
}

import sys
import typer
import xml.etree.ElementTree as ET
from typing import Optional, List
from decimal import Decimal, InvalidOperation

from ..client import get_client, ClientError
from cli_tools_shared.output import (
    print_json,
    print_table,
    handle_error,
    print_success,
    print_error,
    print_info,
)
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
from ..parsers import format_local_time
from ..properties import validate_and_filter_properties, PropertyValidationError

app = typer.Typer(help="Manage Best Offers from buyers")

# eBay XML namespace for Trading API parsing
NS = {"ebay": "urn:ebay:apis:eBLBaseComponents"}


# =============================================================================
# Helper Functions: XML Parsing
# =============================================================================


def _find_element(parent: Optional[ET.Element], path: str) -> Optional[ET.Element]:
    """Find child element, trying with namespace first then without."""
    if parent is None:
        return None
    el = parent.find(f"ebay:{path}", NS)
    if el is not None:
        return el
    return parent.find(path)


def _get_text(element: Optional[ET.Element], path: str, default: str = "") -> str:
    """Get text from an element, handling namespace and None."""
    if element is None:
        return default
    el = _find_element(element, path)
    return el.text if el is not None and el.text else default


def _parse_best_offers_xml(xml_content: str) -> tuple[list[dict], int]:
    """Parse GetBestOffers XML response into list of offers."""
    try:
        root = ET.fromstring(xml_content)

        # Check for errors
        ack = _get_text(root, "Ack")
        if ack == "Failure":
            errors = _find_element(root, "Errors")
            if errors is not None:
                error_msg = _get_text(errors, "LongMessage") or _get_text(
                    errors, "ShortMessage"
                )
                raise ClientError(f"eBay API error: {error_msg}")
            raise ClientError("eBay API returned failure status")

        # Get pagination info
        pagination_result = _find_element(root, "PaginationResult")
        total_entries = int(_get_text(pagination_result, "TotalNumberOfEntries", "0"))

        # Parse offers
        offers = []
        best_offers_array = _find_element(root, "BestOfferArray")
        if best_offers_array is not None:
            for offer_container in best_offers_array.findall("ebay:BestOffer", NS):
                # Get basic offer info
                offer = {
                    "best_offer_id": _get_text(offer_container, "BestOfferID"),
                    "expiration_time": _get_text(offer_container, "ExpirationTime"),
                    "price": _get_text(offer_container, "Price"),
                    "status": _get_text(offer_container, "Status"),
                    "quantity": _get_text(offer_container, "Quantity"),
                    "best_offer_code_type": _get_text(
                        offer_container, "BestOfferCodeType"
                    ),
                    "buyer_message": _get_text(offer_container, "BuyerMessage"),
                }

                # Get buyer info
                buyer = _find_element(offer_container, "Buyer")
                if buyer is not None:
                    offer["buyer_user_id"] = _get_text(buyer, "UserID")
                    feedback_score = _find_element(buyer, "FeedbackScore")
                    if feedback_score is not None and feedback_score.text:
                        offer["buyer_feedback_score"] = feedback_score.text
                    positive_feedback = _find_element(
                        buyer, "PositiveFeedbackPercent"
                    )
                    if positive_feedback is not None and positive_feedback.text:
                        offer["buyer_positive_feedback_percent"] = positive_feedback.text

                # Get item info
                item_array = _find_element(offer_container, "ItemArray")
                if item_array is not None:
                    item = _find_element(item_array, "Item")
                    if item is not None:
                        offer["item_id"] = _get_text(item, "ItemID")
                        offer["item_title"] = _get_text(item, "Title")
                        # Get current price from the item
                        selling_status = _find_element(item, "SellingStatus")
                        if selling_status is not None:
                            current_price = _find_element(
                                selling_status, "CurrentPrice"
                            )
                            if (
                                current_price is not None
                                and current_price.text is not None
                            ):
                                offer["item_current_price"] = current_price.text

                offers.append(offer)

        return offers, total_entries

    except ET.ParseError as e:
        raise ClientError(f"Failed to parse XML response: {e}")


def _parse_respond_to_best_offer_xml(xml_content: str) -> dict:
    """Parse RespondToBestOffer XML response."""
    try:
        root = ET.fromstring(xml_content)

        # Check for errors
        ack = _get_text(root, "Ack")
        if ack == "Failure":
            errors = _find_element(root, "Errors")
            if errors is not None:
                error_msg = _get_text(errors, "LongMessage") or _get_text(
                    errors, "ShortMessage"
                )
                raise ClientError(f"eBay API error: {error_msg}")
            raise ClientError("eBay API returned failure status")

        # Parse response
        result = {
            "ack": ack,
        }

        # Get Best Offer array to see if the response was successful
        best_offer_array = _find_element(root, "RespondToBestOffer")
        if best_offer_array is not None:
            result["best_offer_id"] = _get_text(best_offer_array, "BestOfferID")

        return result

    except ET.ParseError as e:
        raise ClientError(f"Failed to parse XML response: {e}")


# =============================================================================
# Commands
# =============================================================================


@app.command("list")
@command
def offers_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(
        100, "--limit", "-l", help="Maximum number of offers to return (max 200)"
    ),
    offset: int = typer.Option(0, "--offset", "-o", help="Offset for pagination"),
    item_id: Optional[str] = typer.Option(
        None, "--item-id", help="Filter by item ID"
    ),
    status: Optional[str] = typer.Option(
        "Active",
        "--status",
        help="Filter by status (Active, Accepted, Declined, Expired, etc.)",
    ),
    filters: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter (field:op:value). Operators: eq, ne, gt, gte, lt, lte, in, nin, like, ilike, null, notnull",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output",
    ),
):
    """
    List Best Offers from buyers.

    Examples:
        ebay seller offers list
        ebay seller offers list --table
        ebay seller offers list --item-id 123456789012
        ebay seller offers list --status Active --limit 50
    """
    try:
        client = get_client()

        # Calculate pagination for Trading API
        page_number = (offset // limit) + 1
        entries_per_page = min(limit, 200)

        # Get offers from API
        xml_response = client.get_best_offers(
            item_id=item_id,
            best_offer_status=status or "Active",
            entries_per_page=entries_per_page,
            page_number=page_number,
        )

        # Parse XML response
        offers, total_entries = _parse_best_offers_xml(xml_response)

        # Validate and apply client-side filters if provided
        if filters:
            try:
                validated_filters = validate_filters(filters)
                offers = apply_filters(offers, validated_filters)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Handle properties filtering
        if properties:
            try:
                offers = validate_and_filter_properties(offers, properties)
            except PropertyValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Display output
        if table:
            table_data = []
            for offer in offers:
                # Truncate title if too long
                title = offer.get("item_title", "")
                if len(title) > 40:
                    title = title[:37] + "..."

                # Truncate message if too long
                message = offer.get("buyer_message", "")
                if len(message) > 40:
                    message = message[:37] + "..."

                table_data.append(
                    {
                        "offer_id": offer.get("best_offer_id", ""),
                        "buyer": offer.get("buyer_user_id", ""),
                        "price": offer.get("price", ""),
                        "qty": offer.get("quantity", "1"),
                        "item_id": offer.get("item_id", ""),
                        "title": title,
                        "expires": format_local_time(offer.get("expiration_time", "")),
                        "message": message,
                    }
                )

            print_table(
                table_data,
                [
                    "offer_id",
                    "buyer",
                    "price",
                    "qty",
                    "item_id",
                    "title",
                    "expires",
                    "message",
                ],
                [
                    "Offer ID",
                    "Buyer",
                    "Price",
                    "Qty",
                    "Item ID",
                    "Title",
                    "Expires",
                    "Message",
                ],
            )
            print(f"\nTotal offers: {total_entries}", file=sys.stderr)
        else:
            # JSON output
            output = {
                "offers": offers,
                "total": total_entries,
                "limit": limit,
                "offset": offset,
            }
            print_json(output)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def offers_get(
    best_offer_id: str = typer.Argument(
        ..., help="Best Offer ID (use 'list' to find offer IDs)"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a specific Best Offer.

    Examples:
        ebay seller offers get 1234567890
        ebay seller offers get 1234567890 --table
    """
    try:
        client = get_client()

        # Get all offers and filter to the requested one
        xml_response = client.get_best_offers(
            best_offer_status="All",
            entries_per_page=200,
            page_number=1,
        )

        offers, _ = _parse_best_offers_xml(xml_response)

        # Find the requested offer
        offer = None
        for o in offers:
            if o.get("best_offer_id") == best_offer_id:
                offer = o
                break

        if not offer:
            print_error(f"Best Offer {best_offer_id} not found")
            raise typer.Exit(1)

        # Display output
        if table:
            # Show single offer in a detailed format
            print("\nBest Offer Details")
            print("=" * 80)
            print(f"Offer ID:        {offer.get('best_offer_id', '')}")
            print(f"Status:          {offer.get('status', '')}")
            print(f"Type:            {offer.get('best_offer_code_type', '')}")
            print(f"Buyer:           {offer.get('buyer_user_id', '')}")
            print(
                f"Buyer Feedback:  {offer.get('buyer_feedback_score', 'N/A')} ({offer.get('buyer_positive_feedback_percent', 'N/A')}%)"
            )
            print(f"Price:           ${offer.get('price', '0.00')}")
            print(f"Quantity:        {offer.get('quantity', '1')}")
            print(
                f"Expires:         {format_local_time(offer.get('expiration_time', ''))}"
            )
            print(f"Item ID:         {offer.get('item_id', '')}")
            print(f"Item Title:      {offer.get('item_title', '')}")
            print(
                f"Current Price:   ${offer.get('item_current_price', 'N/A')}"
            )
            print(f"Buyer Message:   {offer.get('buyer_message', '(none)')}")
            print("=" * 80)
        else:
            print_json(offer)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("accept")
@command
def offers_accept(
    best_offer_id: str = typer.Argument(..., help="Best Offer ID to accept"),
    item_id: str = typer.Option(..., "--item-id", help="Item ID for the offer"),
    message: Optional[str] = typer.Option(
        None, "--message", "-m", help="Optional message to the buyer"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip confirmation prompt"
    ),
):
    """
    Accept a Best Offer from a buyer.

    Examples:
        ebay seller offers accept 1234567890 --item-id 123456789012
        ebay seller offers accept 1234567890 --item-id 123456789012 --yes
        ebay seller offers accept 1234567890 --item-id 123456789012 --message "Thanks!"
    """
    try:
        client = get_client()

        # Get offer details to show what we're accepting
        xml_response = client.get_best_offers(
            best_offer_status="Active",
            entries_per_page=200,
            page_number=1,
        )
        offers, _ = _parse_best_offers_xml(xml_response)

        offer = None
        for o in offers:
            if o.get("best_offer_id") == best_offer_id:
                offer = o
                break

        if not offer:
            print_error(
                f"Best Offer {best_offer_id} not found or not active"
            )
            raise typer.Exit(1)

        # Show what we're accepting
        print_info("\nAccepting Best Offer:")
        print(f"  Offer ID: {best_offer_id}")
        print(f"  Buyer: {offer.get('buyer_user_id', 'Unknown')}")
        print(f"  Price: ${offer.get('price', '0.00')}")
        print(f"  Quantity: {offer.get('quantity', '1')}")
        print(f"  Item: {offer.get('item_title', 'Unknown')}")
        if message:
            print(f"  Message to buyer: {message}")

        # Confirm
        if not yes:
            confirm = typer.confirm(
                "\nAre you sure you want to accept this offer?"
            )
            if not confirm:
                print_info("Cancelled.")
                raise typer.Exit(0)

        # Accept the offer
        print_info("Accepting offer...")
        xml_response = client.respond_to_best_offer(
            item_id=item_id,
            best_offer_id=best_offer_id,
            action="Accept",
            seller_response=message,
        )

        # Parse response
        result = _parse_respond_to_best_offer_xml(xml_response)

        if result.get("ack") == "Success":
            print_success(f"Best Offer {best_offer_id} accepted!")
            print_info(
                "The buyer will receive a notification and the item will be marked as sold."
            )
        else:
            print_error("Failed to accept offer")
            raise typer.Exit(1)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("decline")
@command
def offers_decline(
    best_offer_id: str = typer.Argument(..., help="Best Offer ID to decline"),
    item_id: str = typer.Option(..., "--item-id", help="Item ID for the offer"),
    message: Optional[str] = typer.Option(
        None, "--message", "-m", help="Optional message to the buyer"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip confirmation prompt"
    ),
):
    """
    Decline a Best Offer from a buyer.

    Examples:
        ebay seller offers decline 1234567890 --item-id 123456789012
        ebay seller offers decline 1234567890 --item-id 123456789012 --yes
        ebay seller offers decline 1234567890 --item-id 123456789012 --message "Sorry, price is too low"
    """
    try:
        client = get_client()

        # Get offer details to show what we're declining
        xml_response = client.get_best_offers(
            best_offer_status="Active",
            entries_per_page=200,
            page_number=1,
        )
        offers, _ = _parse_best_offers_xml(xml_response)

        offer = None
        for o in offers:
            if o.get("best_offer_id") == best_offer_id:
                offer = o
                break

        if not offer:
            print_error(
                f"Best Offer {best_offer_id} not found or not active"
            )
            raise typer.Exit(1)

        # Show what we're declining
        print_info("\nDeclining Best Offer:")
        print(f"  Offer ID: {best_offer_id}")
        print(f"  Buyer: {offer.get('buyer_user_id', 'Unknown')}")
        print(f"  Price: ${offer.get('price', '0.00')}")
        print(f"  Quantity: {offer.get('quantity', '1')}")
        print(f"  Item: {offer.get('item_title', 'Unknown')}")
        if message:
            print(f"  Message to buyer: {message}")

        # Confirm
        if not yes:
            confirm = typer.confirm(
                "\nAre you sure you want to decline this offer?"
            )
            if not confirm:
                print_info("Cancelled.")
                raise typer.Exit(0)

        # Decline the offer
        print_info("Declining offer...")
        xml_response = client.respond_to_best_offer(
            item_id=item_id,
            best_offer_id=best_offer_id,
            action="Decline",
            seller_response=message,
        )

        # Parse response
        result = _parse_respond_to_best_offer_xml(xml_response)

        if result.get("ack") == "Success":
            print_success(f"Best Offer {best_offer_id} declined.")
        else:
            print_error("Failed to decline offer")
            raise typer.Exit(1)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("counter")
@command
def offers_counter(
    best_offer_id: str = typer.Argument(..., help="Best Offer ID to counter"),
    item_id: str = typer.Option(..., "--item-id", help="Item ID for the offer"),
    price: str = typer.Option(..., "--price", "-p", help="Counter offer price"),
    quantity: Optional[int] = typer.Option(
        None, "--quantity", "-q", help="Counter offer quantity"
    ),
    message: Optional[str] = typer.Option(
        None, "--message", "-m", help="Optional message to the buyer"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip confirmation prompt"
    ),
):
    """
    Send a counter offer to a buyer.

    Examples:
        ebay seller offers counter 1234567890 --item-id 123456789012 --price 45.00
        ebay seller offers counter 1234567890 --item-id 123456789012 --price 45.00 --yes
        ebay seller offers counter 1234567890 --item-id 123456789012 --price 45.00 --quantity 2
        ebay seller offers counter 1234567890 --item-id 123456789012 --price 45.00 --message "Best I can do"
    """
    try:
        client = get_client()

        # Validate price format
        try:
            price_decimal = Decimal(price)
            if price_decimal <= 0:
                print_error("Counter price must be greater than 0")
                raise typer.Exit(1)
            # Format to 2 decimal places
            price = f"{price_decimal:.2f}"
        except InvalidOperation:
            print_error(f"Invalid price format: {price}")
            raise typer.Exit(1)

        # Get offer details to show what we're countering
        xml_response = client.get_best_offers(
            best_offer_status="Active",
            entries_per_page=200,
            page_number=1,
        )
        offers, _ = _parse_best_offers_xml(xml_response)

        offer = None
        for o in offers:
            if o.get("best_offer_id") == best_offer_id:
                offer = o
                break

        if not offer:
            print_error(
                f"Best Offer {best_offer_id} not found or not active"
            )
            raise typer.Exit(1)

        # Show what we're countering
        print_info("\nSending Counter Offer:")
        print(f"  Offer ID: {best_offer_id}")
        print(f"  Buyer: {offer.get('buyer_user_id', 'Unknown')}")
        print(f"  Buyer's offer: ${offer.get('price', '0.00')}")
        print(f"  Your counter: ${price}")
        if quantity:
            print(f"  Quantity: {quantity}")
        else:
            print(f"  Quantity: {offer.get('quantity', '1')} (from original offer)")
        print(f"  Item: {offer.get('item_title', 'Unknown')}")
        if message:
            print(f"  Message to buyer: {message}")

        # Confirm
        if not yes:
            confirm = typer.confirm(
                "\nAre you sure you want to send this counter offer?"
            )
            if not confirm:
                print_info("Cancelled.")
                raise typer.Exit(0)

        # Send counter offer
        print_info("Sending counter offer...")
        xml_response = client.respond_to_best_offer(
            item_id=item_id,
            best_offer_id=best_offer_id,
            action="Counter",
            counter_offer_price=price,
            counter_offer_quantity=quantity,
            seller_response=message,
        )

        # Parse response
        result = _parse_respond_to_best_offer_xml(xml_response)

        if result.get("ack") == "Success":
            print_success(f"Counter offer sent to buyer!")
            print_info(
                "The buyer will receive your counter offer and can accept, decline, or counter."
            )
        else:
            print_error("Failed to send counter offer")
            raise typer.Exit(1)

    except Exception as e:
        raise typer.Exit(handle_error(e))
