import json

from typer.testing import CliRunner

from airtable_cli.commands import fields


runner = CliRunner()


class FakeClient:
    def list_fields(self, base_id, table_id):
        assert base_id == "appBase"
        assert table_id == "tblSlides"
        return [
            {
                "id": "fldCueStatus",
                "name": "Review Status",
                "type": "formula",
                "options": {
                    "formula": "IF({Approved}, 'Approved', 'Needs Review')"
                },
            }
        ]


def test_fields_list_returns_schema_fields(monkeypatch):
    monkeypatch.setattr(fields, "resolve_base_id", lambda base_id: "appBase")
    monkeypatch.setattr(fields, "get_client", lambda: FakeClient())

    result = runner.invoke(fields.app, ["list", "tblSlides"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {
            "id": "fldCueStatus",
            "name": "Review Status",
            "type": "formula",
            "options": {
                "formula": "IF({Approved}, 'Approved', 'Needs Review')"
            },
        }
    ]


def test_fields_delete_fails_clearly_without_api_call(monkeypatch):
    monkeypatch.setattr(fields, "resolve_base_id", lambda base_id: "appBase")
    monkeypatch.setattr(fields, "get_client", lambda: (_ for _ in ()).throw(AssertionError("client should not be used")))

    result = runner.invoke(fields.app, ["delete", "tblSlides", "fldObsolete", "--yes"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Airtable's public Web/Meta API does not support deleting fields." in result.stderr
    assert "airtable fields list --filter name:eq:<field name>" in result.stderr


def test_fields_delete_does_not_prompt_without_confirmation(monkeypatch):
    monkeypatch.setattr(fields, "resolve_base_id", lambda base_id: "appBase")
    monkeypatch.setattr(fields, "get_client", lambda: (_ for _ in ()).throw(AssertionError("client should not be used")))

    result = runner.invoke(fields.app, ["delete", "tblSlides", "fldObsolete"])

    assert result.exit_code == 1
    assert "Are you sure you want to delete field fldObsolete from table tblSlides?" not in result.stdout
    assert "Airtable's public Web/Meta API does not support deleting fields." in result.stderr
