"""Regression tests for bounded Podio organization and space list requests."""

import pytest
from typer.testing import CliRunner

from podio_cli.commands import org, space
from pypodio2.transport import HttpTransport, RetryConfig

runner = CliRunner()


class _HangingHttp:
    """Simulates the timeout raised by a stalled httplib2 request."""

    def __init__(self):
        self.calls = 0

    def request(self, url, method, body=None, headers=None):
        self.calls += 1
        raise TimeoutError("timed out")


class _OrgApi:
    def __init__(self, transport):
        self._transport = transport

    def get_all(self):
        return self._transport.GET(url="/org/")


class _SpaceApi:
    def __init__(self, transport):
        self._transport = transport

    def find_all_for_org(self, org_id):
        return self._transport.GET(url="/org/%s/space/" % org_id)


class _Client:
    def __init__(self, transport):
        self.Org = _OrgApi(transport)
        self.Space = _SpaceApi(transport)


def _stalled_client():
    transport = HttpTransport(
        url="https://api.podio.com",
        headers_factory=lambda: {},
        retry_config=RetryConfig(max_retries=3, request_timeout=0.01),
    )
    hanging_http = _HangingHttp()
    transport._http = hanging_http
    return _Client(transport), hanging_http


@pytest.mark.parametrize(
    ("command_module", "arguments"),
    [
        (org, ["list"]),
        (space, ["list", "--org-id", "1"]),
    ],
)
def test_list_timeout_exits_with_clear_error(monkeypatch, command_module, arguments):
    client, hanging_http = _stalled_client()
    monkeypatch.setattr(command_module, "get_client", lambda: client)

    result = runner.invoke(command_module.app, arguments)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert (
        "Error: API error: TransportException(timeout): Request timed out after 0.01 seconds."
        in result.stderr
    )
    assert hanging_http.calls == 1
