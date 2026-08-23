"""Upwork GraphQL transport.

POSTs GraphQL operations to ``https://api.upwork.com/graphql`` with an OAuth2
bearer token. Upwork's GraphQL endpoint returns HTTP 200 even when the operation
fails, so this client inspects the response ``errors`` array on every 200 and
raises :class:`~cli_tools_shared.exceptions.ClientError`; it never silently
swallows GraphQL errors. Transient transport failures and retryable HTTP status
codes use the shared exponential-backoff-with-jitter retry policy, and expired
access tokens are refreshed once via the shared ``TokenManager`` before the call.
"""

from __future__ import annotations

from typing import Any, Optional

import requests

from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.http_session import RequestsRetryPolicy, request_with_retry
from cli_tools_shared.token_manager import TokenManager

DEFAULT_GRAPHQL_TIMEOUT = 30.0


class UpworkGraphQLError(ClientError):
    """Raised when an Upwork GraphQL response contains an ``errors`` array."""


class UpworkGraphQLClient:
    """Execute GraphQL operations against the Upwork API.

    Args:
        config: Upwork ``Config`` instance exposing OAuth token state, the
            ``graphql_url`` property, and the ``OAUTH_*`` class variables used by
            ``TokenManager`` for refresh.
    """

    def __init__(self, config):
        self.config = config
        self._logger = get_activity_logger("upwork")
        self._tokens = TokenManager(config, on_refresh=self._on_token_refresh)
        self._retry = RequestsRetryPolicy()
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def execute(
        self,
        query: str,
        variables: Optional[dict[str, Any]] = None,
        *,
        operation_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """Run a GraphQL operation and return the ``data`` object.

        Args:
            query: GraphQL document text.
            variables: Optional GraphQL variables.
            operation_name: Optional operation name for multi-operation documents.

        Returns:
            The ``data`` object from the GraphQL response.

        Raises:
            ClientError: When OAuth credentials are missing, the HTTP request
                fails after retries, the HTTP status is a non-retryable error, or
                the JSON body cannot be parsed.
            UpworkGraphQLError: When the GraphQL response contains ``errors``.
        """
        if not self.config.has_api_credentials():
            raise ClientError(
                "Missing Upwork API credentials. Run "
                "'upwork auth login -c oauth_authorization_code' to configure."
            )

        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables
        if operation_name:
            payload["operationName"] = operation_name

        response = self._post_with_retry(payload)
        return self._parse_response(response, operation_name or "graphql")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _on_token_refresh(self) -> None:
        self._logger.info("upwork oauth token refreshed")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _post_with_retry(self, payload: dict[str, Any]) -> requests.Response:
        url = self.config.graphql_url

        def send() -> requests.Response:
            # Refresh the access token before each attempt so a mid-loop expiry
            # or a fresh refresh after a 401 both use a current bearer token.
            self._tokens.ensure_valid()
            return self._session.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=DEFAULT_GRAPHQL_TIMEOUT,
            )

        self._logger.info("upwork graphql POST %s", url)
        try:
            response = request_with_retry(send, self._retry)
        except requests.exceptions.RequestException as exc:
            self._logger.error("upwork graphql transport error: %s", exc)
            raise ClientError(f"Upwork GraphQL request failed: {exc}") from exc

        # A single 401 after the pre-request refresh means the token was rejected;
        # force one refresh and retry once. No silent fallback beyond that.
        if response.status_code == 401:
            self._logger.info("upwork graphql 401 — forcing token refresh and retrying once")
            self._tokens.force_refresh()
            response = self._session.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=DEFAULT_GRAPHQL_TIMEOUT,
            )
        return response

    def _parse_response(self, response: requests.Response, operation: str) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            self._logger.error(
                "upwork graphql non-JSON response (HTTP %s) for %s",
                response.status_code,
                operation,
            )
            raise ClientError(
                f"Upwork GraphQL returned a non-JSON response (HTTP {response.status_code})."
            ) from exc

        # Upwork returns 200 even on errors, but a non-2xx with no GraphQL errors
        # array is still a hard failure that must surface.
        if not isinstance(body, dict):
            raise ClientError("Upwork GraphQL response was not a JSON object.")

        errors = body.get("errors")
        if errors:
            message = self._format_errors(errors)
            self._logger.error("upwork graphql errors for %s: %s", operation, message)
            raise UpworkGraphQLError(f"Upwork GraphQL error: {message}")

        if not response.ok:
            raise ClientError(
                f"Upwork GraphQL HTTP {response.status_code} with no error detail."
            )

        data = body.get("data")
        if data is None:
            raise ClientError(
                f"Upwork GraphQL response for {operation} contained no data."
            )
        return data

    @staticmethod
    def _format_errors(errors: Any) -> str:
        if isinstance(errors, list):
            messages = []
            for item in errors:
                if isinstance(item, dict):
                    text = item.get("message")
                    extensions = item.get("extensions")
                    if isinstance(extensions, dict) and extensions.get("code"):
                        text = f"{text} (code: {extensions['code']})"
                    messages.append(str(text) if text is not None else str(item))
                else:
                    messages.append(str(item))
            return "; ".join(messages)
        return str(errors)
