# -*- coding: utf-8 -*-
from . import transport, client


def build_headers(authorization_headers, user_agent):
    headers = transport.KeepAliveHeaders(authorization_headers)
    if user_agent is not None:
        headers = transport.UserAgentHeaders(headers, user_agent)
    return headers


def OAuthClient(api_key, api_secret, login, password, user_agent=None,
                domain="https://api.podio.com", retry_config=None):
    auth = transport.OAuthAuthorization(login, password,
                                        api_key, api_secret, domain)
    return AuthorizingClient(domain, auth, user_agent=user_agent, retry_config=retry_config)


def OAuthAppClient(client_id, client_secret, app_id, app_token, user_agent=None,
                   domain="https://api.podio.com", retry_config=None):

    auth = transport.OAuthAppAuthorization(app_id, app_token,
                                           client_id, client_secret, domain)

    return AuthorizingClient(domain, auth, user_agent=user_agent, retry_config=retry_config)


def OAuthAuthorizationCodeClient(client_id, client_secret, authorization_code, redirect_uri,
                                  user_agent=None, domain="https://api.podio.com", retry_config=None):
    """
    Create a Podio client using server-side OAuth authorization code flow.

    Args:
        client_id: Your application's client ID
        client_secret: Your application's client secret
        authorization_code: The authorization code received from the callback
        redirect_uri: The redirect URI used in the authorization request
        user_agent: Optional user agent string
        domain: API domain (defaults to https://api.podio.com)
        retry_config: Optional RetryConfig for configuring retry behavior

    Returns:
        Client: Authenticated Podio API client
    """
    auth = transport.OAuthAuthorizationCodeAuthorization(
        authorization_code, redirect_uri, client_id, client_secret, domain
    )
    return AuthorizingClient(domain, auth, user_agent=user_agent, retry_config=retry_config)


def OAuthTokenClient(access_token, refresh_token=None, expires_in=None,
                     client_id=None, client_secret=None, user_agent=None, domain="https://api.podio.com",
                     on_token_refresh=None, retry_config=None):
    """
    Create a Podio client using an existing access token (client-side flow).

    Args:
        access_token: The access token from the URL fragment
        refresh_token: Optional refresh token (enables automatic token refresh)
        expires_in: Optional token expiration time in seconds
        client_id: Optional client ID (required for token refresh)
        client_secret: Optional client secret (required for token refresh)
        user_agent: Optional user agent string
        domain: API domain (defaults to https://api.podio.com)
        on_token_refresh: Optional callback function(access_token, refresh_token) called after token refresh
        retry_config: Optional RetryConfig for configuring retry behavior

    Returns:
        Client: Authenticated Podio API client with automatic token refresh
    """
    auth = transport.OAuthTokenAuthorization(
        access_token, refresh_token, expires_in, client_id, client_secret, domain, on_token_refresh
    )
    return AuthorizingClient(domain, auth, user_agent=user_agent, retry_config=retry_config)


def AuthorizingClient(domain, auth, user_agent=None, retry_config=None):
    """Creates a Podio client using an auth object."""
    http_transport = transport.HttpTransport(
        domain,
        build_headers(auth, user_agent),
        auth_object=auth,
        retry_config=retry_config
    )
    return client.Client(http_transport)
