"""Authentication commands for FreshBooks CLI."""
import time
from urllib.parse import urlencode, urlparse, parse_qs

import requests
import typer
from playwright.sync_api import sync_playwright

from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.output import print_success, print_error, print_info

from ..config import get_config

# OAuth configuration
FRESHBOOKS_AUTH_URL = "https://my.freshbooks.com/service/auth/oauth/authorize"
FRESHBOOKS_TOKEN_URL = "https://api.freshbooks.com/auth/oauth/token"
DEFAULT_REDIRECT_URI = "https://localhost/callback"


def _get_auth_code_from_browser(auth_url: str, redirect_uri: str, timeout: int = 120) -> str:
    """Open browser, wait for OAuth redirect, extract auth code from URL."""
    captured_url = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, channel="chrome")
        page = browser.new_page()

        def on_request(request):
            nonlocal captured_url
            if request.url.startswith(redirect_uri):
                captured_url = request.url

        page.on("request", on_request)
        page.goto(auth_url)

        print_info("Waiting for authentication...")

        start = time.time()
        while time.time() - start < timeout:
            if captured_url:
                browser.close()
                return captured_url
            page.wait_for_timeout(500)

        browser.close()
        raise TimeoutError("Authentication timed out")


def _login_handler(config, _force: bool):
    """Authenticate with FreshBooks using the existing browser OAuth flow."""
    if not config.client_id or not config.client_secret:
        print_error("Missing CLIENT_ID or CLIENT_SECRET in .env")
        raise typer.Exit(1)

    redirect_uri = config.redirect_uri or DEFAULT_REDIRECT_URI
    auth_params = {
        "client_id": config.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
    }
    auth_url = f"{FRESHBOOKS_AUTH_URL}?{urlencode(auth_params)}"

    print_info("Opening browser for FreshBooks authentication...")
    callback_url = _get_auth_code_from_browser(auth_url, redirect_uri)

    params = parse_qs(urlparse(callback_url).query)
    if "error" in params:
        print_error(f"Authentication failed: {params.get('error_description', params['error'])[0]}")
        raise typer.Exit(1)
    if "code" not in params:
        print_error("No authorization code received.")
        raise typer.Exit(1)

    print_info("Exchanging code for tokens...")
    response = requests.post(
        FRESHBOOKS_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "code": params["code"][0],
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )

    if response.status_code != 200:
        print_error(f"Token exchange failed: {response.text}")
        raise typer.Exit(1)

    tokens = response.json()
    config.save_tokens(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_at=str(int(time.time()) + tokens.get("expires_in", 3600)),
    )
    print_success("Successfully authenticated with FreshBooks!")


app = create_auth_app(get_config, tool_name="freshbooks", login_handler=_login_handler)
