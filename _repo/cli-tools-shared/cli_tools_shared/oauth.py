"""Built-in OAuth 2.0 Authorization Code flow handler.

Provides a complete login handler that works with OAUTH_* class variables
on BaseConfig subclasses. Supports PKCE, Basic/body/none token auth, and
manual code capture from the system browser.
"""

import base64
import hashlib
import html
import secrets
import webbrowser
from datetime import datetime
from urllib.parse import urlencode, urlparse, parse_qs, unquote

import requests
import typer

from .output import print_success, print_error, print_info

DEFAULT_TOKEN_EXPIRY = 7200


def parse_and_save_tokens(config, token_response: dict, fallback_refresh: str = None) -> int:
    """Parse OAuth token response and save tokens to config.

    Args:
        config: BaseConfig instance.
        token_response: Parsed JSON response from token endpoint.
        fallback_refresh: Refresh token to use if response doesn't include one.

    Returns:
        expires_in value (seconds).
    """
    access_token = token_response.get("access_token")
    refresh_token = token_response.get("refresh_token", fallback_refresh)
    expires_in = token_response.get("expires_in", DEFAULT_TOKEN_EXPIRY)
    expires_at = str(datetime.now().timestamp() + expires_in)
    config.save_tokens(access_token, refresh_token, expires_at)
    return expires_in


def generate_pkce_pair() -> tuple:
    """Generate PKCE code_verifier and code_challenge (S256).

    Returns:
        (code_verifier, code_challenge) tuple.
    """
    code_verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def extract_code_from_input(user_input: str) -> str:
    """Extract authorization code from user input.

    Accepts either:
    - Direct code: v^1.1#i^1#...
    - Full redirect URL: https://example.com/?code=v%5E1.1%23...

    Returns the URL-decoded authorization code.
    """
    user_input = user_input.strip()

    if user_input.startswith("http://") or user_input.startswith("https://"):
        parsed = urlparse(user_input)
        query_params = parse_qs(parsed.query)

        if "error" in query_params:
            error = query_params["error"][0]
            description = html.unescape(query_params.get("error_description", [""])[0])
            if description:
                raise ValueError(f"OAuth authorization failed: {error}: {description}")
            raise ValueError(f"OAuth authorization failed: {error}")

        if "code" not in query_params:
            raise ValueError("No 'code' parameter found in URL")

        code = query_params["code"][0]
        return unquote(code)

    return unquote(user_input)


def build_token_auth_headers(config) -> tuple:
    """Build headers and extra form data for token exchange based on OAUTH_TOKEN_AUTH.

    Returns:
        (headers_dict, extra_data_dict) tuple.
    """
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    extra_data = {}

    auth_method = config.OAUTH_TOKEN_AUTH

    if auth_method == "basic":
        credentials = f"{config.client_id}:{config.client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"
    elif auth_method == "body":
        extra_data["client_id"] = config.client_id
        extra_data["client_secret"] = config.client_secret
    elif auth_method == "none":
        extra_data["client_id"] = config.client_id
    else:
        raise ValueError(f"Unknown OAUTH_TOKEN_AUTH value: {auth_method}")

    return headers, extra_data


def oauth_login(config, force: bool) -> None:
    """Built-in OAuth 2.0 Authorization Code login handler.

    Signature matches login_handler(config, force) expected by create_auth_app.

    Uses OAUTH_* class variables from the config to drive the flow:
    - OAUTH_AUTH_URL / OAUTH_TOKEN_URL: endpoints
    - OAUTH_SCOPES: scope strings
    - OAUTH_REDIRECT_URI: default redirect (overridable via .env REDIRECT_URI)
    - OAUTH_PKCE: enable PKCE S256
    - OAUTH_TOKEN_AUTH: "basic" | "body" | "none"
    - OAUTH_EXTRA_AUTH_PARAMS: extra query params for auth URL
    """
    # Skip if already authenticated with valid token (unless --force)
    if not force and config.access_token:
        expires_at = config.token_expires_at
        if expires_at:
            try:
                if datetime.now().timestamp() < float(expires_at):
                    print_info("Already authenticated with a valid token.")
                    print_info("Use --force to re-authenticate anyway.")
                    return
            except (ValueError, TypeError):
                pass

    # Resolve redirect URI: .env overrides class default
    redirect_uri = config.redirect_uri or config.OAUTH_REDIRECT_URI
    redirect_uri_required = getattr(config, "OAUTH_REDIRECT_URI_REQUIRED", True)
    if not redirect_uri and redirect_uri_required:
        print_error("No redirect URI configured. Set REDIRECT_URI in .env or OAUTH_REDIRECT_URI on Config.")
        raise typer.Exit(1)

    # PKCE
    code_verifier = None
    code_challenge = None
    if config.OAUTH_PKCE:
        code_verifier, code_challenge = generate_pkce_pair()

    # Build auth URL
    auth_params = {
        "client_id": config.client_id,
        "response_type": "code",
    }
    if redirect_uri:
        auth_params["redirect_uri"] = redirect_uri

    if config.OAUTH_SCOPES:
        auth_params["scope"] = " ".join(config.OAUTH_SCOPES)

    if code_challenge:
        auth_params["code_challenge"] = code_challenge
        auth_params["code_challenge_method"] = "S256"

    if config.OAUTH_EXTRA_AUTH_PARAMS:
        auth_params.update(config.OAUTH_EXTRA_AUTH_PARAMS)

    auth_url = config.OAUTH_AUTH_URL
    full_url = f"{auth_url}?{urlencode(auth_params)}"

    print_info("Opening browser for authorization...")
    print_info(f"\nIf browser doesn't open, visit:\n{full_url}\n")
    webbrowser.open(full_url)

    print_info("After authorizing, you'll be redirected.")
    print_info("Paste the authorization code OR the full redirect URL below:\n")

    user_input = typer.prompt("Code or URL")
    try:
        code = extract_code_from_input(user_input)
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)

    # Exchange code for tokens
    headers, extra_data = build_token_auth_headers(config)

    token_data = {
        "grant_type": "authorization_code",
        "code": code,
        **extra_data,
    }
    if redirect_uri:
        token_data["redirect_uri"] = redirect_uri

    if code_verifier:
        token_data["code_verifier"] = code_verifier

    token_url = config.OAUTH_TOKEN_URL
    response = requests.post(token_url, headers=headers, data=token_data)

    if response.status_code != 200:
        try:
            error_data = response.json()
            error_msg = error_data.get("error_description", response.text)
        except Exception:
            error_msg = response.text
        print_error(f"Token exchange failed: {error_msg}")
        raise typer.Exit(1)

    expires_in = parse_and_save_tokens(config, response.json())

    print_success("Authentication successful! Tokens saved.")
    print_info(f"Access token expires in {expires_in // 3600} hours.")
