"""Airtable schema-field commands scoped to the CourseCraft base."""
COMMAND_CREDENTIALS = {"rename": ["custom"]}

import typer

from ..client import ClientError, get_client
from cli_tools_shared.output import command, print_error, print_json, print_success


app = typer.Typer(help="Manage CourseCraft Airtable schema fields", no_args_is_help=True)


@app.command("rename")
@command
def rename_field(
    table: str = typer.Argument(..., help="CourseCraft Airtable table name"),
    current_name: str = typer.Argument(..., help="Current Airtable field name"),
    new_name: str = typer.Argument(..., help="New Airtable field name"),
):
    """Rename one CourseCraft Airtable field and verify the schema read-back."""
    try:
        field = get_client().rename_field(table, current_name, new_name)
        print_success(
            f"Renamed {table}.{current_name} to {new_name} ({field['id']})"
        )
        print_json(field)
    except ClientError as exc:
        print_error(str(exc))
        raise typer.Exit(1)
