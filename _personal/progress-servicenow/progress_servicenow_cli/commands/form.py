"""Form introspection commands for Progress ServiceNow CLI.

Commands for discovering the live structure of a catalog item form and probing
its Select2-based lookup fields. Use these when the offline
``ticket_template.json`` entry is empty or stale, or when you need to find the
exact value of a reference field (e.g., application name) before creating a
ticket.

Both commands resolve a template through its catalog item ``sys_id``, so they
never depend on scraping the Employee Center search page.
"""

import typer
from typing import Optional

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import command, handle_error, print_error, print_json, print_table

from ..client import get_client
from ..template_data import load_ticket_template

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
    catalog_items = load_ticket_template()["catalog_items"]
    if template_key not in catalog_items:
        print_error(
            f"Unknown template key: {template_key!r}\n"
            "Available keys:\n"
            + "\n".join(f"  {key}" for key in sorted(catalog_items))
        )
        raise typer.Exit(1)
    return catalog_items[template_key]


def _resolve_target(template: Optional[str], url: Optional[str]) -> dict:
    if (template is None) == (url is None):
        print_error("Provide exactly one of --template or --url.")
        raise typer.Exit(1)
    if template is not None:
        return {"template_data": _load_template_data(template)}
    return {"url": url}


@app.command("inspect")
@command
def form_inspect(
    template: Optional[str] = typer.Option(
        None,
        "--template",
        "-T",
        help="Template key (e.g., 'other_development_request'). Mutually exclusive with --url.",
    ),
    url: Optional[str] = typer.Option(
        None,
        "--url",
        "-u",
        help="Direct catalog item form URL. Mutually exclusive with --template.",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Inspect the live fields on a catalog item form.

    Opens the form in the authenticated browser, reads the accessibility tree,
    and returns every form field as a JSON record with its label, type
    (dropdown/reference/textarea/checkbox/text), required flag, and a
    snake_case key suggestion suitable for ticket_template.json.

    Examples:
        progress-servicenow ticket form inspect -T other_development_request
        progress-servicenow ticket form inspect -T purchase_request --table
        progress-servicenow ticket form inspect --url "https://progress1.service-now.com/esc?id=sc_cat_item&sys_id=838c9810dbe5db0408f33a1b7c961930"
    """
    target = _resolve_target(template, url)
    client = get_client()
    try:
        fields = client.inspect_form(**target)
    except ClientError as exc:
        handle_error(exc)
        raise typer.Exit(1)
    finally:
        client.close()

    if not fields:
        print_error(
            "No form fields were found on the catalog item form for "
            f"{template or url!r}. The form did not render, or the page shape changed."
        )
        raise typer.Exit(1)

    if table:
        columns = ["label", "type", "required", "key_suggestion"]
        print_table(fields, columns, ["Label", "Type", "Required", "Key Suggestion"])
    else:
        print_json(fields)


@app.command("lookup")
@command
def form_lookup(
    field: str = typer.Option(
        ...,
        "--field",
        "-f",
        help=(
            "Exact label of the dropdown/reference field to search "
            "(e.g., 'Please select the application from the list')."
        ),
    ),
    search: str = typer.Option(
        ..., "--search", "-s", help="Search string to type into the lookup (e.g., 'Copilot')."
    ),
    template: Optional[str] = typer.Option(
        None, "--template", "-T", help="Template key. Mutually exclusive with --url."
    ),
    url: Optional[str] = typer.Option(
        None,
        "--url",
        "-u",
        help="Direct catalog item form URL. Mutually exclusive with --template.",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Search a Select2/reference field on a catalog item form.

    Opens the form, clicks the named field, types the search string, and
    returns the matching option labels from the dropdown.

    Examples:
        progress-servicenow ticket form lookup -T purchase_request -f "Cost Center" -s "IT"
    """
    target = _resolve_target(template, url)
    client = get_client()
    try:
        options = client.lookup_form_field(field, search, **target)
    except ClientError as exc:
        handle_error(exc)
        raise typer.Exit(1)
    finally:
        client.close()

    if not options:
        print_error(f"No options matched {search!r} for field {field!r}.")
        raise typer.Exit(1)

    rows = [{"option": option} for option in options]
    if table:
        print_table(rows, ["option"], ["Option"])
    else:
        print_json(rows)
