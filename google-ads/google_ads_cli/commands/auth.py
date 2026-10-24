"""Shared Google Ads authentication commands."""
from cli_tools_shared.auth_commands import create_auth_app
from ..config import get_config

app = create_auth_app(get_config, tool_name="google-ads")

import typer
from cli_tools_shared.config import read_cli_tool_secret
from cli_tools_shared.exceptions import CredentialError
from cli_tools_shared.output import command, print_json

client_app = typer.Typer(help="Select existing OAuth app credentials from the CLI-tools secret manager.", no_args_is_help=True)


@client_app.command("import")
@command
def import_client(
    client_id_secret: str = typer.Option(..., "--client-id-secret", help="Existing secret-manager name for OAuth client ID"),
    client_secret_secret: str = typer.Option(..., "--client-secret-secret", help="Existing secret-manager name for OAuth client secret"),
    profile: str = typer.Option("default", "--profile", help="Target Google Ads profile"),
):
    """Copy explicitly named OAuth app secrets; clear prior Ads tokens; never import another tool's tokens."""
    client_id = read_cli_tool_secret(client_id_secret)
    client_secret = read_cli_tool_secret(client_secret_secret)
    if not client_id or not client_secret:
        raise CredentialError("Both named OAuth client secrets must exist in the CLI-tools secret manager.")
    config = get_config(profile=profile)
    config.save_credentials(CLIENT_ID=client_id, CLIENT_SECRET=client_secret)
    config.clear_ephemeral()
    print_json({"profile": profile, "client_credentials_saved": True, "oauth_consent_required": True})


app.add_typer(client_app, name="client")
