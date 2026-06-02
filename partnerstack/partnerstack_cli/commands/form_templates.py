"""Form-template commands for PartnerStack CLI."""
from typing import List, Optional

import typer

from ..client import AUTH_BASIC, get_client
from cli_tools_shared.output import handle_error, print_json, print_table

from ._common import extract_fields, model_to_dict, parse_properties


COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
}
COMMAND_AUTH_TYPES = {
    "list": AUTH_BASIC,
    "get": AUTH_BASIC,
}


app = typer.Typer(
    help="List PartnerStack form templates using Basic auth",
    no_args_is_help=True,
)


@app.command("list")
def form_templates_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(
        10, "--limit", "-l", min=1, max=250, help="Maximum form templates to return"
    ),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help=(
            "API filter. Supported equality filters: group:eq:<slug>, "
            "target_type:eq:<value>, mold_keys:eq:<value>; "
            "created_at and updated_at support gte/lte with epoch-ms values."
        ),
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include, with dot-notation support",
    ),
    starting_after: Optional[str] = typer.Option(
        None, "--starting-after", help="Pagination cursor"
    ),
    ending_before: Optional[str] = typer.Option(
        None, "--ending-before", help="Pagination cursor"
    ),
):
    """List application form templates from GET /api/v2/form-templates."""
    try:
        client = get_client(COMMAND_AUTH_TYPES["list"])
        templates = client.list_form_templates(
            limit=limit,
            filters=filter,
            starting_after=starting_after,
            ending_before=ending_before,
        )

        if properties:
            fields = parse_properties(properties)
            templates = extract_fields(templates, fields)

        if table:
            if properties:
                columns = parse_properties(properties)
                print_table(templates, columns, columns)
            else:
                columns = ["key", "name", "group", "target_type"]
                rows = extract_fields(templates, columns)
                print_table(rows, columns, ["Key", "Name", "Group", "Target Type"])
        else:
            print_json(templates)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def form_templates_get(
    form_template_key: str = typer.Argument(
        ..., help="Form template key (also exposed as 'id' on the model)"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include, with dot-notation support",
    ),
):
    """Get one form template by key."""
    try:
        client = get_client(COMMAND_AUTH_TYPES["get"])
        template = client.get_form_template(form_template_key)

        if properties:
            fields = parse_properties(properties)
            output = extract_fields([template], fields)[0]
        else:
            output = template

        if table:
            if properties:
                columns = parse_properties(properties)
                print_table([output], columns, columns)
            else:
                data = model_to_dict(output)
                rows = [{"field": k, "value": v} for k, v in data.items()]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(output)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
