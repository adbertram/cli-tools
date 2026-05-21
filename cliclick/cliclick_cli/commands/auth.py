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
        client = CliclickClient(skip_availability_check=True)
        raw_status = client.auth_status()
        authenticated = bool(raw_status["authenticated"])
        profile_name = config.profile or "default"
        status_data = {
            "profiles": [
                {
                    "name": profile_name,
                    "auth_type": "default",
                    "active": True,
                    "authenticated": authenticated,
                    "credential_types": {
                        "custom": {
                            "credentials_saved": True,
                            "authenticated": authenticated,
                            "cli_available": bool(raw_status.get("cli_available")),
                            "cli_path": raw_status.get("cli_path"),
                            "version": raw_status.get("version"),
                            "accessibility_permissions": bool(raw_status.get("accessibility_permissions")),
                            "message": raw_status.get("message"),
                        }
                    },
                }
            ]
        }

        if table:
            profile = status_data["profiles"][0]
            custom = profile["credential_types"]["custom"]
            rows = [
                {"setting": "Profile", "value": profile["name"]},
                {"setting": "Authenticated", "value": "Yes" if profile["authenticated"] else "No"},
                {"setting": "CLI Available", "value": "Yes" if custom["cli_available"] else "No"},
                {"setting": "CLI Path", "value": custom["cli_path"] or "N/A"},
                {"setting": "Version", "value": custom["version"] or "Unknown"},
                {"setting": "Accessibility", "value": "Yes" if custom["accessibility_permissions"] else "No"},
            ]
            if custom.get("message") and not profile["authenticated"]:
                rows.append({"setting": "Message", "value": custom["message"][:60]})
            print_table(rows, ["setting", "value"], ["Setting", "Value"])
        else:
            print_json(status_data)

    except typer.Exit:
        raise
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))
