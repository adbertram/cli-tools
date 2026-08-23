"""OAuth login flow for Epic MyChart SMART on FHIR."""

from __future__ import annotations

import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests
import typer
from cli_tools_shared.oauth import (
    build_token_auth_headers,
    generate_pkce_pair,
    parse_and_save_tokens,
)
from cli_tools_shared.output import print_error, print_info, print_success


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    server: "_OAuthCallbackServer"

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        expected_path = self.server.expected_path or "/"
        if parsed.path != expected_path:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Unexpected callback path.")
            return

        params = parse_qs(parsed.query)
        self.server.authorization_code = (params.get("code") or [None])[0]
        self.server.authorization_error = (params.get("error_description") or params.get("error") or [None])[0]
        self.send_response(200 if self.server.authorization_code else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if self.server.authorization_code:
            self.wfile.write(b"<html><body><h1>MyChart CLI authenticated.</h1>You can close this tab.</body></html>")
        else:
            self.wfile.write(b"<html><body><h1>MyChart CLI authentication failed.</h1></body></html>")

    def log_message(self, format, *args):  # noqa: A002 - BaseHTTPRequestHandler API
        return


class _OAuthCallbackServer(HTTPServer):
    def __init__(self, server_address, handler_class, expected_path: str):
        super().__init__(server_address, handler_class)
        self.expected_path = expected_path
        self.authorization_code: str | None = None
        self.authorization_error: str | None = None


def _capture_code_from_loopback(redirect_uri: str, timeout_seconds: int = 300) -> str:
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"} or parsed.port is None:
        raise ValueError(
            "MyChart CLI auth requires a registered loopback HTTP redirect URI, "
            "for example http://localhost:8765/callback."
        )

    server = _OAuthCallbackServer(
        (parsed.hostname, parsed.port),
        _OAuthCallbackHandler,
        parsed.path or "/",
    )
    server.timeout = 1
    deadline = time.time() + timeout_seconds
    try:
        while time.time() < deadline:
            server.handle_request()
            if server.authorization_error:
                raise ValueError(server.authorization_error)
            if server.authorization_code:
                return server.authorization_code
    finally:
        server.server_close()
    raise TimeoutError("Timed out waiting for Epic OAuth redirect.")


def mychart_login(config, force: bool) -> None:
    """Authenticate with Epic SMART on FHIR and save patient context."""
    if not config.client_id:
        print_error("Missing CLIENT_ID. Run 'mychart auth login' and enter an Epic on FHIR client ID.")
        raise typer.Exit(1)

    redirect_uri = config.redirect_uri or config.OAUTH_REDIRECT_URI
    code_verifier, code_challenge = generate_pkce_pair()
    auth_params = {
        "aud": config.base_url,
        "client_id": config.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(config.OAUTH_SCOPES),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{config.OAUTH_AUTH_URL}?{urlencode(auth_params)}"

    print_info("Opening browser for Epic MyChart authorization...")
    print_info(f"\nIf the browser does not open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)
    print_info("Waiting for the OAuth redirect on the registered localhost callback...")

    try:
        code = _capture_code_from_loopback(redirect_uri)
    except (OSError, TimeoutError, ValueError) as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    headers, extra_data = build_token_auth_headers(config)
    token_data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        **extra_data,
    }
    response = requests.post(config.OAUTH_TOKEN_URL, headers=headers, data=token_data, timeout=30)
    if response.status_code != 200:
        try:
            error_body = response.json()
            detail = error_body.get("error_description") or error_body.get("error") or response.text
        except ValueError:
            detail = response.text
        print_error(f"Token exchange failed: {detail}")
        raise typer.Exit(1)

    token_payload = response.json()
    parse_and_save_tokens(config, token_payload)
    patient_id = token_payload.get("patient")
    if patient_id:
        config._set("PATIENT_ID", str(patient_id))
    granted_scopes = token_payload.get("scope")
    if granted_scopes:
        config._set("GRANTED_SCOPES", str(granted_scopes))
    print_success("Authentication successful. Tokens and patient context saved.")
