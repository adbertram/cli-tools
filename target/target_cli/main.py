"""Main entry point for Target CLI."""

import re

import typer
from typing import List, Optional
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_error, print_info, print_json, print_table

from . import __version__
from . import session as session_store
from .client import ClientError, TargetClient, get_client
from .config import get_config

_CANCEL_REASON_HELP = "Cancellation reason. One of: " + " | ".join(TargetClient.CANCEL_REASONS)

from cli_tools_shared.auth_commands import create_auth_app

COLUMNS = ["id", "title", "price"]

app = create_app(name="target", help="CLI interface for Target", version=__version__)
products_app = typer.Typer(help="Products management", no_args_is_help=True)
cart_app = typer.Typer(help="Cart management", no_args_is_help=True)
store_app = typer.Typer(help="Store location management", no_args_is_help=True)
session_app = typer.Typer(help="Fast-search (redsky) session management", no_args_is_help=True)
payment_app = typer.Typer(
    help="Saved card pointers: name your Target wallet cards so checkout can select them",
    no_args_is_help=True,
)
pickup_app = typer.Typer(
    help="Default pickup contact (name + email) used by checkout for this profile",
    no_args_is_help=True,
)
orders_app = typer.Typer(help="Order history: find and cancel orders", no_args_is_help=True)
favorites_app = typer.Typer(help="Saved favorites (the heart): list items you saved", no_args_is_help=True)

FAVORITE_COLUMNS = [*COLUMNS, "available"]


def _property_fields(properties: Optional[str]) -> Optional[List[str]]:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def _validate(filters: Optional[List[str]]) -> None:
    if not filters:
        return
    try:
        validate_filters(filters)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


def _render(rows: List[dict], table: bool, properties: Optional[str], empty: str, columns: List[str]) -> None:
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info(empty)
        return
    columns = fields or columns
    print_table(rows, columns, [column.replace("_", " ").title() for column in columns])


PAYMENT_COLUMNS = ["name", "brand", "last4", "default", "cvv_stored", "in_wallet"]


def _pointer_row(pointer: dict, wallet_last4: set) -> dict:
    """Safe display shape for a card pointer, shared by 'payment-method' list/get.

    Emits only whether a CVV is stored (``cvv_stored``), NEVER the stored CVV
    itself, so neither list nor get can leak it in JSON or table output.
    """
    return {
        "name": pointer.get("name"),
        "brand": pointer.get("brand"),
        "last4": pointer.get("last4"),
        "default": pointer.get("default", False),
        "cvv_stored": bool(pointer.get("cvv")),
        "in_wallet": pointer.get("last4") in wallet_last4,
    }


@products_app.command("list")
@command
def products_list(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(24, "--limit", "-l", help="Maximum number of results"),
    store: Optional[str] = typer.Option(None, "--store", help="Store id (defaults to config STORE_ID)"),
    zip_code: Optional[str] = typer.Option(None, "--zip", help="Zip for geo context (defaults to config ZIP)"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Search for items on Target."""
    client = get_client()
    try:
        _validate(filter)
        rows = client.search(query, limit, store_id=store, zip_code=zip_code)
        if filter:
            rows = apply_filters(rows, filter)
        _render(rows, table, properties, "No results found.", COLUMNS)
    finally:
        client.close()


@products_app.command("get")
@command
def products_get(
    item_id: str = typer.Argument(..., help="Item TCIN"),
    store: Optional[str] = typer.Option(None, "--store", help="Store id (defaults to config STORE_ID)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get details for a specific item."""
    client = get_client()
    try:
        row = client.get_item(item_id, store_id=store)
        fields = _property_fields(properties)
        if fields:
            _render([row], table, properties, "No item found.", COLUMNS)
        elif table:
            print_table(
                [{"field": key, "value": str(value)} for key, value in row.items()],
                ["field", "value"],
                ["Field", "Value"],
            )
        else:
            print_json(row)
    finally:
        client.close()


@products_app.command("inventory")
@command
def products_inventory(
    item_id: str = typer.Argument(..., help="Item TCIN"),
    store: Optional[str] = typer.Option(None, "--store", help="Store id (defaults to config STORE_ID)"),
    zip_code: Optional[str] = typer.Option(None, "--zip", help="Zip for pickup stores (defaults to config ZIP)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Show pickup + shipping availability for an item."""
    client = get_client()
    try:
        data = client.get_inventory(item_id, store_id=store, zip_code=zip_code)
        if table:
            print_table(
                [{"store": p["store"], "pickup": p["pickup"], "qty": p["quantity"]} for p in data["pickup"]],
                ["store", "pickup", "qty"],
                ["Store", "Pickup", "Qty"],
            )
        else:
            print_json(data)
    finally:
        client.close()


@cart_app.command("list")
@command
def cart_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """View current cart contents."""
    client = get_client()
    try:
        cart = client.get_cart()
        if table:
            _render(cart["items"], True, properties, "Cart is empty.", ["title"])
            print_info(f"Total: {cart['total']}")
        else:
            print_json(cart)
    finally:
        client.close()


@cart_app.command("add")
@command
def cart_add(
    item_id: str = typer.Argument(..., help="Item TCIN"),
    method: str = typer.Option("pickup", "--method", "-m", help="Fulfillment: pickup, shipping, or delivery"),
):
    """Add an item to the cart (defaults to store pickup)."""
    client = get_client()
    try:
        client.add_to_cart(item_id, method=method)
        print_info(f"Added {item_id} to cart ({method}).")
    finally:
        client.close()


@cart_app.command("remove")
@command
def cart_remove(item_id: str = typer.Argument(..., help="Item TCIN")):
    """Remove an item from the cart."""
    client = get_client()
    try:
        client.remove_from_cart(item_id)
        print_info(f"Removed {item_id} from cart.")
    finally:
        client.close()


@cart_app.command("clear")
@command
def cart_clear(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Empty the cart by removing every item in it (no-op if already empty)."""
    from cli_tools_shared.output import confirm_destructive_action
    confirm_destructive_action(
        "Clear the cart? This removes every item currently in it.",
        assume_yes=yes,
        action_description="clear the cart",
        skip_flag_hint="--yes",
    )
    client = get_client()
    try:
        removed = client.clear_cart()
        print_info(f"Cleared the cart ({removed} item(s) removed).")
    finally:
        client.close()


@cart_app.command("checkout")
@command
def cart_checkout(
    yes: bool = typer.Option(False, "--yes", "-y", help="Actually place the order (spends money). Omit for a dry run."),
    card: Optional[str] = typer.Option(None, "--card", help="Name of a saved card pointer ('payment-method add') to charge; defaults to the default pointer"),
    pickup_email: Optional[str] = typer.Option(None, "--pickup-email", help="Pickup contact email (required the first time an account places a pickup order)"),
    pickup_name: Optional[str] = typer.Option(None, "--pickup-name", help="Pickup person name 'First Last' (defaults to the account holder Target prefills)"),
):
    """Review checkout (dry run) or place the order with --yes.

    Fulfillment (pickup/shipping) is chosen per item at 'cart add --method'.
    --card selects a saved card pointer at checkout; if it needs a CVV you're
    prompted securely at that moment (or it uses a stored CVV). Pickup contact
    falls back to the profile default ('pickup set') when the flags are omitted.
    """
    client = get_client()
    try:
        result = client.checkout(
            place_order=yes,
            card=card,
            pickup_email=pickup_email,
            pickup_name=pickup_name,
        )
        print_json(result)
        if result.get("placed"):
            print_info(f"Order placed. Confirmation: {result.get('order_number') or 'see cart'}.")
        else:
            print_info("Dry run complete -- no order placed. Add --yes to buy.")
    finally:
        client.close()


@store_app.command("list")
@command
def store_list(
    zip_code: str = typer.Argument(..., help="Zip code to search near"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """List Target stores near a zip code."""
    client = get_client()
    try:
        rows = client.find_stores(zip_code)
        _render(rows, table, None, "No stores found.", ["id", "name", "distance", "status"])
    finally:
        client.close()


@store_app.command("get")
@command
def store_get(
    store_id: str = typer.Argument(..., help="Store id"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get a single Target store by id."""
    client = get_client()
    try:
        store = client.get_store(store_id)
        if table:
            print_table(
                [{"field": key, "value": str(value)} for key, value in store.items()],
                ["field", "value"],
                ["Field", "Value"],
            )
        else:
            print_json(store)
    finally:
        client.close()


@payment_app.command("add")
@command
def payment_method_add(
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Friendly name for this card pointer (e.g. amex-personal)"),
    last4: Optional[str] = typer.Option(None, "--last4", help="Point at a card ALREADY in your Target wallet by its last 4 digits (skips the add-card page)"),
    no_default: bool = typer.Option(False, "--no-default", help="Do not mark this pointer as the default"),
):
    """Save a selectable pointer to a Target wallet card.

    Default: opens Target's add-card page (headed) so you enter and save a NEW
    card yourself; the CLI captures only a pointer (name + last4 + brand), never
    the card number or CVV. With --last4, points at a card already in your wallet
    without opening the page. Then 'cart checkout --card <name>' selects it.
    """
    from cli_tools_shared.output import prompt_text
    from . import cards as card_store
    config = get_config()
    resolved = name if name is not None else prompt_text("Name this card pointer (e.g. amex-personal)")
    slug = card_store.normalize_name(resolved)
    if not slug:
        print_error("Card pointer name must contain letters or digits.")
        raise typer.Exit(1)
    if card_store.get_pointer(config, slug) is not None:
        print_error(f"A card pointer named '{slug}' already exists. Pick another name or remove it first.")
        raise typer.Exit(1)
    client = get_client()
    try:
        if last4 is not None:
            digits = re.sub(r"\D", "", last4)
            if len(digits) != 4:
                print_error(f"--last4 must be 4 digits (got '{last4}').")
                raise typer.Exit(1)
            match = next((c for c in client.list_payments() if c.get("last4") == digits), None)
            if match is None:
                print_error(
                    f"No card ending {digits} is saved in your Target wallet. Add it there first, "
                    "or run 'payment-method add' without --last4 to add a new card."
                )
                raise typer.Exit(1)
            captured = {"last4": digits, "brand": match.get("brand")}
        else:
            captured = client.capture_new_card()
        # Optionally store the CVV (hidden) so checkout is one-shot. Only prompt
        # in an interactive terminal; skip silently when non-interactive.
        from cli_tools_shared.output import _stdin_is_interactive_tty, prompt_secret
        cvv = None
        if _stdin_is_interactive_tty():
            entered = prompt_secret(
                "Card security code (CVV) to store for one-shot checkout [Enter to skip]",
                allow_empty=True,
            )
            cvv = entered or None
        pointer = card_store.add_pointer(
            config, slug, captured["last4"], captured.get("brand"),
            default=not no_default, cvv=cvv,
        )
        print_info(
            f"Saved card pointer '{pointer['name']}' -> {pointer.get('brand') or 'card'} "
            f"ending {pointer['last4']}{' (default)' if pointer['default'] else ''}"
            f"{', CVV stored' if pointer.get('cvv') else ''}."
        )
    finally:
        client.close()


@payment_app.command("set-cvv")
@command
def payment_method_set_cvv(
    name: str = typer.Argument(..., help="Card pointer name to store a CVV for"),
):
    """Store the CVV for a saved card pointer (hidden prompt) for one-shot checkout."""
    from cli_tools_shared.output import prompt_secret
    from . import cards as card_store
    config = get_config()
    slug = card_store.normalize_name(name)
    if card_store.get_pointer(config, slug) is None:
        print_error(f"No card pointer named '{slug}'.")
        raise typer.Exit(1)
    cvv = prompt_secret("Card security code (CVV)")
    card_store.set_cvv(config, slug, cvv)
    print_info(f"Stored CVV for card pointer '{slug}'.")


@payment_app.command("list")
@command
def payment_method_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """List saved card pointers for the active profile (cross-checked against the live wallet)."""
    from . import cards as card_store
    config = get_config()
    pointers = card_store.load_pointers(config)
    client = get_client()
    try:
        wallet = client.list_payments()
    finally:
        client.close()
    wallet_last4 = {c["last4"] for c in wallet if c.get("last4")}
    # Rows are built via _pointer_row, which never emits the stored CVV (only
    # whether one is stored), so `list` can't leak it in JSON or table output.
    rows = [_pointer_row(p, wallet_last4) for p in pointers]
    _render(
        rows, table, None,
        "No saved card pointers. Add one with 'payment-method add'.",
        PAYMENT_COLUMNS,
    )
    pointer_last4 = {p["last4"] for p in pointers}
    orphans = [c for c in wallet if c.get("last4") and c["last4"] not in pointer_last4]
    if orphans:
        print_info(f"{len(orphans)} Target wallet card(s) have no pointer; run 'payment-method add' to name one.")


@payment_app.command("get")
@command
def payment_method_get(
    identifier: str = typer.Argument(..., help="Card pointer name, or the card's last 4 digits"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get one saved card pointer by name or last4 (never prints the stored CVV).

    Cross-checks the pointer against the live Target wallet (like 'list') so
    'in_wallet' tells you whether it still points at a real saved card.
    """
    from . import cards as card_store
    config = get_config()
    pointer = card_store.find_pointer(config, identifier)
    if pointer is None:
        print_error(
            f"No saved card pointer matching '{identifier}'. "
            "List them with 'payment-method list'."
        )
        raise typer.Exit(1)
    client = get_client()
    try:
        wallet = client.list_payments()
    finally:
        client.close()
    wallet_last4 = {c["last4"] for c in wallet if c.get("last4")}
    row = _pointer_row(pointer, wallet_last4)
    if table:
        print_table(
            [{"field": key, "value": str(value)} for key, value in row.items()],
            ["field", "value"],
            ["Field", "Value"],
        )
    else:
        print_json(row)


@payment_app.command("remove")
@command
def payment_method_remove(
    name: str = typer.Argument(..., help="Card pointer name to remove"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Remove a saved card pointer (does NOT touch your Target wallet)."""
    from cli_tools_shared.output import confirm_destructive_action
    from . import cards as card_store
    config = get_config()
    slug = card_store.normalize_name(name)
    if card_store.get_pointer(config, slug) is None:
        print_error(f"No card pointer named '{slug}'.")
        raise typer.Exit(1)
    confirm_destructive_action(
        f"Remove card pointer '{slug}'? This only deletes the pointer, not the card in Target.",
        assume_yes=yes,
        action_description=f"remove card pointer '{slug}'",
        skip_flag_hint="--yes",
    )
    card_store.remove_pointer(config, slug)
    print_info(f"Removed card pointer '{slug}'.")


@payment_app.command("set-default")
@command
def payment_method_set_default(
    name: str = typer.Argument(..., help="Card pointer name to make the default"),
):
    """Mark a card pointer as the default used when 'cart checkout' gets no --card."""
    from . import cards as card_store
    config = get_config()
    slug = card_store.normalize_name(name)
    if card_store.get_pointer(config, slug) is None:
        print_error(f"No card pointer named '{slug}'.")
        raise typer.Exit(1)
    card_store.set_default(config, slug)
    print_info(f"'{slug}' is now the default card pointer.")


@pickup_app.command("set")
@command
def pickup_set(
    email: Optional[str] = typer.Option(None, "--email", "-e", help="Default pickup contact email"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Default pickup person name 'First Last'"),
):
    """Store the default pickup email and/or name for this profile.

    'cart checkout' uses these when --pickup-email / --pickup-name are not passed.
    """
    from . import prefs
    if email is None and name is None:
        print_error("Provide --email and/or --name.")
        raise typer.Exit(1)
    contact = prefs.set_pickup_contact(get_config(), email=email, name=name)
    print_info(f"Default pickup contact: {contact.get('name') or '(no name)'} <{contact.get('email') or 'no email'}>.")


@pickup_app.command("show")
@command
def pickup_show(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Show this profile's stored default pickup contact."""
    from . import prefs
    contact = prefs.get_pickup_contact(get_config())
    if table:
        print_table(
            [{"field": "email", "value": contact.get("email") or ""},
             {"field": "name", "value": contact.get("name") or ""}],
            ["field", "value"], ["Field", "Value"],
        )
    else:
        print_json(contact)


@pickup_app.command("clear")
@command
def pickup_clear():
    """Remove this profile's stored default pickup contact."""
    from . import prefs
    prefs.clear_pickup_contact(get_config())
    print_info("Cleared the default pickup contact.")


@orders_app.command("list")
@command
def orders_list(
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum number of orders"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """List recent orders (find an order number to cancel)."""
    client = get_client()
    try:
        rows = client.list_orders(limit=limit)
        _render(rows, table, None, "No orders found.", ["order_number", "status", "total"])
    finally:
        client.close()


@orders_app.command("get")
@command
def orders_get(
    order_number: str = typer.Argument(..., help="Order number to look up (see 'orders list')"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get one order's status and total by order number."""
    client = get_client()
    try:
        order = client.get_order(order_number)
        if table:
            print_table(
                [{"field": key, "value": str(value)} for key, value in order.items()],
                ["field", "value"],
                ["Field", "Value"],
            )
        else:
            print_json(order)
    finally:
        client.close()


@orders_app.command("cancel")
@command
def orders_cancel(
    order_number: str = typer.Argument(..., help="Order number to cancel (see 'orders list')"),
    cancel_reason: str = typer.Option("No longer want the item", "--cancel-reason", "-r", help=_CANCEL_REASON_HELP),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Cancel all items of an order (only works while it's still cancellable).

    --cancel-reason must match one of Target's reasons (a unique partial is fine):
    Chose wrong store | Used wrong payment method | Ordered it somewhere else |
    Needed it sooner | Ordered wrong item | Purchased it at another Target store |
    Wanted the item shipped | No longer want the item | Couldn't pick up in time |
    Store requested I cancel it | Other - Please describe
    """
    from cli_tools_shared.output import confirm_destructive_action
    reason = TargetClient.resolve_reason(cancel_reason)
    if reason is None:
        print_error(
            f"Unknown --cancel-reason '{cancel_reason}'. Choose one of:\n  - "
            + "\n  - ".join(TargetClient.CANCEL_REASONS)
        )
        raise typer.Exit(1)
    confirm_destructive_action(
        f"Cancel order {order_number} (reason: {reason})? This cancels all items in the order.",
        assume_yes=yes,
        action_description=f"cancel order {order_number}",
        skip_flag_hint="--yes",
    )
    client = get_client()
    try:
        result = client.cancel_order(order_number, reason)
        print_info(
            f"Cancelled order {order_number} ({result.get('items_cancelled')} item(s), "
            f"reason: {result.get('reason')})."
        )
    finally:
        client.close()


@session_app.command("refresh")
@command
def session_refresh():
    """Re-capture the fast-search (redsky) session via a headed browser."""
    client = get_client()
    try:
        count = client.refresh_session()
        print_info(f"Fast-search session refreshed ({count} results verified).")
    finally:
        client.close()


@session_app.command("status")
@command
def session_status():
    """Show the cached fast-search (redsky) session state."""
    session = session_store.load_session(get_config())
    if session is None:
        print_json({"captured": False, "hint": "Run `target auth login` or `target session refresh`."})
        return
    print_json({
        "captured": True,
        "age_hours": round(session.age_seconds / 3600, 2),
        "expired": session.expired,
        "store_id": session.store_id,
        "zip": session.zip,
    })


@favorites_app.command("list")
@command
def favorites_list(
    limit: int = typer.Option(24, "--limit", "-l", help="Maximum number of favorites"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List the items you saved to your Target favorites (the heart)."""
    client = get_client()
    try:
        _validate(filter)
        rows = client.list_favorites(limit=limit)
        if filter:
            rows = apply_filters(rows, filter)
        _render(rows, table, properties, "No favorites found.", FAVORITE_COLUMNS)
    finally:
        client.close()


@favorites_app.command("get")
@command
def favorites_get(
    item_id: str = typer.Argument(..., help="Item TCIN to look up in your favorites"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one saved favorite by TCIN (errors if it isn't one of your favorites)."""
    client = get_client()
    try:
        row = client.get_favorite(item_id)
        fields = _property_fields(properties)
        if fields:
            _render([row], table, properties, "No favorite found.", FAVORITE_COLUMNS)
        elif table:
            print_table(
                [{"field": key, "value": str(value)} for key, value in row.items()],
                ["field", "value"],
                ["Field", "Value"],
            )
        else:
            print_json(row)
    finally:
        client.close()


@favorites_app.command("remove")
@command
def favorites_remove(
    item_id: str = typer.Argument(..., help="Item TCIN to remove from your favorites"),
):
    """Remove an item from your Target favorites by TCIN (errors if not favorited)."""
    client = get_client()
    try:
        result = client.remove_favorite(item_id)
        print_json(result)
        print_info(f"Removed {item_id} from favorites ({result['remaining']} remaining).")
    finally:
        client.close()


app.add_typer(products_app, name="products")
app.add_typer(cart_app, name="cart")
app.add_typer(store_app, name="store")
app.add_typer(session_app, name="session")
app.add_typer(payment_app, name="payment-method")
app.add_typer(pickup_app, name="pickup")
app.add_typer(orders_app, name="orders")
app.add_typer(favorites_app, name="favorites")
app.add_typer(create_auth_app(get_config, tool_name="target"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    try:
        run_app(app)
    except ClientError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


if __name__ == "__main__":
    main()
