"""Regression tests for Podio transport retry and request-timeout behavior.

Podio's documented rate-limit response is HTTP 420, not the standard 429
(https://developers.podio.com/index/limits). The retry loop in
`pypodio2.transport.HttpTransport` previously special-cased only status 429,
so a genuine Podio rate-limit response fell straight through to the
immediate-failure 4xx branch and `RetryConfig(retry_on_rate_limit=True)`
never actually engaged for real traffic.
"""

import pytest

from pypodio2 import api as api_module
from pypodio2 import transport as transport_module
from pypodio2.transport import HttpTransport, RetryConfig, TransportException
from podio_cli.config import Config


class _FakeResponse(dict):
    """Mimics an httplib2.Response: dict-like headers plus a `.status` attr."""

    def __init__(self, status, headers=None):
        super().__init__(headers or {})
        self.status = status


class _FakeHttp:
    """Stand-in for httplib2.Http that returns a scripted sequence of responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def request(self, url, method, body=None, headers=None):
        self.calls += 1
        status, data = self._responses.pop(0)
        return _FakeResponse(status), data


class _HangingHttp:
    """Stand-in that raises the timeout httplib2 surfaces for stalled requests."""

    def __init__(self):
        self.calls = 0

    def request(self, url, method, body=None, headers=None):
        self.calls += 1
        raise TimeoutError("timed out")


def _make_transport(responses, retry_config):
    transport = HttpTransport(
        url="https://api.podio.com",
        headers_factory=lambda: {},
        retry_config=retry_config,
    )
    fake_http = _FakeHttp(responses)
    transport._http = fake_http
    return transport, fake_http


def test_status_420_is_retried_and_eventually_succeeds():
    # First call hits Podio's real rate-limit status (420); second succeeds.
    responses = [
        (420, b'{"error_description":"rate limit exceeded"}'),
        (200, b'{"item_id": 1}'),
    ]
    retry_config = RetryConfig(max_retries=3, base_delay=0.001, jitter=False)
    transport, fake_http = _make_transport(responses, retry_config)

    transport._method = "GET"
    result = transport()

    assert result == {"item_id": 1}
    assert fake_http.calls == 2


def test_status_420_retries_exhausted_raises_transport_exception():
    # Every attempt returns 420; once retries are exhausted it must raise,
    # not silently succeed or hang.
    retry_config = RetryConfig(max_retries=2, base_delay=0.001, jitter=False)
    responses = [(420, b'{"error_description":"rate limit exceeded"}')] * (
        retry_config.max_retries + 1
    )
    transport, fake_http = _make_transport(responses, retry_config)

    transport._method = "GET"
    try:
        transport()
        assert False, "expected TransportException"
    except TransportException as exc:
        assert exc.status.status == 420

    assert fake_http.calls == retry_config.max_retries + 1


def test_status_429_still_retried():
    # Guard the pre-existing standard-429 behavior against regression.
    responses = [
        (429, b'{"error_description":"too many requests"}'),
        (200, b'{"item_id": 1}'),
    ]
    retry_config = RetryConfig(max_retries=3, base_delay=0.001, jitter=False)
    transport, fake_http = _make_transport(responses, retry_config)

    transport._method = "GET"
    result = transport()

    assert result == {"item_id": 1}
    assert fake_http.calls == 2


def test_non_rate_limit_4xx_is_not_retried():
    # A genuine bad request (400) must still fail immediately, not be
    # mistaken for a rate-limit-retryable status.
    responses = [(400, b'{"error_description":"bad request"}')]
    retry_config = RetryConfig(max_retries=3, base_delay=0.001, jitter=False)
    transport, fake_http = _make_transport(responses, retry_config)

    transport._method = "GET"
    try:
        transport()
        assert False, "expected TransportException"
    except TransportException as exc:
        assert exc.status.status == 400

    assert fake_http.calls == 1


def test_request_timeout_is_passed_to_httplib2(monkeypatch):
    captured = {}

    class _CapturingHttp:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(transport_module, "Http", _CapturingHttp)

    HttpTransport(
        url="https://api.podio.com",
        headers_factory=lambda: {},
        retry_config=RetryConfig(request_timeout=12.5),
    )

    assert captured["timeout"] == 12.5


def test_all_oauth_http_requests_use_configured_timeout(monkeypatch):
    captured = []

    class _CapturingHttp:
        def __init__(self, **kwargs):
            captured.append(kwargs)

        def request(self, url, method, body=None, headers=None):
            return (
                _FakeResponse(200),
                b'{"expires_in": 3600, "access_token": "access", "refresh_token": "refresh"}',
            )

    monkeypatch.setattr(transport_module, "Http", _CapturingHttp)

    transport_module.OAuthAuthorization(
        "user", "password", "key", "secret", "https://api.podio.com", request_timeout=12.5
    )
    transport_module.OAuthAppAuthorization(
        1, "token", "key", "secret", "https://api.podio.com", request_timeout=12.5
    )
    transport_module.OAuthAuthorizationCodeAuthorization(
        "code",
        "https://example.test/callback",
        "key",
        "secret",
        "https://api.podio.com",
        request_timeout=12.5,
    )
    token_auth = transport_module.OAuthTokenAuthorization("access", "refresh", request_timeout=12.5)
    assert token_auth.refresh_access_token() is True

    assert [kwargs["timeout"] for kwargs in captured] == [12.5] * 4


def test_oauth_factory_forwards_configured_request_timeout(monkeypatch):
    captured = {}

    class _CapturingTokenAuthorization:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        def __call__(self):
            return {}

    monkeypatch.setattr(
        api_module.transport,
        "OAuthTokenAuthorization",
        _CapturingTokenAuthorization,
    )
    monkeypatch.setattr(api_module, "AuthorizingClient", lambda *args, **kwargs: object())

    api_module.OAuthTokenClient(
        "access",
        retry_config=RetryConfig(request_timeout=12.5),
    )

    assert captured["request_timeout"] == 12.5


def test_request_timeout_fails_fast_with_clear_transport_error():
    transport = HttpTransport(
        url="https://api.podio.com",
        headers_factory=lambda: {},
        retry_config=RetryConfig(max_retries=3, request_timeout=0.01),
    )
    hanging_http = _HangingHttp()
    transport._http = hanging_http
    transport._method = "GET"

    with pytest.raises(
        TransportException,
        match=r"Request timed out after 0.01 seconds\.",
    ):
        transport()

    assert hanging_http.calls == 1


@pytest.mark.parametrize("request_timeout", [0, -1, "not-a-number"])
def test_request_timeout_must_be_positive(request_timeout):
    with pytest.raises(ValueError, match="request_timeout must be a positive number"):
        RetryConfig(request_timeout=request_timeout)


@pytest.mark.parametrize(
    ("request_timeout", "error"),
    [
        ("0", "request_timeout must be a positive number"),
        ("-1", "request_timeout must be a positive number"),
        ("not-a-number", "REQUEST_TIMEOUT_SECONDS must be a number"),
    ],
)
def test_config_rejects_invalid_request_timeout(monkeypatch, request_timeout, error):
    config = Config.__new__(Config)
    config._retry_config = None
    monkeypatch.setenv("REQUEST_TIMEOUT_SECONDS", request_timeout)

    with pytest.raises(ValueError, match=error):
        config.get_retry_config()
