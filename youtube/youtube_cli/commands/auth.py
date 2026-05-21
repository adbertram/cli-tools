"""Authentication commands for YouTube CLI (OAuth for YouTube Data API)."""
import json

import typer
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.output import print_error, print_info

from ..api_client import SCOPES, reset_api_client
from ..config import YOUTUBE_PROFILE_AUTH_TYPE, get_config


def _print_setup_instructions():
    """Print OAuth setup instructions before prompting."""
    print_info(
        "To get your OAuth credentials:\n"
        "  1. Go to https://console.cloud.google.com/apis/credentials\n"
        "  2. Click 'Create Credentials' > 'OAuth client ID'\n"
        "  3. Application type: 'Desktop app' (NOT 'Web application')\n"
        "     Desktop app type auto-allows http://localhost redirect URIs.\n"
        "  4. Enable the YouTube Data API v3 in the same Cloud project\n"
        "     (https://console.cloud.google.com/apis/library/youtube.googleapis.com)\n"
        "  5. Copy the Client ID and Client Secret shown after creation"
    )


def _youtube_login_handler(config, force: bool):
    """Handle YouTube OAuth2 flow — builds credentials.json from prompted ID/secret."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    config._set(config.PROFILE_AUTH_TYPE_FIELD, YOUTUBE_PROFILE_AUTH_TYPE)

    # Force clears the existing OAuth token. Static client credentials are
    # collected by cli_tools_shared before this handler runs.
    token_path = config.token_path_obj
    if force and token_path.exists():
        token_path.unlink()
        reset_api_client()

    client_id = config._get("CLIENT_ID")
    client_secret = config._get("CLIENT_SECRET")

    if not client_id or not client_secret:
        print_error(
            "OAuth credentials not found. Run 'youtube auth login' to be prompted."
        )
        _print_setup_instructions()
        raise typer.Exit(2)

    creds_data = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": ["http://localhost", "urn:ietf:wg:oauth:2.0:oob"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    creds_path = config.get_profile_data_dir() / "credentials.json"
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    with open(creds_path, "w") as f:
        json.dump(creds_data, f, indent=2)

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)

    with open(config.token_path, "w") as f:
        f.write(creds.to_json())


def _youtube_test_handler(config) -> dict:
    """Test YouTube authentication by fetching the user's channel."""
    from googleapiclient.errors import HttpError

    from ..api_client import get_api_client

    try:
        client = get_api_client(profile=config.get_active_profile_name())
        service = client.get_youtube_service()
        response = service.channels().list(part="snippet", mine=True).execute()
        items = response.get("items", [])
        if not items:
            return {"api_test": "failed: no channel found for authenticated user"}
        channel = items[0]
        return {
            "api_test": "passed",
            "channel_id": channel["id"],
            "channel_title": channel["snippet"]["title"],
        }
    except HttpError as e:
        return {"api_test": f"failed: {e}"}


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="youtube",
    login_handler=_youtube_login_handler,
    test_handler=_youtube_test_handler,
)
