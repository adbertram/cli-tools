# -*- coding: utf-8 -*-
from httplib2 import Http
import time
import random

try:
    from urllib.parse import urlencode
except ImportError:
    from urllib import urlencode

from .encode import multipart_encode


import json


class RetryConfig(object):
    """Configuration for retry behavior with exponential backoff."""

    def __init__(self, max_retries=3, base_delay=1.0, max_delay=60.0,
                 exponential_base=2.0, jitter=True, retry_on_rate_limit=True):
        """
        Initialize retry configuration.

        Args:
            max_retries: Maximum number of retry attempts (default: 3)
            base_delay: Initial delay in seconds (default: 1.0)
            max_delay: Maximum delay in seconds (default: 60.0)
            exponential_base: Base for exponential backoff (default: 2.0)
            jitter: Whether to add random jitter to delays (default: True)
            retry_on_rate_limit: Whether to retry on 429 rate limit errors (default: True)
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retry_on_rate_limit = retry_on_rate_limit

    def calculate_delay(self, attempt):
        """
        Calculate delay for a given retry attempt with exponential backoff.

        Args:
            attempt: Current retry attempt number (0-indexed)

        Returns:
            float: Delay in seconds
        """
        delay = min(self.base_delay * (self.exponential_base ** attempt), self.max_delay)

        if self.jitter:
            # Add jitter: random value between 0 and delay
            delay = delay * (0.5 + random.random() * 0.5)

        return delay


class OAuthToken(object):
    """
    Class used to encapsulate the OAuthToken required to access the
    Podio API.

    Do not modify its attributes manually Use the methods in the
    Podio API Connector, get_oauth_token and refresh_oauth_token
    """
    def __init__(self, resp):
        self.expires_in = resp['expires_in']
        self.access_token = resp['access_token']
        self.refresh_token = resp['refresh_token']

    def to_headers(self):
        return {'authorization': "OAuth2 %s" % self.access_token}


class OAuthAuthorization(object):
    """Generates headers for Podio OAuth2 Authorization"""

    def __init__(self, login, password, key, secret, domain):
        body = {'grant_type': 'password',
                'client_id': key,
                'client_secret': secret,
                'username': login,
                'password': password}
        h = Http(disable_ssl_certificate_validation=True)
        headers = {'content-type': 'application/json'}
        response, data = h.request(
            domain + "/oauth/token/v2",
            "POST",
            json.dumps(body),
            headers=headers
        )
        self.token = OAuthToken(_handle_response(response, data))

    def __call__(self):
        return self.token.to_headers()


class OAuthAppAuthorization(object):

    def __init__(self, app_id, app_token, key, secret, domain):
        body = {'grant_type': 'app',
                'client_id': key,
                'client_secret': secret,
                'app_id': app_id,
                'app_token': app_token}
        h = Http(disable_ssl_certificate_validation=True)
        headers = {'content-type': 'application/json'}
        response, data = h.request(
            domain + "/oauth/token/v2",
            "POST",
            json.dumps(body),
            headers=headers
        )
        self.token = OAuthToken(_handle_response(response, data))

    def __call__(self):
        return self.token.to_headers()


class OAuthAuthorizationCodeAuthorization(object):
    """Server-side OAuth2 authorization using authorization code flow"""

    def __init__(self, authorization_code, redirect_uri, client_id, client_secret, domain):
        # Exchange authorization code for access token
        body = {
            'grant_type': 'authorization_code',
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
            'code': authorization_code
        }
        h = Http(disable_ssl_certificate_validation=True)
        headers = {'content-type': 'application/json'}
        response, data = h.request(
            domain + "/oauth/token/v2",
            "POST",
            json.dumps(body),
            headers=headers
        )
        self.token = OAuthToken(_handle_response(response, data))

    def __call__(self):
        return self.token.to_headers()
    
    @staticmethod
    def get_authorization_url(client_id, redirect_uri, scope=None):
        """
        Generate the authorization URL to redirect users to Podio for authorization.
        
        Args:
            client_id: Your application's client ID
            redirect_uri: URL to redirect back to after authorization
            scope: Optional scope string (e.g., 'global:all')
        
        Returns:
            str: The full authorization URL
        """
        params = {
            'client_id': client_id,
            'redirect_uri': redirect_uri
        }
        if scope:
            params['scope'] = scope
        
        return f"https://podio.com/oauth/authorize?{urlencode(params)}"


class OAuthTokenAuthorization(object):
    """Client-side OAuth2 authorization using existing access token with auto-refresh"""

    def __init__(self, access_token, refresh_token=None, expires_in=None, client_id=None, client_secret=None, domain="https://api.podio.com", on_token_refresh=None):
        # Use an existing access token directly (from client-side flow)
        token_data = {
            'access_token': access_token,
            'refresh_token': refresh_token or '',
            'expires_in': expires_in or 28800  # Default 8 hours
        }
        self.token = OAuthToken(token_data)
        self.client_id = client_id  # Store for token refresh
        self.client_secret = client_secret  # Store for token refresh
        self.domain = domain
        self.on_token_refresh = on_token_refresh  # Callback for token persistence

    def __call__(self):
        return self.token.to_headers()
    
    def refresh_access_token(self):
        """
        Refresh the access token using the refresh token.
        
        Returns:
            bool: True if refresh was successful, False otherwise
        """
        if not self.token.refresh_token:
            return False
        
        # Refresh tokens don't require client credentials for Podio
        # But we'll include them if available for compatibility
        body = {
            'grant_type': 'refresh_token',
            'refresh_token': self.token.refresh_token
        }
        
        # Add client credentials if available
        if self.client_id and self.client_secret:
            body['client_id'] = self.client_id
            body['client_secret'] = self.client_secret
        
        try:
            h = Http(disable_ssl_certificate_validation=True)
            headers = {'content-type': 'application/json'}
            response, data = h.request(
                self.domain + "/oauth/token/v2",
                "POST",
                json.dumps(body),
                headers=headers
            )
            
            if response.status == 200:
                # Update token with new access token
                new_token_data = _handle_response(response, data)
                self.token = OAuthToken(new_token_data)

                # Call the persistence callback if provided
                if self.on_token_refresh:
                    try:
                        self.on_token_refresh(self.token.access_token, self.token.refresh_token)
                    except Exception:
                        # Don't fail refresh if persistence fails
                        pass

                return True
            else:
                return False
        except Exception:
            return False
    
    @staticmethod
    def get_authorization_url(client_id, redirect_uri, scope=None):
        """
        Generate the authorization URL for client-side flow (returns token in fragment).
        
        Args:
            client_id: Your application's client ID
            redirect_uri: URL to redirect back to after authorization
            scope: Optional scope string (e.g., 'global:all')
        
        Returns:
            str: The full authorization URL with response_type=token
        """
        params = {
            'response_type': 'token',  # Key difference for client-side flow
            'client_id': client_id,
            'redirect_uri': redirect_uri
        }
        if scope:
            params['scope'] = scope
        
        return f"https://podio.com/oauth/authorize?{urlencode(params)}"


class UserAgentHeaders(object):
    def __init__(self, base_headers_factory, user_agent):
        self.base_headers_factory = base_headers_factory
        self.user_agent = user_agent

    def __call__(self):
        headers = self.base_headers_factory()
        headers['User-Agent'] = self.user_agent
        return headers


class KeepAliveHeaders(object):

    def __init__(self, base_headers_factory):
        self.base_headers_factory = base_headers_factory

    def __call__(self):
        headers = self.base_headers_factory()
        headers['Connection'] = 'Keep-Alive'
        return headers


class TransportException(Exception):

    def __init__(self, status, content):
        super(TransportException, self).__init__()
        self.status = status
        self.content = content

    def __str__(self):
        return "TransportException(%s): %s" % (self.status, self.content)


class HttpTransport(object):
    def __init__(self, url, headers_factory, auth_object=None, retry_config=None):
        self._api_url = url
        self._headers_factory = headers_factory
        self._auth_object = auth_object  # Store auth object for token refresh
        self._retry_config = retry_config or RetryConfig()  # Default retry config
        self._supported_methods = ("GET", "POST", "PUT", "HEAD", "DELETE",)
        self._attribute_stack = []
        self._method = "GET"
        self._posts = []
        self._http = Http(disable_ssl_certificate_validation=True)
        self._params = {}
        self._url_template = '%(domain)s/%(generated_url)s'
        self._stack_collapser = "/".join
        self._params_template = '?%s'

    def __call__(self, *args, **kwargs):
        self._attribute_stack += [str(a) for a in args]
        self._params = kwargs

        if 'url' not in kwargs:
            url = self.get_url()
        else:
            url = self.get_url(kwargs['url'])

        # Prepare request body
        if (self._method == "POST" or self._method == "PUT") and 'type' not in kwargs:
            body = json.dumps(kwargs)
        elif 'type' in kwargs:
            if kwargs['type'] == 'multipart/form-data':
                body, new_headers = multipart_encode(kwargs['body'])
                body = b"".join(body)
            else:
                body = kwargs['body']
        else:
            body = self._generate_body()  # hack

        # Retry loop with exponential backoff
        last_exception = None
        for attempt in range(self._retry_config.max_retries + 1):
            try:
                # Prepare headers for this attempt
                headers = self._headers_factory()

                if (self._method == "POST" or self._method == "PUT") and 'type' not in kwargs:
                    headers.update({'content-type': 'application/json'})
                elif 'type' in kwargs and kwargs['type'] == 'multipart/form-data':
                    headers.update(new_headers)
                elif 'type' in kwargs:
                    headers.update({'content-type': kwargs['type']})

                # Make the HTTP request
                response, data = self._http.request(url, self._method, body=body, headers=headers)

                # Handle 401 Unauthorized with token refresh
                if response.status == 401 and self._auth_object and isinstance(self._auth_object, OAuthTokenAuthorization):
                    if hasattr(self._auth_object, 'refresh_access_token'):
                        if self._auth_object.refresh_access_token():
                            # Retry immediately with new token
                            headers = self._headers_factory()
                            if (self._method == "POST" or self._method == "PUT") and 'type' not in kwargs:
                                headers.update({'content-type': 'application/json'})
                            elif 'type' in kwargs and kwargs['type'] == 'multipart/form-data':
                                headers.update(new_headers)
                            elif 'type' in kwargs:
                                headers.update({'content-type': kwargs['type']})
                            response, data = self._http.request(url, self._method, body=body, headers=headers)

                # Handle rate limiting (429)
                if response.status == 429 and self._retry_config.retry_on_rate_limit:
                    if attempt < self._retry_config.max_retries:
                        # Check for Retry-After header
                        retry_after = response.get('retry-after')
                        if retry_after:
                            try:
                                delay = float(retry_after)
                            except (ValueError, TypeError):
                                delay = self._retry_config.calculate_delay(attempt)
                        else:
                            delay = self._retry_config.calculate_delay(attempt)

                        time.sleep(delay)
                        continue
                    # If max retries reached, let it fall through to handler

                # Handle server errors (5xx) with retry
                if response.status >= 500:
                    if attempt < self._retry_config.max_retries:
                        delay = self._retry_config.calculate_delay(attempt)
                        time.sleep(delay)
                        continue
                    # If max retries reached, let it fall through to handler

                # Handle client errors (4xx) - do not retry, fail immediately
                if response.status >= 400 and response.status < 500:
                    self._attribute_stack = []
                    handler = kwargs.get('handler', _handle_response)
                    return handler(response, data)

                # Success or other non-retryable responses
                self._attribute_stack = []
                handler = kwargs.get('handler', _handle_response)
                return handler(response, data)

            except TransportException as e:
                # Don't retry client errors (4xx) - they indicate bad requests
                # that won't succeed on retry
                raise
            except Exception as e:
                last_exception = e
                if attempt < self._retry_config.max_retries:
                    delay = self._retry_config.calculate_delay(attempt)
                    time.sleep(delay)
                    continue
                raise

        # Should not reach here, but handle edge case
        if last_exception:
            raise last_exception

        # Return last response if no exception
        self._attribute_stack = []
        handler = kwargs.get('handler', _handle_response)
        return handler(response, data)

    def _generate_params(self, params):
        body = self._params_template % urlencode(params)
        if body is None:
            return ''
        return body

    def _generate_body(self):
        if self._method == 'POST':
            internal_params = self._params.copy()

            if 'GET' in internal_params:
                del internal_params['GET']

            return self._generate_params(internal_params)[1:]

    def _clear_content_type(self):
        """Clear content-type"""
        if 'content-type' in self._headers:
            del self._headers['content-type']

    def _clear_headers(self):
        """Clear all headers"""
        self._headers = {}

    def get_url(self, url=None):
        if url is None:
            url = self._url_template % {
                "domain": self._api_url,
                "generated_url": self._stack_collapser(self._attribute_stack),
            }
        else:
            url = self._url_template % {
                'domain': self._api_url,
                'generated_url': url[1:]
            }
            del self._params['url']

        if len(self._params):
            internal_params = self._params.copy()

            if 'handler' in internal_params:
                del internal_params['handler']

            if self._method == 'POST' or self._method == "PUT":
                if "GET" not in internal_params:
                    return url
                internal_params = internal_params['GET']
            url += self._generate_params(internal_params)
        return url

    def __getitem__(self, name):
        self._attribute_stack.append(name)
        return self

    def __getattr__(self, name):
        if name in self._supported_methods:
            self._method = name
        elif not name.endswith(')'):
            self._attribute_stack.append(name)
        return self


def _handle_response(response, data):
    if not data:
        data = '{}'
    else:
        data = data.decode("utf-8")
    if response.status >= 400:
        raise TransportException(response, data)
    return json.loads(data)
