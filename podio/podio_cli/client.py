"""Podio client factory and wrapper."""
import sys
from typing import Optional
from pypodio2 import api
from .config import get_config


# Global client instance
_client: Optional[api.OAuthClient] = None


class ClientError(Exception):
    """Exception raised for client initialization errors."""
    pass


def get_client(config=None) -> api.OAuthClient:
    """
    Get or create the global Podio API client.

    Returns:
        OAuthClient: Authenticated Podio API client

    Raises:
        ClientError: If credentials are missing or authentication fails
    """
    global _client

    use_global = config is None
    if use_global and _client is not None:
        return _client

    config = get_config() if use_global else config
    try:
        retry_config = config.get_retry_config()
    except ValueError as e:
        raise ClientError(f"Invalid retry configuration: {e}")

    # Check for missing credentials
    missing = config.get_missing_credentials()
    if missing:
        error_msg = (
            "Missing required Podio credentials. Please set the following "
            "environment variables in your .env file:\n\n"
        )
        for cred in missing:
            error_msg += f"  - {cred}\n"

        error_msg += "\nRun 'podio auth login' to configure credentials.\n"

        raise ClientError(error_msg)

    # Try token authentication first (simplest, no extra round trip)
    if config.has_token_auth():
        try:
            # Create a callback to persist tokens after refresh
            def on_token_refresh(access_token, refresh_token):
                config.save_podio_tokens(access_token, refresh_token)

            client = api.OAuthTokenClient(
                access_token=config.access_token,
                refresh_token=config.refresh_token,
                client_id=config.client_id,  # Pass for token refresh capability
                client_secret=config.client_secret,  # Pass for token refresh capability
                on_token_refresh=on_token_refresh,  # Callback to persist refreshed tokens
                retry_config=retry_config
            )
            if use_global:
                _client = client
            return client
        except Exception as e:
            raise ClientError(f"Failed to authenticate with access token: {e}")

    # Try authorization code flow (most secure for web apps)
    if config.has_authorization_code_auth():
        try:
            client = api.OAuthAuthorizationCodeClient(
                client_id=config.client_id,
                client_secret=config.client_secret,
                authorization_code=config.authorization_code,
                redirect_uri=config.redirect_uri,
                retry_config=retry_config
            )
            if use_global:
                _client = client
            return client
        except Exception as e:
            raise ClientError(f"Failed to authenticate with authorization code: {e}")
    
    # Try user authentication (preferred for multi-app access)
    if config.has_user_auth():
        try:
            client = api.OAuthClient(
                api_key=config.client_id,
                api_secret=config.client_secret,
                login=config.username,
                password=config.password,
                retry_config=retry_config
            )
            if use_global:
                _client = client
            return client
        except Exception as e:
            raise ClientError(f"Failed to authenticate with user credentials: {e}")

    # Fall back to app authentication
    if config.has_app_auth():
        try:
            client = api.OAuthAppClient(
                client_id=config.client_id,
                client_secret=config.client_secret,
                app_id=int(config.app_id),
                app_token=config.app_token,
                retry_config=retry_config
            )
            if use_global:
                _client = client
            return client
        except Exception as e:
            raise ClientError(f"Failed to authenticate with app credentials: {e}")

    # This shouldn't happen if get_missing_credentials() works correctly
    raise ClientError("No valid authentication method available")


def reset_client():
    """Reset the global client instance (useful for testing)."""
    global _client
    _client = None
