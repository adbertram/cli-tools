"""Helpers for WordPress.com OAuth token management."""

from __future__ import annotations

import sys
import webbrowser
from typing import Optional
from urllib.parse import urlencode

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.oauth import extract_code_from_input
from cli_tools_shared.output import print_info

from .config import Config


WPCOM_OAUTH_AUTH_URL = "https://public-api.wordpress.com/oauth2/authorize"
WPCOM_OAUTH_TOKEN_URL = "https://public-api.wordpress.com/oauth2/token"
WPCOM_OAUTH_SCOPE = "global"
WPCOM_SAVE_CREDENTIAL_COMMAND = (
    "wordpress org token save-credential "
    "--client-id ... --client-secret ... --site ... --redirect-uri ..."
)


def build_wpcom_missing_credentials_message(missing_fields: list[str]) -> str:
    """Build the canonical missing-credentials error message."""
    missing = ", ".join(missing_fields)
    return (
        f"Missing WordPress.com credentials: {missing}. "
        f"Run `{WPCOM_SAVE_CREDENTIAL_COMMAND}` to save the full WordPress.com credential bundle."
    )


def save_wpcom_credentials(
    config: Config,
    *,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    site: Optional[str] = None,
    redirect_uri: Optional[str] = None,
) -> dict:
    """Save provided WordPress.com credentials and verify the bundle is complete."""
    config.save_wpcom_credentials(
        client_id=client_id,
        client_secret=client_secret,
        site=site,
        redirect_uri=redirect_uri,
    )
    missing = config.get_missing_wpcom_credentials()
    if missing:
        raise ClientError(build_wpcom_missing_credentials_message(missing))

    return {
        "site": config.wpcom_site,
        "credentials_saved": True,
        "configured_fields": list(config.WPCOM_REQUIRED_FIELDS),
    }


def acquire_wpcom_access_token(
    config: Config,
    *,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    site: Optional[str] = None,
    redirect_uri: Optional[str] = None,
) -> dict:
    """Request and save a WordPress.com OAuth token using authorization code flow."""
    save_wpcom_credentials(
        config,
        client_id=client_id,
        client_secret=client_secret,
        site=site,
        redirect_uri=redirect_uri,
    )

    authorization_url = build_wpcom_authorization_url(config)
    print_info("Open the following URL in your browser to authorize WordPress.com access:")
    print_info(authorization_url)
    print_info("")
    webbrowser.open(authorization_url)
    print_info("After approving access, paste the full redirect URL or just the authorization code below.")
    code = _read_authorization_code()

    response = _request_wpcom_token(
        data={
            "client_id": config.wpcom_client_id,
            "client_secret": config.wpcom_client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.wpcom_redirect_uri,
        },
    )

    payload = _parse_wpcom_json(response)
    if not response.ok:
        message = payload.get("error_description") or payload.get("message") or payload.get("error") or response.text
        raise ClientError(f"WordPress.com token request failed ({response.status_code}): {message}")

    access_token = payload.get("access_token")
    if not access_token:
        raise ClientError("WordPress.com token response did not include access_token")

    token_type = payload.get("token_type")
    scope = payload.get("scope")
    config.save_wpcom_access_token(
        access_token,
        token_type=token_type,
        scope=scope,
    )
    return {
        "site": config.wpcom_site,
        "token_saved": True,
        "token_type": token_type,
        "scope": scope,
    }


def build_wpcom_authorization_url(config: Config) -> str:
    """Build the WordPress.com authorization URL for the configured site."""
    if not config.wpcom_client_id:
        raise ClientError("Missing WordPress.com client id: WPCOM_CLIENT_ID")
    if not config.wpcom_redirect_uri:
        raise ClientError("Missing WordPress.com redirect URI: WPCOM_REDIRECT_URI")

    params = {
        "client_id": config.wpcom_client_id,
        "redirect_uri": config.wpcom_redirect_uri,
        "response_type": "code",
        "scope": WPCOM_OAUTH_SCOPE,
    }
    return f"{WPCOM_OAUTH_AUTH_URL}?{urlencode(params)}"


def _read_authorization_code() -> str:
    """Read a pasted redirect URL or authorization code from stdin."""
    sys.stderr.write("Code or URL: ")
    sys.stderr.flush()
    user_input = sys.stdin.readline()
    if not user_input:
        raise ClientError("No authorization code was provided on stdin")

    try:
        return extract_code_from_input(user_input)
    except ValueError as exc:
        raise ClientError(str(exc)) from exc


def wpcom_response_indicates_invalid_token(response: requests.Response) -> bool:
    """Return True when a WordPress.com API response says the token is invalid."""
    if response.status_code == 401:
        return True
    payload = _parse_wpcom_json(response)
    error = payload.get("error")
    message = payload.get("message")
    return error == "invalid_token" or message == "invalid_token"


def extract_wpcom_error_message(response: requests.Response) -> str:
    """Extract the best available error message from a WordPress.com response."""
    payload = _parse_wpcom_json(response)
    return payload.get("message") or payload.get("error_description") or payload.get("error") or response.text


def _parse_wpcom_json(response: requests.Response) -> dict:
    """Parse a WordPress.com JSON response into a dict."""
    try:
        payload = response.json()
    except Exception:
        return {}
    if not isinstance(payload, dict):
        raise ClientError(f"Expected WordPress.com response to be a dict, got {type(payload)}")
    return payload


def _request_wpcom_token(data: dict):
    import requests

    return requests.request(
        method="POST",
        url=WPCOM_OAUTH_TOKEN_URL,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=data,
        timeout=60,
    )
