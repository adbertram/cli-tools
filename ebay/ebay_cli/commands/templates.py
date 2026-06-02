"""Templates commands for eBay CLI.

Manage local listing templates that can be used to create draft offers.
Templates are stored in ~/.ebay/templates.json
"""
COMMAND_CREDENTIALS = {
    "list": ["oauth_authorization_code"],
    "get": ["oauth_authorization_code"],
    "create": ["oauth_authorization_code"],
    "update": ["oauth_authorization_code"],
    "delete": ["oauth_authorization_code"],
    "validate": ["oauth_authorization_code"],
}

import json
import typer
from pathlib import Path
from typing import Optional, List

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error, print_success, print_info, print_warning, print_error
from ..storage import TemplateStorage
from ..template_validation import TemplateValidationError
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
from ..parsers import format_local_time, format_date
from ..properties import (
    add_template_property_aliases,
    validate_and_filter_properties,
    PropertyValidationError,
)

app = typer.Typer(help="Manage listing templates")


def _template_record(template: dict) -> dict:
    """Expose canonical list properties for stored template records."""
    return {
        **template,
        "id": template.get("name"),
    }


@app.command("list")
def templates_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of templates to return"),
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
    List all saved templates.

    Examples:
        ebay templates list
        ebay templates list --table
        ebay templates list --filter "name:ilike:%lego%"
        ebay templates list --properties "name,description"
    """
    try:
        storage = TemplateStorage()
        templates = storage.get_all_templates()

        if not templates:
            if table:
                print_table([], ["name", "description", "category", "price", "updated"], ["Name", "Description", "Category", "Price", "Updated"])
            else:
                print_json([])
            return

        # Validate and apply client-side filters if provided
        if filters:
            try:
                validated_filters = validate_filters(filters)
                templates = apply_filters(templates, validated_filters)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        templates = [_template_record(template) for template in templates]

        # Apply properties filtering
        if properties:
            try:
                templates = validate_and_filter_properties(
                    add_template_property_aliases(templates),
                    properties,
                )
            except PropertyValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply limit
        templates = templates[:limit]

        if table:
            rows = []
            for t in templates:
                tmpl = t.get("template", {})
                price_info = tmpl.get("pricingSummary", {}).get("price", {})
                price = f"{price_info.get('value', '')} {price_info.get('currency', 'USD')}" if price_info.get('value') else ""
                rows.append({
                    "name": t.get("name", ""),
                    "description": t.get("description", "")[:30] + ("..." if len(t.get("description", "")) > 30 else ""),
                    "category": tmpl.get("categoryId", ""),
                    "price": price,
                    "updated": format_date(t.get("updated_at", "")),
                })
            print_table(
                rows,
                ["name", "description", "category", "price", "updated"],
                ["Name", "Description", "Category", "Price", "Updated"],
            )
        else:
            print_json(templates)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def templates_get(
    name: str = typer.Argument(..., help="Template name"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get a specific template by name.

    Examples:
        ebay templates get vintage-camera
        ebay templates get vintage-camera --table
    """
    try:
        storage = TemplateStorage()
        template = storage.get_template(name)

        if not template:
            print_error(f"Template '{name}' not found.")
            raise typer.Exit(1)

        if table:
            tmpl = template.get("template", {})
            price_info = tmpl.get("pricingSummary", {}).get("price", {})
            policies = tmpl.get("listingPolicies", {})

            print(f"\nTemplate: {template.get('name')}")
            print(f"Description: {template.get('description', 'None')}")
            print(f"Created: {format_local_time(template.get('created_at', ''))}")
            print(f"Updated: {format_local_time(template.get('updated_at', ''))}")
            print("\nListing Settings:")
            print(f"  Category ID: {tmpl.get('categoryId', 'Not set')}")
            print(f"  Marketplace: {tmpl.get('marketplaceId', 'EBAY_US')}")
            print(f"  Format: {tmpl.get('format', 'FIXED_PRICE')}")
            if price_info:
                print(f"  Price: {price_info.get('value', '')} {price_info.get('currency', 'USD')}")
            if tmpl.get('availableQuantity'):
                print(f"  Quantity: {tmpl.get('availableQuantity')}")
            if policies:
                print("\nPolicies:")
                print(f"  Fulfillment: {policies.get('fulfillmentPolicyId', 'Not set')}")
                print(f"  Payment: {policies.get('paymentPolicyId', 'Not set')}")
                print(f"  Return: {policies.get('returnPolicyId', 'Not set')}")
        else:
            print_json(template)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def templates_create(
    name: str = typer.Argument(..., help="Template name (e.g., 'vintage-camera', 'standard-book')"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Template description"),
    from_offer: Optional[str] = typer.Option(None, "--from-offer", help="Create template from existing offer ID"),
    from_json: Optional[str] = typer.Option(None, "--from-json", help="Create template from JSON file"),
    marketplace: str = typer.Option("EBAY_US", "--marketplace", "-m", help="Marketplace ID"),
    format_type: str = typer.Option("FIXED_PRICE", "--format", "-f", help="Listing format"),
    category_id: Optional[str] = typer.Option(None, "--category", "-c", help="eBay category ID"),
    price: Optional[str] = typer.Option(None, "--price", "-p", help="Listing price"),
    currency: str = typer.Option("USD", "--currency", help="Currency code"),
    quantity: Optional[int] = typer.Option(None, "--quantity", "-q", help="Available quantity"),
    listing_description: Optional[str] = typer.Option(None, "--listing-description", help="Listing description text"),
    fulfillment_policy_id: Optional[str] = typer.Option(None, "--fulfillment-policy", help="Fulfillment policy ID"),
    payment_policy_id: Optional[str] = typer.Option(None, "--payment-policy", help="Payment policy ID"),
    return_policy_id: Optional[str] = typer.Option(None, "--return-policy", help="Return policy ID"),
    location_key: Optional[str] = typer.Option(None, "--location", help="Merchant location key"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing template"),
):
    """
    Create a listing template.

    Templates can be created from:
    - CLI options (--category, --price, etc.)
    - An existing eBay offer (--from-offer)
    - A JSON file (--from-json)

    Examples:
        ebay templates create vintage-camera --category 625 --price 99.99
        ebay templates create standard-book --from-offer 1234567890
        ebay templates create electronics --from-json template.json
    """
    try:
        storage = TemplateStorage()

        # Check if template exists
        if storage.template_exists(name) and not force:
            print_error(f"Template '{name}' already exists. Use --force to overwrite.")
            raise typer.Exit(1)

        template = {}

        # Option 1: From existing offer
        if from_offer:
            print_info(f"Fetching offer {from_offer}...")
            client = get_client()
            offer = client.get_offer(from_offer)

            # Extract template-relevant fields (exclude offer-specific fields)
            for field in ["marketplaceId", "format", "categoryId", "pricingSummary",
                          "listingPolicies", "listingDescription", "merchantLocationKey",
                          "availableQuantity"]:
                if field in offer:
                    template[field] = offer[field]

            print_success(f"Created template from offer {from_offer}")

        # Option 2: From JSON file (as base defaults)
        elif from_json:
            with open(from_json, "r") as f:
                loaded = json.load(f)
            # Handle full template record (with name/description/template keys)
            # or raw template content
            if "template" in loaded and isinstance(loaded["template"], dict):
                template = loaded["template"]
                if not description and loaded.get("description"):
                    description = loaded.get("description")
            else:
                template = loaded
            print_success(f"Loaded template from {from_json}")

        # Apply CLI options (override defaults from JSON or offer, or set from scratch)
        # These always apply - CLI params override template defaults
        if marketplace != "EBAY_US" or "marketplaceId" not in template:
            template["marketplaceId"] = marketplace
        if format_type != "FIXED_PRICE":
            template["format"] = format_type

        if category_id:
            template["categoryId"] = category_id

        if price:
            template["pricingSummary"] = {
                "price": {
                    "value": price,
                    "currency": currency,
                }
            }

        if quantity is not None:
            template["availableQuantity"] = quantity

        if listing_description:
            template["listingDescription"] = listing_description

        if fulfillment_policy_id or payment_policy_id or return_policy_id:
            if "listingPolicies" not in template:
                template["listingPolicies"] = {}
            if fulfillment_policy_id:
                template["listingPolicies"]["fulfillmentPolicyId"] = fulfillment_policy_id
            if payment_policy_id:
                template["listingPolicies"]["paymentPolicyId"] = payment_policy_id
            if return_policy_id:
                template["listingPolicies"]["returnPolicyId"] = return_policy_id

        if location_key:
            template["merchantLocationKey"] = location_key

        # Save template (validates against schema)
        try:
            record = storage.add_template(name, template, description)
            print_success(f"Template '{name}' saved.")
            print_info("Use 'ebay templates apply <name> --sku <SKU>' to create a draft offer.")
        except TemplateValidationError as e:
            print_error("Template validation failed:")
            for error in e.errors:
                print_error(f"  - {error}")
            raise typer.Exit(1)

    except TemplateValidationError:
        raise  # Already handled above
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def templates_update(
    name: str = typer.Argument(..., help="Template name to update"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Update description"),
    category_id: Optional[str] = typer.Option(None, "--category", "-c", help="eBay category ID"),
    price: Optional[str] = typer.Option(None, "--price", "-p", help="Listing price"),
    currency: Optional[str] = typer.Option(None, "--currency", help="Currency code"),
    quantity: Optional[int] = typer.Option(None, "--quantity", "-q", help="Available quantity"),
    listing_description: Optional[str] = typer.Option(None, "--listing-description", help="Listing description"),
    fulfillment_policy_id: Optional[str] = typer.Option(None, "--fulfillment-policy", help="Fulfillment policy ID"),
    payment_policy_id: Optional[str] = typer.Option(None, "--payment-policy", help="Payment policy ID"),
    return_policy_id: Optional[str] = typer.Option(None, "--return-policy", help="Return policy ID"),
    location_key: Optional[str] = typer.Option(None, "--location", help="Merchant location key"),
):
    """
    Update an existing template.

    Examples:
        ebay templates update vintage-camera --price 129.99
        ebay templates update standard-book --category 267
    """
    try:
        storage = TemplateStorage()
        existing = storage.get_template(name)

        if not existing:
            print_error(f"Template '{name}' not found.")
            raise typer.Exit(1)

        template = existing.get("template", {})
        new_description = description if description is not None else existing.get("description", "")

        # Apply updates
        if category_id:
            template["categoryId"] = category_id

        if price or currency:
            if "pricingSummary" not in template:
                template["pricingSummary"] = {"price": {}}
            if "price" not in template["pricingSummary"]:
                template["pricingSummary"]["price"] = {}
            if price:
                template["pricingSummary"]["price"]["value"] = price
            if currency:
                template["pricingSummary"]["price"]["currency"] = currency

        if quantity is not None:
            template["availableQuantity"] = quantity

        if listing_description:
            template["listingDescription"] = listing_description

        if fulfillment_policy_id or payment_policy_id or return_policy_id:
            # Update both listingPolicies (eBay API format) and policies (template format)
            # to ensure compatibility with different template structures
            if "listingPolicies" not in template:
                template["listingPolicies"] = {}
            if "policies" not in template:
                template["policies"] = {}
            if fulfillment_policy_id:
                template["listingPolicies"]["fulfillmentPolicyId"] = fulfillment_policy_id
                template["policies"]["fulfillmentPolicyId"] = fulfillment_policy_id
            if payment_policy_id:
                template["listingPolicies"]["paymentPolicyId"] = payment_policy_id
                template["policies"]["paymentPolicyId"] = payment_policy_id
            if return_policy_id:
                template["listingPolicies"]["returnPolicyId"] = return_policy_id
                template["policies"]["returnPolicyId"] = return_policy_id

        if location_key:
            template["merchantLocationKey"] = location_key

        # Save updated template (validates against schema)
        try:
            storage.add_template(name, template, new_description)
            print_success(f"Template '{name}' updated.")
        except TemplateValidationError as e:
            print_error("Template validation failed:")
            for error in e.errors:
                print_error(f"  - {error}")
            raise typer.Exit(1)

    except TemplateValidationError:
        raise  # Already handled above
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def templates_delete(
    name: str = typer.Argument(..., help="Template name to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """
    Delete a template.

    Examples:
        ebay templates delete old-template
        ebay templates delete old-template --force
    """
    try:
        storage = TemplateStorage()

        if not storage.template_exists(name):
            print_error(f"Template '{name}' not found.")
            raise typer.Exit(1)

        if not force:
            if not typer.confirm(f"Delete template '{name}'?"):
                print_info("Deletion cancelled.")
                raise typer.Exit(0)

        storage.delete_template(name)
        print_success(f"Template '{name}' deleted.")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("validate")
def templates_validate(
    file_path: str = typer.Argument(..., help="Path to JSON template file to validate"),
):
    """
    Validate a template JSON file against the schema.

    Checks that the template file is valid JSON and conforms to the
    template schema before importing.

    Examples:
        ebay templates validate ./my-template.json
        ebay templates validate ~/templates/lego-bulk.json
    """
    from ..template_validation import validate_template

    try:
        path = Path(file_path)
        if not path.exists():
            print_error(f"File not found: {file_path}")
            raise typer.Exit(1)

        # Load and parse JSON
        try:
            template_record = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            print_error(f"Invalid JSON: {e}")
            raise typer.Exit(1)

        # Validate against schema
        is_valid, errors = validate_template(template_record)

        if is_valid:
            print_success(f"Template '{template_record.get('name', 'unknown')}' is valid.")
            print_info("Use 'ebay templates create <name> --from-json <file>' to import.")
        else:
            print_error("Template validation failed:")
            for error in errors:
                print_error(f"  - {error}")
            raise typer.Exit(1)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))
