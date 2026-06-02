"""Orders commands for eBay CLI.

Uses the eBay Fulfillment API to query and manage orders.
API Docs: https://developer.ebay.com/api-docs/sell/fulfillment/resources/order/methods/getOrders
"""
COMMAND_CREDENTIALS = {
    "list": ["oauth_authorization_code"],
    "get": ["oauth_authorization_code"],
    "fulfillments": ["oauth_authorization_code"],
    "create": ["oauth_authorization_code"],
}

import sys
import typer
from typing import Optional, List, Any, Dict

from ..client import get_client
from ..config import get_config
from cli_tools_shared.output import print_json, print_table, handle_error, print_error
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
from ..parsers import format_local_time, format_date
from ..properties import validate_and_filter_properties, PropertyValidationError

app = typer.Typer(help="Manage eBay orders")
shipping_label_app = typer.Typer(help="Manage eBay shipping labels")


@app.command("list")
def orders_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of orders to return (max 200)"),
    offset: int = typer.Option(0, "--offset", "-o", help="Offset for pagination"),
    status: Optional[str] = typer.Option(
        None, 
        "--status", 
        "-s", 
        help="Filter by fulfillment status: NOT_STARTED, IN_PROGRESS, FULFILLED"
    ),
    shipped: bool = typer.Option(
        False,
        "--shipped",
        help="Filter for shipped orders (FULFILLED)"
    ),
    not_shipped: bool = typer.Option(
        False,
        "--not-shipped",
        help="Filter for unshipped orders (NOT_STARTED or IN_PROGRESS)"
    ),
    order_ids: Optional[str] = typer.Option(
        None,
        "--order-ids",
        help="Comma-separated list of order IDs to retrieve"
    ),
    filters: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter (field:op:value). Operators: eq, ne, gt, gte, lt, lte, in, nin, like, ilike, null, notnull"
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """
    List eBay orders with advanced filtering.
    
    IMPORTANT: By default, eBay returns orders from the last 90 days only. 
    To see older orders, use a 'created' filter (e.g., --filter "created:gte:2023-01-01").
    
    Pagination: Use --limit (max 200) and --offset to page through results.
    The output includes 'total_matches' to show how many orders are available.
    
    Syntax: field:operator:value (e.g., total:gt:100)
    Default operator is 'eq' (e.g., status:FULFILLED)
    
    Server-side filters (efficient):
      - status: NOT_STARTED, IN_PROGRESS, FULFILLED
      - created: ISO 8601 date (e.g., 2023-01-01)
      - modified: ISO 8601 date
    
    Client-side filters (any field):
      - total, buyer, payment_status, cancel_status, etc.
    
    Logic:
      - AND: Comma-separated in one flag: --filter "status:FULFILLED,total:gt:100"
      - OR: Multiple flags: --filter "status:NOT_STARTED" --filter "status:IN_PROGRESS"
    
    Examples:
        ebay orders list --status NOT_STARTED
        ebay orders list --not-shipped
        ebay orders list --filter "total:gt:100"
        ebay orders list --filter "created:gte:2023-01-01"
        ebay orders list --filter "buyer:ilike:%example%"
    """
    try:
        # Check exclusivity
        if sum([bool(status), shipped, not_shipped]) > 1:
            print_error("Cannot use --status, --shipped, and --not-shipped together.")
            raise typer.Exit(1)

        # Combine options into filters
        all_filters = []
        if filters:
            all_filters.extend(filters)
            
        if status:
            all_filters.append(f"status:eq:{status}")
        elif shipped:
            all_filters.append("status:eq:FULFILLED")
        elif not_shipped:
            all_filters.append("status:in:NOT_STARTED|IN_PROGRESS")
            
        # Validate filters
        if all_filters:
            validate_filters(all_filters)

        client = get_client(profile=profile)
        
        # Parse order IDs if provided
        order_id_list = None
        if order_ids:
            order_id_list = [oid.strip() for oid in order_ids.split(",")]
        
        # Get orders (server-side filtering happens here for supported fields)
        result = client.get_orders(
            filters=all_filters,
            limit=limit,
            offset=offset,
            order_ids=order_id_list,
        )
        
        orders = result.get("orders", [])
        
        # Transform orders
        formatted_orders = []
        for order in orders:
            buyer = order.get("buyer", {})
            pricing = order.get("pricingSummary", {})
            cancel_status = order.get("cancelStatus", {})
            
            formatted_orders.append({
                "order_id": order.get("orderId", ""),
                "fulfillment_status": order.get("orderFulfillmentStatus", ""),
                "status": order.get("orderFulfillmentStatus", ""), # Alias for filtering
                "payment_status": order.get("orderPaymentStatus", ""),
                "cancel_status": cancel_status.get("cancelState", ""),
                "buyer": buyer.get("username", ""),
                "total": pricing.get("total", {}).get("value", ""),
                "created": format_date(order.get("creationDate", "")),
                # Include full date for better client-side filtering if needed, 
                # but 'created' is what user sees.
                # Let's add hidden fields if we want precise filtering, 
                # but filters usually target visible columns.
            })
            
        # Apply client-side filters (for non-server fields like total, buyer)
        if all_filters:
            formatted_orders = apply_filters(formatted_orders, all_filters)

        # Apply properties filter if specified
        if properties:
            try:
                output_data = {"orders": formatted_orders}
                output_data = validate_and_filter_properties(output_data, properties, "orders")
                formatted_orders = output_data["orders"]
            except PropertyValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        if table:
            print_table(
                formatted_orders,
                ["order_id", "fulfillment_status", "payment_status", "cancel_status", "buyer", "total", "created"],
                ["Order ID", "Fulfillment", "Payment", "Cancel", "Buyer", "Total", "Created"],
            )
        else:
            output = {
                "orders": formatted_orders, 
                "count": len(formatted_orders),
                "total_matches": result.get("total", 0)
            }
            print_json(output)
            
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def orders_get(
    order_id: str = typer.Argument(..., help="The eBay order ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
    include_shipping_labels: bool = typer.Option(
        False, 
        "--include-shipping-labels", 
        "--include_shipping_labels",
        "-i", 
        help="Include shipping labels/fulfillments in output"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """
    Get details for a specific order.
    
    Examples:
        ebay orders get 12-12345-12345
        ebay orders get 12-12345-12345 --table
        ebay orders get 12-12345-12345 --include-shipping-labels
    """
    try:
        client = get_client(profile=profile)
        order = client.get_order(order_id)
        
        fulfillments = []
        if include_shipping_labels:
            result = client.get_shipping_fulfillments(order_id)
            fulfillments = result.get("fulfillments", [])
            # For JSON output, merge it into the order object
            if not table:
                order["fulfillments"] = fulfillments

        if table:
            # Show order summary in table format
            buyer = order.get("buyer", {})
            pricing = order.get("pricingSummary", {})
            fulfillment_instructions = order.get("fulfillmentStartInstructions", [{}])[0]
            ship_to = fulfillment_instructions.get("shippingStep", {}).get("shipTo", {})
            cancel_status = order.get("cancelStatus", {})
            
            summary = [{
                "order_id": order.get("orderId", ""),
                "fulfillment_status": order.get("orderFulfillmentStatus", ""),
                "payment_status": order.get("orderPaymentStatus", ""),
                "cancel_status": cancel_status.get("cancelState", ""),
                "buyer": buyer.get("username", ""),
                "total": pricing.get("total", {}).get("value", ""),
                "ship_to": f"{ship_to.get('fullName', '')} - {ship_to.get('contactAddress', {}).get('city', '')}",
            }]
            
            print_table(
                summary,
                ["order_id", "fulfillment_status", "payment_status", "cancel_status", "buyer", "total", "ship_to"],
                ["Order ID", "Fulfillment", "Payment", "Cancel", "Buyer", "Total", "Ship To"],
            )
            
            # Show line items
            line_items = order.get("lineItems", [])
            if line_items:
                items_data = []
                for item in line_items:
                    items_data.append({
                        "sku": item.get("sku", ""),
                        "title": item.get("title", "")[:40] + "..." if len(item.get("title", "")) > 40 else item.get("title", ""),
                        "quantity": item.get("quantity", ""),
                        "price": item.get("lineItemCost", {}).get("value", ""),
                    })
                
                print("\nLine Items:")
                print_table(
                    items_data,
                    ["sku", "title", "quantity", "price"],
                    ["SKU", "Title", "Qty", "Price"],
                )
            
            # Show fulfillments if requested
            if include_shipping_labels:
                print("\nShipping Fulfillments:")
                if not fulfillments:
                    print("No shipping fulfillments found.")
                else:
                    fulfillments_data = []
                    for f in fulfillments:
                        fulfillments_data.append({
                            "fulfillment_id": f.get("fulfillmentId", ""),
                            "carrier": f.get("shippingCarrierCode", ""),
                            "tracking": f.get("trackingNumber", ""),
                            "shipped_date": format_date(f.get("shippedDate", "")),
                        })

                    print_table(
                        fulfillments_data,
                        ["fulfillment_id", "carrier", "tracking", "shipped_date"],
                        ["Fulfillment ID", "Carrier", "Tracking #", "Shipped"],
                    )

        else:
            print_json(order)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@shipping_label_app.command("create")
def shipping_label_create(
    order_id: str = typer.Argument(..., help="The eBay order ID"),
    weight: float = typer.Option(..., help="Package weight value"),
    weight_unit: str = typer.Option("POUND", help="Weight unit: POUND, OUNCE, KILOGRAM, GRAM"),
    length: float = typer.Option(..., help="Package length"),
    width: float = typer.Option(..., help="Package width"),
    height: float = typer.Option(..., help="Package height"),
    dimension_unit: str = typer.Option("INCH", help="Dimension unit: INCH, CENTIMETER"),

    # Sender info (defaults from config)
    from_name: Optional[str] = typer.Option(None, help="Sender full name (defaults to profile config)"),
    from_street: Optional[str] = typer.Option(None, help="Sender street address (defaults to profile config)"),
    from_city: Optional[str] = typer.Option(None, help="Sender city (defaults to profile config)"),
    from_state: Optional[str] = typer.Option(None, help="Sender state/province code (defaults to profile config)"),
    from_zip: Optional[str] = typer.Option(None, help="Sender postal code (defaults to profile config)"),
    from_country: Optional[str] = typer.Option(None, help="Sender country code (defaults to profile config)"),
    from_phone: Optional[str] = typer.Option(None, help="Sender phone number (defaults to profile config)"),

    # Optional overrides
    to_name: Optional[str] = typer.Option(None, help="Override recipient name"),
    to_phone: Optional[str] = typer.Option(None, help="Override recipient phone"),

    service: Optional[str] = typer.Option(None, help="Preferred USPS service name (substring match)"),
    insurance: bool = typer.Option(False, help="Add shipping insurance (SHIP_COVER_INSURANCE)"),
    proof_of_delivery: bool = typer.Option(False, help="Add proof of delivery / signature"),
    label_message: Optional[str] = typer.Option(None, help="Custom message on label"),

    interactive: bool = typer.Option(True, help="Interactively select rate"),
    rate_index: int = typer.Option(1, "--rate-index", help="1-based rate to select"),
    dry_run: bool = typer.Option(False, help="Only show quotes, do not purchase"),
    out: Optional[str] = typer.Option(None, "--out", "-o", help="Output file path for the label PDF"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """
    Create and purchase a USPS shipping label for an eBay order.

    Uses the eBay Logistics API to get shipping quotes and purchase a label.
    The buyer's address is automatically fetched from the order.

    Examples:
        ebay shipping-labels create 04-08365-42542 --weight 2
        ebay shipping-labels create 04-08365-42542 --weight 1.5 --length 10 --width 8 --height 4
        ebay shipping-labels create 04-08365-42542 --weight 2 --service "Priority" --dry-run
        ebay shipping-labels create 04-08365-42542 --weight 2 --insurance --out label.pdf
    """
    try:
        config = get_config(profile=profile)
        client = get_client(profile=profile)

        # 1. Fetch order details for ship-to address
        print_error(f"Fetching order {order_id}...")
        order = client.get_order(order_id)

        fulfillment_instructions = order.get("fulfillmentStartInstructions", [{}])[0]
        ship_to_data = fulfillment_instructions.get("shippingStep", {}).get("shipTo", {})
        address = ship_to_data.get("contactAddress", {})

        dest_name = to_name or ship_to_data.get("fullName")
        dest_phone = to_phone or ship_to_data.get("primaryPhone", {}).get("phoneNumber")

        # 2. Build shipping quote request (eBay Logistics API contract)
        # Use provided options or fall back to profile config
        f_name = from_name or config.get_from_name()
        f_street = from_street or config.get_from_street()
        f_city = from_city or config.get_from_city()
        f_state = from_state or config.get_from_state()
        f_zip = from_zip or config.get_from_zip()
        f_country = from_country or config.get_from_country()
        f_phone = from_phone or config.get_from_phone()

        if not all([f_name, f_street, f_city, f_state, f_zip, f_country]):
            print_error("Missing sender address. Provide via options or configure in profile.")
            raise typer.Exit(1)

        ship_from = {
            "fullName": f_name,
            "contactAddress": {
                "addressLine1": f_street,
                "city": f_city,
                "stateOrProvince": f_state,
                "postalCode": f_zip,
                "countryCode": f_country,
            },
        }
        if f_phone:
            ship_from["primaryPhone"] = {"phoneNumber": f_phone}

        ship_to = {
            "fullName": dest_name,
            "contactAddress": {
                "addressLine1": address.get("addressLine1"),
                "addressLine2": address.get("addressLine2"),
                "city": address.get("city"),
                "stateOrProvince": address.get("stateOrProvince"),
                "postalCode": address.get("postalCode"),
                "countryCode": address.get("countryCode"),
            },
        }
        if dest_phone:
            ship_to["primaryPhone"] = {"phoneNumber": dest_phone}
        # Remove None values from address
        ship_to["contactAddress"] = {k: v for k, v in ship_to["contactAddress"].items() if v}

        package_spec: Dict[str, Any] = {
            "weight": {"value": str(weight), "unit": weight_unit},
            "dimensions": {
                "length": str(length),
                "width": str(width),
                "height": str(height),
                "unit": dimension_unit,
            },
        }

        payload = {
            "orders": [{"channel": "EBAY", "orderId": order_id}],
            "packageSpecification": package_spec,
            "shipFrom": ship_from,
            "shipTo": ship_to,
        }

        # 3. Get quotes
        print_error("Fetching shipping quotes...")
        quote_result = client.create_shipping_quote(payload)

        quote_id = quote_result.get("shippingQuoteId")
        rates = quote_result.get("rates", [])

        if not rates:
            print_error("No shipping rates available for this order.")
            raise typer.Exit(1)

        # 4. Build rate display list
        all_rates = []
        for rate in rates:
            base_cost = float(rate.get("baseShippingCost", {}).get("value", 0))
            # Collect available add-on options (exclude free PRINT_IN_STORE)
            options = [
                o for o in rate.get("additionalOptions", [])
                if o.get("optionType") != "PRINT_IN_STORE"
            ]
            option_names = [o.get("optionType") for o in options]

            all_rates.append({
                "quote_id": quote_id,
                "rate_id": rate.get("rateId"),
                "carrier": rate.get("shippingCarrierName", "USPS"),
                "service": rate.get("shippingServiceName", ""),
                "service_code": rate.get("shippingServiceCode", ""),
                "package": rate.get("shippingPackageName", ""),
                "base_cost": base_cost,
                "currency": rate.get("baseShippingCost", {}).get("currency", "USD"),
                "options": options,
                "option_names": option_names,
                "recommendations": rate.get("rateRecommendation", []),
                "min_delivery": rate.get("minEstimatedDeliveryDate", ""),
                "max_delivery": rate.get("maxEstimatedDeliveryDate", ""),
            })

        # 5. Filter rates if requested
        if service:
            all_rates = [r for r in all_rates if service.lower() in r["service"].lower()]

        if not all_rates:
            print_error("No shipping rates match your filters.")
            raise typer.Exit(1)

        # Sort by base cost
        all_rates.sort(key=lambda x: x["base_cost"])

        # 6. Display and select rate
        if dry_run or interactive:
            print("\nAvailable USPS Rates:", file=sys.stderr)
            for i, r in enumerate(all_rates):
                rec = ""
                if r["recommendations"]:
                    rec = f" [{', '.join(r['recommendations'])}]"
                opts_str = ""
                if r["option_names"]:
                    opt_details = []
                    for o in r["options"]:
                        cost = o.get("additionalCost", {}).get("value", "0")
                        opt_details.append(f"{o['optionType']}(+${cost})")
                    opts_str = f" | add-ons: {', '.join(opt_details)}"
                delivery = ""
                if r["min_delivery"] and r["max_delivery"]:
                    d_min = format_date(r["min_delivery"])
                    d_max = format_date(r["max_delivery"])
                    delivery = f" | {d_min} to {d_max}"
                pkg = f" ({r['package']})" if r["package"] else ""
                print(f"  {i+1}. {r['service']}{pkg} - ${r['base_cost']:.2f}{delivery}{rec}{opts_str}", file=sys.stderr)

        if dry_run:
            print_json({"quote_id": quote_id, "rates": all_rates})
            return

        selected_rate = None
        if interactive:
            choice = rate_index
            if 1 <= choice <= len(all_rates):
                selected_rate = all_rates[choice - 1]
            else:
                print_error("Invalid selection.")
                raise typer.Exit(1)
        else:
            selected_rate = all_rates[0]
            print_error(f"Auto-selected: {selected_rate['service']} - ${selected_rate['base_cost']:.2f}")

        # 7. Build additional options for purchase
        additional_options = []
        for opt in selected_rate["options"]:
            opt_type = opt.get("optionType")
            if (opt_type == "SHIP_COVER_INSURANCE" and insurance) or \
               (opt_type == "PROOF_OF_DELIVERY" and proof_of_delivery):
                additional_options.append({
                    "optionType": opt_type,
                    "additionalCost": opt.get("additionalCost"),
                })

        # Calculate total
        total = selected_rate["base_cost"]
        for opt in additional_options:
            total += float(opt.get("additionalCost", {}).get("value", 0))

        if not typer.confirm(f"Purchase label for ${total:.2f} {selected_rate['currency']}?"):
            print_error("Cancelled.")
            return

        # 8. Purchase label
        print_error("Purchasing label...")
        shipment = client.create_from_shipping_quote(
            quote_id=selected_rate["quote_id"],
            rate_id=selected_rate["rate_id"],
            additional_options=additional_options or None,
            label_custom_message=label_message,
        )

        shipment_id = shipment.get("shipmentId")
        tracking = shipment.get("shipmentTrackingNumber")
        total_cost = shipment.get("rate", {}).get("totalShippingCost", {})

        print_error(f"Shipment created: {shipment_id}")
        print_error(f"Tracking number: {tracking}")
        print_error(f"Total charged: ${total_cost.get('value', '?')} {total_cost.get('currency', '')}")

        # 9. Download label
        path = out or f"label_{order_id}.pdf"
        label_downloaded = False
        if out or typer.confirm("Download label PDF now?"):
            print_error(f"Downloading label to {path}...")
            content = client.download_label_file(shipment_id)
            with open(path, "wb") as f:
                f.write(content)
            print_error(f"Label saved to {path}")
            label_downloaded = True
        else:
            print_error(f"Download later: ebay shipping-labels download {shipment_id}")

        # Output shipment summary as JSON
        print_json({
            "shipment_id": shipment_id,
            "tracking_number": tracking,
            "service": shipment.get("rate", {}).get("shippingServiceName", ""),
            "total_cost": total_cost.get("value", ""),
            "currency": total_cost.get("currency", ""),
            "order_id": order_id,
            "label_file": path if label_downloaded else None,
        })

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


def _void_shipment(shipment_id: str, force: bool):
    """Shared implementation for void/cancel commands."""
    try:
        if not force:
            if not typer.confirm(f"Void shipment {shipment_id}? This will cancel the label and refund the cost."):
                print_error("Aborted.")
                return

        client = get_client()
        result = client.cancel_shipment(shipment_id)

        cancel = result.get("cancellation", {})
        status = cancel.get("cancellationStatus", "UNKNOWN")
        print_error(f"Void status: {status}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@shipping_label_app.command("void")
def shipping_label_void(
    shipment_id: str = typer.Argument(..., help="The shipment ID to void"),
    force: bool = typer.Option(False, "--force", help="Skip confirmation"),
):
    """
    Void a shipping label and receive a refund.

    Examples:
        ebay shipping-labels void S12345
        ebay shipping-labels void S12345 --force
    """
    _void_shipment(shipment_id, force)


@shipping_label_app.command("cancel", hidden=True)
def shipping_label_cancel(
    shipment_id: str = typer.Argument(..., help="The shipment ID to cancel"),
    force: bool = typer.Option(False, "--force", help="Skip confirmation"),
):
    """Alias for 'void'."""
    _void_shipment(shipment_id, force)


@shipping_label_app.command("download")
def shipping_label_download(
    shipment_id: str = typer.Argument(..., help="The shipment ID"),
    out: str = typer.Option(None, "--out", "-o", help="Output file path (default: label_<shipment_id>.pdf)"),
):
    """
    Download the shipping label PDF for a shipment.

    Examples:
        ebay shipping-labels download S12345
        ebay shipping-labels download S12345 --out my-label.pdf
    """
    try:
        client = get_client()
        path = out or f"label_{shipment_id}.pdf"

        print_error(f"Downloading label to {path}...")
        content = client.download_label_file(shipment_id)
        with open(path, "wb") as f:
            f.write(content)
        print_error(f"Label saved to {path}")

        print_json({"shipment_id": shipment_id, "label_file": path, "size_bytes": len(content)})

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("fulfillments")
def orders_fulfillments(
    order_id: str = typer.Argument(..., help="The eBay order ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """
    Get shipping fulfillments for an order.
    
    Examples:
        ebay orders fulfillments 12-12345-12345
        ebay orders fulfillments 12-12345-12345 --table
    """
    try:
        client = get_client(profile=profile)
        result = client.get_shipping_fulfillments(order_id)
        
        fulfillments = result.get("fulfillments", [])
        
        if table:
            if not fulfillments:
                print("No fulfillments found for this order.")
                return
                
            table_data = []
            for f in fulfillments:
                table_data.append({
                    "fulfillment_id": f.get("fulfillmentId", ""),
                    "carrier": f.get("shippingCarrierCode", ""),
                    "tracking": f.get("trackingNumber", ""),
                    "shipped_date": format_date(f.get("shippedDate", "")),
                })

            print_table(
                table_data,
                ["fulfillment_id", "carrier", "tracking", "shipped_date"],
                ["Fulfillment ID", "Carrier", "Tracking #", "Shipped"],
            )
        else:
            print_json(result)
            
    except Exception as e:
        raise typer.Exit(handle_error(e))
