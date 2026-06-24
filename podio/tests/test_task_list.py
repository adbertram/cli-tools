"""Tests for `podio task list` server-side filter assembly.

These verify that the CLI flags reach the Podio GET /task/ transport call as the
exact query parameters Podio expects, and that the security-scope default
(responsible=0) is applied only when no scope flag was supplied.
"""
from unittest.mock import MagicMock

from typer.testing import CliRunner

from podio_cli.commands import task


runner = CliRunner()


def _make_client():
    """Return a fake client whose transport.GET records its call and returns []."""
    client = MagicMock()
    client.transport.GET.return_value = []
    return client


def _get_kwargs(client):
    """Return the kwargs passed to client.transport.GET for assertions."""
    assert client.transport.GET.called, "transport.GET was not called"
    _, kwargs = client.transport.GET.call_args
    return kwargs


def test_reference_reaches_query_without_responsible(monkeypatch):
    client = _make_client()
    monkeypatch.setattr(task, "get_client", lambda: client)

    result = runner.invoke(task.app, ["list", "--reference", "item:123"])

    assert result.exit_code == 0
    kwargs = _get_kwargs(client)
    assert kwargs["url"] == "/task/"
    assert kwargs["reference"] == "item:123"
    assert "responsible" not in kwargs


def test_created_by_reaches_query_without_responsible(monkeypatch):
    client = _make_client()
    monkeypatch.setattr(task, "get_client", lambda: client)

    result = runner.invoke(task.app, ["list", "--created-by", "user:77109345"])

    assert result.exit_code == 0
    kwargs = _get_kwargs(client)
    # Passed through verbatim; Podio requires the user:<id> reference form.
    assert kwargs["created_by"] == "user:77109345"
    assert "responsible" not in kwargs


def test_bare_list_defaults_to_current_user(monkeypatch):
    client = _make_client()
    monkeypatch.setattr(task, "get_client", lambda: client)

    result = runner.invoke(task.app, ["list"])

    assert result.exit_code == 0
    kwargs = _get_kwargs(client)
    assert kwargs["responsible"] == 0


def test_responsible_flag_overrides_default(monkeypatch):
    client = _make_client()
    monkeypatch.setattr(task, "get_client", lambda: client)

    result = runner.invoke(task.app, ["list", "--responsible", "77109340"])

    assert result.exit_code == 0
    kwargs = _get_kwargs(client)
    assert kwargs["responsible"] == 77109340


def test_invalid_reference_exits_2_without_network_call(monkeypatch):
    client = _make_client()
    monkeypatch.setattr(task, "get_client", lambda: client)

    result = runner.invoke(task.app, ["list", "--reference", "foo"])

    assert result.exit_code == 2
    assert not client.transport.GET.called


def test_additional_scope_flags_reach_query(monkeypatch):
    client = _make_client()
    monkeypatch.setattr(task, "get_client", lambda: client)

    result = runner.invoke(
        task.app,
        [
            "list",
            "--external-id", "ext-9",
            "--org", "56789",
            "--app", "24681012",
        ],
    )

    assert result.exit_code == 0
    kwargs = _get_kwargs(client)
    assert kwargs["external_id"] == "ext-9"
    assert kwargs["org"] == 56789
    assert kwargs["app"] == 24681012
    # A scope flag (org/app) is present, so the current-user default must NOT apply.
    assert "responsible" not in kwargs
