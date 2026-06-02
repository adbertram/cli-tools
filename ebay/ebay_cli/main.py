"""Main entry point for eBay CLI."""
from types import SimpleNamespace
from typing import List, Optional

import typer
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .config import get_config

app = create_app(
    name="ebay",
    help="eBay CLI — seller tools, marketplace categories, and account management",
    version=__version__,
)

# Register command modules
from .commands import (
    auth,
    categories,
    images,
    inventory,
    listings,
    locations,
    messages,
    orders,
    payment_policies,
    policies,
    return_policies,
    search,
    seller,
    shipping,
    shipping_labels,
    store,
    templates,
)

# Admin/agnostic — top-level
app.add_typer(auth.app, name="auth", help="Manage eBay API authentication")
register_commands(app, get_config, categories, name="categories", help="Search and browse eBay marketplace categories")

# Marketplace commands — top-level (browser-based, searches all eBay listings)
register_commands(app, get_config, search, name="listings", help="Search eBay marketplace listings")

# Seller commands — grouped under "ebay seller"
seller_app = typer.Typer(
    name="seller",
    help="Seller tools — listings, orders, inventory, policies, and more",
)


@seller_app.command("list")
def seller_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of groups to return"),
    filters: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter (field:op:value)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List seller command groups."""
    from cli_tools_shared.output import print_json, print_table
    from cli_tools_shared.filters import apply_filters, apply_limit, apply_properties_filter

    groups = [
        {"name": "orders", "description": "Manage eBay seller orders"},
        {"name": "shipping-labels", "description": "Manage eBay shipping labels"},
        {"name": "shipping-quote", "description": "Manage eBay shipping quotes"},
        {"name": "inventory", "description": "Manage eBay inventory items"},
        {"name": "listings", "description": "Manage eBay listings"},
        {"name": "templates", "description": "Manage listing templates"},
        {"name": "policies", "description": "Manage fulfillment policies"},
        {"name": "payment-policies", "description": "Manage payment policies"},
        {"name": "return-policies", "description": "Manage return policies"},
        {"name": "images", "description": "Manage eBay images"},
        {"name": "locations", "description": "Manage merchant locations"},
        {"name": "messages", "description": "Manage seller messages"},
        {"name": "store", "description": "Manage eBay store"},
    ]
    groups = apply_filters(groups, filters)
    groups = apply_limit(groups, limit)
    groups = apply_properties_filter(groups, properties)
    if table:
        print_table(groups, ["name", "description"], ["Name", "Description"])
    else:
        print_json(groups)


@seller_app.command("get")
def seller_get(
    name: str = typer.Argument(..., help="Seller command group name"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get details for a seller command group."""
    from cli_tools_shared.output import print_error, print_json, print_table

    groups = {
        "orders": "Manage eBay seller orders",
        "shipping-labels": "Manage eBay shipping labels",
        "shipping-quote": "Manage eBay shipping quotes",
        "inventory": "Manage eBay inventory items",
        "listings": "Manage eBay listings",
        "templates": "Manage listing templates",
        "policies": "Manage fulfillment policies",
        "payment-policies": "Manage payment policies",
        "return-policies": "Manage return policies",
        "images": "Manage eBay images",
        "locations": "Manage merchant locations",
        "messages": "Manage seller messages",
        "store": "Manage eBay store",
    }
    if name not in groups:
        print_error(f"Unknown seller command group: {name}")
        raise typer.Exit(1)
    data = {"name": name, "description": groups[name]}
    if table:
        print_table([data], ["name", "description"], ["Name", "Description"])
    else:
        print_json(data)


register_commands(seller_app, get_config, orders, name="orders", help="Manage eBay seller orders")
register_commands(
    seller_app,
    get_config,
    SimpleNamespace(app=orders.shipping_label_app, COMMAND_CREDENTIALS=shipping_labels.COMMAND_CREDENTIALS),
    name="shipping-labels",
    help="Manage eBay shipping labels",
)
register_commands(
    seller_app,
    get_config,
    shipping,
    name="shipping-quote",
    help="Manage eBay shipping quotes",
)
register_commands(seller_app, get_config, inventory, name="inventory", help="Manage eBay inventory items")
register_commands(seller_app, get_config, listings, name="listings", help="Manage eBay listings (drafts and active)")
register_commands(seller_app, get_config, templates, name="templates", help="Manage listing templates")
register_commands(seller_app, get_config, policies, name="policies", help="Manage eBay fulfillment policies")
register_commands(
    seller_app,
    get_config,
    SimpleNamespace(app=policies.payment_app, COMMAND_CREDENTIALS=payment_policies.COMMAND_CREDENTIALS),
    name="payment-policies",
    help="Manage eBay payment policies",
)
register_commands(
    seller_app,
    get_config,
    SimpleNamespace(app=policies.return_app, COMMAND_CREDENTIALS=return_policies.COMMAND_CREDENTIALS),
    name="return-policies",
    help="Manage eBay return policies",
)
register_commands(seller_app, get_config, images, name="images", help="Manage eBay images")
register_commands(seller_app, get_config, locations, name="locations", help="Manage eBay merchant locations")
register_commands(seller_app, get_config, messages, name="messages", help="Manage eBay seller messages")
register_commands(seller_app, get_config, store, name="store", help="Manage eBay store")
register_commands(
    app,
    get_config,
    SimpleNamespace(app=seller_app, COMMAND_CREDENTIALS=seller.COMMAND_CREDENTIALS),
    name="seller",
    help="Seller tools — listings, orders, inventory, policies, and more",
)

app.add_typer(create_cache_app(get_config), name="cache")


@app.command()
def whoami(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="Profile name"),
):
    """
    Display current user details and scopes.
    """
    from .client import get_client
    from .config import Config
    from cli_tools_shared.output import print_json, print_table, handle_error

    try:
        client = get_client(profile=profile)
        user = client.get_user()

        # Add scopes to the output
        user["scopes"] = Config.OAUTH_SCOPES

        if table:
            # Flatten for table
            data = [{
                "username": user.get("username"),
                "account_type": user.get("accountType"),
                "registration_site": user.get("registrationMarketplaceId"),
                "scopes": str(len(user.get("scopes", []))) + " scopes"
            }]
            print_table(
                data,
                ["username", "account_type", "registration_site", "scopes"],
                ["Username", "Account Type", "Site", "Scopes"]
            )
            print("\nScopes:")
            for scope in user.get("scopes", []):
                print(f"  - {scope}")
        else:
            print_json(user)

    except Exception as e:
        raise typer.Exit(handle_error(e))


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
