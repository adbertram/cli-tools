"""Store settings commands for Bricklink CLI (browser-based)."""
COMMAND_CREDENTIALS = {
    "vacation": [
        "browser_session"
    ]
}

import re
from datetime import datetime
from typing import Optional

import typer

from cli_tools_shared.output import (
    command,
    print_error,
    print_output,
    print_success,
)

from . import run_browser


app = typer.Typer(help="Manage store settings (browser)", no_args_is_help=True)
vacation_app = typer.Typer(help="Manage vacation shipping notice text", no_args_is_help=True)
app.add_typer(vacation_app, name="vacation", help="Manage vacation shipping notice text")


VACATION_MESSAGE = "ATTENTION: All orders will ship"
LEGACY_VACATION_MESSAGE = "ATTENTION: All orders will ship out"
VACATION_SUFFIX_PREFIX = f" | {VACATION_MESSAGE} "
SHIP_OUT_DATE_FORMAT = "%m/%d/%Y"
SHIP_OUT_DATE_INPUT_FORMATS = ("%m/%d/%Y", "%m/%d/%y")
SHIP_OUT_DATE_FORMAT_LABEL = "M/D/YY or MM/DD/YYYY"
VACATION_SUFFIX_RE = re.compile(
    rf"(?:\s*\|\s*{re.escape(LEGACY_VACATION_MESSAGE)} \d{{2}}/\d{{2}}/\d{{4}}"
    rf"|\s*\|\s*{re.escape(VACATION_MESSAGE)} \d{{1,2}}/\d{{1,2}}/\d{{2,4}}!)+\s*$"
)


def validate_ship_out_date(ship_out_date: str) -> str:
    """Validate and preserve a required MM/DD/YYYY ship-out date."""
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
    """Format a validated ship-out date in BrickLink's accepted short form."""
    parsed = datetime.strptime(validate_ship_out_date(ship_out_date), SHIP_OUT_DATE_FORMAT)
    return f"{parsed.month}/{parsed.day}/{parsed.year % 100:02d}"


def remove_vacation_suffix(value: str) -> str:
    """Remove one or more trailing BrickLink vacation notices."""
    return VACATION_SUFFIX_RE.sub("", value or "").rstrip()


def apply_vacation_suffix(value: str, ship_out_date: str) -> str:
    """Replace any existing vacation notice with the requested ship-out date."""
    clean_value = remove_vacation_suffix(value)
    return f"{clean_value}{VACATION_SUFFIX_PREFIX}{format_store_ship_out_date(ship_out_date)}!"


def _field_summary(name: str, current: str, updated: str) -> dict:
    current_clean = remove_vacation_suffix(current)
    updated_clean = remove_vacation_suffix(updated)
    return {
        "field": name,
        "changed": current != updated,
        "previous_has_vacation_suffix": current != current_clean,
        "updated_has_vacation_suffix": updated != updated_clean,
        "previous_length": len(current or ""),
        "updated_length": len(updated or ""),
    }


def _shipping_method_summary(current: dict, updated_note: str) -> dict:
    summary = _field_summary(
        f"shipping_method:{current['id']}:{current['name']}",
        current.get("description", ""),
        updated_note,
    )
    summary["shipping_method_id"] = current["id"]
    summary["shipping_method_name"] = current["name"]
    return summary


def _build_result(
    *,
    enabled: bool,
    ship_out_date: Optional[str],
    dry_run: bool,
    submitted: bool,
    current: dict,
    updated: dict,
    response: Optional[dict],
) -> dict:
    action = "enable" if enabled else "disable"
    fields = [
        _field_summary("announcement", current["announcement"], updated["announcement"]),
        _field_summary("banner", current["banner"], updated["banner"]),
        *[
            _shipping_method_summary(method, updated_note)
            for method, updated_note in zip(
                current["shipping_methods"],
                updated["shipping_method_notes"],
            )
        ],
    ]
    changed = any(field["changed"] for field in fields)
    result = {
        "success": True,
        "action": action,
        "enabled": enabled,
        "dry_run": dry_run,
        "changed": changed,
        "submitted": submitted,
        "ship_out_date": ship_out_date,
        "suffix": (
            f"{VACATION_SUFFIX_PREFIX}{format_store_ship_out_date(ship_out_date)}!"
            if ship_out_date
            else None
        ),
        "fields": fields,
        "message": _result_message(action, changed=changed, dry_run=dry_run, submitted=submitted),
    }
    if response is not None:
        result["response"] = response
    return result


def _result_message(action: str, *, changed: bool, dry_run: bool, submitted: bool) -> str:
    if dry_run:
        return f"Dry run: store vacation {action} changes were not saved."
    if not changed:
        return f"Store vacation {action} made no changes."
    if submitted:
        return f"Store vacation {action} saved."
    return f"Store vacation {action} did not submit changes."


def _run_vacation_update(
    *,
    enabled: bool,
    ship_out_date: Optional[str] = None,
    dry_run: bool,
    yes: bool,
) -> dict:
    if not dry_run and not yes:
        print_error(
            "Refusing to update BrickLink store vacation text without --yes or --dry-run."
        )
        raise typer.Exit(1)

    if enabled:
        if ship_out_date is None:
            raise ValueError("ship_out_date is required when enabling vacation text")
        ship_out_date = validate_ship_out_date(ship_out_date)

    def _update(browser):
        settings = browser.get_store_display_settings()
        current = {
            "announcement": settings["announcement"],
            "banner": settings["banner"],
            "shipping_methods": browser.get_enabled_shipping_methods(),
        }
        if enabled:
            updated = {
                "announcement": apply_vacation_suffix(current["announcement"], ship_out_date),
                "banner": apply_vacation_suffix(current["banner"], ship_out_date),
                "shipping_method_notes": [
                    apply_vacation_suffix(method["description"], ship_out_date)
                    for method in current["shipping_methods"]
                ],
            }
        else:
            updated = {
                "announcement": remove_vacation_suffix(current["announcement"]),
                "banner": remove_vacation_suffix(current["banner"]),
                "shipping_method_notes": [
                    remove_vacation_suffix(method["description"])
                    for method in current["shipping_methods"]
                ],
            }

        response = {"display": None, "shipping_methods": []}
        submitted = False
        if (
            current["announcement"] != updated["announcement"]
            or current["banner"] != updated["banner"]
        ) and not dry_run:
            response["display"] = browser.save_store_display_settings(
                announcement=updated["announcement"],
                banner=updated["banner"],
            )
            submitted = True
        if not dry_run:
            for method, updated_note in zip(
                current["shipping_methods"],
                updated["shipping_method_notes"],
            ):
                if method["description"] == updated_note:
                    continue
                response["shipping_methods"].append(
                    browser.save_shipping_method_note(method["id"], updated_note)
                )
                submitted = True

        return _build_result(
            enabled=enabled,
            ship_out_date=ship_out_date,
            dry_run=dry_run,
            submitted=submitted,
            current=current,
            updated=updated,
            response=response if submitted else None,
        )

    return run_browser(_update)


def _print_vacation_result(result: dict, table: bool) -> None:
    if result.get("success") and result.get("submitted"):
        print_success(result["message"])
    columns = None
    headers = None
    data = result
    if table:
        data = result["fields"]
        columns = [
            "field",
            "changed",
            "previous_has_vacation_suffix",
            "updated_has_vacation_suffix",
            "previous_length",
            "updated_length",
        ]
        headers = [
            "Field",
            "Changed",
            "Had Notice",
            "Has Notice",
            "Previous Length",
            "Updated Length",
        ]
    print_output(
        data,
        table=table,
        columns=columns,
        headers=headers,
    )


@vacation_app.command("enable")
@command
def vacation_enable(
    ship_out_date: str = typer.Argument(
        ...,
        help=f"Ship-out date to show in {SHIP_OUT_DATE_FORMAT_LABEL} format",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview changes without saving",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Save changes to BrickLink"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Add or replace the vacation shipping notice on announcement, banner,
    and enabled shipping methods.

    Examples:
        bricklink store vacation enable 07/15/2026 --dry-run
        bricklink store vacation enable 07/15/2026 --yes
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
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview changes without saving",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Save changes to BrickLink"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Remove the vacation shipping notice from announcement, banner,
    and enabled shipping methods.

    Examples:
        bricklink store vacation disable --dry-run
        bricklink store vacation disable --yes
    """
    result = _run_vacation_update(
        enabled=False,
        dry_run=dry_run,
        yes=yes,
    )
    _print_vacation_result(result, table)
