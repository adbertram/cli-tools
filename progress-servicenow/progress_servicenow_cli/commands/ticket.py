"""Ticket commands for Progress ServiceNow CLI."""
import typer
from typing import Optional, List

from pydantic import BaseModel

from ..client import get_client
from ..template_data import load_ticket_template
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import (
    print_json, print_table, handle_error,
    print_success, print_error, print_info,
)
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError

def _load_template() -> dict:
    """Load the ticket template JSON."""
    try:
        return load_ticket_template()
    except FileNotFoundError as exc:
        raise typer.BadParameter(
            "ticket_template.json is missing from the installed package. "
            "Re-install the CLI to restore it."
        ) from exc

app = typer.Typer(help="Manage ServiceNow tickets", no_args_is_help=True)

# Register subgroups under ticket
from .template import app as template_app
app.add_typer(template_app, name="template")

from .product import app as product_app
app.add_typer(product_app, name="product")

from .form import app as form_app
app.add_typer(form_app, name="form")

COMMAND_CREDENTIALS = {
    "close": [
        "browser_session"
    ],
    "comment": [
        "browser_session"
    ],
    "create": [
        "browser_session"
    ],
    "form": [
        "browser_session"
    ],
    "get": [
        "browser_session"
    ],
    "list": [
        "browser_session"
    ],
    "product": [
        "browser_session"
    ],
    "template": [
        "browser_session"
    ]
}


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def extract_fields(items: list, fields: list) -> list:
    """Extract specified fields from items."""
    result = []
    for item in items:
        data = model_to_dict(item)
        extracted = {}
        for field in fields:
            parts = field.split(".")
            value = data
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = None
                    break
            extracted[field] = value
        result.append(extracted)
    return result


@app.command("list")
def ticket_list(
    view: str = typer.Option(
        "watchlist-open",
        "--view", "-V",
        help="View: open, closed, watchlist-open, watchlist-closed",
    ),
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
    List tickets from My Requests page.

    Examples:
        progress-servicenow ticket list
        progress-servicenow ticket list --view open --table
        progress-servicenow ticket list --view closed --limit 10
        progress-servicenow ticket list --filter "state:eq:Open"
        progress-servicenow ticket list --properties "number,description,state"
    """
    try:
        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        client = get_client()
        results = client.list_tickets(view=view, limit=limit)

        # Apply client-side filters
        if filter and isinstance(results, list):
            results_dict = [model_to_dict(item) for item in results]
            results_dict = apply_filters(results_dict, filter)
            results = results_dict

        # Apply properties selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            results = extract_fields(results, fields)

        if table:
            if results:
                if properties:
                    columns = [f.strip() for f in properties.split(",")]
                else:
                    columns = ["number", "description", "state", "updated"]
                headers = [c.replace("_", " ").title() for c in columns]
                print_table(results, columns, headers)
            else:
                print_info("No tickets found.")
        else:
            print_json(results)

        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def ticket_get(
    number: str = typer.Argument(..., help="RITM number (e.g., RITM0352332) or sys_id"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    comments: bool = typer.Option(False, "--comments", "-c", help="Include comments"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """
    Get details for a specific ticket.

    Examples:
        progress-servicenow ticket get RITM0352332
        progress-servicenow ticket get RITM0352332 --table
        progress-servicenow ticket get RITM0352332 --comments
        progress-servicenow ticket get abc123def456... --properties "number,state,assigned_to"
    """
    try:
        client = get_client()
        ticket = client.get_ticket(number)

        # Optionally strip comments for cleaner output
        if not comments:
            ticket_dict = model_to_dict(ticket)
            ticket_dict.pop('comments', None)
        else:
            ticket_dict = model_to_dict(ticket)

        # Apply properties selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            ticket_dict = extract_fields([ticket_dict], fields)[0]

        if table:
            if properties:
                columns = [f.strip() for f in properties.split(",")]
                print_table([ticket_dict], columns, columns)
            else:
                # Key-value table for single ticket
                rows = [
                    {"field": k, "value": str(v)}
                    for k, v in ticket_dict.items()
                    if v is not None
                ]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(ticket_dict)

        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("comment")
def ticket_comment(
    number: str = typer.Argument(..., help="RITM number or sys_id"),
    message: str = typer.Argument(..., help="Comment text to post"),
):
    """
    Post a comment on a ticket.

    Examples:
        progress-servicenow ticket comment RITM0352332 "Please update the status"
        progress-servicenow ticket comment abc123... "Thank you for the update"
    """
    try:
        client = get_client()
        client.comment_ticket(number, message)
        print_success(f"Comment posted on {number}")
        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("close")
def ticket_close(
    number: str = typer.Argument(..., help="RITM number or sys_id"),
):
    """
    Close a ticket.

    Examples:
        progress-servicenow ticket close RITM0352332
        progress-servicenow ticket close abc123def456...
    """
    try:
        client = get_client()
        client.close_ticket(number)
        print_success(f"Ticket {number} closed")
        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def ticket_create(
    template: Optional[str] = typer.Option(
        None, "--template", "-T",
        help="Template key for programmatic creation (e.g., 'development_cloud_issue'). "
             "Use 'ticket template list' to see all keys.",
    ),
    field: Optional[List[str]] = typer.Option(
        None, "--field", "-F",
        help="Field key=value pair. Repeatable. "
             "Use 'ticket template fields <key>' to see available fields.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Validate fields against the template without submitting.",
    ),
    draft: bool = typer.Option(
        False, "--draft",
        help="Save as draft instead of submitting.",
    ),
):
    """
    Create a ServiceNow ticket.

    Without --template, opens a headed browser for manual ticket creation.

    With --template, creates a ticket programmatically by filling in the
    catalog item form via browser automation and submitting it.

    Examples:
        progress-servicenow ticket create
        progress-servicenow ticket create --template development_cloud_issue --field product=Azure --field description="Request to create Document Intelligence resource"
        progress-servicenow ticket create -T development_cloud_issue -F product=Azure -F impact=High
        progress-servicenow ticket create --template development_cloud_issue --field product=Azure --dry-run
    """
    try:
        if template is None:
            # No template: fall back to headed browser for manual creation
            if field:
                print_error("--field requires --template. Use --template to specify a catalog item.")
                raise typer.Exit(1)
            client = get_client()
            client.create_ticket()
            print_info(
                "Browser opened at ServiceNow Employee Center. "
                "Browse the catalog and submit your request in the browser window."
            )
            return

        # Programmatic creation via template
        data = _load_template()
        catalog_items = data["catalog_items"]

        if template not in catalog_items:
            print_error(f"Unknown template key: '{template}'")
            print_info("Available keys:")
            for k in sorted(catalog_items.keys()):
                print_info(f"  {k}")
            raise typer.Exit(1)

        template_data = catalog_items[template]
        template_fields = template_data.get("fields", {})

        if not template_fields:
            print_error(
                f"Template '{template}' has no documented fields. "
                "This catalog item may require manual creation."
            )
            raise typer.Exit(1)

        # Parse field key=value pairs
        field_values = {}
        if field:
            for f in field:
                if "=" not in f:
                    print_error(
                        f"Invalid field format: '{f}'. "
                        "Expected key=value (e.g., product=Azure)."
                    )
                    raise typer.Exit(1)
                key, value = f.split("=", 1)
                key = key.strip()
                value = value.strip()
                if key not in template_fields:
                    print_error(f"Unknown field '{key}' for template '{template}'.")
                    print_info(
                        f"Available fields: {', '.join(sorted(template_fields.keys()))}"
                    )
                    raise typer.Exit(1)
                field_values[key] = value

        # Validate required fields
        missing_required = []
        for fkey, fdef in template_fields.items():
            if fdef.get("required") and fkey not in field_values:
                # Skip if the field has a default value
                if fdef.get("default") is not None:
                    continue
                missing_required.append(fkey)

        if missing_required:
            print_error("Missing required fields:")
            for fkey in missing_required:
                fdef = template_fields[fkey]
                print_error(f"  --field {fkey}=<value>  ({fdef.get('label', fkey)})")
            raise typer.Exit(1)

        if dry_run:
            print_success("Validation passed. Fields that would be submitted:")
            rows = []
            for fkey, value in field_values.items():
                fdef = template_fields[fkey]
                rows.append({
                    "field": fkey,
                    "label": fdef.get("label", ""),
                    "type": fdef.get("type", ""),
                    "value": value,
                })
            print_table(
                rows,
                ["field", "label", "type", "value"],
                ["Field", "Label", "Type", "Value"],
            )
            return

        # Submit (or draft) the ticket
        client = get_client()
        ritm = client.create_ticket_from_template(
            template_key=template,
            template_data=template_data,
            field_values=field_values,
            draft=draft,
        )

        if draft:
            if ritm and ritm != "DRAFT_SAVED":
                print_success(f"Draft saved: {ritm}")
                print_json({"number": ritm, "template": template, "status": "draft", "fields": field_values})
            else:
                print_success("Draft saved successfully.")
                print_json({"template": template, "status": "draft", "fields": field_values})
        else:
            print_success(f"Ticket created: {ritm}")
            print_json({"number": ritm, "template": template, "fields": field_values})

        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))
