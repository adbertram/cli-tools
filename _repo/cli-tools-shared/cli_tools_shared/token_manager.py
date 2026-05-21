"""OAuth token lifecycle management: expiry checks and automatic refresh.

Usage:
    from cli_tools_shared.token_manager import TokenManager

    class MyClient:
        def __init__(self):
            self.config = get_config()
            self.tokens = TokenManager(self.config)

        def _request(self, method, url, **kwargs):
            self.tokens.ensure_valid()
            headers = {"Authorization": f"Bearer {self.config.access_token}"}
            ...
"""

from datetime import datetime
from typing import Callable, Optional

import requests

from .exceptions import ClientError
from .oauth import build_token_auth_headers, parse_and_save_tokens


class TokenManager:
    """Manages OAuth token expiry and refresh for CLI tool clients.

    Args:
        config: BaseConfig subclass instance with OAUTH_* class variables.
        expiry_buffer: Seconds before actual expiry to consider token expired (default 300).
        on_refresh: Optional callback invoked after tokens are saved on refresh.
            Useful for clients that cache auth headers.
    """

    def __init__(
        self,
        config,
        expiry_buffer: int = 300,
        on_refresh: Optional[Callable] = None,
    ):
        self.config = config
        self.expiry_buffer = expiry_buffer
        self.on_refresh = on_refresh

    def is_expired(self) -> bool:
        """Check if access token is expired or within expiry_buffer of expiring."""
        expires_at = self.config.token_expires_at
        if not expires_at:
            return True

        try:
            expires_timestamp = float(expires_at)
            return datetime.now().timestamp() > (expires_timestamp - self.expiry_buffer)
        except (ValueError, TypeError):
            return True

    def ensure_valid(self) -> None:
        """Refresh token if expired, no-op if still valid."""
        if self.is_expired():
            self.force_refresh()

    def force_refresh(self) -> None:
        """Force token refresh using stored refresh_token.

        Raises:
            ClientError: If no refresh token available or refresh request fails.
        """
        refresh_token = self.config.refresh_token
        if not refresh_token:
            raise ClientError(
                "No refresh token available. Run 'auth login' to re-authenticate."
            )

        token_url = self.config.OAUTH_TOKEN_URL
        if not token_url:
            raise ClientError(
                "No OAUTH_TOKEN_URL configured. Token refresh not supported."
            )

        headers, extra_data = build_token_auth_headers(self.config)
        redirect_uri = self.config.redirect_uri or self.config.OAUTH_REDIRECT_URI

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            **extra_data,
        }
        if redirect_uri:
            data["redirect_uri"] = redirect_uri

        response = requests.post(token_url, headers=headers, data=data)

        if response.status_code != 200:
            error_data = response.json() if response.text else {}
            error_msg = error_data.get("error_description", response.text)
            raise ClientError(f"Token refresh failed: {error_msg}")

        parse_and_save_tokens(self.config, response.json(), fallback_refresh=refresh_token)

        if self.on_refresh:
            self.on_refresh()
