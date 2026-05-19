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
