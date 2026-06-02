"""Coupon commands for Brickowl CLI.

Browser automation for managing store coupons on Brick Owl.
"""
COMMAND_CREDENTIALS = {
    "list": ["browser_session"],
    "get": ["browser_session"],
    "create-user": ["browser_session"],
    "create-code": ["browser_session"],
    "delete": ["browser_session"],
}

import typer
from typing import Optional, List

from cli_tools_shared.output import print_error, print_json, print_success, print_table
from cli_tools_shared.filters import apply_filters, apply_properties_filter, apply_limit

app = typer.Typer(help="Manage Brick Owl coupons", no_args_is_help=True)


@app.command("list")
def coupon_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of coupons to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List store coupons.

    Examples:
        brickowl coupon list
        brickowl coupon list --table
    """
    from ..browser import get_browser

    browser = get_browser()
    try:
        data = browser.list_coupons()
        data = apply_filters(data, filter)
        data = apply_properties_filter(data, properties)
        data = apply_limit(data, limit)
        if table:
            print_table(
                data,
                ["coupon_id", "code", "recipient", "note", "redemptions", "status"],
                ["ID", "Code", "Recipient", "Note", "Redemptions", "Status"],
            )
        else:
            print_json(data)
    except RuntimeError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Failed to list coupons: {e}")
        raise typer.Exit(1)
    finally:
        browser.close()


@app.command("get")
def coupon_get(
    coupon_id: str = typer.Argument(..., help="The coupon ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a specific coupon.

    Examples:
        brickowl coupon get COUPON_ID
        brickowl coupon get COUPON_ID --table
    """
    from ..browser import get_browser

    browser = get_browser()
    try:
        data = browser.list_coupons()
        match = None
        for coupon in data:
            if coupon.get("coupon_id") == coupon_id:
                match = coupon
                break
        if not match:
            print_error(f"Coupon not found: {coupon_id}")
            raise typer.Exit(1)
        if table:
            print_table(
                match,
                ["coupon_id", "code", "recipient", "note", "redemptions", "status"],
                ["ID", "Code", "Recipient", "Note", "Redemptions", "Status"],
            )
        else:
            print_json(match)
    except RuntimeError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Failed to get coupon: {e}")
        raise typer.Exit(1)
    finally:
        browser.close()


@app.command("create-user")
def coupon_create_user(
    username: str = typer.Argument(..., help="Username to create coupon for"),
    discount: float = typer.Argument(..., help="Discount percentage"),
    min_order: Optional[float] = typer.Option(None, "--min-order", help="Minimum order amount"),
    max_discount: Optional[float] = typer.Option(None, "--max-discount", help="Maximum discount amount"),
    free_shipping: bool = typer.Option(False, "--free-shipping", help="Include free shipping"),
    note: Optional[str] = typer.Option(None, "--note", "-n", help="Coupon note"),
):
    """
    Create a coupon for a specific user.

    Examples:
        brickowl coupon create-user buyer123 10
        brickowl coupon create-user buyer123 15 --min-order 25.00 --free-shipping
    """
    from ..browser import get_browser

    browser = get_browser()
    try:
        result = browser.create_user_coupon(
            username=username,
            discount=discount,
            note=note or "",
            free_shipping=free_shipping,
            min_order=min_order,
            max_discount=max_discount,
        )
        print_json(result)
        print_success(f"User coupon created for {username}")
    except RuntimeError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Failed to create user coupon: {e}")
        raise typer.Exit(1)
    finally:
        browser.close()


@app.command("create-code")
def coupon_create_code(
    code: str = typer.Argument(..., help="Coupon code"),
    discount: float = typer.Argument(..., help="Discount percentage"),
    min_order: Optional[float] = typer.Option(None, "--min-order", help="Minimum order amount"),
    max_discount: Optional[float] = typer.Option(None, "--max-discount", help="Maximum discount amount"),
    free_shipping: bool = typer.Option(False, "--free-shipping", help="Include free shipping"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Maximum number of redemptions"),
    note: Optional[str] = typer.Option(None, "--note", "-n", help="Coupon note"),
):
    """
    Create a coupon with a specific code.

    Examples:
        brickowl coupon create-code SAVE10 10
        brickowl coupon create-code HOLIDAY20 20 --min-order 50 --limit 100
    """
    from ..browser import get_browser

    browser = get_browser()
    try:
        result = browser.create_coupon_code(
            code=code,
            discount=discount,
            note=note or "",
            free_shipping=free_shipping,
            min_order=min_order,
            max_discount=max_discount,
            limit=limit or 1,
        )
        print_json(result)
        print_success(f"Coupon code '{code}' created")
    except RuntimeError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Failed to create coupon code: {e}")
        raise typer.Exit(1)
    finally:
        browser.close()


@app.command("delete")
def coupon_delete(
    coupon_id: str = typer.Argument(..., help="The coupon ID to delete"),
):
    """
    Delete a coupon.

    Examples:
        brickowl coupon delete COUPON_ID
    """
    from ..browser import get_browser

    browser = get_browser()
    try:
        result = browser.delete_coupon(coupon_id)
        print_json(result)
        print_success(f"Coupon {coupon_id} deleted")
    except RuntimeError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Failed to delete coupon: {e}")
        raise typer.Exit(1)
    finally:
        browser.close()
