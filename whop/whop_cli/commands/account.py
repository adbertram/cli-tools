from typing import List, Optional
import typer
from cli_tools_shared.output import command
from ..render import read, render

app=typer.Typer(no_args_is_help=True)
COMMAND_CREDENTIALS={'get': ['browser_session']}

@app.command("get")
@command
def get(table: bool=typer.Option(False,"--table","-t")):
    """Get the current Whop participant account and observed account balances."""
    render(read("account"),table)
