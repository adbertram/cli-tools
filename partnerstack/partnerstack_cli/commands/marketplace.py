"""Marketplace (program discovery) commands for PartnerStack CLI."""
COMMAND_CREDENTIALS = {
    "list": ["api_key"],
    "get": ["api_key"],
}

from typing import List, Optional

import typer

from ..client import get_client
from cli_tools_shared.output import handle_error, print_json, print_table

from ._common import extract_fields, model_to_dict, parse_properties


app = typer.Typer(help="Browse PartnerStack marketplace programs (discovery)", no_args_is_help=True)


@app.command("list")
def marketplace_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(10, "--limit", "-l", min=1, max=250, help="Maximum programs to return"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help=(
            "API filter, e.g. category:eq:artificial-intelligence, "
            "created_at:gte:1711034344078, or created_at:lte:1748902440427"
        ),
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include, with dot-notation support",
    ),
    starting_after: Optional[str] = typer.Option(None, "--starting-after", help="Pagination cursor"),
    ending_before: Optional[str] = typer.Option(None, "--ending-before", help="Pagination cursor"),
):
    """List marketplace-listed programs (programs the partner has not necessarily joined)."""
    try:
        client = get_client()
        programs = client.list_marketplace_programs(
            limit=limit,
            filters=filter,
            starting_after=starting_after,
            ending_before=ending_before,
        )

        if properties:
            fields = parse_properties(properties)
            programs = extract_fields(programs, fields)

        if table:
            if properties:
                columns = parse_properties(properties)
                print_table(programs, columns, columns)
            else:
                columns = ["key", "name", "category", "website"]
                rows = extract_fields(programs, columns)
                print_table(rows, columns, ["Key", "Name", "Category", "Website"])
        else:
            print_json(programs)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def marketplace_get(
    company_key: str = typer.Argument(..., help="Marketplace program company_key"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include, with dot-notation support",
    ),
):
    """Retrieve a single marketplace program by company_key."""
    try:
        client = get_client()
        program = client.get_marketplace_program(company_key)

        if properties:
            fields = parse_properties(properties)
            program_output = extract_fields([program], fields)[0]
        else:
            program_output = program

        if table:
            if properties:
                columns = parse_properties(properties)
                print_table([program_output], columns, columns)
            else:
                program_dict = model_to_dict(program_output)
                rows = [{"field": key, "value": value} for key, value in program_dict.items()]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(program_output)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))

