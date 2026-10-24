from .._bytecode import load_module_bytecode

load_module_bytecode(__name__, globals())

from typing import List, Optional

import typer
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import FilterValidationError, apply_filters, validate_filters
from cli_tools_shared.output import (
    command,
    handle_error,
    print_error,
    print_info,
    print_json,
    print_success,
    print_table,
)

from .. import catalog_api
from ..client import get_client
from ..template_data import load_ticket_template, save_ticket_template

# ``refresh`` is the only template command that talks to ServiceNow.
COMMAND_CREDENTIALS["refresh"] = ["browser_session"]


def _template_rows() -> list[dict]:
    template = load_ticket_template()
    rows = []
    for key, item in template["catalog_items"].items():
        required_fields = item.get("required_fields", [])
        rows.append(
            {
                "id": key,
                "key": key,
                "name": item.get("name", ""),
                "description": item.get("description", ""),
                "category": item.get("category", ""),
                "fields": len(item.get("fields", {})),
                "required_fields": ", ".join(required_fields) if required_fields else "none",
                "notes": item.get("notes", ""),
            }
        )
    return rows


def _template_by_key(key: str) -> dict:
    template = load_ticket_template()
    catalog_items = template["catalog_items"]
    if key not in catalog_items:
        print_error(
            f"Unknown template key: {key!r}\n"
            "Available keys:\n"
            + "\n".join(f"  {available_key}" for available_key in catalog_items)
        )
        raise typer.Exit(1)
    return {"id": key, "key": key, **catalog_items[key]}


def _select_properties(row: dict, properties: Optional[str]) -> dict:
    if not properties:
        return row
    fields = [field.strip() for field in properties.split(",")]
    return {field: row.get(field) for field in fields}


def template_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """List all available catalog item templates."""
    try:
        if filter:
            validate_filters(filter)
        rows = _template_rows()
        if filter:
            rows = apply_filters(rows, filter)
        rows = rows[:limit]
        rows = [_select_properties(row, properties) for row in rows]

        if table:
            if rows:
                columns = (
                    [field.strip() for field in properties.split(",")]
                    if properties
                    else ["id", "name", "category", "fields", "required_fields"]
                )
                print_table(rows, columns, [column.title() for column in columns])
            else:
                print_info("No templates found.")
            return

        print_json(rows)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


def template_get(
    key: str = typer.Argument(
        ..., help="Catalog item key (e.g., 'development_cloud_issue', 'purchase_request')"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """Get the full template for a specific catalog item."""
    row = _select_properties(_template_by_key(key), properties)

    if table:
        columns = (
            [field.strip() for field in properties.split(",")]
            if properties
            else ["id", "name", "category", "description"]
        )
        print_table([row], columns, [column.title() for column in columns])
    else:
        print_json(row)


@app.command("refresh")
@command
def template_refresh(
    add: Optional[List[str]] = typer.Option(
        None,
        "--add",
        "-a",
        help="Exact catalog item name to add to the registry. Repeatable.",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Rebuild ticket_template.json from the live ServiceNow catalog.

    Every registry entry is re-resolved against the live Service Catalog API:
    name, category, description, sys_id, field labels, field types, required
    flags, and dropdown options all come from the live catalog item. Registry
    keys are derived from the live catalog item name, so a renamed or retired
    item shows up as a changed or failing key instead of silently going stale.

    Examples:
        progress-servicenow ticket template refresh
        progress-servicenow ticket template refresh --add "Development Database Request"
    """
    existing = load_ticket_template()["catalog_items"]
    names: List[str] = []
    for key, entry in existing.items():
        name = entry.get("name")
        if not name:
            print_error(
                f"Template entry {key!r} has no 'name', so it cannot be resolved against "
                "the live catalog. Fix or remove the entry, then re-run refresh."
            )
            raise typer.Exit(1)
        names.append(str(name))
    for name in add or []:
        names.append(name)

    client = get_client()
    rows = []
    catalog_items = {}
    try:
        page = client.catalog_page()
        for name in dict.fromkeys(names):
            sys_id = catalog_api.resolve_item_sys_id(page, name)
            item = catalog_api.get_item(page, sys_id)
            entry = catalog_api.build_template_entry(item)
            key = catalog_api.template_key_for(entry["name"])
            catalog_items[key] = entry
            rows.append(
                {
                    "key": key,
                    "name": entry["name"],
                    "sys_id": entry["sys_id"],
                    "fields": len(entry["fields"]),
                    "required_fields": ", ".join(entry["required_fields"]) or "none",
                }
            )
    except ClientError as exc:
        handle_error(exc)
        raise typer.Exit(1)
    finally:
        client.close()

    path = save_ticket_template({"catalog_items": catalog_items})
    print_success(f"Refreshed {len(catalog_items)} catalog item templates in {path}")

    if table:
        columns = ["key", "name", "sys_id", "fields", "required_fields"]
        print_table(rows, columns, [column.replace("_", " ").title() for column in columns])
    else:
        print_json(rows)


for command_info in app.registered_commands:
    if command_info.name == "list":
        command_info.callback = template_list
    elif command_info.name == "get":
        command_info.callback = template_get
