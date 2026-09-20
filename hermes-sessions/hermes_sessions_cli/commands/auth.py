"""Read-only local-access status for the Hermes state store.

hermes-sessions reads the Hermes state store on this host and owns no remote
credential, so the only auth command it exposes is `status`: a report of
whether that store is readable.
"""
from typing import Optional

import typer
from cli_tools_shared.output import command, print_json, print_table

from ..config import get_config

app = typer.Typer(
    help="Report local Hermes state access (read-only)",
    no_args_is_help=True,
)


def _status_payload(profile: Optional[str] = None) -> dict:
    """Return the shared profile-shaped contract without creating a profile."""
    if profile not in (None, "default"):
        raise typer.BadParameter(
            "hermes-sessions has only the synthetic read-only profile 'default'",
            param_hint="--profile",
        )
    status = get_config(profile=profile).test_connection()
    authenticated = bool(status["state_db_readable"])
    custom = {
        "credentials_saved": True,
        "authenticated": authenticated,
        **status,
    }
    return {
        "profiles": [
            {
                "name": "default",
                "auth_type": "default",
                "active": True,
                "authenticated": authenticated,
                "credential_types": {"custom": custom},
            }
        ]
    }


@app.command("status")
@command
def auth_status(
    profile: Optional[str] = typer.Option(
        None, "--profile", "-p", help="Profile name to check (default only)"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Check local Hermes state access without writing configuration."""
    payload = _status_payload(profile)
    entry = payload["profiles"][0]
    if table:
        custom = entry["credential_types"]["custom"]
        row = {
            "name": entry["name"],
            "active": entry["active"],
            "authenticated": entry["authenticated"],
            "state_db": custom["state_db"],
            "api_test": custom["api_test"],
        }
        print_table(
            [row],
            ["name", "active", "authenticated", "state_db", "api_test"],
            ["Profile", "Active", "Authenticated", "State DB", "Test"],
            max_columns=0,
        )
    else:
        print_json(payload)
    if not entry["authenticated"]:
        raise typer.Exit(2)
