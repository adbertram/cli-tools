"""Authentication commands for Cliclick CLI wrapper.

cliclick is a local tool that requires no authentication.
These commands check CLI availability and macOS Accessibility permissions.
"""
import typer
from ..config import get_config
from ..client import CliclickClient, ClientError
from cli_tools_shared.output import print_json, print_table, print_success, print_error, print_info, handle_error

app = typer.Typer(help="Check cliclick availability and permissions", no_args_is_help=True)


@app.command("login")
def auth_login(
    force: bool = typer.Option(False, "--force", "-F", help="Re-verify permissions (ignored, kept for compatibility)"),
):
    """
    Verify cliclick availability and permissions.

    cliclick is a local tool with no authentication. This command verifies
    that cliclick is installed and has macOS Accessibility permissions.

    Example:
        cliclick auth login
        cliclick auth login --force  # Re-check permissions
    """
    try:
        # Create client without availability check to get detailed status
        client = CliclickClient(skip_availability_check=True)
        result = client.auth_login(force=force)

        if result["success"]:
            print_success(result.get("message", "cliclick is ready"))
        else:
            print_error(result.get("message", "cliclick not ready"))
            raise typer.Exit(2)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("logout")
def auth_logout():
    """
    No-op for cliclick (local tool with no authentication).

    cliclick is a local tool with no session to clear.
    """
    try:
        client = CliclickClient(skip_availability_check=True)
        result = client.auth_logout()

        print_success(result.get("message", "No authentication to clear"))

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("status")
def auth_status(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Check cliclick availability and Accessibility permissions.

    Always returns exit code 0 with machine-readable status. A false
    authenticated value means cliclick is missing or Accessibility permissions
    are not granted.

    Example:
        cliclick auth status
        cliclick auth status --table
    """
    try:
        config = get_config()

        # First check if CLI is available
        if not config.is_cli_available():
            status_data = {
                "authenticated": False,
                "cli_available": False,
                "cli_path": None,
                "version": None,
                "accessibility_permissions": False,
                "message": "cliclick not found. Install with: brew install cliclick",
            }
            if table:
                rows = [
                    {"setting": "CLI Available", "value": "No"},
                    {"setting": "Authenticated", "value": "No"},
                    {"setting": "Message", "value": status_data["message"]},
                ]
                print_table(rows, ["setting", "value"], ["Setting", "Value"])
            else:
                print_json(status_data)
            return

        # Check auth status via client
        client = CliclickClient(skip_availability_check=True)
        status_data = client.auth_status()

        if table:
            rows = [
                {"setting": "Authenticated", "value": "Yes" if status_data["authenticated"] else "No"},
                {"setting": "CLI Available", "value": "Yes" if status_data.get("cli_available") else "No"},
                {"setting": "CLI Path", "value": status_data.get("cli_path") or "N/A"},
                {"setting": "Version", "value": status_data.get("version") or "Unknown"},
                {"setting": "Accessibility", "value": "Yes" if status_data.get("accessibility_permissions") else "No"},
            ]
            if status_data.get("message") and not status_data["authenticated"]:
                rows.append({"setting": "Message", "value": status_data["message"][:60]})
            print_table(rows, ["setting", "value"], ["Setting", "Value"])
        else:
            print_json(status_data)

    except typer.Exit:
        raise
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))
