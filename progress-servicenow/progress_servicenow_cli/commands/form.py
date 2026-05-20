"""Form introspection commands for Progress ServiceNow CLI.

Commands for discovering the live structure of a catalog item form and
probing its Select2-based lookup fields.  Use these when the offline
``ticket_template.json`` entry is empty or stale, or when you need to
find the exact value of a reference field (e.g., application name)
before creating a ticket.
"""
from typing import Optional

import typer

from ..client import get_client
from ..template_data import load_ticket_template
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import (
    print_json, print_table, handle_error, print_error, print_info,
)

app = typer.Typer(
    help="Inspect live catalog item forms (discover fields, search lookups)",
    no_args_is_help=True,
)

COMMAND_CREDENTIALS = {
    "inspect": ["browser_session"],
    "lookup": ["browser_session"],
}

def _load_template_data(template_key: str) -> dict:
    """Load a single catalog item template entry by key."""
    try:
        data = load_ticket_template()
    except FileNotFoundError as exc:
        raise typer.BadParameter(
            "ticket_template.json is missing from the installed package."
        ) from exc
    catalog_items = data["catalog_items"]
    if template_key not in catalog_items:
        print_error(f"Unknown template key: '{template_key}'")
        print_info("Available keys:")
        for k in sorted(catalog_items.keys()):
            print_info(f"  {k}")
        raise typer.Exit(1)
    return catalog_items[template_key]


@app.command("inspect")
def form_inspect(
    template: Optional[str] = typer.Option(
        None, "--template", "-T",
        help="Template key (e.g., 'request_application_assistance'). "
             "Mutually exclusive with --url.",
    ),
    url: Optional[str] = typer.Option(
        None, "--url", "-u",
        help="Direct catalog item form URL. Mutually exclusive with --template.",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Inspect the live fields on a catalog item form.

    Opens the form in the authenticated browser, reads the accessibility
    tree, and returns every form field as a JSON record with its label,
    type (dropdown/reference/textarea/checkbox/text), required flag, and
    a snake_case key suggestion suitable for ticket_template.json.

    Use this when a template's `fields: {}` block is empty or stale,
    or when you want to confirm the real field structure before creating
    a ticket.

    Examples:
        progress-servicenow ticket form inspect -T other_development_request
        progress-servicenow ticket form inspect -T request_application_assistance --table
        progress-servicenow ticket form inspect --url "https://progress1.service-now.com/esc?id=sc_cat_item&sys_id=69a04cbfdb02109086e95f77489619bf"
    """
    if bool(template) == bool(url):
        print_error("Provide exactly one of --template or --url.")
        raise typer.Exit(1)

    template_data = _load_template_data(template) if template else None

    try:
        client = get_client()
        fields = client.inspect_form(template_data=template_data, url=url)

        if not fields:
            print_info("No form fields found on the page.")
            client.close()
            return

        if table:
            print_table(
                fields,
                ["key_suggestion", "label", "type", "required"],
                ["Key", "Label", "Type", "Required"],
            )
        else:
            print_json(fields)

        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("lookup")
def form_lookup(
    field: str = typer.Option(
        ..., "--field", "-f",
        help="Exact label of the dropdown/reference field to search "
             "(e.g., 'Please select the application from the list').",
    ),
    search: str = typer.Option(
        ..., "--search", "-s",
        help="Search string to type into the lookup (e.g., 'Copilot').",
    ),
    template: Optional[str] = typer.Option(
        None, "--template", "-T",
        help="Template key. Mutually exclusive with --url.",
    ),
    url: Optional[str] = typer.Option(
        None, "--url", "-u",
        help="Direct catalog item form URL. Mutually exclusive with --template.",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Search a Select2/reference field on a catalog item form.

    Opens the form, clicks the named field, types the search string,
    and returns the matching option labels from the dropdown. Use this
    to find the exact value to pass to a reference field when creating
    a ticket (e.g., the exact application name in Request Application
    Assistance).

    Examples:
        progress-servicenow ticket form lookup \\
            -T request_application_assistance \\
            -f "Please select the application from the list" \\
            -s "Copilot"

        progress-servicenow ticket form lookup \\
            --url "https://progress1.service-now.com/esc?id=sc_cat_item&sys_id=69a04cbfdb02109086e95f77489619bf" \\
            -f "Please select the application from the list" \\
            -s "Microsoft" \\
            --table
    """
    if bool(template) == bool(url):
        print_error("Provide exactly one of --template or --url.")
        raise typer.Exit(1)

    template_data = _load_template_data(template) if template else None

    try:
        client = get_client()
        options = client.lookup_form_field(
            field_label=field,
            search=search,
            template_data=template_data,
            url=url,
        )

        if not options:
            print_info(f"No options matched '{search}' for field '{field}'.")
            client.close()
            return

        if table:
            rows = [{"option": o} for o in options]
            print_table(rows, ["option"], ["Option"])
        else:
            print_json(options)

        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))
