"""Account commands for Easyship CLI."""
import typer

from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import handle_error, print_json, print_table

from ..client import get_client

COMMAND_CREDENTIALS = {
    "list": ["personal_access_token"],
    "get": ["personal_access_token"],
}

app = typer.Typer(help="Inspect the authenticated Easyship account", no_args_is_help=True)


def _item_to_rows(item) -> list[dict]:
    data = item.model_dump()
    return [{"field": key, "value": value} for key, value in data.items() if value is not None]


@app.command("list")
def account_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(1, "--limit", "-l", help="Maximum number of accounts to return"),
    filter: list[str] | None = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., email:eq:user@example.com, country_alpha2:eq:US)"),
    properties: str | None = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List the current authenticated Easyship account as a single-row collection."""
    try:
        if limit <= 0:
            raise typer.BadParameter("limit must be greater than 0")

        client = get_client()
        account = client.get_account()
        rows = [account.model_dump()]
        if filter:
            rows = apply_filters(rows, filter)
        if properties:
            fields = [field.strip() for field in properties.split(",")]
            rows = [{field: row.get(field) for field in fields} for row in rows]

        if table:
            columns = [field.strip() for field in properties.split(",")] if properties else sorted(rows[0].keys())
            print_table(rows, columns, [column.replace("_", " ").title() for column in columns])
        else:
            print_json(rows[:limit])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def account_get(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get the current Easyship account payload."""
    try:
        client = get_client()
        account = client.get_account()
        if table:
            print_table(_item_to_rows(account), ["field", "value"], ["Field", "Value"])
        else:
            print_json(account)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
