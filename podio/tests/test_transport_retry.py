"""Regression test: Podio's real rate-limit status (HTTP 420) must be retried.

Podio's documented rate-limit response is HTTP 420, not the standard 429
(https://developers.podio.com/index/limits). The retry loop in
`pypodio2.transport.HttpTransport` previously special-cased only status 429,
so a genuine Podio rate-limit response fell straight through to the
immediate-failure 4xx branch and `RetryConfig(retry_on_rate_limit=True)`
never actually engaged for real traffic.
"""

from pypodio2.transport import HttpTransport, RetryConfig, TransportException


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
