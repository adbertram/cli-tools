"""Authentication commands for CourseCraft CLI."""
import subprocess

import typer
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.output import print_error, print_info, print_success

from ..config import get_config


def _login_handler(config, force: bool):
    """Delegate interactive Airtable authentication to the Airtable CLI."""
    args = ["auth", "login"]
    if force:
        args.append("--force")

    print_info("Delegating authentication to the Airtable CLI...")
    try:
        result = subprocess.run(["airtable"] + args, timeout=300)
    except FileNotFoundError:
        print_error("airtable CLI not found. Install the airtable CLI first.")
        raise typer.Exit(1)
    except subprocess.TimeoutExpired:
        print_error("airtable auth login timed out")
        raise typer.Exit(1)

    if result.returncode != 0:
        raise typer.Exit(result.returncode)

    print_success("Airtable authentication configured for CourseCraft")


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="coursecraft",
    login_handler=_login_handler,
)
