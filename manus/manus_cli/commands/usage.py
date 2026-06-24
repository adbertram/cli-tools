"""Usage commands for Manus CLI."""
import typer

from ..client import ClientError, get_client
from ..output import handle_error, print_json, print_table

app = typer.Typer(help="Inspect Manus credit usage", no_args_is_help=True)


@app.command("available-credits")
def usage_available_credits(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table."),
):
    """Get current available Manus credits."""
    try:
        data = get_client().available_credits()
        if table:
            print_table([data])
        else:
            print_json(data)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
