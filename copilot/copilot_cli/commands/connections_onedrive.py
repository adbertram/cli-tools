"""OneDrive for Business diagnostics subcommands."""
import typer
import httpx
from typing import Optional

from ..client import get_access_token, ClientError
from cli_tools_shared.output import print_json, handle_error


app = typer.Typer(help="OneDrive for Business diagnostics")

COMMAND_CREDENTIALS = {
    "check-drive": ["custom"],
}

# Azure CLI public client ID — used for ROPC token acquisition
_AZ_CLI_CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"


def _acquire_token_ropc(tenant_id: str, username: str, password: str) -> str:
    """Acquire a Graph token via ROPC flow, authenticating as the user."""
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            token_url,
            data={
                "grant_type": "password",
                "client_id": _AZ_CLI_CLIENT_ID,
                "scope": "https://graph.microsoft.com/.default",
                "username": username,
                "password": password,
            },
        )
    if response.status_code != 200:
        raise ClientError(
            f"ROPC token acquisition failed: {response.status_code} {response.text[:300]}"
        )
    return response.json()["access_token"]


@app.command("check-drive")
def check_drive(
    user_principal_name: str = typer.Argument(
        ...,
        help="User principal name (e.g., user@domain.com)",
    ),
    password: Optional[str] = typer.Option(
        None,
        "--password",
        "-p",
        help="M365 password for the user (uses ROPC to authenticate as the user)",
        envvar="M365_PASSWORD",
    ),
    tenant_id: Optional[str] = typer.Option(
        None,
        "--tenant-id",
        "-t",
        help="Azure AD tenant ID (required with --password)",
        envvar="AZURE_TENANT_ID",
    ),
):
    """
    Check if a user's OneDrive for Business has been provisioned.

    By default, uses the current az CLI login context. If --password and
    --tenant-id are provided, authenticates as the user via ROPC instead.

    - HTTP 200: OneDrive is provisioned (prints drive info, exit 0)
    - HTTP 404: OneDrive is NOT provisioned (prints remediation, exit 1)
    - Other errors: prints error details, exit 1

    Examples:
        copilot connections onedrive check-drive user@domain.com
        copilot connections onedrive check-drive user@domain.com -p 'secret' -t <tenant-id>
    """
    try:
        # Determine auth method
        if password and tenant_id:
            graph_token = _acquire_token_ropc(tenant_id, user_principal_name, password)
            graph_url = "https://graph.microsoft.com/v1.0/me/drive"
        elif password and not tenant_id:
            raise ClientError("--tenant-id is required when using --password")
        else:
            graph_token = get_access_token("https://graph.microsoft.com")
            graph_url = f"https://graph.microsoft.com/v1.0/users/{user_principal_name}/drive"

        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                graph_url,
                headers={"Authorization": f"Bearer {graph_token}"},
            )

        if response.status_code == 200:
            drive = response.json()
            result = {
                "provisioned": True,
                "drive_id": drive.get("id", ""),
                "drive_type": drive.get("driveType", ""),
                "quota": drive.get("quota", {}),
            }
            print_json(result)
        elif response.status_code == 404:
            typer.echo(
                f"OneDrive for Business is NOT provisioned for {user_principal_name}.\n"
                "\n"
                "Remediation:\n"
                "  1. Assign a OneDrive for Business license (e.g., Microsoft 365 E3/E5)\n"
                "  2. Open https://admin.microsoft.com → Users → Active users\n"
                "  3. Select the user → Licenses and apps → assign a license with OneDrive\n"
                "  4. Wait up to 24 hours for provisioning (or visit https://portal.office.com\n"
                "     as the user to trigger immediate provisioning)\n"
                "  5. Re-run this check to confirm provisioning",
                err=True,
            )
            raise typer.Exit(1)
        else:
            raise ClientError(
                f"Graph API returned {response.status_code} for {user_principal_name}: "
                f"{response.text[:300]}"
            )

    except typer.Exit:
        raise
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)
