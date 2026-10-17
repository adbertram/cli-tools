"""Ticket commands for Progress ServiceNow CLI.

The base implementation is loaded from preserved bytecode. ``ticket create`` is
maintained as source below because:

* it called ``create_ticket_from_template`` through a patched client method
  whose signature had lost the ``template_data`` and ``draft`` parameters, so
  ``--draft`` always raised ``TypeError``; and
* ``--dry-run`` reported "Validation passed" for values the template could not
  verify. Values are now checked against the live option list the template
  carries, and every field states how it was validated.
"""

from typing import List, Optional

import typer
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import (
    handle_error,
    print_error,
    print_info,
    print_json,
    print_success,
    print_table,
)

from .._bytecode import load_module_bytecode

load_module_bytecode(__name__, globals())


def _validation_note(definition: dict, value: str) -> str:
    """Describe how a field value was checked, or say plainly that it was not."""
    options = definition.get("options")
    if options:
        if value not in options:
            raise ClientError(
                f"Value {value!r} is not a valid option for field "
                f"{definition.get('label')!r}. Valid options: {', '.join(options)}."
            )
        return "matched template option"
    field_type = definition.get("type")
    if field_type == "reference":
        return "NOT VERIFIED - reference lookup, resolved on the live form"
    return f"NOT VERIFIED - free-form {field_type} value"


def ticket_create(
    template: Optional[str] = typer.Option(
        None,
        "--template",
        "-T",
        help=(
            "Template key for programmatic creation (e.g., 'other_development_request'). "
            "Use 'ticket template list' to see all keys."
        ),
    ),
    field: Optional[List[str]] = typer.Option(
        None,
        "--field",
        "-F",
        help=(
            "Field key=value pair. Repeatable. Use 'ticket template fields <key>' to see "
            "available fields."
        ),
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Validate fields against the template without submitting."
    ),
    draft: bool = typer.Option(False, "--draft", help="Save as draft instead of submitting."),
    draft_name: Optional[str] = typer.Option(
        None,
        "--draft-name",
        help=(
            "Name for the saved draft. Draft names must be unique. Defaults to the name "
            "ServiceNow pre-fills in its 'Save draft' dialog."
        ),
    ),
):
    """
    Create a ServiceNow ticket.

    Without --template, opens a headed browser for manual ticket creation.

    With --template, creates a ticket programmatically by filling in the
    catalog item form via browser automation.

    Examples:
        progress-servicenow ticket create
        progress-servicenow ticket create -T other_development_request -F product=Sitefinity -F req_impact=Medium -F description="..." --dry-run
        progress-servicenow ticket create -T other_development_request -F product=Sitefinity -F req_impact=Medium -F description="..." --draft
    """
    if field and not template:
        print_error("--field requires --template. Use --template to specify a catalog item.")
        raise typer.Exit(1)

    if draft_name and not draft:
        print_error("--draft-name requires --draft.")
        raise typer.Exit(1)

    if not template:
        client = get_client()
        try:
            client.create_ticket()
        except ClientError as exc:
            handle_error(exc)
            raise typer.Exit(1)
        print_info(
            "Browser opened at ServiceNow Employee Center. Browse the catalog and submit "
            "your request in the browser window."
        )
        return

    catalog_items = _load_template()["catalog_items"]
    if template not in catalog_items:
        print_error(
            f"Unknown template key: {template!r}\n"
            "Available keys:\n" + "\n".join(f"  {key}" for key in sorted(catalog_items))
        )
        raise typer.Exit(1)

    template_data = catalog_items[template]
    fields = template_data.get("fields") or {}
    if not fields:
        print_error(
            f"Template {template!r} has no documented fields. Run "
            "'progress-servicenow ticket template refresh' to resync it from the live catalog."
        )
        raise typer.Exit(1)

    field_values = {}
    for pair in field or []:
        if "=" not in pair:
            print_error(
                f"Invalid field format: {pair!r}. Expected key=value (e.g., product=Sitefinity)."
            )
            raise typer.Exit(1)
        key, value = pair.split("=", 1)
        key = key.strip()
        if key not in fields:
            print_error(
                f"Unknown field {key!r} for template {template!r}.\n"
                f"Available fields: {', '.join(sorted(fields))}"
            )
            raise typer.Exit(1)
        field_values[key] = value

    missing = [
        key
        for key, definition in fields.items()
        if definition.get("required") and key not in field_values
    ]
    if missing:
        print_error(
            "Missing required fields:\n"
            + "\n".join(f"  --field {key}=<value>  ({fields[key].get('label')})" for key in missing)
        )
        raise typer.Exit(1)

    try:
        rows = [
            {
                "field": key,
                "label": fields[key].get("label", ""),
                "type": fields[key].get("type", ""),
                "value": value,
                "validation": _validation_note(fields[key], value),
            }
            for key, value in field_values.items()
        ]
    except ClientError as exc:
        handle_error(exc)
        raise typer.Exit(1)

    if dry_run:
        print_info("Validation passed. Fields that would be submitted:")
        print_table(
            rows,
            ["field", "label", "type", "value", "validation"],
            ["Field", "Label", "Type", "Value", "Validation"],
        )
        return

    client = get_client()
    try:
        result = client.create_ticket_from_template(
            template_key=template,
            template_data=template_data,
            field_values=field_values,
            draft=draft,
            draft_name=draft_name,
        )
    except ClientError as exc:
        handle_error(exc)
        raise typer.Exit(1)
    finally:
        client.close()

    if result.get("status") == "DRAFT_SAVED":
        print_success(f"Draft saved for template {template}.")
    else:
        print_success(f"Ticket created: {result.get('number')}")
    print_json(result)


for command_info in app.registered_commands:
    if command_info.name == "create":
        command_info.callback = ticket_create
