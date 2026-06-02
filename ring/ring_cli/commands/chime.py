"""Chime commands — play test sounds on Ring chimes."""
import typer

from cli_tools_shared.output import handle_error, print_output

from ..client import get_client


app = typer.Typer(help="Control Ring chime devices", no_args_is_help=True)


COMMAND_CREDENTIALS = {
    "test": ["username_password"],
}


@app.command("test")
def chime_test(
    device: str = typer.Option(..., "--device", "-d", help="Chime device name or numeric ID"),
    kind: str = typer.Option(
        "ding",
        "--kind",
        "-k",
        help="Sound to play: 'ding' or 'motion'",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Play a test sound on a chime."""
    try:
        client = get_client()
        result = client.chime_test(identifier=device, kind=kind)
        print_output(result, table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
