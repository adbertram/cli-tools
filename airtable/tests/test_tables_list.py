import json

from typer.testing import CliRunner

from airtable_cli.commands import tables


runner = CliRunner()


class FakeTablesClient:
    def list_tables(self, base_id):
        assert base_id == "appBase"
        return [
            {
                "id": "tblDeals",
                "name": "Deals",
                "primaryFieldId": "fldName",
                "description": "Pipeline deals",
                "fields": [
                    {"id": "fldName", "name": "Name"},
                    {"id": "fldStatus", "name": "Writer Success Manager"},
                ],
                "views": [{"id": "viwAll", "name": "All"}],
            }
        ]


def test_tables_list_returns_summary_objects(monkeypatch):
    monkeypatch.setattr(tables, "resolve_base_id", lambda base_id: "appBase")
    monkeypatch.setattr(tables, "get_client", lambda: FakeTablesClient())

    result = runner.invoke(tables.app, ["list"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {
            "id": "tblDeals",
            "name": "Deals",
            "primaryFieldId": "fldName",
            "description": "Pipeline deals",
            "field_count": 2,
        }
    ]


def test_tables_list_properties_filters_summary_output(monkeypatch):
    monkeypatch.setattr(tables, "resolve_base_id", lambda base_id: "appBase")
    monkeypatch.setattr(tables, "get_client", lambda: FakeTablesClient())

    result = runner.invoke(tables.app, ["list", "--properties", "id,name"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [{"id": "tblDeals", "name": "Deals"}]
