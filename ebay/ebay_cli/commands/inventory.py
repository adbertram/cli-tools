"""Inventory commands for eBay CLI.

Uses the eBay Inventory API to manage inventory items.
API Docs: https://developer.ebay.com/api-docs/sell/inventory/resources/inventory_item/methods/getInventoryItems
"""
COMMAND_CREDENTIALS = {
    "list": ["oauth_authorization_code"],
    "get": ["oauth_authorization_code"],
    "create": ["oauth_authorization_code"],
    "update": ["oauth_authorization_code"],
    "delete": ["oauth_authorization_code"],
}

import json
import typer
from typing import Optional, List

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error, print_success, print_info, print_error
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
from ..properties import validate_and_filter_properties, PropertyValidationError

app = typer.Typer(help="Manage eBay inventory items")


def _deep_merge(base: dict, updates: dict) -> dict:
    """
    Deep merge updates into base dict.

    - Nested dicts are merged recursively
    - Lists and other values in updates replace base values
    - Keys not in updates are preserved from base

    Args:
        base: The base dictionary to merge into
        updates: The updates to apply

    Returns:
        Merged dictionary
    """
    result = base.copy()
    for key, value in updates.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@app.command("list")
def inventory_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of items to return (max 200)"),
    offset: int = typer.Option(0, "--offset", "-o", help="Offset for pagination"),
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
    List all inventory items.

    Examples:
        ebay inventory list
        ebay inventory list --table
        ebay inventory list --limit 50 --offset 100
        ebay inventory list --filter "condition:eq:NEW"
    """
    try:
        client = get_client()
        result = client.get_inventory_items(limit=limit, offset=offset)

        items = result.get("inventoryItems", [])

        # Transform items to flat structure for filtering
        flat_items = []
        for item in items:
            product = item.get("product", {})
            availability = item.get("availability", {})
            ship_avail = availability.get("shipToLocationAvailability", {})

            flat_items.append({
                "sku": item.get("sku", ""),
                "title": product.get("title", "") or "",
                "condition": item.get("condition", ""),
                "quantity": ship_avail.get("quantity", ""),
                "locale": item.get("locale", ""),
            })

        # Validate and apply client-side filters if provided
        if filters:
            try:
                validated_filters = validate_filters(filters)
                flat_items = apply_filters(flat_items, validated_filters)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply properties filtering
        if properties:
            try:
                flat_items = validate_and_filter_properties(flat_items, properties)
            except PropertyValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        if table:
            if not flat_items:
                print("No inventory items found.")
                return

            # Truncate titles for table display
            table_data = []
            for item in flat_items:
                display_item = item.copy()
                title = display_item.get("title", "")
                if len(title) > 40:
                    display_item["title"] = title[:37] + "..."
                table_data.append(display_item)

            print_table(
                table_data,
                ["sku", "title", "condition", "quantity", "locale"],
                ["SKU", "Title", "Condition", "Qty", "Locale"],
            )
        else:
            # Return filtered data in JSON
            output = {
                "inventoryItems": flat_items,
                "total": len(flat_items),
            }
            print_json(output)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def inventory_get(
    sku: str = typer.Argument(..., help="The SKU of the inventory item"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
):
    """
    Get details for a specific inventory item.

    Examples:
        ebay inventory get MY-SKU-123
        ebay inventory get MY-SKU-123 --table
    """
    try:
        client = get_client()
        result = client.get_inventory_item(sku)

        if table:
            product = result.get("product", {})
            availability = result.get("availability", {})
            ship_avail = availability.get("shipToLocationAvailability", {})

            summary = [{
                "sku": sku,
                "title": product.get("title", ""),
                "condition": result.get("condition", ""),
                "quantity": ship_avail.get("quantity", ""),
                "locale": result.get("locale", ""),
            }]

            print_table(
                summary,
                ["sku", "title", "condition", "quantity", "locale"],
                ["SKU", "Title", "Condition", "Qty", "Locale"],
            )

            # Show aspects if present
            aspects = product.get("aspects", {})
            if aspects:
                print("\nItem Specifics:")
                for key, values in aspects.items():
                    print(f"  {key}: {', '.join(values) if isinstance(values, list) else values}")

            # Show images
            images = product.get("imageUrls", [])
            if images:
                print(f"\nImages: {len(images)}")
                for img in images[:3]:
                    print(f"  {img}")
                if len(images) > 3:
                    print(f"  ... and {len(images) - 3} more")
        else:
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def inventory_create(
    sku: str = typer.Argument(..., help="The SKU for the inventory item (must be unique)"),
    title: str = typer.Option(..., "--title", help="Product title"),
    condition: str = typer.Option("NEW", "--condition", "-c", help="Item condition: NEW, LIKE_NEW, NEW_OTHER, NEW_WITH_DEFECTS, MANUFACTURER_REFURBISHED, CERTIFIED_REFURBISHED, EXCELLENT_REFURBISHED, VERY_GOOD_REFURBISHED, GOOD_REFURBISHED, SELLER_REFURBISHED, USED_EXCELLENT, USED_VERY_GOOD, USED_GOOD, USED_ACCEPTABLE, FOR_PARTS_OR_NOT_WORKING"),
    quantity: int = typer.Option(1, "--quantity", "-q", help="Available quantity"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Product description"),
    image_urls: Optional[str] = typer.Option(None, "--images", help="Comma-separated list of image URLs (HTTPS)"),
    aspects: Optional[str] = typer.Option(None, "--aspects", help="Item specifics as JSON object: '{\"Brand\": [\"MyBrand\"], \"Color\": [\"Red\"]}'"),
    from_json: Optional[str] = typer.Option(None, "--from-json", help="Path to JSON file containing full inventory item payload"),
    locale: str = typer.Option("en_US", "--locale", help="Locale for the inventory item"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
):
    """
    Create or update an inventory item.

    Use --from-json to provide a complete payload for advanced use cases.
    CLI flags override values from --from-json.

    Examples:
        ebay inventory create SKU123 --title "My Product" --quantity 10
        ebay inventory create SKU123 --title "Widget" --condition USED_GOOD --quantity 5 --description "Gently used widget"
        ebay inventory create SKU123 --from-json payload.json
    """
    try:
        client = get_client()

        # Start with JSON file if provided
        if from_json:
            with open(from_json, "r") as f:
                payload = json.load(f)
        else:
            payload = {}

        # Build/override product section
        if "product" not in payload:
            payload["product"] = {}

        payload["product"]["title"] = title

        if description:
            payload["product"]["description"] = description

        if image_urls:
            payload["product"]["imageUrls"] = [url.strip() for url in image_urls.split(",")]

        if aspects:
            payload["product"]["aspects"] = json.loads(aspects)

        # Set condition
        payload["condition"] = condition

        # Set availability
        if "availability" not in payload:
            payload["availability"] = {}
        if "shipToLocationAvailability" not in payload["availability"]:
            payload["availability"]["shipToLocationAvailability"] = {}
        payload["availability"]["shipToLocationAvailability"]["quantity"] = quantity

        result = client.create_or_update_inventory_item(sku, payload)

        print_success(f"Inventory item '{sku}' created/updated successfully.")

        if table:
            summary = [{
                "sku": sku,
                "title": title,
                "condition": condition,
                "quantity": quantity,
            }]
            print_table(
                summary,
                ["sku", "title", "condition", "quantity"],
                ["SKU", "Title", "Condition", "Qty"],
            )
        else:
            # Return the created item for verification
            item = client.get_inventory_item(sku)
            print_json(item)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def inventory_update(
    sku: str = typer.Argument(..., help="The SKU of the inventory item to update"),
    title: Optional[str] = typer.Option(None, "--title", help="New product title"),
    condition: Optional[str] = typer.Option(None, "--condition", "-c", help="New item condition"),
    quantity: Optional[int] = typer.Option(None, "--quantity", "-q", help="New available quantity"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="New product description"),
    image_urls: Optional[str] = typer.Option(None, "--images", help="New comma-separated list of image URLs"),
    aspects: Optional[str] = typer.Option(None, "--aspects", help="New item specifics as JSON object"),
    weight: Optional[float] = typer.Option(None, "--weight", "-w", help="Package weight in pounds"),
    length: Optional[float] = typer.Option(None, "--length", help="Package length in inches"),
    width: Optional[float] = typer.Option(None, "--width", help="Package width in inches"),
    height: Optional[float] = typer.Option(None, "--height", help="Package height in inches"),
    from_json: Optional[str] = typer.Option(None, "--from-json", help="Path to JSON file containing full inventory item payload"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
):
    """
    Update an existing inventory item.

    Fetches the current item and merges with provided updates.

    Examples:
        ebay inventory update SKU123 --quantity 20
        ebay inventory update SKU123 --title "Updated Title" --quantity 15
        ebay inventory update SKU123 --from-json updates.json
    """
    try:
        client = get_client()

        # Fetch current item
        print_info(f"Fetching inventory item '{sku}'...")
        current = client.get_inventory_item(sku)

        # Start with current item, then merge JSON file if provided
        payload = current.copy()
        # Remove read-only fields
        payload.pop("sku", None)
        payload.pop("locale", None)
        payload.pop("groupIds", None)
        payload.pop("inventoryItemGroupKeys", None)

        if from_json:
            with open(from_json, "r") as f:
                json_updates = json.load(f)
            # Deep merge: JSON updates override current values but preserve unspecified fields
            payload = _deep_merge(payload, json_updates)

        # Apply updates
        if "product" not in payload:
            payload["product"] = current.get("product", {})

        if title:
            payload["product"]["title"] = title
        if description:
            payload["product"]["description"] = description
        if image_urls:
            payload["product"]["imageUrls"] = [url.strip() for url in image_urls.split(",")]
        if aspects:
            payload["product"]["aspects"] = json.loads(aspects)
        if condition:
            payload["condition"] = condition
        if quantity is not None:
            if "availability" not in payload:
                payload["availability"] = {}
            if "shipToLocationAvailability" not in payload["availability"]:
                payload["availability"]["shipToLocationAvailability"] = {}
            payload["availability"]["shipToLocationAvailability"]["quantity"] = quantity

        # Update weight and dimensions
        if weight is not None or length is not None or width is not None or height is not None:
            if "packageWeightAndSize" not in payload:
                payload["packageWeightAndSize"] = {}

            if weight is not None:
                payload["packageWeightAndSize"]["weight"] = {
                    "value": weight,
                    "unit": "POUND"
                }

            if length is not None or width is not None or height is not None:
                if "dimensions" not in payload["packageWeightAndSize"]:
                    payload["packageWeightAndSize"]["dimensions"] = {}
                dims = payload["packageWeightAndSize"]["dimensions"]
                if length is not None:
                    dims["length"] = length
                if width is not None:
                    dims["width"] = width
                if height is not None:
                    dims["height"] = height
                dims["unit"] = "INCH"

        result = client.create_or_update_inventory_item(sku, payload)
        print_success(f"Inventory item '{sku}' updated successfully.")

        if table:
            product = payload.get("product", {})
            ship_avail = payload.get("availability", {}).get("shipToLocationAvailability", {})
            summary = [{
                "sku": sku,
                "title": product.get("title", ""),
                "condition": payload.get("condition", ""),
                "quantity": ship_avail.get("quantity", ""),
            }]
            print_table(
                summary,
                ["sku", "title", "condition", "quantity"],
                ["SKU", "Title", "Condition", "Qty"],
            )
        else:
            # Return the updated item for verification
            item = client.get_inventory_item(sku)
            print_json(item)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def inventory_delete(
    sku: str = typer.Argument(..., help="The SKU of the inventory item to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """
    Delete an inventory item.

    Note: You cannot delete an inventory item that has active offers.
    Delete or end the offers first.

    Examples:
        ebay inventory delete SKU123
        ebay inventory delete SKU123 --force
    """
    try:
        client = get_client()

        if not force:
            # Fetch item for confirmation
            item = client.get_inventory_item(sku)
            title = item.get("product", {}).get("title", sku)

            if not typer.confirm(f"Delete inventory item '{title}' (SKU: {sku})?"):
                print_info("Deletion cancelled.")
                raise typer.Exit(0)

        client.delete_inventory_item(sku)
        print_success(f"Inventory item '{sku}' deleted.")

    except Exception as e:
        raise typer.Exit(handle_error(e))
