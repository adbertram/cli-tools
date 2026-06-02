"""Authentication commands for Kick CLI using Auth0 PKCE flow."""
import base64
import hashlib
import secrets
import urllib.parse
import webbrowser
from datetime import datetime
from typing import Optional

import requests
import typer

from cli_tools_shared.auth_commands import create_auth_app, _prompt_and_save
from cli_tools_shared.output import print_info, print_success, print_error

from ..config import get_config


# Use kick.co's actual redirect URI
REDIRECT_URI = "https://use.kick.co"


class AuthError(Exception):
    """Error during authorization flow."""
    pass


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code verifier and challenge."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return code_verifier, code_challenge


def extract_code_from_url(url: str) -> tuple[str, Optional[str]]:
    """Extract authorization code and state from callback URL."""
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)

    code = query.get("code", [None])[0]
    state = query.get("state", [None])[0]
    error = query.get("error_description", query.get("error", [None]))[0]

    if error:
        raise AuthError(f"Authorization failed: {error}")

    if not code:
        raise AuthError("No authorization code found in URL")

    return code, state


def exchange_code_for_tokens(config, code: str, code_verifier: str) -> dict:
    """Exchange authorization code for tokens."""
    url = f"{config.auth_url}/oauth/token"

    payload = {
        "grant_type": "authorization_code",
        "client_id": config.auth0_client_id,
        "code": code,
        "code_verifier": code_verifier,
        "redirect_uri": REDIRECT_URI,
    }

    response = requests.post(url, data=payload)

    if not response.ok:
        error_data = response.json()
        error_msg = error_data.get("error_description", error_data.get("error", response.text))
        raise AuthError(f"Token exchange failed: {error_msg}")

    return response.json()


def refresh_access_token(config) -> dict:
    """Refresh the access token using the refresh token."""
    if not config.refresh_token:
        raise AuthError("No refresh token available. Run 'kick auth login'.")

    url = f"{config.auth_url}/oauth/token"

    payload = {
        "grant_type": "refresh_token",
        "client_id": config.auth0_client_id,
        "refresh_token": config.refresh_token,
    }

    response = requests.post(url, data=payload)

    if not response.ok:
        error_data = response.json()
        error_msg = error_data.get("error_description", error_data.get("error", response.text))
        raise AuthError(f"Token refresh failed: {error_msg}")

    return response.json()


def _login_handler(config, force: bool):
    """Custom PKCE OAuth flow.

    create_auth_app handles prompt-based static credentials before this runs
    (none in this case — kick uses built-in Auth0 client_id).
    """
    print_info("Starting authorization flow...")

    code_verifier, code_challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(32)

    auth_params = {
        "response_type": "code",
        "client_id": config.auth0_client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": "openid profile email offline_access",
        "audience": config.auth0_audience,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    auth_url = f"{config.auth_url}/authorize?{urllib.parse.urlencode(auth_params)}"

    print_info("")
    print_info("=" * 60)
    print_info("  AUTHORIZATION REQUIRED")
    print_info("=" * 60)
    print_info("")
    print_info("  1. Sign in with your Kick account in the browser")
    print_info("  2. After signing in, COPY THE FULL URL from your browser")
    print_info("     (it will start with https://use.kick.co/?code=...)")
    print_info("  3. Paste the URL below")
    print_info("")
    print_info("=" * 60)
    print_info("")

    print_info("Opening browser...")
    webbrowser.open(auth_url)

    print_info("")

    _prompt_and_save(
        config,
        [("KICK_CALLBACK_URL", "URL from your browser", False)],
        skip_if_set=False,
    )
    callback_url = config._get("KICK_CALLBACK_URL")
    config._clear("KICK_CALLBACK_URL")

    try:
        code, received_state = extract_code_from_url(callback_url)
    except AuthError as e:
        print_error(str(e))
        raise typer.Exit(1)

    if received_state != state:
        print_error("State mismatch - possible security issue. Please try again.")
        raise typer.Exit(1)

    print_info("Exchanging authorization code for tokens...")

    try:
        token_data = exchange_code_for_tokens(config, code, code_verifier)
    except AuthError as e:
        print_error(str(e))
        raise typer.Exit(1)

    expires_at = str(datetime.now().timestamp() + token_data.get("expires_in", 86400))

    config.save_tokens(
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        expires_at=expires_at,
    )

    print_success("Successfully authenticated with Kick!")


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="kick",
    login_handler=_login_handler,
)
