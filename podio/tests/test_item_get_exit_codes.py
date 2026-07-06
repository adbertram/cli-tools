"""Regression tests for `podio item get` exit behavior."""

from typer.testing import CliRunner

from podio_cli.commands import item


runner = CliRunner()


class _FakeItemApi:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def find(self, item_id, basic=False):
        if self.error is not None:
            raise self.error
        return self.result


class _FakeClient:
    def __init__(self, result=None, error=None):
        self.Item = _FakeItemApi(result=result, error=error)


def test_item_get_api_error_exits_nonzero_with_empty_stdout(monkeypatch):
    error = Exception("Item has been deleted")
    monkeypatch.setattr(item, "get_client", lambda: _FakeClient(error=error))

    result = runner.invoke(item.app, ["get", "3330529630"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Error: API error: Item has been deleted" in result.stderr


def test_item_get_success_preserves_json_stdout(monkeypatch):
    monkeypatch.setattr(
        item,
        "get_client",
        lambda: _FakeClient(result={"item_id": 123, "title": "Example"}),
    )

    result = runner.invoke(item.app, ["get", "123"])

    assert result.exit_code == 0
    assert result.stderr == ""
    assert '"item_id": 123' in result.stdout
    assert '"title": "Example"' in result.stdout
