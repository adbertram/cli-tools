"""Store commands for eBay CLI.

Uses the eBay Stores API to manage store settings and categories.
API Docs: https://developer.ebay.com/api-docs/sell/stores/resources/store/methods/getStoreCategories
"""
from cli_tools_shared.output import command
COMMAND_CREDENTIALS = {
    "list": ["oauth_authorization_code"],
    "categories": ["oauth_authorization_code"],
    "time-away": ["browser_session"],
}

from datetime import date, datetime
from typing import Optional, List

import typer

from ..client import get_client
from ..config import get_config
from .. import time_away
from cli_tools_shared.output import print_json, print_table, handle_error, print_error, print_success
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
from ..properties import validate_and_filter_properties, PropertyValidationError

app = typer.Typer(help="Manage eBay store")
categories_app = typer.Typer(help="Manage eBay store categories")
time_away_app = typer.Typer(help="Manage eBay Time Away settings", no_args_is_help=True)
app.add_typer(categories_app, name="categories", help="Manage eBay store categories")
app.add_typer(time_away_app, name="time-away", help="Manage eBay Time Away settings")

DATE_INPUT_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d")
DATE_HELP = "M/D/YY, MM/DD/YYYY, or YYYY-MM-DD"
TIME_AWAY_MODES = {"allow-sales", "pause-sales"}


def _flatten_categories(categories: list, parent_path: str = "") -> list:
    """Flatten nested store category hierarchy into a flat list.

    Each category includes its full path for use with storeCategoryNames.

    Args:
        categories: List of store category dicts from the API
        parent_path: Parent category path prefix

    Returns:
        Flat list of category dicts with id, name, level, order, path
    """
    result = []
    for cat in categories:
        name = cat.get("categoryName", "")
        cat_id = cat.get("categoryId", "")
        level = cat.get("level", 0)
        order = cat.get("order", 0)

        path = f"{parent_path}/{name}" if parent_path else name

        result.append({
            "categoryId": cat_id,
            "categoryName": name,
            "level": level,
            "order": order,
            "path": path,
        })

        children = cat.get("childrenCategories", [])
        if children:
            result.extend(_flatten_categories(children, parent_path=path))

    return result


def _parse_time_away_date(value: str) -> date:
    """Parse a Time Away date from the accepted CLI formats."""
    for date_format in DATE_INPUT_FORMATS:
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue
    raise ValueError(f"date must be {DATE_HELP}")


def _format_display_date(value: date) -> str:
    return f"{value.month}/{value.day}/{value.year}"


def _format_result(action: str, result: dict, *, dry_run: bool = False) -> dict:
    return {
        "success": True,
        "action": action,
        "dry_run": dry_run,
        "url": result.get("url"),
        "title": result.get("title"),
        "enabled": result.get("enabled"),
        "mode": result.get("mode"),
        "has_schedule_action": result.get("has_schedule_action"),
        "has_cancel_action": result.get("has_cancel_action"),
        "text_excerpt": result.get("text_excerpt"),
    }


def _get_browser(profile: Optional[str] = None):
    return get_config(profile=profile).get_browser()


def _print_time_away_result(result: dict, table: bool) -> None:
    if result.get("success") and result.get("submitted"):
        print_success(result["message"])
    if table:
        print_table(
            [result],
            ["action", "dry_run", "submitted", "enabled", "mode", "url"],
            ["Action", "Dry Run", "Submitted", "Enabled", "Mode", "URL"],
        )
    else:
        print_json(result)


@time_away_app.command("get")
@command
def time_away_get(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="Profile name"),
):
    """Get current eBay Time Away settings."""
    browser = _get_browser(profile=profile)
    try:
        result = _format_result("get", time_away.read_settings(browser))
        _print_time_away_result(result, table)
    except Exception as e:
        raise typer.Exit(handle_error(e))
    finally:
        browser.close()


@time_away_app.command("enable")
@command
def time_away_enable(
    end_date: str = typer.Argument(..., help=f"Time Away end date in {DATE_HELP} format"),
    start_date: Optional[str] = typer.Option(None, "--start-date", help=f"Time Away start date in {DATE_HELP} format; defaults to today"),
    mode: str = typer.Option("allow-sales", "--mode", help="Time Away mode: allow-sales or pause-sales"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without saving"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Save changes to eBay"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="Profile name"),
):
    """Schedule eBay Time Away."""
    if mode not in TIME_AWAY_MODES:
        print_error("mode must be allow-sales or pause-sales")
        raise typer.Exit(1)
    if not dry_run and not yes:
        print_error("Refusing to update eBay Time Away without --yes or --dry-run.")
        raise typer.Exit(1)

    try:
        parsed_start = _parse_time_away_date(start_date) if start_date else date.today()
        parsed_end = _parse_time_away_date(end_date)
        if parsed_end < parsed_start:
            raise ValueError("end_date must be on or after start_date")

        browser = _get_browser(profile=profile)
        try:
            if dry_run:
                state = time_away.read_settings(browser)
                result = _format_result("enable", state, dry_run=True)
                result.update(
                    {
                        "submitted": False,
                        "start_date": parsed_start.isoformat(),
                        "end_date": parsed_end.isoformat(),
                        "mode": mode,
                        "message": "Dry run: eBay Time Away enable changes were not saved.",
                    }
                )
            else:
                state = time_away.enable(
                    browser,
                    start_date_iso=parsed_start.isoformat(),
                    start_date_display=_format_display_date(parsed_start),
                    end_date_iso=parsed_end.isoformat(),
                    end_date_display=_format_display_date(parsed_end),
                    mode=mode,
                )
                result = _format_result("enable", state)
                result.update(
                    {
                        "submitted": True,
                        "start_date": parsed_start.isoformat(),
                        "end_date": parsed_end.isoformat(),
                        "mode": mode,
                        "message": "eBay Time Away enable saved.",
                    }
                )
            _print_time_away_result(result, table)
        finally:
            browser.close()
    except Exception as e:
        raise typer.Exit(handle_error(e))


@time_away_app.command("disable")
@command
def time_away_disable(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without saving"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Save changes to eBay"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="Profile name"),
):
    """Cancel eBay Time Away."""
    if not dry_run and not yes:
        print_error("Refusing to update eBay Time Away without --yes or --dry-run.")
        raise typer.Exit(1)

    browser = _get_browser(profile=profile)
    try:
        if dry_run:
            state = time_away.read_settings(browser)
            result = _format_result("disable", state, dry_run=True)
            result.update(
                {
                    "submitted": False,
                    "message": "Dry run: eBay Time Away disable changes were not saved.",
                }
            )
        else:
            state = time_away.disable(browser)
            result = _format_result("disable", state)
            result.update(
                {
                    "submitted": True,
                    "message": "eBay Time Away disable saved.",
                }
            )
        _print_time_away_result(result, table)
    except Exception as e:
        raise typer.Exit(handle_error(e))
    finally:
        browser.close()


@categories_app.command("list")
@command
def categories_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    flat: bool = typer.Option(False, "--flat", help="Flatten category hierarchy into a flat list"),
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
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        "-l",
        help="Maximum number of categories to return (client-side truncation)"
    ),
):
    """
    List all store categories for the seller's eBay store.

    Returns the store category hierarchy (up to 3 levels deep).
    Use --flat to flatten the hierarchy into a single list.

    Examples:
        ebay store categories list
        ebay store categories list --table
        ebay store categories list --flat --table
        ebay store categories list --filter "categoryName:ilike:%lego%"
    """
    try:
        client = get_client()
        result = client.get_store_categories()

        categories = result.get("storeCategories", [])

        if flat:
            categories = _flatten_categories(categories)

        # Validate and apply client-side filters if provided
        if filters:
            try:
                validated_filters = validate_filters(filters)
                categories = apply_filters(categories, validated_filters)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply properties filter if specified
        if properties:
            try:
                categories = validate_and_filter_properties(categories, properties)
            except PropertyValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply client-side limit (truncate flattened results)
        if limit is not None:
            if not flat:
                categories = _flatten_categories(categories)
            categories = categories[:limit]
            # Force flat display since we truncated a flattened list
            flat = True

        if table:
            if not categories:
                print("No store categories found.")
                return

            if flat:
                table_data = []
                for cat in categories:
                    indent = "  " * (cat.get("level", 1) - 1)
                    table_data.append({
                        "id": cat.get("categoryId", ""),
                        "name": f"{indent}{cat.get('categoryName', '')}",
                        "level": str(cat.get("level", "")),
                        "order": str(cat.get("order", "")),
                        "path": cat.get("path", ""),
                    })

                print_table(
                    table_data,
                    ["id", "name", "level", "order", "path"],
                    ["Category ID", "Name", "Level", "Order", "Path"],
                )
            else:
                # For hierarchical display, flatten for table but show indentation
                flat_cats = _flatten_categories(categories)
                table_data = []
                for cat in flat_cats:
                    indent = "  " * (cat.get("level", 1) - 1)
                    table_data.append({
                        "id": cat.get("categoryId", ""),
                        "name": f"{indent}{cat.get('categoryName', '')}",
                        "level": str(cat.get("level", "")),
                        "order": str(cat.get("order", "")),
                    })

                print_table(
                    table_data,
                    ["id", "name", "level", "order"],
                    ["Category ID", "Name", "Level", "Order"],
                )
        else:
            if flat:
                print_json({"storeCategories": categories, "total": len(categories)})
            else:
                print_json({"storeCategories": categories, "total": len(categories)})

    except Exception as e:
        raise typer.Exit(handle_error(e))


@categories_app.command("get")
@command
def categories_get(
    category_id: str = typer.Argument(..., help="Store category ID to look up"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a specific store category by ID.

    Fetches all store categories and returns the one matching the given ID,
    including its full path in the category hierarchy.

    Examples:
        ebay store categories get 12345
        ebay store categories get 12345 --table
    """
    try:
        client = get_client()
        result = client.get_store_categories()

        categories = result.get("storeCategories", [])
        flat_cats = _flatten_categories(categories)

        # Find the category by ID
        match = None
        for cat in flat_cats:
            if str(cat.get("categoryId", "")) == str(category_id):
                match = cat
                break

        if not match:
            print_error(f"Store category '{category_id}' not found.")
            raise typer.Exit(1)

        if table:
            table_data = [{
                "id": match.get("categoryId", ""),
                "name": match.get("categoryName", ""),
                "level": str(match.get("level", "")),
                "order": str(match.get("order", "")),
                "path": match.get("path", ""),
            }]

            print_table(
                table_data,
                ["id", "name", "level", "order", "path"],
                ["Category ID", "Name", "Level", "Order", "Path"],
            )
        else:
            print_json(match)

    except Exception as e:
        raise typer.Exit(handle_error(e))
