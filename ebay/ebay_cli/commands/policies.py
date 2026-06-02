"""Fulfillment policy commands for eBay CLI.

Uses the eBay Account API to manage fulfillment policies (shipping/handling settings).
API Docs: https://developer.ebay.com/api-docs/sell/account/resources/fulfillment_policy/methods/getFulfillmentPolicies
"""
COMMAND_CREDENTIALS = {
    "list": ["oauth_authorization_code"],
    "get": ["oauth_authorization_code"],
    "create": ["oauth_authorization_code"],
    "update": ["oauth_authorization_code"],
    "delete": ["oauth_authorization_code"],
}

import typer
from typing import Optional, List

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error, print_info, print_success, print_error
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
from ..properties import validate_and_filter_properties, PropertyValidationError

app = typer.Typer(help="Manage eBay fulfillment policies")


@app.command("list")
def policies_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of policies to return"),
    marketplace: str = typer.Option(
        "EBAY_US",
        "--marketplace",
        "-m",
        help="eBay marketplace ID (e.g., EBAY_US, EBAY_GB, EBAY_DE)"
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
):
    """
    List all fulfillment policies for a marketplace.

    Fulfillment policies define handling time, shipping options, and other
    fulfillment-related settings for your listings.

    Examples:
        ebay policies list
        ebay policies list --table
        ebay policies list --marketplace EBAY_GB
        ebay policies list --filter "name:ilike:%standard%"
    """
    try:
        client = get_client()
        result = client.get_fulfillment_policies(marketplace_id=marketplace)

        policies = result.get("fulfillmentPolicies", [])

        # Validate and apply client-side filters if provided
        if filters:
            try:
                validated_filters = validate_filters(filters)
                policies = apply_filters(policies, validated_filters)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply properties filter if specified
        if properties:
            try:
                policies = validate_and_filter_properties(policies, properties)
            except PropertyValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply limit (client-side since eBay returns all at once)
        if limit > 0:
            policies = policies[:limit]

        if table:
            if not policies:
                print("No fulfillment policies found for this marketplace.")
                return

            table_data = []
            for p in policies:
                handling = p.get("handlingTime", {})
                categories = p.get("categoryTypes", [])
                category_names = [c.get("name", "") for c in categories]

                table_data.append({
                    "id": p.get("fulfillmentPolicyId", ""),
                    "name": p.get("name", ""),
                    "handling_days": f"{handling.get('value', '-')} {handling.get('unit', '').lower()}",
                    "categories": ", ".join(category_names),
                    "local_pickup": "Yes" if p.get("localPickup") else "No",
                    "global_shipping": "Yes" if p.get("globalShipping") else "No",
                })

            print_table(
                table_data,
                ["id", "name", "handling_days", "categories", "local_pickup", "global_shipping"],
                ["Policy ID", "Name", "Handling Time", "Categories", "Local Pickup", "Global Ship"],
            )
        else:
            print_json({"fulfillmentPolicies": policies, "total": result.get("total", len(policies))})

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def policies_get(
    policy_id: str = typer.Argument(..., help="The fulfillment policy ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
):
    """
    Get details for a specific fulfillment policy.

    Examples:
        ebay policies get 12345678
        ebay policies get 12345678 --table
    """
    try:
        client = get_client()
        policy = client.get_fulfillment_policy(policy_id)

        if table:
            handling = policy.get("handlingTime", {})
            categories = policy.get("categoryTypes", [])
            category_names = [c.get("name", "") for c in categories]

            summary = [{
                "id": policy.get("fulfillmentPolicyId", ""),
                "name": policy.get("name", ""),
                "marketplace": policy.get("marketplaceId", ""),
                "handling_days": f"{handling.get('value', '-')} {handling.get('unit', '').lower()}",
                "categories": ", ".join(category_names),
                "description": policy.get("description", "")[:50] if policy.get("description") else "",
            }]

            print_table(
                summary,
                ["id", "name", "marketplace", "handling_days", "categories", "description"],
                ["Policy ID", "Name", "Marketplace", "Handling", "Categories", "Description"],
            )

            # Show shipping options if present
            shipping_options = policy.get("shippingOptions", [])
            if shipping_options:
                print("\nShipping Options:")
                for opt in shipping_options:
                    option_type = opt.get("optionType", "")
                    cost_type = opt.get("costType", "")
                    services = opt.get("shippingServices", [])

                    print(f"  {option_type} ({cost_type}):")
                    for svc in services:
                        carrier = svc.get("shippingCarrierCode", "")
                        service = svc.get("shippingServiceCode", "")
                        cost = svc.get("shippingCost", {})
                        cost_str = f"{cost.get('value', '0')} {cost.get('currency', '')}" if cost else "N/A"
                        free = " (FREE)" if svc.get("freeShipping") else ""
                        print(f"    - {carrier} {service}: {cost_str}{free}")
        else:
            print_json(policy)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def policies_create(
    name: str = typer.Option(..., "--name", "-n", help="Policy name (must be unique)"),
    handling_days: int = typer.Option(..., "--handling-days", "-d", help="Handling time in business days (0 = same day)"),
    carrier: str = typer.Option(
        ...,
        "--carrier",
        help="Shipping carrier code (e.g., USPS, UPS, FedEx)"
    ),
    service: str = typer.Option(
        ...,
        "--service",
        "-s",
        help="Shipping service code (e.g., USPSParcel, UPSGround, FedExSmartPost)"
    ),
    cost_type: str = typer.Option(
        "CALCULATED",
        "--cost-type",
        help="Shipping cost type: CALCULATED or FLAT_RATE"
    ),
    shipping_cost: Optional[str] = typer.Option(
        None,
        "--shipping-cost",
        help="Flat-rate shipping cost in USD (e.g., '5.99'). Required when cost-type is FLAT_RATE"
    ),
    free_shipping: bool = typer.Option(False, "--free-shipping", help="Offer free shipping"),
    marketplace: str = typer.Option("EBAY_US", "--marketplace", "-m", help="eBay marketplace ID"),
    category: str = typer.Option(
        "ALL_EXCLUDING_MOTORS_VEHICLES",
        "--category",
        "-c",
        help="Category type: ALL_EXCLUDING_MOTORS_VEHICLES or MOTORS_VEHICLES"
    ),
    description: Optional[str] = typer.Option(None, "--description", help="Policy description"),
    local_pickup: bool = typer.Option(False, "--local-pickup", help="Enable local pickup"),
    global_shipping: bool = typer.Option(False, "--global-shipping", help="Enable Global Shipping Program (UK only)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
):
    """
    Create a new fulfillment policy.

    Fulfillment policies define how orders are handled and shipped.
    The handling time specifies how many business days you need to ship after payment.

    A shipping carrier, service code, and cost type are required by the eBay API.

    Examples:
        ebay seller policies create --name "UPS Ground - Buyer Pays" --handling-days 3 --carrier UPS --service UPSGround
        ebay seller policies create --name "Free FedEx" --handling-days 1 --carrier FedEx --service FedExSmartPost --free-shipping
        ebay seller policies create --name "USPS Flat Rate" --handling-days 2 --carrier USPS --service USPSPriority --cost-type FLAT_RATE --shipping-cost 5.99
    """
    try:
        # Validate cost_type
        cost_type_upper = cost_type.upper()
        if cost_type_upper not in ("CALCULATED", "FLAT_RATE"):
            print_error(f"Invalid cost type '{cost_type}'. Must be CALCULATED or FLAT_RATE.")
            raise typer.Exit(1)

        # Validate flat-rate requires shipping cost
        if cost_type_upper == "FLAT_RATE" and not shipping_cost and not free_shipping:
            print_error("--shipping-cost is required when cost-type is FLAT_RATE (unless --free-shipping is set).")
            raise typer.Exit(1)

        client = get_client()

        # Build shipping service entry
        shipping_service = {
            "sortOrder": 1,
            "shippingCarrierCode": carrier,
            "shippingServiceCode": service,
            "freeShipping": free_shipping,
            "buyerResponsibleForShipping": False,
            "buyerResponsibleForPickup": False,
        }

        # Add shipping cost for flat-rate
        if cost_type_upper == "FLAT_RATE":
            cost_value = "0.0" if free_shipping else shipping_cost
            shipping_service["shippingCost"] = {
                "value": cost_value,
                "currency": "USD",
            }
            shipping_service["additionalShippingCost"] = {
                "value": "0.0",
                "currency": "USD",
            }

        # Build shipping option
        shipping_option = {
            "optionType": "DOMESTIC",
            "costType": cost_type_upper,
            "shippingServices": [shipping_service],
            "shippingDiscountProfileId": "0",
            "shippingPromotionOffered": False,
        }

        # Add packageHandlingCost for calculated shipping
        if cost_type_upper == "CALCULATED":
            shipping_option["packageHandlingCost"] = {
                "value": "0.0",
                "currency": "USD",
            }

        policy_data = {
            "name": name,
            "marketplaceId": marketplace,
            "categoryTypes": [{"name": category}],
            "handlingTime": {
                "unit": "DAY",
                "value": handling_days
            },
            "shippingOptions": [shipping_option],
            "localPickup": local_pickup,
            "globalShipping": global_shipping,
        }

        if description:
            policy_data["description"] = description

        result = client.create_fulfillment_policy(policy_data)

        print_success(f"Fulfillment policy created: {result.get('fulfillmentPolicyId')}")

        if table:
            handling = result.get("handlingTime", {})
            summary = [{
                "id": result.get("fulfillmentPolicyId", ""),
                "name": result.get("name", ""),
                "handling_days": f"{handling.get('value', '-')} {handling.get('unit', '').lower()}",
                "marketplace": result.get("marketplaceId", ""),
            }]
            print_table(
                summary,
                ["id", "name", "handling_days", "marketplace"],
                ["Policy ID", "Name", "Handling Time", "Marketplace"],
            )
        else:
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def policies_update(
    policy_id: str = typer.Argument(..., help="The fulfillment policy ID to update"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="New policy name"),
    handling_days: Optional[int] = typer.Option(None, "--handling-days", "-d", help="New handling time in business days"),
    description: Optional[str] = typer.Option(None, "--description", help="New policy description"),
    local_pickup: Optional[bool] = typer.Option(None, "--local-pickup", help="Enable/disable local pickup"),
    global_shipping: Optional[bool] = typer.Option(None, "--global-shipping", help="Enable/disable Global Shipping"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
):
    """
    Update an existing fulfillment policy.

    Only the fields you specify will be updated. The policy is fetched first,
    then merged with your changes.

    Examples:
        ebay policies update 12345678 --handling-days 2
        ebay policies update 12345678 --name "New Name" --handling-days 1
        ebay policies update 12345678 --description "Updated description"
    """
    try:
        client = get_client()

        # Fetch current policy
        print_info(f"Fetching policy {policy_id}...")
        current = client.get_fulfillment_policy(policy_id)

        # Build update payload (must include required fields)
        policy_data = {
            "name": name if name is not None else current.get("name"),
            "marketplaceId": current.get("marketplaceId"),
            "categoryTypes": current.get("categoryTypes", []),
        }

        # Update handling time
        if handling_days is not None:
            policy_data["handlingTime"] = {"unit": "DAY", "value": handling_days}
        elif current.get("handlingTime"):
            policy_data["handlingTime"] = current.get("handlingTime")

        # Update optional fields
        if description is not None:
            policy_data["description"] = description
        elif current.get("description"):
            policy_data["description"] = current.get("description")

        if local_pickup is not None:
            policy_data["localPickup"] = local_pickup
        else:
            policy_data["localPickup"] = current.get("localPickup", False)

        if global_shipping is not None:
            policy_data["globalShipping"] = global_shipping
        else:
            policy_data["globalShipping"] = current.get("globalShipping", False)

        # Preserve existing shipping options
        if current.get("shippingOptions"):
            policy_data["shippingOptions"] = current.get("shippingOptions")
        if current.get("shipToLocations"):
            policy_data["shipToLocations"] = current.get("shipToLocations")

        result = client.update_fulfillment_policy(policy_id, policy_data)

        print_success(f"Fulfillment policy updated: {result.get('fulfillmentPolicyId')}")

        if table:
            handling = result.get("handlingTime", {})
            summary = [{
                "id": result.get("fulfillmentPolicyId", ""),
                "name": result.get("name", ""),
                "handling_days": f"{handling.get('value', '-')} {handling.get('unit', '').lower()}",
                "marketplace": result.get("marketplaceId", ""),
            }]
            print_table(
                summary,
                ["id", "name", "handling_days", "marketplace"],
                ["Policy ID", "Name", "Handling Time", "Marketplace"],
            )
        else:
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def policies_delete(
    policy_id: str = typer.Argument(..., help="The fulfillment policy ID to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """
    Delete a fulfillment policy.

    Note: You cannot delete a policy that is associated with active listings.
    You must first update those listings to use a different policy.

    Examples:
        ebay policies delete 12345678
        ebay policies delete 12345678 --force
    """
    try:
        client = get_client()

        # Get policy info for confirmation
        if not force:
            policy = client.get_fulfillment_policy(policy_id)
            policy_name = policy.get("name", policy_id)

            if not typer.confirm(f"Delete fulfillment policy '{policy_name}' ({policy_id})?"):
                print_info("Deletion cancelled.")
                raise typer.Exit(0)

        client.delete_fulfillment_policy(policy_id)
        print_success(f"Fulfillment policy {policy_id} deleted.")

    except Exception as e:
        raise typer.Exit(handle_error(e))


# ============================================================
# PAYMENT POLICIES
# ============================================================

payment_app = typer.Typer(help="Manage eBay payment policies")


@payment_app.command("list")
def payment_policies_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of policies to return"),
    marketplace: str = typer.Option(
        "EBAY_US",
        "--marketplace",
        "-m",
        help="eBay marketplace ID"
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
):
    """
    List all payment policies for a marketplace.

    Examples:
        ebay payment-policies list
        ebay payment-policies list --table
        ebay payment-policies list --marketplace EBAY_GB
        ebay payment-policies list --filter "name:ilike:%standard%"
    """
    try:
        client = get_client()
        result = client.get_payment_policies(marketplace_id=marketplace)

        policies = result.get("paymentPolicies", [])

        # Validate and apply client-side filters if provided
        if filters:
            try:
                validated_filters = validate_filters(filters)
                policies = apply_filters(policies, validated_filters)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply properties filter if specified
        if properties:
            try:
                policies = validate_and_filter_properties(policies, properties)
            except PropertyValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply limit (client-side since eBay returns all at once)
        if limit > 0:
            policies = policies[:limit]

        if table:
            if not policies:
                print("No payment policies found for this marketplace.")
                return

            table_data = []
            for p in policies:
                categories = p.get("categoryTypes", [])
                category_names = [c.get("name", "") for c in categories]

                table_data.append({
                    "id": p.get("paymentPolicyId", ""),
                    "name": p.get("name", ""),
                    "categories": ", ".join(category_names),
                    "immediate_pay": "Yes" if p.get("immediatePay") else "No",
                    "marketplace": p.get("marketplaceId", ""),
                })

            print_table(
                table_data,
                ["id", "name", "categories", "immediate_pay", "marketplace"],
                ["Policy ID", "Name", "Categories", "Immediate Pay", "Marketplace"],
            )
        else:
            print_json({"paymentPolicies": policies, "total": result.get("total", len(policies))})

    except Exception as e:
        raise typer.Exit(handle_error(e))


@payment_app.command("get")
def payment_policies_get(
    policy_id: str = typer.Argument(..., help="The payment policy ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
):
    """
    Get details for a specific payment policy.

    Examples:
        ebay payment-policies get 12345678
        ebay payment-policies get 12345678 --table
    """
    try:
        client = get_client()
        policy = client.get_payment_policy(policy_id)

        if table:
            categories = policy.get("categoryTypes", [])
            category_names = [c.get("name", "") for c in categories]

            summary = [{
                "id": policy.get("paymentPolicyId", ""),
                "name": policy.get("name", ""),
                "marketplace": policy.get("marketplaceId", ""),
                "categories": ", ".join(category_names),
                "immediate_pay": "Yes" if policy.get("immediatePay") else "No",
            }]

            print_table(
                summary,
                ["id", "name", "marketplace", "categories", "immediate_pay"],
                ["Policy ID", "Name", "Marketplace", "Categories", "Immediate Pay"],
            )
        else:
            print_json(policy)

    except Exception as e:
        raise typer.Exit(handle_error(e))


# ============================================================
# RETURN POLICIES
# ============================================================

return_app = typer.Typer(help="Manage eBay return policies")


@return_app.command("list")
def return_policies_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of policies to return"),
    marketplace: str = typer.Option(
        "EBAY_US",
        "--marketplace",
        "-m",
        help="eBay marketplace ID"
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
):
    """
    List all return policies for a marketplace.

    Examples:
        ebay return-policies list
        ebay return-policies list --table
        ebay return-policies list --marketplace EBAY_GB
        ebay return-policies list --filter "name:ilike:%standard%"
    """
    try:
        client = get_client()
        result = client.get_return_policies(marketplace_id=marketplace)

        policies = result.get("returnPolicies", [])

        # Validate and apply client-side filters if provided
        if filters:
            try:
                validated_filters = validate_filters(filters)
                policies = apply_filters(policies, validated_filters)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply properties filter if specified
        if properties:
            try:
                policies = validate_and_filter_properties(policies, properties)
            except PropertyValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply limit (client-side since eBay returns all at once)
        if limit > 0:
            policies = policies[:limit]

        if table:
            if not policies:
                print("No return policies found for this marketplace.")
                return

            table_data = []
            for p in policies:
                categories = p.get("categoryTypes", [])
                category_names = [c.get("name", "") for c in categories]
                return_period = p.get("returnPeriod", {})

                table_data.append({
                    "id": p.get("returnPolicyId", ""),
                    "name": p.get("name", ""),
                    "returns_accepted": "Yes" if p.get("returnsAccepted") else "No",
                    "return_period": f"{return_period.get('value', '')} {return_period.get('unit', '').lower()}",
                    "refund_method": p.get("refundMethod", ""),
                    "categories": ", ".join(category_names),
                })

            print_table(
                table_data,
                ["id", "name", "returns_accepted", "return_period", "refund_method", "categories"],
                ["Policy ID", "Name", "Returns", "Period", "Refund", "Categories"],
            )
        else:
            print_json({"returnPolicies": policies, "total": result.get("total", len(policies))})

    except Exception as e:
        raise typer.Exit(handle_error(e))


@return_app.command("get")
def return_policies_get(
    policy_id: str = typer.Argument(..., help="The return policy ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
):
    """
    Get details for a specific return policy.

    Examples:
        ebay return-policies get 12345678
        ebay return-policies get 12345678 --table
    """
    try:
        client = get_client()
        policy = client.get_return_policy(policy_id)

        if table:
            categories = policy.get("categoryTypes", [])
            category_names = [c.get("name", "") for c in categories]
            return_period = policy.get("returnPeriod", {})

            summary = [{
                "id": policy.get("returnPolicyId", ""),
                "name": policy.get("name", ""),
                "marketplace": policy.get("marketplaceId", ""),
                "returns_accepted": "Yes" if policy.get("returnsAccepted") else "No",
                "return_period": f"{return_period.get('value', '')} {return_period.get('unit', '').lower()}",
                "refund_method": policy.get("refundMethod", ""),
                "shipping_cost_payer": policy.get("returnShippingCostPayer", ""),
            }]

            print_table(
                summary,
                ["id", "name", "marketplace", "returns_accepted", "return_period", "refund_method", "shipping_cost_payer"],
                ["Policy ID", "Name", "Marketplace", "Returns", "Period", "Refund", "Shipping Cost"],
            )
        else:
            print_json(policy)

    except Exception as e:
        raise typer.Exit(handle_error(e))
