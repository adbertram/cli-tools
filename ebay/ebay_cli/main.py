"""Main entry point for eBay CLI."""
from cli_tools_shared.output import command
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

SELLER_GROUPS = (
    ("orders", "Manage eBay seller orders", orders),
    (
        "shipping-labels",
        "Manage eBay shipping labels",
        SimpleNamespace(app=orders.shipping_label_app, COMMAND_CREDENTIALS=shipping_labels.COMMAND_CREDENTIALS),
    ),
    ("shipping-quote", "Manage eBay shipping quotes", shipping),
    ("inventory", "Manage eBay inventory items", inventory),
    ("listings", "Manage eBay listings (drafts and active)", listings),
    ("templates", "Manage listing templates", templates),
    ("policies", "Manage eBay fulfillment policies", policies),
    (
        "payment-policies",
        "Manage eBay payment policies",
        SimpleNamespace(app=policies.payment_app, COMMAND_CREDENTIALS=payment_policies.COMMAND_CREDENTIALS),
    ),
    (
        "return-policies",
        "Manage eBay return policies",
        SimpleNamespace(app=policies.return_app, COMMAND_CREDENTIALS=return_policies.COMMAND_CREDENTIALS),
    ),
    ("images", "Manage eBay images", images),
    ("locations", "Manage eBay merchant locations", locations),
    ("messages", "Manage eBay seller messages", messages),
    ("store", "Manage eBay store", store),
)


@seller_app.command("list")
@command
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
        {"name": name, "description": description}
        for name, description, _module in SELLER_GROUPS
    ]
    groups = apply_filters(groups, filters)
    groups = apply_limit(groups, limit)
    groups = apply_properties_filter(groups, properties)
    if table:
        print_table(groups, ["name", "description"], ["Name", "Description"])
    else:
        print_json(groups)


@seller_app.command("get")
@command
def seller_get(
    name: str = typer.Argument(..., help="Seller command group name"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get details for a seller command group."""
    from cli_tools_shared.output import print_error, print_json, print_table

    groups = {group_name: description for group_name, description, _module in SELLER_GROUPS}
    if name not in groups:
        print_error(f"Unknown seller command group: {name}")
        raise typer.Exit(1)
    data = {"name": name, "description": groups[name]}
    if table:
        print_table([data], ["name", "description"], ["Name", "Description"])
    else:
        print_json(data)


for group_name, description, module in SELLER_GROUPS:
    register_commands(seller_app, get_config, module, name=group_name, help=description)
register_commands(
    app,
    get_config,
    SimpleNamespace(app=seller_app, COMMAND_CREDENTIALS=seller.COMMAND_CREDENTIALS),
    name="seller",
    help="Seller tools — listings, orders, inventory, policies, and more",
)

app.add_typer(create_cache_app(get_config), name="cache")


@app.command()
@command
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
