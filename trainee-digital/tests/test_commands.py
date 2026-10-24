"""Command-contract unit tests for the trainee-digital CLI (offline).

`tasks list`/`tasks get` are exercised against a fake client that returns the
real captured fixture records, so the command/option contract is tested
without a browser or network. `tasks apply` never touches a client -- it is a
refusal stub -- and is tested for the refusal itself.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from trainee_digital_cli import main as main_module
from trainee_digital_cli.main import app
from trainee_digital_cli.parsers import normalize_order, normalize_orders

runner = CliRunner()


def _load_body(name: str):
    import json as _json
    from pathlib import Path

    path = Path(__file__).parent / "fixtures" / name
    payload = _json.loads(path.read_text(encoding="utf-8"))
    return payload["body"]


class FakeClient:
    """Stands in for TraineeDigitalClient with the real captured records."""

    def __init__(self):
        self.orders = normalize_orders(_load_body("orders_list.json"))
        self.detail = normalize_order(_load_body("orders_detail_med-seg.json"))

    def list_tasks(self, limit: int = 100):
        return self.orders[:limit]

    def get_task(self, order_id: str):
        if order_id != self.detail["id"]:
            from cli_tools_shared.exceptions import ClientError

            raise ClientError(f"GET /api/orders/{order_id} failed (HTTP 404)")
        return self.detail

    def close(self):
        pass


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(main_module, "get_client", lambda: client)
    return client


def test_tasks_list_emits_json_array(fake_client):
    result = runner.invoke(app, ["tasks", "list"])
    assert result.exit_code == 0, result.stdout + result.stderr
    rows = json.loads(result.stdout)
    assert isinstance(rows, list)
    assert len(rows) == 6
    assert rows[0]["id"] == "med-seg"
    assert rows[0]["url"] == "https://trainee.digital/orders"


def test_tasks_list_limit(fake_client):
    result = runner.invoke(app, ["tasks", "list", "--limit", "2"])
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert [row["id"] for row in rows] == ["med-seg", "legal-ner"]


def test_tasks_list_filter(fake_client):
    result = runner.invoke(app, ["tasks", "list", "--filter", "category:eq:Audio"])
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert [row["id"] for row in rows] == ["speech-tr"]


def test_tasks_list_rejects_unknown_filter_field(fake_client):
    result = runner.invoke(app, ["tasks", "list", "--filter", "categoryy:eq:Audio"])
    assert result.exit_code == 1
    assert "categoryy" in result.stderr


def test_tasks_list_properties(fake_client):
    result = runner.invoke(app, ["tasks", "list", "--limit", "1", "--properties", "id,pay"])
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert rows == [{"id": "med-seg", "pay": "$0.40"}]


def test_tasks_list_table(fake_client):
    result = runner.invoke(app, ["tasks", "list", "--limit", "2", "--table"])
    assert result.exit_code == 0
    assert "ID" in result.stdout
    assert "Title" in result.stdout
    assert "med-seg" in result.stdout


def test_tasks_get_json(fake_client):
    result = runner.invoke(app, ["tasks", "get", "med-seg"])
    assert result.exit_code == 0
    row = json.loads(result.stdout)
    assert row["id"] == "med-seg"
    assert len(row["guidelines"]) == 4


def test_tasks_get_table(fake_client):
    result = runner.invoke(app, ["tasks", "get", "med-seg", "--table"])
    assert result.exit_code == 0
    assert "guidelines" in result.stdout


def test_tasks_get_missing_order_is_client_error(fake_client):
    result = runner.invoke(app, ["tasks", "get", "nope"])
    assert result.exit_code != 0


def test_tasks_apply_always_refuses():
    result = runner.invoke(app, ["tasks", "apply", "med-seg", "--confirm"])
    assert result.exit_code == 1
    assert "Refusing to apply" in result.stderr


def test_tasks_list_help_exposes_contract_options():
    result = runner.invoke(app, ["tasks", "list", "--help"])
    assert result.exit_code == 0
    for option in ("--table", "--limit", "--filter", "--properties"):
        assert option in result.stdout


def test_tasks_get_help_exposes_table():
    result = runner.invoke(app, ["tasks", "get", "--help"])
    assert result.exit_code == 0
    assert "--table" in result.stdout
