"""Tests for ``freshbooks invoice update --line-amount LINEID=AMOUNT`` (mocked HTTP).

FreshBooks replaces the whole ``lines`` array on an invoice PUT, so the command
must fetch the invoice, rebuild every line with only the named unit_cost
changed, and PUT the full list.
"""
import copy
import json

import pytest
from typer.testing import CliRunner

from freshbooks_cli import client as client_module
from freshbooks_cli.client import FreshBooksClient
from freshbooks_cli.commands import invoice as invoice_commands
from freshbooks_cli.invoice_lines import parse_line_amounts, rebuild_lines
from cli_tools_shared.exceptions import ClientError

runner = CliRunner()


def _line(lineid, name, amount, qty="1", taxed=False):
    return {
        "lineid": lineid,
        "name": name,
        "description": f"desc {lineid}",
        "qty": qty,
        "type": 0,
        "expenseid": 0,
        "unit_cost": {"amount": amount, "code": "USD"},
        "amount": {"amount": "999.00", "code": "USD"},
        "updated": "2026-10-05 21:31:16",
        "invoiceid": 1463865,
        "taxName1": "VAT" if taxed else None,
        "taxAmount1": "5" if taxed else "0",
        "taxName2": None,
        "taxAmount2": "0",
        "modern_project_id": None,
        "modern_time_entries": [],
    }


EXISTING = [
    _line(1, "Article A", "700.00"),
    _line(2, "Article B", "700.00", qty="2", taxed=True),
    _line(3, "Article C", "700.00"),
]


class FakeClient:
    def __init__(self):
        self.lines = copy.deepcopy(EXISTING)
        self.update_calls = []

    def get_invoice(self, invoice_id):
        return {"id": int(invoice_id), "lines": copy.deepcopy(self.lines)}

    def update_invoice(self, **kwargs):
        self.update_calls.append(kwargs)
        for sent in kwargs["lines"] or []:
            for line in self.lines:
                if line["lineid"] == sent["lineid"]:
                    line["unit_cost"] = sent["unit_cost"]
        return {"id": 1463865, "invoice_number": "INV-9", "amount": {"amount": "2100.00"}}


@pytest.fixture
def fake(monkeypatch):
    fc = FakeClient()
    monkeypatch.setattr(invoice_commands, "get_client", lambda: fc)
    return fc


def _run(*args):
    return runner.invoke(invoice_commands.app, ["update", "1463865", *args])


def test_updates_named_line_and_preserves_others(fake):
    result = _run("--line-amount", "2=750.00")
    assert result.exit_code == 0, result.output
    sent = fake.update_calls[0]["lines"]
    assert [l["lineid"] for l in sent] == [1, 2, 3]
    assert sent[1]["unit_cost"] == {"amount": "750.00", "code": "USD"}
    assert sent[1]["qty"] == "2"
    assert sent[1]["taxName1"] == "VAT" and sent[1]["taxAmount1"] == "5"
    for i in (0, 2):
        assert sent[i]["unit_cost"] == {"amount": "700.00", "code": "USD"}
        assert sent[i]["name"] == EXISTING[i]["name"]
        assert sent[i]["description"] == EXISTING[i]["description"]
        assert "taxName1" not in sent[i]
    # computed/read-only fields are never sent back
    assert all("amount" not in l and "updated" not in l for l in sent)


def test_repeatable_and_short_flag(fake):
    result = _run("-l", "1=10", "-l", "3=20.5")
    assert result.exit_code == 0, result.output
    sent = fake.update_calls[0]["lines"]
    assert [l["unit_cost"]["amount"] for l in sent] == ["10", "700.00", "20.5"]


def test_stdout_is_json_with_stored_lines(fake):
    result = runner.invoke(
        invoice_commands.app,
        ["update", "1463865", "--line-amount", "1=800"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout[result.stdout.index("{"):])
    assert payload["number"] == "INV-9"
    assert payload["lines"][0]["unit_cost"]["amount"] == "800"
    assert payload["lines"][1]["unit_cost"]["amount"] == "700.00"


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("9=100", "Unknown line ID"),
        ("1=abc", "must be a number"),
        ("1=0", "greater than zero"),
        ("1=-5", "greater than zero"),
        ("1=nan", "greater than zero"),
        ("1=inf", "greater than zero"),
        ("1", "expected LINEID=AMOUNT"),
        ("=5", "expected LINEID=AMOUNT"),
        ("1=", "expected LINEID=AMOUNT"),
    ],
)
def test_bad_input_fails_without_putting(fake, spec, expected):
    result = _run("--line-amount", spec)
    assert result.exit_code == 1
    assert expected in result.output
    assert fake.update_calls == []


def test_duplicate_lineid_rejected(fake):
    result = _run("-l", "1=5", "-l", "1=6")
    assert result.exit_code == 1
    assert "Duplicate" in result.output
    assert fake.update_calls == []


def test_parse_line_amounts():
    assert parse_line_amounts(["1=750.00", " 2 = 5 "]) == {"1": "750.00", "2": "5"}


def test_rebuild_lines_keeps_project_fields_when_set():
    line = _line(1, "X", "5")
    line["modern_project_id"] = 42
    line["modern_time_entries"] = [{"id": 7}]
    out = rebuild_lines([line], {"1": "6"})[0]
    assert out["modern_project_id"] == 42
    assert out["modern_time_entries"] == [{"id": 7}]
    with pytest.raises(ClientError):
        rebuild_lines([line], {"2": "6"})


def test_client_update_invoice_puts_full_lines_payload(monkeypatch):
    class Cfg:
        access_token = "t"
        account_id = "acct"
        client_id = "c"
        client_secret = "s"
        refresh_token = "r"
        redirect_uri = None
        token_expires_at = "99999999999"

        def get_missing_credentials(self):
            return []

    monkeypatch.setattr(client_module, "get_config", lambda: Cfg())
    seen = {}

    class Resp:
        status_code = 200
        ok = True
        headers = {}
        text = ""

        def json(self):
            return {"response": {"result": {"invoice": {"id": 1}}}}

    def fake_request(method, url, **kwargs):
        seen.update(method=method, url=url, json=kwargs["json"])
        return Resp()

    monkeypatch.setattr(client_module.requests, "request", fake_request)
    lines = rebuild_lines(copy.deepcopy(EXISTING), {"1": "750"})
    FreshBooksClient().update_invoice("1463865", lines=lines)
    assert seen["method"] == "PUT"
    assert seen["url"].endswith("/accounting/account/acct/invoices/invoices/1463865")
    assert seen["json"] == {"invoice": {"lines": lines}}
