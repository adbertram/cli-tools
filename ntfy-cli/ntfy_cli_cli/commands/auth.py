"""Read-only local readiness commands."""

import typer
from cli_tools_shared.output import command, print_json

from ..client import get_client


app = typer.Typer(
    help="Inspect upstream readiness; credentials remain upstream-owned",
    no_args_is_help=True,
)


@app.command("status")
@command
def status() -> None:
    """Report local executable readiness without mutating credentials."""
    client = get_client()
    available = client.config.is_cli_available()
    version = client.run(("--version",), timeout=10).stdout.strip() if available else None
    print_json({"profiles": [{"name": "default", "auth_type": "upstream", "active": True, "authenticated": available, "credential_types": {"custom": {"credentials_saved": available, "authenticated": available}}, "readiness": {"upstream_available": available, "upstream_version": version}}]})
