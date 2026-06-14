"""System permission commands for iMessage CLI."""
import typer

from cli_tools_shared.output import handle_error, print_json, print_success, print_table

from ..client import get_client

app = typer.Typer(help="Manage system permissions", no_args_is_help=True)

STATUS_COLUMNS = [
    "authenticated",
    "messages_db_accessible",
    "messages_app_available",
    "contacts_accessible",
    "macos_version",
]
STATUS_HEADERS = [
    "Authenticated",
    "Messages DB",
    "Messages App",
    "Contacts",
    "macOS",
]


def _to_dict(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value)


def _status_payload(status_dict):
    authenticated = bool(status_dict["authenticated"])
    api_test = (
        "passed"
        if authenticated
        else "failed: Messages database is not accessible through system permissions"
    )
    return {
        **status_dict,
        "profiles": [
            {
                "name": "default",
                "auth_type": "system_permissions",
                "active": True,
                "authenticated": authenticated,
                "credential_types": {
                    "custom": {
                        "credentials_saved": True,
                        "authenticated": authenticated,
                        "api_test": api_test,
                        "messages_app_available": bool(
                            status_dict["messages_app_available"]
                        ),
                        "messages_db_accessible": bool(
                            status_dict["messages_db_accessible"]
                        ),
                        "contacts_accessible": bool(
                            status_dict["contacts_accessible"]
                        ),
                    }
                },
            }
        ],
    }


@app.command("status")
def auth_status(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Check system permissions and accessibility."""
    try:
        status = get_client().auth_status()
        status_dict = _to_dict(status)
        if table:
            print_table([status_dict], STATUS_COLUMNS, STATUS_HEADERS)
        else:
            print_json(_status_payload(status_dict))
        if not status_dict["authenticated"]:
            raise typer.Exit(2)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("login")
def auth_login(
    force: bool = typer.Option(False, "--force", "-F", help="Re-open System Settings"),
):
    """Open System Settings to grant permissions."""
    try:
        result = get_client().auth_login(force=force)
        print_json(result)
        if result.get("success"):
            print_success(result.get("message", "System Settings opened."))
        else:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("logout")
def auth_logout():
    """Clear iMessage CLI auth state."""
    try:
        result = get_client().auth_logout()
        print_json(result)
        if result.get("success"):
            print_success(result.get("message", "No session to clear."))
        else:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))
