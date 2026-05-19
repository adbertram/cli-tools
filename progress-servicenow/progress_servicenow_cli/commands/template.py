"""Ticket template commands for Progress ServiceNow CLI.

Provides offline access to catalog item form schemas so callers know
exactly which fields are available before creating a ticket — no browser
session or authentication required.
"""
import json
import typer
from pathlib import Path
from typing import Optional, List

from cli_tools_shared.output import (
    print_json, print_table, print_info, print_error,
)
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError

app = typer.Typer(help="Ticket form templates (offline — no auth required)", no_args_is_help=True)

# No credentials needed — purely local data
COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
    "fields": ["no_auth"],
}

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent.parent / "ticket_template.json"


def _load_template() -> dict:
    """Load the ticket template JSON."""
    if not _TEMPLATE_PATH.exists():
        raise typer.BadParameter(
            f"ticket_template.json not found at {_TEMPLATE_PATH}. "
            "Re-install the CLI to restore it."
        )
    with open(_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@app.command("list")
def template_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """
    List all available catalog item templates.

    Shows every catalog item that can be used to create a ticket, along with
    its key, description, category, and number of documented fields.

    Examples:
        progress-servicenow ticket template list --table
        progress-servicenow ticket template list --filter "category:eq:IT"
        progress-servicenow ticket template list --properties "key,name,category"
    """
    if filter:
        try:
            validate_filters(filter)
        except FilterValidationError as e:
            print_error(str(e))
            raise typer.Exit(1)

    data = _load_template()
    items = []
    for key, item in data["catalog_items"].items():
        field_count = len(item.get("fields", {}))
        required_fields = [
            fname for fname, fdef in item.get("fields", {}).items()
            if fdef.get("required")
        ]
        items.append({
            "key": key,
            "name": item["name"],
            "description": item.get("description", ""),
            "category": item.get("category", ""),
            "fields": field_count,
            "required_fields": ", ".join(required_fields) if required_fields else "none",
            "notes": item.get("notes", ""),
        })

    if filter:
        items = apply_filters(items, filter)

    items = items[:limit]

    if properties:
        fields = [f.strip() for f in properties.split(",")]
        items = [{f: row.get(f) for f in fields} for row in items]

    if table:
        if items:
            if properties:
                columns = [f.strip() for f in properties.split(",")]
            else:
                columns = ["key", "name", "category", "fields", "required_fields"]
            headers = [c.replace("_", " ").title() for c in columns]
            print_table(items, columns, headers)
        else:
            print_info("No templates found.")
    else:
        print_json(items)


@app.command("get")
def template_get(
    key: str = typer.Argument(
        ...,
        help="Catalog item key (e.g., 'development_cloud_issue', 'purchase_request'). "
             "Use 'ticket template list' to see all keys.",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """
    Get the full template for a specific catalog item.

    Returns the catalog item metadata and all its form fields with types,
    defaults, placeholders, help text, and required status.

    Examples:
        progress-servicenow ticket template get development_cloud_issue
        progress-servicenow ticket template get purchase_request --table
        progress-servicenow ticket template get purchase_request --properties "name,description,fields"
    """
    data = _load_template()
    catalog_items = data["catalog_items"]

    if key not in catalog_items:
        print_error(f"Unknown template key: '{key}'")
        print_info("Available keys:")
        for k in sorted(catalog_items.keys()):
            print_info(f"  {k}")
        raise typer.Exit(1)

    item = catalog_items[key]

    if properties:
        fields = [f.strip() for f in properties.split(",")]
        result = {f: item.get(f) for f in fields}
    else:
        result = item

    if table:
        # Show as key-value pairs
        rows = []
        for k, v in result.items():
            if k == "fields":
                v = f"{len(v)} fields (use 'ticket template fields {key}' to see details)"
            elif isinstance(v, (dict, list)):
                v = json.dumps(v, indent=2)
            rows.append({"property": k, "value": str(v) if v is not None else ""})
        print_table(rows, ["property", "value"], ["Property", "Value"])
    else:
        print_json(result)


@app.command("fields")
def template_fields(
    key: str = typer.Argument(
        ...,
        help="Catalog item key (e.g., 'development_cloud_issue', 'purchase_request')",
    ),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated field properties to include"
    ),
    required_only: bool = typer.Option(
        False, "--required", "-r", help="Show only required fields"
    ),
):
    """
    List all form fields for a specific catalog item template.

    Shows field names, types, required status, defaults, placeholders,
    and help text for every field on the form.

    Examples:
        progress-servicenow ticket template fields development_cloud_issue --table
        progress-servicenow ticket template fields purchase_request --required --table
        progress-servicenow ticket template fields purchase_request --filter "type:eq:dropdown"
        progress-servicenow ticket template fields purchase_request --properties "key,label,type,required"
    """
    if filter:
        try:
            validate_filters(filter)
        except FilterValidationError as e:
            print_error(str(e))
            raise typer.Exit(1)

    data = _load_template()
    catalog_items = data["catalog_items"]

    if key not in catalog_items:
        print_error(f"Unknown template key: '{key}'")
        print_info("Available keys:")
        for k in sorted(catalog_items.keys()):
            print_info(f"  {k}")
        raise typer.Exit(1)

    item = catalog_items[key]
    fields_dict = item.get("fields", {})

    if not fields_dict:
        print_info(f"No documented fields for '{key}'.")
        if item.get("notes"):
            print_info(f"Note: {item['notes']}")
        raise typer.Exit(0)

    rows = []
    for field_key, field_def in fields_dict.items():
        # Flatten options for display
        options = field_def.get("options", [])
        if options and isinstance(options[0], dict):
            options_str = ", ".join(o.get("label", o.get("value", "")) for o in options)
        elif options:
            options_str = ", ".join(str(o) for o in options)
        else:
            options_str = ""

        row = {
            "key": field_key,
            "label": field_def.get("label", ""),
            "type": field_def.get("type", ""),
            "required": str(field_def.get("required", False)).lower(),
            "default": str(field_def.get("default", "")) if field_def.get("default") is not None else "",
            "placeholder": field_def.get("placeholder", "") or "",
            "help_text": field_def.get("help_text", "") or "",
            "description": field_def.get("description", "") or "",
            "options": options_str,
            "conditional": str(field_def.get("conditional", False)).lower(),
        }
        rows.append(row)

    if required_only:
        rows = [r for r in rows if r["required"] == "true"]

    if filter:
        rows = apply_filters(rows, filter)

    if properties:
        prop_list = [f.strip() for f in properties.split(",")]
        rows = [{p: row.get(p) for p in prop_list} for row in rows]

    if table:
        if rows:
            if properties:
                columns = [f.strip() for f in properties.split(",")]
            else:
                columns = ["key", "label", "type", "required", "default", "options"]
            headers = [c.replace("_", " ").title() for c in columns]
            print_table(rows, columns, headers)
        else:
            print_info("No fields match the criteria.")
    else:
        print_json(rows)
