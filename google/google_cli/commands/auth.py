"""Authentication commands for Google CLI."""
from cli_tools_shared.auth_commands import create_auth_app
from ..config import get_config
from ..client import SCOPES, reset_client
from cli_tools_shared.output import print_error


def _print_setup_instructions():
    """Print OAuth setup instructions before prompting."""
    from cli_tools_shared.output import print_info
    print_info(
        "To get your OAuth credentials:\n"
        "  1. Go to https://console.cloud.google.com/apis/credentials\n"
        "  2. Click 'Create Credentials' > 'OAuth client ID'\n"
        "  3. Application type: 'Desktop app' (NOT 'Web application')\n"
        "     Desktop app type auto-allows http://localhost redirect URIs.\n"
        "  4. Copy the Client ID and Client Secret shown after creation"
    )


def _google_login_handler(config, force: bool):
    """Handle Google OAuth2 flow using in-memory OAuth client config."""
    import typer
    from google_auth_oauthlib.flow import InstalledAppFlow

    # Force clears the existing OAuth token. Static client credentials are
    # collected by cli_tools_shared before this handler runs.
    token_path = config.token_path_obj
    if force and token_path.exists():
        token_path.unlink()
        reset_client()

    try:
        client_config = config.oauth_client_config()
    except ValueError:
        print_error(
            "OAuth credentials not found. Run 'google auth login' to be prompted."
        )
        _print_setup_instructions()
        raise typer.Exit(2)

    # Run OAuth flow
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)

    # Save token to profile data dir
    with open(config.token_path, "w") as f:
        f.write(creds.to_json())


def _google_test_handler(config) -> dict:
    """Test Google authentication by calling Drive API."""
    from ..client import get_client
    from googleapiclient.errors import HttpError
    try:
        client = get_client(profile=config.get_active_profile_name())
        service = client.get_drive_service()
        about = service.about().get(fields="user").execute()
        email = about.get("user", {}).get("emailAddress", "unknown")
        return {"api_test": "passed", "email": email}
    except HttpError as e:
        return {"api_test": f"failed: {e}"}


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="google",
    login_handler=_google_login_handler,
    test_handler=_google_test_handler,
)
