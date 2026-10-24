"""TikTok desktop OAuth authorization-code flow with PKCE."""
from __future__ import annotations

import hashlib
import secrets
import string
import time
import webbrowser
from urllib.parse import parse_qs, urlencode, unquote, urlparse

import requests
import typer

from cli_tools_shared.output import print_error, print_info, print_success, prompt_text

_UNRESERVED = string.ascii_letters + string.digits + "-._~"


def generate_tiktok_pkce_pair() -> tuple[str, str]:
    verifier = "".join(secrets.choice(_UNRESERVED) for _ in range(64))
    challenge = hashlib.sha256(verifier.encode("ascii")).hexdigest()
    return verifier, challenge


def _authorization_code(user_input: str, expected_state: str) -> str:
    value = user_input.strip()
    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        params = parse_qs(parsed.query)
        if params.get("error"):
            message = params.get("error_description", params["error"])[0]
            raise ValueError(f"TikTok authorization failed: {message}")
        returned_state = params.get("state", [""])[0]
        if returned_state != expected_state:
            raise ValueError("TikTok OAuth state mismatch; refusing the authorization response.")
        code = params.get("code", [""])[0]
        if not code:
            raise ValueError("TikTok redirect URL did not contain an authorization code.")
        return unquote(code)
    raise ValueError("Paste the full TikTok redirect URL so the OAuth state can be verified.")


def _save_token_response(config, payload: dict) -> None:
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    if not access_token or not refresh_token:
        raise ValueError("TikTok token response omitted access_token or refresh_token.")
    expires_in = int(payload.get("expires_in") or 86400)
    config.save_tokens(
        access_token,
        refresh_token,
        str(time.time() + expires_in),
    )
    if payload.get("open_id"):
        config._set("OPEN_ID", str(payload["open_id"]))
    if payload.get("scope"):
        config._set("GRANTED_SCOPES", str(payload["scope"]))


def tiktok_oauth_login(config, force: bool) -> None:
    if config.auth_type == "browser_session":
        raise typer.BadParameter(
            "Use --credential-type browser_session for TikTok browser login."
        )

    if not force and config.access_token and config.token_expires_at:
        try:
            if float(config.token_expires_at) > time.time() + 60:
                print_info("Already authenticated with a valid TikTok access token.")
                return
        except (TypeError, ValueError):
            pass

    verifier, challenge = generate_tiktok_pkce_pair()
    state = secrets.token_urlsafe(32)
    params = {
        "client_key": config.client_key,
        "scope": ",".join(config.requested_scopes),
        "response_type": "code",
        "redirect_uri": config.redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = f"{config.authorization_url}?{urlencode(params)}"
    print_info("Opening TikTok authorization in your browser...")
    print_info(f"If the browser does not open, visit:\n{url}")
    webbrowser.open(url)
    print_info("After authorization, paste the full redirect URL or authorization code.")
    raw = prompt_text("Code or URL")
    try:
        code = _authorization_code(raw, state)
    except ValueError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    response = requests.post(
        config.token_url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": config.client_key,
            "client_secret": config.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": config.redirect_uri,
            "code_verifier": verifier,
        },
        timeout=30,
    )
    if not response.ok:
        print_error(f"TikTok token exchange failed: {response.text[:1000]}")
        raise typer.Exit(1)
    payload = response.json()
    if payload.get("error"):
        print_error(
            "TikTok token exchange failed: "
            + str(payload.get("error_description") or payload["error"])
        )
        raise typer.Exit(1)

    try:
        _save_token_response(config, payload)
    except ValueError as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    print_success("TikTok authentication successful.")
