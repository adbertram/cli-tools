"""Account balance."""
COMMAND_CREDENTIALS = {
    "get": ["custom"],
}

from typing import Optional

import typer
from cli_tools_shared.output import command

from ._common import DEMO_OPTION, ENV_OPTION, PROPERTIES_OPTION, TABLE_OPTION, emit_record, open_client

app = typer.Typer(help="Account balance and portfolio value", no_args_is_help=True)


@app.command("get")
@command
def balance_get(
    table: bool = TABLE_OPTION,
    properties: Optional[str] = PROPERTIES_OPTION,
    env: Optional[str] = ENV_OPTION,
    demo: bool = DEMO_OPTION,
):
    """Get the available balance and portfolio value."""
    with open_client(env, demo, auth=True) as client:
        emit_record(client.balance(), table, properties)
