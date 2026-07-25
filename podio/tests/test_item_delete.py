"""Regression tests for `podio item delete`.

These cover the two coupled defects that made
``podio item delete <id> --silent --no-hook`` print a false
"deleted successfully" while the item was never actually removed:

1. ``pypodio2.transport.HttpTransport.get_url`` appended a bare ``?`` for an
   empty param dict.  For a DELETE whose url already carried a query string
   (``.../item/123?silent=true&hook=false``) this produced a second ``?``
   (``.../item/123?silent=true&hook=false?``), turning the last param into
   ``hook=false?``.  Podio rejected the malformed request, so the delete never
   happened.

2. ``pypodio2.areas.Item.delete`` passed ``handler=lambda x, y: None`` which
   discarded the HTTP response entirely, so the resulting error was swallowed
   and the CLI still reported success.

The tests exercise the real ``Item`` area over a real ``HttpTransport`` (only
the socket-level ``_http.request`` is faked) plus the CLI command, so a
regression in either the url construction or the error handling fails here.
"""
import pytest
from typer.testing import CliRunner

from pypodio2.areas import Item
from pypodio2.transport import HttpTransport, TransportException

from podio_cli.commands import item


runner = CliRunner()


class _FakeResponse(dict):
    """Minimal stand-in for an httplib2 response with a ``status`` attribute."""

    def __init__(self, status):
        super().__init__()
        self.status = status


def _make_item_area(status=204, data=b""):
    """Build a real ``Item`` area backed by a real transport with a faked socket.

    Returns the ``Item`` instance and a dict that captures the final url/method
    handed to the HTTP layer.
    """
    captured = {}
    transport = HttpTransport("https://api.podio.com", headers_factory=lambda: {})

    def fake_request(url, method, body=None, headers=None):
        captured["url"] = url
        captured["method"] = method
        return _FakeResponse(status), data

    transport._http.request = fake_request
    return Item(transport), captured


@pytest.mark.parametrize(
    "silent, hook, expected_url",
    [
        (False, True, "https://api.podio.com/item/12345"),
        (True, False, "https://api.podio.com/item/12345?silent=true&hook=false"),
        (True, True, "https://api.podio.com/item/12345?silent=true"),
        (False, False, "https://api.podio.com/item/12345?hook=false"),
    ],
)
def test_delete_builds_wellformed_url(silent, hook, expected_url):
    """The DELETE url must be well-formed: a single '?' and correct params.

    Regression guard: the flags previously produced a double '?' such as
    '.../item/12345?silent=true&hook=false?' that Podio rejected, so the item
    was silently never deleted.
    """
    item_area, captured = _make_item_area(status=204)

    item_area.delete(item_id=12345, silent=silent, hook=hook)

    assert captured["method"] == "DELETE"
    assert captured["url"] == expected_url
    # Never more than one query separator.
    assert captured["url"].count("?") <= 1


def test_delete_does_not_swallow_api_error():
    """A non-2xx DELETE response must raise, not be swallowed into a success.

    Regression guard: Item.delete used ``handler=lambda x, y: None`` which
    discarded the response, so a failed delete looked like a success.
    """
    item_area, _ = _make_item_area(
        status=404, data=b'{"error":"not_found","error_description":"Object not found"}'
    )

    with pytest.raises(TransportException):
        item_area.delete(item_id=12345, silent=True, hook=False)


def test_delete_success_does_not_raise():
    """A 204 No Content is a successful delete and must not raise."""
    item_area, _ = _make_item_area(status=204)

    # Must not raise; a successful delete returns normally.
    item_area.delete(item_id=12345, silent=True, hook=False)


# --- CLI-level regression tests ---


class _FakeItemApi:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def delete(self, item_id, silent=False, hook=True):
        self.calls.append({"item_id": item_id, "silent": silent, "hook": hook})
        if self.error is not None:
            raise self.error
        return {}


class _FakeClient:
    def __init__(self, error=None):
        self.Item = _FakeItemApi(error=error)


def test_cli_delete_reports_failure_without_false_success(monkeypatch):
    """A delete that fails at the API must exit non-zero and never print a
    false 'deleted successfully' / '"deleted": true'."""
    error = TransportException(
        _FakeResponse(404), '{"error":"not_found","error_description":"Object not found"}'
    )
    fake = _FakeClient(error=error)
    monkeypatch.setattr(item, "get_client", lambda: fake)

    result = runner.invoke(item.app, ["delete", "12345", "--silent", "--no-hook"])

    assert result.exit_code != 0
    assert "deleted successfully" not in result.stdout
    assert "deleted successfully" not in result.stderr
    assert '"deleted": true' not in result.stdout
    # The delete was still actually attempted (not short-circuited by the flags).
    assert fake.Item.calls == [{"item_id": 12345, "silent": True, "hook": False}]


def test_cli_delete_threads_flags_to_api(monkeypatch):
    """--silent maps to silent=True and --no-hook maps to hook=False; the HTTP
    DELETE is always issued regardless of the flags."""
    fake = _FakeClient()
    monkeypatch.setattr(item, "get_client", lambda: fake)

    result = runner.invoke(item.app, ["delete", "12345", "--silent", "--no-hook"])

    assert result.exit_code == 0
    assert fake.Item.calls == [{"item_id": 12345, "silent": True, "hook": False}]


def test_cli_delete_plain_issues_delete(monkeypatch):
    """Plain delete (no flags) still issues the delete with default semantics."""
    fake = _FakeClient()
    monkeypatch.setattr(item, "get_client", lambda: fake)

    result = runner.invoke(item.app, ["delete", "12345"])

    assert result.exit_code == 0
    assert fake.Item.calls == [{"item_id": 12345, "silent": False, "hook": True}]
