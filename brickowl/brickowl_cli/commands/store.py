"""Store settings commands for Brickowl CLI (browser-based)."""
COMMAND_CREDENTIALS = {
    "vacation": [
        "browser_session",
    ],
}

import re
from datetime import datetime
from typing import Optional

import typer

from cli_tools_shared.output import command, print_error, print_json, print_success, print_table

app = typer.Typer(help="Manage Brick Owl store settings", no_args_is_help=True)
vacation_app = typer.Typer(help="Manage vacation shipping notice text", no_args_is_help=True)
app.add_typer(vacation_app, name="vacation", help="Manage vacation shipping notice text")


VACATION_MESSAGE = "ATTENTION: All orders will ship"
LEGACY_VACATION_MESSAGE = "ATTENTION: All orders will ship out"
VACATION_SUFFIX_PREFIX = f" | {VACATION_MESSAGE} "
SHIP_OUT_DATE_FORMAT = "%m/%d/%Y"
SHIP_OUT_DATE_INPUT_FORMATS = ("%m/%d/%Y", "%m/%d/%y")
SHIP_OUT_DATE_FORMAT_LABEL = "M/D/YY or MM/DD/YYYY"
SLOGAN_MAX_LENGTH = 85
VACATION_SUFFIX_RE = re.compile(
    rf"(?:\s*\|\s*{re.escape(LEGACY_VACATION_MESSAGE)} \d{{2}}/\d{{2}}/\d{{4}}"
    rf"|\s*\|\s*{re.escape(VACATION_MESSAGE)} \d{{1,2}}/\d{{1,2}}/\d{{2,4}}!)+\s*$"
)


def validate_ship_out_date(ship_out_date: str) -> str:
    """Validate and normalize a ship-out date to MM/DD/YYYY."""
    if not re.fullmatch(r"\d{1,2}/\d{1,2}/(?:\d{2}|\d{4})", ship_out_date):
        raise ValueError(f"ship_out_date must be {SHIP_OUT_DATE_FORMAT_LABEL}")
    for date_format in SHIP_OUT_DATE_INPUT_FORMATS:
        try:
            parsed = datetime.strptime(ship_out_date, date_format)
            return parsed.strftime(SHIP_OUT_DATE_FORMAT)
        except ValueError:
            continue
    raise ValueError(
        f"ship_out_date must be a valid calendar date in {SHIP_OUT_DATE_FORMAT_LABEL} format"
    )


def format_store_ship_out_date(ship_out_date: str) -> str:
    """Format a validated ship-out date in the accepted short form."""
    parsed = datetime.strptime(validate_ship_out_date(ship_out_date), SHIP_OUT_DATE_FORMAT)
    return f"{parsed.month}/{parsed.day}/{parsed.year % 100:02d}"


def vacation_suffix(ship_out_date: str) -> str:
    return f"{VACATION_SUFFIX_PREFIX}{format_store_ship_out_date(ship_out_date)}!"


def remove_vacation_suffix(value: str) -> str:
    """Remove one or more trailing vacation notices."""
    return VACATION_SUFFIX_RE.sub("", value or "").rstrip()


def apply_vacation_suffix(value: str, ship_out_date: str) -> str:
    """Replace any existing vacation notice with the requested ship-out date."""
    clean_value = remove_vacation_suffix(value)
    return f"{clean_value}{vacation_suffix(ship_out_date)}"


def _field_summary(current: str, updated: str) -> dict:
    current_clean = remove_vacation_suffix(current)
    updated_clean = remove_vacation_suffix(updated)
    return {
        "field": "slogan",
        "changed": current != updated,
        "previous_has_vacation_suffix": current != current_clean,
        "updated_has_vacation_suffix": updated != updated_clean,
        "previous_length": len(current or ""),
        "updated_length": len(updated or ""),
    }


def _result_message(action: str, *, changed: bool, dry_run: bool, submitted: bool) -> str:
    if dry_run:
        return f"Dry run: Brick Owl store vacation {action} changes were not saved."
    if not changed:
        return f"Brick Owl store vacation {action} made no changes."
    if submitted:
        return f"Brick Owl store vacation {action} saved."
    return f"Brick Owl store vacation {action} did not submit changes."


def _build_result(
    *,
    enabled: bool,
    ship_out_date: Optional[str],
    dry_run: bool,
    submitted: bool,
    current: dict,
    updated_slogan: str,
    response: Optional[dict],
) -> dict:
    action = "enable" if enabled else "disable"
    field = _field_summary(current["slogan"], updated_slogan)
    result = {
        "success": True,
        "action": action,
        "enabled": enabled,
        "dry_run": dry_run,
        "changed": field["changed"],
        "submitted": submitted,
        "ship_out_date": ship_out_date,
        "suffix": vacation_suffix(ship_out_date) if ship_out_date else None,
        "fields": [field],
        "message": _result_message(
            action,
            changed=field["changed"],
            dry_run=dry_run,
            submitted=submitted,
        ),
    }
    if response is not None:
        result["response"] = response
    return result


def _run_vacation_update(
    *,
    enabled: bool,
    ship_out_date: Optional[str] = None,
    dry_run: bool,
    yes: bool,
) -> dict:
    if not dry_run and not yes:
        print_error(
            "Refusing to update Brick Owl store vacation text without --yes or --dry-run."
        )
        raise typer.Exit(1)

    if enabled:
        if ship_out_date is None:
            raise ValueError("ship_out_date is required when enabling vacation text")
        ship_out_date = validate_ship_out_date(ship_out_date)

    from ..browser import get_browser

    browser = get_browser()
    try:
        current = browser.get_store_settings()
        if enabled:
            updated_slogan = apply_vacation_suffix(current["slogan"], ship_out_date)
        else:
            updated_slogan = remove_vacation_suffix(current["slogan"])

        max_length = current.get("slogan_max_length") or SLOGAN_MAX_LENGTH
        if len(updated_slogan) > max_length:
            raise ValueError(
                f"Updated Brick Owl slogan is {len(updated_slogan)} characters; "
                f"maximum is {max_length}."
            )

        response = None
        submitted = False
        if current["slogan"] != updated_slogan and not dry_run:
            response = browser.save_store_slogan(updated_slogan)
            submitted = True

        return _build_result(
            enabled=enabled,
            ship_out_date=ship_out_date,
            dry_run=dry_run,
            submitted=submitted,
            current=current,
            updated_slogan=updated_slogan,
            response=response,
        )
    finally:
        browser.close()


def _print_vacation_result(result: dict, table: bool) -> None:
    if result.get("success") and result.get("submitted"):
        print_success(result["message"])
    if table:
        print_table(
            result["fields"],
            [
                "field",
                "changed",
                "previous_has_vacation_suffix",
                "updated_has_vacation_suffix",
                "previous_length",
                "updated_length",
            ],
            ["Field", "Changed", "Had Notice", "Has Notice", "Previous Length", "Updated Length"],
        )
    else:
        print_json(result)


@vacation_app.command("enable")
@command
def vacation_enable(
    ship_out_date: str = typer.Argument(
        ...,
        help=f"Ship-out date to show in {SHIP_OUT_DATE_FORMAT_LABEL} format",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without saving"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Save changes to Brick Owl"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Add or replace the vacation shipping notice on the Brick Owl Slogan / Tag Line.

    Examples:
        brickowl store vacation enable 7/21/26 --dry-run
        brickowl store vacation enable 7/21/26 --yes
    """
    result = _run_vacation_update(
        enabled=True,
        ship_out_date=ship_out_date,
        dry_run=dry_run,
        yes=yes,
    )
    _print_vacation_result(result, table)


@vacation_app.command("disable")
@command
def vacation_disable(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without saving"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Save changes to Brick Owl"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Remove the vacation shipping notice from the Brick Owl Slogan / Tag Line.

    Examples:
        brickowl store vacation disable --dry-run
        brickowl store vacation disable --yes
    """
    result = _run_vacation_update(
        enabled=False,
        dry_run=dry_run,
        yes=yes,
    )
    _print_vacation_result(result, table)
